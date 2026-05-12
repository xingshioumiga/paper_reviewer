"""CLI：Mock 图入口（无需 Ollama），用于本地快速验证状态机与配置加载。

Mock-graph CLI for fast routing/state checks without a live LLM.
"""

import argparse
import logging
import time
from pathlib import Path

from LangGraph_loop import graph
from langgraph_nodes import section_score_summary
from langgraph_state import GraphState
from paper_reviewer_tool import assemble_output_tex
from prompt_modes import normalize_edit_mode
from runtime_config import load_merged_config
from utils.logging_setup import setup_logging


def parse_args() -> argparse.Namespace:
    """解析参数；可与 ``config/local.yaml`` 叠加使用。"""
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
    parser.add_argument(
        "--mode",
        dest="mode_override",
        choices=["proofread", "rewrite"],
        default=None,
        help="Edit mode (stored on state for consistency; mock graph ignores prompts).",
    )
    return parser.parse_args()


def main() -> None:
    """调用 mock 图并写 TeX；控制台与日志末尾输出 ``section_score_summary``。
    Run mock graph, write TeX; print and log ``section_score_summary`` at the end."""
    started_at = time.perf_counter()
    args = parse_args()
    config = load_merged_config(Path(args.config_path))
    if args.mode_override is not None:
        config["mode"] = args.mode_override
    else:
        config["mode"] = normalize_edit_mode(config.get("mode"))

    log_level = args.log_level or config.get("log_level", "INFO")
    log_dir = str(config.get("log_dir", "logs"))
    log_file = setup_logging(str(log_level), log_dir=log_dir)
    logger = logging.getLogger(__name__)

    input_path = args.input_path or config.get("input_path", "private-draft.tex")
    output_path = args.output_path or config.get("output_path", "output.tex")
    max_iterations = args.max_iterations or int(config.get("max_iterations", 1))
    max_no_improve = args.max_no_improve or int(config.get("max_no_improve", 100))

    test_file = Path(input_path)
    if not test_file.exists():
        raise FileNotFoundError(f"Test file not found: {test_file}")

    original_tex = test_file.read_text(encoding="utf-8")
    initial_state = GraphState(
        original_tex=original_tex,
        max_iterations=max_iterations,
        max_no_improve=max_no_improve,
        edit_mode=str(config["mode"]),
    )
    logger.info(
        "run demo start: mode=%s input=%s output=%s max_iterations=%s max_no_improve=%s log_file=%s",
        config["mode"],
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

    section_scores = section_score_summary(final_state)

    print("=== Demo Finished ===")
    print(f"Iterations: {final_state.iteration}")
    print(f"History items: {len(final_state.history)}")
    print("Section scores (section_id, latest accepted score):")
    for sid, sc in section_scores:
        print(f"  {sid}: {sc:.4f}")
    print()
    output_file = Path(output_path)
    output_tex = assemble_output_tex(
        final_state.document_prefix,
        final_state.best_tex,
        final_state.current_tex,
        final_state.sections,
    )
    output_file.write_text(output_tex, encoding="utf-8")
    logger.info(
        "run complete: iterations=%s history_items=%s elapsed=%.2fs output_file=%s",
        final_state.iteration,
        len(final_state.history),
        time.perf_counter() - started_at,
        output_file.resolve(),
    )

    print(f"Saved output to: {output_file.resolve()}")
    print(f"Log file: {log_file.resolve()}")
    print()
    print("=== Output TeX Preview (first 1200 chars) ===")
    print(output_tex[:1200])

    logger.info(
        "final section_score_summary (section_id, score): %s",
        section_scores,
    )


if __name__ == "__main__":
    main()
