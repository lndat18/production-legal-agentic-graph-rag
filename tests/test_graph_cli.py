"""Kiểm thử CLI `tools/ingest_graph.py` và `Neo4jSettings` (graph_spec.md mục 8, 10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from production_legal_agentic_graph_rag.config import Neo4jSettings
from production_legal_agentic_graph_rag.graph.store import (
    InMemoryGraphStore,
    Neo4jGraphStore,
)
from tests.graph_helpers import GOC_MARKDOWN, HUONG_DAN_MARKDOWN, write_document
from tools import ingest_graph

runner = CliRunner()


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--markdown-dir",
        str(tmp_path / "markdown"),
        "--chunks-dir",
        str(tmp_path / "chunks"),
        *extra,
    ]


def test_dry_run_reports_without_connecting_neo4j(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    write_document(tmp_path, "Nghị định mẫu", HUONG_DAN_MARKDOWN)

    def _forbidden(*_: object, **__: object) -> None:
        raise AssertionError("dry-run không được kết nối Neo4j")

    monkeypatch.setattr(Neo4jGraphStore, "from_settings", _forbidden)

    result = runner.invoke(ingest_graph.app, _args(tmp_path, "--dry-run"))

    assert result.exit_code == 0, result.output
    assert "DRY_RUN Luật mẫu" in result.output
    assert "DRY_RUN Nghị định mẫu" in result.output
    assert "REFERS_TO=7" in result.output
    assert "Tổng: 2 văn bản, 0 lỗi" in result.output


def test_dry_run_exits_1_when_a_document_fails(tmp_path: Path) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    (tmp_path / "chunks" / "Luật mẫu.json").write_text("[]", encoding="utf-8")

    result = runner.invoke(ingest_graph.app, _args(tmp_path, "--dry-run"))

    assert result.exit_code == 1
    assert "FAILED Luật mẫu" in result.output
    assert "Tổng: 1 văn bản, 1 lỗi" in result.output


def test_dry_run_single_file(tmp_path: Path) -> None:
    markdown_path, _, _ = write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    write_document(tmp_path, "Nghị định mẫu", HUONG_DAN_MARKDOWN)

    result = runner.invoke(
        ingest_graph.app, _args(tmp_path, "--dry-run", "--file", str(markdown_path))
    )

    assert result.exit_code == 0, result.output
    assert "Luật mẫu" in result.output
    assert "Nghị định mẫu" not in result.output
    assert "Tổng: 1 văn bản" in result.output


def test_real_run_writes_to_store_and_closes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    store = InMemoryGraphStore()
    closed: list[bool] = []
    store.close = lambda: closed.append(True)  # type: ignore[method-assign]
    monkeypatch.setattr(
        ingest_graph, "Neo4jSettings", lambda: Neo4jSettings(_env_file=None, password="x")
    )
    monkeypatch.setattr(
        Neo4jGraphStore, "from_settings", classmethod(lambda cls, settings: store)
    )

    result = runner.invoke(ingest_graph.app, _args(tmp_path))

    assert result.exit_code == 0, result.output
    assert "WRITTEN Luật mẫu" in result.output
    assert len(store.documents) == 1
    assert store.schema_ready is True
    assert closed == [True]


# --- Neo4jSettings ---


def test_neo4j_settings_reads_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://db:7687")
    monkeypatch.setenv("NEO4J_USER", "reader")
    monkeypatch.setenv("NEO4J_PASSWORD", "s3cret-pw")
    monkeypatch.setenv("NEO4J_DATABASE", "legal")

    settings = Neo4jSettings(_env_file=None)

    assert (settings.uri, settings.user, settings.database) == (
        "bolt://db:7687",
        "reader",
        "legal",
    )
    assert isinstance(settings.password, SecretStr)
    assert settings.password.get_secret_value() == "s3cret-pw"
    assert "s3cret-pw" not in repr(settings)


def test_neo4j_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_DATABASE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")

    settings = Neo4jSettings(_env_file=None)

    assert settings.uri == "bolt://localhost:7687"
    assert settings.user == "neo4j"
    assert settings.database == "neo4j"


def test_neo4j_settings_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    with pytest.raises(ValueError):
        Neo4jSettings(_env_file=None)
