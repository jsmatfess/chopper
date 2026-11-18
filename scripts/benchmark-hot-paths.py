"""A/B full-job CPU/RSS measurements for CSV, merge and shuffle hot paths.

Requires GNU time. Alternates builds, verifies bytes/order/digests/names/stages,
includes a rare 1.8 MiB record to force multiple baseline merge levels at 32 MiB.
Warm local storage only; this is not a cold-storage or billion-row certificate.
"""
import argparse
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
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--cases', nargs='+', choices=['stream_columns', 'profile_columns', 'merge_rare_wide',
                                                     'shuffle_narrow', 'shuffle_resident'],
                        default=['stream_columns', 'profile_columns', 'merge_rare_wide'])
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1:
        parser.error('need at least 1000 rows and positive repeats')
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required for per-process CPU and peak RSS')
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
                      'repeats': args.repeats, 'cache': 'warm, uncontrolled',
                      'binary_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest()
                                        for k, v in [('before', args.before), ('after', args.after)]}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-hot-paths-', dir=args.work_dir) as directory:
        root = Path(directory)
        for case in args.cases:
            source = root / 'input.csv'
            columns = 0 if case.startswith('shuffle') else 32
            with source.open('w') as output:
                output.write(','.join(['id'] + [f'c{i}' for i in range(columns)]) + '\n')
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + col) % 10) for col in range(columns)]
                    if case == 'merge_rare_wide' and row == 0:
                        fields[1] = 'x' * 1800000
                    output.write(','.join(fields) + '\n')
            command = 'profile' if case.startswith('profile') else 'run'
            job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'hot-paths-v1',
                   'operations': [{'type': 'shuffle', 'strategy': 'uniform'}] if case.startswith(('merge', 'shuffle')) else [],
                   'resources': {'memory_mb': 256 if case == 'shuffle_resident' else 32,
                                 'workers': 1, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
            config = root / 'job.json'
            config.write_text(json.dumps(job))
            reference = None
            measures = {'before': [], 'after': []}
            for repeat in range(args.repeats):
                builds = [('before', args.before), ('after', args.after)]
                if repeat % 2:
                    builds.reverse()
                for label, binary in builds:
                    stats = root / 'time.txt'
                    cmd = [timer, '-f', '%U %S %M', '-o', str(stats), str(binary.resolve()), command,
                           '--config', str(config)] + (['--yes'] if command == 'run' else [])
                    started = time.perf_counter()
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                    elapsed = time.perf_counter() - started
                    user, system, rss = map(float, stats.read_text().split())
                    analysis = json.loads(result.stdout)
                    if command == 'run':
                        actual = pipelines.fingerprint(root / 'output', analysis, 'none')
                        shutil.rmtree(root / 'output')
                    else:
                        actual = {k: v for k, v in analysis.items() if k not in ['seconds', 'cache_hit']}
                    if reference is None:
                        reference = actual
                    assert actual == reference, f'{case}/{label}: changed output'
                    measures[label].append(elapsed)
                    print(json.dumps({'type': 'measurement', 'case': case, 'build': label, 'repeat': repeat + 1,
                                      'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': int(rss),
                                      'diagnostics': analysis.get('diagnostics'), 'timings': analysis.get('timings'),
                                      'peak_temp_bytes': analysis.get('peak_temp_bytes'), 'verified': True}), flush=True)
            print(json.dumps({'type': 'summary', 'case': case,
                              'median_seconds': {k: statistics.median(v) for k, v in measures.items()},
                              'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()},
                              'verified': True}), flush=True)


if __name__ == '__main__':
    main()
