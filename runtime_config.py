"""Default runtime settings and YAML merge helpers.

默认运行时配置与 YAML 合并工具。
All tunable values should live in ``config/*.yaml``; this module only holds
defaults and merge logic so imports stay stable without reading files.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

# 完整默认树；用户 YAML 在其上做深度合并。
# Full default tree; user YAML is deep-merged on top.
DEFAULT_CONFIG: dict[str, Any] = {
    "input_path": "sample_manuscript.tex",
    "output_path": "output.tex",
    # proofread = 最小改动订正；rewrite = 发展性重写 / minimal edits vs broader developmental polish (see README).
    "mode": "proofread",
    # 可选：按模式与角色覆盖内置 system 文案 / optional per-mode system overrides: modes.<proofread|rewrite>.<reviewer|editor|critic>
    "modes": {},
    "max_iterations": 1,
    "max_no_improve": 100,
    "log_level": "INFO",
    "log_dir": "logs",
    # run.py 启动前是否探测 Ollama /api/tags；非 Ollama 端点请设 false / probe Ollama before run; set false for other hosts.
    "ollama_healthcheck": True,
    # 为 true 且 mode 为 rewrite 时 run.py 会再跑一轮 proofread（额外费用）/ second proofread pass after rewrite (extra LLM cost).
    "post_proofread_after_rewrite": False,
    "post_proofread_max_iterations": 1,
    # 本地术语表：种子 + 首轮按节模型增量；见 glossary_merge 与 README / local glossary; see glossary_merge and README.
    "glossary": {
        "enabled": True,
        "seed_path": "private/glossary.seed.yaml",
        "merged_path": "private/glossary.merged.yaml",
        "bootstrap_provisional_from_merged": True,
        "persist_merged_after_merge": True,
    },
    "llm": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        # Ollama 原生路径：最大生成 token，长 JSON（如整节 LaTeX）易截断时可调大 / native Ollama: max output tokens; raise for long JSON.
        # 设为 null 则不在请求里传 num_predict（用模型默认）/ null omits num_predict (model default).
        "num_predict": 24576,
        # OllamaStructuredLLM：单次调用的 JSON 解析最大尝试次数（含首次）/ max JSON parse attempts per invoke (including first).
        "json_parse_retries": 3,
        # 不设 request_timeout 则沿用 LangChain/httpx 默认（不按秒硬断）/ omit for library default timeout.
        # 可在 config/local.yaml 的 llm 下写 request_timeout: 600 等正数启用 / set positive seconds in local.yaml to enable.
        "reviewer": {
            "model": "qwen2.5:14b",
            "temperature": 0.1,
        },
        "editor": {
            "model": "qwen2.5:14b",
            "temperature": 0.7,
            # 编辑返回整段 LaTeX JSON，默认可比全局多试几次 / editor returns full-body JSON; allow more parse retries than global.
            "json_parse_retries": 5,
        },
        "critic": {
            "model": "qwen2.5:14b",
            "temperature": 0.0,
        },
    },
}


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并字典；标量与列表以 override 为准。
    Deep-merge mappings; ``override`` wins for scalars and replaces lists."""
    out = deepcopy(base)
    for key, val in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = merge_config(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def load_merged_config(config_path: Path) -> dict[str, Any]:
    """读取 YAML 并与 DEFAULT_CONFIG 合并后返回。
    Load YAML from ``config_path`` and merge onto :data:`DEFAULT_CONFIG`."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        user = yaml.safe_load(f) or {}

    if not isinstance(user, dict):
        raise ValueError("Config file must contain a mapping at top level.")

    return merge_config(DEFAULT_CONFIG, user)
