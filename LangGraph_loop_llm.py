"""LLM LangGraph：审稿/改写/打分为 ``langgraph_nodes`` 的 ``*_llm`` 节点（如 Ollama）。

Production-style graph; call ``init_llms_from_config`` before first ``graph.invoke`` (see ``run.py``).
"""

from langgraph.graph import END, StateGraph

from langgraph_nodes import (
    aggregator_node,
    critic_node_llm,     # ✅ LLM版本
    editor_node_llm,     # ✅ LLM版本
    has_more_sections,
    init_node,
    iteration_step,
    next_section,
    reviewer_node_llm,   # ✅ LLM版本
    route_after_iteration,
)

from langgraph_state import GraphState


# LLM 版本图：Reviewer / Editor / Critic 都调用本地 Ollama 兼容接口。
builder = StateGraph(GraphState)

# =========================
# ✅ 注册节点（LLM版本）
# =========================
builder.add_node("init", init_node)
builder.add_node("reviewer", reviewer_node_llm)
builder.add_node("editor", editor_node_llm)
builder.add_node("critic", critic_node_llm)
builder.add_node("aggregator", aggregator_node)
builder.add_node("next_section", next_section)
builder.add_node("iteration_step", iteration_step)

# =========================
# ✅ 入口
# =========================
builder.set_entry_point("init")

# =========================
# ✅ 主流程
# =========================
builder.add_edge("init", "reviewer")
builder.add_edge("reviewer", "editor")
builder.add_edge("editor", "critic")
builder.add_edge("critic", "aggregator")
builder.add_edge("aggregator", "next_section")

# section loop：按 section 逐个处理；达到 section 级无提升上限的段落会被跳过。
builder.add_conditional_edges(
    "next_section",
    has_more_sections,
    {
        "reviewer": "reviewer",
        "iteration_step": "iteration_step"
    }
)

# iteration loop：整轮结束后，根据最大迭代数和全文是否改进决定是否继续。
builder.add_conditional_edges(
    "iteration_step",
    route_after_iteration,
    {
        "reviewer": "reviewer",
        "end": END
    }
)

# =========================
# 🚀 编译 graph
# =========================
graph = builder.compile()
