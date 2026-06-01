"""LangGraph node functions: init → glossary → reviewer → editor → critic → aggregator → routing.

节点流水线：初始化 → 术语表（可选）→ 审稿 → 改写 → 打分 → 汇总采纳/回滚 → 切换段落或外层轮次。
Mock 节点用于快速验证；`*_llm` 节点通过 ``init_llms_from_config`` 使用配置文件中的 LLM。
"""

import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Type, TypeVar

from glossary_merge import merge_glossary_candidates, render_glossary_block, save_merged_yaml
from langgraph_state import GraphState, HistoryItem, Issue
from paper_reviewer_tool import (
    normalize_fake_newlines_in_latex,
    render_sections,
    split_prefix_and_sections,
    strip_leading_section_command,
)
# 保留：langchain StrOutputParser 示例（当前未使用）/ reserved: StrOutputParser example (unused).
# from langchain_core.output_parsers import StrOutputParser

from langchain_openai import ChatOpenAI
try:
    from langchain_ollama import OllamaLLM
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from runtime_config import DEFAULT_CONFIG, merge_config
from prompt_modes import build_prompt_bundle, normalize_edit_mode

T = TypeVar("T", bound=BaseModel)

_PROMPT_BUNDLE: dict[str, dict[str, str]] | None = None


def refresh_prompt_bundle(merged_config: dict[str, Any]) -> None:
    """从合并后的 YAML 重建全局提示表（在每次 ``init_llms_from_config`` 后调用）/ rebuild global prompts from merged YAML."""
    global _PROMPT_BUNDLE
    _PROMPT_BUNDLE = build_prompt_bundle(merged_config)


def system_prompt_for(role: str, mode: str) -> str:
    """返回 reviewer|editor|critic 在当前 ``mode`` 下的 system 文案 / return system prompt for role and edit ``mode``."""
    if role not in ("reviewer", "editor", "critic"):
        raise ValueError(f"invalid role: {role}")
    bundle = _PROMPT_BUNDLE if _PROMPT_BUNDLE is not None else build_prompt_bundle({})
    m = normalize_edit_mode(mode)
    per_mode = bundle.get(m) or bundle["proofread"]
    return per_mode[role]


def _escape_langchain_template_literals(s: str) -> str:
    """``ChatPromptTemplate`` 将 ``{...}`` 当变量；system 中的 JSON 示例需双写花括号 / double braces for JSON literals in templates."""
    return s.replace("{", "{{").replace("}", "}}")


def _pydantic_validate_json(schema: type[T], raw: str) -> T:
    """解析 JSON 字符串为 Pydantic（v1 ``parse_raw`` 或 v2 ``model_validate_json``）/ parse JSON string into a Pydantic model."""
    validate = getattr(schema, "model_validate_json", None)
    if callable(validate):
        return validate(raw)
    return schema.parse_raw(raw)  # type: ignore[call-arg]  # 旧版 Pydantic parse_raw / legacy Pydantic parse_raw.


def _balanced_json_object(text: str, start_idx: int) -> str | None:
    """自 ``start_idx`` 的 ``{`` 起截取平衡 ``{...}``，字符串内近似 JSON 引号规则 / balanced ``{...}`` from ``start_idx`` with string-aware rules."""
    if start_idx >= len(text) or text[start_idx] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for j in range(start_idx, len(text)):
        c = text[j]
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : j + 1]
    return None


def _iter_json_object_candidates(content: str, max_starts: int = 32) -> list[str]:
    """从左到右枚举候选顶层 JSON 子串（模型夹杂说明或残缺 JSON 时）/ enumerate candidate top-level JSON substrings."""
    candidates: list[str] = []
    start_search = 0
    seen: set[str] = set()
    while len(candidates) < max_starts:
        i = content.find("{", start_search)
        if i < 0:
            break
        chunk = _balanced_json_object(content, i)
        if chunk and chunk not in seen:
            seen.add(chunk)
            candidates.append(chunk)
        start_search = i + 1
    return candidates


# 可选的流式调试：设置环境变量 DEBUG_LLM_STREAM=1 可在终端实时看到原始 token（用于确认 LLM 正在响应）。
# Optional streaming debug: set env DEBUG_LLM_STREAM=1 to see raw tokens in terminal (confirms LLM is responding).
class _DebugStreamingHandler(BaseCallbackHandler):
    """将 LLM token 实时写到 stderr，不干扰结构化输出 / stream tokens to stderr without breaking structured I/O."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # 打到 stderr，避免污染 stdout 与下游解析 / print to stderr to avoid breaking stdout / parsers.
        sys.stderr.write(f"{self.prefix}{token}")
        sys.stderr.flush()

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        sys.stderr.write(f"\n[stream error: {error}]\n")
        sys.stderr.flush()


def _maybe_streaming_callbacks(role: str) -> list[BaseCallbackHandler] | None:
    """若 ``DEBUG_LLM_STREAM=1`` 则返回流式回调，否则 ``None`` / streaming callbacks when env flag set."""
    if os.getenv("DEBUG_LLM_STREAM", "").strip() in ("1", "true", "yes"):
        return [_DebugStreamingHandler(prefix=f"[{role}] ")]
    return None


# Ollama JSON 重试附言：审稿/评分用 / generic JSON retry hint for reviewer and critic.
_DEFAULT_OLLAMA_JSON_RETRY_HINT = (
    "上一版输出无法解析为合法 JSON。"
    "规则：字符串内的反斜杠必须写成 \\\\；字符串内不要出现未转义的双引号；"
    "problem 每条不超过 120 个中文字符，少用 LaTeX 命令字面量，改用文字描述（如「section 标题」）。"
    "请只输出一整段合法 UTF-8 JSON，不要用 Markdown 围栏，不要用「…」截断。"
)

# 编辑链专用：整段 LaTeX 嵌入 ``refined_latex`` 时易超长或破坏 JSON / editor-specific hint for embedded LaTeX JSON.
_EDITOR_OLLAMA_JSON_RETRY_HINT = (
    "上一版输出无法解析为合法 JSON。"
    "你必须只输出一个 JSON 对象，且仅含键 refined_latex。"
    "refined_latex 的值是一个 JSON 字符串：内部双引号必须写成 \\\"；反斜杠必须写成 \\\\。"
    "不要在 JSON 字符串未闭合时结束输出；不要用「…」或省略号代替正文。"
    "若段落很长，优先做最小必要修改以缩短输出 token，但仍须输出完整合法 JSON（字符串必须正确闭合）。"
    "不要使用 Markdown 代码围栏；不要输出 JSON 以外的任何文字。"
)

_NUM_PREDICT_UNSET = object()


def _is_retryable_ollama_transport(exc: BaseException) -> bool:
    """长流式 generate 时 Ollama/httpx 可能断连或短暂 502；可重试 / transient Ollama or proxy errors worth retrying."""
    name = type(exc).__name__
    mod = getattr(type(exc), "__module__", "") or ""
    if "RemoteProtocolError" in name or "ReadTimeout" in name or "ConnectError" in name:
        return True
    if mod.startswith("httpx.") or mod.startswith("httpcore."):
        if "Timeout" in name or "Protocol" in name or "Connect" in name:
            return True
    code = getattr(exc, "status_code", None)
    if isinstance(code, int) and code in (502, 503, 504):
        return True
    return False


# =========================
# Ollama 原生 API 封装（如禁用 thinking）/ Ollama native API wrapper (e.g. disable thinking)
# =========================
class OllamaStructuredLLM:
    """包装 Ollama 原生客户端：结构化 JSON，并可禁用 thinking / wrap native Ollama for structured JSON and optional no-thinking.

    适用于 Qwen3.5 等默认开启 thinking 的模型；通过 ``reasoning`` 等关闭 / for models with default “thinking”; disable via ``reasoning`` etc.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        disable_thinking: bool = True,
        role: str = "",
        timeout: float | None = None,
        num_predict: int | None | object = _NUM_PREDICT_UNSET,
    ) -> None:
        if not _OLLAMA_AVAILABLE:
            raise ImportError(
                "langchain-ollama is required for Ollama native backend. "
                "Install: pip install langchain-ollama"
            )
        # 去掉 /v1 后缀；原生 API 走根路径 / strip ``/v1``; native API uses origin root.
        base_url_clean = base_url.replace("/v1", "").rstrip("/")
        self.model = model
        self.role = role
        self.disable_thinking = disable_thinking

        # Ollama / langchain-ollama 选项：用 reasoning 控制思考，而非 think / use ``reasoning`` (not ``think``) for thinking mode.
        # reasoning=False 关闭 thinking；None 表示模型默认 / ``False`` disables thinking; ``None`` uses model default.
        reasoning = False if disable_thinking else None

        llm_kw: dict[str, Any] = {
            "model": model,
            "base_url": base_url_clean,
            "temperature": temperature,
            "reasoning": reasoning,
        }
        if num_predict is _NUM_PREDICT_UNSET:
            resolved_np: int | None = int(DEFAULT_CONFIG["llm"].get("num_predict", 24576))
        elif num_predict is None:
            resolved_np = None
        else:
            resolved_np = int(num_predict)  # type: ignore[arg-type]
        if resolved_np is not None:
            llm_kw["num_predict"] = resolved_np
        self.llm = OllamaLLM(**llm_kw)
        logger.debug(
            "Ollama native client created: model=%s, reasoning=%s, num_predict=%s",
            model,
            reasoning,
            resolved_np,
        )

    def invoke(
        self,
        messages: list,
        output_schema: type[T],
        *,
        retry_hint: str | None = None,
        max_parse_attempts: int = 3,
    ) -> T:
        """调用 Ollama 并解析结构化输出；失败则有限次重试 / invoke Ollama; parse structured output with bounded retries."""
        hint = retry_hint if retry_hint is not None else _DEFAULT_OLLAMA_JSON_RETRY_HINT
        msgs: list[Any] = list(messages)
        last_err: BaseException | None = None
        transport_attempts_max = 3
        for attempt in range(max_parse_attempts):
            response: str | None = None
            last_transport: BaseException | None = None
            for tr in range(transport_attempts_max):
                try:
                    response = self.llm.invoke(msgs)
                    last_transport = None
                    break
                except BaseException as e:
                    last_transport = e
                    if tr + 1 < transport_attempts_max and _is_retryable_ollama_transport(e):
                        logging.getLogger(__name__).warning(
                            "OllamaStructuredLLM transport retry %s/%s role=%s: %s",
                            tr + 1,
                            transport_attempts_max,
                            self.role,
                            e,
                        )
                        time.sleep(min(10.0, 2.0 ** tr))
                        continue
                    raise
            assert response is not None
            try:
                return self._parse_response(response, output_schema)
            except ValueError as e:
                last_err = e
                logging.getLogger(__name__).warning(
                    "OllamaStructuredLLM JSON parse failed attempt %s/%s role=%s: %s",
                    attempt + 1,
                    max_parse_attempts,
                    self.role,
                    e,
                )
                msgs = list(messages) + [HumanMessage(content=hint)]
        assert last_err is not None
        raise last_err

    def _parse_response(self, content: str, schema: type[T]) -> T:
        """从响应文本提取 JSON 并校验为 ``schema`` / extract JSON from response text and validate as ``schema``."""
        stripped = content.strip()

        # 先试整段为纯 JSON / try whole response as raw JSON first.
        try:
            return _pydantic_validate_json(schema, stripped)
        except Exception:
            pass

        # 再试 Markdown 围栏内的 JSON / then fenced ```json``` blocks.
        json_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)```', content)
        for block in json_blocks:
            try:
                return _pydantic_validate_json(schema, block.strip())
            except Exception:
                continue

        # 平衡括号枚举多个 JSON 对象候选，避免贪婪匹配错位 / balanced-brace candidates to avoid greedy mismatch.
        for chunk in _iter_json_object_candidates(content):
            try:
                return _pydantic_validate_json(schema, chunk)
            except Exception:
                continue

        raise ValueError(f"No valid JSON found in response: {content[:500]}...")


# LLM 结构化输出用的 Pydantic 容器 / Pydantic containers for structured LLM outputs.
class ReviewOutput(BaseModel):
    issues: List[Issue] = Field(description="段落中发现的问题列表")


# 编辑器一次性返回 refined_latex / editor returns ``refined_latex`` in one JSON object.
class EditorOutput(BaseModel):
    refined_latex: str = Field(
        description="完全优化后的 LaTeX 段落内容。要求：严禁包含任何 Markdown 标签、解释文字或开场白。"
    )


# Critic 一次性返回 score / critic returns scalar ``score``.
class ScoreOutput(BaseModel):
    score: float = Field(description="0到1之间的浮点数评分，0.9表示完美，0.5表示无改进")


# Glossary chunk extract / 术语表增量抽取.
class GlossaryExtractEntry(BaseModel):
    abbr: str = Field(description="缩写或简短记号，如 EV、HHG / short token such as EV, HHG")
    expansion: str = Field(description="英文全称或简短释义，≤200 字符 / English gloss, under ~200 chars")
    confidence: float = Field(default=0.6, ge=0.0, le=1.0, description="置信度 0–1 / confidence 0–1")


class GlossaryExtractOutput(BaseModel):
    entries: List[GlossaryExtractEntry] = Field(
        default_factory=list,
        description='JSON 键 entries：对象数组，每项含 abbr、expansion、confidence / key "entries": array of objects',
    )


GLOSSARY_SYSTEM = """你是学术 LaTeX 稿件的术语抽取助手。任务：从给定的一个章节片段中，抽取重要的缩写与领域专有名词及其英文释义。
规则：
- 只输出一个 JSON 对象，且仅含键 "entries"；entries 为数组，元素含 abbr、expansion、confidence（0 到 1）。
- abbr 为短记号（如 EV、HHG），不要整句；expansion 为英文释义，单条不超过 200 字符。
- 人类消息中「locked」术语不得给出与之矛盾的 expansion；若该缩写已在 locked 中，不要重复输出。
- 不要臆造文中未出现的含义；不确定则 confidence 放低或省略该项。
- 若无新术语可补充，返回 {"entries": []}。
- 不要 Markdown 代码围栏；不要输出 JSON 以外的文字。"""

_DEFAULT_GLOSSARY_JSON_RETRY_HINT = (
    "上一版输出无法解析为合法 JSON。"
    "请只输出一个 JSON 对象，键为 entries，值为数组；每项含 abbr、expansion、confidence。"
    "字符串内双引号必须转义为 \\\"；不要用 Markdown 围栏。"
)


# =========================
# Ollama 原生 Runnable 链（置于 Output 类之后避免前向引用）/ native Runnable chains after Output classes
# =========================
from langchain_core.runnables import Runnable


class OllamaReviewerChain(Runnable):
    """Ollama 审稿 Runnable；返回 ``ReviewOutput`` / Ollama reviewer runnable returning ``ReviewOutput``."""

    def __init__(
        self,
        llm: OllamaStructuredLLM,
        system_prompt: str,
        max_parse_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_parse_attempts = max(1, int(max_parse_attempts))

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> ReviewOutput:
        # ChatPromptValue：来自 ``prompt | chain`` / handle ``ChatPromptValue`` from ``prompt | chain``.
        if hasattr(inputs, "to_messages"):
            # 直接使用其消息并加 system / reuse messages and prepend system.
            messages = [SystemMessage(content=self.system_prompt)] + list(inputs.to_messages())
        else:
            # 普通 dict 输入路径 / plain dict input path.
            title = inputs.get("title", "")
            content = inputs.get("content", "")
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=f"标题: {title}\n\n内容:\n{content}"),
            ]
        return self.llm.invoke(messages, ReviewOutput, max_parse_attempts=self.max_parse_attempts)


class OllamaEditorChain(Runnable):
    """Ollama 编辑 Runnable；返回 ``EditorOutput`` / Ollama editor runnable returning ``EditorOutput``."""

    def __init__(
        self,
        llm: OllamaStructuredLLM,
        system_prompt: str,
        max_parse_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_parse_attempts = max(1, int(max_parse_attempts))

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> EditorOutput:
        # ChatPromptValue：来自 ``prompt | chain`` / handle ``ChatPromptValue`` from ``prompt | chain``.
        if hasattr(inputs, "to_messages"):
            messages = [SystemMessage(content=self.system_prompt)] + list(inputs.to_messages())
        else:
            title = inputs.get("title", "")
            content = inputs.get("content", "")
            issues = inputs.get("issues", [])
            issues_text = "\n".join([f"- {i.problem} (严重性: {i.severity})" for i in issues])
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(
                    content=f"标题: {title}\n\n当前段落内容:\n{content}\n\n需要修复的问题:\n{issues_text}\n\n请提供优化后的 LaTeX 段落。"
                ),
            ]
        return self.llm.invoke(
            messages,
            EditorOutput,
            retry_hint=_EDITOR_OLLAMA_JSON_RETRY_HINT,
            max_parse_attempts=self.max_parse_attempts,
        )


class OllamaCriticChain(Runnable):
    """Ollama 评分 Runnable；返回 ``ScoreOutput`` / Ollama critic runnable returning ``ScoreOutput``."""

    def __init__(
        self,
        llm: OllamaStructuredLLM,
        system_prompt: str,
        max_parse_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_parse_attempts = max(1, int(max_parse_attempts))

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> ScoreOutput:
        # ChatPromptValue：来自 ``prompt | chain`` / handle ``ChatPromptValue`` from ``prompt | chain``.
        if hasattr(inputs, "to_messages"):
            messages = [SystemMessage(content=self.system_prompt)] + list(inputs.to_messages())
        else:
            before = inputs.get("before", "")
            after = inputs.get("after", "")
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=f"修改前: {before}\n\n修改后: {after}"),
            ]
        return self.llm.invoke(messages, ScoreOutput, max_parse_attempts=self.max_parse_attempts)


class OllamaGlossaryChain(Runnable):
    """Ollama 术语抽取 Runnable；返回 ``GlossaryExtractOutput`` / Ollama glossary extraction runnable."""

    def __init__(
        self,
        llm: OllamaStructuredLLM,
        system_prompt: str,
        max_parse_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.max_parse_attempts = max(1, int(max_parse_attempts))

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> GlossaryExtractOutput:
        title = str(inputs.get("title", ""))
        content = str(inputs.get("content", ""))
        existing = str(inputs.get("existing_glossary", "(none)"))
        human = (
            "Current merged glossary (respect locked; do not propose conflicting expansions for locked keys):\n"
            f"{existing}\n\nSection title:\n{title}\n\nLaTeX section body:\n{content}\n\n"
            'Return only JSON: {{"entries": [...]}}.'
        )
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=human),
        ]
        return self.llm.invoke(
            messages,
            GlossaryExtractOutput,
            retry_hint=_DEFAULT_GLOSSARY_JSON_RETRY_HINT,
            max_parse_attempts=self.max_parse_attempts,
        )


# 运行期由 init_llms_from_config 填充；import 时用 DEFAULT_CONFIG 预初始化一次。
# Filled by init_llms_from_config; seeded once at import from DEFAULT_CONFIG.
llm_ini_reviewer: ChatOpenAI
llm_ini_editor: ChatOpenAI
llm_ini_critic: ChatOpenAI
llm_ini_glossary: ChatOpenAI | None = None
llm_structured_reviewer: Any
llm_strucured_editor: Any
llm_structured_critic: Any
llm_structured_glossary: Any = None

# merged 术语表落盘路径（由 init_llms_from_config 根据 YAML 写入）/ merged glossary persist paths from YAML.
_GLOSSARY_PERSIST: dict[str, Any] = {
    "merged_path": "private/glossary.merged.yaml",
    "persist": False,
}


def _resolved_num_predict(llm_cfg: dict[str, Any], role: dict[str, Any]) -> int | None:
    """角色可覆盖 ``num_predict``；``null`` 表示不传 Ollama（模型默认）/ per-role override; ``null`` omits for Ollama default."""
    if "num_predict" in role:
        v = role.get("num_predict")
        return None if v is None else int(v)
    v = llm_cfg.get("num_predict", DEFAULT_CONFIG["llm"].get("num_predict", 24576))
    if v is None:
        return None
    return int(v)


def _resolved_json_parse_attempts(llm_cfg: dict[str, Any], role: dict[str, Any], fallback: int) -> int:
    """``json_parse_retries``：角色优先，其次 ``llm`` 顶层，最后 ``fallback`` / role wins, then top-level ``llm``, then fallback."""
    v = role.get("json_parse_retries")
    if v is not None:
        return max(1, int(v))
    v = llm_cfg.get("json_parse_retries")
    if v is not None:
        return max(1, int(v))
    return max(1, int(fallback))


def init_llms_from_config(config: dict[str, Any] | None = None) -> None:
    """根据合并后的配置重建三个 ChatOpenAI 客户端及结构化链（应在 run.py 中再次调用以覆盖 YAML）。
    Rebuild reviewer/editor/critic clients and structured chains from merged config."""
    global llm_ini_reviewer, llm_ini_editor, llm_ini_critic, llm_ini_glossary
    global llm_structured_reviewer, llm_strucured_editor, llm_structured_critic, llm_structured_glossary
    global _GLOSSARY_PERSIST

    merged = merge_config(DEFAULT_CONFIG, config or {})
    # 规范化编辑模式并刷新全局提示表 / canonicalize mode and refresh global prompt table.
    mode_resolved = normalize_edit_mode(merged.get("mode"))
    merged["mode"] = mode_resolved
    refresh_prompt_bundle(merged)

    llm_cfg = merged.get("llm", {})
    base_url = str(llm_cfg.get("base_url", "http://localhost:11434/v1"))
    api_key = str(llm_cfg.get("api_key", "ollama"))

    def _role(name: str) -> dict[str, Any]:
        block = llm_cfg.get(name)
        return block if isinstance(block, dict) else {}

    rv = _role("reviewer")
    ed = _role("editor")
    cr = _role("critic")
    gloss_raw = llm_cfg.get("glossary")
    gloss_d = gloss_raw if isinstance(gloss_raw, dict) else {}
    gloss_model = str(gloss_d.get("model") or rv.get("model", "qwen2.5:14b"))
    gloss_temp = float(gloss_d.get("temperature", 0.0))

    timeout_raw = llm_cfg.get("request_timeout")
    request_timeout: float | None = None
    if timeout_raw is not None:
        try:
            t = float(timeout_raw)
            if t > 0:
                request_timeout = t
        except (TypeError, ValueError):
            pass

    # 后端：openai_compatible（默认）或 ollama_native / backend selection.
    backend = str(llm_cfg.get("backend", "openai_compatible")).lower()
    use_ollama_native = backend == "ollama_native"

    if use_ollama_native:
        # Ollama 原生路径（reasoning 等）/ Ollama native path (reasoning options).
        if not _OLLAMA_AVAILABLE:
            raise ImportError(
                "backend='ollama_native' requires langchain-ollama. "
                "Install: pip install langchain-ollama"
            )
        np_rv = _resolved_num_predict(llm_cfg, rv)
        np_ed = _resolved_num_predict(llm_cfg, ed)
        np_cr = _resolved_num_predict(llm_cfg, cr)
        attempts_rv = _resolved_json_parse_attempts(
            llm_cfg,
            rv,
            int(DEFAULT_CONFIG["llm"].get("json_parse_retries", 3)),
        )
        attempts_ed = _resolved_json_parse_attempts(
            llm_cfg,
            ed,
            int(DEFAULT_CONFIG["llm"].get("editor", {}).get("json_parse_retries", 5)),
        )
        attempts_cr = _resolved_json_parse_attempts(
            llm_cfg,
            cr,
            int(DEFAULT_CONFIG["llm"].get("json_parse_retries", 3)),
        )

        logger.info(
            "Using Ollama native backend (think=false) for models: "
            "reviewer=%s, editor=%s, critic=%s num_predict=(%s,%s,%s) json_parse_attempts=(%s,%s,%s)",
            rv.get("model", "qwen2.5:14b"),
            ed.get("model", "qwen2.5:14b"),
            cr.get("model", "qwen2.5:14b"),
            np_rv,
            np_ed,
            np_cr,
            attempts_rv,
            attempts_ed,
            attempts_cr,
        )

        ollama_reviewer = OllamaStructuredLLM(
            model=str(rv.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(rv.get("temperature", 0.1)),
            disable_thinking=True,
            role="reviewer",
            num_predict=np_rv,
        )
        ollama_editor = OllamaStructuredLLM(
            model=str(ed.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(ed.get("temperature", 0.7)),
            disable_thinking=True,
            role="editor",
            num_predict=np_ed,
        )
        ollama_critic = OllamaStructuredLLM(
            model=str(cr.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(cr.get("temperature", 0.0)),
            disable_thinking=True,
            role="critic",
            num_predict=np_cr,
        )

        # Runnable 包装原生客户端；system 与当前 mode 一致 / Runnable wrappers; system prompt matches resolved mode.
        llm_structured_reviewer = OllamaReviewerChain(
            ollama_reviewer,
            system_prompt_for("reviewer", mode_resolved),
            max_parse_attempts=attempts_rv,
        )
        llm_strucured_editor = OllamaEditorChain(
            ollama_editor,
            system_prompt_for("editor", mode_resolved),
            max_parse_attempts=attempts_ed,
        )
        llm_structured_critic = OllamaCriticChain(
            ollama_critic,
            system_prompt_for("critic", mode_resolved),
            max_parse_attempts=attempts_cr,
        )

        np_gl = _resolved_num_predict(llm_cfg, gloss_d)
        attempts_gl = _resolved_json_parse_attempts(
            llm_cfg,
            gloss_d,
            int(DEFAULT_CONFIG["llm"].get("json_parse_retries", 3)),
        )
        ollama_glossary = OllamaStructuredLLM(
            model=gloss_model,
            base_url=base_url,
            temperature=gloss_temp,
            disable_thinking=True,
            role="glossary",
            num_predict=np_gl,
        )
        llm_structured_glossary = OllamaGlossaryChain(
            ollama_glossary,
            GLOSSARY_SYSTEM,
            max_parse_attempts=attempts_gl,
        )
        llm_ini_glossary = None

    else:
        # OpenAI 兼容路径（ChatOpenAI + structured_output）/ OpenAI-compatible path.
        def _chat_kw(temperature: float, model: str, role: str) -> dict[str, Any]:
            kw: dict[str, Any] = {
                "model": model,
                "openai_api_key": api_key,
                "base_url": base_url,
                "temperature": temperature,
            }
            if request_timeout is not None:
                kw["request_timeout"] = request_timeout
            # 流式调试回调：仅观察生成过程，不改变业务逻辑 / streaming debug callbacks for observation only.
            callbacks = _maybe_streaming_callbacks(role)
            if callbacks:
                kw["callbacks"] = callbacks
                kw["streaming"] = True
            return kw

        llm_ini_reviewer = ChatOpenAI(
            **_chat_kw(float(rv.get("temperature", 0.1)), str(rv.get("model", "qwen2.5:14b")), "reviewer"),
        )
        llm_ini_editor = ChatOpenAI(
            **_chat_kw(float(ed.get("temperature", 0.7)), str(ed.get("model", "qwen2.5:14b")), "editor"),
        )
        llm_ini_critic = ChatOpenAI(
            **_chat_kw(float(cr.get("temperature", 0.0)), str(cr.get("model", "qwen2.5:14b")), "critic"),
        )

        llm_structured_reviewer = llm_ini_reviewer.with_structured_output(ReviewOutput)
        llm_strucured_editor = llm_ini_editor.with_structured_output(EditorOutput)
        llm_structured_critic = llm_ini_critic.with_structured_output(ScoreOutput)

        llm_ini_glossary = ChatOpenAI(
            **_chat_kw(gloss_temp, gloss_model, "glossary"),
        )
        gloss_sys_esc = _escape_langchain_template_literals(GLOSSARY_SYSTEM)
        prompt_glossary = ChatPromptTemplate.from_messages(
            [
                ("system", gloss_sys_esc),
                (
                    "human",
                    "Current merged glossary:\n{existing_glossary}\n\n"
                    "Section title:\n{title}\n\nLaTeX section body:\n{content}",
                ),
            ]
        )
        llm_structured_glossary = prompt_glossary | llm_ini_glossary.with_structured_output(
            GlossaryExtractOutput
        )

    gc = merged.get("glossary") or {}
    _GLOSSARY_PERSIST = {
        "merged_path": str(gc.get("merged_path", "private/glossary.merged.yaml")),
        "persist": bool(gc.get("persist_merged_after_merge", True)),
    }

    # 记录最终选用的模型与超时 / log resolved models and timeout.
    logging.getLogger(__name__).info(
        "init_llms_from_config: mode=%s backend=%s base_url=%s request_timeout=%r "
        "reviewer_model=%s editor_model=%s critic_model=%s",
        mode_resolved,
        backend,
        base_url,
        request_timeout,
        str(rv.get("model", "qwen2.5:14b")),
        str(ed.get("model", "qwen2.5:14b")),
        str(cr.get("model", "qwen2.5:14b")),
    )


logger = logging.getLogger(__name__)


init_llms_from_config({})


def _flush_log_handlers() -> None:
    """在阻塞 LLM 调用前刷新 handler，确保日志落盘 / flush handlers before blocking LLM calls so logs hit disk."""
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def _elapsed_seconds(state: GraphState) -> float:
    """自 ``run_started_at`` 起的单调时钟秒数 / monotonic seconds since ``run_started_at``."""
    if not state.run_started_at:
        return 0.0
    return time.monotonic() - state.run_started_at


def _progress_args(state: GraphState) -> tuple[int, int, int, int, float]:
    """日志用元组：(外层轮次显示, 上限, 当前节号, 总节数, 秒) / tuple for log formatting."""
    section_count = len(state.sections)
    section_number = min(state.current_section_index + 1, section_count)
    return (
        state.iteration + 1,
        state.max_iterations,
        section_number,
        section_count,
        _elapsed_seconds(state),
    )


def _is_section_skipped(state: GraphState, section_id: str) -> bool:
    """该节是否已在跳过列表 / whether ``section_id`` is in ``skipped_section_ids``."""
    return section_id in state.skipped_section_ids


def _next_active_section_index(state: GraphState, start_index: int) -> int:
    """自 ``start_index`` 起第一个未跳过节的索引；无则 ``len(sections)`` / first non-skipped index from ``start_index``."""
    index = start_index
    while index < len(state.sections):
        if not _is_section_skipped(state, state.sections[index].id):
            return index
        index += 1
    return len(state.sections)


def section_score_summary(state: GraphState) -> list[tuple[str, float]]:
    """文档序 (section_id, 最近采纳分)；无采纳记 0.0 / document-ordered accepted scores; default 0.0."""
    accepted_scores: dict[str, float] = {}
    for item in state.history:
        if item.accepted:
            accepted_scores[item.section_id] = item.score
    return [(section.id, accepted_scores.get(section.id, 0.0)) for section in state.sections]


# --- 1 init：解析 \\section、重置计数与计时 / parse sections, reset counters and timer ---
def init_node(state: GraphState) -> GraphState:
    """解析 ``\\section``、填充 ``document_prefix``/``sections``、初始化计时与计数 / parse TeX, init state and timers."""
    state.run_started_at = time.monotonic()
    prefix, sections = split_prefix_and_sections(state.original_tex)
    state.document_prefix = prefix
    state.sections = sections
    body0 = render_sections(sections) if sections else ""
    state.current_tex = body0
    state.best_tex = body0

    state.iteration = 0
    state.current_section_index = 0
    state.section_no_improve_rounds = {section.id: 0 for section in sections}
    state.skipped_section_ids = []
    state.editor_skipped_section_ids = []
    state.iteration_accepted_count = 0
    state.stop_due_to_no_document_improve = False
    state.llm_failure_count = 0
    logger.info(
        "init_node: mode=%s initialized sections=%s max_iterations=%s max_no_improve=%s elapsed=%.2fs",
        state.edit_mode,
        len(sections),
        state.max_iterations,
        state.max_no_improve,
        _elapsed_seconds(state),
    )

    return state


def glossary_node_noop(state: GraphState) -> GraphState:
    """Mock 图占位：与 LLM 图拓扑对齐，不修改 state / no-op for mock graph topology parity."""
    return state


def _glossary_appendix(state: GraphState) -> str:
    """注入审稿/编辑 human 的术语表后缀 / suffix for reviewer/editor human prompts."""
    if not state.glossary_enabled:
        return ""
    block = render_glossary_block(state.glossary_locked, state.glossary_provisional)
    return f"\n\n{block}" if block else ""


def _critic_glossary_note(state: GraphState) -> str:
    """注入 critic：术语一致性提示 / critic note for glossary consistency."""
    if not state.glossary_enabled:
        return ""
    block = render_glossary_block(state.glossary_locked, state.glossary_provisional)
    if not block:
        return ""
    return (
        "\n\n术语表一致性：若修改后正文与上述术语表中 locked 或已有 provisional 含义明显矛盾，"
        "应给显著更低分。\n\n" + block
    )


def glossary_node_llm(state: GraphState) -> GraphState:
    """首轮外层迭代、每节一次：模型抽取术语并 merge 进 provisional / extract+merge once per section on outer iter 0."""
    if not state.glossary_enabled:
        return state
    if state.iteration > 0:
        return state
    if not state.sections:
        return state
    section = state.sections[state.current_section_index]
    if section.id in state.glossary_extracted_section_ids:
        return state

    existing = render_glossary_block(state.glossary_locked, state.glossary_provisional) or "(none yet)"

    if llm_structured_glossary is None:
        logger.warning("glossary_node_llm: llm_structured_glossary is None, skipping extract")
        state.glossary_extracted_section_ids = [
            *state.glossary_extracted_section_ids,
            section.id,
        ]
        return state

    try:
        logger.info(
            "glossary_node_llm: section_id=%s iteration=%s invoking LLM",
            section.id,
            state.iteration,
        )
        _flush_log_handlers()
        out = llm_structured_glossary.invoke(
            {
                "title": section.title,
                "content": section.content,
                "existing_glossary": existing,
            }
        )
        raw_entries: list[dict[str, Any]] = []
        for e in out.entries:
            if hasattr(e, "model_dump"):
                raw_entries.append(e.model_dump())
            else:
                raw_entries.append(e.dict())  # type: ignore[call-arg]
        new_prov, logs = merge_glossary_candidates(
            state.glossary_locked,
            state.glossary_provisional,
            raw_entries,
        )
        for line in logs:
            logger.info("glossary_node_llm: %s", line)
        state.glossary_provisional = new_prov
    except Exception as e:
        state.llm_failure_count += 1
        logger.error("glossary_node_llm failed: %s", e, exc_info=True)

    state.glossary_extracted_section_ids = [
        *state.glossary_extracted_section_ids,
        section.id,
    ]

    if _GLOSSARY_PERSIST.get("persist"):
        try:
            save_merged_yaml(
                Path(_GLOSSARY_PERSIST["merged_path"]),
                state.glossary_locked,
                state.glossary_provisional,
            )
        except Exception as e:
            logger.warning("glossary persist failed: %s", e)

    return state


# --- 2 reviewer (mock)：占位 issues，离线测图 / stub issues for offline graph tests ---
def reviewer_node(state: GraphState) -> GraphState:
    """Mock 审稿：写入固定占位 issues / mock reviewer: attach stub issues."""
    section = state.sections[state.current_section_index]

    # Mock：固定占位问题；生产见 reviewer_node_llm / stub issues; production path is ``reviewer_node_llm``.
    issues = [
        Issue(
            section_id=section.id,
            problem="Sentence unclear",
            severity="medium",
            span=None
        )
    ]

    state.issues = issues
    logger.info(
        "reviewer_node: section_id=%s index=%s issues=%s progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        state.current_section_index,
        len(issues),
        *_progress_args(state),
    )
    return state

def reviewer_node_llm(state: GraphState) -> GraphState:
    """LLM 审稿：对当前节 title+content 生成 ``Issue`` 列表 / LLM review: emit ``Issue`` list for current section."""
    # 当前待处理段落 / Current section under review
    section = state.sections[state.current_section_index]

    # 学术论文 + LaTeX 的 system 提示（转义花括号）/ academic LaTeX system prompt (brace-escaped).
    # 可按需在 prompt_modes 中按领域调整 / tune per domain in ``prompt_modes`` if needed.
    sys_r = _escape_langchain_template_literals(system_prompt_for("reviewer", state.edit_mode))
    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_r),
        ("human", "标题: {title}\n\n内容:\n{content}{glossary_appendix}"),
    ])

    # 组装并执行 LCEL 链 / build and run LCEL chain.
    chain = prompt | llm_structured_reviewer

    try:
        logger.info(
            "reviewer_node_llm: mode=%s invoking LLM (HTTP log line appears only after response) "
            "section_id=%s title_chars=%s content_chars=%s",
            state.edit_mode,
            section.id,
            len(section.title),
            len(section.content),
        )
        _flush_log_handlers()
        response = chain.invoke(
            {
                "title": section.title,
                "content": section.content,
                "glossary_appendix": _glossary_appendix(state),
            }
        )
        
        # 写入 issues，并统一 section_id / attach issues with correct ``section_id``.
        issues = []
        for issue in response.issues:
            issue.section_id = section.id  # 与当前节对齐 / align with current section.
            issues.append(issue)
            
        state.issues = issues

    except Exception as e:
        state.llm_failure_count += 1
        logger.error("reviewer_node_llm failed: %s", e, exc_info=True)
        # 失败时置空列表，避免中断整图 / on failure use empty list so graph continues.
        state.issues = []

    # 与既有 reviewer 日志字段对齐 / keep log fields consistent with mock reviewer.
    logger.info(
        "reviewer_node: section_id=%s index=%s issues=%s progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        state.current_section_index,
        len(state.issues),
        *_progress_args(state),
    )
    
    return state



# --- 3 editor (mock)：按 issues 简单追加标记 / mock editor: append marker per issue ---
def editor_node(state: GraphState):
    """Mock 编辑：按 issues 在正文末尾追加标记 / mock editor: append marker per issue."""
    section = state.sections[state.current_section_index]

    old_content = section.content
    new_content = old_content

    for issue in state.issues:
        if issue.section_id == section.id:
            new_content = new_content + "\n% improved"

    section.content = new_content
    state.sections[state.current_section_index] = section

    # 先追加 history 占位；分数与采纳由 critic、aggregator 填写 / history placeholder; score/accept filled later.
    # Reassign the list rather than mutating it in-place. Some LangGraph state
    # merge paths do not reliably observe nested Pydantic list mutation.
    state.history = [
        *state.history,
        HistoryItem(
            iteration=state.iteration,
            section_id=section.id,
            before=old_content,
            after=new_content,
            score=0.0,          # critic 后更新 / updated by critic
            accepted=False      # aggregator 决定 / decided by aggregator
        ),
    ]
    logger.info(
        "editor_node: section_id=%s issues_applied=%s history_len=%s "
        "progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        len(state.issues),
        len(state.history),
        *_progress_args(state),
    )

    return state

def editor_node_llm(state: GraphState):
    """LLM 编辑：仅处理当前节 issues；无 issues 时仍写 history 以对齐 critic / LLM edit; no issues still logs history for critic."""
    section = state.sections[state.current_section_index]
    
    # 仅保留当前节相关 issues / keep issues for the active section only.
    current_section_issues = [
        i for i in state.issues 
        if i.section_id == section.id
    ]
    
    # 无 issues 时仍写一条 history，便于 critic 对齐 / no issues: still append history for critic alignment.
    if not current_section_issues:
        logger.info("editor_node: section_id=%s no issues to fix, skipping.", section.id)
        state.history = [
            *state.history,
            HistoryItem(
                iteration=state.iteration,
                section_id=section.id,
                before=section.content,
                after=section.content,   # 无文本改动 / no textual change
                score=0.0,
                accepted=False  # 无改动则不标记采纳 / not accepted without edits
            ),
        ]
        return state

    issues_text = "\n".join([
    f"- [{i.severity}] {i.problem} | span: {i.span}"
    for i in current_section_issues
])

    sys_e = _escape_langchain_template_literals(system_prompt_for("editor", state.edit_mode))
    # 构建 ChatPromptTemplate / build ChatPromptTemplate.
    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_e),
        (
            "human",
            "【原始段落】\n"
            "{content}\n\n"
            "【需要解决的问题】\n"
            "{issues}\n"
            "{glossary_appendix}\n"
            "请输出修改后的 LaTeX 段落：",
        ),
    ])

    chain = prompt | llm_strucured_editor  # 可选 StrOutputParser / optional StrOutputParser

    try:
        logger.info(
            "editor_node_llm: mode=%s invoking LLM (HTTP log line appears only after response) "
            "section_id=%s num_issues=%s content_chars=%s",
            state.edit_mode,
            section.id,
            len(current_section_issues),
            len(section.content),
        )
        _flush_log_handlers()
        refined_content = chain.invoke(
            {
                "content": section.content,
                "issues": issues_text,
                "glossary_appendix": _glossary_appendix(state),
            }
        )
        
        # 去掉 Markdown 围栏等噪声 / strip markdown fences and noise.
        refined_content = refined_content.refined_latex.strip()
        refined_content = refined_content.replace("```latex", "").replace("```", "").strip()
        refined_content = strip_leading_section_command(refined_content)
        refined_content = normalize_fake_newlines_in_latex(refined_content)

        # 写回当前节正文 / write back section body.
        old_content = section.content
        section.content = refined_content
        state.sections[state.current_section_index] = section
        
        # 追加 editor 历史项 / append editor history item.
        state.history = [
            *state.history,
            HistoryItem(
                iteration=state.iteration,
                section_id=section.id,
                before=old_content,
                after=refined_content,
                score=0.0,
                accepted=False,
            ),
        ]

    except Exception as e:
        logger.error("editor_node_llm failed: %s", e, exc_info=True)
        # 占位 history + 跳过后续 reviewer，避免 critic 误用旧 history / placeholder history + skip; avoids critic using stale history[-1].
        body = section.content
        state.history = [
            *state.history,
            HistoryItem(
                iteration=state.iteration,
                section_id=section.id,
                before=body,
                after=body,
                score=0.0,
                accepted=False,
            ),
        ]
        if section.id not in state.skipped_section_ids:
            state.skipped_section_ids.append(section.id)
        if section.id not in state.editor_skipped_section_ids:
            state.editor_skipped_section_ids.append(section.id)
        logger.warning(
            "EDITOR_SECTION_SKIPPED: section_id=%s reason=structured_output_failed "
            "content_chars=%s num_issues=%s error_type=%s",
            section.id,
            len(body),
            len(current_section_issues),
            type(e).__name__,
        )

    # 与 mock editor 日志字段一致 / align log fields with mock editor.
    logger.info(
        "editor_node: section_id=%s issues_applied=%s history_len=%s "
        "progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        len(current_section_issues),
        len(state.history),
        *_progress_args(state),
    )
    
    return state


# --- 4 critic (mock)：随机分；pytest/e2e 可 monkeypatch / mock critic: random score; monkeypatch in tests ---
def critic_node(state: GraphState) -> GraphState:
    """Mock 评分：随机分，便于测试稳定（可 monkeypatch）/ mock critic: random score; monkeypatch for stability."""
    score = random.uniform(0.6, 0.95)

    state.current_score = score  # 供 aggregator 写入 history[-1].score / Fed to aggregator
    logger.info(
        "critic_node: score=%.4f progress=%s/%s section=%s/%s elapsed=%.2fs",
        score,
        *_progress_args(state),
    )

    return state


def critic_node_llm(state: GraphState) -> GraphState:
    """LLM 对 history 末条 before/after 打分（仅本轮改写）/ score last history before/after pair for this edit only."""
    # 与本轮 editor 输出对应的那条 history / Matches latest editor append
    if not state.history:
        logger.warning("critic_node: No history found to evaluate!")
        return state
        
    last_history = state.history[-1]

    sys_c = _escape_langchain_template_literals(system_prompt_for("critic", state.edit_mode))
    # 构建 ChatPromptTemplate / build ChatPromptTemplate.
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", sys_c),
            ("human", "修改前: {before}\n\n修改后: {after}{glossary_note}"),
        ]
    )

    chain = prompt | llm_structured_critic  # LCEL：prompt → structured critic / LCEL: prompt → structured critic.

    try:
        logger.info(
            "critic_node_llm: mode=%s invoking LLM (HTTP log line appears only after response) "
            "section_id=%s before_chars=%s after_chars=%s",
            state.edit_mode,
            last_history.section_id,
            len(last_history.before),
            len(last_history.after),
        )
        _flush_log_handlers()
        result = chain.invoke(
            {
                "before": last_history.before,
                "after": last_history.after,
                "glossary_note": _critic_glossary_note(state),
            }
        )
        score = result.score
    except Exception as e:
        state.llm_failure_count += 1
        logger.error("critic_node_llm failed: %s", e, exc_info=True)
        score = 0.5  # 失败时的中性默认分 / neutral default score on failure.

    state.current_score = score

    # 与 mock critic 日志风格一致 / match mock critic logging style.
    logger.info(
        "critic_node: section_id=%s score=%.2f progress=%s/%s section=%s/%s elapsed=%.2fs",
        last_history.section_id,
        score,
        *_progress_args(state),
    )
    
    return state

def aggregator_node(state: GraphState):
    """渲染全文；将 current_score 与「该段上次采纳分」比较，决定采纳或回滚并更新跳过逻辑。
    Re-render full TeX; accept/reject vs last accepted score for same section; update skips."""
    for section in state.sections:
        section.content = strip_leading_section_command(section.content)
    new_tex = render_sections(state.sections)

    state.current_tex = new_tex

    if not state.history:
        logger.warning("aggregator_node: history is empty, skipping update")
        return state
    last = state.history[-1]
    last.score = state.current_score

    previous_same_section = next(
        (
            item
            for item in reversed(state.history[:-1])
            if item.section_id == last.section_id and item.accepted
        ),
        None,
    )
    # 该段尚无采纳记录时基线为 0.0 / Baseline 0.0 if no prior accept for this section
    previous_score = previous_same_section.score if previous_same_section else 0.0

    if state.current_score > previous_score:
        state.best_tex = state.current_tex
        last.accepted = True
        state.section_no_improve_rounds[last.section_id] = 0
        state.iteration_accepted_count += 1
        logger.info(
            "aggregator_node: accepted iteration=%s section_id=%s score=%.4f "
            "previous_score=%.4f progress=%s/%s section=%s/%s elapsed=%.2fs",
            state.iteration,
            last.section_id,
            state.current_score,
            previous_score,
            *_progress_args(state),
        )
    else:
        last.accepted = False
        section_no_improve = state.section_no_improve_rounds.get(last.section_id, 0) + 1
        state.section_no_improve_rounds[last.section_id] = section_no_improve
        if (
            section_no_improve >= state.max_no_improve
            and last.section_id not in state.skipped_section_ids
        ):
            state.skipped_section_ids.append(last.section_id)
        rollback_content = previous_same_section.after if previous_same_section else last.before
        for idx, section in enumerate(state.sections):
            if section.id == last.section_id:
                section.content = rollback_content
                state.sections[idx] = section
                break
        state.current_tex = render_sections(state.sections)
        if not state.best_tex:
            state.best_tex = state.current_tex
        logger.info(
            "aggregator_node: rejected iteration=%s section_id=%s "
            "score=%.4f previous_score=%.4f section_no_improve=%s "
            "skipped_sections=%s progress=%s/%s section=%s/%s elapsed=%.2fs",
            state.iteration,
            last.section_id,
            state.current_score,
            previous_score,
            section_no_improve,
            len(state.skipped_section_ids),
            *_progress_args(state),
        )

    return state


def next_section(state: GraphState) -> GraphState:
    """前进到下一未跳过节的索引 / advance ``current_section_index`` to next non-skipped section."""
    state.current_section_index = _next_active_section_index(
        state,
        state.current_section_index + 1,
    )
    logger.debug(
        "next_section: current_section_index=%s progress=%s/%s section=%s/%s elapsed=%.2fs",
        state.current_section_index,
        *_progress_args(state),
    )
    return state


def has_more_sections(state: GraphState) -> str:
    """路由：还有节 → ``glossary``；否则 ``iteration_step`` / route to ``glossary`` or ``iteration_step``."""
    state.current_section_index = _next_active_section_index(state, state.current_section_index)
    if state.current_section_index < len(state.sections):
        return "glossary"
    else:
        return "iteration_step"


def iteration_step(state: GraphState) -> GraphState:
    """外层一步：自增 ``iteration``，按本轮采纳数设提前停止，指针回到首节 / outer step: bump iteration, early-stop flags, reset index."""
    accepted_count = state.iteration_accepted_count
    state.iteration += 1
    state.stop_due_to_no_document_improve = accepted_count == 0
    state.iteration_accepted_count = 0
    state.current_section_index = _next_active_section_index(state, 0)
    logger.info(
        "iteration_step: iteration=%s/%s elapsed=%.2fs history_len=%s "
        "accepted_in_round=%s skipped_sections=%s stop_no_document_improve=%s",
        state.iteration,
        state.max_iterations,
        _elapsed_seconds(state),
        len(state.history),
        accepted_count,
        len(state.skipped_section_ids),
        state.stop_due_to_no_document_improve,
    )
    return state


def route_after_iteration(state: GraphState) -> str:
    """外层路由：达上限、无全文改进或无活跃节 → ``end``；否则 ``glossary`` / outer route: ``end`` or ``glossary``."""
    if state.iteration >= state.max_iterations:
        return "end"
    if state.stop_due_to_no_document_improve:
        return "end"
    if state.current_section_index >= len(state.sections):
        return "end"
    return "glossary"
