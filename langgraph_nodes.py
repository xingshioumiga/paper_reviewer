"""LangGraph node functions: init → reviewer → editor → critic → aggregator → routing.

节点流水线：初始化 → 审稿 → 改写 → 打分 → 汇总采纳/回滚 → 切换段落或外层轮次。
Mock 节点用于快速验证；`*_llm` 节点通过 ``init_llms_from_config`` 使用配置文件中的 LLM。
"""

import logging
import random
import time

from langgraph_state import GraphState, HistoryItem, Issue
from paper_reviewer_tool import render_sections, split_into_sections, strip_leading_section_command
# from langchain_core.output_parsers import StrOutputParser

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from typing import Any, List, Optional
from pydantic import BaseModel, Field

from runtime_config import DEFAULT_CONFIG, merge_config


# LLM 结构化输出容器（与 ChatOpenAI.with_structured_output 配合）。
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

    def _chat_kw(temperature: float, model: str) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": model,
            "openai_api_key": api_key,
            "base_url": base_url,
            "temperature": temperature,
        }
        if request_timeout is not None:
            kw["request_timeout"] = request_timeout
        return kw

    llm_ini_reviewer = ChatOpenAI(
        **_chat_kw(float(rv.get("temperature", 0.1)), str(rv.get("model", "qwen2.5:14b"))),
    )
    llm_ini_editor = ChatOpenAI(
        **_chat_kw(float(ed.get("temperature", 0.7)), str(ed.get("model", "qwen2.5:14b"))),
    )
    llm_ini_critic = ChatOpenAI(
        **_chat_kw(float(cr.get("temperature", 0.0)), str(cr.get("model", "qwen2.5:14b"))),
    )

    llm_structured_reviewer = llm_ini_reviewer.with_structured_output(ReviewOutput)
    llm_strucured_editor = llm_ini_editor.with_structured_output(EditorOutput)
    llm_structured_critic = llm_ini_critic.with_structured_output(ScoreOutput)

    logging.getLogger(__name__).info(
        "init_llms_from_config: base_url=%s request_timeout=%r "
        "reviewer_model=%s editor_model=%s critic_model=%s",
        base_url,
        llm_ini_reviewer.request_timeout,
        str(rv.get("model", "qwen2.5:14b")),
        str(ed.get("model", "qwen2.5:14b")),
        str(cr.get("model", "qwen2.5:14b")),
    )


init_llms_from_config({})


logger = logging.getLogger(__name__)


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
    sections = split_into_sections(state.original_tex)

    state.sections = sections
    state.current_tex = state.original_tex

    state.best_tex = state.original_tex
    state.iteration = 0
    state.current_section_index = 0
    state.section_no_improve_rounds = {section.id: 0 for section in sections}
    state.skipped_section_ids = []
    state.iteration_accepted_count = 0
    state.stop_due_to_no_document_improve = False
    state.llm_failure_count = 0
    logger.info(
        "init_node: initialized sections=%s max_iterations=%s max_no_improve=%s elapsed=%.2fs",
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
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "你是一位顶尖物理学期刊的资深审稿人，同时也是 LaTeX 专家。"
            "你的任务是审查用户提供的 LaTeX 段落，识别其中的语法错误、学术表达不专业、逻辑漏洞或 LaTeX 格式问题。"
            "对于每个发现的问题，请务必给出准确的 problem 描述、severity(low/medium/high) 以及对应的 span(原文片段)。"
            "请保持专业、严谨的态度。最多返回 5 个最重要的问题"
        )),
        ("human", "标题: {title}\n\n内容:\n{content}")
    ])

    # 构造链条并执行
    chain = prompt | llm_structured_reviewer

    try:
        logger.info(
            "reviewer_node_llm: invoking LLM (HTTP log line appears only after response) "
            "section_id=%s title_chars=%s content_chars=%s",
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
    
    # 2. 构建优雅的 ChatPrompt
    prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "你是一位顶尖的 LaTeX 润色专家和物理学学术编辑。\n"
        "你的任务是基于问题列表，对给定段落进行最小必要修改（minimal edit）。\n\n"

        "【严格要求】\n"
        "1. 仅修改问题涉及的文本片段（由 span 指定），不要重写整个段落。\n"
        "2. 优先解决 high > medium > low 严重程度的问题。\n"
        "3. 严禁破坏 LaTeX 语法、公式、命令结构。\n"
        "4. 不要引入新的内容或改变原有科学含义。\n"
        "5. 输出必须是完整的 LaTeX 段落。\n"
        "6. 严禁输出 Markdown、解释说明或额外文本。\n\n"

        "【问题格式说明】\n"
        "- [severity] problem | span: 原文片段\n"
    )),
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
            "editor_node_llm: invoking LLM (HTTP log line appears only after response) "
            "section_id=%s num_issues=%s content_chars=%s",
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

    # 3. 使用 ChatPromptTemplate 构建 LCEL 链
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一位严苛的学术期刊编辑。请评价 LaTeX 段落的润色质量，只输出评分。注意，评分为0到1之间的浮点数评分，0.9表示完美，0.5表示无改进,禁止输出任何大于1的值。"),
        ("human", "修改前: {before}\n\n修改后: {after}")
    ])

    # 4. 组成威力强大的 Chain
    chain = prompt | llm_structured_critic

    try:
        logger.info(
            "critic_node_llm: invoking LLM (HTTP log line appears only after response) "
            "section_id=%s before_chars=%s after_chars=%s",
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
