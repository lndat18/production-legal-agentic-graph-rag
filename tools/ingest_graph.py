"""CLI mỏng gọi `graph.pipeline.run_ingest` (mục 10 `graph_spec.md`).

Đọc toàn bộ `data/chunks/**/*.json`, full rebuild đồ thị Neo4j. Cần
`NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`/`NEO4J_DATABASE` reachable trước khi
chạy (mục 4) -- không có bước dựng Neo4j ở đây.

Cách dùng:
    uv run python tools/ingest_graph.py
    uv run python tools/ingest_graph.py --chunks-dir data/chunks
"""

from __future__ import annotations

from pathlib import Path

import typer

from production_legal_agentic_graph_rag.graph.pipeline import (
    DEFAULT_CHUNKS_DIR,
    run_ingest,
)

app = typer.Typer(add_completion=False)


@app.command()
def main(
    chunks_dir: Path = typer.Option(DEFAULT_CHUNKS_DIR, help="Thư mục .json đầu vào."),
) -> None:
    """Ingest toàn bộ `chunks_dir` vào Neo4j (full rebuild, mục 8)."""
    result = run_ingest(chunks_dir)
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
