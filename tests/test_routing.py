from langgraph_nodes import has_more_sections, iteration_step, next_section, route_after_iteration
from langgraph_state import GraphState
from paper_reviewer_tool import split_into_sections


# 这些测试覆盖 section 路由、跳过逻辑和整轮无改进停止条件。
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


def test_route_after_iteration_ends_after_full_round_without_document_improvement():
    state = GraphState(original_tex="\\section{A}\ntext", max_iterations=3)
    state.stop_due_to_no_document_improve = True
    assert route_after_iteration(state) == "end"


def test_route_after_iteration_continues_when_limits_not_reached():
    state = GraphState(
        original_tex="\\section{A}\ntext",
        max_iterations=3,
        max_no_improve=3,
    )
    state.iteration = 1
    state.sections = split_into_sections(state.original_tex)
    assert route_after_iteration(state) == "reviewer"


def test_next_section_skips_sections_that_reached_no_improve_limit():
    state = GraphState(
        original_tex="\\section{A}\na\n\\section{B}\nb\n\\section{C}\nc",
        max_no_improve=1,
    )
    state.sections = split_into_sections(state.original_tex)
    state.skipped_section_ids = ["sec_1"]
    state.current_section_index = 0

    result = next_section(state)

    assert result.current_section_index == 2
    assert has_more_sections(result) == "reviewer"


def test_iteration_step_stops_when_no_section_was_accepted_in_round():
    state = GraphState(original_tex="\\section{A}\na", max_iterations=3)
    state.sections = split_into_sections(state.original_tex)
    state.iteration_accepted_count = 0

    result = iteration_step(state)

    assert result.stop_due_to_no_document_improve is True
    assert route_after_iteration(result) == "end"
