"""Deterministic planning from inventory and explicitly verified frame locations.

This module does not infer defects, pick an NDT technique, execute inspections,
or clear an inventory requirement. Unknown input fields (including ground truth
and future NDT outcomes) are deliberately not used by this planner.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal
from numbers import Real

STATUSES = {"anomaly_observed", "no_anomaly_observed", "indeterminate", "unsupported_domain"}
UNCERTAIN = {"indeterminate", "unsupported_domain"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identifier(value, field):
    _require(isinstance(value, str) and bool(value.strip()), f"{field} must be a nonempty string")
    return value


def _number(value, field):
    _require(isinstance(value, Real) and not isinstance(value, bool), f"{field} must be numeric")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{field} must be finite and nonnegative") from error
    _require(math.isfinite(result) and result >= 0, f"{field} must be finite and nonnegative")
    return result


def _references(value, field):
    _require(isinstance(value, list), f"{field} must be a list")
    return sorted({_identifier(v, field) for v in value})


def _task_id(kind, identity):
    encoded = json.dumps([kind, *identity], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{kind}:{hashlib.sha256(encoded).hexdigest()[:24]}"


def _location(mapping_rows, inventory):
    if not mapping_rows:
        return None, "missing_mapping", []
    locations = set()
    for row in mapping_rows:
        asset, segment = row.get("asset_id"), row.get("segment_id")
        if not (isinstance(asset, str) and asset.strip() and isinstance(segment, str) and segment.strip()):
            return None, "incomplete_mapping_location", []
        locations.add((asset, segment))
    # Even an unverified competing location makes automatic attribution unsafe.
    if len(locations) != 1:
        return None, "ambiguous_mapping", []
    location = next(iter(locations))
    if location not in inventory:
        return None, "unknown_inventory_location", []
    trusted = [r for r in mapping_rows if r.get("verified") is True
               and isinstance(r.get("evidence_ref"), str) and r["evidence_ref"].strip()]
    if not trusted:
        reason = "missing_mapping_evidence" if any(r.get("verified") is True for r in mapping_rows) else "unverified_mapping"
        return None, reason, []
    return location, "resolved_verified_mapping", sorted({r["evidence_ref"] for r in trusted})


def _merged_evidence(observations):
    return {"observation_ids": sorted({o["observation_id"] for o in observations}),
            "frame_ids": sorted({o["frame_id"] for o in observations}),
            "assessment_statuses": sorted({o["assessment_status"] for o in observations}),
            "quality_flags": sorted({v for o in observations for v in o["quality_flags"]}),
            "evidence_refs": sorted({v for o in observations for v in o["evidence_refs"]}),
            "mapping_evidence_refs": sorted({v for o in observations for v in o.get("mapping_evidence_refs", [])})}


def plan_inspections(inventory: list[dict], observations: list[dict], mappings: list[dict],
                     budget: float | None = None) -> dict:
    """Plan required work first, then greedily fund ranked thermal review candidates.

    Costs and budget share the caller's unspecified currency/unit. Required costs
    are committed even when over budget or an existing method reference is absent.
    Deferral never deletes a candidate. Follow-up review/capture costs are unknown
    and excluded; task statuses describe planning only, never actual execution.
    """
    for value, name in ((inventory, "inventory"), (observations, "observations"), (mappings, "mappings")):
        _require(isinstance(value, list) and all(isinstance(row, dict) for row in value), f"{name} must be a list of dictionaries")
    budget_value = None if budget is None else Decimal(str(_number(budget, "budget")))
    assets = {}
    for row in inventory:
        key = (_identifier(row.get("asset_id"), "asset_id"), _identifier(row.get("segment_id"), "segment_id"))
        _require(key not in assets, "Duplicate inventory asset_id/segment_id")
        for name in ("mandatory", "high_risk"):
            _require(type(row.get(name)) is bool, f"{name} must be bool")
        plan = row.get("inspection_plan_ref")
        _require(plan is None or isinstance(plan, str), "inspection_plan_ref must be a string or absent")
        assets[key] = {"asset_id": key[0], "segment_id": key[1], "mandatory": row["mandatory"],
                       "high_risk": row["high_risk"], "risk_priority": _number(row.get("risk_priority"), "risk_priority"),
                       "estimated_cost": _number(row.get("estimated_cost"), "estimated_cost"),
                       "inspection_plan_ref": plan if plan and plan.strip() else None}
    mapped_by_frame = defaultdict(list)
    for row in mappings:
        frame = _identifier(row.get("frame_id"), "mapping frame_id")
        _require("verified" not in row or type(row["verified"]) is bool, "mapping verified must be bool")
        mapped_by_frame[frame].append(row)
    known_ids, normalized = set(), []
    for row in observations:
        oid = _identifier(row.get("observation_id"), "observation_id")
        _require(oid not in known_ids, "Duplicate observation_id")
        known_ids.add(oid)
        frame = _identifier(row.get("frame_id"), "observation frame_id")
        _require(isinstance(row.get("assessment_status"), str)
                 and row["assessment_status"] in STATUSES, "Unknown assessment_status")
        normalized.append({"observation_id": oid, "frame_id": frame,
                           "assessment_status": row["assessment_status"],
                           "quality_flags": _references(row.get("quality_flags", []), "quality_flags"),
                           "evidence_refs": _references(row.get("evidence_refs", []), "evidence_refs")})
    resolved, unmapped, mapping_records = defaultdict(list), defaultdict(list), []
    for observation in sorted(normalized, key=lambda o: o["observation_id"]):
        frame = observation["frame_id"]
        location, reason, refs = _location(mapped_by_frame.get(frame, []), assets)
        observation["mapping_evidence_refs"] = refs
        mapping_records.append({"observation_id": observation["observation_id"], "frame_id": frame,
                                "location_status": "resolved" if location is not None else "unmapped",
                                "asset_id": location[0] if location else None,
                                "segment_id": location[1] if location else None,
                                "reason": reason, "mapping_evidence_refs": refs})
        if location is None:
            unmapped[frame].append({**observation, "mapping_reason": reason})
        else:
            resolved[location].append(observation)
    required, additional, followups = [], [], []
    for key, asset in sorted(assets.items()):
        linked = resolved.get(key, [])
        statuses = {o["assessment_status"] for o in linked}
        reasons = []
        if asset["mandatory"]:
            reasons.append("mandatory_inventory_requirement")
        if asset["high_risk"]:
            reasons.append("high_risk_inventory_requirement")
        required_task = asset["mandatory"] or asset["high_risk"]
        anomaly = "anomaly_observed" in statuses
        if anomaly:
            reasons.append("thermal_anomaly_requires_inspection_review")
        if "no_anomaly_observed" in statuses:
            reasons.append("no_anomaly_does_not_clear_inventory_risk")
        if statuses & UNCERTAIN:
            reasons.extend(f"{s}_requires_followup" for s in sorted(statuses & UNCERTAIN))
            followups.append({"task_id": _task_id("capture_review", key), "task_kind": "followup_capture_review",
                              "status": "pending_review", "action": "followup_capture_review",
                              "asset_id": key[0], "segment_id": key[1],
                              "reasons": sorted(f"{s}_observation" for s in statuses & UNCERTAIN),
                              **_merged_evidence(linked)})
        if required_task or anomaly:
            missing_method = required_task and asset["inspection_plan_ref"] is None
            flags = ["unresolved_method"] if missing_method else []
            task = {"task_id": _task_id("inspection", key), **asset, "required": required_task,
                    "task_kind": "required_inspection" if required_task else "inspection_review",
                    "status": "scheduled" if required_task else "pending_budget_allocation",
                    "action": ("required_inspection_pending_method_review" if missing_method
                               else "existing_inspection_plan_pending_execution") if required_task
                              else "inspection_review_pending_ndt_method_review",
                    "ndt_method_review_required": bool(missing_method or anomaly),
                    "flags": flags, "reasons": sorted(reasons), **_merged_evidence(linked)}
            (required if required_task else additional).append(task)
    for frame, linked in sorted(unmapped.items()):
        followups.append({"task_id": _task_id("mapping_review", (frame,)), "task_kind": "unmapped_observation_review",
                          "status": "pending_review", "action": "verify_frame_location_before_routing",
                          "asset_id": None, "segment_id": None,
                          "reasons": sorted({o["mapping_reason"] for o in linked}),
                          "capture_review_required": any(o["assessment_status"] in UNCERTAIN for o in linked),
                          **_merged_evidence(linked)})
        if any(o["assessment_status"] in UNCERTAIN for o in linked):
            followups.append({"task_id": _task_id("unmapped_capture_review", (frame,)),
                              "task_kind": "followup_capture_review", "status": "pending_review",
                              "action": "followup_capture_review", "asset_id": None, "segment_id": None,
                              "reasons": sorted({f"{o['assessment_status']}_observation" for o in linked
                                                 if o["assessment_status"] in UNCERTAIN}),
                              **_merged_evidence(linked)})

    def rank(task):
        return -task["risk_priority"], task["asset_id"], task["segment_id"]

    def cost(task):
        return Decimal(str(task["estimated_cost"]))

    required.sort(key=rank); additional.sort(key=rank)
    required_cost = sum((cost(t) for t in required), Decimal(0))
    remaining = None if budget_value is None else max(Decimal(0), budget_value - required_cost)
    available_initial = remaining
    scheduled, deferred = list(required), []
    for task in additional:
        if remaining is None or cost(task) <= remaining:
            task["status"] = "scheduled"
            scheduled.append(task)
            if remaining is not None:
                remaining -= cost(task)
        else:
            task["status"] = "deferred"
            task["reasons"] = sorted([*task["reasons"], "insufficient_additional_budget"])
            deferred.append(task)
    shortfall = Decimal(0) if budget_value is None else max(Decimal(0), required_cost - budget_value)
    if shortfall > 0:
        for task in required:
            task["flags"] = sorted([*task["flags"], "required_budget_unresolved"])
    required_keys = {k for k, a in assets.items() if a["mandatory"] or a["high_risk"]}
    scheduled_required_keys = {(t["asset_id"], t["segment_id"]) for t in scheduled if t["required"]}
    preserved = required_keys == scheduled_required_keys
    _require(preserved, "Internal error: required inventory tasks were not preserved")
    _require(len({t["task_id"] for t in scheduled + deferred + followups}) == len(scheduled + deferred + followups), "Internal task ID collision")
    additional_cost = sum((cost(t) for t in scheduled if not t["required"]), Decimal(0))
    deferred_cost = sum((cost(t) for t in deferred), Decimal(0))
    _require(all(math.isfinite(float(v)) for v in (required_cost, additional_cost, deferred_cost,
                                                 required_cost + additional_cost)), "Aggregate estimated cost exceeds finite numeric range")
    return {"policy_version": "inspection-routing-v1", "planning_only": True,
            "inspection_execution_performed": False, "required_preserved": preserved,
            "scheduled": scheduled, "deferred": deferred,
            "followups": sorted(followups, key=lambda t: t["task_id"]), "mapping_records": mapping_records,
            "summary": {"inventory_segments": len(assets), "observations": len(normalized),
                        "resolved_observations": sum(r["location_status"] == "resolved" for r in mapping_records),
                        "unmapped_observations": sum(r["location_status"] == "unmapped" for r in mapping_records),
                        "required_tasks": len(required), "scheduled_tasks": len(scheduled),
                        "additional_scheduled_tasks": len(scheduled) - len(required),
                        "deferred_tasks": len(deferred), "followup_tasks": len(followups),
                        "required_preserved": preserved, "required_over_budget": shortfall > 0,
                        "unresolved_budget": shortfall > 0,
                        "required_unresolved_method_tasks": sum("unresolved_method" in t["flags"] for t in required),
                        "budget": None if budget_value is None else float(budget_value),
                        "required_committed_estimated_cost": float(required_cost),
                        "additional_scheduled_estimated_cost": float(additional_cost),
                        "additional_deferred_estimated_cost": float(deferred_cost),
                        "scheduled_estimated_cost": float(required_cost + additional_cost),
                        "available_for_additional_initial": None if available_initial is None else float(available_initial),
                        "budget_remaining": None if remaining is None else float(remaining),
                        "required_budget_shortfall": float(shortfall)},
            "cost_assumptions": ["All estimated costs and budget use the caller's same unspecified currency/unit.",
                                 "Required inventory costs are committed first, including unresolved inspection methods.",
                                 "Each segment is costed once; repeated observations do not add another inspection cost.",
                                 "Additional candidates are funded greedily by descending risk priority, then asset and segment IDs; unaffordable candidates remain deferred.",
                                 "Capture/mapping follow-up and additional NDT-method-review costs are unknown and excluded.",
                                 "These are planning estimates, not actual expenditures or completed inspections."],
            "limits": ["Thermal observations do not infer a defect probability, select an NDT technique, or certify safety.",
                       "No-anomaly, indeterminate, unsupported, absent and unmapped observations never clear inventory requirements.",
                       "Frame-to-location verification and its evidence are supplied by the caller; no location is inferred.",
                       "Only explicit inventory and observation fields affect routing; future NDT outcomes and ground-truth fields are not consumed."]}
