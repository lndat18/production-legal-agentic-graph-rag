"""Pydantic contracts trao đổi giữa các module của `graph/` (mục 10 `graph_spec.md`).

`DieuCoordinate`/`KhoanCoordinate` là kết quả trung gian của `breadcrumb.py`
(một Khoản pháp lý đã gộp `is_split`, trước khi build node/edge). `GraphNode`
gộp 6 kiểu node (`VanBanNode`.../`KhoanNode`, mục 5); `HasChildEdge`/
`ReferenceEdge` là 2 loại relationship duy nhất. `GraphDocument` là kết quả
cuối cùng của `builder.py`, ghi thẳng vào Neo4j bởi `neo4j_client.py` — không
có bước checkpoint JSON trung gian (mục 2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DieuCoordinate(BaseModel):
    """Toạ độ 1 Điều: số + tên, tách bởi dấu `.` đầu tiên sau số (mục 6 bước 3).

    `number` là `str` chứ không phải `int`: số Điều trong corpus thật có thể
    mang hậu tố chữ (`"48a"`, `"7b"` — `Luật bảo hiểm y tế`, cùng lý do
    `chunking/models.py::KhoanNode.khoan_number` đã chọn `str | None` thay vì
    `int`). Ép `int` sẽ làm mất phân biệt "Điều 7" với "Điều 7a" và khiến toàn
    bộ Khoản dưới các Điều có hậu tố chữ bị coi là lỗi parse (mất khỏi đồ thị)
    — vi phạm mục 11 "mọi Khoản ... có đúng một node Khoan".
    """

    number: str
    title: str


class KhoanCoordinate(BaseModel):
    """1 Khoản đã gộp mọi mảnh `is_split`, trước khi build `GraphDocument` (mục 6).

    `content` là nội dung nối theo thứ tự `split_index` của mọi mảnh, chỉ
    dùng tạm trong bộ nhớ để `references.py` quét viện dẫn chéo (mục 7) —
    không bao giờ được ghi vào `KhoanNode` hay bất kỳ node nào khác (bất biến
    1, mục 3: node không lưu content).
    """

    source_document: str
    phan: str | None = None
    chuong: str | None = None
    muc: str | None = None
    dieu: DieuCoordinate
    khoan_number: str | None
    breadcrumb_root: str
    chunk_ids: list[str] = Field(default_factory=list)
    content: str


class VanBanNode(BaseModel):
    """Gốc cây 1 văn bản pháp luật. `id` dùng trực tiếp `source_document`."""

    id: str
    source_document: str


class PhanNode(BaseModel):
    """Cấp Phần/Phụ lục. `label` giữ nguyên văn sau `Phần ` (số La Mã nếu có)."""

    id: str
    label: str


class ChuongNode(BaseModel):
    """Cấp Chương. `label` giữ nguyên văn sau `Chương `."""

    id: str
    label: str


class MucNode(BaseModel):
    """Cấp Mục. `label` giữ nguyên văn sau `Mục `."""

    id: str
    label: str


class DieuNode(BaseModel):
    """Cấp Điều.

    `number` là `str` (không phải `int`) vì có thể mang hậu tố chữ (`"48a"`),
    xem `DieuCoordinate.number`.
    """

    id: str
    number: str
    title: str


class KhoanNode(BaseModel):
    """Cấp Khoản — đơn vị nội dung nhỏ nhất có identity trong đồ thị (bất biến 2).

    `number` là `None` cho "Khoản ngầm định cấp Điều" (nội dung nằm trực
    tiếp dưới Điều, không có heading Khoản riêng — `chunking_spec.md` mục 4
    "Nội dung không có heading Khoản"). Trường hợp này vẫn là 1 Khoản pháp lý
    thật có nội dung cần giữ (`KhoanNode.khoan_number: None` bên
    `chunking/models.py`), nên vẫn có 1 node `Khoan` riêng thay vì gộp vào
    `Dieu` — `Dieu` không có `chunk_ids` (mục 5), gộp vào đó sẽ làm mất
    `chunk_ids` của nội dung này.
    """

    id: str
    number: str | None
    chunk_ids: list[str] = Field(default_factory=list)
    breadcrumb: str


GraphNode = VanBanNode | PhanNode | ChuongNode | MucNode | DieuNode | KhoanNode


class HasChildEdge(BaseModel):
    """Cạnh `HAS_CHILD` giữa 2 cấp liền kề bất kỳ, bỏ cấp vắng mặt (mục 5)."""

    parent_id: str
    child_id: str


class ReferenceEdge(BaseModel):
    """Cạnh `REFERENCES` từ 1 `Khoan` tới `Dieu`/`Khoan` đích (mục 5, 7)."""

    source_id: str
    target_id: str
    raw_text: str
    target_diem: str | None = None


class GraphDocument(BaseModel):
    """Toàn bộ node/relationship dựng từ 1 batch chunk, trước khi ghi Neo4j.

    Node gom theo label (không phải 1 list `GraphNode` chung) để
    `neo4j_client.py` chạy đúng 1 câu `UNWIND ... MERGE` tĩnh cho mỗi label
    (mục 4, 10) mà không cần phân loại lại node bằng `isinstance` khi ghi.
    """

    van_bans: list[VanBanNode] = Field(default_factory=list)
    phans: list[PhanNode] = Field(default_factory=list)
    chuongs: list[ChuongNode] = Field(default_factory=list)
    mucs: list[MucNode] = Field(default_factory=list)
    dieus: list[DieuNode] = Field(default_factory=list)
    khoans: list[KhoanNode] = Field(default_factory=list)
    has_child_edges: list[HasChildEdge] = Field(default_factory=list)
    references: list[ReferenceEdge] = Field(default_factory=list)


class IngestResult(BaseModel):
    """Thống kê 1 lần `pipeline.run_ingest()` (mục 10, 11)."""

    files_processed: int = 0
    files_failed: int = 0
    chunks_read: int = 0
    skipped_front_back_matter: int = 0
    skipped_unparseable_breadcrumb: int = 0
    node_counts: dict[str, int] = Field(default_factory=dict)
    edge_counts: dict[str, int] = Field(default_factory=dict)
