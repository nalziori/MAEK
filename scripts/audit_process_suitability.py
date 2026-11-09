"""Audit saved pipe topology and demo scope without changing scene or route."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "visualization/process_suitability"


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def main():
    catalog = read("unity/MAEKInspection/Assets/MAEK/Source/pipe_services.json")
    net = read("visualization/pipe_services/services_network.json")
    hydraulic = read("unity/MAEKInspection/Assets/MAEK/Source/hydraulic_results.json")
    nodes = net["nodes"]
    ids = [p["id"] for p in catalog["pipes"]]
    graph = defaultdict(set)
    failures = []
    rows = []
    category = {
        "CW_SUPPLY": "primary_inspection",
        "CW_RETURN": "primary_inspection",
        "BFG_RAW": "primary_inspection",
        "BFG_DEDUST": "primary_inspection",
        "BFG_CLEAN": "primary_inspection",
        "WASH": "primary_inspection",
        "SLURRY": "primary_inspection",
        "HOT_BLAST": "process_context",
        "COLD_BLAST": "process_context",
        "COMB_AIR": "process_context",
        "FLUE": "process_context",
        "TRAIN_CW": "training_only",
        "N2": "standalone_utility_demo",
        "INSTR_AIR": "standalone_utility_demo",
    }
    by_id = {p["id"]: p for p in catalog["pipes"]}
    if len(ids) != 247 or len(set(ids)) != 247:
        failures.append("Catalogue must contain 247 distinct pipe IDs")
    if set(ids) != {l["id"] for l in net["lines"]}:
        failures.append("Catalogue and topology IDs differ")
    for line in net["lines"]:
        a, b = line["from"], line["to"]
        if a not in nodes or b not in nodes:
            failures.append(line["id"] + ": missing node")
            continue
        endpoint_error = max(
            math.dist(line["points"][0], nodes[a]["position"]),
            math.dist(line["points"][-1], nodes[b]["position"]),
        )
        if endpoint_error > 0.001:
            failures.append(line["id"] + ": endpoint mismatch")
        if any(nodes[k]["medium"] != line["medium"] for k in (a, b)):
            failures.append(line["id"] + ": incompatible external medium")
        if line["service"] != by_id[line["id"]]["serviceCode"]:
            failures.append(line["id"] + ": service assignment mismatch")
        if line["state"] != "closed":
            graph[a].add(b)
            graph[b].add(a)
        rows.append(
            {
                "id": line["id"],
                "service": line["service"],
                "demo_role": category[line["service"]],
                "from_node": a,
                "to_node": b,
                "state": line["state"],
                "endpoint_error_m": endpoint_error,
            }
        )
    for edge in net["internal_connections"]:
        if edge["active"]:
            graph[edge["from"]].add(edge["to"])
            graph[edge["to"]].add(edge["from"])
    routes = []
    for route in net["required_routes"]:
        visited = {route["from"]}
        queue = deque(visited)
        while queue:
            for neighbor in graph[queue.popleft()] - visited:
                visited.add(neighbor)
                queue.append(neighbor)
        ok = route["to"] in visited
        routes.append(dict(**route, connected=ok))
        if not ok:
            failures.append("Required route disconnected: " + route["caption"])
    hydraulic_checks = []
    for scenario in hydraulic["scenarios"]:
        actual = [p["id"] for p in scenario["pipes"]]
        ok = set(actual) == set(ids) and len(actual) == len(ids)
        hydraulic_checks.append({"scenario": scenario["id"], "complete_ids": ok})
        if not ok:
            failures.append("Hydraulic catalogue mismatch: " + scenario["id"])
    context = read("unity/MAEKInspection/Assets/MAEK/Source/process_context.json")
    context_services = {item["code"]: item for item in context["services"]}
    if len(context_services) != 14:
        failures.append("Process context must define 14 unique services")
    for row in rows:
        item = context_services.get(row["service"], {})
        if item.get("role") != row["demo_role"] or not all(
            item.get(key) for key in ("label", "chain", "inspection", "followUp")
        ):
            failures.append(row["id"] + ": missing/misleading process context")
    base = hydraulic["scenarios"][0]
    sample = {p["id"]: p for p in base["pipes"]}
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "pipe_roles.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    sources = [
        "unity/MAEKInspection/Assets/MAEK/Source/pipe_services.json",
        "visualization/pipe_services/services_network.json",
        "unity/MAEKInspection/Assets/MAEK/Source/hydraulic_results.json",
        "unity/MAEKInspection/Assets/MAEK/Source/inspection_tour.json",
        "visualization/hydraulics/config.json",
        "unity/MAEKInspection/Assets/MAEK/Source/process_context.json",
    ]
    result = {
        "date": "2026-11-09",
        "structural_status": "PASS" if not failures else "FAIL",
        "suitability": "CONDITIONAL: RGB rust demonstration; not validated plant engineering",
        "pipe_count": len(ids),
        "service_counts": dict(Counter(p["serviceCode"] for p in catalog["pipes"])),
        "role_counts": dict(Counter(r["demo_role"] for r in rows)),
        "required_routes": routes,
        "hydraulic_id_checks": hydraulic_checks,
        "failures": failures,
        "connectivity_scope": "Undirected active fluid topology, not pressure-directed reachability, CAD interference, or P&ID certification. Closed valves intentionally excluded; standby is available topology, not asserted flow.",
        "baseline_example": {k: sample[k] for k in ["BF1-H200", "BF1-G001", "UTIL-N002"]},
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
    }
    (OUT / "audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: result[k] for k in ["structural_status", "pipe_count", "role_counts", "failures"]},
            ensure_ascii=False,
        )
    )
    print("required routes:", len(routes), "connected:", sum(r["connected"] for r in routes))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
