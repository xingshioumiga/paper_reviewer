from langgraph_state import Section
from paper_reviewer_tool import render_sections, split_into_sections


# 校验 LaTeX section 解析不受嵌套 label 与注释干扰 / section parsing ignores nested labels and comments.
def test_split_into_sections_parses_three_sections():
    tex = (
        "\\section{Intro}\nFirst part.\n"
        "\\section{Method}\nSecond part.\n"
        "\\section{Result}\nThird part.\n"
    )
    sections = split_into_sections(tex)

    assert len(sections) == 3
    assert sections[0].title == "\\section{Intro}"
    assert "First part." in sections[0].content
    assert sections[1].title == "\\section{Method}"


def test_split_into_sections_returns_empty_when_no_sections():
    tex = "This document has no explicit section markers."
    sections = split_into_sections(tex)
    assert sections == []


def test_split_into_sections_handles_empty_input():
    assert split_into_sections("") == []


def test_split_into_sections_handles_complex_latex():
    tex = (
        "\\section{Method}\n"
        "Equation: \\[E = mc^2\\]\n"
        "\\subsection{Details}\n"
        "Itemize content.\n"
        "\\section{Results}\n"
        "Table and references.\n"
    )
    sections = split_into_sections(tex)
    assert len(sections) == 2
    assert sections[0].title == "\\section{Method}"
    assert "\\subsection{Details}" in sections[0].content


def test_split_into_sections_preserves_nested_label_in_title():
    tex = (
        "\\section{\\label{sec:1}Introduction}\n"
        "Intro body.\n"
        "\\section{\\label{sec:2}Method}\n"
        "Method body.\n"
    )
    sections = split_into_sections(tex)

    assert len(sections) == 2
    assert sections[0].title == "\\section{\\label{sec:1}Introduction}"
    assert sections[0].content == "Intro body."
    assert sections[1].title == "\\section{\\label{sec:2}Method}"


def test_split_into_sections_ignores_commented_section_commands():
    tex = (
        "\\section{A}\n"
        "A body.\n"
        "% \\section{Commented out}\n"
        "Still A body.\n"
        "\\section{B}\n"
        "B body.\n"
    )
    sections = split_into_sections(tex)

    assert len(sections) == 2
    assert sections[0].title == "\\section{A}"
    assert "% \\section{Commented out}" in sections[0].content
    assert sections[1].title == "\\section{B}"


def test_render_sections_strips_accidental_leading_section_from_content():
    rendered = render_sections(
        [
            Section(
                id="sec_0",
                title="\\section{\\label{sec:1}Introduction}",
                content="\\section{Introduction}\\label{sec:1}\nIntro body.",
            )
        ]
    )

    assert rendered == "\\section{\\label{sec:1}Introduction}\nIntro body."
