"""Alternate whole-file native profiles with/without bounded hash batches.

Compare complete stable profile JSON, excluding elapsed seconds/cache_hit, across
workers and variants. Timing runs use ordinary binaries; allocation censuses use
the separate allocation-profile example. GNU time measures process RSS/CPU and
filesystem blocks, not physical device traffic. Storage is warm/uncontrolled.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time


def emit(value):
    print(json.dumps(value), flush=True)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fields(row, shape):
    if shape == 'first_wide':
        return [str(row), '界' * 40_000 if row == 0 else 'narrow', str(row % 7)]
    if shape == 'many':
        return [str(row)] + [f'{row * 37 + c}' for c in range(32)]
    if shape == 'long_text':
        return [str(row), f'{row}:' + 'abcd界' * 150, 'group' + str(row % 7)]
    if shape == 'high_cardinality':
        return [str(row)] + [f'{row * 37 + c}:value' for c in range(7)]
    if shape == 'rare_wide':
        return [str(row), ('界' * 40_000 if row % 8191 == 8190 else 'quoted, "text"\nnext'), str(row % 7)]
    return [str(row), 'duplicate', str(row % 7)]


def normalized(profile):
    return {k: v for k, v in profile.items() if k not in ('seconds', 'cache_hit')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['baseline', 'candidate']:
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ['baseline-allocator', 'candidate-allocator']:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--skip-allocations', action='store_true')
    parser.add_argument('--rows', type=int, default=150000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--memory-mb', type=int, default=32)
    parser.add_argument('--workers', nargs='+', type=int, default=[1, 4])
    parser.add_argument('--shapes', nargs='+', choices=['narrow', 'many', 'high_cardinality', 'long_text', 'rare_wide', 'first_wide'],
                        default=['narrow', 'many', 'high_cardinality', 'long_text', 'rare_wide'])
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1 or any(w < 1 or w > 32 for w in args.workers):
        parser.error('need rows >= 1000, positive repeats, workers in 1..32')
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    if not args.skip_allocations and (not args.baseline_allocator or not args.candidate_allocator):
        parser.error('need both allocator binaries or --skip-allocations')
    allocators = {} if args.skip_allocations else {
        'baseline': args.baseline_allocator.resolve(), 'candidate': args.candidate_allocator.resolve()}
    emit({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
          'repeats': args.repeats, 'memory_mb': args.memory_mb, 'workers': args.workers,
          'cache': 'warm, uncontrolled; fresh process/cache on every run',
          'binaries': {k: digest(v) for k, v in binaries.items()},
          'allocators': {k: digest(v) for k, v in allocators.items()}})
    with tempfile.TemporaryDirectory(prefix='chopper-parallel-profile-', dir=args.work_dir) as directory:
        root = Path(directory)
        config = root / 'job.json'
        time_file = root / 'time.txt'
        for shape in args.shapes:
            source = root / 'input.csv'
            width = len(fields(0, shape))
            with source.open('w', newline='') as out:
                writer = csv.writer(out, lineterminator='\n')
                writer.writerow([f'c{i}' for i in range(width)])
                writer.writerows(fields(row, shape) for row in range(args.rows))
            emit({'type': 'fixture', 'shape': shape, 'bytes': source.stat().st_size,
                  'source_sha256': digest(source), 'columns': width})
            expected = None
            measurements = {}
            for repeat in range(args.repeats):
                cases = [(workers, variant) for workers in args.workers for variant in binaries]
                if repeat % 2:
                    cases.reverse()
                for workers, variant in cases:
                    job = {'input': str(source), 'output': str(root / 'output'),
                           'operations': [{'type': 'partition', 'columns': ['c0', 'c1']}],
                           'seed': 'parallel-profile-v1', 'resources': {'workers': workers,
                           'memory_mb': args.memory_mb, 'max_record_bytes': 1048576, 'temp_dir': str(root)}}
                    config.write_text(json.dumps(job))
                    command = ['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(time_file),
                               str(binaries[variant]), 'profile', '--config', str(config)]
                    started = time.perf_counter()
                    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=300)
                    wall = time.perf_counter() - started
                    profile = json.loads(result.stdout)
                    assert profile['rows'] == args.rows
                    value = normalized(profile)
                    if expected is None:
                        expected = value
                    assert value == expected, (shape, workers, variant, 'profile changed')
                    profile_digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
                    user, system, rss, reads, writes = map(float, time_file.read_text().split())
                    row = {'type': 'measurement', 'shape': shape, 'workers': workers,
                           'variant': variant, 'repeat': repeat, 'wall_seconds': wall,
                           'profile_seconds': profile['seconds'], 'cpu_seconds': user + system,
                           'peak_rss_kib': int(rss), 'filesystem_input_blocks': int(reads),
                           'filesystem_output_blocks': int(writes), 'profile_parity': True,
                           'profile_sha256': profile_digest}
                    emit(row)
                    measurements.setdefault((workers, variant), []).append(row)
            for workers in ([] if args.skip_allocations else args.workers):
                for variant in allocators:
                    job['resources']['workers'] = workers
                    config.write_text(json.dumps(job))
                    result = subprocess.run([str(allocators[variant]), str(config), 'profile'],
                                            capture_output=True, text=True, check=True, timeout=300)
                    census = json.loads(result.stdout)
                    assert normalized(census['profile']) == expected
                    execution = census['execution']
                    if variant == 'candidate' and workers > 1 and shape != 'first_wide':
                        assert execution['hash_workers'] == workers and execution['hashed_rows'] == args.rows
                    else:
                        assert execution['hash_workers'] == 0 and execution['hashed_rows'] == 0
                    emit({'type': 'allocation', 'shape': shape, 'workers': workers,
                          'variant': variant, 'execution': execution,
                          'allocation_profile': census['allocation_profile'], 'profile_parity': True,
                          'profile_sha256': profile_digest})
            for (workers, variant), values in measurements.items():
                emit({'type': 'summary', 'shape': shape, 'workers': workers, 'variant': variant,
                      **{key: {'median': statistics.median(v[key] for v in values),
                               'min': min(v[key] for v in values), 'max': max(v[key] for v in values)}
                         for key in ['wall_seconds', 'cpu_seconds', 'peak_rss_kib']}})


if __name__ == '__main__':
    main()
