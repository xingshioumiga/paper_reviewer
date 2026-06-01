"""Local web dashboard for paper-reviewer (FastAPI + static UI).

本机暗色 Web 控制台：通过子进程调用 ``run.py`` / ``run_demo.py``，不重复实现 LangGraph 逻辑。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from _version import __version__

REPO_ROOT = Path(__file__).resolve().parent
WEB_UI_DIR = REPO_ROOT / "web_ui"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7860
MAX_OUTPUT_PREVIEW = 120_000
MAX_LOG_TAIL = 80_000


def _resolve_repo_path(raw: str) -> Path:
    """Resolve path relative to repo root; reject traversal outside repo."""
    p = Path(raw)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    else:
        p = p.resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        # Allow paths outside repo only if they exist (user private data dir).
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"Path not found: {p}")
    return p


def build_run_argv(payload: RunRequest, *, demo: bool = False) -> list[str]:
    """Build subprocess argv for run.py or run_demo.py."""
    script = "run_demo.py" if demo else "run.py"
    argv = [
        sys.executable,
        str(REPO_ROOT / script),
        "--config",
        payload.config_path,
        "--input",
        payload.input_path,
        "--output",
        payload.output_path,
        "--mode",
        payload.mode,
        "--max-iterations",
        str(payload.max_iterations),
        "--max-no-improve",
        str(payload.max_no_improve),
        "--log-level",
        payload.log_level,
    ]
    if not demo and payload.post_proofread:
        argv.append("--post-proofread")
    if not demo and payload.allow_llm_failures:
        argv.append("--allow-llm-failures")
    return argv


class RunRequest(BaseModel):
    input_path: str = "sample_manuscript.tex"
    output_path: str = "output.tex"
    config_path: str = "config/local.yaml"
    mode: Literal["proofread", "rewrite"] = "proofread"
    max_iterations: int = Field(default=1, ge=1, le=20)
    max_no_improve: int = Field(default=100, ge=1, le=500)
    log_level: str = "INFO"
    post_proofread: bool = False
    allow_llm_failures: bool = False
    demo: bool = False


class ConfigFileRequest(BaseModel):
    path: str = "config/local.yaml"


class ConfigSaveRequest(ConfigFileRequest):
    content: str


def _resolve_editable_config_path(raw: str) -> Path:
    """Resolve a YAML config path that the local UI is allowed to edit."""
    p = Path(raw)
    if p.is_absolute():
        p = p.resolve()
    else:
        p = (REPO_ROOT / p).resolve()

    try:
        rel = p.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Config editor only supports files inside this repository.",
        ) from exc

    if p.suffix.lower() not in {".yaml", ".yml"}:
        raise HTTPException(status_code=400, detail="Config file must be .yaml or .yml.")

    parts = rel.parts
    if not parts or parts[0] not in {"config", "private", "examples"}:
        raise HTTPException(
            status_code=400,
            detail="Editable configs must live under config/, private/, or examples/.",
        )
    return p


@dataclass
class Job:
    job_id: str
    command: list[str]
    process: subprocess.Popen[str]
    started_at: float
    input_path: str
    output_path: str
    config_path: str
    demo: bool
    log_path: Path | None = None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    _reader_done: threading.Event = field(default_factory=threading.Event)

    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started_at

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: Job | None = None
        self._last_finished: Job | None = None

    def _refresh(self) -> None:
        if self._job and self._job.poll() is not None:
            self._last_finished = self._job
            self._job = None

    def active(self) -> Job | None:
        with self._lock:
            self._refresh()
            return self._job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._refresh()
            if self._job and self._job.job_id == job_id:
                return self._job
            if self._last_finished and self._last_finished.job_id == job_id:
                return self._last_finished
            return None

    def current_or_last(self) -> Job | None:
        with self._lock:
            self._refresh()
            if self._job:
                return self._job
            return self._last_finished

    def start(self, payload: RunRequest) -> Job:
        with self._lock:
            if self._job and self._job.poll() is None:
                raise HTTPException(status_code=409, detail="A run is already in progress.")

            inp = _resolve_repo_path(payload.input_path)
            if not inp.is_file():
                raise HTTPException(status_code=400, detail=f"Input file not found: {inp}")

            cfg = _resolve_repo_path(payload.config_path)
            if not cfg.is_file():
                raise HTTPException(status_code=400, detail=f"Config not found: {cfg}")

            _resolve_repo_path(payload.output_path)  # validate writable parent exists or path ok
            out_parent = (
                (REPO_ROOT / payload.output_path).resolve().parent
                if not Path(payload.output_path).is_absolute()
                else Path(payload.output_path).resolve().parent
            )
            out_parent.mkdir(parents=True, exist_ok=True)

            argv = build_run_argv(payload, demo=payload.demo)
            proc = subprocess.Popen(
                argv,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            job = Job(
                job_id=str(uuid.uuid4()),
                command=argv,
                process=proc,
                started_at=time.perf_counter(),
                input_path=payload.input_path,
                output_path=payload.output_path,
                config_path=payload.config_path,
                demo=payload.demo,
            )
            self._job = job
            threading.Thread(target=_drain_streams, args=(job,), daemon=True).start()
            return job

    def stop(self, job_id: str) -> None:
        with self._lock:
            job = self._job
            if not job or job.job_id != job_id:
                raise HTTPException(status_code=404, detail="Job not found or not active.")
            job.terminate()


def _drain_streams(job: Job) -> None:
    assert job.process.stdout is not None
    assert job.process.stderr is not None

    def read_stream(stream, bucket: list[str]) -> None:
        for line in stream:
            bucket.append(line.rstrip("\n"))

    t_out = threading.Thread(target=read_stream, args=(job.process.stdout, job.stdout_lines))
    t_err = threading.Thread(target=read_stream, args=(job.process.stderr, job.stderr_lines))
    t_out.start()
    t_err.start()
    t_out.join()
    t_err.join()
    job._reader_done.set()


def _latest_log_file(log_dir: Path) -> Path | None:
    if not log_dir.is_dir():
        return None
    logs = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _tail_text(path: Path, max_chars: int) -> str:
    if not path.is_file():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) <= max_chars:
        return data
    return "... (truncated)\n" + data[-max_chars:]


def _job_status_dict(job: Job) -> dict[str, Any]:
    exit_code = job.poll()
    log_dir = REPO_ROOT / "logs"
    latest = _latest_log_file(log_dir)
    if latest:
        job.log_path = latest

    log_parts: list[str] = []
    if job.stdout_lines:
        log_parts.append("\n".join(job.stdout_lines[-200:]))
    if job.stderr_lines:
        log_parts.append("\n".join(job.stderr_lines[-200:]))
    if latest:
        log_parts.append(_tail_text(latest, MAX_LOG_TAIL))

    combined = "\n".join(p for p in log_parts if p).strip()
    if len(combined) > MAX_LOG_TAIL:
        combined = "... (truncated)\n" + combined[-MAX_LOG_TAIL:]

    out_path = _resolve_repo_path(job.output_path)
    output_exists = out_path.is_file()

    return {
        "job_id": job.job_id,
        "running": exit_code is None,
        "exit_code": exit_code,
        "elapsed_s": round(job.elapsed_s(), 2),
        "command": job.command,
        "input_path": job.input_path,
        "output_path": job.output_path,
        "output_exists": output_exists,
        "config_path": job.config_path,
        "demo": job.demo,
        "log_file": str(latest.resolve()) if latest else None,
        "log_tail": combined,
    }


job_manager = JobManager()

app = FastAPI(
    title="paper-reviewer",
    description="Local dashboard for LaTeX review pipeline",
    version=__version__,
)


@app.get("/api/defaults")
def api_defaults() -> dict[str, Any]:
    private_cfg = REPO_ROOT / "private" / "run_config.yaml"
    glossary_merged = REPO_ROOT / "private" / "glossary.merged.yaml"
    return {
        "version": __version__,
        "repo_root": str(REPO_ROOT),
        "default_config": "config/local.yaml",
        "private_config": "private/run_config.yaml",
        "has_private_config": private_cfg.is_file(),
        "has_config_local": (REPO_ROOT / "config" / "local.yaml").is_file(),
        "sample_input": "sample_manuscript.tex",
        "default_output": "output.tex",
        "glossary_merged_path": "private/glossary.merged.yaml",
        "has_glossary_merged": glossary_merged.is_file(),
        "log_dir": "logs",
    }


@app.get("/api/config")
def api_config(path: str = "config/local.yaml") -> dict[str, Any]:
    p = _resolve_editable_config_path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"Config not found: {p}")
    return {
        "path": str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
        "content": p.read_text(encoding="utf-8", errors="replace"),
    }


@app.put("/api/config")
def api_save_config(payload: ConfigSaveRequest) -> dict[str, Any]:
    p = _resolve_editable_config_path(payload.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload.content, encoding="utf-8")
    return {
        "status": "saved",
        "path": str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
        "bytes": p.stat().st_size,
    }


@app.post("/api/run")
def api_run(payload: RunRequest) -> dict[str, Any]:
    job = job_manager.start(payload)
    return {"job_id": job.job_id, "status": "started"}


@app.get("/api/status/{job_id}")
def api_status(job_id: str) -> dict[str, Any]:
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_status_dict(job)


@app.get("/api/status")
def api_status_current() -> dict[str, Any]:
    job = job_manager.current_or_last()
    if not job:
        return {"running": False, "job_id": None}
    data = _job_status_dict(job)
    if not data["running"]:
        data["last_finished"] = True
    return data


@app.post("/api/stop/{job_id}")
def api_stop(job_id: str) -> dict[str, str]:
    job_manager.stop(job_id)
    return {"status": "stopped"}


@app.get("/api/output")
def api_output(path: str) -> dict[str, Any]:
    p = _resolve_repo_path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Output file not found.")
    text = p.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > MAX_OUTPUT_PREVIEW
    if truncated:
        text = text[:MAX_OUTPUT_PREVIEW]
    return {
        "path": str(p),
        "size": p.stat().st_size,
        "truncated": truncated,
        "content": text,
    }


@app.get("/api/glossary")
def api_glossary(path: str = "private/glossary.merged.yaml") -> dict[str, Any]:
    p = _resolve_repo_path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Glossary file not found.")
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/logs")
def api_logs(limit: int = 15) -> dict[str, Any]:
    log_dir = REPO_ROOT / "logs"
    if not log_dir.is_dir():
        return {"logs": []}
    files = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for f in files[:limit]:
        items.append(
            {
                "name": f.name,
                "path": str(f.relative_to(REPO_ROOT)).replace("\\", "/"),
                "mtime": f.stat().st_mtime,
                "size": f.stat().st_size,
            }
        )
    return {"logs": items}


@app.get("/api/log")
def api_log(path: str) -> dict[str, str]:
    p = _resolve_repo_path(path)
    if not p.is_file() or p.suffix != ".log":
        raise HTTPException(status_code=400, detail="Invalid log path.")
    return {"path": str(p), "content": _tail_text(p, MAX_LOG_TAIL)}


if WEB_UI_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_UI_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    index_file = WEB_UI_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=500, detail="web_ui/index.html missing.")
    return FileResponse(index_file)


def parse_web_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start paper-reviewer local web dashboard.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port (default 7860)")
    return parser.parse_args()


def main() -> None:
    args = parse_web_args()
    import uvicorn

    print(f"paper-reviewer Web UI v{__version__}")
    print(f"Open http://{args.host}:{args.port}/ in your browser.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
