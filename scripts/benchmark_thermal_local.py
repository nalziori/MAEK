"""PC-only thermal rule cost comparison; never evidence of Jetson performance.

Run only after accuracy experiments and other benchmark workers have stopped:
  .venv-benchmark/Scripts/python.exe scripts/benchmark_thermal_local.py \
      --protocol PATH/TO/protocol.json --out NEW_OUTPUT_DIRECTORY

Three fresh sequential processes each measure baseline plus all three frozen
candidates. Rendering, quantization and file I/O are outside the timed scope.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THREAD_VARIABLES = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')
LABEL = 'PConly_notJetson'
SCOPE = 'temperature_to_mask_quality'
POLICY = {'seed': 20261121, 'source_count': 160, 'condition': 'dr', 'input_count': 12,
          'warmup': 3, 'repeats': 24, 'fresh_processes': 3, 'batch_size': 1,
          'shape_hw': [256, 320], 'thread_environment': 1, 'baseline_reuse': False,
          'scope': SCOPE, 'candidate_order': 'frozen registry order in each process',
          'excluded': ['render', 'quantization', 'file_io'],
          'included': ['input quality checks', 'full baseline', 'candidate',
                       'quality reference append'],
          'memory': '10ms sampled absolute process RSS; includes inputs/runtime/setup and '
                    'retained allocator memory from earlier candidates; not incremental RSS',
          'external_validation': False, 'hardware_label': LABEL}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def source_hashes(protocol):
    names = set(protocol['source_hashes']) | {
        'scripts/benchmark_thermal_local.py', 'maek/jetson_benchmark.py',
        'maek/onboard_models.py'}
    return {name: sha(ROOT / name) for name in sorted(names)}


def checked_protocol(path):
    protocol = read(path)
    if protocol['splits']['develop'] != [POLICY['seed'], POLICY['source_count'], 'dr']:
        raise ValueError('Expected frozen development seed20261121/count160/dr')
    hashes = source_hashes(protocol)
    if any(hashes[name] != expected for name, expected in protocol['source_hashes'].items()):
        raise ValueError('Frozen accuracy source has changed')
    return protocol, hashes


def quality_counts(qualities):
    return {'frames': len(qualities),
            'frame_abstentions': sum(q.status == 'abstain' for q in qualities),
            'reasons': dict(Counter(reason for q in qualities for reason in q.reasons)),
            'saturated_frames': sum(q.saturated_pixels > 0 for q in qualities),
            'local_support_frames': sum(q.abstained_components > 0 for q in qualities),
            'local_support_components': sum(q.abstained_components for q in qualities),
            'local_support_pixels': sum(q.abstained_pixels for q in qualities),
            'boundary_pixels': sum(q.boundary_pixels for q in qualities),
            'removed_components': sum(q.removed_components for q in qualities)}


def worker(args):
    # Set before importing NumPy or any renderer/numerical module, including directly
    # invoked --worker processes. No torch/GPU setup is needed by this CPU detector.
    for name in THREAD_VARIABLES:
        os.environ[name] = '1'
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import psutil

    from maek.jetson_benchmark import array_hash, measure
    from maek.thermal_local_contrast import CANDIDATES, detect_ir
    from scripts.diagnose_thermal_components import samples

    destination = args.out / f'run-{args.worker}.json'
    if destination.exists():
        raise FileExistsError(destination)
    protocol, hashes = checked_protocol(args.protocol)
    benchmark_protocol = read(args.out / 'benchmark-protocol.json')
    if (benchmark_protocol['source_hashes'] != hashes
            or benchmark_protocol['accuracy_protocol_sha256'] != sha(args.protocol)
            or benchmark_protocol['policy'] != POLICY):
        raise ValueError('Worker protocol drift')
    if {name: asdict(c) for name, c in CANDIDATES.items()} != protocol['candidates']:
        raise ValueError('Candidate registry differs from frozen protocol')
    inputs, input_hashes, identities, evaluation_hashes = [], [], [], []
    for item in islice(samples(POLICY['seed'], POLICY['source_count'], 'dr'), 12):
        temp, pipe = item['temperature'], item['pipe']
        raw = np.clip(np.rint((temp + 50) * 100), 0, 65535).astype(np.uint16)
        if list(temp.shape) != POLICY['shape_hw']:
            raise ValueError('Expected 320x256 thermal input')
        inputs.append((temp, pipe, raw))
        input_hashes.append({key: array_hash(value) for key, value in
                             zip(('temperature', 'pipe', 'raw_uint16'), inputs[-1])})
        evaluation_hashes.append(hashlib.sha256(
            raw.tobytes() + item['mask'].tobytes() + pipe.tobytes()).hexdigest())
        identities.append(item['job']['job_id'])
    if len(inputs) != 12 or len(set(evaluation_hashes)) != 12:
        raise ValueError('Expected 12 distinct prepared inputs')
    development_path = args.protocol.parent / 'develop.json'
    development_match = None
    if development_path.exists():
        development_match = evaluation_hashes == read(development_path)['data_hashes'][:12]
        if not development_match:
            raise ValueError('Prepared inputs differ from development first12')
    try:
        from threadpoolctl import threadpool_info
        pools = threadpool_info()
        if any(p['num_threads'] != 1 for p in pools):
            raise ValueError('A numerical thread pool is not limited to one thread')
    except ImportError:
        pools = None  # Environment limit recorded; actual native pool count unverified.
    environment = {'python': platform.python_version(), 'executable': sys.executable,
                   'numpy': np.__version__, 'psutil': psutil.__version__,
                   'hostname': platform.node(), 'cpu': platform.processor(),
                   'machine': platform.machine(), 'platform': platform.platform(),
                   'logical_cpus': psutil.cpu_count(),
                   'physical_cpus': psutil.cpu_count(logical=False),
                   'thread_environment': {n: os.environ[n] for n in THREAD_VARIABLES},
                   'native_threadpools': pools,
                   'native_threadpool_check': 'verified' if pools else 'unavailable_or_no_pools',
                   'pid': os.getpid()}
    results = {}
    for name in CANDIDATES:
        qualities = []

        def invoke(index, candidate_name=name, quality_log=qualities):
            temp, pipe, raw = inputs[index % len(inputs)]
            result = detect_ir(protocol['config'], temp, pipe, candidate_name, raw_uint16=raw)
            quality_log.append(result.quality)

        stats = measure(invoke, lambda: None, POLICY['warmup'], POLICY['repeats'])
        if len(qualities) != POLICY['warmup'] + POLICY['repeats']:
            raise ValueError('Unexpected invocation count')
        results[name] = {'scope': SCOPE, 'stats': stats,
                         'quality': quality_counts(qualities[POLICY['warmup']:]),
                         'warmup_quality': quality_counts(qualities[:POLICY['warmup']])}
        print(f'run {args.worker}: {name} measured', flush=True)
    after_hashes = [{key: array_hash(value) for key, value in
                     zip(('temperature', 'pipe', 'raw_uint16'), values)} for values in inputs]
    if input_hashes != after_hashes or hashes != source_hashes(protocol):
        raise ValueError('Inputs or source mutated during measurement')
    save(destination, {'schema': 'maek-local-pc-v1', 'hardware_label': LABEL,
                       'run': args.worker, 'environment': environment, 'policy': POLICY,
                       'accuracy_protocol_sha256': sha(args.protocol),
                       'source_hashes': hashes, 'input_hashes': input_hashes,
                       'input_identities': identities, 'evaluation_hashes': evaluation_hashes,
                       'matches_development_first12': development_match, 'results': results})


def collect(out, expected_hashes, accuracy_hash):
    sys.path.insert(0, str(ROOT))
    from maek.onboard_models import summarize

    runs = [read(out / f'run-{run}.json') for run in (1, 2, 3)]
    reference = runs[0]
    fields = ('input_hashes', 'input_identities', 'evaluation_hashes', 'policy')
    if len({r['environment']['pid'] for r in runs}) != 3:
        raise ValueError('Workers did not report distinct process IDs')
    table = []
    for index, run in enumerate(runs, 1):
        if (run['run'] != index or run['source_hashes'] != expected_hashes
                or run['accuracy_protocol_sha256'] != accuracy_hash
                or run['hardware_label'] != LABEL
                or any(run[key] != reference[key] for key in fields)
                or list(run['results']) != list(reference['results'])):
            raise ValueError('Mixed worker inputs, sources or protocol')
        for name, result in run['results'].items():
            stats = result['stats']
            rebuilt = summarize(stats['latencies_ms'], stats['elapsed_s'], None)
            if (len(stats['latencies_ms']) != POLICY['repeats']
                    or result['quality']['frames'] != POLICY['repeats']
                    or any(abs(stats[k] - rebuilt[k]) > 1e-8 for k in
                           ('p50_ms', 'p95_ms', 'throughput_per_s'))):
                raise ValueError('Invalid raw latency/count summary')
            table.append({'hardware_label': LABEL, 'candidate': name, 'run': index,
                          'scope': SCOPE, **{k: stats[k] for k in
                          ('p50_ms', 'p95_ms', 'throughput_per_s', 'process_peak_rss_mib',
                           'system_min_available_mib')},
                          'frame_abstentions': result['quality']['frame_abstentions']})
    aggregate = {}
    for name in reference['results']:
        rows = [row for row in table if row['candidate'] == name]
        rss = [row['process_peak_rss_mib'] for row in rows]
        aggregate[name] = {
            'median_run_p50_ms': statistics.median(r['p50_ms'] for r in rows),
            'worst_run_p95_ms': max(r['p95_ms'] for r in rows),
            'median_run_throughput_per_s': statistics.median(r['throughput_per_s'] for r in rows),
            'maximum_process_peak_rss_mib': max(rss) if all(r is not None for r in rss) else None,
            'frame_abstentions': sum(r['frame_abstentions'] for r in rows)}
    baseline = aggregate['baseline']
    for row in aggregate.values():
        row['median_p50_delta_from_baseline_ms'] = (
            row['median_run_p50_ms'] - baseline['median_run_p50_ms'])
    save(out / 'summary.json', {'hardware_label': LABEL, 'policy': POLICY,
                               'aggregate': aggregate, 'runs': runs})
    with (out / 'summary.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True,
                        help='Frozen evaluate_thermal_local.py protocol.json')
    parser.add_argument('--out', type=Path, required=True, help='New output directory; no overwrite')
    parser.add_argument('--worker', type=int, choices=(1, 2, 3), help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.protocol, args.out = args.protocol.resolve(), args.out.resolve()
    if args.worker is not None:
        worker(args)
        return
    _, hashes = checked_protocol(args.protocol)
    accuracy_hash = sha(args.protocol)
    args.out.mkdir(parents=True, exist_ok=False)
    save(args.out / 'benchmark-protocol.json', {
        'policy': POLICY, 'source_hashes': hashes,
        'accuracy_protocol': str(args.protocol), 'accuracy_protocol_sha256': accuracy_hash})
    environment = {**os.environ, **{name: '1' for name in THREAD_VARIABLES}}
    for run in (1, 2, 3):
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--protocol',
                        str(args.protocol), '--out', str(args.out), '--worker', str(run)],
                       cwd=ROOT, env=environment, check=True)
    collect(args.out, hashes, accuracy_hash)
    print(f'{LABEL}: {args.out / "summary.json"}', flush=True)


if __name__ == '__main__':
    main()
