#Requires -Version 5.1
<#
.SYNOPSIS
  使用 ``py -m git_filter_repo`` 从整条 Git 历史中删除常见敏感路径（.vscode、曾误提交的 local.yaml、private-draft.tex）。

.DESCRIPTION
  运行前请备份仓库。重写后需 ``git push --force-with-lease``；他人需重新克隆。
  ``git-filter-repo`` 会删除 ``origin`` 远程；本脚本在末尾尝试按 ``$OriginUrl`` 加回。

  若历史上还有**其它**需从 blob 中抹掉的字面量（例如本机 Python 绝对路径），请在本机新建一个
  文本文件（不要提交到 Git），每行格式见 ``py -m git_filter_repo --help`` 中的 ``--replace-text``，
  然后传入 ``-ReplaceTextFile``。

  依赖：``py -m pip install git-filter-repo``，且 ``py -m git_filter_repo --version`` 可用。

.EXAMPLE
  .\contrib\rewrite-history-for-public.ps1

.EXAMPLE
  .\contrib\rewrite-history-for-public.ps1 -ReplaceTextFile "$env:USERPROFILE\gfr-replacements.txt"
#>

param(
  [string] $ReplaceTextFile = "",
  [string] $OriginUrl = "https://github.com/YOUR_GITHUB_USER/YOUR_REPO.git"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Error "git not found in PATH."
}

$null = py -m git_filter_repo --version 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Error "Cannot run 'py -m git_filter_repo'. Install: py -m pip install git-filter-repo"
}

$gfrArgs = @(
  "--force",
  "--invert-paths",
  "--path", ".vscode/",
  "--path", "config/local.yaml",
  "--path", "private-draft.tex"
)

if ($ReplaceTextFile) {
  if (-not (Test-Path -LiteralPath $ReplaceTextFile)) {
    Write-Error "Replace-text file not found: $ReplaceTextFile"
  }
  $gfrArgs += @("--replace-text", (Resolve-Path -LiteralPath $ReplaceTextFile).Path)
}

Write-Host "Running: py -m git_filter_repo $($gfrArgs -join ' ')" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to cancel, or Enter to continue."
Read-Host | Out-Null

py -m git_filter_repo @gfrArgs

if (-not (git remote 2>$null | Select-String -Pattern "^origin\s")) {
  git remote add origin $OriginUrl
  Write-Host "Re-added remote: origin -> $OriginUrl" -ForegroundColor Green
}

Write-Host @"

Done. Next:
1. Verify there are no leftover secrets:  git grep -i "" OR use GitHub secret scanning
2. Push:  git push --force-with-lease origin main
"@ -ForegroundColor Green
