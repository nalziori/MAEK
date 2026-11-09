"""Paired image bootstrap and preregistered false-alarm reduction gates."""
from __future__ import annotations

import math
import warnings

import numpy as np

from maek.thermal_dataset import CLASS_NAMES


def paired_change(before, after, seed=19, repeats=2000):
    if not isinstance(repeats, int) or repeats <= 0:
        raise ValueError('repeats must be positive integer')
    if not before or len(before) != len(after):
        raise ValueError('Expected equally sized nonempty outcomes')
    names = CLASS_NAMES[1:]
    differences = np.full((len(before), 4), np.nan)
    for i, (old, new) in enumerate(zip(before, after)):
        if old['normal'] != new['normal'] or set(old['hits']) != set(new['hits']):
            raise ValueError('Ground-truth alignment differs')
        if set(old['hits']) - set(names):
            raise ValueError('Unknown class')
        values = [old['normal'], old['alarm'], new['alarm'],
                  *old['hits'].values(), *new['hits'].values()]
        if any(x not in (True, False, 0, 1) for x in values):
            raise ValueError('Expected binary outcomes')
        for j, name in enumerate(names):
            if name in old['hits']:
                differences[i, j] = int(new['hits'][name]) - int(old['hits'][name])
        if old['normal']:
            differences[i, 3] = int(old['alarm']) - int(new['alarm'])
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(before), size=(repeats, len(before)))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        point = np.nanmean(differences, axis=0)
        boot = np.nanmean(differences[indices], axis=1)
    macro_point = float(np.mean(point[:3]))
    macro_boot = np.mean(boot[:, :3], axis=1)

    def result(value, distribution, denominator):
        finite = distribution[np.isfinite(distribution)]
        return {'change': float(value) if math.isfinite(value) else None,
                'ci95': np.percentile(finite, [2.5, 97.5]).tolist() if len(finite) else None,
                'n': int(denominator), 'bootstrap_valid': len(finite)}

    return {'n_images': len(before), 'seed': seed, 'repeats': repeats,
            'fa_reduction': result(point[3], boot[:, 3], np.isfinite(differences[:, 3]).sum()),
            'macro_recall_change': result(macro_point, macro_boot, len(before)),
            'per_class_recall_change': {
                name: result(point[j], boot[:, j], np.isfinite(differences[:, j]).sum())
                for j, name in enumerate(names)}}


def passes_gate(changes, before_normal_fa, tolerance=1e-12):
    fa = changes['fa_reduction']['change']
    macro = changes['macro_recall_change']['change']
    per_class = changes['per_class_recall_change']
    if set(per_class) != set(CLASS_NAMES[1:]):
        return False
    values = [fa, macro, before_normal_fa] + [r['change'] for r in per_class.values()]
    if any(v is None or not math.isfinite(v) for v in values):
        return False
    return (0 <= before_normal_fa <= 1
            and (fa + tolerance >= .10
                 or (before_normal_fa > 0 and fa / before_normal_fa + tolerance >= .50))
            and macro + tolerance >= -.02
            and all(r['change'] + tolerance >= -.05 for r in per_class.values()))
