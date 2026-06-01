# VS Code / Cursor 调试配置示例 / Sample VS Code launch & tasks

仓库根目录的 **`.vscode/`** 仍建议 **不提交**（已在 `.gitignore`），以免误把本机绝对路径写进 git。  
本目录提供 **可复制** 的 `*.json`：**只使用 conda 环境名 `AIagent1`**，不包含磁盘路径。

The repo root **`.vscode/`** stays **gitignored** so local paths are not committed.  
These portable JSON files use **only** the conda env name **`AIagent1`** (no drive letters or usernames).

---

## 1. Conda 环境 / Conda environment

使用仓库根目录的 **`environment.yml`**（`name: AIagent1`）创建或更新环境：

```bash
conda env create -f environment.yml
# 若已存在同名环境：
conda env update -f environment.yml
conda activate AIagent1
```

若你本地已有别的用途的 `AIagent1`，可在**本机**复制 `environment.yml` 后改 `name:`（该副本不要提交）。

---

## 2. 复制 VS Code 配置 / Copy editor config

**Windows (PowerShell):**

```powershell
New-Item -ItemType Directory -Force .vscode | Out-Null
Copy-Item -Path contrib\vscode\*.json -Destination .vscode\ -Force
```

**macOS / Linux:**

```bash
mkdir -p .vscode && cp contrib/vscode/*.json .vscode/
```

---

## 3. 任务（Tasks）/ Tasks

`tasks.json` 中的命令均为 **`conda run -n AIagent1 ...`**，不依赖「已激活终端」，也不写入解释器绝对路径。  
前提：`conda` 在 PATH 中（例如在 **Anaconda Prompt** 中打开 Cursor，或已执行 `conda init`）。

---

## 4. 调试（Launch）/ Debugging

`launch.json` 仍使用 **`${command:python.interpreterPath}`**（由编辑器解析）。请在本工作区内 **Python: Select Interpreter** 选择 **`AIagent1` (conda)** 一次；该选择通常写入 **本地** `.vscode/settings.json`（gitignore 已忽略），不会进 git。

---

## 5. 从终端一键跑（不写路径）/ CLI without storing paths

Windows PowerShell：

```powershell
.\scripts\conda_run.ps1 python -m pytest tests/ -q
```

详见 **[scripts/README.md](../../scripts/README.md)**。

---

To **erase `.vscode` from all past commits** before pushing to GitHub, run `contrib/rewrite-history-for-public.ps1` (requires `git-filter-repo`) or see comments inside that script.
