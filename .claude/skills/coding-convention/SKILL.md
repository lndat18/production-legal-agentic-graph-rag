---
name: coding-convention
description: Quy ước coding chuẩn production cho project — kiến trúc thư mục, naming, format, docstring, và bộ công cụ hiện đại (pydantic, typer, ruff)
---
# Coding convention chuẩn production

## Kiến trúc thư mục & package

- Mọi source import được nằm trong `src/production_legal_agentic_graph_rag/`.
- Mỗi logic nghiệp vụ một package riêng, vd. chunking → `src/production_legal_agentic_graph_rag/chunking/`.
- Trong package, chia nhiều module theo logic; không gộp vào một file.
- Spec không cần liệt kê test cụ thể (agent `tester` đảm nhiệm) nhưng phải mô tả đủ hành vi quan trọng, gồm lỗi và trường hợp biên, vì `tester` và `reviewer` suy test từ spec.
- Phụ thuộc dịch vụ ngoài (Neo4j...): ghi rõ dùng fake qua interface mỏng hay cần integration thật (marker `integration`).

## Naming

- Module/file `snake_case.py`; class `PascalCase`; function/variable `snake_case`; constant `UPPER_SNAKE_CASE`; private `_underscore`.
- Tên mô tả rõ hành vi, tránh viết tắt tối nghĩa (`chunk_legal_document`, không `proc_doc`).

## Định dạng & cấu trúc mã

- Format bằng **Ruff** (`ruff format` + `ruff check`, cấu hình trong `pyproject.toml`); thay Black/isort/flake8.
- Type hint bắt buộc cho mọi function signature (tham số + return).
- `src/` layout; import order stdlib → third-party → local, cách nhau một dòng trắng (Ruff tự sắp).
- Mỗi function làm một việc, ~40–50 dòng trở xuống; tách nhỏ khi logic phức tạp.

## Comments

- Giải thích **tại sao**, không giải thích **cái gì**.
- Không comment thừa/lặp tên hàm.
- Việc chưa xong: `# TODO:` / `# FIXME:` kèm ngữ cảnh ngắn.

## Docstring (PEP 8 / PEP 257)

- Mọi module, class, public function đều có docstring.
- Module-level: mỗi file `.py` mở đầu bằng docstring mô tả module làm gì, đặt ngay dòng đầu, trước import.
- Format: dòng tóm tắt → dòng trống → mô tả chi tiết (nếu cần) → `Args:` / `Returns:` / `Raises:` (với function).

Module-level:

```python
"""Tách văn bản pháp luật thành các đoạn nhỏ theo cấp Khoản/Điểm.

Module này xử lý bước chunking trong pipeline ingestion, nhận đầu vào là
Markdown đã chuẩn hóa và trả về danh sách đoạn văn bản sẵn sàng embedding.
"""

from production_legal_agentic_graph_rag.chunking.models import Chunk
```

Function-level:

```python
def split_by_khoan(text: str, max_tokens: int = 192) -> list[str]:
    """Tách văn bản pháp luật thành các đoạn theo cấp Khoản.

    Args:
        text: Nội dung văn bản đầu vào đã chuẩn hóa.
        max_tokens: Giới hạn token tối đa mỗi đoạn.

    Returns:
        Danh sách các đoạn văn bản đã tách.
    """
```

## Data validation: Pydantic

- Mọi cấu trúc dữ liệu trao đổi giữa các package (input/output pipeline) dùng **Pydantic v2** `BaseModel`; không dùng `dict` thô hay `dataclass` trần.
- Validate kiểu tại runtime, giảm lỗi ẩn khi dữ liệu ngoài (docx, API) sai format.

## CLI: Typer

- Mọi script/CLI trong `tools/` dùng **Typer**, không dùng `argparse`.
- Typer tự sinh validation, help và autocomplete từ signature; ít boilerplate hơn.

## Công cụ nền tảng (2026 stack, miễn phí)

| Việc | Công cụ | Thay cho |
| --- | --- | --- |
| Quản lý dependency | `uv` | pip, pip-tools, poetry, pyenv |
| Lint + format | `ruff` | black, isort, flake8, pyupgrade |
| Type check | `mypy` (hoặc `ty` beta: nhanh hơn nhưng chưa đủ plugin cho pydantic) | — |
| Validate dữ liệu | `pydantic` v2 | dataclass thô, dict validation tay |
| CLI | `typer` | argparse |
| Audit dependency | `pip-audit` | — |

- Bảng trên dùng xuyên suốt repo, không đổi theo từng bài toán.

## Chọn thư viện cho bài toán cụ thể

- Ngoài bảng trên là quyết định mở theo từng bài toán; không có danh sách cố định "luôn dùng X cho Y".
- Ưu tiên phương án đo được là hiệu quả nhất cho đúng bài toán: code ngắn hơn, ít bề mặt lỗi, ít round-trip/I/O, dễ test; dựa trên bằng chứng (tài liệu chính thức, benchmark, số dòng/độ phức tạp thực tế), không dựa thói quen hay "nghe quen tên".
- Cân nhắc thêm:
  - cộng đồng lớn, dùng trong production 2026
  - hiệu năng cao nếu có lựa chọn tương đương
  - miễn phí/open-source
  - tích hợp tốt với stack hiện tại (Pydantic, Typer...)
- Không suy diễn một quyết định thành rule chung: lựa chọn tốt cho bài toán này (vd. ingest dữ liệu có cấu trúc sẵn) có thể không tốt cho bài toán nhìn giống nó (vd. truy vấn ngôn ngữ tự nhiên trên cùng dữ liệu).
- Quyết định cụ thể kèm lý do so sánh ghi trong `*_spec.md` của package (mục "Công cụ & công nghệ"), không ghi ở file này.
