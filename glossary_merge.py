"""Glossary seed/merge helpers: load YAML, normalize keys, merge LLM candidates, persist merged file.

术语表：人工种子 locked、运行期 provisional 合并与落盘（默认 private/，gitignore）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def normalize_abbr_key(abbr: str) -> str:
    """Normalize abbreviation for dictionary keys (case-insensitive uniqueness)."""
    s = (abbr or "").strip()
    if not s:
        return ""
    s = s.strip("{}")
    s = re.sub(r"^\\textit\{|\}$", "", s)
    s = re.sub(r"^\\textbf\{|\}$", "", s)
    return s.upper()


def load_seed_yaml(path: Path) -> dict[str, str]:
    """Load ``locked: {ABBR: expansion}`` from seed file; missing file → empty."""
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("glossary seed read failed %s: %s", path, e)
        return {}
    if not isinstance(raw, dict):
        return {}
    locked = raw.get("locked")
    if not isinstance(locked, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in locked.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        nk = normalize_abbr_key(k)
        if nk:
            out[nk] = v.strip()
    return out


def load_merged_yaml(path: Path) -> dict[str, str]:
    """Load ``provisional`` mapping from a previous merged file."""
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("glossary merged read failed %s: %s", path, e)
        return {}
    if not isinstance(raw, dict):
        return {}
    prov = raw.get("provisional")
    if not isinstance(prov, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in prov.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        nk = normalize_abbr_key(k)
        if nk:
            out[nk] = v.strip()
    return out


def merge_glossary_candidates(
    locked: dict[str, str],
    provisional: dict[str, str],
    entries: list[dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """Merge model entries into ``provisional``; never overwrite ``locked``. Returns (new_provisional, log_lines)."""
    new_p = dict(provisional)
    logs: list[str] = []
    locked_keys = set(locked.keys())

    for ent in entries:
        if not isinstance(ent, dict):
            continue
        abbr = ent.get("abbr", "")
        exp = ent.get("expansion", "")
        if not isinstance(abbr, str) or not isinstance(exp, str):
            continue
        key = normalize_abbr_key(abbr)
        exp_clean = exp.strip()
        if not key or not exp_clean or len(exp_clean) > 400:
            continue
        if key in locked_keys:
            logs.append(f"glossary merge: skip '{key}' (locked)")
            continue
        if key in new_p and new_p[key].lower() != exp_clean.lower():
            logs.append(f"glossary merge: conflict '{key}' keep first expansion")
            continue
        if key not in new_p:
            new_p[key] = exp_clean
            logs.append(f"glossary merge: add provisional {key}={exp_clean[:80]!r}")

    return new_p, logs


def save_merged_yaml(path: Path, locked: dict[str, str], provisional: dict[str, str]) -> None:
    """Atomically write merged glossary (locked snapshot + provisional)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "locked": {k: locked[k] for k in sorted(locked.keys())},
        "provisional": {k: provisional[k] for k in sorted(provisional.keys())},
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def render_glossary_block(locked: dict[str, str], provisional: dict[str, str]) -> str:
    """Single prompt block for reviewer/editor/critic (deduped by key)."""
    if not locked and not provisional:
        return ""
    lines: list[str] = [
        "## Canonical glossary (use these meanings; do not invent different expansions "
        "for the same abbreviation):",
    ]
    for k in sorted(locked.keys()):
        lines.append(f"- {k} (locked): {locked[k]}")
    for k in sorted(provisional.keys()):
        if k in locked:
            continue
        lines.append(f"- {k}: {provisional[k]}")
    return "\n".join(lines)


def load_initial_glossary_state(
    seed_path: Path,
    merged_path: Path,
    load_provisional_from_merged: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    """At run start: locked from seed; provisional optionally bootstrapped from merged file."""
    locked = load_seed_yaml(seed_path)
    provisional: dict[str, str] = {}
    if load_provisional_from_merged:
        provisional = load_merged_yaml(merged_path)
    return locked, provisional
