import numpy as np
import pytest

from maek import thermal_rules


def test_steam_merge_preserves_existing_labels_and_input(monkeypatch):
    baseline = np.array([[0, 1], [2, 0]], dtype=np.uint8)
    relaxed = np.full((2, 2), 3, dtype=np.uint8)
    calls = []

    def fake_detect(cfg, temperature, pipe_mask):
        calls.append(cfg)
        return baseline if len(calls) == 1 else relaxed

    monkeypatch.setattr(thermal_rules.tr, 'detect_ir', fake_detect)
    monkeypatch.setattr(thermal_rules.params, 'with_values', lambda cfg, values: values)
    result = thermal_rules.detect_ir({}, np.zeros((2, 2)), np.ones((2, 2)), 'steam_mild')
    np.testing.assert_array_equal(result, [[3, 1], [2, 3]])
    np.testing.assert_array_equal(baseline, [[0, 1], [2, 0]])
    assert len(calls) == 2


def test_unknown_candidate_rejected():
    with pytest.raises(ValueError, match='Unknown'):
        thermal_rules.detect_ir({}, np.zeros((1, 1)), np.ones((1, 1)), 'unknown')
