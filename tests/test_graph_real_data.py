"""Kiểm thử graph trên 6 văn bản thật trong `data/` (graph_spec.md mục 3, 9, 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from production_legal_agentic_graph_rag.graph.pipeline import build_document_graph

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DOCUMENTS = sorted(path.stem for path in (DATA_DIR / "markdown").glob("*.md"))

pytestmark = pytest.mark.skipif(
    not DOCUMENTS, reason="Không có data/markdown trong môi trường này"
)


def _build(name: str):  # noqa: ANN202
    return build_document_graph(
        DATA_DIR / "markdown" / f"{name}.md", DATA_DIR / "chunks" / f"{name}.json"
    )


@pytest.mark.parametrize("name", DOCUMENTS)
def test_real_document_builds_with_invariants(name: str) -> None:
    graph, report = _build(name)  # kiểm tra mục 9 chạy trong build_document_graph
    node_ids = [node.id for node in graph.all_nodes()]
    node_set = set(node_ids)

    assert len(node_ids) == len(node_set)
    assert report.node_counts["Article"] == len(graph.articles) > 0
    assert report.chunk_count == len(
        {
            *graph.document.front_chunk_ids,
            *graph.document.back_chunk_ids,
            *(cid for c in graph.clauses for cid in c.chunk_ids),
        }
    )
    for edge in graph.references:
        assert edge.source_id in node_set
        assert edge.target_id in node_set
        assert edge.source_id != edge.target_id
    assert len({(e.source_id, e.target_id) for e in graph.references}) == len(
        graph.references
    )


@pytest.mark.parametrize("name", DOCUMENTS)
def test_real_document_build_is_deterministic(name: str) -> None:
    first, _ = _build(name)
    second, _ = _build(name)

    assert first == second


def test_real_huong_dan_document_drops_bare_articles() -> None:
    graph, report = _build("Điều kiện lao động và quan hệ lao động")

    assert graph.document.kind.value == "huong_dan"
    assert report.bare_huong_dan_refs > 0
    assert report.external_refs > 0


def test_real_goc_documents_have_no_bare_huong_dan_count() -> None:
    _, report = _build("Luật bảo hiểm xã hội")

    assert report.bare_huong_dan_refs == 0
    assert report.refers_to_edges > 0
