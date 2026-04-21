from pathlib import Path

from LangGraph_loop import graph
from langgraph_state import GraphState


def main() -> None:
    test_file = Path("private-draft.tex")
    if not test_file.exists():
        raise FileNotFoundError(f"Test file not found: {test_file}")

    original_tex = test_file.read_text(encoding="utf-8")
    initial_state = GraphState(original_tex=original_tex)
    result = graph.invoke(initial_state)

    # LangGraph may return dict-like state or model instance.
    if isinstance(result, dict):
        final_state = GraphState(**result)
    else:
        final_state = result

    print("=== Demo Finished ===")
    print(f"Iterations: {final_state.iteration}")
    print(f"Best score: {final_state.best_score:.4f}")
    print(f"History items: {len(final_state.history)}")
    print()
    print("=== Best TeX Preview ===")
    preview = final_state.best_tex if final_state.best_tex else final_state.current_tex
    print(preview[:1200])


if __name__ == "__main__":
    main()
