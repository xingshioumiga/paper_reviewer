"""Lightweight Ollama reachability check (does not use LangChain).

用于 run.py 在长时间 graph.invoke 之前确认本机 ``ollama serve`` 可访问。
"""

from __future__ import annotations

from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


def check_ollama_tags(llm_cfg: dict[str, Any], timeout: float = 5.0) -> None:
    """GET ``{origin}/api/tags``；失败时抛出带说明的 RuntimeError。

    ``llm.base_url`` 通常为 ``http://host:11434/v1``；Ollama 原生 API 在根路径下。
    """
    base = str(llm_cfg.get("base_url", "http://localhost:11434/v1"))
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid llm.base_url: {base!r}")

    origin = f"{parsed.scheme}://{parsed.netloc}"
    tags_url = f"{origin}/api/tags"

    try:
        with urlopen(tags_url, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"Ollama {tags_url} returned HTTP {resp.status}")
    except URLError as e:
        raise RuntimeError(
            f"无法连接 Ollama：{tags_url}（由 config 中 llm.base_url 推导）。"
            f"请先在本机执行 ``ollama serve`` 并确认端口。原始错误: {e}"
        ) from e
