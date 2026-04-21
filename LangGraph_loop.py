from langgraph.graph import StateGraph
from langgraph_state import GraphState
from langgraph_nodes import (
    init_node,
    reviewer_node,
    editor_node,
    critic_node,
    aggregator_node,
    next_section,
    has_more_sections,
    iteration_step,
    route_after_iteration,
)
from langgraph.graph import END

builder = StateGraph(GraphState)

# 注册节点
builder.add_node("init", init_node)
builder.add_node("reviewer", reviewer_node)
builder.add_node("editor", editor_node)
builder.add_node("critic", critic_node)
builder.add_node("aggregator", aggregator_node)
builder.add_node("next_section", next_section)
builder.add_node("iteration_step", iteration_step)

# 入口
builder.set_entry_point("init")

# 主流程
builder.add_edge("init", "reviewer")
builder.add_edge("reviewer", "editor")
builder.add_edge("editor", "critic")
builder.add_edge("critic", "aggregator")
builder.add_edge("aggregator", "next_section")

# section loop
builder.add_conditional_edges(
    "next_section",
    has_more_sections,
    {
        "reviewer": "reviewer",
        "iteration_step": "iteration_step"
    }
)

# iteration loop
builder.add_conditional_edges(
    "iteration_step",
    route_after_iteration,
    {
        "reviewer": "reviewer",
        "end": END
    }
)

graph = builder.compile()