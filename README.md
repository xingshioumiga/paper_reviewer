# paper_reviewer

A lightweight LangGraph-based paper reviewer demo with iterative section editing.

## Quick Start

1. Create or use the conda environment:
   - `AIagent1`
2. Install dependencies:
   - `D:/ProgramData/anaconda3/envs/AIagent1/python.exe -m pip install -r requirements.txt`
3. Run the demo:
   - `D:/ProgramData/anaconda3/envs/AIagent1/python.exe run_demo.py`

## One-Click Run in Cursor/VS Code

This repository includes:

- `.vscode/launch.json`: run/debug `run_demo.py` with F5
- `.vscode/tasks.json`: one-click terminal tasks

After opening the workspace:

1. Open **Run and Debug**
2. Select **Run Demo (AIagent1)**
3. Press **F5**

## Test

Run tests with:

- `D:/ProgramData/anaconda3/envs/AIagent1/python.exe -m pytest -q`

Included tests cover:

- section splitting logic
- graph routing logic
- minimal end-to-end graph invocation

## Beginner Guide

- Chinese beginner testing guide: `TESTING_GUIDE_ZH.md`
