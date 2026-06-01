# Helper scripts / 辅助脚本

## `conda_run.ps1` (Windows PowerShell)

Runs a command inside the **`AIagent1`** conda environment via `conda run` (no absolute paths in the repo).

```powershell
.\scripts\conda_run.ps1 python -m pytest tests/ -q
.\scripts\conda_run.ps1 python run.py --input sample_manuscript.tex --output output.tex
```

Requires `conda` on `PATH` (e.g. after `conda init powershell` or from Anaconda Prompt).

## `rewrite-history-for-public.ps1`

Removes sensitive paths (e.g. `.vscode/`, `config/local.yaml`) from **entire Git history** before a public push. Requires `py -m pip install git-filter-repo`. See script header for usage.

See also the repo root **`environment.yml`**, **[examples/README.md](../examples/README.md)**, **[docs/local-runner.md](../docs/local-runner.md)**, and **[templates/vscode/README.md](../templates/vscode/README.md)**.
