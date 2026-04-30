import argparse
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from LangGraph_loop import graph
from langgraph_state import GraphState
from utils.logging_setup import setup_logging


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a mapping at top level.")
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the paper reviewer demo pipeline.")
    parser.add_argument("--input", dest="input_path", help="Input TeX file path")
    parser.add_argument("--output", dest="output_path", help="Output TeX file path")
    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/local.yaml",
        help="Config YAML path",
    )
    parser.add_argument("--max-iterations", type=int, help="Override max iterations")
    parser.add_argument("--max-no-improve", type=int, help="Override max no-improve rounds")
    parser.add_argument("--log-level", help="Override log level, e.g. INFO/DEBUG")
    return parser.parse_args()


def main() -> None:
    started_at = time.perf_counter()
    args = parse_args()
    config = load_config(Path(args.config_path))

    log_level = args.log_level or config.get("log_level", "INFO")
    log_file = setup_logging(str(log_level))
    logger = logging.getLogger(__name__)

    input_path = args.input_path or config.get("input_path", "private-draft.tex")
    output_path = args.output_path or config.get("output_path", "output.tex")
    max_iterations = args.max_iterations or int(config.get("max_iterations", 1))
    max_no_improve = args.max_no_improve or int(config.get("max_no_improve", 100))#这里需要修改，应该对应与每一个section的max_no_improve,而不是全局的

    test_file = Path(input_path)
    if not test_file.exists():
        raise FileNotFoundError(f"Test file not found: {test_file}")

    original_tex = test_file.read_text(encoding="utf-8")
    initial_state = GraphState(
        original_tex=original_tex,
        max_iterations=max_iterations,
        max_no_improve=max_no_improve,
    )
    logger.info(
        "run demo start: input=%s output=%s max_iterations=%s max_no_improve=%s log_file=%s",
        test_file,
        output_path,
        max_iterations,
        max_no_improve,
        log_file,
    )
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
    output_file = Path(output_path)
    output_tex = final_state.best_tex if final_state.best_tex else final_state.current_tex
    output_file.write_text(output_tex, encoding="utf-8")
    logger.info(
        "run complete: iterations=%s best_score=%.4f history_items=%s elapsed=%.2fs output_file=%s",
        final_state.iteration,
        final_state.best_score,
        len(final_state.history),
        time.perf_counter() - started_at,
        output_file.resolve(),
    )

    print(f"Saved output to: {output_file.resolve()}")
    print(f"Log file: {log_file.resolve()}")
    print()
    print("=== Output TeX Preview (first 1200 chars) ===")
    print(output_tex[:1200])


if __name__ == "__main__":
    main()
