# 这是一个示例 Python 脚本。

# 按 Shift+F10 执行或将其替换为您的代码。
# 按 双击 Shift 在所有地方搜索类、文件、工具窗口、操作和设置。



# 导入类型提示工具：List 表示列表，Optional 表示可选（可以为 None）
from typing import List, Optional

from pydantic import BaseModel, Field


# =========================
# Section：论文分段结构
# =========================
class Section(BaseModel):
    id: str  # 段落唯一标识（用于追踪和修改）
    title: str  # 段落标题（例如 \section{Introduction}）
    content: str  # 段落正文内容
    level: int = 1  # 段落层级（1=section，2=subsection等）


# =========================
# Issue：问题结构（Reviewer输出）
# =========================
class Issue(BaseModel):
    section_id: str  # 问题所属的段落ID（定位问题在哪一段）
    problem: str  # 问题描述（例如“句子不清晰”）
    severity: str  # 问题严重程度（low / medium / high）
    span: Optional[str] = None  # 问题对应的原文片段（用于精确修改，可为空）


# =========================
# HistoryItem：修改历史记录
# =========================
class HistoryItem(BaseModel):
    iteration: int  # 第几轮迭代（第几次优化）
    section_id: str  # 被修改的段落ID
    before: str  # 修改前的文本内容
    after: str  # 修改后的文本内容
    score: float  # 本次修改后的评分
    accepted: bool  # 该修改是否被采纳（是否真的写入最终版本）


# =========================
# GraphState：整个系统的状态中心
# =========================
class GraphState(BaseModel):
    original_tex: str  # 原始输入的 LaTeX 文本（永远不变，用作参考）
    current_tex: str = ""  # 当前版本的 LaTeX 文本（不断被修改）

    sections: List[Section] = Field(default_factory=list)  
    # 分割后的段落列表（系统真正操作的核心数据）

    current_section_index: int = 0  
    # 当前正在处理第几个段落（用于循环处理）

    issues: List[Issue] = Field(default_factory=list)  
    # 当前段落中发现的问题列表（Reviewer输出）

    history: List[HistoryItem] = Field(default_factory=list)  
    # 所有历史修改记录（用于debug、回溯、分析）

    current_score: float = 0.0  
    # 当前版本的评分（由 Critic 给出）

    best_tex: str = ""  
    # 历史最优版本（防止越改越差）

    best_score: float = 0.0  
    # 历史最高评分

    iteration: int = 0  
    # 当前是第几轮全局迭代

    max_iterations: int = 3  
    # 最大允许迭代次数（防止死循环）

    no_improve_rounds: int = 0  
    # 连续多少轮没有提升（用于提前停止）

    max_no_improve: int = 2  
    # 最多允许多少轮无提升（超过就停止）
