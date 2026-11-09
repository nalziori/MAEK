"""Compare saved thermal detectors and benchmark the trained inference pipeline on CPU."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '1'


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def sources():
    files = ['maek/thermal_learned.py', 'maek/thermal_dataset.py', 'maek/thermal_render.py',
             'maek/thermal_filter.py', 'maek/thermal_validation.py', 'maek/onboard_models.py',
             'scripts/compare_trained_thermal.py', 'scripts/benchmark_models.py',
             'config/default.yaml']
    return {name: sha(ROOT / name) for name in files}


def save(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, indent=2, allow_nan=False)


def dataset(archive, split):
    from maek.thermal_dataset import load_zip
    if split == 'val':
        yield from load_zip(archive, 'train', 'val')
    elif split == 'shifted':
        for part in ('train', 'val'):
            yield from load_zip(archive, 'shifted', part)
    else:
        raise ValueError(split)


def thread_check():
    import cv2
    import torch
    if torch.get_num_threads() != 1 or torch.get_num_interop_threads() != 1:
        raise RuntimeError('Requested PyTorch CPU thread counts changed')
    if cv2.getNumThreads() != 1:
        raise RuntimeError('OpenCV CPU thread count changed')


def evaluate(args):
    import numpy as np

    from maek import params
    from maek import thermal_render as tr
    from maek.thermal_dataset import CLASS_NAMES, evaluate_arrays
    from maek.thermal_filter import filter_wet_components
    from maek.thermal_learned import PREDICT, ThermalYOLO, paired_iou_change
    from maek.thermal_validation import paired_change

    if (args.out / 'comparison.json').exists():
        raise FileExistsError('Comparison already exists')
    frozen = sources()
    metadata = {'weights_sha256': sha(args.weights), 'archive_sha256': sha(args.archive),
                'source_hashes': frozen, 'predict': PREDICT, 'temperature_range_c': [-40, 200],
                'protocol_sha256': sha(args.out / 'protocol.md')}
    first = next(dataset(args.archive, 'val'))
    model = ThermalYOLO(args.weights, first['temperature'])
    cfg = params.load_config()
    results, rows = {}, []
    for split, expected in (('val', 188), ('shifted', 300)):
        pairs = {name: [] for name in ('rules', 'rules_filtered', 'trained_yolo')}
        counts = {name: [] for name in pairs}
        ids, hashes = [], []
        for i, sample in enumerate(dataset(args.archive, split)):
            t, truth = sample['temperature'], sample['mask']
            pipe = tr.pipe_mask(sample['job'])
            baseline = tr.detect_ir(cfg, t, pipe)
            predictions = {'rules': baseline,
                           'rules_filtered': filter_wet_components(
                               t, pipe, baseline, 'wet_width14_area100'),
                           'trained_yolo': model.predict(t)}
            ids.append(f"{sample['job']['condition']}:{sample['job']['job_id']}")
            hashes.append(hashlib.sha256(t.tobytes() + truth.tobytes()).hexdigest())
            for name, prediction in predictions.items():
                pairs[name].append((truth, prediction))
                counts[name].append([[int(((truth == c) & (prediction == c)).sum()),
                                      int(((truth == c) | (prediction == c)).sum())]
                                     for c in range(1, 4)])
            if (i + 1) % 50 == 0:
                print(split, i + 1, '/', expected, flush=True)
        if len(ids) != expected or len(set(ids)) != expected or len(set(hashes)) != expected:
            raise ValueError('Sample counts or uniqueness failed')
        metrics = {name: evaluate_arrays(items) for name, items in pairs.items()}
        comparisons = {}
        for reference in ('rules', 'rules_filtered'):
            change = paired_change(metrics[reference]['sample_outcomes'],
                                   metrics['trained_yolo']['sample_outcomes'])
            change['pixel_iou_change'] = paired_iou_change(counts[reference], counts['trained_yolo'])
            comparisons[reference] = change
        results[split] = {'sample_ids': ids, 'data_hashes': hashes, 'metrics': metrics,
                          'trained_minus_reference': comparisons}
        np.savez_compressed(args.out / f'{split}-predictions.npz',
                            ids=np.asarray(ids), truth=np.asarray([x[0] for x in pairs['rules']]),
                            **{name: np.asarray([x[1] for x in items])
                               for name, items in pairs.items()})
        for method, m in metrics.items():
            macro = sum(m['classes'][c]['image_recall'] for c in CLASS_NAMES[1:]) / 3
            for cls, values in m['classes'].items():
                rows.append({'split': split, 'method': method, 'class': cls, **values,
                             'macro_image_recall': macro, 'normal_images': m['normal_images'],
                             'normal_false_alarms': m['normal_false_alarms'],
                             'normal_false_alarm_rate': m['normal_image_false_alarm_rate']})
        print(split, 'evaluated', flush=True)
    if set(results['val']['data_hashes']) & set(results['shifted']['data_hashes']):
        raise ValueError('Identical images across evaluation sets')
    thread_check()
    if sources() != frozen:
        raise ValueError('Source changed during evaluation')
    save(args.out / 'comparison.json', {**metadata, 'results': results})
    with (args.out / 'thermal-performance.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def worker(args):
    import gc
    import platform

    import numpy as np
    import psutil
    import torch
    import ultralytics

    from maek.thermal_learned import PREDICT, ThermalYOLO
    from scripts.benchmark_models import measure

    rng = np.random.default_rng(20261107)
    samples = []
    for split, count in (('val', 188), ('shifted', 300)):
        indices = set(rng.choice(count, 12, replace=False).tolist())
        for i, sample in enumerate(dataset(args.archive, split)):
            if i in indices:
                samples.append(sample)
    del sample
    inputs = [s['temperature'] for s in samples]
    input_ids = [f"{s['job']['condition']}:{s['job']['job_id']}" for s in samples]
    del samples
    gc.collect()
    process = psutil.Process()
    pre_model_rss = process.memory_info().rss / 2**20
    model = ThermalYOLO(args.weights, inputs[0])
    if model.model is not model.yolo.predictor.model.backend.model:
        raise ValueError('Timed model differs from the active predictor backend')
    tensors = [model.tensor(t) for t in inputs]
    if not all(tuple(t.shape) == (1, 3, 256, 320) and t.dtype == torch.float32
               and t.device.type == 'cpu' for t in tensors):
        raise ValueError('Unexpected actual predictor input tensors')
    expected = model.predict(inputs[0])
    loaded_rss = process.memory_info().rss / 2**20

    def forward(i):
        with torch.inference_mode():
            return model.model(tensors[i % len(tensors)])

    def end_to_end(i):
        return model.predict(inputs[i % len(inputs)])

    timings = {}
    for name, fn in (('model_only', forward), ('end_to_end', end_to_end)):
        for i in range(10):
            fn(i)
        thread_check()
        # Warmup already completed; zero here avoids doing it twice.
        timings[name] = measure(fn, 0, 100, process)
        thread_check()
    if not np.array_equal(expected, model.predict(inputs[0])):
        raise ValueError('Prediction changed across timed scopes')
    memory = process.memory_info()
    return {'run': args.run, 'model': 'MAEK-trained YOLO11n-seg', 'batch': 1,
            'torch_threads': torch.get_num_threads(), 'torch_interop_threads': 1,
            'cv2_threads': 1, 'dtype': 'float32', 'device': 'cpu', 'predict': PREDICT,
            'actual_tensor_shape': list(tensors[0].shape), 'warmup_per_scope': 10,
            'model_only_is_predictor_backend': True,
            'active_batchnorm_layers': sum(isinstance(m, torch.nn.BatchNorm2d)
                                           for m in model.model.modules()),
            'repeats_per_scope': 100, 'input_ids': input_ids,
            'input_sha256': [hashlib.sha256(t.tobytes()).hexdigest() for t in inputs],
            'weights_sha256': sha(args.weights), 'weights_mib': args.weights.stat().st_size / 2**20,
            'archive_sha256': sha(args.archive), 'source_hashes': sources(),
            'pre_model_rss_mib': pre_model_rss, 'loaded_rss_mib': loaded_rss,
            'process_lifetime_peak_wset_mib': getattr(memory, 'peak_wset', 0) / 2**20 or None,
            'rss_sampling_ms': 5, 'file_io_included': False,
            'scope_note': 'E2E Celsius array -> fixed RGB -> predict -> semantic mask; '
                          'model_only uses actual predictor letterbox tensors; RSS is process-wide',
            'python': platform.python_version(), 'torch': torch.__version__,
            'ultralytics': ultralytics.__version__, 'numpy': np.__version__,
            'processor': os.environ.get('PROCESSOR_IDENTIFIER'),
            'logical_cpus': psutil.cpu_count(), 'physical_cpus': psutil.cpu_count(logical=False),
            'system_memory_mib': psutil.virtual_memory().total / 2**20,
            'available_memory_end_mib': psutil.virtual_memory().available / 2**20,
            **timings}


def benchmark(args):
    if (args.out / 'cpu-runs.json').exists():
        raise FileExistsError('Benchmark already exists')
    comparison = json.loads((args.out / 'comparison.json').read_text())
    if (comparison['source_hashes'] != sources()
            or comparison['weights_sha256'] != sha(args.weights)
            or comparison['archive_sha256'] != sha(args.archive)
            or comparison['protocol_sha256'] != sha(args.out / 'protocol.md')):
        raise ValueError('Comparison and benchmark inputs changed')
    runs = []
    for run in range(1, 4):
        cmd = [sys.executable, str(Path(__file__).resolve()), '--mode', 'worker',
               '--run', str(run), '--archive', str(args.archive.resolve()),
               '--weights', str(args.weights.resolve()), '--out', str(args.out.resolve())]
        child = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if child.returncode:
            raise RuntimeError(child.stderr + child.stdout)
        result = json.loads(child.stdout.strip().splitlines()[-1])
        save(args.out / f'cpu-run-{run}.json', result)
        runs.append(result)
        print('CPU run', run, 'E2E p50/p95', result['end_to_end']['p50_ms'],
              result['end_to_end']['p95_ms'], flush=True)
    save(args.out / 'cpu-runs.json', runs)
    rows = [{'run': r['run'], 'scope': s, **{k: v for k, v in r[s].items()
                                          if k not in ('latencies_ms', 'rss_errors')}}
            for r in runs for s in ('model_only', 'end_to_end')]
    with (args.out / 'cpu-speed.csv').open('x', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('evaluate', 'benchmark', 'worker'), required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--run', type=int, default=1)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.mode == 'worker':
        print(json.dumps(worker(args), allow_nan=False))
    elif args.mode == 'evaluate':
        evaluate(args)
    else:
        benchmark(args)


if __name__ == '__main__':
    main()
