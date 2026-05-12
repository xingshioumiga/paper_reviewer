"""Shared Pydantic models for LangGraph state (sections, issues, history).

LangGraph 使用的状态模型：段落、审稿问题、修改历史等。
"""

from pydantic import BaseModel, Field


class Section(BaseModel):
    """LaTeX 中按 \\section 切分的一块；可单独评审与改写。
    One slice of the manuscript split by ``\\section``; reviewed/edited independently."""

    id: str
    title: str
    content: str
    level: int = 1


class Issue(BaseModel):
    """审稿人发现的单个问题；通过 section_id 绑定到段落。
    Single reviewer finding; tied to a section via ``section_id``."""

    section_id: str
    problem: str
    severity: str
    span: str | None = None


class HistoryItem(BaseModel):
    """一次针对某段的改写尝试：前后文本、critic 分数、是否采纳。
    One edit attempt for a section: before/after text, critic score, accepted flag."""

    iteration: int
    section_id: str
    before: str
    after: str
    score: float
    accepted: bool


class GraphState(BaseModel):
    """LangGraph 节点间传递的全局状态（当前稿、段落列表、历史与停止条件）。
    Global graph state: current draft, sections list, history, and stop flags."""

    original_tex: str
    # proofread | rewrite — selects system prompts for this run only (see prompt_modes).
    edit_mode: str = "proofread"
    current_tex: str = ""
    run_started_at: float = 0.0

    sections: list[Section] = Field(default_factory=list)
    current_section_index: int = 0

    issues: list[Issue] = Field(default_factory=list)
    history: list[HistoryItem] = Field(default_factory=list)

    current_score: float = 0.0  # 本轮 critic 对「最后一次改写」的打分 / Latest critic score for last edit
    best_tex: str = ""  # 最近一次「采纳」后的全文 LaTeX 快照 / Full-doc snapshot after last accept

    iteration: int = 0  # 已完成的外层轮次数（iteration_step 末尾递增）/ Finished outer rounds
    max_iterations: int = 3  # 外层循环上限 / Cap on outer iterations

    # 每段连续「未超过历史最优」的次数；达 max_no_improve 则跳过该段。
    # Per-section streak of non-improving tries; section is skipped when ≥ max_no_improve.
    section_no_improve_rounds: dict[str, int] = Field(default_factory=dict)
    skipped_section_ids: list[str] = Field(default_factory=list)  # 已标记跳过的 section id / Skipped section ids

    # 当前这一轮 scan 中被采纳的修改次数；轮末若为 0 则触发提前结束。
    # Accepted edits in the current full pass over sections; 0 → early stop next route.
    iteration_accepted_count: int = 0
    stop_due_to_no_document_improve: bool = False  # 上一轮无任何采纳 / No accept in previous round

    max_no_improve: int = 2  # 每段允许连续无提升的最大次数 / Max consecutive no-improve per section

    # 本 run 内 LLM 节点失败次数；run.py 据此非零退出，避免静默假成功。
    # LLM node failure count; run.py uses this for non-zero exit (no silent false success).
    llm_failure_count: int = 0
