"""Lightweight Ollama reachability check (does not use LangChain).

在长时间 ``graph.invoke`` 前由 ``run.py`` 探测本机 ``ollama serve`` 是否可达 / used by ``run.py`` before long graph runs.
"""

from __future__ import annotations

from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


def check_ollama_tags(llm_cfg: dict[str, Any], timeout: float = 5.0) -> None:
    """GET ``{origin}/api/tags``；失败抛 ``RuntimeError`` / probe tags endpoint; raise ``RuntimeError`` on failure.

    ``llm.base_url`` 常为 ``http://host:11434/v1``；原生 API 在站点根路径 / ``llm.base_url`` is often ``.../v1``; native API lives at origin.
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
            f"无法连接 Ollama / cannot reach Ollama: {tags_url}（由 llm.base_url 推导 / derived from llm.base_url）。"
            f"请先运行 ``ollama serve`` 并确认端口 / ensure ``ollama serve`` and port. 原始错误 / original error: {e}"
        ) from e
