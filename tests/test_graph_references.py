"""Unit test cho `graph/references.py` (graph_spec.md mục 1, 3 bất biến 5, 7, 9).

Test trực tiếp `extract_references` với `KhoanCoordinate` dựng tay + map
`dieu_ids`/`khoan_ids` giả lập đồ thị đã build -- không cần qua
`builder.py`/Neo4j. Các case bám theo đúng mục 7: viện dẫn đơn, liệt kê
nhiều Khoản (kể cả bỏ qua riêng số không tồn tại), tự tham chiếu "Điều này",
viện dẫn khác văn bản qua alias, viện dẫn mơ hồ/không resolve được, guard
false-positive.
"""

from __future__ import annotations

from production_legal_agentic_graph_rag.graph.models import (
    DieuCoordinate,
    KhoanCoordinate,
)
from production_legal_agentic_graph_rag.graph.references import extract_references


def _khoan(
    doc: str, dieu_number: str, dieu_title: str, khoan_number: str, content: str
) -> KhoanCoordinate:
    return KhoanCoordinate(
        source_document=doc,
        dieu=DieuCoordinate(number=dieu_number, title=dieu_title),
        khoan_number=khoan_number,
        breadcrumb_root=(
            f"{doc} - Điều {dieu_number}. {dieu_title} - Khoản {khoan_number}"
        ),
        chunk_ids=[],
        content=content,
    )


def test_vien_dan_don_cung_van_ban_qua_tu_tham_chieu_luat_nay():
    khoan = _khoan(
        "DOC", "2", "Tên", "7", "theo quy định tại khoản 7 Điều 33 của Luật này."
    )
    edges = extract_references(
        khoan,
        "src1",
        dieu_ids={("DOC", "33"): "dieu33"},
        khoan_ids={("DOC", "33", "7"): "khoan337"},
    )
    assert len(edges) == 1
    assert edges[0].source_id == "src1"
    assert edges[0].target_id == "khoan337"
    assert edges[0].raw_text == "khoản 7 Điều 33 của Luật này"
    assert edges[0].target_diem is None


def test_vien_dan_khac_van_ban_qua_alias():
    khoan = _khoan(
        "LUẬT BẢO HIỂM XÃ HỘI",
        "2",
        "Tên",
        "7",
        "theo quy định tại khoản 2 Điều 169 của Bộ luật Lao động.",
    )
    edges = extract_references(
        khoan,
        "src1",
        dieu_ids={("BỘ LUẬT LAO ĐỘNG", "169"): "dieu169"},
        khoan_ids={("BỘ LUẬT LAO ĐỘNG", "169", "2"): "khoan1692"},
    )
    assert len(edges) == 1
    assert edges[0].target_id == "khoan1692"


def test_liet_ke_nhieu_khoan_tao_nhieu_edge_bo_qua_so_khong_ton_tai():
    khoan = _khoan(
        "DOC",
        "8",
        "Tên",
        "1",
        "theo quy định tại các khoản 6, 7, 9 và 10 Điều 34.",
    )
    edges = extract_references(
        khoan,
        "src2",
        dieu_ids={("DOC", "34"): "dieu34"},
        # Khoản 9 cố tình không có trong đồ thị -- chỉ số đó bị bỏ qua,
        # 3 số còn lại (6, 7, 10) vẫn tạo edge (không phải case mơ hồ, mục 7).
        khoan_ids={
            ("DOC", "34", "6"): "k6",
            ("DOC", "34", "7"): "k7",
            ("DOC", "34", "10"): "k10",
        },
    )
    assert {edge.target_id for edge in edges} == {"k6", "k7", "k10"}
    assert all(edge.raw_text == "các khoản 6, 7, 9 và 10 Điều 34" for edge in edges)


def test_tu_tham_chieu_dieu_nay_resolve_ve_dieu_cha_cua_khoan_dang_quet():
    khoan = _khoan(
        "DOC",
        "2",
        "Tên",
        "7",
        "các khoản 1, 4 và 5 Điều này của Bộ luật Lao động.",
    )
    edges = extract_references(
        khoan,
        "src4",
        # "Điều này" phải resolve về Dieu cha (DOC, "2"), KHÔNG phải Bộ luật
        # Lao động dù regex bắt được cụm "của Bộ luật Lao động" phía sau --
        # tự tham chiếu và tham chiếu văn bản khác loại trừ lẫn nhau (mục 7).
        dieu_ids={("DOC", "2"): "dieu2", ("BỘ LUẬT LAO ĐỘNG", "2"): "other_dieu2"},
        khoan_ids={("DOC", "2", "1"): "k1", ("DOC", "2", "4"): "k4"},
    )
    assert {edge.target_id for edge in edges} == {"k1", "k4"}


def test_dieu_nay_khong_co_so_khoan_tro_thang_toi_dieu_cha():
    khoan = _khoan("DOC", "5", "Tên", "1", "theo quy định tại Điều này.")
    edges = extract_references(
        khoan, "src5", dieu_ids={("DOC", "5"): "dieu5"}, khoan_ids={}
    )
    assert len(edges) == 1
    assert edges[0].target_id == "dieu5"


def test_vien_dan_thang_toi_dieu_khong_nhac_so_khoan():
    khoan = _khoan("DOC", "1", "Tên", "1", "theo quy định tại Điều 10 của Luật này.")
    edges = extract_references(
        khoan, "src6", dieu_ids={("DOC", "10"): "dieu10"}, khoan_ids={}
    )
    assert len(edges) == 1
    assert edges[0].target_id == "dieu10"


def test_vien_dan_van_ban_khong_khop_alias_nao_bi_bo_qua():
    khoan = _khoan(
        "DOC",
        "1",
        "Tên",
        "1",
        "theo khoản 1 Điều 10 của Văn bản không tồn tại nào.",
    )
    edges = extract_references(
        khoan, "src7", dieu_ids={("DOC", "10"): "dieu10"}, khoan_ids={}
    )
    assert edges == []


def test_dieu_dich_khong_co_trong_do_thi_bi_bo_qua():
    khoan = _khoan("DOC", "1", "Tên", "1", "theo Điều 999 của Luật này.")
    edges = extract_references(khoan, "src8", dieu_ids={}, khoan_ids={})
    assert edges == []


def test_target_diem_duoc_trich_khi_co_diem_cu_the():
    khoan = _khoan("DOC", "1", "Tên", "1", "theo quy định tại điểm a khoản 1 Điều 5.")
    edges = extract_references(
        khoan,
        "src9",
        dieu_ids={("DOC", "5"): "dieu5"},
        khoan_ids={("DOC", "5", "1"): "khoan51"},
    )
    assert len(edges) == 1
    assert edges[0].target_diem == "a"


def test_target_diem_nhieu_diem_giu_nguyen_cum_goc():
    khoan = _khoan(
        "DOC", "1", "Tên", "1", "theo quy định tại điểm a, b khoản 1 Điều 5."
    )
    edges = extract_references(
        khoan,
        "src9b",
        dieu_ids={("DOC", "5"): "dieu5"},
        khoan_ids={("DOC", "5", "1"): "khoan51"},
    )
    assert len(edges) == 1
    assert edges[0].target_diem == "a, b"


def test_guard_dieu_kien_dieu_khoan_dieu_hanh_khong_bi_nhan_nham():
    khoan = _khoan("DOC", "1", "Tên", "1", "cần đủ điều kiện và điều khoản hợp đồng.")
    edges = extract_references(khoan, "src10", dieu_ids={}, khoan_ids={})
    assert edges == []


def test_guard_so_dieu_dung_truoc_don_vi_khong_phai_vien_dan():
    # "khoản 2 Điều 5 năm" -- số 5 đứng trước đơn vị "năm" là số năm, không
    # phải số Điều thật (chính ví dụ trong comment gốc của `references.py`).
    khoan = _khoan("DOC", "1", "Tên", "1", "khoản 2 Điều 5 năm.")
    edges = extract_references(
        khoan, "src11", dieu_ids={("DOC", "5"): "dieu5"}, khoan_ids={}
    )
    assert edges == []
