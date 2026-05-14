# 在 conda 环境 AIagent1 中执行命令（不写磁盘路径，仅环境名）/ Run a command in conda env AIagent1 (name only, no paths).
# 例 / Examples:
#   .\scripts\conda_run.ps1 python -m pytest tests/ -q
#   .\scripts\conda_run.ps1 python run.py --input sample_manuscript.tex --output output.tex

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CommandArgs
)

if (-not $CommandArgs -or $CommandArgs.Count -eq 0) {
    Write-Error "Usage: .\scripts\conda_run.ps1 <command> [args...]  e.g.  python -m pytest tests/"
    exit 2
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    Write-Error "conda not found on PATH. Open Anaconda Prompt or run 'conda init powershell' then retry."
    exit 1
}

& conda run -n AIagent1 --no-capture-output @CommandArgs
exit $LASTEXITCODE
