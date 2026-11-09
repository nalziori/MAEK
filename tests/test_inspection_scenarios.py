import copy
import json

import pytest

from scripts.check_inspection_scenarios import SOURCE, validate


def data():
    load = lambda n: json.loads((SOURCE / n).read_text(encoding="utf-8-sig"))
    return load("inspection_scenarios.json"), load("pipe_services.json"), load("supplementary_circuits.json")


def test_available_cases():
    validate(*data())


@pytest.mark.parametrize("change,error", [("duplicate", "duplicate scenario"),
                                        ("unknown", "unknown pipe"),
                                        ("crack", "unsupported diagnosis")])
def test_reject_bad_scenarios(change, error):
    scenarios, pipes, extra = data()
    broken = copy.deepcopy(scenarios)
    if change == "duplicate":
        broken["scenarios"][1]["id"] = broken["scenarios"][0]["id"]
    elif change == "unknown":
        broken["scenarios"][0]["pipeId"] = "invented"
    else:
        next(r for r in broken["scenarios"] if r["mode"] == "ut_required")["expected"] = "rgb_crack_confirmed"
    with pytest.raises(AssertionError, match=error):
        validate(broken, pipes, extra)
