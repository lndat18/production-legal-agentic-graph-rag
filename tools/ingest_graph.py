"""CLI mỏng ingest văn bản pháp luật vào Neo4j (graph_spec.md mục 10).

Dựng graph từ `data/markdown` + `data/chunks`, ghi mỗi văn bản một transaction.
`--dry-run` chỉ dựng và báo cáo, không kết nối Neo4j. Cấu hình Neo4j đọc từ biến
môi trường `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`/`NEO4J_DATABASE`.

Cách dùng:
    uv run python tools/ingest_graph.py --dry-run
    uv run python tools/ingest_graph.py
    uv run python tools/ingest_graph.py --file "data/markdown/Luật thuế thu nhập cá nhân.md"
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from production_legal_agentic_graph_rag.config import Neo4jSettings
from production_legal_agentic_graph_rag.graph.models import DocumentOutcome
from production_legal_agentic_graph_rag.graph.pipeline import (
    ingest_directory,
    ingest_document,
)
from production_legal_agentic_graph_rag.graph.store import GraphStore, Neo4jGraphStore

DEFAULT_MARKDOWN_DIR = Path("data/markdown")
DEFAULT_CHUNKS_DIR = Path("data/chunks")

app = typer.Typer(add_completion=False)


def _print_outcome(outcome: DocumentOutcome) -> None:
    if outcome.report is None:
        typer.echo(f"FAILED {outcome.short_name}: {outcome.error}")
        return
    report = outcome.report
    typer.echo(f"{outcome.status.upper()} {report.short_name}")
    typer.echo(f"  nodes: {report.node_counts}")
    typer.echo(
        f"  REFERS_TO={report.refers_to_edges} external={report.external_refs} "
        f"unresolved={report.unresolved_target_refs} "
        f"bare_huong_dan={report.bare_huong_dan_refs} "
        f"self_skipped={report.self_refs_skipped} "
        f"repealed_clauses={report.repealed_clauses} chunks={report.chunk_count}"
    )


@app.command()
def main(
    markdown_dir: Path = typer.Option(DEFAULT_MARKDOWN_DIR, help="Thư mục .md nguồn."),
    chunks_dir: Path = typer.Option(DEFAULT_CHUNKS_DIR, help="Thư mục chunk .json."),
    file: Path | None = typer.Option(
        None, help="Chỉ ingest một file .md (bỏ qua việc quét thư mục)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Dựng graph và báo cáo, không ghi Neo4j."
    ),
) -> None:
    """Ingest văn bản vào Neo4j; thoát mã 1 nếu có văn bản lỗi."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store: GraphStore | None = None
    if not dry_run:
        store = Neo4jGraphStore.from_settings(Neo4jSettings())  # type: ignore[call-arg]
    try:
        if file is None:
            outcomes = ingest_directory(markdown_dir, chunks_dir, store)
        else:
            if store is not None:
                store.ensure_schema()
            chunks_path = (chunks_dir / file.name).with_suffix(".json")
            outcomes = [ingest_document(file, chunks_path, store)]
    finally:
        if store is not None:
            store.close()
    for outcome in outcomes:
        _print_outcome(outcome)
    failed = sum(1 for outcome in outcomes if outcome.status == "failed")
    typer.echo(f"Tổng: {len(outcomes)} văn bản, {failed} lỗi")
    raise typer.Exit(code=1 if failed else 0)


if __name__ == "__main__":
    app()
