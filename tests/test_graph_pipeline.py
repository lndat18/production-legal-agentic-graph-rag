"""Kiểm thử pipeline ingest graph: kiểm tra sau dựng, báo cáo, batch (graph_spec.md mục 3, 9, 10)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from production_legal_agentic_graph_rag.graph.builder import GraphBuildError
from production_legal_agentic_graph_rag.graph.models import (
    GraphDocument,
    NodeLabel,
    ReferenceEdge,
    ReferenceKind,
)
from production_legal_agentic_graph_rag.graph.pipeline import (
    build_document_graph,
    ingest_directory,
    ingest_document,
    validate_graph,
)
from production_legal_agentic_graph_rag.graph.store import (
    GraphStore,
    InMemoryGraphStore,
)
from tests.graph_helpers import (
    GOC_MARKDOWN,
    HUONG_DAN_MARKDOWN,
    build_from_markdown,
    write_document,
)


def _paths(tmp_path: Path, name: str = "Luật mẫu", markdown: str = GOC_MARKDOWN):
    markdown_path, chunks_path, _ = write_document(tmp_path, name, markdown)
    return markdown_path, chunks_path


# --- build_document_graph + báo cáo ---


def test_build_document_graph_report_counts(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)

    graph, report = build_document_graph(markdown_path, chunks_path)

    assert report.short_name == "Luật mẫu"
    assert report.node_counts == {
        "Document": 1,
        "Part": 0,
        "Chapter": 2,
        "Section": 1,
        "Article": 5,
        "Clause": 11,
        "Point": 2,
    }
    assert report.refers_to_edges == len(graph.references) == 7
    assert report.unresolved_target_refs == 1  # khoản 3 Điều 2 và Điều 99 (mơ hồ)
    assert report.external_refs == 0
    # "Chính phủ quy định chi tiết Điều này" và "Nội dung Điều 48a" (trong chính Điều 48a).
    assert report.self_refs_skipped == 2
    assert report.repealed_clauses == 0
    assert report.chunk_count == 13  # 11 Khoản + front + back


def test_report_counts_repealed_clauses_only_on_exact_line(tmp_path: Path) -> None:
    markdown = GOC_MARKDOWN.replace("Nội dung khoản 1a.", "(được bãi bỏ)").replace(
        "Chính phủ quy định chi tiết Điều này.",
        "Quy định này (được bãi bỏ) một phần.",
    )
    markdown_path, chunks_path = _paths(tmp_path, markdown=markdown)

    _, report = build_document_graph(markdown_path, chunks_path)

    assert report.repealed_clauses == 1


def test_build_report_counts_bare_huong_dan(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(
        tmp_path, "Nghị định mẫu", HUONG_DAN_MARKDOWN
    )

    graph, report = build_document_graph(markdown_path, chunks_path)

    assert graph.document.kind.value == "huong_dan"
    assert report.bare_huong_dan_refs == 1
    assert report.refers_to_edges == 1  # khoản 2 Điều 1 của Nghị định này


def test_build_document_graph_rejects_stale_chunks(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    raw = json.loads(chunks_path.read_text(encoding="utf-8"))
    raw.append({**raw[1], "chunk_id": "cũ", "breadcrumb": "LUẬT MẪU - Điều 77. Cũ"})
    chunks_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GraphBuildError):
        build_document_graph(markdown_path, chunks_path)


# --- validate_graph (mục 9) ---


def _valid(tmp_path: Path):
    graph, tree, chunks = build_from_markdown(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    return graph, tree, chunks


def test_validate_graph_accepts_valid(tmp_path: Path) -> None:
    graph, tree, chunks = _valid(tmp_path)

    validate_graph(graph, tree, chunks)


def test_validate_graph_rejects_dangling_edge(tmp_path: Path) -> None:
    graph, tree, chunks = _valid(tmp_path)
    clause = graph.clauses[0]
    bad = ReferenceEdge(
        source_label=NodeLabel.CLAUSE,
        source_id=clause.id,
        target_label=NodeLabel.ARTICLE,
        target_id="khong-ton-tai",
        raw_text="Điều 9",
        kind=ReferenceKind.SINGLE,
    )

    with pytest.raises(GraphBuildError, match="không tồn tại"):
        validate_graph(graph.model_copy(update={"references": [bad]}), tree, chunks)


def test_validate_graph_rejects_self_edge(tmp_path: Path) -> None:
    graph, tree, chunks = _valid(tmp_path)
    clause = graph.clauses[0]
    loop = ReferenceEdge(
        source_label=NodeLabel.CLAUSE,
        source_id=clause.id,
        target_label=NodeLabel.CLAUSE,
        target_id=clause.id,
        raw_text="khoản 1",
        kind=ReferenceKind.SINGLE,
    )

    with pytest.raises(GraphBuildError, match="tự trỏ"):
        validate_graph(graph.model_copy(update={"references": [loop]}), tree, chunks)


def test_validate_graph_rejects_chunk_covered_twice(tmp_path: Path) -> None:
    graph, tree, chunks = _valid(tmp_path)
    first, second = graph.clauses[0], graph.clauses[1]
    graph.clauses[1] = second.model_copy(
        update={"chunk_ids": [*second.chunk_ids, *first.chunk_ids]}
    )

    with pytest.raises(GraphBuildError, match="chunk"):
        validate_graph(graph, tree, chunks)


def test_validate_graph_rejects_missing_clause(tmp_path: Path) -> None:
    graph, tree, chunks = _valid(tmp_path)
    graph.clauses.pop()

    with pytest.raises(GraphBuildError):
        validate_graph(graph, tree, chunks)


# --- ingest_document ---


def test_ingest_document_written_to_store(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    store = InMemoryGraphStore()

    outcome = ingest_document(markdown_path, chunks_path, store)

    assert outcome.status == "written"
    assert outcome.report is not None
    assert len(store.documents) == 1


def test_ingest_document_dry_run_has_no_store(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)

    outcome = ingest_document(markdown_path, chunks_path, None)

    assert outcome.status == "dry_run"
    assert outcome.report is not None


def test_ingest_document_is_idempotent(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    store = InMemoryGraphStore()

    ingest_document(markdown_path, chunks_path, store)
    first = {k: v.model_copy(deep=True) for k, v in store.documents.items()}
    ingest_document(markdown_path, chunks_path, store)

    assert store.documents == first


def test_reingest_replaces_old_graph_completely(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    store = InMemoryGraphStore()
    ingest_document(markdown_path, chunks_path, store)
    changed = GOC_MARKDOWN.replace("Nội dung Điều 48a.", "Nội dung đã sửa.")
    markdown_path, chunks_path = _paths(tmp_path, markdown=changed)

    ingest_document(markdown_path, chunks_path, store)

    (graph,) = store.documents.values()
    texts = [c.text for c in graph.clauses]
    assert "Nội dung đã sửa." in texts
    assert "Nội dung Điều 48a." not in texts


def test_ingest_document_build_error_leaves_store_untouched(tmp_path: Path) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    chunks_path.write_text("[]", encoding="utf-8")
    store = InMemoryGraphStore()

    outcome = ingest_document(markdown_path, chunks_path, store)

    assert outcome.status == "failed"
    assert outcome.report is None
    assert outcome.error
    assert store.documents == {}


def test_ingest_document_missing_chunks_file_fails_with_type_only(
    tmp_path: Path,
) -> None:
    markdown_path, chunks_path = _paths(tmp_path)
    chunks_path.unlink()

    outcome = ingest_document(markdown_path, chunks_path, InMemoryGraphStore())

    assert outcome.status == "failed"
    assert outcome.error == "FileNotFoundError"


class _ExplodingStore(InMemoryGraphStore):
    def replace_document(self, graph: GraphDocument) -> None:
        raise RuntimeError("password=hunter2 nội dung điều luật")


def test_store_error_message_never_logged_or_returned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    markdown_path, chunks_path = _paths(tmp_path)

    with caplog.at_level(logging.DEBUG):
        outcome = ingest_document(markdown_path, chunks_path, _ExplodingStore())

    assert outcome.status == "failed"
    assert outcome.error == "RuntimeError"
    assert "hunter2" not in caplog.text
    assert "nội dung điều luật" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


# --- ingest_directory ---


def test_ingest_directory_continues_after_failed_document(tmp_path: Path) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    write_document(tmp_path, "Nghị định mẫu", HUONG_DAN_MARKDOWN)
    bad_markdown, _, _ = write_document(
        tmp_path, "Luật hỏng", GOC_MARKDOWN.replace("LUẬT", "LUẬT HỎNG")
    )
    (tmp_path / "chunks" / bad_markdown.with_suffix(".json").name).write_text("[]")
    store = InMemoryGraphStore()

    outcomes = ingest_directory(tmp_path / "markdown", tmp_path / "chunks", store)

    assert [(o.short_name, o.status) for o in outcomes] == [
        ("Luật hỏng", "failed"),
        ("Luật mẫu", "written"),
        ("Nghị định mẫu", "written"),
    ]
    assert len(store.documents) == 2
    assert store.schema_ready is True


def test_ingest_directory_dry_run_does_not_touch_store(tmp_path: Path) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)

    outcomes = ingest_directory(tmp_path / "markdown", tmp_path / "chunks", None)

    assert [o.status for o in outcomes] == ["dry_run"]


def test_ingest_directory_ensures_schema_before_writing(tmp_path: Path) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    calls: list[str] = []

    class _Recording(InMemoryGraphStore):
        def ensure_schema(self) -> None:
            calls.append("schema")

        def replace_document(self, graph: GraphDocument) -> None:
            calls.append("write")

    ingest_directory(tmp_path / "markdown", tmp_path / "chunks", _Recording())

    assert calls == ["schema", "write"]


def test_in_memory_store_satisfies_interface() -> None:
    assert isinstance(InMemoryGraphStore(), GraphStore)
