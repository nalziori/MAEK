import copy

import numpy as np
import pytest

from maek.thermal_dataset import evaluate_arrays
from scripts.evaluate_thermal_local import Accumulator, disjoint, eligible, save


def test_streaming_metrics_equal_reference():
    rng = np.random.default_rng(18)
    pairs = [(rng.integers(0, 4, (16, 20)), rng.integers(0, 4, (16, 20))) for _ in range(4)]
    pairs += [(np.zeros((16, 20), int), np.zeros((16, 20), int)),
              (np.zeros((16, 20), int), np.ones((16, 20), int))]
    acc = Accumulator()
    for truth, pred in pairs:
        acc.add(truth, pred)
    assert acc.result() == evaluate_arrays(pairs)
    assert Accumulator().result() == evaluate_arrays([])


def test_ci_gate_rejects_uncertain_recall_and_abstention():
    change = {'fa_reduction': {'change': .2, 'ci95': [.1, .3]},
              'macro_recall_change': {'change': -.01, 'ci95': [-.015, 0]},
              'per_class_recall_change': {c: {'change': -.01, 'ci95': [-.03, 0]}
                                         for c in ('wet_insulation', 'insulation_damage', 'steam_leak')}}
    assert eligible(change, .4, {'frame_abstentions': 0})
    assert not eligible(change, .4, {'frame_abstentions': 1})
    uncertain = copy.deepcopy(change)
    uncertain['per_class_recall_change']['wet_insulation']['ci95'][0] = -.06
    assert not eligible(uncertain, .4, {'frame_abstentions': 0})


def test_overwrite_and_overlap_rejected(tmp_path):
    path = tmp_path / 'result.json'
    save(path, {'original': True})
    with pytest.raises(FileExistsError):
        save(path, {'original': False})
    assert 'true' in path.read_text()
    with pytest.raises(ValueError, match='overlap'):
        disjoint([{'data_hashes': ['same']}], {'data_hashes': ['same']})
