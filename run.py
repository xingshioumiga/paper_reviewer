"""CLI：加载 YAML、初始化 LLM、执行 ``LangGraph_loop_llm`` 并写出 TeX 与日志。

LLM pipeline entry: merge config, init clients, run graph, write output and section score summary.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from _version import __version__
from langgraph_nodes import init_llms_from_config, section_score_summary
from langgraph_state import GraphState
from runtime_config import load_merged_config
from utils.logging_setup import setup_logging
from utils.ollama_health import check_ollama_tags


# =========================
# 参数解析
# =========================
def parse_args() -> argparse.Namespace:
    """解析 CLI；优先级见 main 内「CLI > config > default」。
    Parse CLI; precedence is documented in ``main``."""
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


# =========================
# 主函数
# =========================
def main() -> None:
    """运行完整 LLM 流水线并在日志末尾写入 ``section_score_summary``。
    Run full LLM pipeline; append ``section_score_summary`` as the final log line."""

    started_at = time.perf_counter()
    args = parse_args()
    config = load_merged_config(Path(args.config_path))

    # 先配置日志，再初始化 LLM / 跑图，否则 httpx 等库在首次请求完成前可能没有任何文件记录。
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

    # ===== 参数优先级：CLI > config > default =====
    input_path = args.input_path or config.get("input_path", "private-draft.tex")
    output_path = args.output_path or config.get("output_path", "output.tex")

    max_iterations = args.max_iterations or int(config.get("max_iterations", 1))
    max_no_improve = args.max_no_improve or int(config.get("max_no_improve", 100))

    # ===== 读取输入 =====
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    original_tex = input_file.read_text(encoding="utf-8")

    # ===== 初始化 state =====
    initial_state = GraphState(
        original_tex=original_tex,
        max_iterations=max_iterations,
        max_no_improve=max_no_improve,
    )

    logger.info(
        "run start (LLM) v%s: input=%s output=%s max_iterations=%s max_no_improve=%s log=%s",
        __version__,
        input_file,
        output_path,
        max_iterations,
        max_no_improve,
        log_file,
    )

    # =========================
    # 执行 LangGraph（LLM）
    # =========================
    # 计算 recursion_limit: 8 段 x 每段约 5 步 + 余量 = 100
    result = graph.invoke(initial_state, {"recursion_limit": 100})

    # ===== 兼容 dict / model =====
    if isinstance(result, dict):
        final_state = GraphState(**result)
    else:
        final_state = result

    # =========================
    # 📊 输出统计
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
    # 💾 保存结果
    # =========================
    output_file = Path(output_path)

    output_tex = (
        final_state.best_tex
        if final_state.best_tex
        else final_state.current_tex
    )

    output_file.write_text(output_tex, encoding="utf-8")

    logger.info(
        "run complete: iterations=%s history=%s elapsed=%.2fs output=%s",
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

    failures = final_state.llm_failure_count
    if failures > 0:
        msg = (
            f"DEGRADED: {failures} LLM call(s) failed during this run; "
            "output may be incomplete or unscored. See log for ERROR lines."
        )
        logger.error(msg)
        print(msg, file=sys.stderr)
        if not args.allow_llm_failures:
            sys.exit(1)


# =========================
# 入口
# =========================
if __name__ == "__main__":
    main()
