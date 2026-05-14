# Helper scripts / 辅助脚本

## `conda_run.ps1` (Windows PowerShell)

Runs a command inside the **`AIagent1`** conda environment via `conda run` (no absolute paths in the repo).

```powershell
.\scripts\conda_run.ps1 python -m pytest tests/ -q
.\scripts\conda_run.ps1 python run.py --input sample_manuscript.tex --output output.tex
```

Requires `conda` on `PATH` (e.g. after `conda init powershell` or from Anaconda Prompt).

See also the repo root **`environment.yml`** and **[contrib/vscode/README.md](../contrib/vscode/README.md)**.
