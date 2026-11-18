# Historical reproduction only: targets pinned pre-removal builds, not the current engine.
# Buffer-shuffle requests below are retained to interpret the recorded evidence.
"""Fast red-capable reproduction of the original bucket window-label flag."""
import argparse
import csv
import hashlib
import importlib.util
import inspect
import platform
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('shuffle_diagnostic', Path(__file__).with_name('diagnose-shuffle.py'))
diag = importlib.util.module_from_spec(spec); spec.loader.exec_module(diag)


def observe(binary, root, seed, strategy='auto'):
    source = root / 'input.csv'
    job = {'input': str(source), 'output': str(root / 'output'), 'seed': seed,
           'full_shuffle_policy': 'flexible_v1',
           'operations': [{'type': 'shuffle', 'strategy': strategy, 'buffer_rows': 4}],
           'resources': {'memory_mb': 64, 'workers': 1, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
    if strategy == 'auto': job['full_shuffle_algorithm'] = 'independent_buckets_v1'
    config = root / 'job.json'; config.write_text(json.dumps(job))
    result = subprocess.run([str(binary), 'run', '--config', str(config), '--yes'], capture_output=True, text=True, timeout=120)
    if result.returncode: raise RuntimeError(result.stderr)
    groups = diag.fixture('ascending')
    orders, fingerprint = diag.verify(root / 'output', json.loads(result.stdout), groups, None)
    metric = diag.combined(orders, groups)[diag.METRICS.index('window_labels')]
    shutil.rmtree(root / 'output')
    return metric, fingerprint


def write_fixture(root):
    with (root / 'input.csv').open('w', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n'); writer.writerow(['id', 'value', 'label', 'group']); writer.writerows(diag.fixture('ascending')[0])



def load_calibration(path):
    cache = json.loads(path.read_text())
    source = ''.join(inspect.getsource(getattr(diag, name)) for name in ['fixture', 'metrics', 'discrepancy', 'combined', 'null_distribution'])
    expected = {'version': 'shuffle-diagnostic-null-v1', 'python': platform.python_version(), 'source_sha256': hashlib.sha256(source.encode()).hexdigest(), 'seeds': diag.SEEDS, 'patterns': diag.PATTERNS, 'metrics': diag.METRICS, 'pilot': diag.PILOT, 'corpora': diag.NULL_CORPORA}
    assert cache['contract'] == expected, 'null calibration contract changed'
    return cache


def compare(mean, cache):
    index = diag.METRICS.index('window_labels')
    calibration = cache['patterns']['ascending']
    departure = abs(mean - calibration['center'][index])
    return (1 + sum(abs(row[index] - calibration['center'][index]) >= departure for row in calibration['corpora'])) / (1 + len(calibration['corpora']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--null-cache', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    args = parser.parse_args()
    cache = load_calibration(args.null_cache)
    reference = {r['seed']: r for r in map(json.loads, args.reference.read_text().splitlines()) if r.get('type') == 'sample' and r['pattern'] == 'ascending' and r['algorithm'] == 'auto'}
    samples = []
    print(json.dumps({'type': 'design', 'phase': 'original-reproduction', 'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(), 'null_cache_sha256': hashlib.sha256(args.null_cache.read_bytes()).hexdigest(), 'reference_sha256': hashlib.sha256(args.reference.read_bytes()).hexdigest(), 'seeds': diag.SEEDS, 'pattern': 'ascending', 'metric': 'window_labels', 'threshold': 0.05 / 60}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-window-repro-') as directory:
        root = Path(directory); write_fixture(root)
        for seed in diag.SEEDS:
            metric, fingerprint = observe(args.binary.resolve(), root, seed)
            samples.append(metric)
            print(json.dumps({'type': 'sample', 'seed': seed, 'window_labels': metric, 'reference_fingerprint_matches': fingerprint == reference[seed]['fingerprint']}), flush=True)
    mean = statistics.mean(samples); p = compare(mean, cache); flagged = p < 0.05 / 60
    print(json.dumps({'type': 'summary', 'jobs': len(samples), 'mean': mean, 'p': p, 'flagged': flagged}), flush=True)
    raise SystemExit(1 if flagged else 0)


if __name__ == '__main__':
    main()
