import copy
import random

import pytest

from maek.inspection_routing import plan_inspections


def asset(asset_id="A", segment_id="S", **updates):
    return {"asset_id": asset_id, "segment_id": segment_id, "mandatory": False,
            "high_risk": False, "risk_priority": 1., "estimated_cost": 10.,
            "inspection_plan_ref": "existing-plan", **updates}


def observation(oid="o1", frame="f1", status="anomaly_observed", **updates):
    return {"observation_id": oid, "frame_id": frame, "assessment_status": status,
            "quality_flags": [], "evidence_refs": [f"evidence:{oid}"], **updates}


def mapping(frame="f1", asset_id="A", segment_id="S", **updates):
    return {"frame_id": frame, "asset_id": asset_id, "segment_id": segment_id,
            "verified": True, "evidence_ref": f"location:{frame}", **updates}


def test_required_inventory_survives_no_observations_zero_budget_and_missing_method():
    inventory = [asset(mandatory=True, inspection_plan_ref=None),
                 asset("B", high_risk=True, estimated_cost=20), asset("C")]
    result = plan_inspections(inventory, [], [], budget=0)
    assert {(t["asset_id"], t["segment_id"]) for t in result["scheduled"]} == {("A", "S"), ("B", "S")}
    assert result["required_preserved"] and result["summary"]["required_preserved"]
    assert result["summary"]["required_budget_shortfall"] == 30
    assert result["summary"]["required_over_budget"] and result["summary"]["unresolved_budget"]
    assert result["summary"]["required_unresolved_method_tasks"] == 1
    tasks = {t["asset_id"]: t for t in result["scheduled"]}
    assert tasks["A"]["action"] == "required_inspection_pending_method_review"
    assert "unresolved_method" in tasks["A"]["flags"]
    assert tasks["B"]["action"] == "existing_inspection_plan_pending_execution"
    assert not result["inspection_execution_performed"]


def test_same_segment_merges_multiple_observations_without_double_cost():
    observations = [observation(), observation("o2", status="no_anomaly_observed"),
                    observation("o3", "f2", "indeterminate", quality_flags=["blur"])]
    result = plan_inspections([asset(mandatory=True)], observations, [mapping(), mapping("f2")], budget=10)
    assert len(result["scheduled"]) == 1
    task = result["scheduled"][0]
    assert task["observation_ids"] == ["o1", "o2", "o3"]
    assert task["evidence_refs"] == ["evidence:o1", "evidence:o2", "evidence:o3"]
    assert task["mapping_evidence_refs"] == ["location:f1", "location:f2"]
    assert task["quality_flags"] == ["blur"]
    assert task["ndt_method_review_required"] and task["required"]
    assert "no_anomaly_does_not_clear_inventory_risk" in task["reasons"]
    assert result["summary"]["scheduled_estimated_cost"] == 10
    assert result["followups"][0]["action"] == "followup_capture_review"


def test_greedy_budget_preserves_unaffordable_candidates_and_unlimited_option():
    inventory = [asset("R", mandatory=True, estimated_cost=5),
                 asset("A", risk_priority=10, estimated_cost=6),
                 asset("B", risk_priority=2, estimated_cost=5)]
    observations = [observation("oa", "fa"), observation("ob", "fb")]
    mappings = [mapping("fa", "A"), mapping("fb", "B")]
    result = plan_inspections(inventory, observations, mappings, budget=10)
    assert [t["asset_id"] for t in result["scheduled"]] == ["R", "B"]
    assert [t["asset_id"] for t in result["deferred"]] == ["A"]
    assert result["deferred"][0]["status"] == "deferred"
    assert result["deferred"][0]["action"] == "inspection_review_pending_ndt_method_review"
    assert result["summary"]["budget_remaining"] == 0
    unlimited = plan_inspections(inventory, observations, mappings)
    assert [t["asset_id"] for t in unlimited["scheduled"]] == ["R", "A", "B"]
    assert unlimited["deferred"] == [] and unlimited["summary"]["budget"] is None
    assert result["deferred"][0]["task_id"] == unlimited["scheduled"][1]["task_id"]


def test_cross_asset_same_segment_id_never_causes_bad_join():
    result = plan_inspections([asset("A"), asset("B", mandatory=True)], [observation()], [mapping(asset_id="A")])
    tasks = {t["asset_id"]: t for t in result["scheduled"]}
    assert tasks["A"]["observation_ids"] == ["o1"] and tasks["B"]["observation_ids"] == []
    assert tasks["A"]["task_id"] != tasks["B"]["task_id"]


@pytest.mark.parametrize(("mapping_rows", "reason"), [
    ([], "missing_mapping"),
    ([mapping(verified=False)], "unverified_mapping"),
    ([mapping(evidence_ref="")], "missing_mapping_evidence"),
    ([mapping(asset_id="unknown")], "unknown_inventory_location"),
    ([mapping(), mapping(asset_id="B", verified=False)], "ambiguous_mapping"),
    ([mapping(), mapping(asset_id=None)], "incomplete_mapping_location"),
])
def test_unresolved_mapping_never_assigns_guessed_location(mapping_rows, reason):
    result = plan_inspections([asset()], [observation()], mapping_rows)
    assert result["scheduled"] == [] and result["deferred"] == []
    record = result["mapping_records"][0]
    assert record["reason"] == reason and record["location_status"] == "unmapped"
    assert record["asset_id"] is None and record["segment_id"] is None
    assert result["followups"][0]["asset_id"] is None


@pytest.mark.parametrize("status", ["indeterminate", "unsupported_domain"])
def test_uncertainty_requires_capture_review_without_marking_normal(status):
    result = plan_inspections([asset(high_risk=True)], [observation(status=status)], [mapping()])
    assert result["scheduled"][0]["required"]
    assert result["followups"][0]["assessment_statuses"] == [status]
    assert result["followups"][0]["action"] == "followup_capture_review"
    unmapped = plan_inspections([asset()], [observation(status=status)], [])
    assert {t["action"] for t in unmapped["followups"]} == {"followup_capture_review", "verify_frame_location_before_routing"}
    assert all(t["asset_id"] is None for t in unmapped["followups"])


def test_permutation_invariance_input_immutability_and_duplicate_frame_observations():
    inventory = [asset("B", risk_priority=2), asset("A", risk_priority=2), asset("R", mandatory=True)]
    observations = [observation("o2", "f2"), observation("o1", "f1"),
                    observation("o3", "f1", "unsupported_domain")]
    mappings = [mapping("f2", "B"), mapping("f1", "A"), mapping("f1", "A")]
    originals = copy.deepcopy((inventory, observations, mappings))
    expected = plan_inspections(inventory, observations, mappings, budget=20)
    assert (inventory, observations, mappings) == originals
    for seed in range(8):
        changed = copy.deepcopy(originals)
        rng = random.Random(seed)
        for rows in changed:
            rng.shuffle(rows)
        assert plan_inspections(*changed, budget=20) == expected
    assert [t["asset_id"] for t in expected["scheduled"]] == ["R", "A"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "10"])
def test_malformed_cost_and_budget_are_rejected(bad):
    with pytest.raises(ValueError):
        plan_inspections([asset(estimated_cost=bad)], [], [])
    with pytest.raises(ValueError):
        plan_inspections([asset()], [], [], budget=bad)


def test_duplicate_inventory_and_duplicate_observation_ids_fail():
    with pytest.raises(ValueError, match="Duplicate inventory"):
        plan_inspections([asset(), asset()], [], [])
    for second in (observation(), observation(status="no_anomaly_observed")):
        with pytest.raises(ValueError, match="Duplicate observation_id"):
            plan_inspections([asset()], [observation(), second], [mapping()])
    with pytest.raises(ValueError, match="mandatory"):
        plan_inspections([asset(mandatory=1)], [], [])
    with pytest.raises(ValueError, match="risk_priority"):
        plan_inspections([asset(risk_priority=float("nan"))], [], [])


def test_ground_truth_and_future_ndt_fields_do_not_change_routing():
    inventory, observations, mappings = [asset(mandatory=True)], [observation(status="no_anomaly_observed")], [mapping()]
    expected = plan_inspections(inventory, observations, mappings)
    inventory[0].update(ground_truth_crack=False, ndt_status="passed", safe=True)
    observations[0].update(ground_truth_wall_loss=0, ndt_result="negative", defect_probability=0)
    mappings[0]["automatically_inferred_location"] = "B"
    assert plan_inspections(inventory, observations, mappings) == expected


def test_decimal_cost_accounting_and_aggregate_overflow_guard():
    inventory = [asset("A", mandatory=True, estimated_cost=.1), asset("B", high_risk=True, estimated_cost=.2)]
    result = plan_inspections(inventory, [], [], budget=.3)
    assert result["summary"]["required_committed_estimated_cost"] == .3
    assert not result["summary"]["required_over_budget"]
    with pytest.raises(ValueError, match="Aggregate"):
        plan_inspections([asset("A", mandatory=True, estimated_cost=1e308),
                          asset("B", mandatory=True, estimated_cost=1e308)], [], [])
