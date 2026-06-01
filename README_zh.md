# paper-reviewer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**paper-reviewer** 是基于 **LangGraph** 的 **LaTeX** 润色流水线：按 `\section` / `\subsection` 推进，审稿模型列问题，编辑模型给出修改稿，评分模型打分；**仅当分数优于该节上次采纳结果时采纳**，否则对该节**回滚**。

英文说明：**[README.md](README.md)**（与本文结构、命令一致）。

> **目录说明：** 可提交的示例与文档在 **`examples/`**、**`docs/`**、**`templates/`**（原 `contrib/`）。仅本机运行文件放在 gitignore 的仓库根 **`private/`**。

## 目录约定

| 路径 | 用途 |
|------|------|
| **`private/`** | 不进 Git：bat、`run_config.yaml`、术语表、输出等 |
| **`examples/`** | 可提交模板（[索引](examples/README.md)），复制到 `private/` |
| **`templates/`** | 编辑器模板（如 `templates/vscode/`） |
| **`docs/`** | 使用说明（[索引](docs/README.md)，如 [web-ui.md](docs/web-ui.md)、[local-runner.md](docs/local-runner.md)） |

## 0.4.0 大更新摘要

- **术语表 Glossary（内置默认开启）：** 每个 `\section` 在审稿前可增加一步 **glossary**，把缩写抽成合并表（**`locked`** 来自 `private/glossary.seed.yaml`，**`provisional`** 由模型增量写入）。同一张表会注入 **reviewer / editor / critic** 的提示，减少前后文乱改缩写。仅在**外层第 0 轮**、**每节各抽一次**。若不想多耗 LLM，在 YAML 设 **`glossary.enabled: false`**。实现见 [`glossary_merge.py`](glossary_merge.py)、**[docs/local-runner.md](docs/local-runner.md)**、[`config/local.example.yaml`](config/local.example.yaml)。
- **Ollama 稳定性：** 对断流、**502/503/504** 等传输错误做**有限次重试**；仍可调 **`num_predict`**、JSON 解析重试等应对长节。
- **私稿运行说明：** **[docs/local-runner.md](docs/local-runner.md)** 补充 bat 编码、conda 路径、长文 Ollama 报错处理等。

## 能做什么

- 对接本机或远端的 **OpenAI 兼容**接口（如 Ollama），或选用 **ollama_native** 走原生参数。
- **`proofread`**：以审稿问题为牵引的**轻量、安全**修改；**`rewrite`**：单节内更大范围润色，**不编造结论**、**不破坏**引用、标签、交叉引用与数学环境。
- 可选：**`rewrite` 后再跑一轮 `proofread`**（同一条命令）。
- 生成新的 **`.tex`**，并在默认 **`logs/`** 下写**带时间戳日志**。
- **Glossary（开启时）：** 人工 **`locked`** + 模型 **`provisional`** 合并，并注入后续提示。

## 环境要求

- **Python 3.10+**
- 跑 **`run.py`**：可访问的 LLM 与配置中的模型名。
- 跑 **`run_demo.py`**：无需网络（Mock）。

## 安装

```bash
git clone <your-repository-url>
cd paper_reviewer
python -m venv .venv
```

**Windows（PowerShell）：** `.\.venv\Scripts\Activate.ps1`  
**macOS / Linux：** `source .venv/bin/activate`

```bash
python -m pip install -r requirements-lock.txt
```

（也可：`python -m pip install -r requirements.txt`。）

若 YAML 中设置 **`llm.backend: ollama_native`**：

```bash
python -m pip install langchain-ollama
```

### Conda（可选）

仓库提供 **`environment.yml`**（仅**环境名**与依赖列表，不含本机路径）：

```bash
conda env create -f environment.yml
conda activate <environment.yml 中的 name>
```

更新依赖：`conda env update -f environment.yml`。在 **Windows** 上可不先激活，直接：**`.\scripts\conda_run.ps1 python -m pytest tests/ -q`**。编辑器任务模板见 **`templates/vscode/`**（复制到本地 `.vscode/`，说明见 **`templates/vscode/README.md`**）。

## 首次配置

1. 复制示例为本地文件（含密钥时**勿提交**）：

   ```bash
   copy config\local.example.yaml config\local.yaml   # Windows
   # cp config/local.example.yaml config/local.yaml   # macOS / Linux
   ```

2. 编辑 **`config/local.yaml`**。本机 Ollama 常用 `api_key: ollama`；云端 Key 请放 **`config/*.private.yaml`**（见 `.gitignore`），不要写进会被提交的仓库文件。

3. 配置 **`input_path` / `output_path`**，或使用命令行 **`--input` / `--output`**。示例稿为 **`sample_manuscript.tex`**。

4. **Glossary（内置配置默认 `enabled: true`）：** 文件在 **`private/`**（gitignore）。可将 **[examples/glossary.seed.example.yaml](examples/glossary.seed.example.yaml)** 复制为 **`private/glossary.seed.yaml`** 填写 **`locked:`**；**`private/glossary.merged.yaml`** 在 **`persist_merged_after_merge: true`** 时会更新。不需要术语表时在 YAML 设 **`glossary.enabled: false`**。

## 运行示例

**完整流水线（会调用模型）：**

```bash
python run.py --input sample_manuscript.tex --output output.tex
```

**偏重写的润色：**

```bash
python run.py --input sample_manuscript.tex --output draft.tex --mode rewrite
```

**不接大模型（Mock）：**

```bash
python run_demo.py
```

**查看版本：**

```bash
python run.py --version
```

## 图形界面（本机 Web）

安装 Web 依赖后启动暗色控制台（默认 **http://127.0.0.1:7860/**）：

```bash
python -m pip install fastapi "uvicorn[standard]"
python web_app.py
```

在页面里填写路径、选择模式并点击「开始润色」；可实时看日志、预览输出与术语表。详见 **[docs/web-ui.md](docs/web-ui.md)**。

## 自己的论文与私稿目录

- 使用 **`--input` / `--output`** 或 YAML 中的路径字段。
- **Windows 双击：** 在仓库根使用 **`private/`**（由 **`.gitignore`** 中 **`/private/`** 忽略）。从 **`examples/`** 复制 `run_config.example.yaml`、`run_my_paper.bat.example` 到 **`private/`**；**`input_path` 相对路径以仓库根为基准**（不是相对 `private/`）。详见 **[docs/local-runner.md](docs/local-runner.md)**（编码、`conda.exe` 与 **`CONDA_EXE_PATH`** 等）。
- 本地私稿请在 **`.gitignore`** 中增加规则，避免误提交。

## 编辑风格（`mode`）

| 模式 | 说明 |
|------|------|
| **`proofread`**（默认） | 较小幅度、以审稿问题为导向的修改。 |
| **`rewrite`** | 单节内更大范围句式与衔接调整；遵守引用与结构约束。 |

命令行 **`--mode`** 覆盖当次 YAML 中的 `mode`。

## 可选：重写后再订正

**`--mode rewrite`** 时加 **`--post-proofread`**（或 YAML 中 `post_proofread_after_rewrite: true`），会在同一命令内再跑 **`proofread`**；耗时更多，第二轮外层迭代上限为 **`post_proofread_max_iterations`**。

## 输出位置

- **TeX：** **`--output`** 或 **`output_path`**（如 `output.tex`；该文件名默认在 `.gitignore` 中）。
- **日志：** **`log_dir`**（默认 `logs/`），如 `run_YYYYMMDD_HHMMSS.log`。

部分 LLM 失败时，**`run.py` 仍会写出当前 TeX**，默认退出码 **`1`**，除非使用 **`--allow-llm-failures`**。

## 常用配置项

默认 **`config/local.yaml`**，可用 **`--config`** 指定其他文件。

| 配置项 | 含义 |
|--------|------|
| `input_path` / `output_path` | 默认输入、输出 TeX |
| `mode` | `proofread` 或 `rewrite` |
| `post_proofread_after_rewrite` | 与 `rewrite` 同时为真时再跑 `proofread`（也可用 `--post-proofread`） |
| `post_proofread_max_iterations` | 第二轮订正的外层迭代上限 |
| `max_iterations` | 整稿外层轮次上限 |
| `max_no_improve` | 单节未超过上次采纳分时的重试上限 |
| `log_level` / `log_dir` | 日志级别与目录 |
| `ollama_healthcheck` | 为 `true` 时启动前请求 Ollama `GET /api/tags` |
| `glossary` | `enabled`、`seed_path`、`merged_path`、`bootstrap_provisional_from_merged`、`persist_merged_after_merge`（见示例 YAML） |
| `llm` | `backend`、`base_url`、`api_key`、可选 `request_timeout`、各角色 `model` / `temperature`，可选嵌套 **`glossary`**（`model`、`temperature`）专用于抽取步，以及生成与解析重试等（见示例 YAML） |

更完整示例见 **`config/local.example.yaml`**。**优先级：** 命令行（支持的项）> YAML > 内置默认值。

**LLM 图顺序：** `init` → **`glossary`** → `reviewer` → `editor` → `critic` → `aggregator` → …

## 常用命令行参数

| 参数 | 含义 |
|------|------|
| `--input` / `--output` | 输入、输出 `.tex` |
| `--config` | YAML 路径（默认 `config/local.yaml`） |
| `--mode` | `proofread` 或 `rewrite` |
| `--post-proofread` | `rewrite` 后衔接 `proofread` |
| `--max-iterations` / `--max-no-improve` | 覆盖迭代上限 |
| `--log-level` | 如 `INFO`、`DEBUG` |
| `--allow-llm-failures` | 部分 LLM 失败仍返回退出码 `0` |
| `--version` | 打印版本 |

## LLM 后端

| `llm.backend` | 适用场景 |
|---------------|----------|
| **`openai_compatible`**（默认） | 标准 OpenAI 风格 `/v1`：Ollama、vLLM、多数云 API。 |
| **`ollama_native`** | 需要原生 Ollama 参数（如关闭部分模型的 thinking）；需安装 `langchain-ollama`。 |

**Ollama 与结构化输出：** 默认支持配置 **`num_predict`**（生成长度上限）及对结构化链路的 **JSON 解析重试**；**editor** 角色可使用更高的重试上限。若某节仍解析失败，该节可能被**跳过**并记日志；可尝试换模型、加大上下文、调整 **`num_predict`** 或拆分过长小节—详见 **`config/local.example.yaml`** 与运行日志。

## 常见问题

| 现象 | 处理建议 |
|------|----------|
| `ModuleNotFoundError` | 重装 `requirements-lock.txt`；`ollama_native` 需 `langchain-ollama`。 |
| 连不上 Ollama | 确认 `ollama serve`；`base_url` 可试 `http://127.0.0.1:11434/v1`；非 Ollama 服务请关 `ollama_healthcheck`。 |
| 很慢 / 超时 | 调整或去掉 `llm.request_timeout`；若 JSON 被截断可增大 `num_predict`。 |
| 终端里 TeX 显示不全 | 以输出 `.tex` 文件为准。 |
| Editor JSON / 某节被跳过 | 缩短小节、换更守 JSON 的模型、调大 `num_predict` 或重试相关配置。 |
| Windows bat / conda 异常 | 见 **[docs/local-runner.md](docs/local-runner.md)**。 |

## 开发

```bash
python -m pytest tests/ -q
```

## 版本

当前发布版本：**0.4.0**。执行 `python run.py --version`，应与 **`_version.py`**、**`pyproject.toml`** 一致。
