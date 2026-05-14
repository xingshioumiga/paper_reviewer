"""LLM LangGraph：审稿/改写/打分为 ``langgraph_nodes`` 的 ``*_llm`` 节点（如 Ollama）。

Production-style graph; call ``init_llms_from_config`` before first ``graph.invoke`` (see ``run.py``).
"""

from langgraph.graph import END, StateGraph

from langgraph_nodes import (
    aggregator_node,
    critic_node_llm,
    editor_node_llm,
    glossary_node_llm,
    has_more_sections,
    init_node,
    iteration_step,
    next_section,
    reviewer_node_llm,
    route_after_iteration,
)

from langgraph_state import GraphState


# LLM 版图：Reviewer / Editor / Critic 均调用配置的模型 / LLM graph: all three roles call the configured model.
builder = StateGraph(GraphState)

# 注册节点（LLM）/ register LLM nodes
builder.add_node("init", init_node)
builder.add_node("glossary", glossary_node_llm)
builder.add_node("reviewer", reviewer_node_llm)
builder.add_node("editor", editor_node_llm)
builder.add_node("critic", critic_node_llm)
builder.add_node("aggregator", aggregator_node)
builder.add_node("next_section", next_section)
builder.add_node("iteration_step", iteration_step)

# 入口 / graph entry
builder.set_entry_point("init")

# 主边 / main linear edges
builder.add_edge("init", "glossary")
builder.add_edge("glossary", "reviewer")
builder.add_edge("reviewer", "editor")
builder.add_edge("editor", "critic")
builder.add_edge("critic", "aggregator")
builder.add_edge("aggregator", "next_section")

# 节内循环：逐节；达无提升上限的节会被跳过 / section loop; sections may be skipped after no-improve cap.
builder.add_conditional_edges(
    "next_section",
    has_more_sections,
    {
        "glossary": "glossary",
        "iteration_step": "iteration_step"
    }
)

# 外层循环：整轮结束后按最大轮次与是否改进决定是否继续 / outer loop: stop or continue by max rounds and improvement.
builder.add_conditional_edges(
    "iteration_step",
    route_after_iteration,
    {
        "glossary": "glossary",
        "end": END
    }
)

graph = builder.compile()
