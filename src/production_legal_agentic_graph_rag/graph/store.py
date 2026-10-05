"""Lưu và đọc knowledge graph: interface mỏng `GraphStore`, bản Neo4j và bản fake in-memory.

Cypher hoàn toàn tham số hoá (mục 3): chỉ nhãn node/kiểu cạnh lấy từ enum
hằng số `NodeLabel` được nội suy vào chuỗi truy vấn, không bao giờ từ nội dung
văn bản. Interface chỉ phục vụ ingest và các truy vấn mẫu của mục 11; hợp đồng
đọc cho retrieval/agent thuộc spec sau (mục 12).
"""

from __future__ import annotations

import abc
from collections import defaultdict
from typing import TYPE_CHECKING, Any, LiteralString, cast

from neo4j import Driver, GraphDatabase, ManagedTransaction

from production_legal_agentic_graph_rag.graph.models import (
    STRUCTURAL_REL_BY_CHILD,
    ArticleNode,
    ClauseContext,
    ClauseNode,
    ClauseView,
    GraphDocument,
    NodeLabel,
    ReferenceCard,
    ReferenceCards,
    ReferenceKind,
    StructureNode,
    TocEntry,
)

if TYPE_CHECKING:
    from production_legal_agentic_graph_rag.config import Neo4jSettings

_STRUCTURE_LABELS = (NodeLabel.PART, NodeLabel.CHAPTER, NodeLabel.SECTION)
_TOC_LABELS = (*_STRUCTURE_LABELS, NodeLabel.ARTICLE)
_ALL_STRUCTURAL_RELS = "|".join(STRUCTURAL_REL_BY_CHILD.values())
_DOC_TO_UNIT_RELS = "HAS_PART|HAS_CHAPTER|HAS_SECTION|HAS_ARTICLE"


class GraphStore(abc.ABC):
    """Interface ghi/đọc graph; test dùng `InMemoryGraphStore` qua interface này."""

    @abc.abstractmethod
    def ensure_schema(self) -> None:
        """Tạo constraint `UNIQUE` trên `id` mỗi nhãn node (`IF NOT EXISTS`)."""

    @abc.abstractmethod
    def replace_document(self, graph: GraphDocument) -> None:
        """Xoá graph cũ của văn bản rồi ghi graph mới, trong một transaction."""

    @abc.abstractmethod
    def get_article_clauses(
        self, short_name: str, article_label: str
    ) -> list[ClauseView]:
        """Toàn văn một Điều: các Khoản theo `order`."""

    @abc.abstractmethod
    def get_table_of_contents(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> list[TocEntry]:
        """Mục lục: con trực tiếp của Phần/Chương/Mục theo `order`."""

    @abc.abstractmethod
    def get_clause_context(self, chunk_id: str) -> ClauseContext | None:
        """Từ `chunk_id` lên Khoản, Điều, Khoản/Điều anh em và Mục/Chương cha."""

    @abc.abstractmethod
    def get_reference_cards(
        self, short_name: str, article_label: str, clause_label: str | None
    ) -> ReferenceCards:
        """Thẻ viện dẫn đi ra/đi vào của một Khoản (hoặc cả Điều nếu `clause_label=None`)."""

    @abc.abstractmethod
    def count_descendants(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> dict[str, int]:
        """Đếm node con cháu theo nhãn của một đơn vị."""

    def close(self) -> None:
        """Giải phóng kết nối (nếu có)."""


def _require_unit_label(node_label: NodeLabel) -> None:
    if node_label not in _TOC_LABELS:
        raise ValueError(f"Không hỗ trợ truy vấn theo nhãn {node_label.value}")


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------


def _cypher(text: str) -> LiteralString:
    # `text` chỉ ghép từ hằng số của module này (enum nhãn), không từ dữ liệu ngoài.
    return cast(LiteralString, text)


_DELETE_DOCUMENT = _cypher(
    "MATCH (d:Document {id: $doc_id}) "
    f"OPTIONAL MATCH (d)-[:{_ALL_STRUCTURAL_RELS}*]->(n) "
    "DETACH DELETE d, n"
)

_UNIT_MATCH = (
    f"MATCH (d:Document {{short_name: $short_name}})-[:{_DOC_TO_UNIT_RELS}*]->"
)

_SCOPE_MATCH = (
    _UNIT_MATCH + "(a:Article {label: $article_label}) "
    "OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(c:Clause) "
    "WHERE $clause_label IS NULL OR c.label = $clause_label "
    "OPTIONAL MATCH (c)-[:HAS_POINT]->(p:Point) "
    "WITH collect(DISTINCT c) + collect(DISTINCT p) + "
    "CASE WHEN $clause_label IS NULL THEN collect(DISTINCT a) ELSE [] END AS scope "
    "UNWIND scope AS n "
)

_CARD_FIELDS = (
    "MATCH (ta:Article)-[:HAS_CLAUSE|HAS_POINT*0..2]->(o) "
    "RETURN r.raw_text AS raw_text, r.kind AS kind, labels(o)[0] AS node_label, "
    "o.label AS label, ta.label AS article_label, ta.title AS article_title, "
    "CASE WHEN o:Article THEN o.char_count ELSE size(o.text) END AS char_count "
    "ORDER BY n.id, o.id"
)


def _clause_view(props: Any) -> ClauseView:
    return ClauseView(
        label=props.get("label"),
        order=props["order"],
        text=props["text"],
        chunk_ids=list(props["chunk_ids"]),
        implicit=props["implicit"],
    )


def _toc_entry(node_label: str, props: Any) -> TocEntry:
    return TocEntry(
        node_label=NodeLabel(node_label),
        label=props["label"],
        title=props["title"],
        order=props["order"],
        char_count=props["char_count"],
    )


def _card(record: Any) -> ReferenceCard:
    return ReferenceCard(
        raw_text=record["raw_text"],
        kind=ReferenceKind(record["kind"]),
        node_label=NodeLabel(record["node_label"]),
        label=record["label"],
        article_label=record["article_label"],
        article_title=record["article_title"],
        char_count=record["char_count"],
    )


def _node_rows(graph: GraphDocument) -> dict[NodeLabel, list[dict[str, Any]]]:
    rows: dict[NodeLabel, list[dict[str, Any]]] = defaultdict(list)
    for node in graph.all_nodes():
        rows[node.node_label].append(
            node.model_dump(
                mode="json", exclude={"node_label", "parent_id"}, exclude_none=True
            )
        )
    return rows


def _write_graph(tx: ManagedTransaction, graph: GraphDocument) -> None:
    tx.run(_DELETE_DOCUMENT, doc_id=graph.document.id).consume()
    for label, rows in _node_rows(graph).items():
        tx.run(
            _cypher(
                f"UNWIND $rows AS row MERGE (n:{label.value} {{id: row.id}}) SET n += row"
            ),
            rows=rows,
        ).consume()

    structural: dict[tuple[NodeLabel, NodeLabel], list[dict[str, str]]] = defaultdict(
        list
    )
    for edge in graph.structural_edges():
        structural[(edge.parent_label, edge.child_label)].append(
            {"parent_id": edge.parent_id, "child_id": edge.child_id}
        )
    for (parent_label, child_label), rows in structural.items():
        rel = STRUCTURAL_REL_BY_CHILD[child_label]
        tx.run(
            _cypher(
                "UNWIND $rows AS row "
                f"MATCH (p:{parent_label.value} {{id: row.parent_id}}) "
                f"MATCH (c:{child_label.value} {{id: row.child_id}}) "
                f"MERGE (p)-[:{rel}]->(c)"
            ),
            rows=rows,
        ).consume()

    references: dict[tuple[NodeLabel, NodeLabel], list[dict[str, str]]] = defaultdict(
        list
    )
    for ref in graph.references:
        references[(ref.source_label, ref.target_label)].append(
            {
                "source_id": ref.source_id,
                "target_id": ref.target_id,
                "raw_text": ref.raw_text,
                "kind": ref.kind.value,
            }
        )
    for (source_label, target_label), rows in references.items():
        tx.run(
            _cypher(
                "UNWIND $rows AS row "
                f"MATCH (s:{source_label.value} {{id: row.source_id}}) "
                f"MATCH (t:{target_label.value} {{id: row.target_id}}) "
                "MERGE (s)-[r:REFERS_TO]->(t) "
                "SET r.raw_text = row.raw_text, r.kind = row.kind"
            ),
            rows=rows,
        ).consume()


class Neo4jGraphStore(GraphStore):
    """`GraphStore` trên Neo4j qua driver chính thức, một database."""

    def __init__(self, driver: Driver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    @classmethod
    def from_settings(cls, settings: Neo4jSettings) -> Neo4jGraphStore:
        """Mở kết nối từ `Neo4jSettings` (mật khẩu không bao giờ được log)."""
        driver = GraphDatabase.driver(
            settings.uri, auth=(settings.user, settings.password.get_secret_value())
        )
        return cls(driver, settings.database)

    def close(self) -> None:
        """Đóng driver."""
        self._driver.close()

    def verify_connectivity(self) -> None:
        """Kiểm tra kết nối tới Neo4j; ném lỗi của driver nếu không tới được."""
        self._driver.verify_connectivity()

    def ensure_schema(self) -> None:
        """Tạo constraint `UNIQUE` trên `id` cho mọi nhãn node."""
        with self._driver.session(database=self._database) as session:
            for label in NodeLabel:
                session.run(
                    _cypher(
                        f"CREATE CONSTRAINT {label.value.lower()}_id_unique IF NOT EXISTS "
                        f"FOR (n:{label.value}) REQUIRE n.id IS UNIQUE"
                    )
                ).consume()

    def replace_document(self, graph: GraphDocument) -> None:
        """Ghi một văn bản trong một transaction (lỗi thì rollback, graph cũ còn nguyên)."""
        with self._driver.session(database=self._database) as session:
            session.execute_write(_write_graph, graph)

    def _read(self, query: LiteralString, **parameters: Any) -> list[Any]:
        with self._driver.session(database=self._database) as session:
            return list(session.run(query, parameters))

    def get_article_clauses(
        self, short_name: str, article_label: str
    ) -> list[ClauseView]:
        """Xem `GraphStore.get_article_clauses`."""
        records = self._read(
            _cypher(
                _UNIT_MATCH + "(a:Article {label: $article_label})-[:HAS_CLAUSE]->"
                "(c:Clause) RETURN c ORDER BY c.order"
            ),
            short_name=short_name,
            article_label=article_label,
        )
        return [_clause_view(record["c"]) for record in records]

    def get_table_of_contents(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> list[TocEntry]:
        """Xem `GraphStore.get_table_of_contents`."""
        _require_unit_label(node_label)
        records = self._read(
            _cypher(
                _UNIT_MATCH + f"(u:{node_label.value} {{label: $label}})"
                "-[:HAS_CHAPTER|HAS_SECTION|HAS_ARTICLE]->(child) "
                "RETURN labels(child)[0] AS node_label, child "
                "ORDER BY u.order, child.order"
            ),
            short_name=short_name,
            label=label,
        )
        return [_toc_entry(record["node_label"], record["child"]) for record in records]

    def get_clause_context(self, chunk_id: str) -> ClauseContext | None:
        """Xem `GraphStore.get_clause_context`."""
        records = self._read(
            _cypher(
                "MATCH (c:Clause) WHERE $chunk_id IN c.chunk_ids "
                "MATCH (par)-[:HAS_ARTICLE]->(a:Article)-[:HAS_CLAUSE]->(c) "
                "MATCH (a)-[:HAS_CLAUSE]->(s:Clause) "
                "WITH c, a, par, s ORDER BY s.order "
                "WITH c, a, par, collect(s) AS siblings "
                "MATCH (par)-[:HAS_ARTICLE]->(sa:Article) "
                "WITH c, a, par, siblings, sa ORDER BY sa.order "
                "RETURN c, a, par, labels(par)[0] AS par_label, siblings, "
                "collect(sa) AS sibling_articles"
            ),
            chunk_id=chunk_id,
        )
        if not records:
            return None
        record = records[0]
        parent = (
            _toc_entry(record["par_label"], record["par"])
            if record["par_label"] != NodeLabel.DOCUMENT.value
            else None
        )
        return ClauseContext(
            clause=_clause_view(record["c"]),
            article=_toc_entry(NodeLabel.ARTICLE.value, record["a"]),
            sibling_clauses=[_clause_view(node) for node in record["siblings"]],
            parent=parent,
            sibling_articles=[
                _toc_entry(NodeLabel.ARTICLE.value, node)
                for node in record["sibling_articles"]
            ],
        )

    def get_reference_cards(
        self, short_name: str, article_label: str, clause_label: str | None
    ) -> ReferenceCards:
        """Xem `GraphStore.get_reference_cards`."""
        parameters = {
            "short_name": short_name,
            "article_label": article_label,
            "clause_label": clause_label,
        }
        outgoing = self._read(
            _cypher(_SCOPE_MATCH + "MATCH (n)-[r:REFERS_TO]->(o) " + _CARD_FIELDS),
            **parameters,
        )
        incoming = self._read(
            _cypher(_SCOPE_MATCH + "MATCH (o)-[r:REFERS_TO]->(n) " + _CARD_FIELDS),
            **parameters,
        )
        return ReferenceCards(
            outgoing=[_card(record) for record in outgoing],
            incoming=[_card(record) for record in incoming],
        )

    def count_descendants(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> dict[str, int]:
        """Xem `GraphStore.count_descendants`."""
        _require_unit_label(node_label)
        records = self._read(
            _cypher(
                _UNIT_MATCH + f"(u:{node_label.value} {{label: $label}}) "
                f"MATCH (u)-[:{_ALL_STRUCTURAL_RELS}*]->(n) "
                "RETURN labels(n)[0] AS node_label, count(DISTINCT n) AS total"
            ),
            short_name=short_name,
            label=label,
        )
        return {record["node_label"]: record["total"] for record in records}


# ---------------------------------------------------------------------------
# Fake in-memory
# ---------------------------------------------------------------------------


def _clause_view_of(clause: ClauseNode) -> ClauseView:
    return ClauseView(
        label=clause.label,
        order=clause.order,
        text=clause.text,
        chunk_ids=list(clause.chunk_ids),
        implicit=clause.implicit,
    )


def _toc_entry_of(node: StructureNode | ArticleNode) -> TocEntry:
    return TocEntry(
        node_label=node.node_label,
        label=node.label,
        title=node.title,
        order=node.order,
        char_count=node.char_count,
    )


class InMemoryGraphStore(GraphStore):
    """Fake `GraphStore` giữ `GraphDocument` trong bộ nhớ; ngữ nghĩa đọc giống bản Neo4j."""

    def __init__(self) -> None:
        self.schema_ready = False
        self.documents: dict[str, GraphDocument] = {}

    def ensure_schema(self) -> None:
        """Đánh dấu schema đã sẵn sàng (không có constraint thật)."""
        self.schema_ready = True

    def replace_document(self, graph: GraphDocument) -> None:
        """Thay graph của văn bản theo `document.id`; dữ liệu cũ bị bỏ hoàn toàn."""
        self.documents[graph.document.id] = graph.model_copy(deep=True)

    def _document(self, short_name: str) -> GraphDocument | None:
        return next(
            (
                graph
                for graph in self.documents.values()
                if graph.document.short_name == short_name
            ),
            None,
        )

    def _units(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> tuple[GraphDocument, list[StructureNode | ArticleNode]]:
        _require_unit_label(node_label)
        graph = self._document(short_name)
        if graph is None:
            raise KeyError(short_name)
        pool = graph.units()
        units = [
            node
            for node in pool
            if node.node_label is node_label and node.label == label
        ]
        return graph, units

    def get_article_clauses(
        self, short_name: str, article_label: str
    ) -> list[ClauseView]:
        """Xem `GraphStore.get_article_clauses`."""
        graph = self._document(short_name)
        if graph is None:
            return []
        article_ids = {a.id for a in graph.articles if a.label == article_label}
        clauses = [c for c in graph.clauses if c.parent_id in article_ids]
        return [_clause_view_of(c) for c in sorted(clauses, key=lambda c: c.order)]

    def get_table_of_contents(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> list[TocEntry]:
        """Xem `GraphStore.get_table_of_contents`."""
        try:
            graph, units = self._units(short_name, node_label, label)
        except KeyError:
            return []
        entries: list[TocEntry] = []
        for unit in sorted(units, key=lambda u: u.order):
            children = [node for node in graph.units() if node.parent_id == unit.id]
            entries.extend(
                _toc_entry_of(c) for c in sorted(children, key=lambda c: c.order)
            )
        return entries

    def get_clause_context(self, chunk_id: str) -> ClauseContext | None:
        """Xem `GraphStore.get_clause_context`."""
        for graph in self.documents.values():
            clause = next((c for c in graph.clauses if chunk_id in c.chunk_ids), None)
            if clause is None:
                continue
            article = next(a for a in graph.articles if a.id == clause.parent_id)
            siblings = sorted(
                (c for c in graph.clauses if c.parent_id == article.id),
                key=lambda c: c.order,
            )
            parent = next(
                (s for s in graph.structures if s.id == article.parent_id), None
            )
            sibling_articles = sorted(
                (a for a in graph.articles if a.parent_id == article.parent_id),
                key=lambda a: a.order,
            )
            return ClauseContext(
                clause=_clause_view_of(clause),
                article=_toc_entry_of(article),
                sibling_clauses=[_clause_view_of(c) for c in siblings],
                parent=_toc_entry_of(parent) if parent else None,
                sibling_articles=[_toc_entry_of(a) for a in sibling_articles],
            )
        return None

    def get_reference_cards(
        self, short_name: str, article_label: str, clause_label: str | None
    ) -> ReferenceCards:
        """Xem `GraphStore.get_reference_cards`."""
        graph = self._document(short_name)
        article = (
            next((a for a in graph.articles if a.label == article_label), None)
            if graph
            else None
        )
        if graph is None or article is None:
            return ReferenceCards()
        clauses = [
            c
            for c in graph.clauses
            if c.parent_id == article.id
            and (clause_label is None or c.label == clause_label)
        ]
        scope = {c.id for c in clauses}
        scope |= {p.id for p in graph.points if p.parent_id in scope}
        if clause_label is None:
            scope.add(article.id)
        return ReferenceCards(
            outgoing=[
                self._card(graph, ref.target_id, ref.raw_text, ref.kind)
                for ref in graph.references
                if ref.source_id in scope
            ],
            incoming=[
                self._card(graph, ref.source_id, ref.raw_text, ref.kind)
                for ref in graph.references
                if ref.target_id in scope
            ],
        )

    @staticmethod
    def _card(
        graph: GraphDocument, node_id: str, raw_text: str, kind: ReferenceKind
    ) -> ReferenceCard:
        articles = {a.id: a for a in graph.articles}
        clauses = {c.id: c for c in graph.clauses}
        points = {p.id: p for p in graph.points}
        node_label: NodeLabel
        label: str | None
        size: int
        if node_id in articles:
            article = articles[node_id]
            node_label, label, size = (
                NodeLabel.ARTICLE,
                article.label,
                article.char_count,
            )
        elif node_id in clauses:
            clause = clauses[node_id]
            article = articles[clause.parent_id]
            node_label, label, size = NodeLabel.CLAUSE, clause.label, len(clause.text)
        else:
            point = points[node_id]
            article = articles[clauses[point.parent_id].parent_id]
            node_label, label, size = NodeLabel.POINT, point.label, len(point.text)
        return ReferenceCard(
            raw_text=raw_text,
            kind=kind,
            node_label=node_label,
            label=label,
            article_label=article.label,
            article_title=article.title,
            char_count=size,
        )

    def count_descendants(
        self, short_name: str, node_label: NodeLabel, label: str
    ) -> dict[str, int]:
        """Xem `GraphStore.count_descendants`."""
        try:
            graph, units = self._units(short_name, node_label, label)
        except KeyError:
            return {}
        label_by_id = {n.id: n.node_label for n in graph.all_nodes()}
        parent_by_id = {n.id: n.parent_id for n in graph.all_nodes()}
        unit_ids = {u.id for u in units}
        counts: dict[str, int] = defaultdict(int)
        for node_id, node_type in label_by_id.items():
            ancestor = parent_by_id[node_id]
            while ancestor is not None:
                if ancestor in unit_ids:
                    counts[node_type.value] += 1
                    break
                ancestor = parent_by_id.get(ancestor)
        return dict(counts)
