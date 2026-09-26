"""Parse breadcrumb -> toạ độ phân cấp; lọc front/back matter; gộp `is_split` (mục 6).

Module mới, không tái dùng `retrieval/citation.py` (mục 4 `graph_spec.md`).
Khác với việc đọc breadcrumb đơn giản kiểu `.split(" - ")` mô tả bằng lời ở
mục 6 bước 3, `_LEVEL_TOKEN` bên dưới định vị từng token cấp bằng regex thay
vì tách chuỗi ngây thơ theo `" - "`: tên Điều nguyên văn có thể tự chứa
`" - "` (dữ liệu thật, vd `"Điều 136. Trách nhiệm của Bộ Lao động - Thương
binh và Xã hội"`, `LUẬT BẢO HIỂM XÃ HỘI`) — tách ngây thơ sẽ cắt đứt tên Điều
thành 1 đoạn giả không khớp tiền tố cấp nào, khiến toàn bộ Khoản dưới Điều đó
bị coi là lỗi parse và mất khỏi đồ thị. Định vị bằng regex + validate thứ tự
xuất hiện (`_validate_order`) cho cùng kết quả với chuỗi hợp lệ nhưng không
vỡ trên tên Điều có `" - "`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from production_legal_agentic_graph_rag.chunking.models import Chunk
from production_legal_agentic_graph_rag.graph.models import (
    DieuCoordinate,
    KhoanCoordinate,
)

logger = logging.getLogger(__name__)

# 2 quy tắc front/back matter đã định nghĩa ở `chunking_spec.md` mục 5, dùng
# lại nguyên văn ở đây (mục 6 bước 1).
BACK_MATTER_MARKER = "Chú thích sửa đổi (cuối văn bản)"

_PART_SUFFIX = re.compile(r"\s*\(phần \d+/\d+\)\s*$")
# "- Điểm a, b" luôn là hậu tố cuối cùng khi Khoản có Điểm bị tách (mục 6 bước 2).
_DIEM_SUFFIX = re.compile(r"\s*-\s*Điểm [^-]+$")

# Value ngay sau từ khoá cấp phải là số La Mã/số thường (có thể kèm 1 chữ cái
# hậu tố, vd "Điều 48a", "Khoản 3a" -- dữ liệu thật `Luật bảo hiểm y tế`/`Luật
# bảo hiểm xã hội`, cùng lý do `chunking/models.py::KhoanNode.khoan_number` là
# `str`), theo sau bởi dấu "." (chỉ Điều có tên sau số, `chunking_spec.md` mục
# 4) hoặc khoảng trắng/hết chuỗi (ranh giới sang token cấp kế tiếp) -- tránh
# khớp nhầm từ thường đứng sau "Điều"/"Mục" trong tên Điều (vd "Điều kiện",
# không có chữ số theo sau nên không khớp).
_LEVEL_TOKEN = re.compile(
    r" - (?P<level>Phần|Chương|Mục|Điều|Khoản) "
    r"(?P<value>[IVXLCDM]+|\d+[a-zđ]?)(?=[.\s]|$)"
)
_LEVEL_ORDER = {"Phần": 0, "Chương": 1, "Mục": 2, "Điều": 3, "Khoản": 4}


class BreadcrumbParseError(ValueError):
    """Breadcrumb gốc không khớp pattern cấp nào theo đúng thứ tự (mục 6 bước 5)."""


def is_front_or_back_matter(breadcrumb: str, source_document: str) -> bool:
    """2 quy tắc nhận diện front/back matter của `chunking_spec.md` mục 5.

    Front matter: breadcrumb (sau khi bỏ hậu tố `(phần i/n)`) đúng bằng
    `source_document`. Back matter: chứa `BACK_MATTER_MARKER`.
    """
    stripped = _PART_SUFFIX.sub("", breadcrumb)
    return stripped == source_document or BACK_MATTER_MARKER in stripped


def root_breadcrumb(breadcrumb: str) -> str:
    """`breadcrumb` gốc dùng làm khoá gộp mọi mảnh `is_split` (mục 6 bước 2).

    Cắt hậu tố `(phần i/n)` trước, rồi hậu tố `- Điểm ...` (nếu có) -- đúng
    thứ tự mô tả ở mục 6 bước 2 vì `(phần i/n)` luôn đứng sau `- Điểm ...`
    trong breadcrumb gốc.
    """
    without_part = _PART_SUFFIX.sub("", breadcrumb)
    return _DIEM_SUFFIX.sub("", without_part)


def _validate_order(matches: Sequence[re.Match[str]], breadcrumb: str) -> None:
    last_rank = -1
    for match in matches:
        rank = _LEVEL_ORDER[match.group("level")]
        if rank <= last_rank:
            # Cấp thấp hơn xuất hiện sau cấp cao hơn -- token khớp nhầm bên
            # trong tên Điều (guard cho ca `" - "` trong tên, xem docstring
            # module), không phải toạ độ hợp lệ.
            raise BreadcrumbParseError(breadcrumb)
        last_rank = rank


def parse_path(
    breadcrumb_root: str,
) -> tuple[str | None, str | None, str | None, DieuCoordinate, str | None]:
    """Toạ độ phân cấp (Phan, Chuong, Muc, Dieu, so_khoan) từ breadcrumb gốc.

    Trả về `so_khoan=None` cho "Khoản ngầm định cấp Điều" (breadcrumb dừng ở
    Điều, không có token `Khoản` -- `chunking_spec.md` mục 4 "Nội dung không
    có heading Khoản"); đây vẫn là 1 Khoản pháp lý hợp lệ (mục 3 bất biến 2),
    `builder.py` vẫn tạo 1 node `Khoan` cho nó (mục 5 `KhoanNode`).

    Raises:
        BreadcrumbParseError: Không có token `Điều` nào (v1 chưa hỗ trợ
            "Khoản gộp không có Điều bao ngoài" -- `graph_spec.md` mục 12 liệt
            kê đây là việc cần làm khi mở rộng corpus, không phải v1 hiện
            tại), hoặc các token khớp được không theo đúng thứ tự hierarchy.
    """
    matches = list(_LEVEL_TOKEN.finditer(breadcrumb_root))
    if not matches:
        raise BreadcrumbParseError(breadcrumb_root)
    _validate_order(matches, breadcrumb_root)

    values = {match.group("level"): match for match in matches}
    dieu_match = values.get("Điều")
    if dieu_match is None:
        raise BreadcrumbParseError(breadcrumb_root)

    phan = values["Phần"].group("value") if "Phần" in values else None
    chuong = values["Chương"].group("value") if "Chương" in values else None
    muc = values["Mục"].group("value") if "Mục" in values else None
    khoan_match = values.get("Khoản")
    khoan_number = khoan_match.group("value") if khoan_match is not None else None

    next_start = next(
        (m.start() for m in matches if m.start() > dieu_match.start()),
        len(breadcrumb_root),
    )
    title = breadcrumb_root[dieu_match.end() : next_start].lstrip(". ").strip()
    dieu = DieuCoordinate(number=dieu_match.group("value"), title=title)
    return phan, chuong, muc, dieu, khoan_number


def group_khoans(chunks: Sequence[Chunk]) -> tuple[list[KhoanCoordinate], int, int]:
    """Lọc front/back matter, parse breadcrumb, gộp `is_split` (mục 6).

    Nhóm theo `(source_document, breadcrumb gốc)` trước khi parse toạ độ, nên
    việc gộp mảnh `is_split` không phụ thuộc kết quả parse (mục 6 bước 4:
    "không tin thứ tự chunk trong file JSON" -- sắp theo `split_index`).

    Returns:
        `(danh sách KhoanCoordinate, số chunk front/back matter bị bỏ qua,
        số chunk breadcrumb không parse được)`. Lỗi parse không chặn batch
        (bất biến 6, mục 3); đã log `source_document`/`chunk_id` liên quan.
    """
    front_back_count = 0
    groups: dict[tuple[str, str], list[Chunk]] = {}
    for chunk in chunks:
        if is_front_or_back_matter(chunk.breadcrumb, chunk.source_document):
            front_back_count += 1
            continue
        key = (chunk.source_document, root_breadcrumb(chunk.breadcrumb))
        groups.setdefault(key, []).append(chunk)

    coordinates: list[KhoanCoordinate] = []
    unparseable_count = 0
    for (source_document, breadcrumb_root), members in groups.items():
        try:
            phan, chuong, muc, dieu, khoan_number = parse_path(breadcrumb_root)
        except BreadcrumbParseError:
            unparseable_count += len(members)
            logger.warning(
                "Bỏ qua %d chunk, breadcrumb không parse được: source_document=%r, "
                "chunk_id=%r",
                len(members),
                source_document,
                [member.chunk_id for member in members],
            )
            continue

        ordered = sorted(members, key=lambda member: member.split_index or 0)
        coordinates.append(
            KhoanCoordinate(
                source_document=source_document,
                phan=phan,
                chuong=chuong,
                muc=muc,
                dieu=dieu,
                khoan_number=khoan_number,
                breadcrumb_root=breadcrumb_root,
                chunk_ids=[member.chunk_id for member in ordered],
                content="\n".join(member.content for member in ordered),
            )
        )

    return coordinates, front_back_count, unparseable_count
