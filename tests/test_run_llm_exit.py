"""run.py exit behaviour when the graph reports LLM failures."""

import sys
from pathlib import Path

import pytest

import LangGraph_loop_llm as lg_loop
from langgraph_state import GraphState


def test_run_exits_1_when_llm_failures_reported(monkeypatch, tmp_path: Path) -> None:
    inp = tmp_path / "in.tex"
    inp.write_text("\\section{X}\nbody", encoding="utf-8")
    out = tmp_path / "out.tex"
    cfg = tmp_path / "c.yaml"
    cfg.write_text("ollama_healthcheck: false\n", encoding="utf-8")

    def fake_invoke(state: GraphState, *args: object, **kwargs: object) -> GraphState:
        return GraphState(
            original_tex=state.original_tex,
            llm_failure_count=1,
            current_tex="x",
            best_tex="x",
        )

    monkeypatch.setattr(lg_loop.graph, "invoke", fake_invoke)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--input",
            str(inp),
            "--output",
            str(out),
            "--config",
            str(cfg),
        ],
    )

    import run as run_mod

    with pytest.raises(SystemExit) as excinfo:
        run_mod.main()
    assert excinfo.value.code == 1
    assert out.exists()


def test_run_exits_0_with_allow_llm_failures(monkeypatch, tmp_path: Path) -> None:
    inp = tmp_path / "in.tex"
    inp.write_text("\\section{X}\nbody", encoding="utf-8")
    out = tmp_path / "out.tex"
    cfg = tmp_path / "c.yaml"
    cfg.write_text("ollama_healthcheck: false\n", encoding="utf-8")

    def fake_invoke(state: GraphState, *args: object, **kwargs: object) -> GraphState:
        return GraphState(
            original_tex=state.original_tex,
            llm_failure_count=2,
            current_tex="y",
            best_tex="y",
        )

    monkeypatch.setattr(lg_loop.graph, "invoke", fake_invoke)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--input",
            str(inp),
            "--output",
            str(out),
            "--config",
            str(cfg),
            "--allow-llm-failures",
        ],
    )

    import run as run_mod

    run_mod.main()
    assert out.exists()
