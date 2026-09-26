"""Bảng văn bản trong corpus + chuẩn hoá text cho `graph/` (mục 4, 7, 10 `graph_spec.md`).

Bản sao độc lập của `graph/` cho bảng văn bản + fold text — không import
`retrieval.citation` (package đang tạm ngoài phạm vi phát triển, xem
`CLAUDE.md` mục 3 và `graph_spec.md` mục 4), dù nội dung bảng khớp với
`retrieval/citation.py::DOCUMENTS` vì cùng mô tả 6 văn bản mẫu hiện có trong
`data/raw`. Thêm văn bản mới vào corpus phải cập nhật `DOCUMENTS` ở đây
(`graph_spec.md` mục 12).
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

# Sentinel cho "chính văn bản đang xét" trong `_ALIAS_PATTERNS` — phân biệt
# với alias trỏ tới 1 `source_document` cụ thể khác trong `DOCUMENTS`.
_SELF_REFERENCE = "__self__"


def fold(text: str) -> str:
    """NFC + lowercase + bỏ dấu (kể cả đ -> d) + gộp khoảng trắng (mục 7)."""
    decomposed = unicodedata.normalize("NFD", unicodedata.normalize("NFC", text))
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(stripped.lower().replace("đ", "d").split())


class DocumentEntry(NamedTuple):
    """Văn bản trong corpus: key nguyên văn (`source_document`) + alias đã fold."""

    source_document: str
    aliases: tuple[str, ...]


def _entry(source_document: str, *aliases: str) -> DocumentEntry:
    return DocumentEntry(source_document, tuple(fold(alias) for alias in aliases))


# Cụm tự-tham-chiếu ("của Luật này", ...) -- luôn resolve về chính văn bản
# đang xét, bất kể văn bản nào (mục 7).
SELF_REFERENCE_ALIASES: tuple[str, ...] = tuple(
    fold(alias)
    for alias in (
        "luật này",
        "bộ luật này",
        "nghị định này",
        "thông tư này",
        "pháp lệnh này",
        "văn bản này",
    )
)

# `source_document` nguyên văn trong `data/chunks` -> alias hay dùng khi viện
# dẫn tới nó từ văn bản khác (mục 7). Alias chỉ gồm tên có tiền tố luật/bộ
# luật/nghị định hoặc chữ viết tắt, không phải tên chủ đề trơn (dễ trùng lặp
# nhiều văn bản). Thêm/đổi văn bản trong corpus phải cập nhật bảng này (mục 12).
DOCUMENTS: dict[str, DocumentEntry] = {
    "BỘ LUẬT LAO ĐỘNG": _entry(
        "BỘ LUẬT LAO ĐỘNG", "bộ luật lao động", "luật lao động", "blld"
    ),
    "LUẬT BẢO HIỂM XÃ HỘI": _entry(
        "LUẬT BẢO HIỂM XÃ HỘI", "luật bảo hiểm xã hội", "luật bhxh"
    ),
    "LUẬT BẢO HIỂM Y TẾ": _entry(
        "LUẬT BẢO HIỂM Y TẾ", "luật bảo hiểm y tế", "luật bhyt"
    ),
    "LUẬT THUẾ THU NHẬP CÁ NHÂN": _entry(
        "LUẬT THUẾ THU NHẬP CÁ NHÂN",
        "luật thuế thu nhập cá nhân",
        "luật thuế tncn",
        "thuế thu nhập cá nhân",
        "thuế tncn",
    ),
    "NGHỊ ĐỊNH QUY ĐỊNH MỨC LƯƠNG TỐI THIỂU ĐỐI VỚI NGƯỜI LAO ĐỘNG LÀM VIỆC THEO HỢP ĐỒNG LAO ĐỘNG": _entry(
        "NGHỊ ĐỊNH QUY ĐỊNH MỨC LƯƠNG TỐI THIỂU ĐỐI VỚI NGƯỜI LAO ĐỘNG LÀM VIỆC THEO HỢP ĐỒNG LAO ĐỘNG",
        "nghị định lương tối thiểu",
        "nghị định mức lương tối thiểu",
        "nghị định quy định mức lương tối thiểu",
    ),
    "NGHỊ ĐỊNH QUY ĐỊNH CHI TIẾT VÀ HƯỚNG DẪN THI HÀNH MỘT SỐ ĐIỀU CỦA BỘ LUẬT LAO ĐỘNG VỀ ĐIỀU KIỆN LAO ĐỘNG VÀ QUAN HỆ LAO ĐỘNG": _entry(
        "NGHỊ ĐỊNH QUY ĐỊNH CHI TIẾT VÀ HƯỚNG DẪN THI HÀNH MỘT SỐ ĐIỀU CỦA BỘ LUẬT LAO ĐỘNG VỀ ĐIỀU KIỆN LAO ĐỘNG VÀ QUAN HỆ LAO ĐỘNG",
        "nghị định điều kiện lao động",
        "nghị định quan hệ lao động",
        "nghị định hướng dẫn bộ luật lao động",
        "nghị định về điều kiện lao động và quan hệ lao động",
    ),
}

# (source_document đích | sentinel tự-tham-chiếu, alias đã fold) — dùng chung
# 1 danh sách để `resolve_document_phrase` chọn alias dài nhất khi chồng lấn,
# thay vì phải so 2 vòng lặp riêng cho self-reference và văn bản khác.
_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (_SELF_REFERENCE, re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"))
    for alias in SELF_REFERENCE_ALIASES
] + [
    (source_document, re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"))
    for source_document, entry in DOCUMENTS.items()
    for alias in entry.aliases
]


def resolve_document_phrase(phrase: str | None, own_document: str) -> str | None:
    """`source_document` đích của cụm "của <phrase>" trong 1 câu viện dẫn (mục 7).

    Áp đúng 4 nhánh của mục 7 `graph_spec.md`:

    1. `phrase` rỗng (không có cụm "của ...") -> cùng văn bản (`own_document`).
    2. Khớp 1 cụm tự-tham-chiếu ("luật này", ...) -> cùng văn bản.
    3. Khớp alias của 1 văn bản khác trong `DOCUMENTS` -> văn bản đó.
    4. Không khớp alias nào -> `None` (không resolve được, gọi phía trên bỏ
       qua + log, không suy luận thêm — bất biến 5).

    Khi nhiều alias chồng lấn trong `phrase`, alias dài nhất thắng (cùng
    nguyên tắc `retrieval/citation.py::detect_document`, không tái dùng code).

    Args:
        phrase: Cụm văn bản bắt được sau "của" trong câu viện dẫn, hoặc
            `None` khi câu viện dẫn không có "của ...".
        own_document: `source_document` của Khoản đang chứa câu viện dẫn.
    """
    if phrase is None:
        return own_document

    folded = fold(phrase)
    spans: list[tuple[int, int, str]] = []
    for key, pattern in _ALIAS_PATTERNS:
        spans.extend((m.start(), m.end(), key) for m in pattern.finditer(folded))
    if not spans:
        return None

    spans.sort(key=lambda span: span[0] - span[1])  # đoạn khớp dài nhất trước
    best_key = spans[0][2]
    return own_document if best_key == _SELF_REFERENCE else best_key
