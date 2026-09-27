"""Unit test cho `graph/pipeline.py` (graph_spec.md mục 9, 10, 11).

`load_all_chunks` cô lập lỗi theo từng file (bất biến batch, cùng
`chunking_spec.md`). `run_ingest` nhận `client` đã mở sẵn (dùng ở test) --
không tự tạo `Neo4jClient()` thật nên không cần Neo4j sống để test điều phối
`builder.py` + thống kê `IngestResult`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from production_legal_agentic_graph_rag.graph.builder import build_graph_document
from production_legal_agentic_graph_rag.graph.models import GraphDocument
from production_legal_agentic_graph_rag.graph.pipeline import (
    load_all_chunks,
    run_ingest,
)

_GOOD_CHUNKS = (
    '[{"chunk_id": "c1", "source_document": "DOC", '
    '"breadcrumb": "DOC - Điều 1. A - Khoản 1", '
    '"content": "Nội dung khoản 1.", "token_count": 3}]'
)


class _FakeNeo4jClient:
    """Test double ghi lại `GraphDocument` được truyền vào `rebuild`."""

    def __init__(self) -> None:
        self.rebuilt_with: GraphDocument | None = None
        self.closed = False

    def rebuild(self, document: GraphDocument) -> None:
        self.rebuilt_with = document

    def close(self) -> None:
        self.closed = True


# ==========================================================================
# load_all_chunks -- cô lập lỗi theo file
# ==========================================================================


def test_load_all_chunks_thu_muc_khong_ton_tai_tra_ve_rong(tmp_path: Path):
    chunks, processed, failed = load_all_chunks(tmp_path / "khong_ton_tai")
    assert chunks == []
    assert processed == 0
    assert failed == 0


def test_load_all_chunks_doc_dung_1_file_hop_le(tmp_path: Path):
    (tmp_path / "a.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    chunks, processed, failed = load_all_chunks(tmp_path)
    assert processed == 1
    assert failed == 0
    assert [chunk.chunk_id for chunk in chunks] == ["c1"]


def test_load_all_chunks_bo_qua_file_json_hong_khong_chan_file_khac(
    tmp_path: Path,
):
    (tmp_path / "good.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not valid json,", encoding="utf-8")
    chunks, processed, failed = load_all_chunks(tmp_path)
    assert processed == 1
    assert failed == 1
    assert [chunk.chunk_id for chunk in chunks] == ["c1"]


def test_load_all_chunks_bo_qua_file_thieu_field_bat_buoc(tmp_path: Path):
    missing_field = (
        '[{"source_document": "DOC", "breadcrumb": "x", '
        '"content": "y", "token_count": 1}]'
    )
    (tmp_path / "good.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    (tmp_path / "missing.json").write_text(missing_field, encoding="utf-8")
    chunks, processed, failed = load_all_chunks(tmp_path)
    assert processed == 1
    assert failed == 1
    assert [chunk.chunk_id for chunk in chunks] == ["c1"]


def test_load_all_chunks_quet_de_quy_thu_muc_con(tmp_path: Path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    chunks, processed, failed = load_all_chunks(tmp_path)
    assert processed == 1
    assert failed == 0
    assert len(chunks) == 1


# ==========================================================================
# run_ingest -- điều phối builder + client, không đụng Neo4j thật
# ==========================================================================


def test_run_ingest_goi_rebuild_voi_dung_graph_document(tmp_path: Path):
    (tmp_path / "a.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    fake_client: Any = _FakeNeo4jClient()

    result = run_ingest(tmp_path, client=fake_client)

    chunks, _, _ = load_all_chunks(tmp_path)
    expected_document, _, _ = build_graph_document(chunks)
    assert fake_client.rebuilt_with == expected_document
    assert result.chunks_read == 1
    assert result.files_processed == 1
    assert result.files_failed == 0
    assert result.node_counts == {
        "VanBan": 1,
        "Phan": 0,
        "Chuong": 0,
        "Muc": 0,
        "Dieu": 1,
        "Khoan": 1,
    }
    assert result.edge_counts == {"HAS_CHILD": 2, "REFERENCES": 0}


def test_run_ingest_khong_dong_client_duoc_truyen_vao_tu_ben_ngoai(
    tmp_path: Path,
):
    # `client` truyền vào từ bên ngoài (`owns_client=False` trong
    # `pipeline.py`) không được tự đóng -- vòng đời do caller quản lý.
    (tmp_path / "a.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    fake_client: Any = _FakeNeo4jClient()

    run_ingest(tmp_path, client=fake_client)

    assert fake_client.closed is False


def test_run_ingest_thong_ke_dung_khi_co_file_loi(tmp_path: Path):
    (tmp_path / "good.json").write_text(_GOOD_CHUNKS, encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not valid json,", encoding="utf-8")
    fake_client: Any = _FakeNeo4jClient()

    result = run_ingest(tmp_path, client=fake_client)

    assert result.files_processed == 1
    assert result.files_failed == 1
    assert result.chunks_read == 1
