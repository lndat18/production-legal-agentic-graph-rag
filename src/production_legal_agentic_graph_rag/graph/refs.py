"""Trích và phân giải viện dẫn nội bộ bằng quy tắc xác định (graph_spec.md mục 7).

Ưu tiên precision hơn recall: viện dẫn ngoại hoặc mơ hồ bị bỏ (chỉ đếm), chỉ
tạo cạnh khi đích tồn tại thật trong cùng văn bản. Không dùng LLM.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from production_legal_agentic_graph_rag.graph.builder import split_points
from production_legal_agentic_graph_rag.graph.models import (
    ArticleNode,
    ClauseNode,
    DocumentKind,
    GraphDocument,
    NodeLabel,
    PointNode,
    ReferenceEdge,
    ReferenceKind,
    ReferenceStats,
)

_OPEN_QUOTE = "“"
_CLOSE_QUOTE = "”"

_NUM = r"\d+[a-zđ]?(?!\w)"
_LETTER = r"[a-zđ](?!\w)"
_SEP = r"(?:\s*,\s*(?:và\s+|hoặc\s+)?|\s+(?:và|hoặc)\s+)"
_DOCUMENT_WORDS = r"(?:Bộ luật|Luật|Nghị định|Thông tư|Pháp lệnh|Nghị quyết|Quyết định)"

_RE_REFERENCE = re.compile(
    rf"""
    (?:
        (?:(?:[Cc]ác\s+)?[Đđ]iểm\s+(?P<points>{_LETTER}(?:{_SEP}(?:điểm\s+)?{_LETTER})*)\s+)?
        (?:[Cc]ác\s+)?[Kk]hoản\s+(?P<clauses>{_NUM}(?:{_SEP}(?:khoản\s+)?{_NUM})*)
        \s+(?:của\s+)?
    )?
    (?:
        (?:[Tt]ừ\s+)?Điều\s+(?P<range_from>{_NUM})\s+(?:đến|tới)\s+(?:hết\s+)?Điều\s+(?P<range_to>{_NUM})
        |
        (?:[Cc]ác\s+)?Điều\s+(?P<articles>{_NUM}(?:{_SEP}(?:Điều\s+)?{_NUM})*)
        |
        Điều\s+(?P<this_article>này)(?!\w)
    )
    """,
    re.VERBOSE,
)
_RE_THIS_DOCUMENT = re.compile(rf"\s+(?:của\s+)?{_DOCUMENT_WORDS}\s+này(?!\w)")
_RE_OTHER_DOCUMENT = re.compile(
    rf"(?<!\w){_DOCUMENT_WORDS}(?!\s+này)(?!\w)|\d+/\d{{4}}/[\wĐ-]+"
)
_RE_SENTENCE_BREAK = re.compile(r"(?<=\.)\s+|\n")
_RE_NUMBER_LABEL = re.compile(_NUM)
_RE_POINT_LABEL = re.compile(rf"(?<!\w){_LETTER}")


class ExtractedReference(BaseModel):
    """Một viện dẫn trích từ text, chưa phân giải."""

    raw_text: str
    is_range: bool = False
    this_article: bool = False
    article_labels: list[str] = Field(default_factory=list)
    clause_labels: list[str] = Field(default_factory=list)
    point_labels: list[str] = Field(default_factory=list)
    explicit_internal: bool = False
    other_document_in_sentence: bool = False


def mask_quoted_text(text: str) -> str:
    """Thay nội dung trong ngoặc kép trích dẫn bằng khoảng trắng (giữ nguyên độ dài).

    Đoạn trích nguyên văn luật khác có viện dẫn thuộc văn bản được trích,
    không phải văn bản đang xử lý.
    """
    depth = 0
    chars: list[str] = []
    for char in text:
        if char == _OPEN_QUOTE:
            depth += 1
            chars.append(" ")
        elif char == _CLOSE_QUOTE:
            depth = max(depth - 1, 0)
            chars.append(" ")
        else:
            chars.append(" " if depth > 0 and char != "\n" else char)
    return "".join(chars)


def _sentence_spans(text: str) -> list[tuple[int, int, bool]]:
    """Danh sách (start, end, có_nêu_văn_bản_khác) của từng câu."""
    spans: list[tuple[int, int, bool]] = []
    start = 0
    for match in [*_RE_SENTENCE_BREAK.finditer(text), None]:
        end = match.start() if match else len(text)
        spans.append((start, end, bool(_RE_OTHER_DOCUMENT.search(text, start, end))))
        if match:
            start = match.end()
    return spans


def extract_references(text: str) -> list[ExtractedReference]:
    """Trích mọi viện dẫn dạng `[điểm …] [khoản …] Điều …` trong text.

    Nội dung trong ngoặc kép trích dẫn bị bỏ qua. `other_document_in_sentence`
    đánh dấu câu có nêu tên/số hiệu văn bản khác (mục 7, bước 1).

    Args:
        text: Text của một Khoản (phần câu dẫn) hoặc một Điểm.

    Returns:
        Danh sách viện dẫn theo thứ tự xuất hiện.
    """
    masked = mask_quoted_text(text)
    sentences = _sentence_spans(masked)
    references: list[ExtractedReference] = []
    for match in _RE_REFERENCE.finditer(masked):
        suffix = _RE_THIS_DOCUMENT.match(masked, match.end())
        end = suffix.end() if suffix else match.end()
        other = any(
            start <= match.start() < stop and flag for start, stop, flag in sentences
        )
        references.append(
            ExtractedReference(
                raw_text=" ".join(masked[match.start() : end].split()),
                is_range=match.group("range_from") is not None,
                this_article=match.group("this_article") is not None,
                article_labels=(
                    [match.group("range_from"), match.group("range_to")]
                    if match.group("range_from")
                    else _RE_NUMBER_LABEL.findall(match.group("articles") or "")
                ),
                clause_labels=_RE_NUMBER_LABEL.findall(match.group("clauses") or ""),
                point_labels=_RE_POINT_LABEL.findall(match.group("points") or ""),
                explicit_internal=suffix is not None
                or match.group("this_article") is not None,
                other_document_in_sentence=other,
            )
        )
    return references


class _Index:
    """Tra cứu đích theo nhãn trong một văn bản."""

    def __init__(self, graph: GraphDocument) -> None:
        self.articles = graph.articles
        self.article_by_label = {article.label: article for article in graph.articles}
        self.article_position = {
            article.label: position for position, article in enumerate(graph.articles)
        }
        self.clause_by_key: dict[tuple[str, str], ClauseNode] = {}
        for clause in graph.clauses:
            if clause.label is not None:
                self.clause_by_key[(clause.parent_id, clause.label)] = clause
        self.points_by_key: dict[tuple[str, str], list[PointNode]] = {}
        for point in graph.points:
            self.points_by_key.setdefault((point.parent_id, point.label), []).append(
                point
            )


class _Source(BaseModel):
    node_label: NodeLabel
    node_id: str
    article: ArticleNode
    ancestor_ids: set[str]


def _targets(
    reference: ExtractedReference, source: _Source, index: _Index, stats: ReferenceStats
) -> list[tuple[NodeLabel, str, ReferenceKind]]:
    """Đích tồn tại của một viện dẫn; đích không có thật được đếm, không tạo cạnh."""
    if reference.is_range:
        first, last = reference.article_labels
        positions = index.article_position
        if (
            first not in positions
            or last not in positions
            or (positions[first] > positions[last])
        ):
            stats.unresolved_target += 1
            return []
        return [
            (NodeLabel.ARTICLE, article.id, ReferenceKind.RANGE)
            for article in index.articles[positions[first] : positions[last] + 1]
        ]
    labels = (
        [source.article.label] if reference.this_article else reference.article_labels
    )
    # "khoản 1 Điều 43 và Điều 44" không nói rõ khoản áp dụng cho Điều nào: không đoán.
    if reference.clause_labels and len(labels) > 1:
        stats.unresolved_target += 1
        return []
    targets: list[tuple[NodeLabel, str, ReferenceKind]] = []
    for label in labels:
        article = index.article_by_label.get(label)
        if article is None:
            stats.unresolved_target += 1
        elif not reference.clause_labels:
            targets.append((NodeLabel.ARTICLE, article.id, ReferenceKind.SINGLE))
        else:
            targets.extend(_clause_targets(reference, article, index, stats))
    return targets


def _clause_targets(
    reference: ExtractedReference,
    article: ArticleNode,
    index: _Index,
    stats: ReferenceStats,
) -> list[tuple[NodeLabel, str, ReferenceKind]]:
    # "điểm a khoản 1 và khoản 2" không nói rõ điểm thuộc khoản nào: không đoán.
    if reference.point_labels and len(reference.clause_labels) > 1:
        stats.unresolved_target += 1
        return []
    targets: list[tuple[NodeLabel, str, ReferenceKind]] = []
    for clause_label in reference.clause_labels:
        clause = index.clause_by_key.get((article.id, clause_label))
        if clause is None:
            stats.unresolved_target += 1
        elif not reference.point_labels:
            targets.append((NodeLabel.CLAUSE, clause.id, ReferenceKind.SINGLE))
        else:
            for point_label in reference.point_labels:
                points = index.points_by_key.get((clause.id, point_label), [])
                # Nhãn Điểm trùng trong một Khoản là mơ hồ: không đoán (mục 3).
                if len(points) == 1:
                    targets.append(
                        (NodeLabel.POINT, points[0].id, ReferenceKind.SINGLE)
                    )
                else:
                    stats.unresolved_target += 1
    return targets


def _resolve_text(
    text: str,
    source: _Source,
    kind: DocumentKind,
    index: _Index,
    stats: ReferenceStats,
) -> list[ReferenceEdge]:
    edges: list[ReferenceEdge] = []
    for reference in extract_references(text):
        if not reference.explicit_internal:
            if reference.other_document_in_sentence:
                stats.external += 1
                continue
            if kind is DocumentKind.HUONG_DAN:
                stats.bare_huong_dan += 1
                continue
        for target_label, target_id, ref_kind in _targets(
            reference, source, index, stats
        ):
            if target_id == source.node_id or target_id in source.ancestor_ids:
                stats.self_skipped += 1
                continue
            edges.append(
                ReferenceEdge(
                    source_label=source.node_label,
                    source_id=source.node_id,
                    target_label=target_label,
                    target_id=target_id,
                    raw_text=reference.raw_text,
                    kind=ref_kind,
                )
            )
    return edges


def resolve_references(
    graph: GraphDocument,
) -> tuple[list[ReferenceEdge], ReferenceStats]:
    """Trích và phân giải viện dẫn của mọi Khoản/Điểm trong `graph` (mục 7).

    Cạnh đi từ node nhỏ nhất chứa viện dẫn: câu dẫn của Khoản (phần trước
    Điểm đầu tiên) thuộc Khoản, text mỗi Điểm thuộc Điểm đó. Cạnh trùng
    (cùng nguồn, cùng đích) chỉ giữ lần đầu.

    Args:
        graph: Graph của một văn bản đã có hierarchy (chưa có cạnh viện dẫn).

    Returns:
        (danh sách cạnh `REFERS_TO`, bộ đếm các ca bị loại).
    """
    index = _Index(graph)
    article_by_id = {article.id: article for article in graph.articles}
    clause_by_id = {clause.id: clause for clause in graph.clauses}
    stats = ReferenceStats()
    edges: list[ReferenceEdge] = []
    seen: set[tuple[str, str]] = set()
    kind = graph.document.kind

    def collect(source: _Source, text: str) -> None:
        for edge in _resolve_text(text, source, kind, index, stats):
            key = (edge.source_id, edge.target_id)
            if key not in seen:
                seen.add(key)
                edges.append(edge)

    for clause in graph.clauses:
        article = article_by_id[clause.parent_id]
        lead_in, _ = split_points(clause.text)
        collect(
            _Source(
                node_label=NodeLabel.CLAUSE,
                node_id=clause.id,
                article=article,
                ancestor_ids={article.id},
            ),
            lead_in,
        )
    for point in graph.points:
        clause = clause_by_id[point.parent_id]
        article = article_by_id[clause.parent_id]
        collect(
            _Source(
                node_label=NodeLabel.POINT,
                node_id=point.id,
                article=article,
                ancestor_ids={clause.id, article.id},
            ),
            point.text,
        )
    return edges, stats
