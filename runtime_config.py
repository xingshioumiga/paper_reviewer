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
    "input_path": "private-draft.tex",
    "output_path": "output.tex",
    "max_iterations": 1,
    "max_no_improve": 100,
    "log_level": "INFO",
    "log_dir": "logs",
    # run.py 启动时是否请求 Ollama /api/tags；使用非 Ollama 的 OpenAI 兼容端点时改为 false。
    "ollama_healthcheck": True,
    "llm": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        # 不设 request_timeout 时与早期代码一致（由 LangChain / httpx 默认行为，等价于不按秒切断）。
        # 可选：在 config/local.yaml 的 llm 下写 request_timeout: 600 等正数才启用。
        "reviewer": {
            "model": "qwen2.5:14b",
            "temperature": 0.1,
        },
        "editor": {
            "model": "qwen2.5:14b",
            "temperature": 0.7,
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
