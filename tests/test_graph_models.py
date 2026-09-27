"""Data/schema validation cho `graph/models.py` (graph_spec.md mục 3, 5, 10).

Trọng tâm: `number`/`khoan_number` phải chấp nhận `str` có hậu tố chữ
(`"48a"`, `"7b"`) thay vì `int` (mục 5 -- lý do đã nêu trong docstring của
từng model), và các field mặc định rỗng đúng theo bảng schema mục 5.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from production_legal_agentic_graph_rag.graph.models import (
    ChuongNode,
    DieuCoordinate,
    DieuNode,
    GraphDocument,
    HasChildEdge,
    IngestResult,
    KhoanCoordinate,
    KhoanNode,
    MucNode,
    PhanNode,
    ReferenceEdge,
    VanBanNode,
)

# ==========================================================================
# DieuCoordinate
# ==========================================================================


def test_dieu_coordinate_bat_buoc_number_va_title():
    with pytest.raises(ValidationError):
        DieuCoordinate()  # type: ignore[call-arg]


def test_dieu_coordinate_chap_nhan_number_hau_to_chu():
    coordinate = DieuCoordinate(number="48a", title="Tên điều")
    assert coordinate.number == "48a"


# ==========================================================================
# KhoanCoordinate
# ==========================================================================


def _dieu() -> DieuCoordinate:
    return DieuCoordinate(number="2", title="Tên điều")


def test_khoan_coordinate_bat_buoc_khoan_number_du_la_none():
    # `khoan_number: str | None` không có default -- phải truyền tường minh,
    # kể cả khi giá trị là `None` (Khoản ngầm định cấp Điều, mục 6).
    with pytest.raises(ValidationError):
        KhoanCoordinate(
            source_document="DOC",
            dieu=_dieu(),
            breadcrumb_root="DOC - Điều 2 - Khoản 1",
            content="Nội dung.",
        )  # type: ignore[call-arg]


def test_khoan_coordinate_chap_nhan_khoan_number_none_cho_khoan_ngam_dinh():
    coordinate = KhoanCoordinate(
        source_document="DOC",
        dieu=_dieu(),
        khoan_number=None,
        breadcrumb_root="DOC - Điều 2",
        content="Nội dung.",
    )
    assert coordinate.khoan_number is None
    assert coordinate.chunk_ids == []
    assert coordinate.phan is None
    assert coordinate.chuong is None
    assert coordinate.muc is None


def test_khoan_coordinate_chap_nhan_khoan_number_hau_to_chu():
    coordinate = KhoanCoordinate(
        source_document="DOC",
        dieu=_dieu(),
        khoan_number="3a",
        breadcrumb_root="DOC - Điều 2 - Khoản 3a",
        content="Nội dung.",
        chunk_ids=["c1", "c2"],
    )
    assert coordinate.khoan_number == "3a"
    assert coordinate.chunk_ids == ["c1", "c2"]


# ==========================================================================
# Node theo cấp (mục 5)
# ==========================================================================


def test_van_ban_node_bat_buoc_id_va_source_document():
    with pytest.raises(ValidationError):
        VanBanNode()  # type: ignore[call-arg]
    node = VanBanNode(id="DOC", source_document="DOC")
    assert node.id == "DOC"


@pytest.mark.parametrize("node_class", [PhanNode, ChuongNode, MucNode])
def test_phan_chuong_muc_node_bat_buoc_id_va_label(node_class: type):
    with pytest.raises(ValidationError):
        node_class()  # type: ignore[call-arg]
    node = node_class(id="hash123", label="I")
    assert node.label == "I"


def test_dieu_node_chap_nhan_number_hau_to_chu():
    node = DieuNode(id="hash", number="7a", title="Tên điều")
    assert node.number == "7a"


def test_khoan_node_bat_buoc_number_du_la_none():
    fields = {"id": "hash", "chunk_ids": ["c1"], "breadcrumb": "bc"}
    with pytest.raises(ValidationError):
        KhoanNode(**fields)  # type: ignore[arg-type]


def test_khoan_node_chap_nhan_number_none_va_hau_to_chu():
    implicit = KhoanNode(id="hash1", number=None, breadcrumb="bc")
    with_suffix = KhoanNode(id="hash2", number="5a", breadcrumb="bc")
    assert implicit.number is None
    assert implicit.chunk_ids == []
    assert with_suffix.number == "5a"


# ==========================================================================
# HasChildEdge / ReferenceEdge
# ==========================================================================


def test_has_child_edge_bat_buoc_parent_va_child():
    with pytest.raises(ValidationError):
        HasChildEdge()  # type: ignore[call-arg]
    edge = HasChildEdge(parent_id="p", child_id="c")
    assert (edge.parent_id, edge.child_id) == ("p", "c")


def test_reference_edge_target_diem_mac_dinh_none():
    edge = ReferenceEdge(source_id="s", target_id="t", raw_text="khoản 1 Điều 2")
    assert edge.target_diem is None


def test_reference_edge_chap_nhan_target_diem():
    edge = ReferenceEdge(
        source_id="s",
        target_id="t",
        raw_text="điểm a khoản 1 Điều 2",
        target_diem="a",
    )
    assert edge.target_diem == "a"


# ==========================================================================
# GraphDocument / IngestResult
# ==========================================================================


def test_graph_document_mac_dinh_tat_ca_rong():
    document = GraphDocument()
    assert document.van_bans == []
    assert document.phans == []
    assert document.chuongs == []
    assert document.mucs == []
    assert document.dieus == []
    assert document.khoans == []
    assert document.has_child_edges == []
    assert document.references == []


def test_ingest_result_mac_dinh_bang_khong():
    result = IngestResult()
    assert result.files_processed == 0
    assert result.files_failed == 0
    assert result.chunks_read == 0
    assert result.skipped_front_back_matter == 0
    assert result.skipped_unparseable_breadcrumb == 0
    assert result.node_counts == {}
    assert result.edge_counts == {}
