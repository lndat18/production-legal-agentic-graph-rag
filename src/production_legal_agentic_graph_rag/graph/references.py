"""Regex trích viện dẫn từ `content`, resolve target trong đồ thị đã build (mục 7).

Module tự viết mới cho `graph/`, không tái dùng `retrieval/citation.py`
(đang tạm ngoài phạm vi phát triển, `graph_spec.md` mục 4). Guard tránh false
positive theo cùng tinh thần đã chứng minh đúng ở đó (biên từ, số bắt buộc
ngay sau "điều" nên "điều kiện"/"điều khoản"/"điều hành" không khớp, loại số
đứng trước đơn vị đo lường) — không tái sử dụng code.
"""

from __future__ import annotations

import logging
import re

from production_legal_agentic_graph_rag.graph.documents import resolve_document_phrase
from production_legal_agentic_graph_rag.graph.models import (
    KhoanCoordinate,
    ReferenceEdge,
)

logger = logging.getLogger(__name__)

# Số Điều/Khoản có thể mang hậu tố chữ (`\d{1,3}[a-zđ]?`, vd "Điều 48b" --
# `Luật bảo hiểm y tế` viện dẫn thật tới chính Điều này), cùng lý do
# `breadcrumb.py::_LEVEL_TOKEN` chấp nhận hậu tố này.
_KHOAN_ITEM = r"\d{1,3}[a-zđ]?"
# Liệt kê nhiều Khoản trước 1 Điều là core use case (mục 1, mục 7 sau khi
# chốt lại) -- dữ liệu thật có cả 2 dạng nối: phẩy thuần
# ("khoản 1, 2, 3 và 10 Điều 34") và lặp lại từ "khoản" trước số cuối
# ("khoản 2, 3 và khoản 4 Điều 24"), nên item nối bằng "và"/"hoặc" chấp nhận
# tiền tố "khoản " tuỳ chọn. `khoan_list` giữ nguyên cụm gốc (kể cả "khoản "
# lặp lại) để `_parse_khoan_list` tách sau, không parse trực tiếp trong regex.
_KHOAN_LIST_GROUP = (
    r"(?:(?:các\s+)?khoản\s+"
    rf"(?P<khoan_list>{_KHOAN_ITEM}"
    rf"(?:\s*,\s*(?:khoản\s+)?{_KHOAN_ITEM})*"
    rf"(?:\s*(?:và|hoặc)\s*(?:khoản\s+)?{_KHOAN_ITEM})?)"
    r"\s+)?"
)
# Nhóm `diem` là phần mở rộng so với công thức gốc mục 7 (`[khoản (\d+) ]?Điều
# (\d+)[ của (<cụm văn bản>)]?`): mục 1 và mục 5 xác nhận `target_diem` phải
# được trích khi câu viện dẫn nêu điểm cụ thể (vd "điểm s khoản 1 Điều 62").
# `(?<!\w)`: biên từ, tránh "chiều 5" khớp nhầm "điều 5". Số bắt buộc ngay
# sau "điều"/"điều thứ" nên "điều kiện"/"điều khoản"/"điều hành" (không có
# chữ số theo sau) không khớp.
#
# "của <cụm văn bản>" phải dừng trước dấu câu kết thúc mệnh đề GẦN NHẤT --
# nhưng dữ liệu thật có câu 2 viện dẫn liền nhau không cách nhau bởi dấu câu
# nào (vd "...theo quy định tại Điều 46 của Bộ luật Lao động đối với ...theo
# quy định tại các khoản 1, 2, 3, 4, 6, 7, 9 và 10 Điều 34 của Bộ luật Lao
# động, trừ..." -- `Điều kiện lao động và quan hệ lao động`). Nếu chỉ dừng ở
# dấu câu, cụm văn bản của viện dẫn Điều 46 sẽ nuốt luôn "các khoản 1" của
# viện dẫn Điều 34 ngay sau, làm mất khoan_list của viện dẫn đó. Nên
# `doc_phrase` còn phải dừng trước điểm bắt đầu 1 viện dẫn mới (`điều`/
# `khoản`/`các khoản`), không chỉ trước dấu câu.
#
# `dieu` còn nhận literal "này" (tự tham chiếu chính Điều đang chứa câu trích
# -- dữ liệu thật "các khoản 1, 4, 5, 6 và 7 Điều này", `Luật bảo hiểm xã
# hội`): không có số nên phải resolve bằng toạ độ của `Khoan` nguồn đang quét
# (`extract_references` xử lý riêng, xem bên dưới), không tra `dieu_ids` bằng
# giá trị "này".
_SELF_DIEU_LITERAL = "này"
_DOC_PHRASE_STOP = r"[,;.\n)]|(?:các\s+)?khoản\b|điều\b"
_REFERENCE = re.compile(
    r"(?<!\w)"
    r"(?:điểm\s+(?P<diem>[a-zđ](?:\s*,\s*[a-zđ])*)\s+)?"
    rf"{_KHOAN_LIST_GROUP}"
    rf"điều\s*(?:thứ\s+)?(?P<dieu>\d{{1,3}}[a-zđ]?|{_SELF_DIEU_LITERAL})(?!\w)"
    rf"(?:\s+của\s+(?P<doc_phrase>(?:(?!{_DOC_PHRASE_STOP}).)+))?",
    re.IGNORECASE,
)
# Số Điều ngay trước đơn vị đo lường là đại lượng, không phải viện dẫn (vd
# "khoản 2 Điều 5 năm" -- số 5 đứng trước "năm" là số năm, không phải số
# Điều thật).
_UNIT_AFTER = re.compile(
    r"\s*(?:tháng|ngày|năm|tuổi|lần|đồng|triệu)(?!\w)|\s*%", re.IGNORECASE
)
_KHOAN_LIST_SEPARATOR = re.compile(r"\s*,\s*|\s+(?:và|hoặc)\s+", re.IGNORECASE)
_KHOAN_LIST_ITEM_PREFIX = re.compile(r"^\s*khoản\s+", re.IGNORECASE)


def _parse_khoan_list(raw: str | None) -> list[str]:
    """Tách cụm `khoan_list` gốc (giữ nguyên "khoản " lặp lại nếu có) thành
    từng số Khoản riêng lẻ, giữ nguyên thứ tự xuất hiện.

    Trả về danh sách rỗng khi câu trích không nhắc số Khoản nào (viện dẫn
    thẳng tới cả Điều).
    """
    if raw is None:
        return []
    items = []
    for token in _KHOAN_LIST_SEPARATOR.split(raw.strip()):
        cleaned = _KHOAN_LIST_ITEM_PREFIX.sub("", token).strip()
        if cleaned:
            items.append(cleaned)
    return items


def extract_references(
    khoan: KhoanCoordinate,
    source_id: str,
    dieu_ids: dict[tuple[str, str], str],
    khoan_ids: dict[tuple[str, str, str], str],
) -> list[ReferenceEdge]:
    """Quét `khoan.content`, resolve target trong đồ thị đã build (mục 7).

    Một câu trích liệt kê nhiều Khoản trước 1 Điều (vd "các khoản 6, 7, 9 và
    10 Điều 34") sinh **nhiều** `ReferenceEdge` -- một edge cho mỗi số Khoản
    hợp lệ, cùng chung `raw_text` gốc; số Khoản nào không tồn tại dưới Điều
    đích chỉ bị bỏ qua riêng số đó (log, không chặn các số còn lại trong cùng
    danh sách) -- đây là core use case viện dẫn chéo (mục 1), không phải case
    mơ hồ nên không bị bất biến 5 chặn.

    "Điều này" (tự tham chiếu, vd "các khoản 1, 4, 5, 6 và 7 Điều này") resolve
    thẳng về `Dieu` cha của chính `khoan` đang quét (`khoan.dieu.number`,
    `khoan.source_document`), bỏ qua mọi `doc_phrase` bắt được -- tự tham
    chiếu và tham chiếu văn bản khác loại trừ lẫn nhau (mục 7).

    Args:
        khoan: Khoản nguồn (đã gộp `is_split` ở `breadcrumb.py`); `content`
            chỉ dùng tạm ở đây, không được ghi vào bất kỳ node nào.
        source_id: `id` node `Khoan` nguồn (đã build ở `builder.py`).
        dieu_ids: `(source_document, dieu_number) -> Dieu.id` của toàn corpus
            đã build (kể cả văn bản khác `khoan.source_document`).
        khoan_ids: `(source_document, dieu_number, khoan_number) -> Khoan.id`
            — chỉ Khoản có số tường minh, không gồm Khoản ngầm định cấp Điều
            (viện dẫn luôn nêu số Khoản cụ thể, không thể trỏ tới Khoản ẩn).

    Returns:
        `ReferenceEdge` đã resolve được target. Viện dẫn mơ hồ (văn bản đích
        không khớp alias nào) hoặc Điều đích không có trong đồ thị (kể cả khi
        văn bản đích có trong corpus) bị bỏ qua + log toàn bộ câu trích,
        không raise, không tạo node giả (bất biến 5, mục 3 "Ngoài phạm vi",
        mục 9, mục 7).
    """
    edges: list[ReferenceEdge] = []
    for match in _REFERENCE.finditer(khoan.content):
        # Check ngay sau số Điều (không phải sau toàn bộ match, có thể còn
        # kéo dài tới hết cụm "của ...") -- "khoản 2 Điều 5 năm" là số năm,
        # không phải viện dẫn thật.
        if _UNIT_AFTER.match(khoan.content, match.end("dieu")):
            continue

        raw_text = match.group(0).strip()
        dieu_group = match.group("dieu")
        if dieu_group.casefold() == _SELF_DIEU_LITERAL:
            # "Điều này" không thể đi kèm cụm "của ..." (tự tham chiếu và
            # tham chiếu văn bản khác loại trừ lẫn nhau, mục 7) -- bỏ qua
            # `doc_phrase` dù regex có bắt được gì phía sau, dùng thẳng toạ
            # độ Dieu cha của chính Khoan đang quét.
            target_document: str | None = khoan.source_document
            dieu_number = khoan.dieu.number
        else:
            target_document = resolve_document_phrase(
                match.group("doc_phrase"), khoan.source_document
            )
            dieu_number = dieu_group
        if target_document is None:
            logger.info(
                "Bỏ qua viện dẫn không resolve được văn bản đích: raw_text=%r, "
                "breadcrumb=%r",
                raw_text,
                khoan.breadcrumb_root,
            )
            continue

        dieu_target_id = dieu_ids.get((target_document, dieu_number))
        if dieu_target_id is None:
            logger.info(
                "Bỏ qua viện dẫn tới Điều không có trong đồ thị: raw_text=%r, "
                "breadcrumb=%r, target_document=%r, target_dieu=%r",
                raw_text,
                khoan.breadcrumb_root,
                target_document,
                dieu_number,
            )
            continue

        khoan_numbers = _parse_khoan_list(match.group("khoan_list"))
        target_diem = match.group("diem")
        if not khoan_numbers:
            edges.append(
                ReferenceEdge(
                    source_id=source_id,
                    target_id=dieu_target_id,
                    raw_text=raw_text,
                    target_diem=target_diem,
                )
            )
            continue

        for khoan_number in khoan_numbers:
            khoan_target_id = khoan_ids.get(
                (target_document, dieu_number, khoan_number)
            )
            if khoan_target_id is None:
                logger.info(
                    "Bỏ qua 1 số Khoản không tồn tại dưới Điều đích trong danh "
                    "sách liệt kê: raw_text=%r, breadcrumb=%r, "
                    "target_document=%r, target_dieu=%r, target_khoan=%r",
                    raw_text,
                    khoan.breadcrumb_root,
                    target_document,
                    dieu_number,
                    khoan_number,
                )
                continue
            edges.append(
                ReferenceEdge(
                    source_id=source_id,
                    target_id=khoan_target_id,
                    raw_text=raw_text,
                    target_diem=target_diem,
                )
            )
    return edges
