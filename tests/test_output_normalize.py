"""Tests for document prefix/suffix assembly and literal ``\\n`` cleanup in LaTeX bodies."""

from langgraph_state import GraphState, Section
from paper_reviewer_tool import (
    assemble_output_tex,
    normalize_fake_newlines_in_latex,
    render_sections,
    split_prefix_and_sections,
)


def test_split_prefix_preserves_preamble() -> None:
    tex = (
        "% header\n"
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{A}\n"
        "body-a\n"
        "\\section{B}\n"
        "body-b\n"
    )
    prefix, sections = split_prefix_and_sections(tex)
    assert "\\documentclass" in prefix
    assert "\\section{A}" not in prefix
    assert len(sections) == 2
    assert sections[0].content.strip() == "body-a"
    assert sections[1].content.strip() == "body-b"


def test_normalize_fake_newlines_preserves_neq() -> None:
    s = r"a \neq b"
    assert normalize_fake_newlines_in_latex(s) == s


def test_normalize_fake_newlines_preserves_nabla() -> None:
    s = r"$\nabla \phi$"
    assert normalize_fake_newlines_in_latex(s) == s


def test_normalize_fake_newlines_replaces_literal_n() -> None:
    s = "intro\\nwhere x"
    out = normalize_fake_newlines_in_latex(s)
    assert out.startswith("intro\nwhere")


def test_assemble_output_tex_prefix_plus_body() -> None:
    sec = Section(id="sec_0", title="\\section{X}", content="y")
    out = assemble_output_tex("PREFIX\n", "", "", [sec])
    assert out.startswith("PREFIX\n")
    assert "\\section{X}" in out
    assert "y" in out


def test_assemble_output_tex_prefers_best_tex() -> None:
    sec = Section(id="sec_0", title="\\section{X}", content="old")
    out = assemble_output_tex("", "BEST", "CUR", [sec])
    assert out == "BEST"


def test_assemble_output_tex_matches_graphstate_fields() -> None:
    st = GraphState(
        original_tex="",
        document_prefix="P:\n",
        best_tex="",
        current_tex=render_sections([Section(id="s0", title="\\section{A}", content="b")]),
        sections=[Section(id="s0", title="\\section{A}", content="b")],
    )
    assert assemble_output_tex(
        st.document_prefix, st.best_tex, st.current_tex, st.sections
    ).startswith("P:\n")
