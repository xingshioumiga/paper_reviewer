"""Mock LangGraph：Reviewer/Editor/Critic 均为非 LLM 实现，用于快速回归与 e2e。

State graph with mock nodes (no remote LLM); used by ``run_demo.py`` and tests.
"""

from langgraph.graph import END, StateGraph

from langgraph_nodes import (
    aggregator_node,
    critic_node,
    editor_node,
    glossary_node_noop,
    has_more_sections,
    init_node,
    iteration_step,
    next_section,
    reviewer_node,
    route_after_iteration,
)
from langgraph_state import GraphState

# Mock 版图：快速验证流程，不调用真实 LLM / mock graph for fast flow checks without a live LLM.
builder = StateGraph(GraphState)

# 注册节点 / register nodes
builder.add_node("init", init_node)
builder.add_node("glossary", glossary_node_noop)
builder.add_node("reviewer", reviewer_node)
builder.add_node("editor", editor_node)
builder.add_node("critic", critic_node)
builder.add_node("aggregator", aggregator_node)
builder.add_node("next_section", next_section)
builder.add_node("iteration_step", iteration_step)

# 入口 / graph entry
builder.set_entry_point("init")

# 主边：init → reviewer → … / main linear edges
builder.add_edge("init", "glossary")
builder.add_edge("glossary", "reviewer")
builder.add_edge("reviewer", "editor")
builder.add_edge("editor", "critic")
builder.add_edge("critic", "aggregator")
builder.add_edge("aggregator", "next_section")

# 节内循环：逐节处理；已跳过节在路由中前进 / section loop; skipped sections advanced in router.
builder.add_conditional_edges(
    "next_section",
    has_more_sections,
    {
        "glossary": "glossary",
        "iteration_step": "iteration_step"
    }
)

# 外层循环：整轮节遍历结束后再判断是否下一轮 / outer loop after each full pass over sections.
builder.add_conditional_edges(
    "iteration_step",
    route_after_iteration,
    {
        "glossary": "glossary",
        "end": END
    }
)

graph = builder.compile()
