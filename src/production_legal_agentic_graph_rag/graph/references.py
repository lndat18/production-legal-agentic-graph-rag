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

# Nhóm `diem` là phần mở rộng so với công thức gốc mục 7
# (`[khoản (\d+) ]?Điều (\d+)[ của (<cụm văn bản>)]?`): mục 1 và mục 5 xác
# nhận `target_diem` phải được trích khi câu viện dẫn nêu điểm cụ thể (vd
# "điểm s khoản 1 Điều 62"), công thức mục 7 chỉ chưa liệt kê riêng nhóm này.
# `(?<!\w)`: biên từ, tránh "chiều 5" khớp nhầm "điều 5". Số bắt buộc ngay
# sau "điều"/"điều thứ" nên "điều kiện"/"điều khoản"/"điều hành" (không có
# chữ số theo sau) không khớp. "của <cụm văn bản>" dừng ở dấu câu kết thúc
# mệnh đề gần nhất.
# Số Điều/Khoản có thể mang hậu tố chữ (`\d{1,3}[a-zđ]?`, vd "Điều 48b" --
# `Luật bảo hiểm y tế` viện dẫn thật tới chính Điều này), cùng lý do
# `breadcrumb.py::_LEVEL_TOKEN` chấp nhận hậu tố này.
_REFERENCE = re.compile(
    r"(?<!\w)"
    r"(?:điểm\s+(?P<diem>[a-zđ](?:\s*,\s*[a-zđ])*)\s+)?"
    r"(?:khoản\s*(?P<khoan>\d{1,3}[a-zđ]?)\s+)?"
    r"điều\s*(?:thứ\s+)?(?P<dieu>\d{1,3}[a-zđ]?)(?!\w)"
    r"(?:\s+của\s+(?P<doc_phrase>[^,;.\n)]+))?",
    re.IGNORECASE,
)
# Số Điều ngay trước đơn vị đo lường là đại lượng, không phải viện dẫn (vd
# "trong vòng điều... " không có nghĩa, nhưng "khoản 2 Điều 5 năm" -- số 5
# đứng trước "năm" là số năm, không phải số Điều thật).
_UNIT_AFTER = re.compile(
    r"\s*(?:tháng|ngày|năm|tuổi|lần|đồng|triệu)(?!\w)|\s*%", re.IGNORECASE
)


def extract_references(
    khoan: KhoanCoordinate,
    source_id: str,
    dieu_ids: dict[tuple[str, str], str],
    khoan_ids: dict[tuple[str, str, str], str],
) -> list[ReferenceEdge]:
    """Quét `khoan.content`, resolve target trong đồ thị đã build (mục 7).

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
        văn bản đích có trong corpus) bị bỏ qua + log, không raise, không tạo
        node giả (bất biến 5, mục 3 "Ngoài phạm vi", mục 9).
    """
    edges: list[ReferenceEdge] = []
    for match in _REFERENCE.finditer(khoan.content):
        # Check ngay sau số Điều (không phải sau toàn bộ match, có thể còn
        # kéo dài tới hết cụm "của ...") -- "khoản 2 Điều 5 năm" là số năm,
        # không phải viện dẫn thật.
        if _UNIT_AFTER.match(khoan.content, match.end("dieu")):
            continue

        raw_text = match.group(0).strip()
        target_document = resolve_document_phrase(
            match.group("doc_phrase"), khoan.source_document
        )
        if target_document is None:
            logger.info(
                "Bỏ qua viện dẫn không resolve được văn bản đích: raw_text=%r, "
                "breadcrumb=%r",
                raw_text,
                khoan.breadcrumb_root,
            )
            continue

        dieu_number = match.group("dieu")
        target_id = dieu_ids.get((target_document, dieu_number))
        if target_id is None:
            logger.info(
                "Bỏ qua viện dẫn tới Điều không có trong đồ thị: raw_text=%r, "
                "breadcrumb=%r, target_document=%r, target_dieu=%r",
                raw_text,
                khoan.breadcrumb_root,
                target_document,
                dieu_number,
            )
            continue

        khoan_number_text = match.group("khoan")
        if khoan_number_text is not None:
            khoan_target_id = khoan_ids.get(
                (target_document, dieu_number, khoan_number_text)
            )
            if khoan_target_id is not None:
                target_id = khoan_target_id

        edges.append(
            ReferenceEdge(
                source_id=source_id,
                target_id=target_id,
                raw_text=raw_text,
                target_diem=match.group("diem"),
            )
        )
    return edges
