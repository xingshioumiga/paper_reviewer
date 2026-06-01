# paper-reviewer

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**paper-reviewer** is a **LangGraph** pipeline for **LaTeX** manuscripts. It walks `\section` / `\subsection`: a reviewer lists issues, an editor proposes revised LaTeX, a critic scores the change, and the tool **accepts an edit only if the score improves**—otherwise it **rolls back** that section.

Chinese guide: **[README_zh.md](README_zh.md)**.

## What’s new in **0.4.0** (major update)

- **Glossary pipeline (enabled by default):** before each section’s reviewer, a **glossary** step can extract abbreviations into a merged table (**`locked`** from `private/glossary.seed.yaml` + model **`provisional`**). The same table is injected into **reviewer / editor / critic** prompts for consistent terminology. It runs **once per section on outer iteration 0** only. Set **`glossary.enabled: false`** in YAML to skip the extra LLM calls. See [`glossary_merge.py`](glossary_merge.py), **[contrib/private/README.md](contrib/private/README.md)**, and [`config/local.example.yaml`](config/local.example.yaml).
- **Ollama resilience:** bounded **retries** for dropped HTTP streams and transient **502 / 503 / 504** on native Ollama calls; existing **`num_predict`** and JSON parse retry settings for long sections.
- **Private runner docs:** expanded **[contrib/private/README.md](contrib/private/README.md)** (bat encoding, conda `Scripts\conda.exe`, long-run Ollama tips).

## What you get

- Local or remote **OpenAI-compatible** APIs (e.g. Ollama) or optional **native Ollama** settings.
- **`proofread`** (light, issue-driven) or **`rewrite`** (broader wording inside each section, without inventing results or breaking cites/refs/math).
- Optional **second pass**: `rewrite` then **`proofread`** in one command.
- A new **`.tex`** plus **timestamped logs** under `logs/` (by default).
- **Glossary** (when enabled): human **`locked`** terms + model **`provisional`** merge; injected into downstream prompts.

## Requirements

- **Python 3.10+**
- **`run.py`**: a reachable LLM endpoint and models named in your config.
- **`run_demo.py`**: no network (mock graph).

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

If you set **`llm.backend: ollama_native`** in YAML:

```bash
python -m pip install langchain-ollama
```

### Conda (optional)

The repo includes **`environment.yml`** (env **name** and dependencies only—no machine paths). Create or update:

```bash
conda env create -f environment.yml
conda activate <env-name-from-environment.yml>
```

Later: `conda env update -f environment.yml`. On **Windows**, without activating: **`.\scripts\conda_run.ps1 python -m pytest tests/ -q`**. VS Code task templates: **`contrib/vscode/`** (copy into `.vscode/`; see **`contrib/vscode/README.md`**).

## Configuration

1. Copy the example to a **local** file (do not commit secrets):

   ```bash
   copy config\local.example.yaml config\local.yaml   # Windows
   # cp config/local.example.yaml config/local.yaml   # macOS / Linux
   ```

2. Edit **`config/local.yaml`**. For local Ollama, `api_key: ollama` is typical. For cloud keys, use **`config/*.private.yaml`** (see `.gitignore`) instead of committing keys.

3. Set **`input_path`** / **`output_path`**, or pass **`--input`** / **`--output`**. The repo ships **`sample_manuscript.tex`** as a demo.

4. **Glossary (default `enabled: true` in built-in config):** files live under **`private/`** (gitignored). Copy **[contrib/private/glossary.seed.example.yaml](contrib/private/glossary.seed.example.yaml)** to **`private/glossary.seed.yaml`** for manual **`locked:`** entries; **`private/glossary.merged.yaml`** is updated when **`persist_merged_after_merge`** is true. Set **`glossary.enabled: false`** to disable glossary LLM calls entirely.

## Run

**Full pipeline (uses your configured LLM):**

```bash
python run.py --input sample_manuscript.tex --output output.tex
```

**Stronger rewrite-style pass:**

```bash
python run.py --input sample_manuscript.tex --output draft.tex --mode rewrite
```

**Mock pipeline (no LLM):**

```bash
python run_demo.py
```

**Version:**

```bash
python run.py --version
```

## Your own manuscript & private runner

- Use **`--input`** / **`--output`** or YAML **`input_path`** / **`output_path`**.
- **Windows double-click:** keep drafts out of git with a root **`private/`** folder (ignored by **`/private/`** in `.gitignore`). Put **`run_my_paper.bat`** and **`run_config.yaml`** there; see **[contrib/private/README.md](contrib/private/README.md)** for encoding, conda path, and `input_path` relative to the **repo root**.
- Add patterns to **`.gitignore`** for any local-only `.tex` you never want committed.

## Editing styles (`mode`)

| Mode | Meaning |
|------|--------|
| **`proofread`** (default) | Small, targeted edits from reviewer issues. |
| **`rewrite`** | Wider polish per section without breaking structure, cites, labels, refs, or math. |

CLI **`--mode`** overrides YAML for that run.

## Optional: proofread after rewrite

Use **`--post-proofread`** with **`--mode rewrite`** (or `post_proofread_after_rewrite: true` in YAML) to chain a second **`proofread`** pass. Extra model time; outer rounds capped by **`post_proofread_max_iterations`**.

## Outputs

- **TeX:** path from **`--output`** or **`output_path`** (e.g. `output.tex`; that name is gitignored by default).
- **Logs:** **`log_dir`** (default `logs/`), e.g. `run_YYYYMMDD_HHMMSS.log`.

If some LLM calls fail, **`run.py` still writes the current TeX** but exits **`1`** unless **`--allow-llm-failures`**.

## Main YAML keys

Default **`config/local.yaml`**; override with **`--config`**.

| Key | Meaning |
|-----|--------|
| `input_path` / `output_path` | Default TeX paths |
| `mode` | `proofread` or `rewrite` |
| `post_proofread_after_rewrite` | With `rewrite`, run chained `proofread` (or use `--post-proofread`) |
| `post_proofread_max_iterations` | Outer iteration cap for that second pass |
| `max_iterations` | Max full-document outer rounds |
| `max_no_improve` | Per-section retries if score does not beat last accepted |
| `log_level` / `log_dir` | Logging |
| `ollama_healthcheck` | If `true`, probes Ollama `GET /api/tags` before run |
| `glossary` | `enabled`, `seed_path`, `merged_path`, `bootstrap_provisional_from_merged`, `persist_merged_after_merge` (see example YAML) |
| `llm` | `backend`, `base_url`, `api_key`, optional `request_timeout`, per-role `model` / `temperature`, optional nested **`glossary`** (`model`, `temperature`) for the extract step, and generation/parse tuning (see example YAML) |

See **`config/local.example.yaml`**. **Precedence:** CLI (where supported) > YAML > code defaults.

**LLM graph order:** `init` → **`glossary`** → `reviewer` → `editor` → `critic` → `aggregator` → …

## CLI flags

| Flag | Meaning |
|------|--------|
| `--input` / `--output` | TeX paths |
| `--config` | YAML path (default `config/local.yaml`) |
| `--mode` | `proofread` or `rewrite` |
| `--post-proofread` | After `rewrite`, run `proofread` pass |
| `--max-iterations` / `--max-no-improve` | Iteration overrides |
| `--log-level` | e.g. `INFO`, `DEBUG` |
| `--allow-llm-failures` | Exit `0` if some LLM calls failed |
| `--version` | Print version |

## LLM backends

| `llm.backend` | Use when |
|---------------|----------|
| **`openai_compatible`** (default) | OpenAI-style `/v1` (Ollama, vLLM, many clouds). |
| **`ollama_native`** | You need native Ollama options (e.g. “thinking” off on some models). Requires `langchain-ollama`. |

**Ollama / structured output:** defaults include configurable **`num_predict`** (max tokens) and **JSON parse retries** for structured chains; the **editor** role may use higher retry limits. If structured parsing still fails for a section, that section may be **skipped** (logged); tune context, model, **`num_predict`**, or split long sections—see **`config/local.example.yaml`** and run logs.

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| `ModuleNotFoundError` | Reinstall from `requirements-lock.txt`; add `langchain-ollama` for `ollama_native`. |
| Cannot reach Ollama | Run `ollama serve`; try `http://127.0.0.1:11434/v1` as `base_url`; set `ollama_healthcheck: false` if the host is not Ollama. |
| Slow / timeouts | Adjust or clear `llm.request_timeout`; increase `num_predict` if output is truncated mid-JSON. |
| Terminal truncates TeX | Open the output `.tex` file. |
| Editor JSON / skipped section | Shorter sections, larger context, more reliable JSON model, or higher `num_predict` / retries in config. |
| Windows bat / conda issues | See **[contrib/private/README.md](contrib/private/README.md)** (encoding, `conda.exe` vs `conda.bat`, `CONDA_EXE_PATH`). |

## Development

```bash
python -m pytest tests/ -q
```

## Version

Current release: **0.4.0**. `python run.py --version` should match **`_version.py`** and **`pyproject.toml`**.
