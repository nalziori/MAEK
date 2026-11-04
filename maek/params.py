"""Config loading, dotted access, validation and Markdown parameter table."""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


def load_config(path=None) -> dict:
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_leaf(node) -> bool:
    return isinstance(node, dict) and "value" in node


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
