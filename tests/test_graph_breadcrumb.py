"""Unit test cho `graph/breadcrumb.py` (graph_spec.md mục 6).

Trọng tâm: parser định vị token cấp bằng regex, không tách `" - "` ngây thơ
-- phải sống sót qua tên Điều tự chứa `" - "` (dữ liệu thật, vd `"Điều 7a.
Trách nhiệm của Bộ Lao động - Thương binh và Xã hội"`, `Luật bảo hiểm y
tế`); "Khoản ngầm định cấp Điều" (`number=None`); gộp `is_split` theo đúng
thứ tự `split_index`, không tin thứ tự chunk trong file JSON; lỗi cục bộ 1
chunk không chặn batch (bất biến 6, mục 3).
"""

from __future__ import annotations

import pytest

from production_legal_agentic_graph_rag.chunking.models import Chunk
from production_legal_agentic_graph_rag.graph.breadcrumb import (
    BreadcrumbParseError,
    group_khoans,
    is_front_or_back_matter,
    parse_path,
    root_breadcrumb,
)

# ==========================================================================
# is_front_or_back_matter
# ==========================================================================


def test_front_matter_khop_dung_bang_source_document():
    assert is_front_or_back_matter("VĂN BẢN MẪU", "VĂN BẢN MẪU") is True


def test_front_matter_khop_ke_ca_hau_to_phan():
    assert is_front_or_back_matter("VĂN BẢN MẪU (phần 2/3)", "VĂN BẢN MẪU") is True


def test_back_matter_khop_theo_marker():
    breadcrumb = "VĂN BẢN MẪU - Chú thích sửa đổi (cuối văn bản) (phần 1/2)"
    assert is_front_or_back_matter(breadcrumb, "VĂN BẢN MẪU") is True


def test_noi_dung_thuong_khong_phai_front_back_matter():
    breadcrumb = "VĂN BẢN MẪU - Chương I - Điều 1. Tên điều - Khoản 1"
    assert is_front_or_back_matter(breadcrumb, "VĂN BẢN MẪU") is False


# ==========================================================================
# root_breadcrumb
# ==========================================================================


def test_root_breadcrumb_cat_hau_to_phan_va_diem():
    breadcrumb = "X - Khoản 3 - Điểm a (phần 1/2)"
    assert root_breadcrumb(breadcrumb) == "X - Khoản 3"


def test_root_breadcrumb_chi_co_hau_to_phan():
    assert root_breadcrumb("X - Khoản 3 (phần 2/2)") == "X - Khoản 3"


def test_root_breadcrumb_chi_co_hau_to_diem():
    assert root_breadcrumb("X - Khoản 3 - Điểm a") == "X - Khoản 3"


def test_root_breadcrumb_khong_co_hau_to_giu_nguyen():
    assert root_breadcrumb("X - Khoản 3") == "X - Khoản 3"


# ==========================================================================
# parse_path
# ==========================================================================


def test_parse_path_day_du_cac_cap():
    breadcrumb = "VĂN BẢN MẪU - Phần I - Chương II - Mục 1 - Điều 5. Tên - Khoản 1"
    phan, chuong, muc, dieu, khoan_number = parse_path(breadcrumb)
    assert phan == "I"
    assert chuong == "II"
    assert muc == "1"
    assert dieu.number == "5"
    assert dieu.title == "Tên"
    assert khoan_number == "1"


def test_parse_path_bo_cap_vang_mat():
    breadcrumb = "VĂN BẢN MẪU - Chương I - Điều 1. Tên điều - Khoản 2"
    phan, chuong, muc, dieu, khoan_number = parse_path(breadcrumb)
    assert phan is None
    assert chuong == "I"
    assert muc is None
    assert dieu.number == "1"
    assert khoan_number == "2"


def test_parse_path_khoan_ngam_dinh_cap_dieu():
    breadcrumb = "VĂN BẢN MẪU - Chương I - Điều 3. Tên điều"
    _, _, _, dieu, khoan_number = parse_path(breadcrumb)
    assert dieu.number == "3"
    assert khoan_number is None


def test_parse_path_ten_dieu_chua_gach_ngang_khong_vo():
    # Dữ liệu thật `Luật bảo hiểm y tế`: tên Điều tự chứa " - ", tách ngây
    # thơ theo literal " - " sẽ cắt đứt tên và làm rớt Khoản con.
    breadcrumb = (
        "LUẬT BẢO HIỂM Y TẾ - Chương I - Điều 7a. Trách nhiệm của Bộ Lao động"
        " - Thương binh và Xã hội - Khoản 1"
    )
    _, _, _, dieu, khoan_number = parse_path(breadcrumb)
    assert dieu.number == "7a"
    assert dieu.title == "Trách nhiệm của Bộ Lao động - Thương binh và Xã hội"
    assert khoan_number == "1"


def test_parse_path_hau_to_chu_o_so_dieu_va_khoan():
    breadcrumb = "VĂN BẢN MẪU - Điều 48b. Tên - Khoản 3a"
    _, _, _, dieu, khoan_number = parse_path(breadcrumb)
    assert dieu.number == "48b"
    assert khoan_number == "3a"


def test_parse_path_khong_co_token_dieu_bao_loi():
    with pytest.raises(BreadcrumbParseError):
        parse_path("VĂN BẢN MẪU - Chương I")


def test_parse_path_thu_tu_cap_sai_bao_loi():
    # "Khoản" xuất hiện trước "Điều" -- không phải toạ độ hợp lệ, phải bị
    # `_validate_order` chặn thay vì âm thầm trả kết quả sai.
    with pytest.raises(BreadcrumbParseError):
        parse_path("VĂN BẢN MẪU - Khoản 1 - Điều 2. Tên")


# ==========================================================================
# group_khoans
# ==========================================================================


def _chunk(
    chunk_id: str, doc: str, breadcrumb: str, content: str, **kw: object
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_document=doc,
        breadcrumb=breadcrumb,
        content=content,
        token_count=len(content.split()),
        **kw,  # type: ignore[arg-type]
    )


def test_group_khoans_loai_front_va_back_matter():
    doc = "VĂN BẢN MẪU"
    chunks = [
        _chunk("front", doc, doc, "Quốc hiệu."),
        _chunk(
            "back",
            doc,
            f"{doc} - Chú thích sửa đổi (cuối văn bản)",
            "Chú thích.",
        ),
        _chunk("k1", doc, f"{doc} - Chương I - Điều 1. Tên - Khoản 1", "Nội dung."),
    ]
    coordinates, front_back_count, unparseable_count = group_khoans(chunks)
    assert front_back_count == 2
    assert unparseable_count == 0
    assert len(coordinates) == 1
    assert coordinates[0].khoan_number == "1"


def test_group_khoans_gop_is_split_dung_thu_tu_split_index_khong_tin_thu_tu_file():
    doc = "VĂN BẢN MẪU"
    breadcrumb_prefix = f"{doc} - Chương I - Điều 1. Tên - Khoản 1"
    # Cố tình đưa mảnh split_index=2 vào TRƯỚC mảnh split_index=1 trong danh
    # sách input, để xác nhận group_khoans không tin thứ tự file JSON.
    chunks = [
        _chunk(
            "phan_2",
            doc,
            f"{breadcrumb_prefix} (phần 2/2)",
            "Nội dung phần 2.",
            is_split=True,
            split_index=2,
            split_total=2,
        ),
        _chunk(
            "phan_1",
            doc,
            f"{breadcrumb_prefix} (phần 1/2)",
            "Nội dung phần 1.",
            is_split=True,
            split_index=1,
            split_total=2,
        ),
    ]
    coordinates, _, _ = group_khoans(chunks)
    assert len(coordinates) == 1
    coordinate = coordinates[0]
    assert coordinate.chunk_ids == ["phan_1", "phan_2"]
    assert coordinate.content == "Nội dung phần 1.\nNội dung phần 2."
    assert coordinate.breadcrumb_root == breadcrumb_prefix


def test_group_khoans_bo_qua_chunk_loi_khong_chan_batch():
    doc = "VĂN BẢN MẪU"
    chunks = [
        _chunk("bad", doc, f"{doc} - Chương I", "Không có Điều."),
        _chunk("good", doc, f"{doc} - Chương I - Điều 1. Tên - Khoản 1", "OK."),
    ]
    coordinates, front_back_count, unparseable_count = group_khoans(chunks)
    assert front_back_count == 0
    assert unparseable_count == 1
    assert len(coordinates) == 1
    assert coordinates[0].dieu.number == "1"
