from pydantic import BaseModel, Field


class Section(BaseModel):
    """论文中的一个可独立评审和修改的 section。"""

    id: str
    title: str
    content: str
    level: int = 1


class Issue(BaseModel):
    """Reviewer 给出的单个问题，用 section_id 绑定到具体段落。"""

    section_id: str
    problem: str
    severity: str
    span: str | None = None


class HistoryItem(BaseModel):
    """记录一次 section 修改尝试，包含修改前后文本、评分和是否采纳。"""

    iteration: int
    section_id: str
    before: str
    after: str
    score: float
    accepted: bool


class GraphState(BaseModel):
    """LangGraph 在各节点之间传递的全局状态。"""

    original_tex: str
    current_tex: str = ""
    run_started_at: float = 0.0

    sections: list[Section] = Field(default_factory=list)
    current_section_index: int = 0

    issues: list[Issue] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)

    current_score: float = 0.0
    best_tex: str = ""
    best_score: float = 0.0

    iteration: int = 0
    max_iterations: int = 3

    # section_no_improve_rounds 是 section 级失败计数，避免局部失败污染全局停止条件。
    section_no_improve_rounds: dict[str, int] = Field(default_factory=dict)
    skipped_section_ids: list[str] = Field(default_factory=list)

    # iteration_accepted_count 统计当前大循环中被采纳的修改数。
    # 如果一整轮结束后仍为 0，说明全文没有任何进步，可以提前停止。
    iteration_accepted_count: int = 0
    stop_due_to_no_document_improve: bool = False

    max_no_improve: int = 2
