import pytest
from langgraph_state import GraphState, Section, Issue, HistoryItem


@pytest.fixture
def basic_state() -> GraphState:
    """Minimal GraphState with two sections for routing / node tests."""
    return GraphState(
        original_tex="\\section{Intro}\ncontent\\section{Method}\nmethod content",
        sections=[
            Section(id="sec_0", title="\\section{Intro}", content="intro content"),
            Section(id="sec_1", title="\\section{Method}", content="method content"),
        ],
        document_prefix="",
        run_started_at=42.0,
    )


@pytest.fixture
def single_section_state() -> GraphState:
    return GraphState(
        original_tex="\\section{Only}\ntext",
        sections=[Section(id="sec_0", title="\\section{Only}", content="just one section")],
        document_prefix="",
    )


@pytest.fixture
def state_with_history() -> GraphState:
    """State with one accepted and one rejected history entry."""
    sections = [
        Section(id="sec_0", title="\\section{Intro}", content="accepted content"),
        Section(id="sec_1", title="\\section{Method}", content="method content"),
    ]
    state = GraphState(
        original_tex="",
        sections=sections,
        best_tex="\\section{Intro}\naccepted content",
        history=[
            HistoryItem(
                iteration=0,
                section_id="sec_0",
                before="original intro",
                after="accepted content",
                score=0.85,
                accepted=True,
            ),
            HistoryItem(
                iteration=0,
                section_id="sec_1",
                before="original method",
                after="worse method",
                score=0.55,
                accepted=False,
            ),
        ],
    )
    return state


@pytest.fixture
def glossary_enabled_state(basic_state: GraphState) -> GraphState:
    basic_state.glossary_enabled = True
    basic_state.glossary_locked = {"NLP": "Natural Language Processing"}
    basic_state.glossary_provisional = {"ML": "Machine Learning"}
    return basic_state
