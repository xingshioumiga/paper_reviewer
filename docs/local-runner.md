# `private/` 本地运行说明 / Local private runner

仓库根目录下的 **`private/`** 由 **`.gitignore`** 中的 **`/private/`** 规则忽略（**仅根目录**）。其中的 `run_my_paper.bat`、`run_config.yaml`、输出文件等 **不会进入 git**。

克隆仓库后若本地没有 `private/`：在仓库根新建文件夹 `private`，从本机备份复制你的 bat/yaml，或从 **[examples/](../examples/)** 复制模板（见下方）。

## 文件约定

| 路径 | 作用 |
|------|------|
| `private/run_config.yaml` | `run.py --config` 使用的合并配置（可写绝对路径、密钥） |
| `private/run_my_paper.bat` | 双击运行：切到仓库根并执行 `conda run -n AIagent1 python run.py --config ...` |

模板（进 Git）：**[examples/run_config.example.yaml](../examples/run_config.example.yaml)**、**[examples/run_my_paper.bat.example](../examples/run_my_paper.bat.example)**。

## Conda 环境名

默认 bat 使用 **`AIagent1`**。若你的环境名不同，用记事本编辑 `private/run_my_paper.bat` 中的 `conda run -n AIagent1` 一行。

## 与 `config/local.yaml` 的关系

两者独立：`config/local.yaml` 仍供你在 IDE 里直接 `python run.py` 使用；`private/run_config.yaml` 专供双击 bat，避免把私稿路径写进已跟踪的配置文件。

## 双击 bat 失败时常见原因

1. **`llm.backend` 拼写** 必须是 **`ollama_native`**（三个 `o`）。写成 `oollama_native` 等不会走原生路径，也不会关 thinking。
2. **`input_path`** 相对路径是**相对仓库根**（`run.py` 所在目录），不是相对 `private/`。仅写 `my_real_paper.tex` 会在根目录找文件，容易 `FileNotFoundError`。
3. **批处理编码**：含中文的 `.bat` 若以 UTF-8 保存，在简体中文 Windows 上 `cmd` 常按 GBK 解析，会破坏 `if (...)`，出现一堆「不是内部或外部命令」后异常退出。仓库里的 `run_my_paper.bat` 模板改为 **仅 ASCII**；若你自写中文 bat，请用 **ANSI/GBK** 保存或避免中文。
4. **PATH 无 conda**：资源管理器双击时 `conda` 常不在 PATH；bat 会依次尝试常见路径下的 **`Scripts\conda.exe`**（不要用嵌套调用 **`Library\bin\conda.bat`**，否则易出现 **BATCH RECURSION**）。仍失败请用 Anaconda Prompt 或设置 **`CONDA_EXE_PATH`** 指向你的 **`...\Scripts\conda.exe`**。

## 术语表（Glossary）

用于在长稿分块润色时**锁定缩写与专有名词**（避免模型前后解释不一致）。模板见 **[examples/glossary.seed.example.yaml](../examples/glossary.seed.example.yaml)**。

| 路径（均在仓库根 `private/`，不进 git） | 作用 |
|------|------|
| `private/glossary.seed.yaml` | 人工维护的 **`locked:`** 缩写 → 英文释义 |
| `private/glossary.merged.yaml` | 运行中合并结果（含 locked 快照 + 模型 **`provisional`** 增量） |

在 **`config/local.yaml`**（或你的 `run_config.yaml`）里配置（**内置默认 `glossary.enabled` 已为 `true`**。若要关闭术语抽取以省 LLM，设 `enabled: false`）：

```yaml
glossary:
  enabled: true
  seed_path: private/glossary.seed.yaml
  merged_path: private/glossary.merged.yaml
  bootstrap_provisional_from_merged: true   # 启动时读回上次 provisional
  persist_merged_after_merge: true            # 每节抽取后写回 merged 文件
```

行为概要：**仅外层 `iteration == 0` 时**对每个 `\section` 调一次术语抽取；后续外层轮次只复用内存中的表。`locked` 永不被模型覆盖。详见仓库内 `glossary_merge.py` 与 `langgraph_nodes.glossary_node_llm`。

## Ollama 长稿报错（与 bat 无关）

若日志或窗口里出现 **`peer closed connection without sending complete message body`**、**`502 Bad Gateway`**，通常是 **单次 `generate` 时间过长 / 输出过大**，Ollama 或中间代理把连接掐断，随后服务短暂不可用。

建议：

1. **重启 Ollama**（`ollama serve` 或托盘退出再开），再双击 bat。
2. 在 `run_config.yaml` 的 `llm` 下适当 **增大 `num_predict`**（编辑器 JSON 更长时）或 **略减小** 以缩短单次生成（需自行试）。
3. 可加 **`llm.request_timeout: 900`**（秒）避免客户端过早放弃（不能修复服务端主动断流，但可缓解 ReadTimeout）。
4. 减轻负载：先 **`max_iterations: 1`** 试跑；或暂时关掉 **`post_proofread_after_rewrite`**；或换更小模型试通流程。
5. 程序已对 **可恢复的断连 / 502** 在 **单次调用内自动重试最多 3 次**（指数退避）；仍失败请看 `logs/run_*.log` 末尾 `ERROR`。

若 bat 阶段就失败（未出现 `run start` 日志），多为 **`conda.exe` 找不到** 或 **没有名为 `AIagent1` 的环境**：请设置 bat 内注释的 **`CONDA_EXE_PATH`**，或把 conda 的 `Scripts` 加入 PATH，或用 Anaconda Prompt 手动 `conda run -n <你的环境名> python run.py --config private/run_config.yaml`。
