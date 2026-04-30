from langgraph_nodes import aggregator_node
from langgraph_state import GraphState, HistoryItem, Section


def test_aggregator_compares_against_previous_same_section_and_rolls_back():
    state = GraphState(original_tex="")
    state.sections = [
        Section(id="sec_0", title="\\section{Intro}", content="worse intro"),
        Section(id="sec_1", title="\\section{Method}", content="method"),
    ]
    state.history = [
        HistoryItem(
            iteration=0,
            section_id="sec_0",
            before="original intro",
            after="better intro",
            score=0.8,
            accepted=True,
        ),
        HistoryItem(
            iteration=1,
            section_id="sec_0",
            before="better intro",
            after="worse intro",
            score=0.0,
            accepted=False,
        ),
    ]
    state.current_score = 0.7
    state.best_score = 0.8
    state.best_tex = "\\section{Intro}\nbetter intro"

    result = aggregator_node(state)

    assert result.history[-1].score == 0.7
    assert result.history[-1].accepted is False
    assert result.sections[0].content == "better intro"
    assert "\\section{Intro}\nbetter intro" in result.current_tex
    assert result.no_improve_rounds == 1


def test_aggregator_accepts_when_score_beats_previous_same_section():
    state = GraphState(original_tex="")
    state.sections = [
        Section(id="sec_0", title="\\section{Intro}", content="best intro"),
    ]
    state.history = [
        HistoryItem(
            iteration=0,
            section_id="sec_0",
            before="original intro",
            after="better intro",
            score=0.8,
            accepted=True,
        ),
        HistoryItem(
            iteration=1,
            section_id="sec_0",
            before="better intro",
            after="best intro",
            score=0.0,
            accepted=False,
        ),
    ]
    state.current_score = 0.9
    state.best_score = 0.8
    state.no_improve_rounds = 2

    result = aggregator_node(state)

    assert result.history[-1].score == 0.9
    assert result.history[-1].accepted is True
    assert result.sections[0].content == "best intro"
    assert result.best_score == 0.9
    assert result.no_improve_rounds == 0
