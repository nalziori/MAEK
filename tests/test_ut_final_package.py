"""Check evidence consistency without requiring optional torch in the core CI."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'UT'


def test_final_manifest_matches_checked_in_artifacts():
    manifest = json.loads((ROOT / 'final_manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT)
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name


def test_crack_counts_match_individual_frozen_decisions():
    results = json.loads((ROOT / 'crack_mlp/run/results.json').read_text())['results']
    for source, models in results.items():
        with (ROOT / f'crack_mlp/run/fresh_{source}_predictions.csv').open(newline='') as f:
            rows = list(csv.DictReader(f))
        positives = [r for r in rows if r['crack'].lower() in {'true', '1', '1.0'}]
        normals = [r for r in rows if r['crack'].lower() not in {'true', '1', '1.0'}]

        def hit(row):
            return row['mlp_prediction'].lower() in {'true', '1', '1.0'}
        actual = models['mlp']
        assert len(positives) == actual['positive_units'] == 1200
        assert len(normals) == actual['normal_units'] == 1200
        assert sum(hit(r) for r in positives) == actual['tp']
        assert sum(hit(r) for r in normals) == actual['fp']


def test_pit_notebook_is_marked_as_saved_output_not_replay():
    report = json.loads((ROOT / 'reports/pit_notebook_saved_results.json').read_text())
    raw = (ROOT / report['source']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report['source_sha256']
    assert report['evidence_level'] == 'saved_notebook_output_only_not_replayed'
    notebook = json.loads(raw)
    cell = notebook['cells'][report['cell_index_zero_based']]
    text = json.dumps(cell['outputs'])
    assert '0.98775' in text and '0.95475' in text and '2/4000' in text
    for row in report['results'].values():
        assert row['tp'] / row['positive_units'] == row['recall']
        assert row['fp'] / row['normal_units'] == row['far']


def test_public_candidates_are_not_claimed_as_final_training_data():
    registry = json.loads((ROOT / 'datasets/registry.json').read_text(encoding='utf-8'))
    assert registry['count'] == len(registry['files'])
    assert registry['total_bytes'] == sum(row['bytes'] for row in registry['files'])
    public = [r for r in registry['files'] if '/public_candidates/' in r['path']]
    assert public
    assert all(r['role'] == 'public_candidate_not_used_for_final_MLP' for r in public)
