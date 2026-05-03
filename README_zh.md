# paper_reviewer

基于 LangGraph 的 LaTeX 论文「按 `\section` 分段」迭代审稿 / 润色示例：Reviewer → Editor → Critic → 汇总采纳或回滚，可接本机 **Ollama**（OpenAI 兼容 `/v1`）。

**英文说明见 [README.md](README.md)。**

## 环境要求

- **Python 3.10+**
- 跑 **LLM 流水线**（`run.py`）时需本机已安装并启动 [Ollama](https://ollama.com/)，且已拉取配置中的模型（如 `qwen2.5:14b`）。
- **Mock 演示**（`run_demo.py`）不调用 Ollama，用于快速验证状态机与配置。

## 快速开始

1. 创建并激活虚拟环境（conda / venv 均可）。
2. 安装依赖（二选一）：
   - **推荐（版本锁定）：** `python -m pip install -r requirements-lock.txt`
   - **宽松（仅包名）：** `python -m pip install -r requirements.txt`
3. 运行方式：
   - **Mock 图（无 LLM）：** `python run_demo.py`
   - **真实 LLM（Ollama）：** `python run.py --input sample_manuscript.tex --output output.tex`

查看版本：`python run.py --version`

## 配置文件

- 默认读取 **`config/local.yaml`**（可用 `--config` 指定其他路径）。
- **`config/local.example.yaml`** 为字段说明与示例；可复制为 `local.yaml` 再改。
- 本机只用 Ollama 时保持 `api_key: ollama` 即可。**不要**把云端真实 API Key 提交进仓库；敏感项可放在 **`config/*.private.yaml`**（已在 `.gitignore` 中忽略）。
- 若系统开启**全局代理**导致访问 `localhost` 出现 **502**，建议将 `llm.base_url` 写为 `http://127.0.0.1:11434/v1`，或为本地地址配置代理例外。

### 常用配置项

| 项 | 含义 |
|----|------|
| `input_path` / `output_path` | 默认输入 / 输出 TeX 路径 |
| `max_iterations` | 外层「整稿轮次」上限 |
| `max_no_improve` | 单段连续「分数未超过历史最优」次数上限，达到后可跳过该段 |
| `log_level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `log_dir` | 日志目录（默认 `logs`，文件名带时间戳） |
| `ollama_healthcheck` | 为 `true` 时，`run.py` 启动前会请求 `{base_url 对应主机}/api/tags`；非 Ollama 端点可改为 `false` |
| `llm.base_url` / `llm.api_key` | OpenAI 兼容基址与密钥（Ollama 占位即可） |
| `llm.request_timeout` | 可选，正数秒；不设则不在配置层限制单次请求读超时 |
| `llm.reviewer` / `editor` / `critic` | 各角色 `model`、`temperature` |

**CLI 覆盖 YAML：** 命令行传入的 `--input`、`--output`、`--max-iterations`、`--max-no-improve`、`--log-level` 会覆盖配置文件中对应项。

### LLM 失败与退出码

当任意 **Reviewer / Editor / Critic** 的 LLM 调用抛错时，会累计 `llm_failure_count`。`run.py` 在**仍会写出当前输出 TeX**的前提下，默认以**退出码 1**结束，避免脚本把「带病输出」当成成功。查看 `logs/` 中带 `ERROR` 的行定位原因。

若你希望无论 LLM 是否失败都返回退出码 0，可加：`--allow-llm-failures`。

## 迭代语义（简述）

图按文档顺序处理每个解析出的 `\section{...}`，再进入下一轮外层迭代。每次改写后由 Critic 打分，**聚合器**将该分与该段「上次已采纳分」比较：

- 新分 **更高** → 采纳并写入历史；
- 否则 → 回滚该段到上次采纳内容；
- 若该段尚无已采纳分，基线为 `0.0`。

每段采纳分记在 `HistoryItem` 上；运行结束会打印 / 记录 **各段最新已采纳分**（从未采纳则为 `0.0`）。**不使用**单一全局「best score」数字，以免跨段混用产生误导。

## 日志

每次运行同时写控制台与 `log_dir` 下文件，形如 `logs/run_<时间戳>.log`。日志中可见分段数、各段审稿/改写步骤、打分与采纳/回滚等。若见 `openai._base_client` 频繁 `Retrying request`，可检查 YAML 中 `request_timeout` 是否过小导致本地大模型被提前切断。

## 在 Cursor / VS Code 中调试

仓库含 `.vscode/launch.json`、`.vscode/tasks.json`：可在「运行和调试」中选择 **Run Demo** 等配置（名称若与你的 conda 环境不一致，可在 JSON 中改成你的解释器路径）。

## 测试与质量

```bash
python -m pytest -q
python -m ruff check .
```

测试覆盖：TeX 分段解析、路由与停止条件、Mock 图端到端、`run.py` 在 LLM 失败计数下的退出码行为等。

## 新手向中文说明

更偏「为什么要测、怎么测」的说明见 **`TESTING_GUIDE_ZH.md`**。

## 常见问题

- **`ModuleNotFoundError`**：在已激活的环境中执行 `pip install -r requirements-lock.txt`（或 `requirements.txt`）。
- **代理导致本机 Ollama 502**：关闭全局代理或改用 `127.0.0.1`，见上文「配置文件」。
- **没有输出文件**：检查 `--input` 路径是否存在、是否有写权限。
- **终端里输出被截断**：完整结果在输出 TeX 文件中；终端仅预览前若干字符。
- **需要更细日志**：`--log-level DEBUG` 并打开 `logs/` 下最新文件。

## 版本

版本号见 `python run.py --version`，并与 `pyproject.toml` 中 `[project].version`、`_version.py` 保持一致（发版时同步修改）。
