# paper-reviewer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**paper-reviewer** 用于按 LaTeX 中的 **`\section` / `\subsection`** 逐节润色稿件：审稿模型列出问题，编辑模型给出修改后的 LaTeX，评分模型打分，工具仅在**分数优于该节上一次采纳结果**时**采纳**修改，否则对该节**回滚**。

英文说明：**[README.md](README.md)**（与本文结构、命令示例一致）。

---

## 能帮你做什么

- 在本地对接 **Ollama** 或任意 **OpenAI 兼容**接口（自建或云端）。
- 选择 **轻度订正**（`proofread`）或 **幅度更大的重写式润色**（`rewrite`）。
- 可选：在 **`rewrite` 之后自动再接一轮 `proofread`**（同一条命令，模型耗时更多）。
- 得到新的 **`.tex` 文件**，并在 **`logs/`** 下生成**带时间戳的日志**。

---

## 使用前准备

- **Python 3.10+**
- 运行 **`run.py`**：可用的 **OpenAI 兼容**服务（常见为本机 Ollama，`http://127.0.0.1:11434/v1`），以及配置里写的模型。
- 运行 **`run_demo.py`**：无需大模型（Mock 流程）。

---

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

若在 YAML 中设置 **`llm.backend: ollama_native`**，还需：

```bash
python -m pip install langchain-ollama
```

---

## 首次配置

1. 复制示例配置为本地文件（若含密钥请勿提交）：

   ```bash
   copy config\local.example.yaml config\local.yaml   # Windows
   # cp config/local.example.yaml config/local.yaml   # macOS / Linux
   ```

2. 编辑 **`config/local.yaml`**。本机 Ollama 常用 `api_key: ollama`；云端 Key **不要**提交进仓库，可使用 **`config/*.private.yaml`**（见 `.gitignore`）。

3. 默认输入/输出由 `input_path`、`output_path` 指定。仓库自带示例稿 **`sample_manuscript.tex`**；撰写真实论文时请把 `input_path` 指到自己的 `.tex`。

---

## 用示例稿跑一遍

**完整流水线（会调用你配置的模型）：**

```bash
python run.py --input sample_manuscript.tex --output output.tex
```

**偏重写的润色：**

```bash
python run.py --input sample_manuscript.tex --output draft.tex --mode rewrite
```

**不接大模型，体验流程（Mock）：**

```bash
python run_demo.py
```

**查看版本：**

```bash
python run.py --version
```

---

## 使用自己的论文

- 使用命令行 **`--input`**、**`--output`**，或在 `config/local.yaml` 里设置 **`input_path` / `output_path`**。
- 私人手稿勿纳入版本库（需要时把文件名加入 `.gitignore`）。仓库仅附带 **`sample_manuscript.tex`** 作为**演示**；`draft*.tex` 等模式已写入 `.gitignore`，避免误提交本地草稿文件名。

---

## 编辑风格（`mode`）

| 模式 | 说明 |
|------|------|
| **`proofread`**（默认） | 以审稿问题为牵引做**较小、较安全**的修改。 |
| **`rewrite`** | 在单节内可做**更大范围**的句式与衔接调整；**禁止**编造实验/结论，**禁止**破坏 `\cite`、`\ref`、`\label` 与数学环境等。 |

命令行 **`--mode`** 会覆盖当次运行 YAML 中的 `mode`。

---

## 可选：重写后再订正

在 **`--mode rewrite`** 时加上 **`--post-proofread`**（或在 YAML 设 `post_proofread_after_rewrite: true`），会在同一命令内再跑一轮 **`proofread`** 图，**额外消耗**模型时间；第二轮外层迭代上限由 **`post_proofread_max_iterations`** 控制。

---

## 输出在哪里

- **润色后的 TeX：** `--output` 或 `output_path` 指定（常见为 `output.tex`；该文件名默认在 `.gitignore` 中，避免误提交）。
- **日志：** 在 **`log_dir`**（默认 `logs/`），形如 `run_YYYYMMDD_HHMMSS.log`。

若部分模型调用失败，**`run.py` 仍会写出当前 TeX**，但默认以退出码 **`1`** 结束，除非使用 **`--allow-llm-failures`**。

---

## 常用配置项

默认读取 **`config/local.yaml`**，可用 **`--config`** 指定其他路径。

| 配置项 | 含义 |
|--------|------|
| `input_path` / `output_path` | 默认输入、输出 TeX 路径 |
| `mode` | `proofread` 或 `rewrite` |
| `post_proofread_after_rewrite` | 与 `rewrite` 同时为真时，再跑一轮 `proofread`（也可用 `--post-proofread`） |
| `post_proofread_max_iterations` | 第二轮订正的外层迭代上限 |
| `max_iterations` | 整稿外层轮次上限 |
| `max_no_improve` | 单节连续未超过「上次采纳分」时的重试上限，达到后跳过该节 |
| `log_level` / `log_dir` | 日志级别与目录 |
| `ollama_healthcheck` | 为 `true` 时启动前探测 Ollama `GET /api/tags`；非 Ollama 服务请改为 `false` |
| `llm` | `backend`、`base_url`、`api_key`、可选 `request_timeout`、各角色 `model` / `temperature` |

更完整示例见 **`config/local.example.yaml`**。

**优先级：** 命令行可覆盖项 **优于** YAML **优于** 内置默认值。

---

## 常用命令行参数

| 参数 | 含义 |
|------|------|
| `--input` / `--output` | 输入、输出 `.tex` |
| `--config` | YAML 路径（默认 `config/local.yaml`） |
| `--mode` | `proofread` 或 `rewrite` |
| `--post-proofread` | `rewrite` 完成后衔接一轮 `proofread` |
| `--max-iterations` / `--max-no-improve` | 覆盖迭代相关上限 |
| `--log-level` | 如 `INFO`、`DEBUG` |
| `--allow-llm-failures` | 部分 LLM 失败时仍返回退出码 `0` |
| `--version` | 打印版本 |

---

## LLM 后端（简表）

| `llm.backend` | 适用场景 |
|---------------|----------|
| **`openai_compatible`**（默认） | 标准 OpenAI 风格 `/v1`：Ollama、vLLM、多数云 API。 |
| **`ollama_native`** | 需原生参数（如关闭部分 Qwen 的 thinking）；依赖 `langchain-ollama`。 |

---

## 常见问题

| 现象 | 处理建议 |
|------|----------|
| `ModuleNotFoundError` | 在已激活环境中重装 `requirements-lock.txt`；`ollama_native` 需安装 `langchain-ollama`。 |
| 无法连接 Ollama | 确认已 `ollama serve`；`base_url` 可试 `http://127.0.0.1:11434/v1`；非 Ollama 服务请关闭 `ollama_healthcheck`。 |
| 超时或很慢 | 在 YAML 中增大或去掉 `llm.request_timeout`。 |
| 终端里 TeX 被截断 | 完整结果在输出 `.tex` 文件中。 |
| 日志里 Editor JSON 警告 | 过长小节：换更大上下文、更守 JSON 的模型，或拆分章节。 |

---

## 版本

执行 `python run.py --version`，应与 `_version.py` 及 `pyproject.toml` 中版本一致（发版时请同步修改）。
