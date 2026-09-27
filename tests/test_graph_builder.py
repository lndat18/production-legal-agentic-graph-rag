"""Unit test cho `graph/builder.py` -- không cần Neo4j thật (graph_spec.md
mục 3, 8, 9, 11).

`build_graph_document` là function thuần `list[Chunk] -> GraphDocument`,
đúng tiêu chí hoàn thành mục 11: test được đầy đủ bằng unit test thuần. Bám
sát các bất biến mục 3: 1 Khoản = 1 node dù `is_split`, `chunk_ids` đúng thứ
tự `split_index`, ID node ổn định độc lập với title, idempotent, không nhân
đôi nội dung (node không có field `content`).
"""

from __future__ import annotations

from production_legal_agentic_graph_rag.chunking.models import Chunk
from production_legal_agentic_graph_rag.graph.builder import build_graph_document

_DOC = "VĂN BẢN MẪU"


def _chunk(chunk_id: str, breadcrumb: str, content: str, **kw: object) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_document=_DOC,
        breadcrumb=breadcrumb,
        content=content,
        token_count=len(content.split()),
        **kw,  # type: ignore[arg-type]
    )


# ==========================================================================
# Hierarchy cơ bản + HAS_CHILD
# ==========================================================================


def test_hierarchy_don_gian_tao_dung_cay_has_child():
    chunk = _chunk(
        "k1",
        f"{_DOC} - Chương I - Điều 1. Tên điều - Khoản 1",
        "Nội dung khoản 1.",
    )
    document, skip_fb, skip_unparse = build_graph_document([chunk])

    assert skip_fb == 0
    assert skip_unparse == 0
    assert len(document.van_bans) == 1
    assert len(document.chuongs) == 1
    assert len(document.dieus) == 1
    assert len(document.khoans) == 1
    assert document.phans == []
    assert document.mucs == []

    van_ban_id = document.van_bans[0].id
    chuong_id = document.chuongs[0].id
    dieu_id = document.dieus[0].id
    khoan_id = document.khoans[0].id
    edges = {(edge.parent_id, edge.child_id) for edge in document.has_child_edges}
    assert edges == {
        (van_ban_id, chuong_id),
        (chuong_id, dieu_id),
        (dieu_id, khoan_id),
    }


def test_node_khong_luu_content_bat_bien_1():
    chunk = _chunk(
        "k1",
        f"{_DOC} - Chương I - Điều 1. Tên - Khoản 1",
        "Nội dung bí mật.",
    )
    document, _, _ = build_graph_document([chunk])
    all_nodes = (
        *document.van_bans,
        *document.phans,
        *document.chuongs,
        *document.mucs,
        *document.dieus,
        *document.khoans,
    )
    for node in all_nodes:
        assert not hasattr(node, "content")


# ==========================================================================
# Bất biến 2: 1 Khoản = 1 node dù is_split, chunk_ids đúng thứ tự
# ==========================================================================


def test_khoan_bi_is_split_van_la_mot_node_va_chunk_ids_dung_thu_tu():
    prefix = f"{_DOC} - Chương I - Điều 3. Tên điều - Khoản 2"
    # Cố tình đưa phần 2 vào trước phần 1 trong danh sách input -- xác nhận
    # `group_khoans` không tin thứ tự file, chỉ tin `split_index`.
    chunks = [
        _chunk(
            "c_phan_2",
            f"{prefix} - Điểm b (phần 2/2)",
            "Nội dung phần 2.",
            is_split=True,
            split_index=2,
            split_total=2,
        ),
        _chunk(
            "c_phan_1",
            f"{prefix} - Điểm a (phần 1/2)",
            "Nội dung phần 1.",
            is_split=True,
            split_index=1,
            split_total=2,
        ),
    ]
    document, _, _ = build_graph_document(chunks)
    assert len(document.khoans) == 1
    khoan = document.khoans[0]
    assert khoan.chunk_ids == ["c_phan_1", "c_phan_2"]


# ==========================================================================
# Bất biến 3: ID node ổn định, độc lập với title
# ==========================================================================


def test_id_dieu_khong_doi_khi_ten_dieu_thay_doi():
    def _build_with_title(title: str) -> str:
        chunk = _chunk(
            "k1",
            f"{_DOC} - Chương I - Điều 3. {title} - Khoản 1",
            "Nội dung.",
        )
        document, _, _ = build_graph_document([chunk])
        return document.dieus[0].id

    id_a = _build_with_title("Tên gốc")
    id_b = _build_with_title("Tên đã sửa lỗi chính tả")
    assert id_a == id_b


def test_id_khoan_khong_phu_thuoc_noi_dung():
    def _build_with_content(content: str) -> str:
        chunk = _chunk(
            "k1",
            f"{_DOC} - Chương I - Điều 3. Tên - Khoản 1",
            content,
        )
        document, _, _ = build_graph_document([chunk])
        return document.khoans[0].id

    id_a = _build_with_content("Nội dung A.")
    id_b = _build_with_content("Nội dung B.")
    assert id_a == id_b


# ==========================================================================
# Khoản ngầm định cấp Điều
# ==========================================================================


def test_khoan_ngam_dinh_cap_dieu_tao_node_rieng_khac_id_voi_dieu():
    chunk = _chunk(
        "imp",
        f"{_DOC} - Chương I - Điều 4. Tên điều 4",
        "Đoạn mở đầu.",
    )
    document, _, _ = build_graph_document([chunk])
    assert len(document.dieus) == 1
    assert len(document.khoans) == 1
    khoan = document.khoans[0]
    assert khoan.number is None
    assert khoan.id != document.dieus[0].id
    assert khoan.chunk_ids == ["imp"]


def test_khoan_ngam_dinh_va_khoan_so_cung_dieu_khong_trung_id():
    # Dữ liệu thật `Luật bảo hiểm y tế` "Điều 48a": đoạn mở đầu (không có
    # heading Khoản) VÀ Khoản 1 đánh số riêng cùng tồn tại dưới 1 Điều.
    chunks = [
        _chunk(
            "imp",
            f"{_DOC} - Chương I - Điều 4. Tên điều 4",
            "Đoạn mở đầu.",
        ),
        _chunk(
            "k1",
            f"{_DOC} - Chương I - Điều 4. Tên điều 4 - Khoản 1",
            "Nội dung khoản 1.",
        ),
    ]
    document, _, _ = build_graph_document(chunks)
    assert len(document.dieus) == 1
    assert len(document.khoans) == 2
    numbers = {khoan.number for khoan in document.khoans}
    assert numbers == {None, "1"}
    ids = {khoan.id for khoan in document.khoans}
    assert len(ids) == 2


# ==========================================================================
# Front/back matter bị loại
# ==========================================================================


def test_front_va_back_matter_khong_tao_node_thua():
    chunks = [
        _chunk("front", _DOC, "Quốc hiệu tiêu ngữ."),
        _chunk(
            "back",
            f"{_DOC} - Chú thích sửa đổi (cuối văn bản)",
            "Chú thích.",
        ),
        _chunk(
            "k1",
            f"{_DOC} - Chương I - Điều 1. Tên - Khoản 1",
            "Nội dung khoản 1.",
        ),
    ]
    document, skip_fb, skip_unparse = build_graph_document(chunks)
    assert skip_fb == 2
    assert skip_unparse == 0
    assert len(document.khoans) == 1
    assert document.khoans[0].chunk_ids == ["k1"]


# ==========================================================================
# Batch cô lập lỗi (bất biến 6)
# ==========================================================================


def test_chunk_breadcrumb_loi_khong_chan_batch():
    chunks = [
        _chunk("bad", f"{_DOC} - Chương I", "Breadcrumb không có Điều."),
        _chunk(
            "good",
            f"{_DOC} - Chương I - Điều 1. Tên - Khoản 1",
            "OK.",
        ),
    ]
    document, skip_fb, skip_unparse = build_graph_document(chunks)
    assert skip_fb == 0
    assert skip_unparse == 1
    assert len(document.khoans) == 1


# ==========================================================================
# Idempotency (mục 8)
# ==========================================================================


def test_build_lai_cung_input_cho_ket_qua_giong_het():
    prefix = f"{_DOC} - Chương I - Điều 3. Tên điều - Khoản 2"
    chunks = [
        _chunk(
            "c1",
            f"{prefix} - Điểm a (phần 1/2)",
            "Phần 1.",
            is_split=True,
            split_index=1,
            split_total=2,
        ),
        _chunk(
            "c2",
            f"{prefix} - Điểm b (phần 2/2)",
            "Phần 2.",
            is_split=True,
            split_index=2,
            split_total=2,
        ),
        _chunk(
            "k41",
            f"{_DOC} - Chương I - Điều 4. Tên khác - Khoản 1",
            "theo quy định tại khoản 2 Điều 3 của Luật này.",
        ),
    ]
    document_1, _, _ = build_graph_document(chunks)
    document_2, _, _ = build_graph_document(chunks)
    assert document_1 == document_2


# ==========================================================================
# Viện dẫn chéo end-to-end (builder gọi references.py sau khi build hierarchy)
# ==========================================================================


def test_vien_dan_cheo_tao_reference_edge_giua_2_khoan_da_build():
    chunks = [
        _chunk(
            "k1_1",
            f"{_DOC} - Điều 1. A - Khoản 1",
            "Quy định về đối tượng áp dụng.",
        ),
        _chunk(
            "k2_1",
            f"{_DOC} - Điều 2. B - Khoản 1",
            "Theo quy định tại khoản 1 Điều 1 của Luật này.",
        ),
    ]
    document, _, _ = build_graph_document(chunks)
    khoan_by_chunk = {
        chunk_id: khoan.id
        for khoan in document.khoans
        for chunk_id in khoan.chunk_ids
    }
    assert len(document.references) == 1
    reference = document.references[0]
    assert reference.source_id == khoan_by_chunk["k2_1"]
    assert reference.target_id == khoan_by_chunk["k1_1"]


def test_vien_dan_giong_het_lap_lai_trong_1_khoan_bi_dedupe():
    chunks = [
        _chunk(
            "k1_1",
            f"{_DOC} - Điều 1. A - Khoản 1",
            "Quy định về đối tượng áp dụng.",
        ),
        _chunk(
            "k2_1",
            f"{_DOC} - Điều 2. B - Khoản 1",
            "Theo quy định tại khoản 1 Điều 1 của Luật này. "
            "Theo quy định tại khoản 1 Điều 1 của Luật này.",
        ),
    ]
    document, _, _ = build_graph_document(chunks)
    # Regex khớp 2 lần (câu trích lặp lại y hệt) nhưng phải dedupe về 1 edge
    # (`_reference_keys` trong `builder.py`), không phồng số edge.
    assert len(document.references) == 1
