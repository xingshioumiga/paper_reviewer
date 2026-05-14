# `private/` 本地运行说明 / Local private runner

仓库根目录下的 **`private/`** 由 **`.gitignore`** 中的 **`/private/`** 规则忽略（**仅根目录**，不会误伤 `contrib/private/`）。其中的 `run_my_paper.bat`、`run_config.yaml`、输出文件等 **不会进入 git**。

克隆仓库后若本地没有 `private/`：在仓库根新建文件夹 `private`，从本机备份复制你的 bat/yaml，或参考下方自行创建。

## 文件约定

| 路径 | 作用 |
|------|------|
| `private/run_config.yaml` | `run.py --config` 使用的合并配置（可写绝对路径、密钥） |
| `private/run_my_paper.bat` | 双击运行：切到仓库根并执行 `conda run -n AIagent1 python run.py --config ...` |

## Conda 环境名

默认 bat 使用 **`AIagent1`**。若你的环境名不同，用记事本编辑 `private/run_my_paper.bat` 中的 `conda run -n AIagent1` 一行。

## 与 `config/local.yaml` 的关系

两者独立：`config/local.yaml` 仍供你在 IDE 里直接 `python run.py` 使用；`private/run_config.yaml` 专供双击 bat，避免把私稿路径写进已跟踪的配置文件。

## 双击 bat 失败时常见原因

1. **`llm.backend` 拼写** 必须是 **`ollama_native`**（三个 `o`）。写成 `oollama_native` 等不会走原生路径，也不会关 thinking。
2. **`input_path`** 相对路径是**相对仓库根**（`run.py` 所在目录），不是相对 `private/`。仅写 `my_real_paper.tex` 会在根目录找文件，容易 `FileNotFoundError`。
3. **批处理编码**：含中文的 `.bat` 若以 UTF-8 保存，在简体中文 Windows 上 `cmd` 常按 GBK 解析，会破坏 `if (...)`，出现一堆「不是内部或外部命令」后异常退出。仓库里的 `run_my_paper.bat` 模板改为 **仅 ASCII**；若你自写中文 bat，请用 **ANSI/GBK** 保存或避免中文。
4. **PATH 无 conda**：资源管理器双击时 `conda` 常不在 PATH；bat 会依次尝试常见路径下的 **`Scripts\conda.exe`**（不要用嵌套调用 **`Library\bin\conda.bat`**，否则易出现 **BATCH RECURSION**）。仍失败请用 Anaconda Prompt 或设置 **`CONDA_EXE_PATH`** 指向你的 **`...\Scripts\conda.exe`**。
