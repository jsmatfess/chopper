"""A/B intermediate balanced-split scanning on complete many-column jobs.

Alternates native builds, verifies output bytes/order, names, lineage, stages and
logical digests. Optional allocation-profile examples count whole-job allocations.
Requires GNU time. Warm uncontrolled storage; not a storage/scale certificate.
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
    parser.add_argument('--before-allocator', type=Path)
    parser.add_argument('--after-allocator', type=Path)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--cases', nargs='+', choices=['columns', 'rare_wide'], default=['columns', 'rare_wide'])
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1:
        parser.error('need at least 1000 rows and positive repeats')
    if bool(args.before_allocator) != bool(args.after_allocator) or min(args.workers) < 1:
        parser.error('provide both allocators and positive workers')
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required for per-process CPU and peak RSS')
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
                      'cpu': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                                   if line.startswith('model name')), 'unknown'),
                      'workers': args.workers, 'repeats': args.repeats, 'cache': 'warm, uncontrolled',
                      'binary_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest()
                                        for k, v in [('before', args.before), ('after', args.after),
                                                     ('before_allocator', args.before_allocator),
                                                     ('after_allocator', args.after_allocator)] if v}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-boundaries-', dir=args.work_dir) as directory:
        root = Path(directory)
        for case in args.cases:
            source = root / 'input.csv'
            columns = 32
            with source.open('w') as output:
                output.write(','.join(['id'] + [f'c{i}' for i in range(columns)]) + '\n')
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + col) % 10) for col in range(columns)]
                    if case == 'rare_wide' and row == 0:
                        fields[1] = 'x' * 1800000
                    output.write(','.join(fields) + '\n')
            job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'boundaries-v1',
                   'operations': [{'type': 'balanced', 'files': 4}, {'type': 'partition', 'columns': ['c0']}],
                   'resources': {'memory_mb': 32,
                                 'workers': 1, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
            for workers in args.workers:
                config = root / 'job.json'
                job['resources']['workers'] = workers
                config.write_text(json.dumps(job))
                reference = None
                measures = {'before': [], 'after': []}
                for repeat in range(args.repeats):
                    builds = [('before', args.before), ('after', args.after)]
                    if repeat % 2:
                        builds.reverse()
                    for label, binary in builds:
                        stats = root / 'time.txt'
                        cmd = [timer, '-f', '%U %S %M', '-o', str(stats), str(binary.resolve()), 'run',
                               '--config', str(config), '--yes']
                        started = time.perf_counter()
                        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                        elapsed = time.perf_counter() - started
                        user, system, rss = map(float, stats.read_text().split())
                        analysis = json.loads(result.stdout)
                        actual = pipelines.fingerprint(root / 'output', analysis, 'none')
                        shutil.rmtree(root / 'output')
                        if reference is None:
                            reference = actual
                        assert actual == reference, f'{case}/{label}: changed output'
                        measures[label].append(elapsed)
                        print(json.dumps({'type': 'measurement', 'case': case, 'workers': workers, 'build': label, 'repeat': repeat + 1,
                                          'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': int(rss),
                                          'diagnostics': analysis.get('diagnostics'), 'timings': analysis.get('timings'),
                                          'peak_temp_bytes': analysis.get('peak_temp_bytes'), 'verified': True}), flush=True)
                print(json.dumps({'type': 'summary', 'case': case, 'workers': workers,
                                  'median_seconds': {k: statistics.median(v) for k, v in measures.items()},
                                  'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()},
                                  'verified': True}), flush=True)
                if args.before_allocator:
                    for label, binary in [('before', args.before_allocator), ('after', args.after_allocator)]:
                        result = subprocess.run([str(binary.resolve()), str(config)], capture_output=True,
                                                text=True, check=True, timeout=300)
                        profile = json.loads(result.stdout)
                        assert pipelines.fingerprint(root / 'output', profile['analysis'], 'none') == reference
                        shutil.rmtree(root / 'output')
                        print(json.dumps({'type': 'allocation', 'case': case, 'workers': workers,
                                          'build': label, 'profile': profile['allocation_profile'],
                                          'verified': True}), flush=True)



if __name__ == '__main__':
    main()
