"""Unit tests for pure / mock functions in `langgraph_nodes.py`.

Covers internal helpers, mock nodes, aggregator, and routing logic.
LLM-bound functions (`*_node_llm`) require integration testing.
"""

import random
import time
from unittest.mock import patch

import httpx

import pytest

from langgraph_nodes import (
    _elapsed_seconds,
    _glossary_appendix,
    _critic_glossary_note,
    _is_retryable_ollama_transport,
    _is_section_skipped,
    _next_active_section_index,
    _progress_args,
    _resolved_json_parse_attempts,
    _resolved_num_predict,
    aggregator_node,
    critic_node,
    editor_node,
    glossary_node_noop,
    has_more_sections,
    init_node,
    iteration_step,
    next_section,
    reviewer_node,
    route_after_iteration,
    section_score_summary,
)
from langgraph_state import GraphState, HistoryItem, Issue, Section


# =============================================================================
# Internal helpers
# =============================================================================

class TestIsRetryableOllamaTransport:
    """Tests for `_is_retryable_ollama_transport`.

    The function checks:
    - Exception class name for `RemoteProtocolError`, `ReadTimeout`, `ConnectError`
    - Module prefix `httpx.` or `httpcore.` with name containing `Timeout`, `Protocol`, `Connect`
    - `status_code` attribute for 502/503/504
    """

    def test_connect_error_by_name(self):
        exc = httpx.ConnectError("connection refused")
        assert _is_retryable_ollama_transport(exc) is True

    def test_read_timeout_by_name(self):
        exc = httpx.ReadTimeout("timed out")
        assert _is_retryable_ollama_transport(exc) is True

    def test_remote_protocol_error_by_name(self):
        exc = httpx.RemoteProtocolError("remote error")
        assert _is_retryable_ollama_transport(exc) is True

    def test_httpcore_connect_error_by_name(self):
        """httpcore.ConnectError: name contains `ConnectError`, caught by name check."""
        import httpcore
        exc = httpcore.ConnectError("connection error")
        assert _is_retryable_ollama_transport(exc) is True

    def test_status_code_502_retryable(self):
        exc = httpx.HTTPStatusError("502 Bad Gateway", request=None, response=None)
        exc.status_code = 502  # type: ignore
        assert _is_retryable_ollama_transport(exc) is True

    def test_status_code_503_retryable(self):
        exc = httpx.HTTPStatusError("503 Service Unavailable", request=None, response=None)
        exc.status_code = 503  # type: ignore
        assert _is_retryable_ollama_transport(exc) is True

    def test_status_code_504_retryable(self):
        exc = httpx.HTTPStatusError("504 Gateway Timeout", request=None, response=None)
        exc.status_code = 504  # type: ignore
        assert _is_retryable_ollama_transport(exc) is True

    def test_status_code_4xx_not_retryable(self):
        exc = httpx.HTTPStatusError("400 Bad Request", request=None, response=None)
        exc.status_code = 400  # type: ignore
        assert _is_retryable_ollama_transport(exc) is False

    def test_unrelated_exception(self):
        exc = ValueError("not retryable")
        assert _is_retryable_ollama_transport(exc) is False

    def test_exception_without_status_code(self):
        exc = httpx.HTTPStatusError("no status", request=None, response=None)
        assert _is_retryable_ollama_transport(exc) is False


class TestResolvedNumPredict:
    """Tests for `_resolved_num_predict`."""

    def test_role_override_takes_precedence(self):
        llm_cfg = {"num_predict": 4096}
        role = {"num_predict": 2048}
        assert _resolved_num_predict(llm_cfg, role) == 2048

    def test_role_null_returns_none(self):
        llm_cfg = {"num_predict": 4096}
        role = {"num_predict": None}
        assert _resolved_num_predict(llm_cfg, role) is None

    def test_falls_back_to_llm_cfg(self):
        llm_cfg = {"num_predict": 8192}
        role: dict = {}
        assert _resolved_num_predict(llm_cfg, role) == 8192

    def test_role_missing_falls_back(self):
        llm_cfg = {"num_predict": 16384}
        role: dict = {"other": "val"}
        assert _resolved_num_predict(llm_cfg, role) == 16384


class TestResolvedJsonParseAttempts:
    """Tests for `_resolved_json_parse_attempts`."""

    def test_role_override(self):
        llm_cfg = {"json_parse_retries": 3}
        role = {"json_parse_retries": 5}
        assert _resolved_json_parse_attempts(llm_cfg, role, 3) == 5

    def test_falls_back_to_llm_cfg(self):
        llm_cfg = {"json_parse_retries": 7}
        role: dict = {}
        assert _resolved_json_parse_attempts(llm_cfg, role, 3) == 7

    def test_falls_back_to_default(self):
        llm_cfg: dict = {}
        role: dict = {}
        assert _resolved_json_parse_attempts(llm_cfg, role, 4) == 4

    def test_minimum_is_1(self):
        llm_cfg = {"json_parse_retries": 0}
        role: dict = {}
        assert _resolved_json_parse_attempts(llm_cfg, role, 3) == 1


class TestElapsedSeconds:
    """Tests for `_elapsed_seconds`."""

    def test_returns_zero_when_not_set(self):
        state = GraphState(original_tex="x")
        assert _elapsed_seconds(state) == 0.0

    def test_returns_positive_elapsed(self):
        state = GraphState(original_tex="x", run_started_at=time.monotonic() - 5)
        elapsed = _elapsed_seconds(state)
        assert 4.0 <= elapsed <= 6.0


class TestProgressArgs:
    """Tests for `_progress_args`."""

    def test_tuple_structure(self, basic_state):
        args = _progress_args(basic_state)
        assert len(args) == 5
        iteration, max_iter, section_num, total_sections, elapsed = args
        assert iteration == 1  # iteration 0 + 1
        assert max_iter == 3
        assert section_num == 1  # current_section_index 0 + 1
        assert total_sections == 2
        assert elapsed >= 0.0

    def test_section_number_capped_at_zero_when_no_sections(self):
        """When sections list is empty, section_number is 0 (min(100, 0))."""
        state = GraphState(original_tex="x")
        state.current_section_index = 99
        args = _progress_args(state)
        assert args[2] == 0


class TestIsSectionSkipped:
    """Tests for `_is_section_skipped`."""

    def test_skipped_section(self):
        state = GraphState(original_tex="x")
        state.skipped_section_ids = ["sec_0", "sec_2"]
        assert _is_section_skipped(state, "sec_0") is True
        assert _is_section_skipped(state, "sec_2") is True

    def test_not_skipped(self):
        state = GraphState(original_tex="x")
        state.skipped_section_ids = ["sec_0"]
        assert _is_section_skipped(state, "sec_1") is False

    def test_empty_skipped(self):
        state = GraphState(original_tex="x")
        assert _is_section_skipped(state, "any") is False


class TestNextActiveSectionIndex:
    """Tests for `_next_active_section_index`."""

    def test_skips_sections(self):
        state = GraphState(original_tex="")
        state.sections = [
            Section(id="sec_0", title="A", content="a"),
            Section(id="sec_1", title="B", content="b"),
            Section(id="sec_2", title="C", content="c"),
        ]
        state.skipped_section_ids = ["sec_1"]
        assert _next_active_section_index(state, 0) == 0
        assert _next_active_section_index(state, 1) == 2
        assert _next_active_section_index(state, 2) == 2

    def test_beyond_end_returns_length(self):
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_0", title="A", content="a")]
        state.skipped_section_ids = ["sec_0"]
        assert _next_active_section_index(state, 0) == 1

    def test_empty_sections(self):
        state = GraphState(original_tex="")
        assert _next_active_section_index(state, 0) == 0


class TestSectionScoreSummary:
    """Tests for `section_score_summary`."""

    def test_returns_accepted_scores_in_document_order(self):
        state = GraphState(original_tex="")
        state.sections = [
            Section(id="sec_0", title="A", content="a"),
            Section(id="sec_1", title="B", content="b"),
        ]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="", after="", score=0.8, accepted=True),
            HistoryItem(iteration=1, section_id="sec_0", before="", after="", score=0.9, accepted=True),
            HistoryItem(iteration=0, section_id="sec_1", before="", after="", score=0.7, accepted=True),
        ]
        summary = section_score_summary(state)
        assert summary == [("sec_0", 0.9), ("sec_1", 0.7)]

    def test_unaccepted_scores_zero(self):
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_0", title="A", content="a")]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="", after="", score=0.5, accepted=False),
        ]
        summary = section_score_summary(state)
        assert summary == [("sec_0", 0.0)]

    def test_section_not_in_history_defaults_zero(self):
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_new", title="New", content="n")]
        assert section_score_summary(state) == [("sec_new", 0.0)]

    def test_empty_sections(self):
        state = GraphState(original_tex="")
        assert section_score_summary(state) == []


# =============================================================================
# init_node
# =============================================================================

class TestInitNode:
    """Tests for `init_node`."""

    def test_parses_sections(self):
        state = GraphState(original_tex="\\section{A}\nbody")
        result = init_node(state)
        assert len(result.sections) == 1
        assert result.sections[0].title == "\\section{A}"
        assert result.sections[0].content == "body"

    def test_splits_prefix(self):
        state = GraphState(original_tex="preamble\n\\section{A}\nbody")
        result = init_node(state)
        assert result.document_prefix == "preamble\n"
        assert len(result.sections) == 1

    def test_sets_run_started_at(self):
        state = GraphState(original_tex="\\section{A}\nbody")
        assert state.run_started_at == 0.0
        result = init_node(state)
        assert result.run_started_at > 0.0

    def test_best_tex_and_current_tex(self):
        state = GraphState(original_tex="\\section{A}\nbody")
        result = init_node(state)
        assert "\\section{A}" in result.best_tex
        assert "\\section{A}" in result.current_tex


# =============================================================================
# glossary appendix helpers
# =============================================================================

class TestGlossaryAppendix:
    """Tests for `_glossary_appendix` and `_critic_glossary_note`."""

    def test_empty_when_disabled(self, basic_state):
        basic_state.glossary_enabled = False
        assert _glossary_appendix(basic_state) == ""
        assert _critic_glossary_note(basic_state) == ""

    def test_non_empty_when_enabled(self, glossary_enabled_state):
        appendix = _glossary_appendix(glossary_enabled_state)
        assert len(appendix) > 0
        assert "NLP" in appendix

    def test_critic_note_includes_consistency_hint(self, glossary_enabled_state):
        note = _critic_glossary_note(glossary_enabled_state)
        assert len(note) > 0
        assert "NLP" in note


class TestGlossaryNodeNoop:
    """Tests for `glossary_node_noop` - should return state unchanged."""

    def test_returns_unchanged_state(self, basic_state):
        result = glossary_node_noop(basic_state)
        assert result is basic_state


# =============================================================================
# reviewer_node (mock)
# =============================================================================

class TestReviewerNode:
    """Tests for mock `reviewer_node`."""

    def test_sets_stub_issues(self, basic_state):
        result = reviewer_node(basic_state)
        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.section_id == "sec_0"
        assert issue.problem == "Sentence unclear"
        assert issue.severity == "medium"


# =============================================================================
# editor_node (mock)
# =============================================================================

class TestEditorNode:
    """Tests for mock `editor_node`."""

    def test_modifies_content_and_appends_history(self, basic_state):
        basic_state.issues = [
            Issue(section_id="sec_0", problem="Unclear", severity="medium"),
        ]
        original_content = basic_state.sections[0].content
        result = editor_node(basic_state)
        assert result.sections[0].content == original_content + "\n% improved"
        assert len(result.history) == 1
        assert result.history[0].section_id == "sec_0"
        assert result.history[0].before == original_content
        assert result.history[0].after == original_content + "\n% improved"

    def test_only_appends_markers_matching_section(self, basic_state):
        basic_state.issues = [
            Issue(section_id="sec_0", problem="Issue1", severity="low"),
            Issue(section_id="sec_1", problem="Issue2", severity="high"),
        ]
        basic_state.current_section_index = 1
        original = basic_state.sections[1].content
        result = editor_node(basic_state)
        assert result.sections[1].content == original + "\n% improved"


# =============================================================================
# critic_node (mock random)
# =============================================================================

class TestCriticNode:
    """Tests for mock `critic_node` (random score)."""

    def test_sets_current_score_in_range(self, basic_state):
        random.seed(42)
        result = critic_node(basic_state)
        assert 0.6 <= result.current_score <= 0.95

    def test_deterministic_with_seed(self, basic_state):
        random.seed(123)
        score_a = critic_node(basic_state).current_score
        random.seed(123)
        score_b = critic_node(basic_state).current_score
        assert score_a == score_b


# =============================================================================
# aggregator_node
# =============================================================================

class TestAggregatorNode:
    """Tests for `aggregator_node` accept/reject/skip logic.

    The aggregator compares `current_score` against the **last accepted**
    score for the same section (baseline 0.0 if none).
    If current_score > previous_score → accept, else → reject (with rollback).
    After `max_no_improve` consecutive non-improving rounds → section skipped.
    """

    def test_accepts_when_score_beats_previous(self):
        """Score 0.9 beats previous accepted 0.85 → accepted."""
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_0", title="\\section{Intro}", content="v2")]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="v0", after="v1", score=0.85, accepted=True),
            HistoryItem(iteration=1, section_id="sec_0", before="v1", after="v2", score=0.0, accepted=False),
        ]
        state.current_score = 0.9
        result = aggregator_node(state)
        assert result.history[-1].accepted is True
        assert result.history[-1].score == 0.9

    def test_rejects_when_score_lower_than_previous(self):
        """Score 0.7 loses to previous accepted 0.85 → rejected."""
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_0", title="\\section{Intro}", content="worse version")]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="v0", after="accepted version", score=0.85, accepted=True),
            HistoryItem(iteration=1, section_id="sec_0", before="accepted version", after="worse version", score=0.0, accepted=False),
        ]
        state.current_score = 0.7
        state.best_tex = "\\section{Intro}\nworse version"
        result = aggregator_node(state)
        assert result.history[-1].accepted is False
        assert result.history[-1].score == 0.7

    def test_reject_rolls_back_section_content(self):
        """Rejected edit rolls section content back to the previous accepted version."""
        state = GraphState(original_tex="")
        state.sections = [
            Section(id="sec_0", title="\\section{Intro}", content="worse version"),
        ]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="original", after="accepted", score=0.85, accepted=True),
            HistoryItem(iteration=1, section_id="sec_0", before="accepted", after="worse version", score=0.0, accepted=False),
        ]
        state.current_score = 0.6  # below 0.85
        state.best_tex = "\\section{Intro}\noriginal"
        result = aggregator_node(state)
        assert result.sections[0].content == "accepted"

    def test_skip_threshold_triggers(self):
        """After `max_no_improve` (=2) consecutive non-improving tries, section gets skipped.

        State pre-seeded with `section_no_improve_rounds={'sec_0': 1}` to simulate
        one previous no-improve round. A second rejection pushes it to 2 → skipped.
        """
        state = GraphState(original_tex="", max_no_improve=2)
        state.sections = [
            Section(id="sec_0", title="\\section{Intro}", content="round 3 content"),
        ]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="v0", after="v1", score=0.85, accepted=True),
            HistoryItem(iteration=1, section_id="sec_0", before="v1", after="v2", score=0.6, accepted=False),
            HistoryItem(iteration=2, section_id="sec_0", before="v2", after="round 3 content", score=0.0, accepted=False),
        ]
        state.current_score = 0.6  # still below 0.85
        state.best_tex = "\\section{Intro}\nround 3 content"
        state.section_no_improve_rounds = {"sec_0": 1}  # pre-seeded: one prior no-improve
        result = aggregator_node(state)
        assert "sec_0" in result.skipped_section_ids

    def test_first_edit_for_section_accepted_when_no_prior_accept(self):
        """No previous accepted entry for this section → baseline 0.0, so any positive score is accepted."""
        state = GraphState(original_tex="")
        state.sections = [Section(id="sec_0", title="\\section{A}", content="v1")]
        state.history = [
            HistoryItem(iteration=0, section_id="sec_0", before="v0", after="v1", score=0.0, accepted=False),
        ]
        state.current_score = 0.75
        result = aggregator_node(state)
        assert result.history[-1].accepted is True


# =============================================================================
# next_section
# =============================================================================

class TestNextSection:
    """Tests for `next_section`."""

    def test_advances_index(self, basic_state):
        assert basic_state.current_section_index == 0
        result = next_section(basic_state)
        assert result.current_section_index == 1

    def test_skips_to_next_active(self):
        """When the next section is skipped, advance past it."""
        state = GraphState(original_tex="")
        state.sections = [
            Section(id="sec_0", title="A", content="a"),
            Section(id="sec_1", title="B", content="b"),
            Section(id="sec_2", title="C", content="c"),
        ]
        state.skipped_section_ids = ["sec_1"]
        state.current_section_index = 0

        # first call: sec_0 is active, advances to sec_1 (start_index=1); sec_1 is skipped → goes to sec_2
        result = next_section(state)
        assert result.current_section_index == 2

        # second call: sec_2 is active, advances past end
        result2 = next_section(result)
        assert result2.current_section_index == 3


# =============================================================================
# has_more_sections
# =============================================================================

class TestHasMoreSections:
    """Tests for `has_more_sections` routing."""

    def test_returns_glossary_when_section_available(self, basic_state):
        assert has_more_sections(basic_state) == "glossary"

    def test_returns_iteration_step_at_end(self, basic_state):
        basic_state.current_section_index = 2
        assert has_more_sections(basic_state) == "iteration_step"

    def test_skips_to_iteration_step_when_all_skipped(self, basic_state):
        basic_state.skipped_section_ids = ["sec_0", "sec_1"]
        assert has_more_sections(basic_state) == "iteration_step"


# =============================================================================
# iteration_step
# =============================================================================

class TestIterationStep:
    """Tests for `iteration_step`."""

    def test_bumps_iteration(self, basic_state):
        result = iteration_step(basic_state)
        assert result.iteration == 1

    def test_sets_no_improve_flag_when_no_accepts(self, basic_state):
        result = iteration_step(basic_state)
        assert result.stop_due_to_no_document_improve is True

    def test_clears_flag_when_accepts_exist(self, basic_state):
        basic_state.iteration_accepted_count = 3
        result = iteration_step(basic_state)
        assert result.stop_due_to_no_document_improve is False
        assert result.iteration_accepted_count == 0

    def test_resets_section_index(self, basic_state):
        basic_state.current_section_index = 5
        result = iteration_step(basic_state)
        assert result.current_section_index == 0


# =============================================================================
# route_after_iteration
# =============================================================================

class TestRouteAfterIteration:
    """Tests for `route_after_iteration` end conditions."""

    def test_ends_when_max_iterations_reached(self):
        state = GraphState(original_tex="x", max_iterations=3, iteration=3)
        assert route_after_iteration(state) == "end"

    def test_ends_on_no_document_improve(self):
        state = GraphState(original_tex="x", max_iterations=5, iteration=2)
        state.stop_due_to_no_document_improve = True
        assert route_after_iteration(state) == "end"

    def test_ends_when_no_active_sections(self):
        state = GraphState(original_tex="x", max_iterations=5, iteration=1)
        state.current_section_index = 5  # beyond sections
        assert route_after_iteration(state) == "end"

    def test_continues_when_conditions_not_met(self):
        state = GraphState(original_tex="\\section{A}\ntext")
        state.iteration = 1
        state.max_iterations = 5
        from paper_reviewer_tool import split_into_sections
        state.sections = split_into_sections(state.original_tex)
        assert route_after_iteration(state) == "glossary"
