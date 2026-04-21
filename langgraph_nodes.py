import logging
import random

from langgraph_state import GraphState, HistoryItem, Issue
from paper_reviewer_tool import split_into_sections

# ===== 需要你已有的定义 =====
# Section, Issue, HistoryItem, GraphState


logger = logging.getLogger(__name__)


# =========================
# 1️⃣ 初始化节点
# =========================
def init_node(state: GraphState) -> GraphState:
    sections = split_into_sections(state.original_tex)

    state.sections = sections
    state.current_tex = state.original_tex

    state.best_tex = state.original_tex
    state.best_score = 0.0

    state.iteration = 0
    state.current_section_index = 0
    state.no_improve_rounds = 0
    logger.info("init_node: initialized sections=%s", len(sections))

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
        "reviewer_node: section_id=%s index=%s issues=%s",
        section.id,
        state.current_section_index,
        len(issues),
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
        "editor_node: section_id=%s issues_applied=%s history_len=%s",
        section.id,
        len(state.issues),
        len(state.history),
    )

    return state


# =========================
# 4️⃣ Critic：打分
# =========================
def critic_node(state: GraphState) -> GraphState:
    score = random.uniform(0.6, 0.95)

    state.current_score = score  # ✅ 修正字段
    logger.info("critic_node: score=%.4f", score)

    return state


# =========================
# 5️⃣ Aggregator：更新全文 + best + history
# =========================
def aggregator_node(state: GraphState):
    new_tex = "\n\n".join([
        f"{sec.title}\n{sec.content}" for sec in state.sections
    ])

    state.current_tex = new_tex

    # ✅ 防崩保护
    if not state.history:
        logger.warning("aggregator_node: history is empty, skipping update")
        return state
    # 🔥 更新“最后一条 history”

    last = state.history[-1]
    last.score = state.current_score

    if state.current_score > state.best_score:
        state.best_score = state.current_score
        state.best_tex = state.current_tex
        last.accepted = True
        state.no_improve_rounds = 0
        logger.info(
            "aggregator_node: accepted iteration=%s section_id=%s best_score=%.4f",
            state.iteration,
            last.section_id,
            state.best_score,
        )
    else:
        last.accepted = False
        state.no_improve_rounds += 1
        logger.info(
            "aggregator_node: rejected iteration=%s section_id=%s no_improve_rounds=%s",
            state.iteration,
            last.section_id,
            state.no_improve_rounds,
        )

    return state


# =========================
# 6️⃣ 切换下一个 section
# =========================
def next_section(state: GraphState) -> GraphState:
    if state.current_section_index < len(state.sections) - 1:
        state.current_section_index += 1
    else:
        state.current_section_index += 1  # 让它越界给判断函数处理
    logger.debug("next_section: current_section_index=%s", state.current_section_index)
    return state


# =========================
# 7️⃣ 判断是否还有 section
# =========================
def has_more_sections(state: GraphState) -> str:
    if state.current_section_index < len(state.sections):
        return "reviewer"
    else:
        return "iteration_step"


# =========================
# 8️⃣ 迭代控制（是否继续循环）
def iteration_step(state: GraphState) -> GraphState:
    # 只负责推进迭代状态
    state.iteration += 1
    state.current_section_index = 0
    logger.info("iteration_step: iteration=%s", state.iteration)
    return state
def route_after_iteration(state: GraphState) -> str:
    # 只负责路由判断，不修改 state
    if state.iteration >= state.max_iterations:
        return "end"
    if state.no_improve_rounds >= state.max_no_improve:
        return "end"
    return "reviewer"