"""Thuần function `list[Chunk] -> GraphDocument`, không I/O (mục 8, 10 `graph_spec.md`).

Gọi `breadcrumb.py` để dựng hierarchy (dedupe node theo `id`, mục 3 bất biến
3-4) rồi `references.py` để trích viện dẫn chéo. Không cần Neo4j chạy thật để
test (mục 9, 11 tiêu chí hoàn thành).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from production_legal_agentic_graph_rag.chunking.models import Chunk
from production_legal_agentic_graph_rag.graph.breadcrumb import group_khoans
from production_legal_agentic_graph_rag.graph.models import (
    ChuongNode,
    DieuNode,
    GraphDocument,
    HasChildEdge,
    KhoanCoordinate,
    KhoanNode,
    MucNode,
    PhanNode,
    ReferenceEdge,
    VanBanNode,
)
from production_legal_agentic_graph_rag.graph.references import extract_references

# Token toạ độ của "Khoản ngầm định cấp Điều" (không có số Khoản thật, mục 6).
# Cố định (không phải title/label) nên vẫn thoả bất biến 3 -- id không đổi dù
# tên Điều bị sửa chính tả.
_IMPLICIT_KHOAN_TOKEN = "Khoan:_implicit"


def _node_id(parts: Sequence[str]) -> str:
    """SHA-256 hex từ toạ độ cấu trúc, độc lập với title/label (mục 3 bất biến 3)."""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _ancestor_chain(khoan: KhoanCoordinate) -> list[str]:
    """Chuỗi toạ độ `source_document|Phan:x|Chuong:y|Muc:z|Dieu:n`, bỏ cấp vắng
    mặt -- dùng làm khoá hash cho node `Dieu` và tiền tố khoá hash `Khoan`."""
    chain = [khoan.source_document]
    if khoan.phan is not None:
        chain.append(f"Phan:{khoan.phan}")
    if khoan.chuong is not None:
        chain.append(f"Chuong:{khoan.chuong}")
    if khoan.muc is not None:
        chain.append(f"Muc:{khoan.muc}")
    chain.append(f"Dieu:{khoan.dieu.number}")
    return chain


class _GraphBuilderState:
    """State tạm khi build 1 `GraphDocument` -- dedupe node/edge theo `id`."""

    def __init__(self) -> None:
        self.van_bans: dict[str, VanBanNode] = {}
        self.phans: dict[str, PhanNode] = {}
        self.chuongs: dict[str, ChuongNode] = {}
        self.mucs: dict[str, MucNode] = {}
        self.dieus: dict[str, DieuNode] = {}
        self.khoans: dict[str, KhoanNode] = {}
        self.has_child_edges: set[tuple[str, str]] = set()
        # Tra cứu target cho `references.py` -- cần đủ toàn corpus trước khi
        # quét viện dẫn nên `build_graph_document` chạy 2 vòng (mục "register"
        # rồi "reference").
        self.dieu_ids: dict[tuple[str, str], str] = {}
        self.khoan_ids: dict[tuple[str, str, str], str] = {}
        # (source_id, target_id, raw_text) -- dedupe viện dẫn giống hệt nhau
        # (MERGE ở Neo4j vốn đã idempotent, dedupe ở đây để `IngestResult`
        # không phồng số edge do nội dung lặp câu chữ giống nhau).
        self._reference_keys: dict[tuple[str, str, str], ReferenceEdge] = {}

    def _add_has_child(self, parent_id: str | None, child_id: str) -> None:
        if parent_id is not None:
            self.has_child_edges.add((parent_id, child_id))

    def register_ancestors(self, khoan: KhoanCoordinate) -> str:
        """Đăng ký VanBan/Phan/Chuong/Muc/Dieu (dedupe) + `HAS_CHILD` liền kề.

        Returns:
            `id` node `Dieu` của Khoản này, dùng làm cha khi đăng ký `Khoan`.
        """
        van_ban_id = khoan.source_document
        self.van_bans.setdefault(
            van_ban_id, VanBanNode(id=van_ban_id, source_document=van_ban_id)
        )
        parent_id: str | None = van_ban_id

        if khoan.phan is not None:
            phan_id = _node_id([khoan.source_document, f"Phan:{khoan.phan}"])
            self.phans.setdefault(phan_id, PhanNode(id=phan_id, label=khoan.phan))
            self._add_has_child(parent_id, phan_id)
            parent_id = phan_id

        if khoan.chuong is not None:
            chuong_parts = [khoan.source_document]
            if khoan.phan is not None:
                chuong_parts.append(f"Phan:{khoan.phan}")
            chuong_parts.append(f"Chuong:{khoan.chuong}")
            chuong_id = _node_id(chuong_parts)
            self.chuongs.setdefault(
                chuong_id, ChuongNode(id=chuong_id, label=khoan.chuong)
            )
            self._add_has_child(parent_id, chuong_id)
            parent_id = chuong_id

        if khoan.muc is not None:
            muc_parts = [khoan.source_document]
            if khoan.phan is not None:
                muc_parts.append(f"Phan:{khoan.phan}")
            if khoan.chuong is not None:
                muc_parts.append(f"Chuong:{khoan.chuong}")
            muc_parts.append(f"Muc:{khoan.muc}")
            muc_id = _node_id(muc_parts)
            self.mucs.setdefault(muc_id, MucNode(id=muc_id, label=khoan.muc))
            self._add_has_child(parent_id, muc_id)
            parent_id = muc_id

        dieu_id = _node_id(_ancestor_chain(khoan))
        self.dieus.setdefault(
            dieu_id,
            DieuNode(id=dieu_id, number=khoan.dieu.number, title=khoan.dieu.title),
        )
        self._add_has_child(parent_id, dieu_id)
        self.dieu_ids[(khoan.source_document, khoan.dieu.number)] = dieu_id
        return dieu_id

    def register_khoan(self, khoan: KhoanCoordinate, dieu_id: str) -> str:
        khoan_token = (
            f"Khoan:{khoan.khoan_number}"
            if khoan.khoan_number is not None
            else _IMPLICIT_KHOAN_TOKEN
        )
        khoan_id = _node_id(_ancestor_chain(khoan) + [khoan_token])
        self.khoans[khoan_id] = KhoanNode(
            id=khoan_id,
            number=khoan.khoan_number,
            chunk_ids=list(khoan.chunk_ids),
            breadcrumb=khoan.breadcrumb_root,
        )
        self._add_has_child(dieu_id, khoan_id)
        if khoan.khoan_number is not None:
            self.khoan_ids[
                (khoan.source_document, khoan.dieu.number, khoan.khoan_number)
            ] = khoan_id
        return khoan_id

    def add_references(self, edges: list[ReferenceEdge]) -> None:
        for edge in edges:
            key = (edge.source_id, edge.target_id, edge.raw_text)
            self._reference_keys.setdefault(key, edge)

    def build(self) -> GraphDocument:
        return GraphDocument(
            van_bans=list(self.van_bans.values()),
            phans=list(self.phans.values()),
            chuongs=list(self.chuongs.values()),
            mucs=list(self.mucs.values()),
            dieus=list(self.dieus.values()),
            khoans=list(self.khoans.values()),
            has_child_edges=[
                HasChildEdge(parent_id=parent_id, child_id=child_id)
                for parent_id, child_id in sorted(self.has_child_edges)
            ],
            references=list(self._reference_keys.values()),
        )


def build_graph_document(chunks: Sequence[Chunk]) -> tuple[GraphDocument, int, int]:
    """`list[Chunk] -> GraphDocument` (mục 8 quy trình, sơ đồ cuối `graph_spec.md`).

    Chạy 2 vòng: vòng 1 đăng ký toàn bộ node hierarchy (`VanBan`...`Khoan`) để
    có đủ `dieu_ids`/`khoan_ids` của TOÀN corpus; vòng 2 mới quét viện dẫn
    chéo (mục 7) -- 1 Khoản có thể viện dẫn 1 Điều xuất hiện sau nó trong thứ
    tự file/chunk, nên không thể resolve target trong cùng 1 vòng duyệt.

    Returns:
        `(GraphDocument đã dedupe, số chunk front/back matter bị bỏ qua, số
        chunk breadcrumb không parse được)`.
    """
    khoans, skipped_front_back, skipped_unparseable = group_khoans(chunks)

    state = _GraphBuilderState()
    khoan_node_ids: list[str] = []
    for khoan in khoans:
        dieu_id = state.register_ancestors(khoan)
        khoan_node_ids.append(state.register_khoan(khoan, dieu_id))

    for khoan, source_id in zip(khoans, khoan_node_ids, strict=True):
        edges = extract_references(khoan, source_id, state.dieu_ids, state.khoan_ids)
        state.add_references(edges)

    return state.build(), skipped_front_back, skipped_unparseable
