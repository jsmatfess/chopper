"""Compare native builds across input shapes; verify every logical output.

Warm-cache experiments, not a calibrated automatic policy or a scale certificate.
Fixtures, spills and outputs are isolated and removed. JSONL goes to stdout.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
    partition = {'type': 'partition', 'columns': ['key']}
    assign = {'type': 'assign', 'groups': [{'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}]}
    # name, rows, payload width, extra short columns, group shape, pipeline, memory
    cases = [
        ('stream_narrow', 100000, 0, 0, 'few', [], 32),
        ('resident_shuffle', 10000, 16, 0, 'few', [shuffle], 256),
        ('shuffle_many_columns', 60000, 0, 32, 'few', [shuffle], 32),
        ('shuffle_wide', 10000, 4096, 0, 'few', [shuffle], 32),
        ('partition_few', 120000, 64, 0, 'few', [partition], 32),
        ('partition_skew', 120000, 64, 0, 'skew', [partition], 32),
        ('partition_many', 120000, 64, 0, 'many', [partition], 32),
        ('partition_late_keys', 120000, 64, 0, 'late', [partition], 32),
        ('assign', 120000, 64, 0, 'few', [assign], 32),
        ('partition_assign', 120000, 64, 0, 'few', [partition, assign], 32),
        ('stratified_assign', 120000, 64, 0, 'few', [{**assign, 'strata': ['key']}], 32),
    ]
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'repeats': args.repeats,
                      'binary_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in [('before', args.before), ('after', args.after)]}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-adaptive-', dir=args.work_dir) as directory:
        root = Path(directory)
        for name, rows, width, columns, shape, operations, memory in cases:
            source = root / 'input.csv'
            with source.open('w', newline='', encoding='utf-8') as out:
                writer = csv.writer(out, lineterminator='\n')
                writer.writerow(['id', 'key', 'payload'] + [f'c{i}' for i in range(columns)])
                for i in range(rows):
                    key = i % 3
                    if shape == 'many' or (shape == 'late' and i >= rows * 3 // 4):
                        key = i % 128
                    elif shape == 'skew':
                        key = 0 if i % 100 else i % 3
                    # Include quoting, multiline records and Unicode in every shape.
                    payload = 'x' * width + ('界,"\n' if i % 1009 == 0 else '')
                    writer.writerow([i, key, payload] + [str((i + c) % 10) for c in range(columns)])
            reference = None
            times = {'before': [], 'after': []}
            for repeat in range(args.repeats):
                builds = [('before', args.before), ('after', args.after)]
                if repeat % 2:
                    builds.reverse()
                for label, binary in builds:
                    output = root / 'output'
                    job = {'input': str(source), 'output': str(output), 'seed': 'adaptive-benchmark',
                           'operations': operations, 'resources': {'memory_mb': memory, 'workers': 1,
                           'max_record_bytes': 1048576, 'temp_dir': str(root)}}
                    config = root / 'job.json'
                    config.write_text(json.dumps(job))
                    start = time.perf_counter()
                    result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'],
                                            capture_output=True, text=True, timeout=180)
                    elapsed = time.perf_counter() - start
                    if result.returncode:
                        raise RuntimeError(f'{name}/{label}: {result.stderr}')
                    analysis = json.loads(result.stdout)
                    actual = pipelines.fingerprint(output, analysis, 'none')
                    if reference is None:
                        reference = actual
                    if reference != actual:
                        raise AssertionError(f'Output mismatch: {name}/{label}')
                    times[label].append(elapsed)
                    print(json.dumps({'type': 'measurement', 'case': name, 'build': label, 'repeat': repeat + 1,
                                      'rows': rows, 'input_bytes': source.stat().st_size, 'memory_mb': memory,
                                      'seconds': elapsed, 'analysis_seconds': analysis['analysis_seconds'],
                                      'peak_temp_bytes': analysis['peak_temp_bytes'], 'diagnostics': analysis['diagnostics'],
                                      'fingerprint': actual}), flush=True)
                    shutil.rmtree(output)
            print(json.dumps({'type': 'summary', 'case': name, 'median_seconds': {k: statistics.median(v) for k, v in times.items()},
                              'logical_outputs_match': True}), flush=True)


if __name__ == '__main__':
    main()
