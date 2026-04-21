from paper_reviewer_tool import split_into_sections


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
