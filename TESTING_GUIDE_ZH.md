# 小白版测试使用手册

这份手册的目标是：让你不需要测试基础，也能知道“为什么要测、怎么测、怎么看结果”。

## 1. 先理解：测试文件到底是什么

`tests/test_reviewer_core.py` 不是业务功能文件，它是“检查业务功能是否正确”的文件。

- 业务代码做事：例如 `run_demo.py` 负责运行 reviewer 流程。
- 测试代码验收：例如测试 `split_into_sections` 是否真的按预期分段。

你可以把它理解成：

- `run_demo.py` = 做菜
- `tests/test_reviewer_core.py` = 质检单

## 2. 为什么“只有函数定义”的文件也能运行成测试

这是因为你并不是用 `python tests/test_reviewer_core.py` 来运行它，而是用测试框架 `pytest`。

`pytest` 的工作原理（简化版）：

1. 扫描项目目录（默认会看 `tests/`）
2. 找文件名匹配 `test_*.py`
3. 在这些文件里找函数名匹配 `test_*`
4. 自动调用这些函数执行
5. 根据函数里 `assert` 的结果判断通过或失败

所以测试文件里“只有函数”完全正常。它们会被 `pytest` 作为入口自动调用。

## 3. 你项目里的三个测试在测什么

### 3.1 分段解析测试

`test_split_into_sections_parses_three_sections`

- 作用：验证 LaTeX 输入会被正确拆成 section 列表。
- 原理：准备固定输入，调用 `split_into_sections`，用 `assert` 检查输出数量和内容。

### 3.2 路由判断测试

`test_routing_logic_covers_continue_and_end`

- 作用：验证状态机“下一步走哪里”是正确的。
- 原理：手工构造不同的 `GraphState`，调用路由函数并断言返回值（`reviewer` / `iteration_step` / `end`）。

### 3.3 端到端最小流程测试

`test_graph_invoke_generates_history`

- 作用：验证整条 LangGraph 流程能跑通，并产出关键状态。
- 原理：
  - 用 `monkeypatch` 固定随机评分为常数，避免结果每次不一样。
  - 调用 `graph.invoke`。
  - 检查迭代次数、history 是否生成、`section_score_summary` 中是否有合理分数。

## 4. 你平时怎么用（最简单操作）

### 方式 A：命令行

在项目根目录运行：

`python -m pytest -q`

你会看到类似：

- `3 passed`：全部通过
- `1 failed`：有一个测试失败，需要修复代码

### 方式 B：一键任务（推荐）

你已经有 `/.vscode/tasks.json`，可直接运行任务：

- `Run Tests`

### 方式 C：调试测试

你已经有 `/.vscode/launch.json`，可直接启动：

- `Run Pytest`

## 5. 测试通过和 demo 运行通过，有什么区别

- `run_demo.py` 通过：说明“这次”主流程能跑
- `pytest` 通过：说明核心逻辑在多个断言点都符合预期

工程实践里这两个都要有：

- demo 像人工验收
- pytest 像自动化回归检查

## 6. 常见问题（小白高频）

### Q1: 为什么我改了代码，测试反而失败？

因为测试就是用来发现“改动是否破坏原行为”的。失败不是坏事，是提前发现问题。

### Q2: 我要不要每次都跑测试？

建议至少在这三个时机跑：

1. 改完核心逻辑后
2. 提交 git 之前
3. 准备给别人演示之前

### Q3: 测试失败先看哪？

先看失败函数名，再看断言报错信息，通常就能定位到具体模块。

### Q4: ``run.py`` 为什么有时退出码是 1？

当流水线里任意一次 LLM 调用（审稿 / 改写 / 打分）抛错时，状态里会累计 ``llm_failure_count``。跑完后若该计数大于 0，``run.py`` 默认 **以退出码 1 结束**（即使已经写入了输出 TeX），避免脚本把「带病输出」当成成功。需要旧行为时在命令行加上 ``--allow-llm-failures``。

## 7. 一句话总结

`tests/test_reviewer_core.py` 虽然只是函数定义，但在 `pytest` 规则下，它们会被自动发现并执行，因此可以成为标准测试入口。
