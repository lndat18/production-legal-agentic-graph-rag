"""Kiểm thử dựng hierarchy, Điểm, chunk_ids của graph (graph_spec.md mục 4, 5, 8)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from production_legal_agentic_graph_rag.chunking.parser import parse_markdown
from production_legal_agentic_graph_rag.graph.builder import (
    BACKMATTER_SUFFIX,
    GraphBuildError,
    build_graph_document,
    classify_document_kind,
    scan_structure_headings,
    split_points,
)
from production_legal_agentic_graph_rag.graph.models import (
    DocumentKind,
    GraphDocument,
    NodeLabel,
)
from tests.graph_helpers import (
    GOC_MARKDOWN,
    breadcrumb_of,
    build_from_markdown,
    make_chunk,
    make_chunks,
    write_document,
)


@pytest.fixture
def goc(tmp_path: Path) -> GraphDocument:
    graph, _, _ = build_from_markdown(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    return graph


def _article(graph: GraphDocument, label: str):
    return next(a for a in graph.articles if a.label == label)


def _clauses_of(graph: GraphDocument, article_label: str):
    article = _article(graph, article_label)
    return sorted(
        (c for c in graph.clauses if c.parent_id == article.id), key=lambda c: c.order
    )


# --- phân loại văn bản ---


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("LUẬT THUẾ THU NHẬP CÁ NHÂN", DocumentKind.GOC),
        ("Bộ luật Lao động", DocumentKind.GOC),
        ("NGHỊ ĐỊNH 145/2020/NĐ-CP", DocumentKind.HUONG_DAN),
        ("Thông tư 10/2021", DocumentKind.HUONG_DAN),
    ],
)
def test_classify_document_kind(name: str, kind: DocumentKind) -> None:
    assert classify_document_kind(name) is kind


def test_classify_document_kind_unknown_raises() -> None:
    with pytest.raises(GraphBuildError):
        classify_document_kind("QUYẾT ĐỊNH 1/2020")


# --- hierarchy ---


def test_document_node_fields(goc: GraphDocument) -> None:
    document = goc.document

    assert document.name == "LUẬT MẪU"
    assert document.short_name == "Luật mẫu"
    assert document.kind is DocumentKind.GOC
    assert document.id == hashlib.sha256("LUẬT MẪU".encode()).hexdigest()[:12]
    assert document.front_text
    assert document.back_text and "Chú thích" in document.back_text


def test_chapter_and_section_hierarchy(goc: GraphDocument) -> None:
    chapters = [s for s in goc.structures if s.node_label is NodeLabel.CHAPTER]
    sections = [s for s in goc.structures if s.node_label is NodeLabel.SECTION]

    assert [(c.label, c.number, c.order) for c in chapters] == [
        ("I", 1, 1),
        ("II", 2, 2),
    ]
    assert all(c.parent_id == goc.document.id for c in chapters)
    assert chapters[0].title == "QUY ĐỊNH CHUNG"
    assert len(sections) == 1
    assert sections[0].parent_id == chapters[1].id
    assert sections[0].number == 1
    assert sections[0].title == "Nhóm thứ nhất"


def test_articles_attach_to_nearest_open_parent_with_order(goc: GraphDocument) -> None:
    chapter_1, chapter_2 = (s for s in goc.structures if s.label in {"I", "II"})
    section = next(s for s in goc.structures if s.node_label is NodeLabel.SECTION)

    assert [(a.label, a.order) for a in goc.articles] == [
        ("1", 1),
        ("2", 2),
        ("3", 1),
        ("4", 2),
        ("48a", 3),
    ]
    assert _article(goc, "1").parent_id == chapter_1.id
    assert _article(goc, "2").parent_id == chapter_1.id
    assert _article(goc, "3").parent_id == section.id
    assert _article(goc, "48a").parent_id == section.id
    assert chapter_2.id != section.id


def test_article_label_is_string_and_title_kept(goc: GraphDocument) -> None:
    article = _article(goc, "48a")

    assert isinstance(article.label, str)
    assert article.title == "Điều có hậu tố"


def test_structural_edges_point_to_direct_children_only(goc: GraphDocument) -> None:
    label_of = {n.id: n.node_label for n in goc.all_nodes()}
    allowed = {
        (NodeLabel.DOCUMENT, NodeLabel.CHAPTER),
        (NodeLabel.CHAPTER, NodeLabel.SECTION),
        (NodeLabel.CHAPTER, NodeLabel.ARTICLE),
        (NodeLabel.SECTION, NodeLabel.ARTICLE),
        (NodeLabel.ARTICLE, NodeLabel.CLAUSE),
        (NodeLabel.CLAUSE, NodeLabel.POINT),
    }
    edges = goc.structural_edges()

    assert {(label_of[e.parent_id], label_of[e.child_id]) for e in edges} <= allowed
    assert len(edges) == len(goc.all_nodes()) - 1


def test_ids_are_unique_and_stable_across_builds(tmp_path: Path) -> None:
    first, _, _ = build_from_markdown(tmp_path / "a", "Luật mẫu", GOC_MARKDOWN)
    second, _, _ = build_from_markdown(tmp_path / "b", "Luật mẫu", GOC_MARKDOWN)
    ids = [n.id for n in first.all_nodes()]

    assert len(ids) == len(set(ids))
    assert ids == [n.id for n in second.all_nodes()]
    assert first == second


def test_roman_numeral_chapter_number_is_int(tmp_path: Path) -> None:
    markdown = GOC_MARKDOWN.replace("## Chương II.", "## Chương XIV.")
    graph, _, _ = build_from_markdown(tmp_path, "Luật mẫu", markdown)

    chapter = next(s for s in graph.structures if s.label == "XIV")

    assert chapter.number == 14
    assert isinstance(chapter.number, int)


# --- Khoản, Điểm ---


def test_clause_order_and_implicit_clause(goc: GraphDocument) -> None:
    article_1 = _clauses_of(goc, "1")
    article_2 = _clauses_of(goc, "2")
    article_48a = _clauses_of(goc, "48a")

    assert len(article_1) == 1
    assert article_1[0].implicit is True
    assert article_1[0].label is None
    assert article_1[0].id.endswith("/khoan-implicit")
    assert [c.label for c in article_2] == ["1", "2", "3"]
    assert [c.order for c in article_2] == [1, 2, 3]
    assert all(not c.implicit for c in article_2)
    assert article_48a[0].implicit is True


def test_clause_label_with_letter_suffix_is_string(goc: GraphDocument) -> None:
    labels = [c.label for c in _clauses_of(goc, "4")]

    assert labels == ["1", "1a"]


def test_points_extracted_from_clause_text(goc: GraphDocument) -> None:
    clause = _clauses_of(goc, "2")[0]
    points = sorted(
        (p for p in goc.points if p.parent_id == clause.id), key=lambda p: p.order
    )

    assert [(p.label, p.order) for p in points] == [("a", 1), ("b", 2)]
    assert points[0].text.startswith("a) Có mặt")
    assert all(p.id.startswith(clause.id) for p in points)


def test_clause_without_points_has_none(goc: GraphDocument) -> None:
    clause = _clauses_of(goc, "2")[1]

    assert not [p for p in goc.points if p.parent_id == clause.id]


def test_split_points_separates_lead_in() -> None:
    lead, points = split_points("Gồm:\na) Một;\nb) Hai.")

    assert lead == "Gồm:"
    assert points == [("a", "a) Một;"), ("b", "b) Hai.")]


def test_split_points_ignores_points_inside_quotes() -> None:
    text = "Sửa đổi như sau: “\na) Nội dung trích\n”\nb) Điểm thật"

    lead, points = split_points(text)

    assert [label for label, _ in points] == ["b"]
    assert "a) Nội dung trích" in lead


def test_duplicate_point_labels_get_distinct_ids(tmp_path: Path) -> None:
    markdown = GOC_MARKDOWN.replace(
        "b) Có nơi ở thường xuyên tại Việt Nam.", "a) Điểm a lặp lại."
    )
    graph, _, _ = build_from_markdown(tmp_path, "Luật mẫu", markdown)

    ids = [p.id for p in graph.points if p.label == "a"]

    assert len(ids) == len(set(ids)) == 2


# --- char_count ---


def test_char_count_sums_clause_text_up_the_tree(goc: GraphDocument) -> None:
    article = _article(goc, "2")
    expected_article = sum(len(c.text) for c in _clauses_of(goc, "2"))
    chapter_1 = next(s for s in goc.structures if s.label == "I")
    expected_chapter = sum(
        len(c.text)
        for c in goc.clauses
        if c.parent_id in {a.id for a in goc.articles if a.parent_id == chapter_1.id}
    )

    assert article.char_count == expected_article > 0
    assert chapter_1.char_count == expected_chapter
    chapter_2 = next(s for s in goc.structures if s.label == "II")
    assert chapter_2.char_count == sum(
        a.char_count for a in goc.articles if a.parent_id != chapter_1.id
    )


def test_char_count_includes_raw_table(tmp_path: Path) -> None:
    table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    markdown = GOC_MARKDOWN.replace(
        "Nội dung Điều 48a.", f"Nội dung Điều 48a.\n\n{table}"
    )
    graph, _, _ = build_from_markdown(tmp_path, "Luật mẫu", markdown)

    clause = _clauses_of(graph, "48a")[0]

    assert clause.has_table is True
    assert clause.raw_table
    assert _article(graph, "48a").char_count == len(clause.text) + len(clause.raw_table)


# --- khớp chunk ---


def test_chunk_ids_match_exactly_one_clause_each(
    tmp_path: Path, goc: GraphDocument
) -> None:
    _, tree, chunks = build_from_markdown(tmp_path / "x", "Luật mẫu", GOC_MARKDOWN)
    by_breadcrumb = {c.breadcrumb: c.chunk_id for c in chunks}
    expected = [by_breadcrumb[breadcrumb_of(tree, i)] for i in range(len(tree.khoans))]

    assert [c.chunk_ids for c in goc.clauses] == [[cid] for cid in expected]
    assert goc.document.front_chunk_ids == [by_breadcrumb["LUẬT MẪU"]]
    assert goc.document.back_chunk_ids == [
        by_breadcrumb[f"LUẬT MẪU - {BACKMATTER_SUFFIX}"]
    ]


def test_khoan_1_does_not_swallow_khoan_1a_chunks(goc: GraphDocument) -> None:
    clauses = _clauses_of(goc, "4")

    assert len(clauses[0].chunk_ids) == 1
    assert len(clauses[1].chunk_ids) == 1
    assert clauses[0].chunk_ids != clauses[1].chunk_ids


def test_split_clause_collects_chunks_ordered_by_split_index(tmp_path: Path) -> None:
    markdown_path, _, _ = write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    tree = parse_markdown(markdown_path)
    target = next(
        i
        for i, k in enumerate(tree.khoans)
        if k.khoan_number == "1" and "Cá nhân cư trú" in k.content
    )
    base = breadcrumb_of(tree, target)
    chunks = [c for c in make_chunks(tree) if c.breadcrumb != base]
    parts = [
        make_chunk(base, tree.source_document, split=(index, 3), suffix=suffix)
        for index, suffix in [(2, " - Điểm b"), (0, ""), (1, " - Điểm a")]
    ]
    chunks.extend(parts)  # cố ý đảo thứ tự: 2, 0, 1
    graph = build_graph_document(
        tree,
        chunks,
        scan_structure_headings(markdown_path.read_text(encoding="utf-8")),
        "Luật mẫu",
    )

    clause = next(c for c in graph.clauses if c.text == tree.khoans[target].content)

    assert clause.chunk_ids == [parts[1].chunk_id, parts[2].chunk_id, parts[0].chunk_id]


def test_unmatched_chunk_fails_document(tmp_path: Path) -> None:
    markdown_path, _, chunks = write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    tree = parse_markdown(markdown_path)
    chunks.append(make_chunk("LUẬT MẪU - Chương I - Điều 9. Không tồn tại", "LUẬT MẪU"))

    with pytest.raises(GraphBuildError, match="không khớp"):
        build_graph_document(
            tree,
            chunks,
            scan_structure_headings(markdown_path.read_text(encoding="utf-8")),
            "Luật mẫu",
        )


def test_clause_without_chunk_fails_document(tmp_path: Path) -> None:
    markdown_path, _, chunks = write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    tree = parse_markdown(markdown_path)
    chunks = [c for c in chunks if c.breadcrumb != breadcrumb_of(tree, 1)]

    with pytest.raises(GraphBuildError, match="không có chunk"):
        build_graph_document(
            tree,
            chunks,
            scan_structure_headings(markdown_path.read_text(encoding="utf-8")),
            "Luật mẫu",
        )


def test_missing_front_chunk_fails_document(tmp_path: Path) -> None:
    markdown_path, _, chunks = write_document(tmp_path, "Luật mẫu", GOC_MARKDOWN)
    tree = parse_markdown(markdown_path)
    chunks = [c for c in chunks if c.breadcrumb != "LUẬT MẪU"]

    with pytest.raises(GraphBuildError, match="Front/back"):
        build_graph_document(
            tree,
            chunks,
            scan_structure_headings(markdown_path.read_text(encoding="utf-8")),
            "Luật mẫu",
        )


# --- cấu trúc ngoài mô hình ---


def test_appendix_heading_fails_scan() -> None:
    markdown = GOC_MARKDOWN.replace(
        "\n---\n", "\n# PHỤ LỤC I\n\n#### Điều 50. Trong phụ lục\n\n---\n"
    )

    with pytest.raises(GraphBuildError, match="Phụ lục"):
        scan_structure_headings(markdown)


def test_scan_structure_headings_skips_frontmatter_and_backmatter() -> None:
    headings = scan_structure_headings(GOC_MARKDOWN)

    assert [(h.node_label, h.label) for h in headings] == [
        (NodeLabel.CHAPTER, "I"),
        (NodeLabel.ARTICLE, "1"),
        (NodeLabel.ARTICLE, "2"),
        (NodeLabel.CHAPTER, "II"),
        (NodeLabel.SECTION, "1"),
        (NodeLabel.ARTICLE, "3"),
        (NodeLabel.ARTICLE, "4"),
        (NodeLabel.ARTICLE, "48a"),
    ]


def test_duplicate_article_label_fails(tmp_path: Path) -> None:
    markdown = GOC_MARKDOWN.replace("Điều 3. Viện dẫn", "Điều 2. Viện dẫn")

    with pytest.raises(GraphBuildError):
        build_from_markdown(tmp_path, "Luật mẫu", markdown)
