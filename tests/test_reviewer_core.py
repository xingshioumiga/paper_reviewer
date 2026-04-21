from pathlib import Path

from LangGraph_loop import graph
from langgraph_nodes import has_more_sections, route_after_iteration
from langgraph_state import GraphState
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


def test_routing_logic_covers_continue_and_end():
    state = GraphState(original_tex="\\section{A}\ntext")
    state.sections = split_into_sections(state.original_tex)
    state.current_section_index = 0

    assert has_more_sections(state) == "reviewer"

    state.current_section_index = len(state.sections)
    assert has_more_sections(state) == "iteration_step"

    state.iteration = state.max_iterations
    assert route_after_iteration(state) == "end"


def test_graph_invoke_generates_history(monkeypatch):
    # Make score deterministic for stable tests.
    monkeypatch.setattr("langgraph_nodes.random.uniform", lambda a, b: 0.8)

    tex = Path("private-draft.tex").read_text(encoding="utf-8")
    initial_state = GraphState(original_tex=tex, max_iterations=1, max_no_improve=5)
    result = graph.invoke(initial_state)
    final_state = GraphState(**result) if isinstance(result, dict) else result

    assert final_state.iteration == 1
    assert len(final_state.history) > 0
    assert final_state.best_score >= 0.8
