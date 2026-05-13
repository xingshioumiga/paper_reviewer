#Requires -Version 5.1
<#
.SYNOPSIS
  使用 git-filter-repo 从整条 Git 历史中删除敏感路径（.vscode、曾提交的 local.yaml、private-draft.tex 等），便于公开仓库。

.DESCRIPTION
  运行前请备份仓库；历史重写后需 force-push，且所有协作者需重新克隆。
  需已安装 git-filter-repo（pip install git-filter-repo，并确保 git 能找到该命令）。

  Before running: backup the repo. After: force-push; all collaborators must re-clone.

.EXAMPLE
  cd path\to\paper_reviewer
  .\contrib\rewrite-history-for-public.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Error "git not found in PATH."
}

$gfr = Get-Command git-filter-repo -ErrorAction SilentlyContinue
if (-not $gfr) {
  Write-Error @"
git-filter-repo not found. Install with:
  py -m pip install git-filter-repo
Then ensure 'git filter-repo' works (pip may install a stub into Python Scripts — add Scripts to PATH), or run:
  py -m pip install --target .tools git-filter-repo
  $env:PATH = (Resolve-Path .tools\bin).Path + ';' + $env:PATH
"@
}

Write-Host "Removing from ALL commits: .vscode/, config/local.yaml, private-draft.tex" -ForegroundColor Yellow
Write-Host "Press Ctrl+C to cancel, or Enter to continue."
Read-Host | Out-Null

git filter-repo --force `
  --invert-paths `
  --path .vscode/ `
  --path config/local.yaml `
  --path private-draft.tex

Write-Host @"

Done. Next steps:
1. Re-add remote:  git remote add origin <your-github-url>
2. Force-push:     git push --force-with-lease origin main

git-filter-repo removes the 'origin' remote by default — you must add it again.
"@ -ForegroundColor Green
