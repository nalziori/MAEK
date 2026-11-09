"""Plot one metadata-selected DEV group; never load test or stress images."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

MECHANISMS = ['stable_repeat', 'wall_loss', 'external_transfer', 'reflection',
              'emissivity_change']
LABELS = ['Stable repeat', 'Wall-loss scenario', 'External transfer',
          'Reflection change', 'Emissivity change']


def preview(data, out):
    """Choose the first DEV bare/high-drive/low-emissivity scene by metadata."""
    if out.exists():
        raise FileExistsError(f'Use a fresh preview path: {out}')
    rows = []
    with (data / 'index.jsonl').open(encoding='utf-8') as source:
        for line in source:
            row = json.loads(line)
            if row['split'] == 'dev':
                rows.append(row)
    candidates = [row for row in rows if not row['factors']['insulated']
                  and row['factors']['drive_bin'] == 'high'
                  and row['factors']['emissivity_bin'] == 'low']
    if not candidates:
        raise ValueError('No DEV bare/high-drive/low-emissivity scene exists')
    group = min(row['base_scene_id'] for row in candidates)
    selected = {row['mechanism']: row for row in rows if row['base_scene_id'] == group}
    if set(selected) != set(MECHANISMS):
        raise ValueError('Selected DEV scene must contain each of the five mechanisms')
    frames = []
    for name in MECHANISMS:
        row = selected[name]
        with np.load(data / row['relative_path'], allow_pickle=False) as archive:
            frames.append({key: archive[key] for key in
                           ('reference_c', 'current_c', 'target', 'valid_mask')})
    valid_temperatures = np.concatenate([frame[key][frame['valid_mask']] for frame in frames
                                        for key in ('reference_c', 'current_c')])
    lo, hi = float(valid_temperatures.min()), float(valid_temperatures.max())
    differences = [frame['current_c'] - frame['reference_c'] for frame in frames]
    delta_max = max(float(np.max(np.abs(delta[frame['valid_mask']])))
                    for frame, delta in zip(frames, differences))
    delta_max = max(delta_max, .01)
    target_cmap = ListedColormap(['#e8edf1', '#d23e43', '#e3b44a'])
    target_norm = BoundaryNorm([-.5, .5, 1.5, 2.5], target_cmap.N)
    temp_cmap = plt.get_cmap('inferno').copy()
    delta_cmap = plt.get_cmap('RdBu_r').copy()
    temp_cmap.set_bad('#75828b')
    delta_cmap.set_bad('#75828b')
    fig, axes = plt.subplots(5, 4, figsize=(14, 13), layout='constrained')
    fig.suptitle(
        f'Synthetic registered thermal pairs | DEV {group}\n'
        'Metadata-selected example: bare pipe, high temperature drive, low emissivity\n'
        'Observation-change targets only; not crack labels or field validation',
        fontsize=14,
    )
    for i, (frame, delta, label) in enumerate(zip(frames, differences, LABELS)):
        invalid = ~frame['valid_mask']
        for j, key in enumerate(('reference_c', 'current_c')):
            temp_im = axes[i, j].imshow(np.ma.array(frame[key], mask=invalid),
                cmap=temp_cmap, vmin=lo, vmax=hi, interpolation='nearest')
        delta_im = axes[i, 2].imshow(np.ma.array(delta, mask=invalid),
            cmap=delta_cmap, vmin=-delta_max, vmax=delta_max, interpolation='nearest')
        targets = np.where(frame['target'] == 255, 2, frame['target'])
        target_im = axes[i, 3].imshow(targets, cmap=target_cmap, norm=target_norm,
                                     interpolation='nearest')
        axes[i, 0].set_ylabel(label, fontsize=11)
        for ax in axes[i]:
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
    for ax, title in zip(axes[0], ['Reference', 'Current', 'Observed current - reference',
                                  'Weak observation target']):
        ax.set_title(title, fontsize=11, pad=12)
    fig.colorbar(temp_im, ax=list(axes[:, :2].flat), location='bottom', shrink=.8,
                 label='Apparent temperature (°C) | same scale in all reference/current panels')
    fig.colorbar(delta_im, ax=list(axes[:, 2]), location='bottom', shrink=.9,
                 label='Observed difference (°C), symmetric scale')
    bar = fig.colorbar(target_im, ax=list(axes[:, 3]), location='bottom', shrink=.9,
                       ticks=[0, 1, 2])
    bar.ax.set_xticklabels(['0: no resolved\nchange', '1: resolved\nchange', '255: ignore'],
                           fontsize=8)
    bar.set_label('No-change does not mean defect-free')
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, facecolor='white')
    plt.close(fig)
    print(json.dumps({'preview': str(out.resolve()), 'split': 'dev', 'scene': group,
                      'loaded_pairs': len(frames), 'temperature_range_c': [lo, hi],
                      'symmetric_delta_range_c': [-delta_max, delta_max]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    preview(args.data, args.out)
