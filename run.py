"""CLI：加载 YAML、初始化 LLM、执行 ``LangGraph_loop_llm`` 并写出 TeX 与日志。

LLM pipeline entry: merge config, init clients, run graph, write output and section score summary.
"""

from __future__ import annotations

import argparse
import copy
import logging
import sys
import time
from pathlib import Path

from _version import __version__
from glossary_merge import load_initial_glossary_state
from langgraph_nodes import init_llms_from_config, section_score_summary
from langgraph_state import GraphState
from prompt_modes import normalize_edit_mode
from paper_reviewer_tool import assemble_output_tex
from runtime_config import load_merged_config
from utils.logging_setup import setup_logging
from utils.ollama_health import check_ollama_tags


# =========================
# 参数解析 / CLI argument parsing
# =========================
def parse_args() -> argparse.Namespace:
    """解析 CLI；优先级见 ``main`` 内说明 / parse CLI; precedence documented in ``main``."""
    parser = argparse.ArgumentParser(
        description="Run the LLM-powered paper reviewer pipeline."
    )

    parser.add_argument("--input", dest="input_path", help="Input TeX file path")
    parser.add_argument("--output", dest="output_path", help="Output TeX file path")

    parser.add_argument(
        "--config",
        dest="config_path",
        default="config/local.yaml",
        help="Config YAML path",
    )

    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--max-no-improve", type=int)
    parser.add_argument("--log-level", help="INFO / DEBUG / WARNING")

    parser.add_argument(
        "--mode",
        dest="mode_override",
        choices=["proofread", "rewrite"],
        default=None,
        help=(
            "Edit mode: proofread (minimal edits) or rewrite (developmental polish). "
            "Overrides config file."
        ),
    )

    parser.add_argument(
        "--post-proofread",
        action="store_true",
        help=(
            "After a rewrite pass, run a second graph pass in proofread mode "
            "(doubles LLM usage; see post_proofread_max_iterations in config)."
        ),
    )

    parser.add_argument(
        "--allow-llm-failures",
        action="store_true",
        help=(
            "Exit 0 even when LLM calls failed (default: exit 1 if any failed, "
            "so scripts do not treat the run as success)."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser.parse_args()


def _state_from_graph_result(result: GraphState | dict) -> GraphState:
    if isinstance(result, dict):
        return GraphState(**result)
    return result


# =========================
# 主函数 / main entry
# =========================
def main() -> None:
    """运行 LLM 流水线；日志末尾写入 ``section_score_summary`` / run LLM pipeline; log ``section_score_summary`` at end."""

    started_at = time.perf_counter()
    args = parse_args()
    config = load_merged_config(Path(args.config_path))
    if args.mode_override is not None:
        config["mode"] = args.mode_override
    else:
        config["mode"] = normalize_edit_mode(config.get("mode"))
    if args.post_proofread:
        config["post_proofread_after_rewrite"] = True

    primary_mode = str(config["mode"])

    # 先配日志再调 LLM，否则首次请求完成前可能没有文件日志 / configure logging before LLM so file logs exist early.
    log_level = args.log_level or config.get("log_level", "INFO")
    log_dir = str(config.get("log_dir", "logs"))
    log_file = setup_logging(str(log_level), log_dir=log_dir)
    logger = logging.getLogger(__name__)

    llm_cfg = config.get("llm", {})
    if config.get("ollama_healthcheck", True) and isinstance(llm_cfg, dict):
        check_ollama_tags(llm_cfg, timeout=5.0)
        logger.info("ollama health: GET /api/tags OK (base derived from llm.base_url)")

    init_llms_from_config(config)
    from LangGraph_loop_llm import graph

    # 优先级：CLI > config > 内置默认 / precedence: CLI > config > built-in defaults.
    input_path = args.input_path or config.get("input_path", "sample_manuscript.tex")
    output_path = args.output_path or config.get("output_path", "output.tex")

    max_iterations = args.max_iterations or int(config.get("max_iterations", 1))
    max_no_improve = args.max_no_improve or int(config.get("max_no_improve", 100))

    # ===== 读取输入 / read input TeX =====
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    original_tex = input_file.read_text(encoding="utf-8")

    gcfg = config.get("glossary") or {}
    gloss_enabled = bool(gcfg.get("enabled", False))
    gloss_locked: dict[str, str] = {}
    gloss_provisional: dict[str, str] = {}
    if gloss_enabled:
        seed_path = Path(str(gcfg.get("seed_path", "private/glossary.seed.yaml")))
        merged_path = Path(str(gcfg.get("merged_path", "private/glossary.merged.yaml")))
        bootstrap = bool(gcfg.get("bootstrap_provisional_from_merged", True))
        gloss_locked, gloss_provisional = load_initial_glossary_state(
            seed_path, merged_path, bootstrap
        )

    # ===== 初始化 state / build initial graph state =====
    initial_state = GraphState(
        original_tex=original_tex,
        max_iterations=max_iterations,
        max_no_improve=max_no_improve,
        edit_mode=primary_mode,
        glossary_enabled=gloss_enabled,
        glossary_locked=gloss_locked,
        glossary_provisional=gloss_provisional,
    )

    logger.info(
        "run start (LLM) v%s: mode=%s post_proofread=%s input=%s output=%s "
        "max_iterations=%s max_no_improve=%s log=%s",
        __version__,
        primary_mode,
        bool(config.get("post_proofread_after_rewrite")),
        input_file,
        output_path,
        max_iterations,
        max_no_improve,
        log_file,
    )

    # =========================
    # 执行 LangGraph（LLM）/ invoke LangGraph (LLM path)
    # =========================
    recursion_limit = 100
    result = graph.invoke(initial_state, {"recursion_limit": recursion_limit})
    first_final = _state_from_graph_result(result)
    final_state = first_final
    total_failures = final_state.llm_failure_count
    editor_skipped_all = list(final_state.editor_skipped_section_ids)

    do_second = bool(config.get("post_proofread_after_rewrite")) and primary_mode == "rewrite"
    if do_second:
        assembled = assemble_output_tex(
            first_final.document_prefix,
            first_final.best_tex,
            first_final.current_tex,
            first_final.sections,
        )
        logger.info(
            "post-proofread: starting second pass (proofread), max_iterations=%s",
            int(config.get("post_proofread_max_iterations", 1)),
        )
        config2 = copy.deepcopy(config)
        config2["mode"] = "proofread"
        config2["post_proofread_after_rewrite"] = False
        init_llms_from_config(config2)
        state2 = GraphState(
            original_tex=assembled,
            max_iterations=int(config.get("post_proofread_max_iterations", 1)),
            max_no_improve=max_no_improve,
            edit_mode="proofread",
            glossary_enabled=first_final.glossary_enabled,
            glossary_locked=dict(first_final.glossary_locked),
            glossary_provisional=dict(first_final.glossary_provisional),
            glossary_extracted_section_ids=[],
        )
        result2 = graph.invoke(state2, {"recursion_limit": recursion_limit})
        final_state = _state_from_graph_result(result2)
        total_failures = first_final.llm_failure_count + final_state.llm_failure_count
        editor_skipped_all = sorted(
            set(first_final.editor_skipped_section_ids) | set(final_state.editor_skipped_section_ids)
        )

    # =========================
    # 输出统计 / run summary to console
    # =========================
    section_scores = section_score_summary(final_state)

    print("=== LLM Pipeline Finished ===")
    print(f"Iterations: {final_state.iteration}")
    print(f"History items: {len(final_state.history)}")
    print("Section scores (section_id, latest accepted score):")
    for sid, sc in section_scores:
        print(f"  {sid}: {sc:.4f}")
    print()

    # =========================
    # 保存结果 TeX / write output TeX
    # =========================
    output_file = Path(output_path)

    output_tex = assemble_output_tex(
        final_state.document_prefix,
        final_state.best_tex,
        final_state.current_tex,
        final_state.sections,
    )

    output_file.write_text(output_tex, encoding="utf-8")

    logger.info(
        "run complete: iterations=%s history=%s elapsed=%.2fs output=%s llm_failures=%s editor_skipped_sections=%s",
        final_state.iteration,
        len(final_state.history),
        time.perf_counter() - started_at,
        output_file.resolve(),
        total_failures,
        editor_skipped_all,
    )

    print(f"Saved output to: {output_file.resolve()}")
    print(f"Log file: {log_file.resolve()}")
    print()

    if editor_skipped_all:
        skip_msg = f"SECTIONS_SKIPPED_BY_EDITOR: {editor_skipped_all}"
        logger.warning(skip_msg)
        print(skip_msg)
        print()

    print("=== Output TeX Preview (first 1200 chars) ===")
    print(output_tex[:1200])

    logger.info(
        "final section_score_summary (section_id, score): %s",
        section_scores,
    )

    if total_failures > 0:
        msg = (
            f"DEGRADED: {total_failures} LLM call(s) failed during this run; "
            "output may be incomplete or unscored. See log for ERROR lines."
        )
        logger.error(msg)
        print(msg, file=sys.stderr)
        if not args.allow_llm_failures:
            sys.exit(1)


# =========================
# 入口 / script entry
# =========================
if __name__ == "__main__":
    main()
