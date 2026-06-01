"""Tests for local web dashboard (web_app.py)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from web_app import REPO_ROOT, RunRequest, app, build_run_argv, job_manager


@pytest.fixture
def client() -> TestClient:
    job_manager._job = None
    job_manager._last_finished = None
    return TestClient(app)


def test_api_defaults(client: TestClient) -> None:
    r = client.get("/api/defaults")
    assert r.status_code == 200
    data = r.json()
    assert data["sample_input"] == "sample_manuscript.tex"
    assert "version" in data


def test_build_run_argv_proofread() -> None:
    payload = RunRequest(
        input_path="sample_manuscript.tex",
        output_path="output.tex",
        config_path="config/local.example.yaml",
        mode="proofread",
        post_proofread=True,
    )
    argv = build_run_argv(payload, demo=False)
    assert argv[1].endswith("run.py")
    assert "--post-proofread" in argv
    assert "--mode" in argv and "proofread" in argv


def test_build_run_argv_demo() -> None:
    payload = RunRequest(demo=True, config_path="config/local.example.yaml")
    argv = build_run_argv(payload, demo=True)
    assert argv[1].endswith("run_demo.py")
    assert "--post-proofread" not in argv


def test_index_serves_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "paper-reviewer" in r.text
    assert 'class="route route-home active" id="route-home"' in r.text
    assert 'id="route-run" hidden' in r.text
    assert 'id="route-config" hidden' in r.text
    assert 'id="route-logs" hidden' in r.text


def test_run_log_panel_is_not_inside_home_route(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    home = r.text.split('id="route-home"', 1)[1].split('id="route-run"', 1)[0]
    assert "logView" not in home
    assert "运行日志" not in home
    assert "inputPath" not in home
    assert "configEditor" not in home
    assert "home-button" in home


def test_run_rejects_missing_input(client: TestClient) -> None:
    r = client.post(
        "/api/run",
        json={
            "input_path": "no_such_file_12345.tex",
            "output_path": "output.tex",
            "config_path": "config/local.example.yaml",
        },
    )
    assert r.status_code == 400


def test_run_demo_mock_subprocess(client: TestClient) -> None:
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout = io.StringIO("")
    mock_proc.stderr = io.StringIO("")

    with patch("web_app.subprocess.Popen", return_value=mock_proc):
        r = client.post(
            "/api/run",
            json={
                "input_path": "sample_manuscript.tex",
                "output_path": "output.tex",
                "config_path": "config/local.example.yaml",
                "demo": True,
                "max_iterations": 1,
                "max_no_improve": 1,
            },
        )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    st = client.get(f"/api/status/{job_id}")
    assert st.status_code == 200
    body = st.json()
    assert body["job_id"] == job_id
    assert body["demo"] is True


def test_api_logs_lists_files(client: TestClient) -> None:
    r = client.get("/api/logs")
    assert r.status_code == 200
    assert "logs" in r.json()


def test_api_output_sample(client: TestClient) -> None:
    out = REPO_ROOT / "sample_manuscript.tex"
    if not out.is_file():
        pytest.skip("sample_manuscript.tex missing")
    r = client.get("/api/output", params={"path": "sample_manuscript.tex"})
    assert r.status_code == 200
    assert "content" in r.json()


def test_api_config_reads_example(client: TestClient) -> None:
    r = client.get("/api/config", params={"path": "config/local.example.yaml"})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "config/local.example.yaml"
    assert "input_path" in data["content"]


def test_api_config_rejects_outside_repo(client: TestClient) -> None:
    r = client.get("/api/config", params={"path": "../outside.yaml"})
    assert r.status_code == 400
