"""Full-file profiling vs preparation/publication and native worker scaling.

Uses a sorted-key fixture, alternates order, verifies output parity across workers.
No GPU or cold-storage claims. Use --work-dir to choose the storage placement.
"""
import argparse
import hashlib
import importlib.util
import json
import os
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
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=1_000_000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if args.rows < 100 or args.repeats < 1 or any(w < 1 or w > 32 for w in args.workers):
        parser.error('need at least 100 rows, positive repeats, workers in 1..32')
    binary = args.binary.resolve()
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
                      'repeats': args.repeats, 'workers': args.workers, 'cache': 'warm, uncontrolled',
                      'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-profile-', dir=args.work_dir) as directory:
        root = Path(directory)
        source = root / 'input.csv'
        with source.open('w') as f:
            f.write('id,key,payload\n')
            for i in range(args.rows):
                f.write(f'{i},{min(6, i * 7 // args.rows)},{"x" * 32}\n')
        partition = {'type': 'partition', 'columns': ['key']}
        assign = {'type': 'assign', 'groups': [{'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}]}
        shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
        cases = [('profile', 'profile', [partition, assign], 'none', 1)]
        for workers in args.workers:
            cases.extend([
                ('stream', 'run', [], 'none', workers),
                ('partition_assign', 'run', [partition, assign], 'none', workers),
                ('shuffle', 'run', [shuffle], 'none', workers),
                ('gzip', 'run', [], 'gzip', workers),
            ])
        fingerprints, measures = {}, {}
        for repeat in range(args.repeats):
            for name, command, operations, compression, workers in (cases if repeat % 2 == 0 else list(reversed(cases))):
                job = {'input': str(source), 'output': str(root / 'output'), 'operations': operations,
                       'compression': compression, 'seed': 'profile-benchmark', 'limits': {'rows': max(1, args.rows // 16)},
                       'resources': {'workers': workers, 'memory_mb': 256, 'max_record_bytes': 1048576, 'temp_dir': str(root)}}
                config = root / 'job.json'
                config.write_text(json.dumps(job))
                cmd = [str(binary), command, '--config', str(config)] + (['--yes'] if command == 'run' else [])
                before_cpu = os.times()
                started = time.perf_counter()
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                wall = time.perf_counter() - started
                after_cpu = os.times()
                cpu = after_cpu.children_user + after_cpu.children_system - before_cpu.children_user - before_cpu.children_system
                analysis = json.loads(result.stdout)
                assert analysis['rows'] == args.rows
                if command == 'run':
                    fingerprint = pipelines.fingerprint(root / 'output', analysis, compression)
                    if name in fingerprints:
                        assert fingerprint == fingerprints[name], (name, workers, 'output changed')
                    fingerprints[name] = fingerprint
                    shutil.rmtree(root / 'output')
                else:
                    assert analysis['column_values'][1]['distinct'] == 7
                    assert analysis['column_values'][1]['distinct_exact']
                print(json.dumps({'type': 'measurement', 'case': name, 'workers': workers, 'repeat': repeat,
                               'wall_seconds': wall, 'cpu_seconds': cpu, 'profile_seconds': analysis.get('seconds'),
                               'analysis_seconds': analysis.get('analysis_seconds'), 'timings': analysis.get('timings'),
                               'diagnostics': analysis.get('diagnostics')}), flush=True)
                measures.setdefault((name, workers), []).append(wall)
        for (name, workers), times in measures.items():
            print(json.dumps({'type': 'summary', 'case': name, 'workers': workers, 'median_seconds': statistics.median(times),
                              'min_seconds': min(times), 'max_seconds': max(times)}), flush=True)

if __name__ == '__main__':
    main()
