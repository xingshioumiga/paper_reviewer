import subprocess
import sys
from pathlib import Path

from LangGraph_loop import graph
from langgraph_state import GraphState


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


def test_cli_generates_output_file(tmp_path):
    input_path = tmp_path / "input.tex"
    output_path = tmp_path / "generated_output.tex"
    input_path.write_text("\\section{Intro}\nDemo content.", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "run_demo.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--max-iterations",
            "1",
            "--max-no-improve",
            "1",
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "\\section{Intro}" in content
