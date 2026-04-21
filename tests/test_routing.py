from langgraph_nodes import has_more_sections, route_after_iteration
from langgraph_state import GraphState
from paper_reviewer_tool import split_into_sections


def test_has_more_sections_routes_to_reviewer_then_iteration_step():
    state = GraphState(original_tex="\\section{A}\ntext")
    state.sections = split_into_sections(state.original_tex)
    state.current_section_index = 0
    assert has_more_sections(state) == "reviewer"

    state.current_section_index = len(state.sections)
    assert has_more_sections(state) == "iteration_step"


def test_route_after_iteration_ends_on_max_iterations():
    state = GraphState(original_tex="\\section{A}\ntext", max_iterations=2)
    state.iteration = 2
    assert route_after_iteration(state) == "end"


def test_route_after_iteration_ends_on_no_improve_limit():
    state = GraphState(original_tex="\\section{A}\ntext", max_no_improve=1)
    state.no_improve_rounds = 1
    assert route_after_iteration(state) == "end"


def test_route_after_iteration_continues_when_limits_not_reached():
    state = GraphState(
        original_tex="\\section{A}\ntext",
        max_iterations=3,
        max_no_improve=3,
    )
    state.iteration = 1
    state.no_improve_rounds = 1
    assert route_after_iteration(state) == "reviewer"
