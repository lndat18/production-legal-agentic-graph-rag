"""Bước ingest Knowledge Graph: chuyển chunk cấp Khoản thành đồ thị Neo4j.

Xem `graph_spec.md` trong package này để biết chi tiết schema node/
relationship, thuật toán gộp breadcrumb và quy tắc trích viện dẫn chéo.
"""

from __future__ import annotations

from production_legal_agentic_graph_rag.graph.builder import build_graph_document
from production_legal_agentic_graph_rag.graph.models import GraphDocument, IngestResult
from production_legal_agentic_graph_rag.graph.neo4j_client import Neo4jClient
from production_legal_agentic_graph_rag.graph.pipeline import run_ingest

__all__ = [
    "GraphDocument",
    "IngestResult",
    "Neo4jClient",
    "build_graph_document",
    "run_ingest",
]
