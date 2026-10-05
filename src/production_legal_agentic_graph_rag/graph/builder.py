"""Dựng `GraphDocument` từ `DocumentTree` + chunk JSON + heading markdown (mục 4, 5).

`DocumentTree` của `chunking/` giữ breadcrumb dạng chuỗi và bỏ mất tiêu đề
Chương/Mục, nên builder quét thêm heading cấu trúc từ chính markdown (cùng
regex công khai của `chunking.patterns`) để có tiêu đề và thứ tự cấu trúc,
rồi gióng từng `KhoanNode` vào Điều tương ứng theo thứ tự xuất hiện. Không
sửa và không tính lại công thức `chunk_id` của `chunking/`.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from pydantic import BaseModel

from production_legal_agentic_graph_rag.chunking.models import Chunk, DocumentTree
from production_legal_agentic_graph_rag.chunking.patterns import (
    RE_BACKMATTER_SEPARATOR,
    RE_CHUONG,
    RE_DIEM,
    RE_DIEU,
    RE_HEADING,
    RE_MUC,
    RE_PHAN,
    is_structural_heading,
)
from production_legal_agentic_graph_rag.graph.models import (
    ArticleNode,
    ClauseNode,
    DocumentKind,
    DocumentNode,
    GraphDocument,
    NodeLabel,
    PointNode,
    StructureNode,
)

# Trùng với hằng số của `chunking/pipeline.py` (private ở đó, không sửa chunking).
BACKMATTER_SUFFIX = "Chú thích sửa đổi (cuối văn bản)"
REPEALED_TEXT = "(được bãi bỏ)"

_RE_BLOCK_SPLIT = re.compile(r"\n{2,}")
_RE_CHUNK_SUFFIX = re.compile(r"(?: - Điểm [^()]+)?(?: \(phần \d+/\d+\))?$")
_RE_PREFIX_TAIL = re.compile(
    r"^(?:Phần \S+ - )?(?:Chương \S+ - )?(?:Mục \S+ - )?"
    r"(?:Điều (?P<label>\d+[a-zđ]?)(?:\. .*)?)?$",
    re.DOTALL,
)
_RE_TITLE_LEAD = re.compile(r"^[\s.:\-–]+")
_RE_LEADING_NUMBER = re.compile(r"^(\d+)")

_ORDINAL_WORDS = {
    "nhất": 1,
    "hai": 2,
    "ba": 3,
    "tư": 4,
    "bốn": 4,
    "năm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
    "mười": 10,
}
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_OPEN_QUOTE = "“"
_CLOSE_QUOTE = "”"


class GraphBuildError(ValueError):
    """Lỗi dựng graph của một văn bản; thông điệp chỉ chứa định danh, không chứa nội dung."""


class StructureHeading(BaseModel):
    """Heading Phần/Chương/Mục/Điều quét từ markdown, theo thứ tự xuất hiện."""

    node_label: NodeLabel
    label: str
    title: str


def classify_document_kind(source_document: str) -> DocumentKind:
    """Suy `kind` từ tên văn bản bằng quy tắc xác định (mục 6).

    Raises:
        GraphBuildError: Tên không bắt đầu bằng Luật/Bộ luật/Nghị định/Thông tư.
    """
    name = source_document.strip().casefold()
    if name.startswith(("luật", "bộ luật")):
        return DocumentKind.GOC
    if name.startswith(("nghị định", "thông tư")):
        return DocumentKind.HUONG_DAN
    raise GraphBuildError("Không phân loại được kind (goc/huong_dan) từ tên văn bản")


def _roman_to_int(text: str) -> int:
    total = 0
    values = [_ROMAN_VALUES[char] for char in text]
    for index, value in enumerate(values):
        if index + 1 < len(values) and value < values[index + 1]:
            total -= value
        else:
            total += value
    return total


def _label_to_number(label: str) -> int:
    """Đổi nhãn Phần/Chương/Mục (La Mã, số, chữ tiếng Việt) sang int."""
    digits = _RE_LEADING_NUMBER.match(label)
    if digits:
        return int(digits.group(1))
    if label.upper() == label and all(char in _ROMAN_VALUES for char in label):
        return _roman_to_int(label)
    number = _ORDINAL_WORDS.get(label.casefold())
    if number is None:
        raise GraphBuildError(f"Không đổi được nhãn cấu trúc {label!r} sang số")
    return number


def _split_title(rest: str) -> str:
    return _RE_TITLE_LEAD.sub("", rest).strip()


def _heading_from_text(level: int, text: str) -> StructureHeading:
    """Phân loại một heading cấp 1-4 thành Phần/Chương/Mục/Điều.

    Raises:
        GraphBuildError: Heading không có node tương ứng (vd. Phụ lục), mục 8.
    """
    if level == 1 and (match := RE_PHAN.match(text)):
        label, label_type = match.group(1), NodeLabel.PART
    elif level == 2 and (match := RE_CHUONG.match(text)):
        label, label_type = match.group(1), NodeLabel.CHAPTER
    elif level == 3 and (match := RE_MUC.match(text)):
        label, label_type = match.group(1), NodeLabel.SECTION
    elif level == 4 and (dieu := RE_DIEU.match(text)):
        return StructureHeading(
            node_label=NodeLabel.ARTICLE,
            label=dieu.group(1),
            title=dieu.group(2).strip(),
        )
    else:
        raise GraphBuildError(
            f"Heading cấp {level} không có node tương ứng trong graph (vd. Phụ lục)"
        )
    return StructureHeading(
        node_label=label_type,
        label=label,
        title=_split_title(text[match.end() :]),
    )


def scan_structure_headings(markdown_text: str) -> list[StructureHeading]:
    """Quét heading Phần/Chương/Mục/Điều theo đúng cách `chunking.parser` chia block.

    Bỏ vùng frontmatter (trước heading cấu trúc đầu tiên) và backmatter (sau
    dòng `---`); heading cấp 5 (Khoản) không thuộc phạm vi quét.

    Args:
        markdown_text: Nội dung file markdown của `formatting/`.

    Returns:
        Danh sách heading theo thứ tự xuất hiện.
    """
    blocks = [
        block.strip() for block in _RE_BLOCK_SPLIT.split(markdown_text) if block.strip()
    ]
    headings: list[StructureHeading] = []
    started = False
    for block in blocks:
        match = RE_HEADING.match(block)
        if match is None:
            if started and RE_BACKMATTER_SEPARATOR.match(block):
                break
            continue
        level, text = len(match.group(1)), match.group(2).strip()
        if not started:
            started = is_structural_heading(level, text)
            if not started:
                continue
        if level == 5:
            continue
        headings.append(_heading_from_text(level, text))
    return headings


def split_points(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Tách text Khoản thành (câu dẫn, [(nhãn Điểm, text Điểm)]) (mục 5).

    Dòng `a)`, `b)`… chỉ là Điểm khi nằm ngoài ngoặc kép trích dẫn: nội dung
    trích nguyên văn từ luật khác không phải cấu trúc của văn bản này.
    """
    lead_lines: list[str] = []
    points: list[tuple[str, list[str]]] = []
    depth = 0
    for line in text.split("\n"):
        stripped = line.strip()
        match = RE_DIEM.match(stripped) if depth == 0 else None
        if match:
            points.append((match.group(1), [stripped]))
        elif points:
            points[-1][1].append(stripped)
        else:
            lead_lines.append(stripped)
        depth = max(depth + line.count(_OPEN_QUOTE) - line.count(_CLOSE_QUOTE), 0)
    lead_in = "\n".join(lead_lines).strip()
    return lead_in, [(label, "\n".join(lines).strip()) for label, lines in points]


def _strip_chunk_suffix(breadcrumb: str) -> str:
    return _RE_CHUNK_SUFFIX.sub("", breadcrumb)


def article_label_of_prefix(prefix: str, source_document: str) -> str:
    """Nhãn Điều của một `breadcrumb_prefix`.

    Raises:
        GraphBuildError: Khoản không nằm dưới Điều nào (vd. Phụ lục).
    """
    head = f"{source_document} - "
    if not prefix.startswith(head):
        raise GraphBuildError("Khoản ngoài cấu trúc Điều (breadcrumb không có Điều)")
    match = _RE_PREFIX_TAIL.match(prefix[len(head) :])
    if match is None or match.group("label") is None:
        raise GraphBuildError("Khoản ngoài cấu trúc Điều (vd. Phụ lục), không có node")
    return str(match.group("label"))


class _Skeleton:
    """Node cấu trúc + Điều dựng từ heading, kèm ngăn xếp cha hiện tại."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.structures: list[StructureNode] = []
        self.articles: list[ArticleNode] = []
        self._child_count: dict[str, int] = defaultdict(int)
        self._open: dict[NodeLabel, StructureNode] = {}

    def _next_order(self, parent_id: str) -> int:
        self._child_count[parent_id] += 1
        return self._child_count[parent_id]

    def _parent_for(self, label: NodeLabel) -> str:
        ancestors = {
            NodeLabel.PART: (),
            NodeLabel.CHAPTER: (NodeLabel.PART,),
            NodeLabel.SECTION: (NodeLabel.CHAPTER, NodeLabel.PART),
            NodeLabel.ARTICLE: (NodeLabel.SECTION, NodeLabel.CHAPTER, NodeLabel.PART),
        }[label]
        for ancestor in ancestors:
            if ancestor in self._open:
                return self._open[ancestor].id
        return self.doc_id

    def add(self, heading: StructureHeading) -> None:
        parent_id = self._parent_for(heading.node_label)
        order = self._next_order(parent_id)
        if heading.node_label is NodeLabel.ARTICLE:
            self.articles.append(
                ArticleNode(
                    id=f"{self.doc_id}/dieu-{heading.label}",
                    order=order,
                    parent_id=parent_id,
                    label=heading.label,
                    title=heading.title,
                )
            )
            return
        node_label = heading.node_label
        node = StructureNode(
            node_label=node_label,  # type: ignore[arg-type]  # đã lọc ở nhánh trên
            id=f"{parent_id}/{node_label.value.lower()}-{order}",
            order=order,
            parent_id=parent_id,
            number=_label_to_number(heading.label),
            label=heading.label,
            title=heading.title,
        )
        self.structures.append(node)
        self._open[node_label] = node
        # Mở cấp cha thì đóng các cấp con còn mở (Chương mới đóng Mục cũ).
        order_of_levels = [NodeLabel.PART, NodeLabel.CHAPTER, NodeLabel.SECTION]
        for deeper in order_of_levels[order_of_levels.index(node_label) + 1 :]:
            self._open.pop(deeper, None)

    def ensure_unique_articles(self) -> None:
        """Số Điều là khoá tra cứu trong văn bản nên không được trùng (mục 4)."""
        labels = [article.label for article in self.articles]
        duplicated = sorted({label for label in labels if labels.count(label) > 1})
        if duplicated:
            raise GraphBuildError(f"Số Điều trùng trong một văn bản: {duplicated}")


def _build_skeleton(doc_id: str, headings: list[StructureHeading]) -> _Skeleton:
    skeleton = _Skeleton(doc_id)
    for heading in headings:
        skeleton.add(heading)
    skeleton.ensure_unique_articles()
    return skeleton


def _assign_khoans_to_articles(
    tree: DocumentTree, articles: list[ArticleNode]
) -> list[ArticleNode]:
    """Gióng từng Khoản vào Điều theo thứ tự xuất hiện (heading và Khoản cùng thứ tự)."""
    cursor = 0
    assigned: list[ArticleNode] = []
    for khoan in tree.khoans:
        label = article_label_of_prefix(khoan.breadcrumb_prefix, tree.source_document)
        if cursor >= len(articles) or articles[cursor].label != label:
            found = next(
                (
                    index
                    for index in range(cursor + 1, len(articles))
                    if articles[index].label == label
                ),
                None,
            )
            if found is None:
                raise GraphBuildError(
                    f"Khoản thuộc Điều {label} không gióng được vào heading markdown"
                    " (markdown và DocumentTree lệch nhau)"
                )
            cursor = found
        assigned.append(articles[cursor])
    return assigned


def _match_chunks(
    tree: DocumentTree, chunks: list[Chunk]
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Gom `chunk_id` theo breadcrumb gốc: (theo khoá Khoản, front, back) (mục 5)."""
    ordered = sorted(
        enumerate(chunks), key=lambda item: (item[1].split_index or 0, item[0])
    )
    by_base: dict[str, list[str]] = defaultdict(list)
    for _, chunk in ordered:
        by_base[_strip_chunk_suffix(chunk.breadcrumb)].append(chunk.chunk_id)
    front = by_base.pop(tree.source_document, [])
    back = by_base.pop(f"{tree.source_document} - {BACKMATTER_SUFFIX}", [])
    return by_base, front, back


def _build_clauses_and_points(
    tree: DocumentTree,
    owners: list[ArticleNode],
    chunk_ids_by_base: dict[str, list[str]],
) -> tuple[list[ClauseNode], list[PointNode]]:
    clauses: list[ClauseNode] = []
    points: list[PointNode] = []
    order_in_article: dict[str, int] = defaultdict(int)
    seen_ids: set[str] = set()
    for khoan, article in zip(tree.khoans, owners, strict=True):
        if khoan.khoan_number is None:
            base, suffix = khoan.breadcrumb_prefix, "implicit"
        else:
            base = f"{khoan.breadcrumb_prefix} - Khoản {khoan.khoan_number}"
            suffix = khoan.khoan_number
        clause_id = f"{article.id}/khoan-{suffix}"
        chunk_ids = chunk_ids_by_base.pop(base, [])
        if clause_id in seen_ids:
            raise GraphBuildError(f"Khoản trùng id {clause_id!r}")
        if not chunk_ids:
            raise GraphBuildError(f"Khoản {clause_id!r} không có chunk nào khớp")
        seen_ids.add(clause_id)
        order_in_article[article.id] += 1
        clauses.append(
            ClauseNode(
                id=clause_id,
                order=order_in_article[article.id],
                parent_id=article.id,
                label=khoan.khoan_number,
                text=khoan.content,
                chunk_ids=chunk_ids,
                implicit=khoan.khoan_number is None,
                has_table=khoan.has_table,
                raw_table=khoan.raw_table,
            )
        )
        points.extend(_build_points(clauses[-1]))
    return clauses, points


def _build_points(clause: ClauseNode) -> list[PointNode]:
    _, raw_points = split_points(clause.text)
    labels = [label for label, _ in raw_points]
    return [
        PointNode(
            id=(
                f"{clause.id}/diem-{label}"
                if labels.count(label) == 1
                else f"{clause.id}/diem-{label}-{order}"
            ),
            order=order,
            parent_id=clause.id,
            label=label,
            text=text,
        )
        for order, (label, text) in enumerate(raw_points, start=1)
    ]


def _fill_char_counts(graph: GraphDocument) -> None:
    """`char_count` = tổng ký tự toàn văn (text + bảng) của mọi Khoản con (mục 4)."""
    parent_by_id = {
        node.id: node.parent_id for node in graph.units() if node.parent_id is not None
    }
    by_id: dict[str, StructureNode | ArticleNode] = {
        node.id: node for node in graph.units()
    }
    for clause in graph.clauses:
        size = len(clause.text) + len(clause.raw_table or "")
        ancestor: str | None = clause.parent_id
        while ancestor is not None and ancestor in by_id:
            by_id[ancestor].char_count += size
            ancestor = parent_by_id.get(ancestor)


def build_graph_document(
    tree: DocumentTree,
    chunks: list[Chunk],
    headings: list[StructureHeading],
    short_name: str,
) -> GraphDocument:
    """Dựng hierarchy, Điểm, `chunk_ids` của một văn bản (chưa có cạnh viện dẫn).

    Args:
        tree: Kết quả `chunking.parser.parse_markdown`.
        chunks: Chunk đã embed, đọc từ `data/chunks` (không tạo lại bằng splitter).
        headings: Kết quả `scan_structure_headings` trên cùng file markdown.
        short_name: Tên ngắn văn bản (stem tên file markdown).

    Returns:
        `GraphDocument` với `references` rỗng.

    Raises:
        GraphBuildError: Cấu trúc không có node (Phụ lục), markdown lệch parser,
            hoặc chunk không khớp đúng một đơn vị (mục 5, 8).
    """
    doc_id = hashlib.sha256(tree.source_document.encode()).hexdigest()[:12]
    skeleton = _build_skeleton(doc_id, headings)
    owners = _assign_khoans_to_articles(tree, skeleton.articles)
    chunk_ids_by_base, front_ids, back_ids = _match_chunks(tree, chunks)
    clauses, points = _build_clauses_and_points(tree, owners, chunk_ids_by_base)
    if chunk_ids_by_base:
        leftover = sorted(cid for ids in chunk_ids_by_base.values() for cid in ids)
        raise GraphBuildError(
            f"{len(leftover)} chunk không khớp đơn vị nào (data/chunks cũ hơn "
            f"markdown?), ví dụ chunk_id {leftover[0]}"
        )
    if bool(tree.frontmatter_content) != bool(front_ids) or bool(
        tree.backmatter_content
    ) != bool(back_ids):
        raise GraphBuildError("Front/back matter không khớp chunk tương ứng")
    graph = GraphDocument(
        document=DocumentNode(
            id=doc_id,
            name=tree.source_document,
            short_name=short_name,
            kind=classify_document_kind(tree.source_document),
            front_text=tree.frontmatter_content,
            back_text=tree.backmatter_content,
            front_chunk_ids=front_ids,
            back_chunk_ids=back_ids,
        ),
        structures=skeleton.structures,
        articles=skeleton.articles,
        clauses=clauses,
        points=points,
    )
    _fill_char_counts(graph)
    return graph
