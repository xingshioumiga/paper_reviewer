# paper_reviewer

A lightweight LangGraph-based paper reviewer demo with iterative section editing.

## Quick Start

1. Create or use the conda environment:
   - `your-env`
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Run the demo:
   - `python run_demo.py`

## Configuration

Default runtime config lives in `config/local.yaml`:

- `input_path`: source TeX file (default `private-draft.tex`)
- `output_path`: generated TeX file (default `output.tex`)
- `max_iterations`: graph iteration ceiling
- `max_no_improve`: early-stop threshold
- `log_level`: `DEBUG` / `INFO` / `WARNING` / `ERROR`

You can override config values from CLI:

- `python run_demo.py --input mypaper.tex --output revised.tex --max-iterations 2 --log-level DEBUG`

## Logging

Each run writes logs to both console and file:

- log directory: `logs/`
- file format: `logs/run_<timestamp>.log`

Typical diagnostics in logs:

- parsed section count
- section-level review/edit steps
- critic score per step
- section-level score comparison, rollback, and no-improve rounds

## Iteration Semantics

The graph iterates over every parsed `\section{...}` before starting the next
global iteration. After each edit, the critic scores the latest section update
and the aggregator compares that score with the last accepted score for the same
`section_id`.

- If the new score is higher than the previous accepted score for that section,
  the edit is accepted and stored in history.
- If the new score is not higher, the edit is rejected and the section content is
  rolled back to the last accepted version for that same section.
- If a section has no previous accepted score, the comparison baseline is `0.0`.

This means `best_score` remains a global diagnostic value, while accept/reject
decisions are made per section rather than against the global best score.

## One-Click Run in Cursor/VS Code

This repository includes:

- `.vscode/launch.json`: run/debug `run_demo.py` with F5
- `.vscode/tasks.json`: one-click terminal tasks

After opening the workspace:

1. Open **Run and Debug**
2. Select **Run Demo**
3. Press **F5**

Useful tasks:

- `Run Demo`
- `Run Tests`
- `Lint (ruff)`
- `Quality Gate (ruff + pytest)`

## Test

Run tests with:

- `python -m pytest -q`

Included tests cover:

- parser behavior and edge cases
- routing boundaries and stop conditions
- end-to-end graph invocation and CLI output generation

## Quality Gate

Run lints:

- `python -m ruff check .`

Run full local gate:

- `python -m ruff check .`
- `python -m pytest -q`

## Troubleshooting

- **`ModuleNotFoundError`**: run `pip install -r requirements.txt` in `your-env`.
- **No output generated**: check input path and whether the file exists.
- **Output seems truncated in terminal**: open `output.tex` directly; terminal only prints a preview.
- **Need deeper debug info**: run with `--log-level DEBUG` and inspect latest file in `logs/`.

## Beginner Guide

- Chinese beginner testing guide: `TESTING_GUIDE_ZH.md`
