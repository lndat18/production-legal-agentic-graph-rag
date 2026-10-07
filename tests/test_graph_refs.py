"""Kiểm thử trích và phân giải viện dẫn nội bộ (graph_spec.md mục 3, 7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from production_legal_agentic_graph_rag.graph.models import (
    GraphDocument,
    NodeLabel,
    ReferenceKind,
    ReferenceStats,
)
from production_legal_agentic_graph_rag.graph.refs import (
    extract_references,
    mask_quoted_text,
    resolve_references,
)
from tests.graph_helpers import build_from_markdown

_TEMPLATE = """VĂN PHÒNG

**{header}**

# {title}

Lời mở đầu.

## Chương I. QUY ĐỊNH CHUNG

#### Điều 1. Một

##### Khoản 1

Cá nhân cư trú là người:

a) {point_a}

b) Điểm b.

##### Khoản 2

Nội dung hai.

#### Điều 2. Hai

##### Khoản 1

{text}
"""


def _resolve(
    tmp_path: Path,
    text: str,
    point_a: str = "Điểm a.",
    header: str = "LUẬT",
) -> tuple[GraphDocument, ReferenceStats]:
    markdown = _TEMPLATE.format(header=header, title="MẪU", text=text, point_a=point_a)
    graph, _, _ = build_from_markdown(tmp_path, "van-ban", markdown)
    edges, stats = resolve_references(graph)
    return graph.model_copy(update={"references": edges}), stats


def _article_id(graph: GraphDocument, label: str) -> str:
    return next(a.id for a in graph.articles if a.label == label)


def _clause_id(graph: GraphDocument, article: str, label: str) -> str:
    article_id = _article_id(graph, article)
    return next(
        c.id for c in graph.clauses if c.parent_id == article_id and c.label == label
    )


# --- extract_references ---


def test_extract_points_clause_article_list() -> None:
    refs = extract_references("theo điểm a, b và c khoản 1 Điều 64 của Luật này")

    assert len(refs) == 1
    ref = refs[0]
    assert ref.point_labels == ["a", "b", "c"]
    assert ref.clause_labels == ["1"]
    assert ref.article_labels == ["64"]
    assert ref.explicit_internal is True
    assert ref.raw_text == "điểm a, b và c khoản 1 Điều 64 của Luật này"


def test_extract_range_and_this_article_and_suffix_label() -> None:
    range_ref = extract_references("quy định từ Điều 5 đến Điều 7.")[0]
    this_ref = extract_references("khoản 2 Điều này")[0]
    suffix_ref = extract_references("theo Điều 48a")[0]

    assert range_ref.is_range is True
    assert range_ref.article_labels == ["5", "7"]
    assert this_ref.this_article is True
    assert this_ref.clause_labels == ["2"]
    assert this_ref.explicit_internal is True
    assert suffix_ref.article_labels == ["48a"]
    assert suffix_ref.explicit_internal is False


def test_extract_article_list_each_element() -> None:
    ref = extract_references("Điều 40, Điều 41 và Điều 42")[0]

    assert ref.article_labels == ["40", "41", "42"]


def test_extract_flags_other_document_by_sentence_only() -> None:
    first, second = extract_references(
        "Theo Điều 5 của Bộ luật Lao động. Thực hiện Điều 6"
    )

    assert first.other_document_in_sentence is True
    assert second.other_document_in_sentence is False


def test_extract_flags_document_number_as_other_document() -> None:
    ref = extract_references("Theo Điều 5 Luật số 51/2024/QH15")[0]

    assert ref.other_document_in_sentence is True


def test_this_document_phrase_is_not_other_document() -> None:
    ref = extract_references("Điều 5 của Nghị định này")[0]

    assert ref.other_document_in_sentence is False
    assert ref.explicit_internal is True


def test_mask_quoted_text_preserves_length_and_newlines() -> None:
    text = "Sửa như sau: “Theo Điều 5\nvà Điều 6” rồi Điều 7"

    masked = mask_quoted_text(text)

    assert len(masked) == len(text)
    assert "Điều 5" not in masked
    assert "\n" in masked
    assert masked.endswith("Điều 7")


def test_extract_ignores_references_inside_quotes() -> None:
    assert extract_references("Bổ sung như sau: “Theo Điều 5 của Luật này”.") == []


# --- resolve_references: nội bộ ---


def test_this_law_reference_creates_edge_to_article(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Thực hiện theo Điều 1 của Luật này.")

    assert len(graph.references) == 1
    edge = graph.references[0]
    assert edge.source_label is NodeLabel.CLAUSE
    assert edge.source_id == _clause_id(graph, "2", "1")
    assert edge.target_label is NodeLabel.ARTICLE
    assert edge.target_id == _article_id(graph, "1")
    assert edge.kind is ReferenceKind.SINGLE
    assert edge.raw_text == "Điều 1 của Luật này"
    assert stats.external == 0


def test_point_list_creates_one_edge_per_point(tmp_path: Path) -> None:
    graph, _ = _resolve(tmp_path, "Theo điểm a và b khoản 1 Điều 1 của Luật này.")

    targets = {(e.target_label, e.target_id) for e in graph.references}
    point_ids = {p.id for p in graph.points}

    assert len(graph.references) == 2
    assert {label for label, _ in targets} == {NodeLabel.POINT}
    assert {tid for _, tid in targets} == point_ids


def test_clause_target_when_no_point(tmp_path: Path) -> None:
    graph, _ = _resolve(tmp_path, "Theo khoản 2 Điều 1 của Luật này.")

    assert [(e.target_label, e.target_id) for e in graph.references] == [
        (NodeLabel.CLAUSE, _clause_id(graph, "1", "2"))
    ]


def test_range_creates_edges_with_range_kind(tmp_path: Path) -> None:
    graph, _ = _resolve(tmp_path, "Quy định từ Điều 1 đến Điều 2 của Luật này.")
    # Nguồn nằm trong Điều 2 nên cạnh tới Điều 2 (tổ tiên) bị bỏ, chỉ còn Điều 1.

    assert [(e.target_id, e.kind) for e in graph.references] == [
        (_article_id(graph, "1"), ReferenceKind.RANGE)
    ]


def test_range_with_missing_endpoint_is_unresolved(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Từ Điều 1 đến Điều 99 của Luật này.")

    assert graph.references == []
    assert stats.unresolved_target == 1


def test_reversed_range_is_unresolved(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Từ Điều 2 đến Điều 1 của Luật này.")

    assert graph.references == []
    assert stats.unresolved_target == 1


def test_missing_target_counted_not_linked(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 99 của Luật này.")

    assert graph.references == []
    assert stats.unresolved_target == 1


def test_missing_clause_and_point_targets_counted(tmp_path: Path) -> None:
    graph, stats = _resolve(
        tmp_path,
        "Theo khoản 9 Điều 1 của Luật này và điểm z khoản 1 Điều 1 của Luật này.",
    )

    assert graph.references == []
    assert stats.unresolved_target == 2


def test_reference_inside_point_has_point_as_source(tmp_path: Path) -> None:
    graph, _ = _resolve(
        tmp_path, "Không có viện dẫn.", point_a="Theo Điều 2 của Luật này."
    )

    assert len(graph.references) == 1
    edge = graph.references[0]
    assert edge.source_label is NodeLabel.POINT
    assert edge.target_id == _article_id(graph, "2")


def test_reference_in_point_not_duplicated_on_parent_clause(tmp_path: Path) -> None:
    graph, _ = _resolve(
        tmp_path, "Không có viện dẫn.", point_a="Theo Điều 2 của Luật này."
    )

    assert all(e.source_label is NodeLabel.POINT for e in graph.references)


def test_duplicate_source_target_kept_once(tmp_path: Path) -> None:
    graph, _ = _resolve(
        tmp_path, "Theo Điều 1 của Luật này. Xem thêm Điều 1 của Luật này."
    )

    assert len(graph.references) == 1


# --- precision: ca mơ hồ không tạo cạnh ---


def test_ambiguous_clause_over_multiple_articles_creates_no_edge(
    tmp_path: Path,
) -> None:
    graph, stats = _resolve(tmp_path, "Theo khoản 1 Điều 1 và Điều 2 của Luật này.")

    assert graph.references == []
    assert stats.unresolved_target == 1


def test_ambiguous_point_over_multiple_clauses_creates_no_edge(
    tmp_path: Path,
) -> None:
    graph, stats = _resolve(
        tmp_path, "Theo điểm a khoản 1 và khoản 2 Điều 1 của Luật này."
    )

    assert graph.references == []
    assert stats.unresolved_target == 1


# --- tự trỏ ---


def test_self_article_reference_skipped(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Chính phủ quy định chi tiết Điều này.")

    assert graph.references == []
    assert stats.self_skipped == 1


def test_reference_to_own_clause_skipped(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo quy định tại khoản 1 Điều này.")

    assert graph.references == []
    assert stats.self_skipped == 1


def test_point_referring_to_parent_clause_skipped(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Không có.", point_a="Theo khoản 1 Điều này.")

    assert graph.references == []
    assert stats.self_skipped == 1


def test_clause_may_reference_sibling_clause_in_same_article(tmp_path: Path) -> None:
    graph, _ = _resolve(tmp_path, "Theo khoản 2 Điều 1 của Luật này.")

    assert len(graph.references) == 1


# --- ngoặc kép ---


def test_quoted_reference_creates_no_edge_and_no_count(tmp_path: Path) -> None:
    graph, stats = _resolve(
        tmp_path, "Sửa đổi như sau: “Theo Điều 1 của Bộ luật Lao động”."
    )

    assert graph.references == []
    assert stats.external == 0
    assert stats.unresolved_target == 0


# --- văn bản khác (ngoại) ---


def test_other_document_in_sentence_is_external(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 1 của Bộ luật Lao động.")

    assert graph.references == []
    assert stats.external == 1


def test_document_number_makes_bare_reference_external(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 1 Luật số 51/2024/QH15.")

    assert graph.references == []
    assert stats.external == 1


def test_list_before_other_document_is_all_external(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 1, Điều 2 của Bộ luật Lao động.")

    assert graph.references == []
    assert stats.external == 1


def test_external_in_one_sentence_does_not_taint_next(tmp_path: Path) -> None:
    graph, stats = _resolve(
        tmp_path, "Theo Điều 1 của Bộ luật Lao động. Thực hiện Điều 1."
    )

    assert stats.external == 1
    assert [e.target_id for e in graph.references] == [_article_id(graph, "1")]


def test_explicit_this_law_wins_in_sentence_with_other_document(
    tmp_path: Path,
) -> None:
    graph, stats = _resolve(
        tmp_path,
        "Theo Điều 1 của Luật này và Điều 2 của Bộ luật Lao động.",
    )

    assert [e.target_id for e in graph.references] == [_article_id(graph, "1")]
    assert stats.external == 1


# --- goc vs huong_dan ---


def test_bare_article_in_goc_is_internal(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 1.")

    assert [e.target_id for e in graph.references] == [_article_id(graph, "1")]
    assert stats.bare_huong_dan == 0


def test_bare_article_in_huong_dan_is_external_by_default(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 1.", header="NGHỊ ĐỊNH")

    assert graph.document.kind.value == "huong_dan"
    assert graph.references == []
    assert stats.bare_huong_dan == 1
    assert stats.external == 0


def test_this_decree_reference_is_internal_in_huong_dan(tmp_path: Path) -> None:
    graph, stats = _resolve(
        tmp_path, "Theo khoản 2 Điều 1 của Nghị định này.", header="NGHỊ ĐỊNH"
    )

    assert [e.target_id for e in graph.references] == [_clause_id(graph, "1", "2")]
    assert stats.bare_huong_dan == 0


def test_bare_article_missing_in_goc_is_counted_not_linked(tmp_path: Path) -> None:
    graph, stats = _resolve(tmp_path, "Theo Điều 77.")

    assert graph.references == []
    assert stats.unresolved_target == 1


@pytest.mark.parametrize("header", ["LUẬT", "NGHỊ ĐỊNH"])
def test_no_edge_dangles_or_self_loops(tmp_path: Path, header: str) -> None:
    graph, _ = _resolve(
        tmp_path,
        "Theo Điều 1 của Luật này, Điều 99 của Luật này và Điều này.",
        header=header,
    )
    node_ids = {n.id for n in graph.all_nodes()}

    for edge in graph.references:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids
        assert edge.source_id != edge.target_id
