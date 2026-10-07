"""Contract Pydantic v2 của package `graph/` (graph_spec.md mục 4, 9, 10).

Gồm node/cạnh của knowledge graph, `GraphDocument` (toàn bộ graph của một
văn bản, đơn vị ghi một transaction), báo cáo ingest và các view đọc cho truy
vấn mẫu (mục 11).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class NodeLabel(StrEnum):
    """Nhãn node Neo4j. Giá trị là hằng số cố định, được phép nội suy vào Cypher."""

    DOCUMENT = "Document"
    PART = "Part"
    CHAPTER = "Chapter"
    SECTION = "Section"
    ARTICLE = "Article"
    CLAUSE = "Clause"
    POINT = "Point"


# Nhãn node con -> kiểu cạnh cấu trúc trỏ tới nó (mục 4).
STRUCTURAL_REL_BY_CHILD: dict[NodeLabel, str] = {
    NodeLabel.PART: "HAS_PART",
    NodeLabel.CHAPTER: "HAS_CHAPTER",
    NodeLabel.SECTION: "HAS_SECTION",
    NodeLabel.ARTICLE: "HAS_ARTICLE",
    NodeLabel.CLAUSE: "HAS_CLAUSE",
    NodeLabel.POINT: "HAS_POINT",
}


class DocumentKind(StrEnum):
    """Loại văn bản (mục 6): quyết định cách xử lý viện dẫn "Điều N" trần."""

    GOC = "goc"
    HUONG_DAN = "huong_dan"


class ReferenceKind(StrEnum):
    """Dạng viện dẫn (mục 4)."""

    SINGLE = "single"
    RANGE = "range"


class DocumentNode(BaseModel):
    """Node `Document`."""

    node_label: Literal[NodeLabel.DOCUMENT] = NodeLabel.DOCUMENT
    id: str
    order: int = 1
    parent_id: None = None
    name: str
    short_name: str
    kind: DocumentKind
    front_text: str | None = None
    back_text: str | None = None
    front_chunk_ids: list[str] = Field(default_factory=list)
    back_chunk_ids: list[str] = Field(default_factory=list)


class StructureNode(BaseModel):
    """Node `Part`/`Chapter`/`Section` (cùng thuộc tính, khác nhãn)."""

    node_label: Literal[NodeLabel.PART, NodeLabel.CHAPTER, NodeLabel.SECTION]
    id: str
    order: int
    parent_id: str
    number: int
    label: str
    title: str
    char_count: int = 0


class ArticleNode(BaseModel):
    """Node `Article` (Điều); `label` là chuỗi đúng như văn bản (`"48a"`)."""

    node_label: Literal[NodeLabel.ARTICLE] = NodeLabel.ARTICLE
    id: str
    order: int
    parent_id: str
    label: str
    title: str
    char_count: int = 0


class ClauseNode(BaseModel):
    """Node `Clause` (Khoản); `label` là `None` với Khoản ngầm định cấp Điều."""

    node_label: Literal[NodeLabel.CLAUSE] = NodeLabel.CLAUSE
    id: str
    order: int
    parent_id: str
    label: str | None = None
    text: str
    chunk_ids: list[str]
    implicit: bool = False
    has_table: bool = False
    raw_table: str | None = None


class PointNode(BaseModel):
    """Node `Point` (Điểm); không có `chunk_id` riêng."""

    node_label: Literal[NodeLabel.POINT] = NodeLabel.POINT
    id: str
    order: int
    parent_id: str
    label: str
    text: str


class StructuralEdge(BaseModel):
    """Cạnh cấu trúc cha -> con trực tiếp."""

    parent_label: NodeLabel
    parent_id: str
    child_label: NodeLabel
    child_id: str


class ReferenceEdge(BaseModel):
    """Cạnh `REFERS_TO` đã phân giải, từ Khoản/Điểm tới Điều/Khoản/Điểm (mục 4)."""

    source_label: NodeLabel
    source_id: str
    target_label: NodeLabel
    target_id: str
    raw_text: str
    kind: ReferenceKind


class ReferenceStats(BaseModel):
    """Bộ đếm kết quả phân giải viện dẫn (mục 9)."""

    external: int = 0
    unresolved_target: int = 0
    bare_huong_dan: int = 0
    self_skipped: int = 0


class GraphDocument(BaseModel):
    """Toàn bộ graph của một văn bản: đơn vị ghi một transaction (mục 3, 8)."""

    document: DocumentNode
    structures: list[StructureNode] = Field(default_factory=list)
    articles: list[ArticleNode] = Field(default_factory=list)
    clauses: list[ClauseNode] = Field(default_factory=list)
    points: list[PointNode] = Field(default_factory=list)
    references: list[ReferenceEdge] = Field(default_factory=list)

    def all_nodes(
        self,
    ) -> list[DocumentNode | StructureNode | ArticleNode | ClauseNode | PointNode]:
        """Mọi node theo thứ tự cha trước con (thứ tự ghi)."""
        return [
            self.document,
            *self.structures,
            *self.articles,
            *self.clauses,
            *self.points,
        ]

    def units(self) -> list[StructureNode | ArticleNode]:
        """Node có tiêu đề (Phần/Chương/Mục/Điều), dùng cho mục lục và `char_count`."""
        return [*self.structures, *self.articles]

    def structural_edges(self) -> list[StructuralEdge]:
        """Cạnh cấu trúc suy từ `parent_id` của từng node."""
        label_by_id = {node.id: node.node_label for node in self.all_nodes()}
        return [
            StructuralEdge(
                parent_label=label_by_id[node.parent_id],
                parent_id=node.parent_id,
                child_label=node.node_label,
                child_id=node.id,
            )
            for node in self.all_nodes()
            if node.parent_id is not None
        ]


class DocumentReport(BaseModel):
    """Báo cáo ingest một văn bản (mục 9)."""

    short_name: str
    node_counts: dict[str, int]
    refers_to_edges: int
    external_refs: int
    unresolved_target_refs: int
    bare_huong_dan_refs: int
    self_refs_skipped: int
    repealed_clauses: int
    chunk_count: int


class DocumentOutcome(BaseModel):
    """Kết quả xử lý một văn bản trong batch."""

    short_name: str
    status: Literal["written", "dry_run", "failed"]
    report: DocumentReport | None = None
    error: str | None = None


# --- View đọc cho truy vấn mẫu (mục 11) ---


class ClauseView(BaseModel):
    """Khoản trả về từ truy vấn đọc."""

    label: str | None
    order: int
    text: str
    chunk_ids: list[str]
    implicit: bool


class TocEntry(BaseModel):
    """Một dòng mục lục: con trực tiếp của Phần/Chương/Mục hoặc cha của Khoản."""

    node_label: NodeLabel
    label: str
    title: str
    order: int
    char_count: int


class ClauseContext(BaseModel):
    """Ngữ cảnh cấu trúc của một Khoản tìm theo `chunk_id`."""

    clause: ClauseView
    article: TocEntry
    sibling_clauses: list[ClauseView]
    parent: TocEntry | None
    sibling_articles: list[TocEntry]


class ReferenceCard(BaseModel):
    """Thẻ viện dẫn (mục 4): toàn văn đích chưa mở, chỉ kèm thông tin để quyết định mở."""

    raw_text: str
    kind: ReferenceKind
    node_label: NodeLabel
    label: str | None
    article_label: str
    article_title: str
    char_count: int


class ReferenceCards(BaseModel):
    """Viện dẫn đi ra và đi vào của một Khoản hoặc Điều."""

    outgoing: list[ReferenceCard] = Field(default_factory=list)
    incoming: list[ReferenceCard] = Field(default_factory=list)
