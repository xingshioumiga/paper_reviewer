import logging
import random
import time

from langgraph_state import GraphState, HistoryItem, Issue
from paper_reviewer_tool import render_sections, split_into_sections, strip_leading_section_command
# from langchain_core.output_parsers import StrOutputParser

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
# from langchain_core.output_parsers import PydanticOutputParser
from typing import List, Optional
from pydantic import BaseModel, Field



# --- 初始化本地 Ollama 驱动的 Qwen2.5---reviewer ---
llm_ini_reviewer = ChatOpenAI(
    model="qwen2.5:14b",
    openai_api_key="ollama",
    base_url="http://localhost:11434/v1",
    temperature=0.1 # 建议低随机性，保证评审结果严谨
)

# --- 初始化本地 Ollama 驱动的 Qwen2.5---editor ---
llm_ini_editor = ChatOpenAI(
    model="qwen2.5:14b",
    openai_api_key="ollama",
    base_url="http://localhost:11434/v1",
    temperature=0.7 # 建议中随机性，保证编辑结果流畅
)

# --- 初始化本地 Ollama 驱动的 Qwen2.5---critic ---
llm_ini_critic = ChatOpenAI(
    model="qwen2.5:14b",
    openai_api_key="ollama",
    base_url="http://localhost:11434/v1",
    temperature=0. # 温度将为0，保证评分结果严谨
)
# # --- 初始化本地 Ollama 驱动的 Qwen2.5---reviewer ---
# llm_ini_reviewer = ChatOpenAI(
#     model="qwen3.5:9b",
#     openai_api_key="ollama",
#     base_url="http://localhost:11434/v1",
#     temperature=0.1 # 建议低随机性，保证评审结果严谨
# )

# # --- 初始化本地 Ollama 驱动的 Qwen2.5---editor ---
# llm_ini_editor = ChatOpenAI(
#     model="qwen3.5:9b",
#     openai_api_key="ollama",
#     base_url="http://localhost:11434/v1",
#     temperature=0.7 # 建议中随机性，保证编辑结果流畅
# )

# # --- 初始化本地 Ollama 驱动的 Qwen2.5---critic ---
# llm_ini_critic = ChatOpenAI(
#     model="qwen3.5:9b",
#     openai_api_key="ollama",
#     base_url="http://localhost:11434/v1",
#     temperature=0. # 温度将为0，保证评分结果严谨
# )

# 定义一个容器，方便 LLM 一次性返回多个 Issue，结构化输出
class ReviewOutput(BaseModel):
    issues: List[Issue] = Field(description="段落中发现的问题列表")
# 创建结构化链reviewer
llm_structured_reviewer = llm_ini_reviewer.with_structured_output(ReviewOutput)


# 定义一个容器，方便 LLM 一次性返回优化后的 LaTeX 段落内容，结构化输出
class EditorOutput(BaseModel):
    refined_latex: str = Field(
        description="完全优化后的 LaTeX 段落内容。要求：严禁包含任何 Markdown 标签、解释文字或开场白。"
    )
# 创建结构化链editor
llm_strucured_editor = llm_ini_editor.with_structured_output(EditorOutput)


# 定义一个容器，方便 LLM 一次性返回评分结果，结构化输出
class ScoreOutput(BaseModel):
    score: float = Field(description="0到1之间的浮点数评分，0.9表示完美，0.5表示无改进")
#创建结构化链
llm_structured_critic = llm_ini_critic.with_structured_output(ScoreOutput)


# ===== 需要你已有的定义 =====
# Section, Issue, HistoryItem, GraphState


logger = logging.getLogger(__name__)


def _elapsed_seconds(state: GraphState) -> float:
    if not state.run_started_at:
        return 0.0
    return time.monotonic() - state.run_started_at


def _progress_args(state: GraphState) -> tuple[int, int, int, int, float]:
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
    """判断 section 是否已达到无提升上限，后续轮次应直接跳过。"""
    return section_id in state.skipped_section_ids


def _next_active_section_index(state: GraphState, start_index: int) -> int:
    """从 start_index 开始寻找仍需要优化的 section。"""
    index = start_index
    while index < len(state.sections):
        if not _is_section_skipped(state, state.sections[index].id):
            return index
        index += 1
    return len(state.sections)


# =========================
# 1️⃣ 初始化节点
# =========================
def init_node(state: GraphState) -> GraphState:
    state.run_started_at = time.monotonic()
    sections = split_into_sections(state.original_tex)

    state.sections = sections
    state.current_tex = state.original_tex

    state.best_tex = state.original_tex
    state.best_score = 0.0

    state.iteration = 0
    state.current_section_index = 0
    state.section_no_improve_rounds = {section.id: 0 for section in sections}
    state.skipped_section_ids = []
    state.iteration_accepted_count = 0
    state.stop_due_to_no_document_improve = False
    logger.info(
        "init_node: initialized sections=%s max_iterations=%s max_no_improve=%s elapsed=%.2fs",
        len(sections),
        state.max_iterations,
        state.max_no_improve,
        _elapsed_seconds(state),
    )

    return state


# =========================
# 2️⃣ Reviewer：找问题（当前简化版）
# =========================
def reviewer_node(state: GraphState) -> GraphState:
    section = state.sections[state.current_section_index]

    # mock：后续换 LLM
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

#LLM版本---------------------------------------------------------------
def reviewer_node_llm(state: GraphState) -> GraphState:
    # 获取当前要处理的 section
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
        # 调用 Qwen2.5 进行审查
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
        logger.error("reviewer_node 报错了，大哥！错误信息: %s", e)
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



# =========================
# 3️⃣ Editor：基于 issues 修改
# =========================
def editor_node(state: GraphState):
    section = state.sections[state.current_section_index]

    old_content = section.content
    new_content = old_content

    for issue in state.issues:
        if issue.section_id == section.id:
            new_content = new_content + "\n% improved"

    section.content = new_content
    state.sections[state.current_section_index] = section

    # ✅ 直接写入一个“pending history”
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

#LLM版本---------------------------------------------------------------
def editor_node_llm(state: GraphState):
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
        # 4. 执行润色
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
        logger.error("editor_node 润色翻车了，大哥！错误: %s", e)

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


# =========================
# 4️⃣ Critic：打分
# =========================
def critic_node(state: GraphState) -> GraphState:
    score = random.uniform(0.6, 0.95)

    state.current_score = score  # ✅ 修正字段
    logger.info(
        "critic_node: score=%.4f progress=%s/%s section=%s/%s elapsed=%.2fs",
        score,
        *_progress_args(state),
    )

    return state


#LLM版本---------------------------------------------------------------
def critic_node_llm(state: GraphState) -> GraphState:
    # 拿到最近的一次修改记录
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
        # 执行调用
        result = chain.invoke({
            "before": last_history.before,
            "after": last_history.after
        })
        score = result.score
    except Exception as e:
        logger.error("critic_node 打分失败: %s", e)
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

# =========================
# 5️⃣ Aggregator：更新全文 + best + history
# =========================
def aggregator_node(state: GraphState):
    for section in state.sections:
        section.content = strip_leading_section_command(section.content)
    new_tex = render_sections(state.sections)

    state.current_tex = new_tex

    # ✅ 防崩保护
    if not state.history:
        logger.warning("aggregator_node: history is empty, skipping update")
        return state
    # 🔥 更新“最后一条 history”

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
    previous_score = previous_same_section.score if previous_same_section else 0.0

    if state.current_score > previous_score:
        state.best_score = max(state.best_score, state.current_score)
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


# =========================
# 6️⃣ 切换下一个 section
# =========================
def next_section(state: GraphState) -> GraphState:
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


# =========================
# 7️⃣ 判断是否还有 section
# =========================
def has_more_sections(state: GraphState) -> str:
    state.current_section_index = _next_active_section_index(state, state.current_section_index)
    if state.current_section_index < len(state.sections):
        return "reviewer"
    else:
        return "iteration_step"


# =========================
# 8️⃣ 迭代控制（是否继续循环）
def iteration_step(state: GraphState) -> GraphState:
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
    if state.iteration >= state.max_iterations:
        return "end"
    if state.stop_due_to_no_document_improve:
        return "end"
    if state.current_section_index >= len(state.sections):
        return "end"
    return "reviewer"
