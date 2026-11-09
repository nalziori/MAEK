"""Config loading, dotted access, validation and Markdown parameter table."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "config" / "scenarios"


def _is_leaf(node) -> bool:
    return isinstance(node, dict) and "value" in node


def _merge(base: dict, over: dict) -> dict:
    """Deep-merge `over` onto `base` in place; a leaf in `over` replaces the base leaf."""
    for k, v in over.items():
        if isinstance(v, dict) and not _is_leaf(v) and isinstance(base.get(k), dict) \
                and not _is_leaf(base[k]):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def scenario_path(name: str) -> Path:
    """Path of config/scenarios/<name>.yaml (ValueError listing the names if missing)."""
    p = SCENARIO_DIR / f"{name}.yaml"
    if not p.is_file():
        avail = sorted(q.stem for q in SCENARIO_DIR.glob("*.yaml"))
        raise ValueError(f"unknown scenario {name!r}; available: {', '.join(avail)}")
    return p


def load_config(path=None, overlays=()) -> dict:
    """Load the base config and deep-merge overlays (YAML paths or dicts) onto it."""
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for ov in overlays:
        if not isinstance(ov, dict):
            with open(ov, encoding="utf-8") as f:
                ov = yaml.safe_load(f) or {}
        _merge(cfg, ov)
    return cfg


def with_values(cfg: dict, values: dict) -> dict:
    """Deep copy of `cfg` with the `value` of each dotted key replaced (KeyError if unknown)."""
    out = copy.deepcopy(cfg)
    for key, v in values.items():
        node = out
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(key)
            node = node[part]
        if not _is_leaf(node):
            raise KeyError(f"{key} is not a leaf parameter")
        node["value"] = v
    return out


def iter_leaves(cfg: dict, prefix: str = ""):
    """Yield (dotted_key, leaf_mapping) for every leaf."""
    for k, v in cfg.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if _is_leaf(v):
            yield key, v
        elif isinstance(v, dict):
            yield from iter_leaves(v, key)
        else:
            yield key, {}  # bare value: invalid leaf, reported by validate


def get(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    if not _is_leaf(node):
        raise KeyError(f"{dotted} is not a leaf parameter")
    return node["value"]


def validate(cfg: dict) -> None:
    bad = []
    for key, leaf in iter_leaves(cfg):
        if not _is_leaf(leaf) or not (leaf.get("source") or leaf.get("assumption") is True):
            bad.append(key)
    if bad:
        raise ValueError("source/assumption missing: " + ", ".join(bad))


def params_table(cfg: dict) -> str:
    rows = ["| 항목 | 값 | 단위 | 근거 |", "|---|---|---|---|"]
    for key, leaf in iter_leaves(cfg):
        src = leaf.get("source")
        basis = f"[링크]({src})" if src else "가정"
        val = str(leaf.get("value")).replace("|", "\\|")
        rows.append(f"| `{key}` | {val} | {leaf.get('unit', '')} | {basis} |")
    return "\n".join(rows) + "\n"
