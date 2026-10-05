"""Hồi quy nhãn Mục trùng giữa các Chương và lỗi CLI ingest (graph_spec.md mục 8, 10, 11)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Self

import pytest
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from typer.testing import CliRunner

from production_legal_agentic_graph_rag.config import Neo4jSettings
from production_legal_agentic_graph_rag.graph.models import NodeLabel
from production_legal_agentic_graph_rag.graph.pipeline import build_document_graph
from production_legal_agentic_graph_rag.graph.store import (
    AmbiguousUnitError,
    InMemoryGraphStore,
    Neo4jGraphStore,
)
from tests.graph_helpers import build_from_markdown, write_document
from tools import ingest_graph

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
NAME = "Luật mẫu"

# Mục 1 xuất hiện ở cả Chương I và Chương II; Chương III không có Mục.
DUP_SECTION_MARKDOWN = """VĂN PHÒNG QUỐC HỘI

**LUẬT**

# MẪU

Lời mở đầu.

## Chương I. CHƯƠNG MỘT

### Mục 1. Nhóm A

#### Điều 1. Một

Nội dung điều một.

#### Điều 2. Hai

Nội dung điều hai.

## Chương II. CHƯƠNG HAI

### Mục 1. Nhóm B

#### Điều 3. Ba

Nội dung điều ba.

### Mục 2. Nhóm C

#### Điều 4. Bốn

Nội dung điều bốn.

## Chương III. CHƯƠNG BA

#### Điều 5. Năm

Nội dung điều năm.
"""

SECTION = NodeLabel.SECTION


@pytest.fixture
def store(tmp_path: Path) -> InMemoryGraphStore:
    graph, _, _ = build_from_markdown(tmp_path, NAME, DUP_SECTION_MARKDOWN)
    memory = InMemoryGraphStore()
    memory.replace_document(graph)
    return memory


def _articles(store: InMemoryGraphStore, parent: str) -> list[tuple[str, int]]:
    toc = store.get_table_of_contents(NAME, SECTION, "1", parent_label=parent)
    return [(e.label, e.order) for e in toc]


# --- InMemoryGraphStore ---


def test_duplicate_section_label_without_parent_raises(
    store: InMemoryGraphStore,
) -> None:
    with pytest.raises(AmbiguousUnitError):
        store.get_table_of_contents(NAME, SECTION, "1")
    with pytest.raises(AmbiguousUnitError):
        store.count_descendants(NAME, SECTION, "1")


def test_ambiguous_error_is_value_error() -> None:
    assert issubclass(AmbiguousUnitError, ValueError)


def test_duplicate_section_with_parent_returns_only_own_children(
    store: InMemoryGraphStore,
) -> None:
    assert _articles(store, "I") == [("1", 1), ("2", 2)]
    assert _articles(store, "II") == [("3", 1)]


def test_duplicate_section_with_parent_counts_only_own_descendants(
    store: InMemoryGraphStore,
) -> None:
    in_one = store.count_descendants(NAME, SECTION, "1", parent_label="I")
    in_two = store.count_descendants(NAME, SECTION, "1", parent_label="II")

    assert in_one["Article"] == 2
    assert in_two["Article"] == 1


def test_unique_section_label_needs_no_parent(store: InMemoryGraphStore) -> None:
    toc = store.get_table_of_contents(NAME, SECTION, "2")

    assert [e.label for e in toc] == ["4"]
    assert store.count_descendants(NAME, SECTION, "2")["Article"] == 1


def test_unknown_section_label_returns_empty(store: InMemoryGraphStore) -> None:
    assert store.get_table_of_contents(NAME, SECTION, "9") == []
    assert store.get_table_of_contents(NAME, SECTION, "9", parent_label="I") == []
    assert store.count_descendants(NAME, SECTION, "9") == {}


def test_mismatched_parent_label_returns_empty(store: InMemoryGraphStore) -> None:
    # Mục 2 chỉ thuộc Chương II; Mục 1 không thuộc Chương III.
    assert store.get_table_of_contents(NAME, SECTION, "2", parent_label="I") == []
    assert store.get_table_of_contents(NAME, SECTION, "1", parent_label="III") == []
    assert store.count_descendants(NAME, SECTION, "1", parent_label="III") == {}


def test_chapter_lookup_lists_sections(
    store: InMemoryGraphStore,
) -> None:
    toc = store.get_table_of_contents(NAME, NodeLabel.CHAPTER, "II")

    assert [(e.node_label, e.label) for e in toc] == [
        (SECTION, "1"),
        (SECTION, "2"),
    ]


# --- dữ liệu thật: BHXH / BLLĐ có Mục lặp ---

REAL_DOCUMENTS = ["Luật bảo hiểm xã hội", "Văn bản hợp nhất bộ luật lao động"]


@pytest.mark.skipif(
    not (DATA_DIR / "markdown").exists(), reason="Không có data/markdown"
)
@pytest.mark.parametrize("name", REAL_DOCUMENTS)
def test_real_duplicate_sections_are_disambiguated_by_parent(name: str) -> None:
    graph, _ = build_document_graph(
        DATA_DIR / "markdown" / f"{name}.md", DATA_DIR / "chunks" / f"{name}.json"
    )
    memory = InMemoryGraphStore()
    memory.replace_document(graph)
    short = graph.document.short_name
    chapter_label = {s.id: s.label for s in graph.structures}
    sections = [s for s in graph.structures if s.node_label is SECTION]
    assert any(s.label == "1" for s in sections)
    ones = [s for s in sections if s.label == "1"]
    assert len(ones) > 1

    with pytest.raises(AmbiguousUnitError):
        memory.get_table_of_contents(short, SECTION, "1")

    for section in ones:
        parent = chapter_label[section.parent_id]
        siblings = [s for s in ones if chapter_label[s.parent_id] == parent]
        if len(siblings) > 1:
            continue
        toc = memory.get_table_of_contents(short, SECTION, "1", parent_label=parent)
        expected = sorted(
            (a for a in graph.articles if a.parent_id == section.id),
            key=lambda a: a.order,
        )
        assert [e.label for e in toc] == [a.label for a in expected]
        assert [e.order for e in toc] == sorted(e.order for e in toc)
        counts = memory.count_descendants(short, SECTION, "1", parent_label=parent)
        assert counts.get("Article", 0) == len(expected)


# --- Neo4jGraphStore._resolve_unit_id với driver giả ---


class _Session:
    def __init__(self, driver: _Driver) -> None:
        self._driver = driver

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def run(self, query: str, parameters: dict[str, Any]) -> Iterator[dict[str, Any]]:
        self._driver.log.append((query, parameters))
        return iter(self._driver.responses.pop(0))


class _Driver:
    def __init__(self, *responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.log: list[tuple[str, dict[str, Any]]] = []

    def session(self, database: str) -> _Session:
        return _Session(self)


def _neo4j(driver: _Driver) -> Neo4jGraphStore:
    return Neo4jGraphStore(driver)  # type: ignore[arg-type]


def test_neo4j_resolve_unit_id_parameterises_label_and_parent() -> None:
    driver = _Driver([{"id": "sec-1"}])
    hostile = "1'}) DETACH DELETE (n) //"

    unit_id = _neo4j(driver)._resolve_unit_id("Luật mẫu", SECTION, hostile, "II")

    assert unit_id == "sec-1"
    query, parameters = driver.log[0]
    assert parameters == {
        "short_name": "Luật mẫu",
        "label": hostile,
        "parent_label": "II",
    }
    assert hostile not in query
    assert "Luật mẫu" not in query
    assert "$label" in query and "$parent_label" in query


def test_neo4j_resolve_unit_id_none_when_no_record() -> None:
    assert _neo4j(_Driver([]))._resolve_unit_id("x", SECTION, "1", None) is None


def test_neo4j_resolve_unit_id_raises_when_ambiguous() -> None:
    driver = _Driver([{"id": "a"}, {"id": "b"}])

    with pytest.raises(AmbiguousUnitError):
        _neo4j(driver)._resolve_unit_id("x", SECTION, "1", None)


def test_neo4j_resolve_rejects_non_unit_label_before_querying() -> None:
    driver = _Driver()

    with pytest.raises(ValueError):
        _neo4j(driver)._resolve_unit_id("x", NodeLabel.CLAUSE, "1", None)

    assert driver.log == []


def test_neo4j_toc_looks_up_children_by_unique_id() -> None:
    child = {
        "label": "3",
        "title": "Ba",
        "order": 1,
        "char_count": 10,
    }
    driver = _Driver([{"id": "sec-II-1"}], [{"node_label": "Article", "child": child}])

    toc = _neo4j(driver).get_table_of_contents("x", SECTION, "1", parent_label="II")

    assert [(e.label, e.order) for e in toc] == [("3", 1)]
    query, parameters = driver.log[1]
    assert parameters == {"unit_id": "sec-II-1"}
    assert "$unit_id" in query and "ORDER BY child.order" in query


def test_neo4j_toc_and_count_empty_when_unit_missing() -> None:
    driver = _Driver([], [])
    store = _neo4j(driver)

    assert store.get_table_of_contents("x", SECTION, "9") == []
    assert store.count_descendants("x", SECTION, "9") == {}
    assert len(driver.log) == 2


def test_neo4j_count_descendants_uses_resolved_id() -> None:
    driver = _Driver([{"id": "sec-I-1"}], [{"node_label": "Article", "total": 2}])

    counts = _neo4j(driver).count_descendants("x", SECTION, "1", parent_label="I")

    assert counts == {"Article": 2}
    assert driver.log[1][1] == {"unit_id": "sec-I-1"}


# --- CLI: lỗi kết nối ---

runner = CliRunner()
SECRET_URI = "bolt://user:hunter2@secret-host:7687"


class _Closable(InMemoryGraphStore):
    def __init__(self) -> None:
        super().__init__()
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def _cli_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--markdown-dir",
        str(tmp_path / "markdown"),
        "--chunks-dir",
        str(tmp_path / "chunks"),
        *extra,
    ]


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ingest_graph,
        "Neo4jSettings",
        lambda: Neo4jSettings(_env_file=None, password="x"),
    )


def _assert_only_type_name(output: str, name: str) -> None:
    assert name in output
    assert "hunter2" not in output
    assert "secret-host" not in output
    assert "Traceback" not in output


def test_cli_disables_locals_in_pretty_exceptions() -> None:
    assert ingest_graph.app.pretty_exceptions_show_locals is False


@pytest.mark.parametrize(
    "error",
    [
        ServiceUnavailable(f"Cannot connect {SECRET_URI}"),
        Neo4jError(f"boom {SECRET_URI}"),
        OSError(f"io {SECRET_URI}"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_cli_connection_failure_prints_only_type_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    write_document(tmp_path, NAME, DUP_SECTION_MARKDOWN)
    _patch_settings(monkeypatch)

    def _fail(cls: type, settings: object) -> None:
        raise error

    monkeypatch.setattr(Neo4jGraphStore, "from_settings", classmethod(_fail))

    result = runner.invoke(ingest_graph.app, _cli_args(tmp_path))

    assert result.exit_code == 1
    _assert_only_type_name(result.output, type(error).__name__)


@pytest.mark.parametrize("failing", ["ensure_schema", "ingest_directory"])
def test_cli_failure_after_connect_closes_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    write_document(tmp_path, NAME, DUP_SECTION_MARKDOWN)
    _patch_settings(monkeypatch)
    store = _Closable()
    error = ServiceUnavailable(f"lost {SECRET_URI}")

    def _raise(*_: object, **__: object) -> None:
        raise error

    args = _cli_args(tmp_path)
    if failing == "ensure_schema":
        store.ensure_schema = _raise  # type: ignore[method-assign]
    else:
        monkeypatch.setattr(ingest_graph, "ingest_directory", _raise)
    monkeypatch.setattr(
        Neo4jGraphStore, "from_settings", classmethod(lambda cls, settings: store)
    )

    result = runner.invoke(ingest_graph.app, args)

    assert result.exit_code == 1
    _assert_only_type_name(result.output, "ServiceUnavailable")
    assert store.closed == 1


def test_cli_single_file_ensure_schema_failure_closes_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    markdown_path, _, _ = write_document(tmp_path, NAME, DUP_SECTION_MARKDOWN)
    _patch_settings(monkeypatch)
    store = _Closable()

    def _raise(*_: object, **__: object) -> None:
        raise ServiceUnavailable(f"lost {SECRET_URI}")

    store.ensure_schema = _raise  # type: ignore[method-assign]
    monkeypatch.setattr(
        Neo4jGraphStore, "from_settings", classmethod(lambda cls, settings: store)
    )

    result = runner.invoke(
        ingest_graph.app, _cli_args(tmp_path, "--file", str(markdown_path))
    )

    assert result.exit_code == 1
    _assert_only_type_name(result.output, "ServiceUnavailable")
    assert store.closed == 1


def test_cli_dry_run_never_touches_store_even_if_neo4j_would_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_document(tmp_path, NAME, DUP_SECTION_MARKDOWN)

    def _forbidden(*_: object, **__: object) -> None:
        raise AssertionError("dry-run không được kết nối Neo4j")

    monkeypatch.setattr(Neo4jGraphStore, "from_settings", _forbidden)

    result = runner.invoke(ingest_graph.app, _cli_args(tmp_path, "--dry-run"))

    assert result.exit_code == 0, result.output
    assert "DRY_RUN Luật mẫu" in result.output
