import copy

import pytest

from maek.thermal_validation import paired_change, passes_gate

NAMES = ('wet_insulation', 'insulation_damage', 'steam_leak')


def outcomes():
    return [{'hits': dict.fromkeys(NAMES, 1), 'normal': False, 'alarm': True},
            {'hits': {}, 'normal': True, 'alarm': True},
            {'hits': {}, 'normal': True, 'alarm': False}]


def test_paired_bootstrap_reproducible():
    before = outcomes()
    same = paired_change(before, before, repeats=100)
    assert same['fa_reduction']['change'] == 0
    assert same['macro_recall_change']['ci95'] == [0, 0]
    assert not passes_gate(same, 0.5)
    after = copy.deepcopy(before)
    after[1]['alarm'] = False
    result = paired_change(before, after, repeats=100)
    assert result == paired_change(before, after, repeats=100)
    assert result['fa_reduction']['change'] == 0.5
    assert passes_gate(result, 0.5)


def gate_result(fa, macro=0, wet=0):
    return {'fa_reduction': {'change': fa}, 'macro_recall_change': {'change': macro},
            'per_class_recall_change': {n: {'change': wet if i == 0 else 0}
                                       for i, n in enumerate(NAMES)}}


def test_gate_boundaries():
    assert passes_gate(gate_result(.1, -.02, -.05), .4)
    assert passes_gate(gate_result(.04), .08)
    assert not passes_gate(gate_result(.04), .1)
    assert not passes_gate(gate_result(0), 0)
    assert not passes_gate(gate_result(.2, -.021), .4)
    assert not passes_gate(gate_result(.2, 0, -.051), .4)
    assert not passes_gate(gate_result(None), .4)


def test_pair_mismatch_rejected_and_missing_class_fails():
    with pytest.raises(ValueError):
        paired_change([], [])
    after = outcomes()
    after[0]['normal'] = True
    with pytest.raises(ValueError):
        paired_change(outcomes(), after)
    missing = gate_result(.2)
    missing['per_class_recall_change'].pop('steam_leak')
    assert not passes_gate(missing, .4)


def test_split_overlap_and_duplicates_rejected():
    from scripts.evaluate_thermal_filter import assert_disjoint

    with pytest.raises(ValueError, match='overlap'):
        assert_disjoint([{'data_hashes': ['same']}], {'data_hashes': ['same']})
    with pytest.raises(ValueError, match='Duplicate'):
        assert_disjoint([], {'data_hashes': ['same', 'same']})
    assert_disjoint([{'data_hashes': ['old']}], {'data_hashes': ['new']})


def test_frozen_source_rejects_change(tmp_path):
    import json

    from scripts.evaluate_thermal_filter import verify_frozen

    (tmp_path / 'frozen.json').write_text(json.dumps({'source_hashes': {}}))
    with pytest.raises(ValueError, match='changed'):
        verify_frozen(tmp_path)
