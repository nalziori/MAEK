"""Reject disconnected or cross-medium additions without rewriting the 247 baseline."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unity/MAEKInspection/Assets/MAEK/Source"


def validate(data: dict) -> None:
    nodes = {n["id"]: n for n in data["nodes"]}
    lines = data["lines"]
    assert data["version"] == 1 and len(nodes) == len(data["nodes"])
    assert {c["id"] for c in data["circuits"]} == {"O2", "SINTER"}
    assert len(lines) == 17 == len({l["id"] for l in lines})
    for line in lines:
        a, b = nodes[line["from"]], nodes[line["to"]]
        assert a["circuit"] == b["circuit"] == line["circuit"], "cross-medium connection"
        assert line["radius"] > 0 and a["position"] != b["position"], "zero-length pipe"
    for circuit in data["circuits"]:
        group = {n["id"] for n in nodes.values() if n["circuit"] == circuit["id"]}
        sources = {n for n in group if nodes[n]["kind"] == "source"}
        sinks = {n for n in group if nodes[n]["kind"] == "sink"}
        assert sources and sinks
        reached = set(sources)
        draining = set(sinks)
        for _ in group:
            reached |= {l["to"] for l in lines if l["from"] in reached}
            draining |= {l["from"] for l in lines if l["to"] in draining}
        assert group <= reached, "unreachable equipment"
        assert group <= draining, "dead-ended equipment"
        assert circuit["source"].startswith("https://") and circuit["limit"]
    assert "NOT solved" in data["flowBasis"]


if __name__ == "__main__":
    from check_inspection_harness import validate_realism_baseline

    validate(json.loads((SOURCE / "supplementary_circuits.json").read_text(encoding="utf-8")))
    validate_realism_baseline(SOURCE, ROOT / "visualization/realism/baseline")
    print("PASS: 17 new spans; typed source/sink connectivity; six frozen original sources unchanged")
