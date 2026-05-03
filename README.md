# paper_reviewer

A lightweight LangGraph-based paper reviewer demo with iterative section editing (LaTeX `\section{...}` blocks), using an **OpenAI-compatible** local API (e.g. **Ollama**).

**中文说明见 [README_zh.md](README_zh.md).**

## Requirements

- **Python 3.10+**
- For **`run.py`** (LLM path): Ollama (or compatible server) running locally, models pulled as configured (e.g. `qwen2.5:14b`).
- **`run_demo.py`**: mock graph only; no LLM calls; good for fast routing/state checks.

## Quick Start

1. Create and activate a virtual environment (conda or venv).
2. Install dependencies (pick one):
   - **Reproducible (recommended):** `python -m pip install -r requirements-lock.txt`
   - **Loose pins:** `python -m pip install -r requirements.txt`
3. Run:
   - **Mock pipeline:** `python run_demo.py`
   - **LLM pipeline (Ollama):** `python run.py --input sample_manuscript.tex --output output.tex`

Print version: `python run.py --version`

## Configuration

- Default config file: **`config/local.yaml`** (override with `--config`).
- Template with comments: **`config/local.example.yaml`**.
- For Ollama-only local use, keep `api_key: ollama`. Do not commit real cloud API keys; optional **`config/*.private.yaml`** is gitignored for secrets.
- If a **system-wide HTTP(S) proxy** breaks local Ollama, set `llm.base_url` to `http://127.0.0.1:11434/v1` or add localhost/127.0.0.1 to proxy bypass.

Common keys:

- `input_path`, `output_path`, `max_iterations`, `max_no_improve`, `log_level`, `log_dir`
- `ollama_healthcheck`: when `true`, `run.py` probes `{host from base_url}/api/tags` before the graph; set `false` for non-Ollama OpenAI-compatible hosts
- `llm`: `base_url`, `api_key`, optional positive `request_timeout` (seconds), and per-role `model` / `temperature` for `reviewer`, `editor`, `critic`

**CLI overrides YAML** for: `--input`, `--output`, `--max-iterations`, `--max-no-improve`, `--log-level`.

### LLM failures and exit codes

If any LLM node (reviewer/editor/critic) raises, `llm_failure_count` is incremented. **`run.py` exits with code 1** by default after writing the output TeX, so scripts do not treat a degraded run as success. Inspect `logs/` for `ERROR` lines.

Use **`--allow-llm-failures`** only if you intentionally want exit code 0 despite LLM errors.

## Iteration Semantics

The graph walks every parsed `\section{...}` in document order before the next outer iteration. After each edit, the critic scores the change and the **aggregator** compares to the last **accepted** score for that `section_id`:

- Higher score → accept and record in `history`.
- Otherwise → roll the section back to the last accepted content.
- If a section has no prior accepted score, the baseline is `0.0`.

The run ends with a per-section **accepted** score summary (never accepted → `0.0`). There is **no single global “best score”** across sections, to avoid misleading mixing of incomparable per-section critic values.

## Logging

Each run logs to the console and to `log_dir` (default `logs/`), files named `run_<timestamp>.log`. If `openai._base_client` keeps logging `Retrying request`, check `llm.request_timeout` in YAML: a small value can abort slow local generations; omit it or set a larger positive value.

## One-Click Run in Cursor/VS Code

The repo includes `.vscode/launch.json` and `.vscode/tasks.json`. If launch names still reference a specific conda env (e.g. `your-env`), adjust the `python` path in those JSON files to match your machine.

Typical tasks: run demo, run tests, ruff, combined quality gate.

## Tests and quality gate

```bash
python -m pytest -q
python -m ruff check .
```

Coverage includes: TeX parser edge cases, routing/stop rules, mock end-to-end graph and CLI, and **`run.py` exit behaviour** when the graph reports LLM failures.

## Troubleshooting

- **`ModuleNotFoundError`**: `pip install -r requirements-lock.txt` (or `requirements.txt`) in the active environment.
- **LLM errors but TeX written**: default **exit code 1**; see **LLM failures and exit codes** above.
- **Global proxy and 502 on localhost**: use `127.0.0.1` in `llm.base_url` or bypass proxy for local addresses.
- **No output file**: verify `--input` exists and paths are correct.
- **Truncated output in terminal**: open the output `.tex` file; the terminal only prints a preview.
- **Deeper diagnostics**: `--log-level DEBUG` and the latest file under `logs/`.

## Beginner guide (Chinese)

See **`TESTING_GUIDE_ZH.md`** for a beginner-oriented testing walkthrough.

## Version

`python run.py --version` matches `_version.py` and `pyproject.toml` `[project].version`; bump all together when cutting a release.
