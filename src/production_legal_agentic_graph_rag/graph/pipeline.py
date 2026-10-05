"""Điều phối ingest graph: parse -> build -> viện dẫn -> kiểm tra -> ghi -> báo cáo (mục 9, 10).

Batch tuần tự; lỗi ở một văn bản không chặn các văn bản còn lại và không để
graph dở dang (mỗi văn bản một transaction ở `GraphStore`). Log chỉ chứa tên
file, số liệu và loại lỗi, không chứa nội dung văn bản hay thông điệp lỗi của
driver.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from production_legal_agentic_graph_rag.chunking.models import Chunk, DocumentTree
from production_legal_agentic_graph_rag.chunking.parser import parse_markdown
from production_legal_agentic_graph_rag.graph.builder import (
    REPEALED_TEXT,
    GraphBuildError,
    article_label_of_prefix,
    build_graph_document,
    scan_structure_headings,
)
from production_legal_agentic_graph_rag.graph.models import (
    DocumentOutcome,
    DocumentReport,
    GraphDocument,
    NodeLabel,
    ReferenceStats,
)
from production_legal_agentic_graph_rag.graph.refs import resolve_references
from production_legal_agentic_graph_rag.graph.store import GraphStore

logger = logging.getLogger(__name__)


def load_chunks(path: Path) -> list[Chunk]:
    """Đọc `data/chunks/**/*.json` (mảng `Chunk` do `chunking/` ghi)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Chunk.model_validate(item) for item in raw]


def validate_graph(
    graph: GraphDocument, tree: DocumentTree, chunks: list[Chunk]
) -> None:
    """Kiểm tra sau dựng (mục 9).

    Raises:
        GraphBuildError: Số Điều/Khoản lệch `DocumentTree`, chunk không phủ đúng
            một lần, hoặc cạnh `REFERS_TO` treo/tự trỏ.
    """
    problems: list[str] = []
    articles_with_clauses = {clause.parent_id for clause in graph.clauses}
    graph_articles = {
        article.label
        for article in graph.articles
        if article.id in articles_with_clauses
    }
    tree_articles = {
        article_label_of_prefix(khoan.breadcrumb_prefix, tree.source_document)
        for khoan in tree.khoans
    }
    if len(graph.clauses) != len(tree.khoans):
        problems.append(
            f"số Khoản graph={len(graph.clauses)} khác DocumentTree={len(tree.khoans)}"
        )
    if graph_articles != tree_articles:
        problems.append("tập Điều có nội dung lệch DocumentTree")

    covered = Counter(
        [
            *graph.document.front_chunk_ids,
            *graph.document.back_chunk_ids,
            *(cid for clause in graph.clauses for cid in clause.chunk_ids),
        ]
    )
    expected = {chunk.chunk_id for chunk in chunks}
    if set(covered) != expected or any(count != 1 for count in covered.values()):
        problems.append("chunk không phủ đúng một lần bởi Clause/front/back")

    node_ids = {node.id for node in graph.all_nodes()}
    for edge in graph.references:
        if edge.source_id not in node_ids or edge.target_id not in node_ids:
            problems.append("cạnh REFERS_TO trỏ tới node không tồn tại")
            break
        if edge.source_id == edge.target_id:
            problems.append("cạnh REFERS_TO tự trỏ")
            break
    if problems:
        raise GraphBuildError("; ".join(problems))


def build_report(
    graph: GraphDocument, stats: ReferenceStats, chunk_count: int
) -> DocumentReport:
    """Báo cáo số liệu của một văn bản (mục 9)."""
    counts = Counter(node.node_label.value for node in graph.all_nodes())
    return DocumentReport(
        short_name=graph.document.short_name,
        node_counts={label.value: counts.get(label.value, 0) for label in NodeLabel},
        refers_to_edges=len(graph.references),
        external_refs=stats.external,
        unresolved_target_refs=stats.unresolved_target,
        bare_huong_dan_refs=stats.bare_huong_dan,
        self_refs_skipped=stats.self_skipped,
        repealed_clauses=sum(
            1 for clause in graph.clauses if clause.text.strip() == REPEALED_TEXT
        ),
        chunk_count=chunk_count,
    )


def build_document_graph(
    markdown_path: Path, chunks_path: Path
) -> tuple[GraphDocument, DocumentReport]:
    """Dựng và kiểm tra graph của một văn bản (chưa ghi Neo4j).

    Args:
        markdown_path: File `.md` trong `data/markdown`.
        chunks_path: File `.json` tương ứng trong `data/chunks`.

    Returns:
        (graph đã có cạnh viện dẫn, báo cáo).

    Raises:
        GraphBuildError: Vi phạm bất biến hoặc kiểm tra mục 9.
        OSError: Không đọc được file.
    """
    tree = parse_markdown(markdown_path)
    chunks = load_chunks(chunks_path)
    headings = scan_structure_headings(markdown_path.read_text(encoding="utf-8"))
    graph = build_graph_document(tree, chunks, headings, markdown_path.stem)
    edges, stats = resolve_references(graph)
    graph = graph.model_copy(update={"references": edges})
    validate_graph(graph, tree, chunks)
    return graph, build_report(graph, stats, len(chunks))


def ingest_document(
    markdown_path: Path,
    chunks_path: Path,
    store: GraphStore | None,
) -> DocumentOutcome:
    """Ingest một văn bản; `store=None` là chế độ dry-run (không ghi Neo4j).

    Mọi lỗi được gói vào `DocumentOutcome(status="failed")`, không ném ra ngoài,
    để batch tiếp tục với văn bản kế tiếp.
    """
    short_name = markdown_path.stem
    try:
        graph, report = build_document_graph(markdown_path, chunks_path)
        if store is not None:
            store.replace_document(graph)
    except GraphBuildError as error:
        logger.error("graph build failed: %s: %s", short_name, error)
        return DocumentOutcome(short_name=short_name, status="failed", error=str(error))
    except Exception as error:  # noqa: BLE001 - lỗi một văn bản không chặn batch
        # Chỉ ghi loại lỗi: thông điệp của driver/IO có thể chứa dữ liệu ngoài.
        kind = type(error).__name__
        logger.error("graph ingest failed: %s: %s", short_name, kind)
        return DocumentOutcome(short_name=short_name, status="failed", error=kind)
    status = "dry_run" if store is None else "written"
    logger.info("graph %s: %s", status, short_name)
    return DocumentOutcome(short_name=short_name, status=status, report=report)


def ingest_directory(
    markdown_dir: Path, chunks_dir: Path, store: GraphStore | None
) -> list[DocumentOutcome]:
    """Ingest mọi `.md` trong `markdown_dir` tuần tự, giữ nguyên cấu trúc thư mục con.

    Args:
        markdown_dir: Thư mục markdown nguồn.
        chunks_dir: Thư mục chunk JSON (cùng cấu trúc, đuôi `.json`).
        store: Store đích; `None` là dry-run.

    Returns:
        Kết quả từng văn bản theo thứ tự tên.
    """
    if store is not None:
        store.ensure_schema()
    sources = sorted(markdown_dir.rglob("*.md"), key=lambda path: str(path).casefold())
    return [
        ingest_document(
            source,
            (chunks_dir / source.relative_to(markdown_dir)).with_suffix(".json"),
            store,
        )
        for source in sources
        if source.is_file()
    ]
