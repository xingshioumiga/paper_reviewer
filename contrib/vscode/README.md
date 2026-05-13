# VS Code / Cursor 调试配置示例 / Sample VS Code launch & tasks

`.vscode` 目录存放 **编辑器本地配置**（启动调试、任务、解释器路径等），**不应提交到公开仓库**，以免泄露本机绝对路径或环境名。

This folder holds **portable** copies you can copy into `.vscode/` at the project root:

**Windows (PowerShell):**

```powershell
Copy-Item -Path contrib\vscode\*.json -Destination .vscode\ -Force
```

**macOS / Linux:**

```bash
mkdir -p .vscode && cp contrib/vscode/*.json .vscode/
```

Then pick your Python interpreter in the editor (**Python: Select Interpreter**). The sample `launch.json` uses `${command:python.interpreterPath}` so no machine-specific path is stored.

To **erase `.vscode` from all past commits** before pushing to GitHub, run `contrib/rewrite-history-for-public.ps1` (requires `git-filter-repo`) or see comments inside that script.
