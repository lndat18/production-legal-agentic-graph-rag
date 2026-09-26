"""Ghi `GraphDocument` vào Neo4j bằng UNWIND batch (mục 4, 8, 10 `graph_spec.md`).

Driver chính thức `neo4j`, API `execute_query()` (tự quản lý session/
transaction/retry). Một câu Cypher tĩnh `UNWIND ... MERGE` cho mỗi label node
và mỗi relationship type — không loop `MERGE` từng node/edge (mục 4). Full
rebuild (mục 8): corpus nhỏ nên `MATCH (n) DETACH DELETE n` rồi ingest lại
toàn bộ mỗi lần chạy, thay vì incremental.
"""

from __future__ import annotations

from typing import Any, Self

from neo4j import GraphDatabase

from production_legal_agentic_graph_rag.config import GraphSettings
from production_legal_agentic_graph_rag.graph.models import GraphDocument

# Mọi node còn mang thêm label chung `Node` để 2 câu MERGE relationship
# (`HAS_CHILD`, `REFERENCES`) match được node 2 đầu chỉ bằng `id`, không cần
# biết trước label cụ thể (`VanBan`/`Phan`/.../`Khoan`) của node đó -- tránh
# phải sinh N câu Cypher khác nhau theo từng cặp label (mục 4: "một số nhỏ
# câu Cypher tĩnh"). Constraint unique trên `id` đặt trên label chung này.
_CONSTRAINT = (
    "CREATE CONSTRAINT graph_node_id IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE"
)

_WIPE = "MATCH (n) DETACH DELETE n"

_MERGE_VAN_BAN = (
    "UNWIND $rows AS row "
    "MERGE (n:VanBan:Node {id: row.id}) "
    "SET n.source_document = row.source_document"
)
_MERGE_PHAN = (
    "UNWIND $rows AS row MERGE (n:Phan:Node {id: row.id}) SET n.label = row.label"
)
_MERGE_CHUONG = (
    "UNWIND $rows AS row MERGE (n:Chuong:Node {id: row.id}) SET n.label = row.label"
)
_MERGE_MUC = (
    "UNWIND $rows AS row MERGE (n:Muc:Node {id: row.id}) SET n.label = row.label"
)
_MERGE_DIEU = (
    "UNWIND $rows AS row "
    "MERGE (n:Dieu:Node {id: row.id}) "
    "SET n.number = row.number, n.title = row.title"
)
_MERGE_KHOAN = (
    "UNWIND $rows AS row "
    "MERGE (n:Khoan:Node {id: row.id}) "
    "SET n.number = row.number, n.chunk_ids = row.chunk_ids, "
    "n.breadcrumb = row.breadcrumb"
)
_MERGE_HAS_CHILD = (
    "UNWIND $rows AS row "
    "MATCH (parent:Node {id: row.parent_id}) "
    "MATCH (child:Node {id: row.child_id}) "
    "MERGE (parent)-[:HAS_CHILD]->(child)"
)
_MERGE_REFERENCES = (
    "UNWIND $rows AS row "
    "MATCH (source:Khoan:Node {id: row.source_id}) "
    "MATCH (target:Node {id: row.target_id}) "
    "MERGE (source)-[r:REFERENCES {raw_text: row.raw_text}]->(target) "
    "SET r.target_diem = row.target_diem"
)


class Neo4jClient:
    """Kết nối Neo4j, full rebuild `GraphDocument` bằng UNWIND batch (mục 8)."""

    def __init__(self, settings: GraphSettings | None = None) -> None:
        self._settings = settings or GraphSettings()
        self._driver = GraphDatabase.driver(
            self._settings.uri, auth=(self._settings.user, self._settings.password)
        )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def _run(self, query: str, rows: list[dict[str, Any]]) -> None:
        self._driver.execute_query(query, rows=rows, database_=self._settings.database)

    def ensure_constraints(self) -> None:
        """Tạo constraint `id` unique trên label `Node` nếu chưa có (idempotent)."""
        self._driver.execute_query(_CONSTRAINT, database_=self._settings.database)

    def wipe(self) -> None:
        """Xoá sạch đồ thị hiện có -- bước đầu của full rebuild (mục 8)."""
        self._driver.execute_query(_WIPE, database_=self._settings.database)

    def rebuild(self, document: GraphDocument) -> None:
        """Full rebuild (mục 8): xoá sạch rồi `MERGE` toàn bộ `GraphDocument`.

        Mất kết nối Neo4j giữa chừng phải raise rõ ràng, không âm thầm bỏ qua
        (mục 9) -- driver chính thức tự raise (vd
        `neo4j.exceptions.ServiceUnavailable`), không bắt và nuốt lỗi ở đây.
        """
        self.ensure_constraints()
        self.wipe()
        self._run(_MERGE_VAN_BAN, [node.model_dump() for node in document.van_bans])
        self._run(_MERGE_PHAN, [node.model_dump() for node in document.phans])
        self._run(_MERGE_CHUONG, [node.model_dump() for node in document.chuongs])
        self._run(_MERGE_MUC, [node.model_dump() for node in document.mucs])
        self._run(_MERGE_DIEU, [node.model_dump() for node in document.dieus])
        self._run(_MERGE_KHOAN, [node.model_dump() for node in document.khoans])
        self._run(
            _MERGE_HAS_CHILD,
            [edge.model_dump() for edge in document.has_child_edges],
        )
        self._run(
            _MERGE_REFERENCES,
            [edge.model_dump() for edge in document.references],
        )
