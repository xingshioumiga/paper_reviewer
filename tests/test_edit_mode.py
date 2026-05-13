"""编辑模式（proofread / rewrite）：提示词、配置合并与默认状态 / edit modes: prompts, config merge, defaults."""

from pathlib import Path
import sys

from langgraph_nodes import init_llms_from_config
from langgraph_state import GraphState
from prompt_modes import build_prompt_bundle, normalize_edit_mode
from runtime_config import DEFAULT_CONFIG, load_merged_config, merge_config


def test_graphstate_default_edit_mode_is_proofread() -> None:
    s = GraphState(original_tex="\\section{A}\nx")
    assert s.edit_mode == "proofread"


def test_normalize_edit_mode_unknown_falls_back() -> None:
    assert normalize_edit_mode(None) == "proofread"
    assert normalize_edit_mode("typo") == "proofread"
    assert normalize_edit_mode("rewrite") == "rewrite"


def test_run_parse_args_accepts_mode() -> None:
    import run as run_mod

    old = sys.argv
    try:
        sys.argv = ["run.py", "--mode", "rewrite"]
        args = run_mod.parse_args()
        assert args.mode_override == "rewrite"
    finally:
        sys.argv = old


def test_proofread_and_rewrite_editor_prompts_differ() -> None:
    b = build_prompt_bundle(merge_config(DEFAULT_CONFIG, {}))
    p = b["proofread"]["editor"]
    r = b["rewrite"]["editor"]
    assert "最小" in p or "minimal" in p.lower()
    assert "重组" in r or "句式" in r
    assert p != r


def test_yaml_modes_override_builtin(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "mode: proofread\n"
        "modes:\n"
        "  proofread:\n"
        "    reviewer: 'OVERRIDE_REVIEWER_SYSTEM'\n",
        encoding="utf-8",
    )
    merged = load_merged_config(cfg)
    bundle = build_prompt_bundle(merged)
    assert bundle["proofread"]["reviewer"] == "OVERRIDE_REVIEWER_SYSTEM"


def test_init_llms_refreshes_prompt_bundle_for_native_backend(tmp_path: Path, monkeypatch) -> None:
    """Ollama native chains must receive prompts for the resolved mode (no stale import-time text)."""
    import langgraph_nodes as ln

    monkeypatch.setattr("langgraph_nodes._OLLAMA_AVAILABLE", True)
    cfg = tmp_path / "ollama.yaml"
    cfg.write_text(
        "ollama_healthcheck: false\n"
        "mode: rewrite\n"
        "llm:\n"
        "  backend: ollama_native\n"
        "  base_url: http://127.0.0.1:11434/v1\n"
        "  api_key: ollama\n",
        encoding="utf-8",
    )
    merged = load_merged_config(cfg)

    class FakeStructured:
        def __init__(self, **kwargs):
            pass

    class FakeReviewer:
        def __init__(self, llm, system_prompt: str):
            self.system_prompt = system_prompt

    class FakeEditor:
        def __init__(self, llm, system_prompt: str):
            self.system_prompt = system_prompt

    class FakeCritic:
        def __init__(self, llm, system_prompt: str):
            self.system_prompt = system_prompt

    monkeypatch.setattr("langgraph_nodes.OllamaStructuredLLM", FakeStructured)
    monkeypatch.setattr("langgraph_nodes.OllamaReviewerChain", FakeReviewer)
    monkeypatch.setattr("langgraph_nodes.OllamaEditorChain", FakeEditor)
    monkeypatch.setattr("langgraph_nodes.OllamaCriticChain", FakeCritic)

    try:
        init_llms_from_config(merged)
        assert "发展性" in ln.llm_structured_reviewer.system_prompt or "结构" in ln.llm_structured_reviewer.system_prompt
        assert "重组" in ln.llm_strucured_editor.system_prompt or "LaTeX" in ln.llm_strucured_editor.system_prompt
    finally:
        ln.init_llms_from_config({})
