"""Integration test cho `graph/neo4j_client.py` -- cần Neo4j thật (graph_spec.md
mục 4, 8, 9, 11).

Đánh dấu `slow` nên CI job `checks` (`uv run pytest -m "not slow"`,
`.github/workflows/ci.yml`) không yêu cầu Neo4j server sống -- quyết định
marker cụ thể là việc của tester theo đúng mục 11 "tiêu chí hoàn thành" (để
ngỏ). Kể cả khi chạy `pytest` đầy đủ (không lọc `-m`), test tự skip gọn gàng
nếu không kết nối được Neo4j thay vì fail cứng, vì môi trường hiện tại chưa
có service Neo4j trong `docker-compose`/CI (mục "Ngoài phạm vi" `graph_spec.md`,
CLAUDE.md mục 3).

Chạy thật (Neo4j Community qua Docker đã lên, `NEO4J_PASSWORD` đặt qua
`.env`/biến môi trường):
    uv run pytest tests/test_graph_neo4j_client.py -m slow
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import GqlError
from pydantic import ValidationError

from production_legal_agentic_graph_rag.config import GraphSettings
from production_legal_agentic_graph_rag.graph.models import (
    DieuNode,
    GraphDocument,
    HasChildEdge,
    KhoanNode,
    ReferenceEdge,
    VanBanNode,
)
from production_legal_agentic_graph_rag.graph.neo4j_client import Neo4jClient

pytestmark = pytest.mark.slow


def _load_settings_or_skip() -> GraphSettings:
    # Thiếu `NEO4J_PASSWORD` (không set trong `.env`/biến môi trường) không
    # phải lỗi test, chỉ là môi trường hiện tại chưa sẵn sàng chạy tích hợp
    # Neo4j (mục 11: CI "not slow" mặc định không yêu cầu điều này).
    try:
        return GraphSettings()  # type: ignore[call-arg]
    except ValidationError as error:
        pytest.skip(f"GraphSettings chưa cấu hình đủ để chạy tích hợp: {error}")


def _connect_or_skip(settings: GraphSettings) -> Neo4jClient:
    client = Neo4jClient(settings)
    try:
        # `verify_connectivity()` fail nhanh (không đi qua vòng retry ~30s
        # mặc định của `execute_query()` khi mất kết nối) -- phù hợp hơn cho
        # 1 lần kiểm tra "có Neo4j sống không" trước khi chạy test thật.
        client._driver.verify_connectivity()  # type: ignore[attr-defined]
        client.ensure_constraints()
    except GqlError as error:
        client.close()
        pytest.skip(f"Không kết nối được Neo4j tại {settings.uri}: {error}")
    return client


@pytest.fixture
def neo4j_client() -> Iterator[Neo4jClient]:
    settings = _load_settings_or_skip()
    client = _connect_or_skip(settings)
    client.wipe()
    try:
        yield client
    finally:
        client.wipe()
        client.close()


def _sample_document() -> GraphDocument:
    return GraphDocument(
        van_bans=[VanBanNode(id="DOC", source_document="DOC")],
        dieus=[DieuNode(id="dieu-1", number="1", title="Tên điều 1")],
        khoans=[
            KhoanNode(
                id="khoan-1-1",
                number="1",
                chunk_ids=["c1"],
                breadcrumb="DOC - Điều 1 - Khoản 1",
            ),
            KhoanNode(
                id="khoan-1-2",
                number="2",
                chunk_ids=["c2a", "c2b"],
                breadcrumb="DOC - Điều 1 - Khoản 2",
            ),
        ],
        has_child_edges=[
            HasChildEdge(parent_id="DOC", child_id="dieu-1"),
            HasChildEdge(parent_id="dieu-1", child_id="khoan-1-1"),
            HasChildEdge(parent_id="dieu-1", child_id="khoan-1-2"),
        ],
        references=[
            ReferenceEdge(
                source_id="khoan-1-2",
                target_id="khoan-1-1",
                raw_text="khoản 1 Điều 1 của Luật này",
            ),
        ],
    )


def _scalar(settings: GraphSettings, query: str) -> int:
    """Chạy 1 câu Cypher đọc bằng driver riêng của test (không đụng nội bộ
    `Neo4jClient`), trả về giá trị cột đầu tiên của record đầu tiên."""
    auth = (settings.user, settings.password)
    with GraphDatabase.driver(settings.uri, auth=auth) as driver:
        records, _, _ = driver.execute_query(query, database_=settings.database)
        return int(records[0][0])


def test_rebuild_ghi_dung_so_luong_node_va_relationship(neo4j_client: Neo4jClient):
    settings = _load_settings_or_skip()
    neo4j_client.rebuild(_sample_document())

    assert _scalar(settings, "MATCH (n:VanBan) RETURN count(n)") == 1
    assert _scalar(settings, "MATCH (n:Dieu) RETURN count(n)") == 1
    assert _scalar(settings, "MATCH (n:Khoan) RETURN count(n)") == 2
    assert _scalar(settings, "MATCH ()-[r:HAS_CHILD]->() RETURN count(r)") == 3
    assert _scalar(settings, "MATCH ()-[r:REFERENCES]->() RETURN count(r)") == 1


def test_moi_node_mang_them_label_chung_node_de_merge_relationship(
    neo4j_client: Neo4jClient,
):
    # `neo4j_client.py` mục 4: mọi node còn mang label chung `Node` để 2 câu
    # MERGE relationship match được 2 đầu chỉ bằng `id`, không cần biết
    # trước label cụ thể.
    settings = _load_settings_or_skip()
    neo4j_client.rebuild(_sample_document())
    assert _scalar(settings, "MATCH (n:Node) RETURN count(n)") == 4


def test_rebuild_idempotent_chay_lai_khong_nhan_doi(neo4j_client: Neo4jClient):
    settings = _load_settings_or_skip()
    document = _sample_document()

    neo4j_client.rebuild(document)
    neo4j_client.rebuild(document)

    assert _scalar(settings, "MATCH (n:Node) RETURN count(n)") == 4
    assert _scalar(settings, "MATCH ()-[r:HAS_CHILD]->() RETURN count(r)") == 3
    assert _scalar(settings, "MATCH ()-[r:REFERENCES]->() RETURN count(r)") == 1


def test_wipe_xoa_sach_toan_bo_do_thi(neo4j_client: Neo4jClient):
    settings = _load_settings_or_skip()
    neo4j_client.rebuild(_sample_document())
    assert _scalar(settings, "MATCH (n) RETURN count(n)") > 0

    neo4j_client.wipe()

    assert _scalar(settings, "MATCH (n) RETURN count(n)") == 0
