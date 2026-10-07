"""Integration test `Neo4jGraphStore` trên Neo4j thật (graph_spec.md mục 8, 11).

Tự bỏ qua khi không có Neo4j: cần đặt `NEO4J_TEST_URI` và `NEO4J_TEST_PASSWORD`
(và tuỳ chọn `NEO4J_TEST_USER`) vào biến môi trường; test không đọc `.env`.
Cảnh báo: test XOÁ văn bản mẫu của chính nó; dùng database dev, không dùng dữ liệu thật.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from production_legal_agentic_graph_rag.graph.models import GraphDocument, NodeLabel
from production_legal_agentic_graph_rag.graph.store import Neo4jGraphStore
from tests.graph_helpers import GOC_MARKDOWN, build_with_references

pytestmark = pytest.mark.integration

_URI = os.environ.get("NEO4J_TEST_URI")
_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD")


@pytest.fixture
def store() -> Iterator[Neo4jGraphStore]:
    if not (_URI and _PASSWORD):
        pytest.skip("Cần NEO4J_TEST_URI và NEO4J_TEST_PASSWORD")
    driver = GraphDatabase.driver(
        _URI, auth=(os.environ.get("NEO4J_TEST_USER", "neo4j"), _PASSWORD)
    )
    try:
        driver.verify_connectivity()
    except Exception:  # noqa: BLE001 - không có Neo4j thì bỏ qua, không làm đỏ suite
        driver.close()
        pytest.skip("Không kết nối được Neo4j test")
    neo4j_store = Neo4jGraphStore(driver)
    neo4j_store.ensure_schema()
    yield neo4j_store
    neo4j_store.close()


@pytest.fixture
def graph(tmp_path: Path) -> GraphDocument:
    return build_with_references(tmp_path, "Luật mẫu integration", GOC_MARKDOWN)


def _count(store: Neo4jGraphStore, graph: GraphDocument) -> int:
    records = store._read(
        "MATCH (d:Document {id: $id}) OPTIONAL MATCH (d)-[*]->(n) "
        "RETURN count(DISTINCT n) AS total",
        id=graph.document.id,
    )
    return int(records[0]["total"])


def test_replace_document_is_idempotent(
    store: Neo4jGraphStore, graph: GraphDocument
) -> None:
    store.replace_document(graph)
    first = _count(store, graph)
    store.replace_document(graph)

    assert _count(store, graph) == first == len(graph.all_nodes()) - 1


def test_article_clauses_and_toc(store: Neo4jGraphStore, graph: GraphDocument) -> None:
    store.replace_document(graph)
    name = graph.document.short_name

    clauses = store.get_article_clauses(name, "2")
    toc = store.get_table_of_contents(name, NodeLabel.CHAPTER, "I")

    assert [c.label for c in clauses] == ["1", "2", "3"]
    assert [e.label for e in toc] == ["1", "2"]


def test_clause_context_and_reference_cards(
    store: Neo4jGraphStore, graph: GraphDocument
) -> None:
    store.replace_document(graph)
    name = graph.document.short_name
    clause = next(c for c in graph.clauses if "Như quy định tại Điều 3" in c.text)

    context = store.get_clause_context(clause.chunk_ids[0])
    cards = store.get_reference_cards(name, "3", None)
    counts = store.count_descendants(name, NodeLabel.CHAPTER, "I")

    assert context is not None and context.article.label == "4"
    assert len(cards.outgoing) == 5
    assert len(cards.incoming) == 1
    assert counts == {"Article": 2, "Clause": 4, "Point": 2}
