"""Unit test cho `graph/documents.py` (graph_spec.md mục 4, 7, 10).

`fold()` chuẩn hoá NFC + lowercase + bỏ dấu (kể cả đ -> d) + gộp khoảng
trắng; `resolve_document_phrase()` áp đúng 4 nhánh của mục 7 (rỗng -> cùng
văn bản, tự-tham-chiếu -> cùng văn bản, khớp alias -> văn bản đó, không khớp
-> `None`), ưu tiên alias dài nhất khi chồng lấn.
"""

from __future__ import annotations

import unicodedata

from production_legal_agentic_graph_rag.graph.documents import (
    DOCUMENTS,
    fold,
    resolve_document_phrase,
)

# ==========================================================================
# fold
# ==========================================================================


def test_fold_lowercase_va_bo_dau():
    assert fold("Luật Bảo Hiểm Xã Hội") == "luat bao hiem xa hoi"


def test_fold_xu_ly_dd_thanh_d():
    assert fold("Điều này") == "dieu nay"


def test_fold_gop_khoang_trang_thua():
    assert fold("  Luật   này  ") == "luat nay"


def test_fold_nfc_nfd_cho_cung_ket_qua():
    # "Điều" gõ tổ hợp (NFD, dấu tổ hợp rời) và dựng sẵn (NFC) phải fold về
    # cùng 1 chuỗi -- đầu vào thật (chunk content) không đảm bảo luôn ở dạng
    # NFC.
    nfc = "Điều"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd  # xác nhận 2 biểu diễn thật sự khác nhau ở byte gốc
    assert fold(nfc) == fold(nfd)


# ==========================================================================
# resolve_document_phrase
# ==========================================================================


def test_resolve_document_phrase_rong_tra_ve_cung_van_ban():
    assert resolve_document_phrase(None, "DOC") == "DOC"


def test_resolve_document_phrase_tu_tham_chieu_tra_ve_cung_van_ban():
    assert resolve_document_phrase("Luật này", "DOC") == "DOC"
    assert resolve_document_phrase("Bộ luật này", "DOC") == "DOC"


def test_resolve_document_phrase_khop_alias_van_ban_khac():
    assert resolve_document_phrase("Bộ luật Lao động", "DOC") == "BỘ LUẬT LAO ĐỘNG"
    assert resolve_document_phrase("Luật bhxh", "DOC") == "LUẬT BẢO HIỂM XÃ HỘI"


def test_resolve_document_phrase_khong_khop_alias_nao_tra_ve_none():
    assert resolve_document_phrase("Văn bản không tồn tại nào", "DOC") is None


def test_resolve_document_phrase_alias_dai_nhat_thang():
    # Cụm chứa cả alias BLLD ("bộ luật lao động") và alias BHXH ("luật bảo
    # hiểm xã hội") -- alias dài hơn (BHXH) phải thắng.
    phrase = "bộ luật lao động và luật bảo hiểm xã hội"
    assert resolve_document_phrase(phrase, "DOC") == "LUẬT BẢO HIỂM XÃ HỘI"


def test_resolve_document_phrase_bien_tu_khong_khop_giua_chu():
    # "blld" là alias hợp lệ nhưng chỉ khi đứng độc lập (biên từ `\w`) --
    # nằm giữa 1 từ khác không được tính là khớp.
    assert resolve_document_phrase("ablldb", "DOC") is None


def test_documents_bang_co_du_6_van_ban_mau():
    # corpus mẫu `data/raw` có 6 văn bản (CLAUDE.md mục 9) -- bảng alias phải
    # theo kịp, thiếu 1 văn bản sẽ làm mọi viện dẫn khác-văn-bản tới nó luôn
    # bị bỏ qua (mục 7, mục 12).
    assert len(DOCUMENTS) == 6
    assert "BỘ LUẬT LAO ĐỘNG" in DOCUMENTS
    assert "LUẬT BẢO HIỂM XÃ HỘI" in DOCUMENTS
