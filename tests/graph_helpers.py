"""Helper và fixture markdown nhỏ cho test `graph/` (graph_spec.md mục 5, 7, 10).

Dựng file markdown + chunk JSON giả theo đúng quy ước breadcrumb của `chunking/`
(không nạp tokenizer) để test builder/pipeline mà không phụ thuộc `data/`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from production_legal_agentic_graph_rag.chunking.models import Chunk, DocumentTree
from production_legal_agentic_graph_rag.chunking.parser import parse_markdown
from production_legal_agentic_graph_rag.graph.builder import (
    BACKMATTER_SUFFIX,
    build_graph_document,
    scan_structure_headings,
)
from production_legal_agentic_graph_rag.graph.models import GraphDocument
from production_legal_agentic_graph_rag.graph.refs import resolve_references

# Văn bản gốc (Luật): Chương I (Điều 1 ngầm định, Điều 2 có Điểm), Chương II với
# Mục 1 (Điều 3 viện dẫn trong nhiều dạng, Điều 4 khoản có hậu tố chữ), Điều 48a.
GOC_MARKDOWN = """VĂN PHÒNG QUỐC HỘI

**LUẬT**

# MẪU

Lời mở đầu của luật mẫu.

## Chương I. QUY ĐỊNH CHUNG

#### Điều 1. Phạm vi điều chỉnh

Luật này quy định về việc mẫu.

#### Điều 2. Giải thích

##### Khoản 1

Cá nhân cư trú là người đáp ứng một trong các điều kiện sau đây:

a) Có mặt tại Việt Nam từ 183 ngày;

b) Có nơi ở thường xuyên tại Việt Nam.

##### Khoản 2

Cá nhân không cư trú là người không đáp ứng điều kiện quy định tại khoản 1 Điều này.

##### Khoản 3

Chính phủ quy định chi tiết Điều này.

## Chương II. QUY ĐỊNH RIÊNG

### Mục 1. Nhóm thứ nhất

#### Điều 3. Viện dẫn

##### Khoản 1

Thực hiện theo quy định tại Điều 1 của Luật này.

##### Khoản 2

Áp dụng điểm a khoản 1 Điều 2 và điểm b khoản 1 Điều 2.

##### Khoản 3

Theo quy định từ Điều 1 đến Điều 2 của Luật này.

##### Khoản 4

Theo khoản 3 Điều 2 và Điều 99 của Luật này.

#### Điều 4. Khoản có hậu tố

##### Khoản 1

Như quy định tại Điều 3.

##### Khoản 1a

Nội dung khoản 1a.

#### Điều 48a. Điều có hậu tố

Nội dung Điều 48a.

---

[1] Chú thích sửa đổi của luật mẫu.
"""

# Văn bản hướng dẫn: "Điều N" trần phải bị coi là ngoại; "… này" là nội bộ.
HUONG_DAN_MARKDOWN = """CHÍNH PHỦ

**NGHỊ ĐỊNH**

# HƯỚNG DẪN MẪU

Nghị định hướng dẫn mẫu.

## Chương I. QUY ĐỊNH CHUNG

#### Điều 1. Phạm vi

##### Khoản 1

Thực hiện theo khoản 2 Điều 1 của Nghị định này.

##### Khoản 2

Nội dung thứ hai.

#### Điều 2. Áp dụng

##### Khoản 1

Theo quy định tại Điều 1 và Điều 2.
"""


def breadcrumb_of(tree: DocumentTree, index: int) -> str:
    """Breadcrumb gốc (chưa có hậu tố Điểm/phần) của Khoản thứ `index`."""
    khoan = tree.khoans[index]
    if khoan.khoan_number is None:
        return khoan.breadcrumb_prefix
    return f"{khoan.breadcrumb_prefix} - Khoản {khoan.khoan_number}"


def make_chunk(
    breadcrumb: str,
    source_document: str,
    split: tuple[int, int] | None = None,
    suffix: str = "",
) -> Chunk:
    """Chunk giả với `chunk_id` deterministic từ breadcrumb (+ hậu tố)."""
    full = f"{breadcrumb}{suffix}"
    if split is not None:
        full = f"{full} (phần {split[0] + 1}/{split[1]})"
    return Chunk(
        chunk_id=hashlib.sha256(f"{source_document}|{full}".encode()).hexdigest(),
        source_document=source_document,
        breadcrumb=full,
        content="x",
        token_count=1,
        is_split=split is not None,
        split_index=split[0] if split else None,
        split_total=split[1] if split else None,
    )


def make_chunks(tree: DocumentTree) -> list[Chunk]:
    """Một chunk cho mỗi Khoản + front/back matter nếu có (đúng quy ước mục 5)."""
    chunks: list[Chunk] = []
    if tree.frontmatter_content:
        chunks.append(make_chunk(tree.source_document, tree.source_document))
    chunks.extend(
        make_chunk(breadcrumb_of(tree, index), tree.source_document)
        for index in range(len(tree.khoans))
    )
    if tree.backmatter_content:
        chunks.append(
            make_chunk(
                f"{tree.source_document} - {BACKMATTER_SUFFIX}", tree.source_document
            )
        )
    return chunks


def write_document(
    directory: Path, name: str, markdown: str
) -> tuple[Path, Path, list[Chunk]]:
    """Ghi `<name>.md` và `<name>.json` (chunk) vào `directory/markdown|chunks`."""
    markdown_dir = directory / "markdown"
    chunks_dir = directory / "chunks"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = markdown_dir / f"{name}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    chunks = make_chunks(parse_markdown(markdown_path))
    chunks_path = chunks_dir / f"{name}.json"
    chunks_path.write_text(
        json.dumps([chunk.model_dump() for chunk in chunks], ensure_ascii=False),
        encoding="utf-8",
    )
    return markdown_path, chunks_path, chunks


def build_from_markdown(
    directory: Path, name: str, markdown: str
) -> tuple[GraphDocument, DocumentTree, list[Chunk]]:
    """Dựng `GraphDocument` (chưa có cạnh viện dẫn) từ markdown fixture."""
    markdown_path, _, chunks = write_document(directory, name, markdown)
    tree = parse_markdown(markdown_path)
    headings = scan_structure_headings(markdown_path.read_text(encoding="utf-8"))
    return build_graph_document(tree, chunks, headings, name), tree, chunks


def build_with_references(directory: Path, name: str, markdown: str) -> GraphDocument:
    """Dựng graph kèm cạnh `REFERS_TO` (không chạy kiểm tra pipeline)."""
    graph, _, _ = build_from_markdown(directory, name, markdown)
    edges, _ = resolve_references(graph)
    return graph.model_copy(update={"references": edges})
