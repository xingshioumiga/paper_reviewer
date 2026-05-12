"""LangGraph node functions: init → reviewer → editor → critic → aggregator → routing.

节点流水线：初始化 → 审稿 → 改写 → 打分 → 汇总采纳/回滚 → 切换段落或外层轮次。
Mock 节点用于快速验证；`*_llm` 节点通过 ``init_llms_from_config`` 使用配置文件中的 LLM。
"""

import logging
import os
import random
import re
import sys
import time
from typing import Any, List, Optional, Type, TypeVar

from langgraph_state import GraphState, HistoryItem, Issue
from paper_reviewer_tool import (
    normalize_fake_newlines_in_latex,
    render_sections,
    split_prefix_and_sections,
    strip_leading_section_command,
)
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
    """Rebuild global prompt table from merged YAML (call after each ``init_llms_from_config``)."""
    global _PROMPT_BUNDLE
    _PROMPT_BUNDLE = build_prompt_bundle(merged_config)


def system_prompt_for(role: str, mode: str) -> str:
    """Return system prompt for ``reviewer`` | ``editor`` | ``critic`` and current edit mode."""
    if role not in ("reviewer", "editor", "critic"):
        raise ValueError(f"invalid role: {role}")
    bundle = _PROMPT_BUNDLE if _PROMPT_BUNDLE is not None else build_prompt_bundle({})
    m = normalize_edit_mode(mode)
    per_mode = bundle.get(m) or bundle["proofread"]
    return per_mode[role]


def _escape_langchain_template_literals(s: str) -> str:
    """``ChatPromptTemplate`` treats ``{...}`` as variables; JSON examples in system text need doubling."""
    return s.replace("{", "{{").replace("}", "}}")


def _pydantic_validate_json(schema: type[T], raw: str) -> T:
    """将 JSON 字符串解析为 Pydantic 模型（兼容 v1 ``parse_raw`` 与 v2 ``model_validate_json``）。"""
    validate = getattr(schema, "model_validate_json", None)
    if callable(validate):
        return validate(raw)
    return schema.parse_raw(raw)  # type: ignore[call-arg]


def _balanced_json_object(text: str, start_idx: int) -> str | None:
    """从 ``start_idx`` 处的 ``{`` 起截取平衡的 ``{...}``，字符串内需跳过未配对括号（近似 JSON 规则）。"""
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
    """从左到右枚举可能的顶层 JSON 对象子串（用于模型夹杂解释文字或输出残缺 JSON 时）。"""
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
    """将 LLM 生成的 token 实时打印到 stderr（不干扰结构化输出）。"""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        # 打印到 stderr，避免污染 stdout/结构化解析
        sys.stderr.write(f"{self.prefix}{token}")
        sys.stderr.flush()

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        sys.stderr.write(f"\n[stream error: {error}]\n")
        sys.stderr.flush()


def _maybe_streaming_callbacks(role: str) -> list[BaseCallbackHandler] | None:
    """若设置了 DEBUG_LLM_STREAM=1，返回流式回调列表，否则 None。"""
    if os.getenv("DEBUG_LLM_STREAM", "").strip() in ("1", "true", "yes"):
        return [_DebugStreamingHandler(prefix=f"[{role}] ")]
    return None


# =========================
# Ollama 原生 API 支持（支持 think: false 等原生特性）
# =========================
class OllamaStructuredLLM:
    """包装 Ollama 原生客户端，支持结构化输出和禁用 thinking 模式。

    适用于 Qwen3.5 等默认开启 thinking 的模型，通过原生 API 的 options 禁用。
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        temperature: float = 0.7,
        disable_thinking: bool = True,
        role: str = "",
        timeout: float | None = None,
        num_predict: int | None = 8192,
    ) -> None:
        if not _OLLAMA_AVAILABLE:
            raise ImportError(
                "langchain-ollama is required for Ollama native backend. "
                "Install: pip install langchain-ollama"
            )
        # 移除 /v1 后缀，Ollama 原生 API 使用根路径
        base_url_clean = base_url.replace("/v1", "").rstrip("/")
        self.model = model
        self.role = role
        self.disable_thinking = disable_thinking

        # Ollama 原生选项
        # 注意：langchain-ollama 使用 reasoning 参数控制思考模式，不是 think
        # reasoning=False 关闭 thinking 模式，reasoning=None 使用默认行为
        reasoning = False if disable_thinking else None

        llm_kw: dict[str, Any] = {
            "model": model,
            "base_url": base_url_clean,
            "temperature": temperature,
            "reasoning": reasoning,
        }
        if num_predict is not None:
            llm_kw["num_predict"] = num_predict
        self.llm = OllamaLLM(**llm_kw)
        logger.debug(
            "Ollama native client created: model=%s, reasoning=%s, num_predict=%s",
            model,
            reasoning,
            num_predict,
        )

    def invoke(self, messages: list, output_schema: type[T]) -> T:
        """调用 Ollama 并解析为结构化输出；解析失败时有限次重试（缓解残缺 JSON）。"""
        retry_hint = (
            "上一版输出无法解析为合法 JSON。"
            "规则：字符串内的反斜杠必须写成 \\\\；字符串内不要出现未转义的双引号；"
            "problem 每条不超过 120 个中文字符，少用 LaTeX 命令字面量，改用文字描述（如「section 标题」）。"
            "请只输出一整段合法 UTF-8 JSON，不要用 Markdown 围栏，不要用「…」截断。"
        )
        msgs: list[Any] = list(messages)
        last_err: BaseException | None = None
        for attempt in range(3):
            response = self.llm.invoke(msgs)
            try:
                return self._parse_response(response, output_schema)
            except ValueError as e:
                last_err = e
                logging.getLogger(__name__).warning(
                    "OllamaStructuredLLM JSON parse failed attempt %s/3 role=%s: %s",
                    attempt + 1,
                    self.role,
                    e,
                )
                msgs = list(messages) + [HumanMessage(content=retry_hint)]
        assert last_err is not None
        raise last_err

    def _parse_response(self, content: str, schema: type[T]) -> T:
        """从模型响应中提取 JSON 并解析为 Pydantic 模型。"""
        stripped = content.strip()

        # 尝试直接解析（如果模型返回纯 JSON）
        try:
            return _pydantic_validate_json(schema, stripped)
        except Exception:
            pass

        # 尝试从 markdown 代码块中提取 JSON
        json_blocks = re.findall(r'```(?:json)?\s*([\s\S]*?)```', content)
        for block in json_blocks:
            try:
                return _pydantic_validate_json(schema, block.strip())
            except Exception:
                continue

        # 平衡括号截取多个候选（避免贪婪 .* 吞掉无效尾部或匹配错位）
        for chunk in _iter_json_object_candidates(content):
            try:
                return _pydantic_validate_json(schema, chunk)
            except Exception:
                continue

        raise ValueError(f"No valid JSON found in response: {content[:500]}...")


# LLM 结构化输出容器
# Pydantic wrappers for structured LLM outputs.
class ReviewOutput(BaseModel):
    issues: List[Issue] = Field(description="段落中发现的问题列表")


# 定义一个容器，方便 LLM 一次性返回优化后的 LaTeX 段落内容，结构化输出
class EditorOutput(BaseModel):
    refined_latex: str = Field(
        description="完全优化后的 LaTeX 段落内容。要求：严禁包含任何 Markdown 标签、解释文字或开场白。"
    )


# 定义一个容器，方便 LLM 一次性返回评分结果，结构化输出
class ScoreOutput(BaseModel):
    score: float = Field(description="0到1之间的浮点数评分，0.9表示完美，0.5表示无改进")


# =========================
# Ollama 原生 Chain 类（放在 Output 类定义后避免前向引用）
# =========================
from langchain_core.runnables import Runnable


class OllamaReviewerChain(Runnable):
    """Ollama 原生的审稿链，返回 ReviewOutput。"""

    def __init__(self, llm: OllamaStructuredLLM, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> ReviewOutput:
        # 处理 ChatPromptValue 对象（来自 prompt | chain 管道）
        if hasattr(inputs, "to_messages"):
            # 如果是 ChatPromptValue，直接使用其消息并添加系统提示
            messages = [SystemMessage(content=self.system_prompt)] + list(inputs.to_messages())
        else:
            # 如果是字典，按原逻辑处理
            title = inputs.get("title", "")
            content = inputs.get("content", "")
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=f"标题: {title}\n\n内容:\n{content}"),
            ]
        return self.llm.invoke(messages, ReviewOutput)


class OllamaEditorChain(Runnable):
    """Ollama 原生的编辑链，返回 EditorOutput。"""

    def __init__(self, llm: OllamaStructuredLLM, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> EditorOutput:
        # 处理 ChatPromptValue 对象（来自 prompt | chain 管道）
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
        return self.llm.invoke(messages, EditorOutput)


class OllamaCriticChain(Runnable):
    """Ollama 原生的评分链，返回 ScoreOutput。"""

    def __init__(self, llm: OllamaStructuredLLM, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt

    def invoke(self, inputs: dict[str, Any], config: Any = None, **kwargs: Any) -> ScoreOutput:
        # 处理 ChatPromptValue 对象（来自 prompt | chain 管道）
        if hasattr(inputs, "to_messages"):
            messages = [SystemMessage(content=self.system_prompt)] + list(inputs.to_messages())
        else:
            before = inputs.get("before", "")
            after = inputs.get("after", "")
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=f"修改前: {before}\n\n修改后: {after}"),
            ]
        return self.llm.invoke(messages, ScoreOutput)


# 运行期由 init_llms_from_config 填充；import 时用 DEFAULT_CONFIG 预初始化一次。
# Filled by init_llms_from_config; seeded once at import from DEFAULT_CONFIG.
llm_ini_reviewer: ChatOpenAI
llm_ini_editor: ChatOpenAI
llm_ini_critic: ChatOpenAI
llm_structured_reviewer: Any
llm_strucured_editor: Any
llm_structured_critic: Any


def init_llms_from_config(config: dict[str, Any] | None = None) -> None:
    """根据合并后的配置重建三个 ChatOpenAI 客户端及结构化链（应在 run.py 中再次调用以覆盖 YAML）。
    Rebuild reviewer/editor/critic clients and structured chains from merged config."""
    global llm_ini_reviewer, llm_ini_editor, llm_ini_critic
    global llm_structured_reviewer, llm_strucured_editor, llm_structured_critic

    merged = merge_config(DEFAULT_CONFIG, config or {})
    # Canonical edit mode + prompt bundle (OpenAI 节点按 state.edit_mode 取词；Ollama 链在 init 时绑定当前 mode)。
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

    timeout_raw = llm_cfg.get("request_timeout")
    request_timeout: float | None = None
    if timeout_raw is not None:
        try:
            t = float(timeout_raw)
            if t > 0:
                request_timeout = t
        except (TypeError, ValueError):
            pass

    # 选择后端：openai_compatible（默认）或 ollama_native
    backend = str(llm_cfg.get("backend", "openai_compatible")).lower()
    use_ollama_native = backend == "ollama_native"

    if use_ollama_native:
        # Ollama 原生 API 模式（支持 think: false 等原生选项）
        if not _OLLAMA_AVAILABLE:
            raise ImportError(
                "backend='ollama_native' requires langchain-ollama. "
                "Install: pip install langchain-ollama"
            )
        logger.info(
            "Using Ollama native backend (think=false) for models: "
            "reviewer=%s, editor=%s, critic=%s",
            rv.get("model", "qwen2.5:14b"),
            ed.get("model", "qwen2.5:14b"),
            cr.get("model", "qwen2.5:14b"),
        )

        ollama_reviewer = OllamaStructuredLLM(
            model=str(rv.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(rv.get("temperature", 0.1)),
            disable_thinking=True,
            role="reviewer",
        )
        ollama_editor = OllamaStructuredLLM(
            model=str(ed.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(ed.get("temperature", 0.7)),
            disable_thinking=True,
            role="editor",
        )
        ollama_critic = OllamaStructuredLLM(
            model=str(cr.get("model", "qwen2.5:14b")),
            base_url=base_url,
            temperature=float(cr.get("temperature", 0.0)),
            disable_thinking=True,
            role="critic",
        )

        # 使用自定义链包装 Ollama 客户端（system 与当前 mode 一致）
        llm_structured_reviewer = OllamaReviewerChain(
            ollama_reviewer, system_prompt_for("reviewer", mode_resolved)
        )
        llm_strucured_editor = OllamaEditorChain(
            ollama_editor, system_prompt_for("editor", mode_resolved)
        )
        llm_structured_critic = OllamaCriticChain(
            ollama_critic, system_prompt_for("critic", mode_resolved)
        )

    else:
        # OpenAI 兼容模式（默认，适合生产部署和多云接入）
        def _chat_kw(temperature: float, model: str, role: str) -> dict[str, Any]:
            kw: dict[str, Any] = {
                "model": model,
                "openai_api_key": api_key,
                "base_url": base_url,
                "temperature": temperature,
            }
            if request_timeout is not None:
                kw["request_timeout"] = request_timeout
            # 若开启流式调试，传入回调；不影响整体逻辑，仅用于观察 LLM 是否正在生成。
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

    # 统一日志输出
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
    """Ensure pre-invoke lines hit disk before a blocking LLM call."""
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def _elapsed_seconds(state: GraphState) -> float:
    if not state.run_started_at:
        return 0.0
    return time.monotonic() - state.run_started_at


def _progress_args(state: GraphState) -> tuple[int, int, int, int, float]:
    """供日志使用：(外层迭代显示值, max_iter, 当前节序号, 总节数, 已用秒数)。
    For logging: (1-based iteration display, max, section #, total sections, elapsed s)."""
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
    """该段是否因连续无提升已被列入跳过列表。
    Whether this section is skipped after too many non-improving edits."""
    return section_id in state.skipped_section_ids


def _next_active_section_index(state: GraphState, start_index: int) -> int:
    """从 start_index 起找第一个未被跳过的段落索引；若无则返回 len(sections)。
    Next section index ≥ start_index that is not skipped, or len(sections) if none."""
    index = start_index
    while index < len(state.sections):
        if not _is_section_skipped(state, state.sections[index].id):
            return index
        index += 1
    return len(state.sections)


def section_score_summary(state: GraphState) -> list[tuple[str, float]]:
    """按文档顺序返回 (section_id, 该段最近一次「采纳」分数)；从未采纳则为 0.0。
    Document-ordered (section_id, latest accepted critic score); 0.0 if never accepted."""
    accepted_scores: dict[str, float] = {}
    for item in state.history:
        if item.accepted:
            accepted_scores[item.section_id] = item.score
    return [(section.id, accepted_scores.get(section.id, 0.0)) for section in state.sections]


# --- 1 init：解析 \\section、重置计数器与计时 ---
# --- 1 init: parse sections, reset counters and timer ---
def init_node(state: GraphState) -> GraphState:
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


# --- 2 reviewer (mock)：占位问题列表，便于离线测图 ---
# --- 2 reviewer (mock): stub issues for offline graph tests ---
def reviewer_node(state: GraphState) -> GraphState:
    section = state.sections[state.current_section_index]

    # Mock：固定问题；生产路径见 reviewer_node_llm。
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
    """LLM 审稿：对当前 section 的 title+content 产出 Issue 列表。"""
    # 当前待处理段落 / Current section under review
    section = state.sections[state.current_section_index]

    # 定义针对学术论文和 LaTeX 格式的 Prompt
    # 这里我针对大哥你的研究领域，加强了对公式和逻辑的审查要求
    sys_r = _escape_langchain_template_literals(system_prompt_for("reviewer", state.edit_mode))
    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_r),
        ("human", "标题: {title}\n\n内容:\n{content}")
    ])

    # 构造链条并执行
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
        response = chain.invoke({
            "title": section.title,
            "content": section.content
        })
        
        # 将 LLM 返回的问题列表存入 state，并统一打上 section_id 标签
        issues = []
        for issue in response.issues:
            issue.section_id = section.id # 确保 ID 匹配
            issues.append(issue)
            
        state.issues = issues

    except Exception as e:
        state.llm_failure_count += 1
        logger.error("reviewer_node_llm failed: %s", e, exc_info=True)
        # 如果报错，给个空的 list 防止程序崩掉
        state.issues = []

    # --- 保持大哥要求的原始日志输出格式 ---
    logger.info(
        "reviewer_node: section_id=%s index=%s issues=%s progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        state.current_section_index,
        len(state.issues),
        *_progress_args(state),
    )
    
    return state



# --- 3 editor (mock)：按 issues 做简单文本追加 ---
def editor_node(state: GraphState):
    section = state.sections[state.current_section_index]

    old_content = section.content
    new_content = old_content

    for issue in state.issues:
        if issue.section_id == section.id:
            new_content = new_content + "\n% improved"

    section.content = new_content
    state.sections[state.current_section_index] = section

    # 先写入历史占位；分数与是否采纳由 critic + aggregator 后续填写。
    state.history.append(
        HistoryItem(
            iteration=state.iteration,
            section_id=section.id,
            before=old_content,
            after=new_content,
            score=0.0,          # critic 后再更新
            accepted=False      # aggregator 决定
        )
    )
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
    """LLM 改写：仅处理当前段 issues；无 issues 时仍追加一条 history 供 critic 对齐。"""
    section = state.sections[state.current_section_index]
    
    # ✅ 显式过滤：精准锁定当前段落的问题
    current_section_issues = [
        i for i in state.issues 
        if i.section_id == section.id
    ]
    
    # 如果没问题，咱们就不浪费 Ollama 的算力了
    if not current_section_issues:
        logger.info("editor_node: section_id=%s no issues to fix, skipping.", section.id)
        state.history.append(HistoryItem(
            iteration=state.iteration,
            section_id=section.id,
            before=section.content,
            after=section.content,   # ❗没有修改
            score=0.0,
            accepted=False # 没有修改，所以不接受
        ))#如果没问题，为了保证critic的评分准确，所以需要记录历史
        
        return state

    issues_text = "\n".join([
    f"- [{i.severity}] {i.problem} | span: {i.span}"
    for i in current_section_issues
])

    sys_e = _escape_langchain_template_literals(system_prompt_for("editor", state.edit_mode))
    # 2. 构建优雅的 ChatPrompt
    prompt = ChatPromptTemplate.from_messages([
    ("system", sys_e),
    ("human", (
        "【原始段落】\n"
        "{content}\n\n"
        "【需要解决的问题】\n"
        "{issues}\n\n"
        "请输出修改后的 LaTeX 段落："
    ))
])

    # 3. 组成 LCEL 链条：Prompt -> LLM -> 纯文本解析
    chain = prompt | llm_strucured_editor # | StrOutputParser()

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
        refined_content = chain.invoke({
            "content": section.content,
            "issues": issues_text
        })
        
        # 简单清洗，防止 LLM 不听话带上 Markdown 标签
        refined_content = refined_content.refined_latex.strip()
        refined_content = refined_content.replace("```latex", "").replace("```", "").strip()
        refined_content = strip_leading_section_command(refined_content)
        refined_content = normalize_fake_newlines_in_latex(refined_content)

        # 更新 state
        old_content = section.content
        section.content = refined_content
        state.sections[state.current_section_index] = section
        
        # 记录历史
        state.history.append(HistoryItem(
            iteration=state.iteration,
            section_id=section.id,
            before=old_content,
            after=refined_content,
            score=0.0,
            accepted=False
        ))

    except Exception as e:
        state.llm_failure_count += 1
        logger.error("editor_node_llm failed: %s", e, exc_info=True)

    # 5. 保持大哥要求的日志格式，同时稍微优化了显示精度
    logger.info(
        "editor_node: section_id=%s issues_applied=%s history_len=%s "
        "progress=%s/%s section=%s/%s elapsed=%.2fs",
        section.id,
        len(current_section_issues),
        len(state.history),
        *_progress_args(state),
    )
    
    return state


# --- 4 critic (mock)：随机分，用于 pytest/e2e 稳定性（可 monkeypatch）---
def critic_node(state: GraphState) -> GraphState:
    score = random.uniform(0.6, 0.95)

    state.current_score = score  # 供 aggregator 写入 history[-1].score / Fed to aggregator
    logger.info(
        "critic_node: score=%.4f progress=%s/%s section=%s/%s elapsed=%.2fs",
        score,
        *_progress_args(state),
    )

    return state


def critic_node_llm(state: GraphState) -> GraphState:
    """LLM 对 history 最后一条 before/after 打分（仅评价当前这次改写）。"""
    # 与本轮 editor 输出对应的那条 history / Matches latest editor append
    if not state.history:
        logger.warning("critic_node: No history found to evaluate!")
        return state
        
    last_history = state.history[-1]

    sys_c = _escape_langchain_template_literals(system_prompt_for("critic", state.edit_mode))
    # 3. 使用 ChatPromptTemplate 构建 LCEL 链
    prompt = ChatPromptTemplate.from_messages([
        ("system", sys_c),
        ("human", "修改前: {before}\n\n修改后: {after}")
    ])

    # 4. 组成威力强大的 Chain
    chain = prompt | llm_structured_critic

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
        result = chain.invoke({
            "before": last_history.before,
            "after": last_history.after
        })
        score = result.score
    except Exception as e:
        state.llm_failure_count += 1
        logger.error("critic_node_llm failed: %s", e, exc_info=True)
        score = 0.5  # 报错时的保底分

    state.current_score = score

    # 5. 日志输出（保持风格一致）
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
    """线性扫描下一活跃段落索引（跳过已在 skipped_section_ids 中的段）。"""
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
    """路由：仍有未处理（且未跳过）的段 → reviewer；否则进入 iteration_step。"""
    state.current_section_index = _next_active_section_index(state, state.current_section_index)
    if state.current_section_index < len(state.sections):
        return "reviewer"
    else:
        return "iteration_step"


def iteration_step(state: GraphState) -> GraphState:
    """外层轮次结束：递增 iteration，根据本轮采纳数设置提前停止标记，并将指针重置到首个活跃段。"""
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
    """外层路由：达最大轮次、上一轮全文无改进、或无活跃段 → end；否则回到 reviewer。"""
    if state.iteration >= state.max_iterations:
        return "end"
    if state.stop_due_to_no_document_improve:
        return "end"
    if state.current_section_index >= len(state.sections):
        return "end"
    return "reviewer"
