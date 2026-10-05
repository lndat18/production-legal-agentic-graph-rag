"""Kiểm thử `InMemoryGraphStore`, truy vấn mẫu và Cypher của `Neo4jGraphStore` (graph_spec.md mục 3, 8, 11)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import pytest

from production_legal_agentic_graph_rag.graph.models import (
    GraphDocument,
    NodeLabel,
    ReferenceKind,
)
from production_legal_agentic_graph_rag.graph.pipeline import build_document_graph
from production_legal_agentic_graph_rag.graph.store import (
    InMemoryGraphStore,
    Neo4jGraphStore,
)
from tests.graph_helpers import GOC_MARKDOWN, build_with_references

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TNCN = "Luật thuế thu nhập cá nhân"


@pytest.fixture
def graph(tmp_path: Path) -> GraphDocument:
    return build_with_references(tmp_path, "Luật mẫu", GOC_MARKDOWN)


@pytest.fixture
def store(graph: GraphDocument) -> InMemoryGraphStore:
    memory = InMemoryGraphStore()
    memory.ensure_schema()
    memory.replace_document(graph)
    return memory


# --- ghi ---


def test_ensure_schema_marks_ready() -> None:
    memory = InMemoryGraphStore()

    memory.ensure_schema()

    assert memory.schema_ready is True


def test_replace_document_is_idempotent_and_isolated(graph: GraphDocument) -> None:
    memory = InMemoryGraphStore()

    memory.replace_document(graph)
    memory.replace_document(graph)
    graph.clauses[0].text = "bị sửa sau khi ghi"

    assert len(memory.documents) == 1
    stored = memory.documents[graph.document.id]
    assert stored.clauses[0].text != "bị sửa sau khi ghi"


# --- truy vấn mẫu (mục 11) ---


def test_article_clauses_ordered(store: InMemoryGraphStore) -> None:
    clauses = store.get_article_clauses("Luật mẫu", "2")

    assert [(c.label, c.order) for c in clauses] == [("1", 1), ("2", 2), ("3", 3)]
    assert store.get_article_clauses("Luật mẫu", "999") == []
    assert store.get_article_clauses("Không có", "2") == []


def test_toc_of_chapter_lists_children_in_order(store: InMemoryGraphStore) -> None:
    toc = store.get_table_of_contents("Luật mẫu", NodeLabel.CHAPTER, "I")

    assert [(e.node_label, e.label, e.order) for e in toc] == [
        (NodeLabel.ARTICLE, "1", 1),
        (NodeLabel.ARTICLE, "2", 2),
    ]
    assert toc[1].title == "Giải thích"
    assert toc[1].char_count > 0


def test_toc_of_chapter_with_section_and_unknown(store: InMemoryGraphStore) -> None:
    toc = store.get_table_of_contents("Luật mẫu", NodeLabel.CHAPTER, "II")

    assert [(e.node_label, e.label) for e in toc] == [(NodeLabel.SECTION, "1")]
    assert store.get_table_of_contents("Luật mẫu", NodeLabel.CHAPTER, "IX") == []
    assert store.get_table_of_contents("Không có", NodeLabel.CHAPTER, "I") == []


def test_toc_rejects_non_unit_label(store: InMemoryGraphStore) -> None:
    with pytest.raises(ValueError):
        store.get_table_of_contents("Luật mẫu", NodeLabel.CLAUSE, "1")


def test_clause_context_from_chunk_id(
    store: InMemoryGraphStore, graph: GraphDocument
) -> None:
    clause = next(
        c for c in graph.clauses if c.label == "2" and "không cư trú" in c.text
    )

    context = store.get_clause_context(clause.chunk_ids[0])

    assert context is not None
    assert context.clause.label == "2"
    assert context.article.label == "2"
    assert [c.label for c in context.sibling_clauses] == ["1", "2", "3"]
    assert context.parent is not None and context.parent.label == "I"
    assert [a.label for a in context.sibling_articles] == ["1", "2"]


def test_clause_context_unknown_chunk_returns_none(store: InMemoryGraphStore) -> None:
    assert store.get_clause_context("khong-co-chunk-nay") is None


def test_clause_context_parent_is_section_for_article_in_section(
    store: InMemoryGraphStore, graph: GraphDocument
) -> None:
    clause = next(c for c in graph.clauses if "Như quy định tại Điều 3" in c.text)

    context = store.get_clause_context(clause.chunk_ids[0])

    assert context is not None
    assert context.parent is not None
    assert context.parent.node_label is NodeLabel.SECTION


def test_reference_cards_outgoing_for_clause(store: InMemoryGraphStore) -> None:
    cards = store.get_reference_cards("Luật mẫu", "3", "1")

    assert cards.incoming == []
    assert len(cards.outgoing) == 1
    card = cards.outgoing[0]
    assert card.node_label is NodeLabel.ARTICLE
    assert card.article_label == "1"
    assert card.article_title == "Phạm vi điều chỉnh"
    assert card.raw_text == "Điều 1 của Luật này"
    assert card.kind is ReferenceKind.SINGLE
    assert card.char_count > 0


def test_reference_cards_for_whole_article_include_incoming(
    store: InMemoryGraphStore,
) -> None:
    cards = store.get_reference_cards("Luật mẫu", "3", None)

    assert (
        len(cards.outgoing) == 5
    )  # Khoản 1 (1) + Khoản 2 (2 Điểm) + Khoản 3 (range 2)
    assert len(cards.incoming) == 1
    assert cards.incoming[0].article_label == "4"


def test_reference_cards_point_target_carries_article_context(
    store: InMemoryGraphStore,
) -> None:
    cards = store.get_reference_cards("Luật mẫu", "3", "2")

    assert {c.node_label for c in cards.outgoing} == {NodeLabel.POINT}
    assert {c.article_label for c in cards.outgoing} == {"2"}


def test_reference_cards_unknown_returns_empty(store: InMemoryGraphStore) -> None:
    assert store.get_reference_cards("Luật mẫu", "999", None).outgoing == []
    assert store.get_reference_cards("Không có", "3", None).incoming == []


def test_count_descendants(store: InMemoryGraphStore) -> None:
    chapter_1 = store.count_descendants("Luật mẫu", NodeLabel.CHAPTER, "I")
    chapter_2 = store.count_descendants("Luật mẫu", NodeLabel.CHAPTER, "II")
    article_2 = store.count_descendants("Luật mẫu", NodeLabel.ARTICLE, "2")

    assert chapter_1 == {"Article": 2, "Clause": 4, "Point": 2}
    assert chapter_2 == {"Section": 1, "Article": 3, "Clause": 7}
    assert article_2 == {"Clause": 3, "Point": 2}
    assert store.count_descendants("Luật mẫu", NodeLabel.CHAPTER, "IX") == {}


# --- dữ liệu thật trong repo ---

real_data = pytest.mark.skipif(
    not (DATA_DIR / "markdown" / f"{TNCN}.md").exists(),
    reason="Không có data/markdown trong môi trường này",
)


@pytest.fixture(scope="module")
def tncn_store() -> InMemoryGraphStore:
    graph, _ = build_document_graph(
        DATA_DIR / "markdown" / f"{TNCN}.md", DATA_DIR / "chunks" / f"{TNCN}.json"
    )
    memory = InMemoryGraphStore()
    memory.replace_document(graph)
    return memory


@real_data
def test_real_tncn_article_4_has_22_clauses_in_order(
    tncn_store: InMemoryGraphStore,
) -> None:
    clauses = tncn_store.get_article_clauses(TNCN, "4")

    assert len(clauses) == 22
    assert [c.order for c in clauses] == list(range(1, 23))
    assert [c.label for c in clauses] == [str(n) for n in range(1, 23)]


@real_data
def test_real_tncn_chunk_lookup_reaches_article_4(
    tncn_store: InMemoryGraphStore,
) -> None:
    clause = tncn_store.get_article_clauses(TNCN, "4")[5]

    context = tncn_store.get_clause_context(clause.chunk_ids[0])

    assert context is not None
    assert context.article.label == "4"
    assert len(context.sibling_clauses) == 22


@real_data
def test_real_tncn_counts_articles_of_chapter(tncn_store: InMemoryGraphStore) -> None:
    counts = tncn_store.count_descendants(TNCN, NodeLabel.CHAPTER, "I")

    assert counts["Article"] >= 4
    assert counts["Clause"] >= 22


# --- Neo4jGraphStore với driver giả: Cypher tham số hoá, không chạy Neo4j thật ---


class _FakeResult:
    def consume(self) -> None:
        return None


class _FakeTransaction:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._log = log

    def run(self, query: str, **parameters: Any) -> _FakeResult:
        self._log.append((query, parameters))
        return _FakeResult()


class _FakeSession:
    def __init__(self, log: list[tuple[str, dict[str, Any]]]) -> None:
        self._log = log

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute_write(self, work: Callable[..., None], *args: Any) -> None:
        work(_FakeTransaction(self._log), *args)

    def run(self, query: str, *_: Any, **parameters: Any) -> _FakeResult:
        self._log.append((query, parameters))
        return _FakeResult()


class _FakeDriver:
    def __init__(self) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []
        self.databases: list[str] = []

    def session(self, database: str) -> _FakeSession:
        self.databases.append(database)
        return _FakeSession(self.log)


def test_neo4j_replace_document_deletes_first_and_parameterises(
    graph: GraphDocument,
) -> None:
    driver = _FakeDriver()
    store = Neo4jGraphStore(driver, database="legal")  # type: ignore[arg-type]

    store.replace_document(graph)

    queries = [query for query, _ in driver.log]
    assert driver.databases == ["legal"]
    assert "DETACH DELETE" in queries[0]
    assert driver.log[0][1] == {"doc_id": graph.document.id}
    assert any("MERGE (n:Document" in q for q in queries)
    assert any("MERGE (s)-[r:REFERS_TO]->(t)" in q for q in queries)
    joined = "\n".join(queries)
    for clause in graph.clauses:
        assert clause.text not in joined
        assert clause.id not in joined
    for article in graph.articles:
        assert article.title not in joined


def test_neo4j_replace_document_writes_rows_as_parameters(
    graph: GraphDocument,
) -> None:
    driver = _FakeDriver()

    Neo4jGraphStore(driver).replace_document(graph)  # type: ignore[arg-type]

    written = [p["rows"] for q, p in driver.log if "MERGE (n:" in q]
    all_ids = {row["id"] for rows in written for row in rows}
    assert all_ids == {n.id for n in graph.all_nodes()}
    reference_rows = [
        row for q, p in driver.log if "REFERS_TO" in q for row in p["rows"]
    ]
    assert len(reference_rows) == len(graph.references)
    assert {row["kind"] for row in reference_rows} <= {"single", "range"}


def test_neo4j_ensure_schema_creates_unique_constraint_per_label() -> None:
    driver = _FakeDriver()

    Neo4jGraphStore(driver).ensure_schema()  # type: ignore[arg-type]

    queries = [query for query, _ in driver.log]
    assert len(queries) == len(NodeLabel)
    for label in NodeLabel:
        assert any(
            f"(n:{label.value})" in q and "IF NOT EXISTS" in q and "n.id IS UNIQUE" in q
            for q in queries
        )


def test_neo4j_toc_rejects_non_unit_label_before_querying() -> None:
    driver = _FakeDriver()

    with pytest.raises(ValueError):
        Neo4jGraphStore(driver).get_table_of_contents(  # type: ignore[arg-type]
            "x", NodeLabel.POINT, "a"
        )

    assert driver.log == []
