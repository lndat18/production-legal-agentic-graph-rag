"""Điều phối `builder.py` + `neo4j_client.py`: đọc `data/chunks/**/*.json`,
ghi Neo4j, trả `IngestResult` (mục 10 `graph_spec.md`).

Stateless, không checkpoint trung gian (mục 2) -- mỗi lần chạy đọc lại toàn
bộ `data/chunks/` và full rebuild đồ thị (mục 8), cùng triết lý
`embedding_spec.md` mục 1 vì corpus hiện tại nhỏ.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from production_legal_agentic_graph_rag.chunking.models import Chunk
from production_legal_agentic_graph_rag.graph.builder import build_graph_document
from production_legal_agentic_graph_rag.graph.models import GraphDocument, IngestResult
from production_legal_agentic_graph_rag.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

DEFAULT_CHUNKS_DIR = Path("data/chunks")


def _scan_chunk_files(chunks_dir: Path) -> list[Path]:
    """Quét đệ quy, trả về danh sách `.json` theo thứ tự ổn định."""
    if not chunks_dir.exists():
        return []
    return sorted(
        (path for path in chunks_dir.rglob("*.json") if path.is_file()),
        key=lambda path: str(path).casefold(),
    )


def _read_chunks(path: Path) -> list[Chunk] | None:
    """Đọc 1 file `.json`; `None` nếu hỏng/thiếu field (mục 9), log rõ lý do.

    Cùng bất biến batch cô lập lỗi của `chunking_spec.md`: 1 file lỗi không
    được chặn các file còn lại (mục 3 bất biến 6).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Chunk.model_validate(item) for item in raw]
    except (json.JSONDecodeError, ValidationError, OSError) as error:
        logger.error("Bỏ qua file chunk không đọc được %s: %s", path, error)
        return None


def load_all_chunks(chunks_dir: Path) -> tuple[list[Chunk], int, int]:
    """Đọc toàn bộ `.json` trong `chunks_dir`, cô lập lỗi theo từng file (mục 9).

    Returns:
        Toàn bộ `Chunk` đọc được, số file đọc thành công, số file lỗi.
    """
    chunks: list[Chunk] = []
    files_processed = 0
    files_failed = 0
    for path in _scan_chunk_files(chunks_dir):
        parsed = _read_chunks(path)
        if parsed is None:
            files_failed += 1
            continue
        chunks.extend(parsed)
        files_processed += 1
    return chunks, files_processed, files_failed


def _node_counts(document: GraphDocument) -> dict[str, int]:
    return {
        "VanBan": len(document.van_bans),
        "Phan": len(document.phans),
        "Chuong": len(document.chuongs),
        "Muc": len(document.mucs),
        "Dieu": len(document.dieus),
        "Khoan": len(document.khoans),
    }


def _edge_counts(document: GraphDocument) -> dict[str, int]:
    return {
        "HAS_CHILD": len(document.has_child_edges),
        "REFERENCES": len(document.references),
    }


def run_ingest(
    chunks_dir: Path = DEFAULT_CHUNKS_DIR, *, client: Neo4jClient | None = None
) -> IngestResult:
    """Chunks -> đồ thị Neo4j: đọc toàn bộ, build `GraphDocument`, full rebuild.

    Args:
        chunks_dir: Thư mục chứa `data/chunks/**/*.json`.
        client: `Neo4jClient` đã mở sẵn (dùng khi test/gọi lồng trong tiến
            trình khác); mặc định `None` -- tự tạo từ `GraphSettings()` và tự
            đóng khi xong.

    Returns:
        Thống kê node/edge đã ghi và số chunk/file bị bỏ qua (mục 11).

    Raises:
        Lỗi driver Neo4j (vd `neo4j.exceptions.ServiceUnavailable`) khi mất
        kết nối -- không âm thầm bỏ qua, khác lỗi cục bộ 1 chunk/file (mục 9).
    """
    chunks, files_processed, files_failed = load_all_chunks(chunks_dir)
    document, skipped_front_back, skipped_unparseable = build_graph_document(chunks)

    owns_client = client is None
    active_client = client if client is not None else Neo4jClient()
    try:
        active_client.rebuild(document)
    finally:
        if owns_client:
            active_client.close()

    return IngestResult(
        files_processed=files_processed,
        files_failed=files_failed,
        chunks_read=len(chunks),
        skipped_front_back_matter=skipped_front_back,
        skipped_unparseable_breadcrumb=skipped_unparseable,
        node_counts=_node_counts(document),
        edge_counts=_edge_counts(document),
    )
