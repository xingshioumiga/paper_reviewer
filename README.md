# paper-reviewer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**paper-reviewer** helps you polish **LaTeX** drafts **section by section** (`\section` / `\subsection`). A reviewer model lists issues, an editor proposes revised LaTeX, a critic scores the change, and the tool **accepts the edit only if the score improves**; otherwise it **rolls back** that section.

Chinese guide: **[README_zh.md](README_zh.md)**.

---

## What you can use it for

- Run **locally** against **Ollama** or any **OpenAI-compatible** API (cloud or self-hosted).
- Choose **light touch** fixes (`proofread`) or **broader** sentence- and paragraph-level polish (`rewrite`).
- Optionally run a **second pass** in `proofread` right after `rewrite` (same command; uses more model time).
- Get a new `.tex` file plus a **timestamped log** under `logs/`.

---

## What you need

- **Python 3.10+**
- For **`run.py`**: a reachable **OpenAI-compatible** endpoint (often Ollama at `http://127.0.0.1:11434/v1`) and the models you list in config.
- For **`run_demo.py`**: nothing else (mock pipeline, no network).

---

## Install

```bash
git clone <your-repository-url>
cd paper_reviewer
python -m venv .venv
```

**Windows (PowerShell):** `.\.venv\Scripts\Activate.ps1`  
**macOS / Linux:** `source .venv/bin/activate`

```bash
python -m pip install -r requirements-lock.txt
```

(Alternatively: `python -m pip install -r requirements.txt`.)

If you set **`llm.backend: ollama_native`** in YAML, also install:

```bash
python -m pip install langchain-ollama
```

---

## First-time configuration

1. Copy the example file to a local file (this path is **not** meant to be shared if it contains secrets):

   ```bash
   copy config\local.example.yaml config\local.yaml   # Windows
   # cp config/local.example.yaml config/local.yaml    # macOS / Linux
   ```

2. Edit **`config/local.yaml`**. For local Ollama, `api_key: ollama` is typical. For cloud keys, **do not commit** them; you can use a `config/*.private.yaml` file (see `.gitignore`).

3. Default input/output paths are set with `input_path` and `output_path`. The repository ships a small sample **`sample_manuscript.tex`**; point `input_path` at your own file when you work on a real manuscript.

---

## Run on the sample manuscript

**Full pipeline (calls your configured LLM):**

```bash
python run.py --input sample_manuscript.tex --output output.tex
```

**Heavier “rewrite” style pass:**

```bash
python run.py --input sample_manuscript.tex --output draft.tex --mode rewrite
```

**Try the flow without any LLM (mock graph):**

```bash
python run_demo.py
```

**Print version:**

```bash
python run.py --version
```

---

## Use your own paper

- Pass **`--input path\to\your.tex`** and **`--output path\to\out.tex`**, or set **`input_path` / `output_path`** in `config/local.yaml`.
- Keep private drafts out of version control (for example add your filename to `.gitignore` if needed). The repo keeps **`sample_manuscript.tex`** only as a **demo**; your personal `private-draft.tex` is ignored by default.

---

## Editing styles (`mode`)

| Mode | In plain terms |
|------|------------------|
| **`proofread`** (default) | Small, targeted edits driven by reviewer issues—good when you want a **safe, minimal** pass. |
| **`rewrite`** | Wider wording and flow improvements inside each section, **without** inventing results and **without** breaking cites, labels, refs, or math. |

CLI **`--mode`** overrides the `mode` value in YAML for that run.

---

## Optional: proofread right after rewrite

Add **`--post-proofread`** to a **`--mode rewrite`** run (or set `post_proofread_after_rewrite: true` in YAML) to chain a second graph pass in **`proofread`** mode. This costs extra LLM time; the number of outer rounds for that second pass is capped by **`post_proofread_max_iterations`**.

---

## Where your files go

- **Output TeX:** the path you pass with `--output` or set as `output_path` (often `output.tex`; that name is gitignored so it is not committed by mistake).
- **Logs:** under **`log_dir`** (default `logs/`), filenames like `run_YYYYMMDD_HHMMSS.log`.

If some model calls fail, **`run.py` still writes the current TeX** but exits with code **`1`** unless you pass **`--allow-llm-failures`**.

---

## Main configuration keys

Default file: **`config/local.yaml`**. Override with **`--config`**.

| Key | Meaning |
|-----|--------|
| `input_path` / `output_path` | Default TeX input and output paths |
| `mode` | `proofread` or `rewrite` |
| `post_proofread_after_rewrite` | If `true` with `rewrite`, run a second `proofread` pass (also toggled by `--post-proofread`) |
| `post_proofread_max_iterations` | Outer iteration cap for that second pass |
| `max_iterations` | Maximum full-document outer rounds |
| `max_no_improve` | Per-section cap: stop retrying a section if the score does not beat the last accepted one |
| `log_level` / `log_dir` | Logging level and directory |
| `ollama_healthcheck` | If `true`, `run.py` checks Ollama `GET /api/tags` before the run (turn off for non-Ollama hosts) |
| `llm` | `backend`, `base_url`, `api_key`, optional `request_timeout`, per-role `model` / `temperature` |

More examples: **`config/local.example.yaml`**.

**Precedence:** CLI arguments override YAML where supported; YAML overrides built-in defaults.

---

## Useful command-line flags

| Flag | Meaning |
|------|--------|
| `--input` / `--output` | Input and output `.tex` paths |
| `--config` | YAML config path (default `config/local.yaml`) |
| `--mode` | `proofread` or `rewrite` |
| `--post-proofread` | After `rewrite`, run the chained `proofread` pass |
| `--max-iterations` / `--max-no-improve` | Override iteration limits |
| `--log-level` | e.g. `INFO`, `DEBUG` |
| `--allow-llm-failures` | Exit `0` even if some LLM calls failed |
| `--version` | Show version string |

---

## LLM backends (short)

| `llm.backend` | When to use it |
|---------------|----------------|
| **`openai_compatible`** (default) | Standard OpenAI-style `/v1` URL (Ollama, vLLM, many cloud APIs). |
| **`ollama_native`** | Native Ollama options (e.g. disable “thinking” on some Qwen models). Requires `langchain-ollama`. |

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| `ModuleNotFoundError` | Re-run install from `requirements-lock.txt` (and `langchain-ollama` if using `ollama_native`). |
| Cannot connect to Ollama | Ensure `ollama serve` is running; try `http://127.0.0.1:11434/v1` as `base_url`; disable `ollama_healthcheck` if the server is not Ollama. |
| Timeouts / very slow | Increase or clear `llm.request_timeout` in YAML. |
| Truncated text in the terminal | Open the output `.tex` file; the terminal only shows a preview. |
| JSON / editor warnings in the log | Very long sections: use a larger context window, a model that follows JSON reliably, or split sections. |

---

## Version

Run `python run.py --version`. It should match `_version.py` and `pyproject.toml` when you release a new version.
