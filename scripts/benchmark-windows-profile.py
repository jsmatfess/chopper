"""Focused Windows whole-profile comparison; allocation censuses are not timed.

Requires a build record with baseline/candidate CLI and allocation-profile hashes,
matching sources, and only experimental-parallel-profile enabled on the candidate.
Uses the existing profile fixtures/normalization and Win32 process counters.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows = load('windows', Path(__file__).with_name('benchmark-windows.py'))
profiles = load('profiles', Path(__file__).with_name('benchmark-parallel-profile.py'))


def emit(record):
    print(json.dumps(record), flush=True)


def validate_build(record):
    binaries, allocators = {}, {}
    for variant in ('baseline', 'candidate'):
        build = record['builds'][variant]
        expected = [] if variant == 'baseline' else ['experimental-parallel-profile']
        if build['features'] != expected or build['returncode'] != 0:
            raise ValueError('incompatible or unsuccessful build')
        for target, info in ((binaries, build), (allocators, build['allocator'])):
            path = Path(info['artifact']).resolve()
            if windows.sha(path) != info['sha256']:
                raise ValueError('artifact does not match its build record')
            target[variant] = path
    if not record.get('source_identity_unchanged') or not record.get('source_sha256'):
        raise ValueError('missing matched build source identity')
    return binaries, allocators


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-record', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hardware', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=150000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--shapes', nargs='+', choices=['many', 'rare_wide'], default=['many', 'rare_wide'])
    args = parser.parse_args()
    if os.name != 'nt' or args.rows < 8192 or args.repeats < 1:
        parser.error('requires Windows, rows >= 8192 and positive repeats')
    build = json.loads(args.build_record.read_text(encoding='utf-8'))
    binaries, allocators = validate_build(build)
    sys.stdout = args.output.open('x', encoding='utf-8', buffering=1)
    emit({'type': 'environment', 'build_record': str(args.build_record),
          'build_record_sha256': windows.sha(args.build_record),
          'source_sha256': build['source_sha256'],
          'measurement_source_sha256': windows.source_inventory(),
          'harness_sha256': {str(p): windows.sha(p) for p in map(Path, [__file__, windows.__file__, profiles.__file__])},
          'binary_sha256': {k: windows.sha(p) for k, p in binaries.items()},
          'allocator_sha256': {k: windows.sha(p) for k, p in allocators.items()},
          'hardware': json.loads(args.hardware.read_text(encoding='utf-8-sig')),
          'rows': args.rows, 'repeats': args.repeats, 'memory_mb': 32, 'workers': [1, 4],
          'seed': 'parallel-profile-v1', 'shared_limit': os.environ.get('CHOPPER_MEMORY_LIMIT_MB'),
          'work_dir': str(args.work_dir.resolve()),
          'cache': 'warm/uncontrolled; fixture generation and verification touch cache; fresh CLI process per run',
          'timing_scope': 'complete CLI profile including startup; no output preparation/publication/export',
          'io_scope': 'Win32 process transfer counters, includes cached I/O; not physical device traffic',
          'physical_io_bytes': None,
          'decision': 'does bounded hash batching benefit many-column Windows profiles without hiding rare-wide or one-worker costs?',
          'stop_criterion': f'{args.repeats} alternating pairs per shape/worker cell; stop on failure, profile mismatch or unexpected temporary/output files; no defaults promoted'})
    with tempfile.TemporaryDirectory(prefix='windows-profile-', dir=args.work_dir) as directory:
        root = Path(directory)
        temp = root / 'temp'
        temp.mkdir()
        for shape in args.shapes:
            source = root / 'input.csv'
            width = len(profiles.fields(0, shape))
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow([f'c{i}' for i in range(width)])
                writer.writerows(profiles.fields(row, shape) for row in range(args.rows))
            emit({'type': 'fixture', 'shape': shape, 'rows': args.rows, 'columns': width,
                  'source_sha256': windows.sha(source), 'bytes': source.stat().st_size})
            reference, samples = None, {}
            cases = [(w, v) for w in (1, 4) for v in binaries]
            # All census runs follow the timed runs, so allocator atomics never
            # contaminate a timing sample. There is no concurrent sampler.
            runs = [('measurement', repeat, workers, variant)
                    for repeat in range(args.repeats)
                    for workers, variant in (cases if repeat % 2 == 0 else list(reversed(cases)))]
            runs += [('allocation', None, workers, variant) for workers, variant in cases]
            for kind, repeat, workers, variant in runs:
                job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'parallel-profile-v1',
                       'operations': [{'type': 'partition', 'columns': ['c0', 'c1']}],
                       'resources': {'memory_mb': 32, 'workers': workers, 'max_record_bytes': 1048576,
                                     'temp_dir': str(temp)}}
                config = root / 'job.json'
                config.write_text(json.dumps(job), encoding='utf-8')
                command = ([str(binaries[variant]), 'profile', '--config', str(config)] if kind == 'measurement'
                           else [str(allocators[variant]), str(config), 'profile'])
                try:
                    with (root / 'stdout').open('wb') as stdout, (root / 'stderr').open('wb') as stderr:
                        started = time.perf_counter()
                        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                        process.wait(timeout=180)
                        elapsed = time.perf_counter() - started
                        metrics = windows.counters(process)
                    if process.returncode:
                        raise RuntimeError((root / 'stderr').read_text(encoding='utf-8'))
                    result = json.loads((root / 'stdout').read_text(encoding='utf-8'))
                    profile = result if kind == 'measurement' else result['profile']
                    assert profile['rows'] == args.rows
                    normalized = profiles.normalized(profile)
                    if reference is None:
                        reference = normalized
                    assert normalized == reference, 'stable profile JSON changed'
                    assert not (root / 'output').exists(), 'profile produced job output'
                    assert not list(temp.iterdir()), 'profile leaked temporary data'
                    row = {'type': kind, 'shape': shape, 'workers': workers, 'variant': variant,
                           'repeat': repeat, 'config': job, 'profile_parity': True, 'cleanup_verified': True,
                           'profile_sha256': hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()}
                    if kind == 'measurement':
                        row.update(seconds=elapsed, profile_seconds=profile['seconds'], **metrics)
                        samples.setdefault((workers, variant), []).append(row)
                    else:
                        execution = result['execution']
                        assert execution['hash_workers'] == (4 if variant == 'candidate' and workers == 4 else 0)
                        assert execution['hashed_rows'] == (args.rows if execution['hash_workers'] else 0)
                        assert execution['serial_retry'] is False
                        row.update(execution=execution, allocation_profile=result['allocation_profile'])
                    emit(row)
                except BaseException as error:
                    if 'process' in locals() and process.poll() is None:
                        process.kill()
                        process.wait()
                    emit({'type': 'failure', 'shape': shape, 'workers': workers, 'variant': variant,
                          'repeat': repeat, 'kind': kind, 'error': repr(error),
                          'stdout': (root / 'stdout').read_text(encoding='utf-8', errors='replace'),
                          'stderr': (root / 'stderr').read_text(encoding='utf-8', errors='replace')})
                    raise
            for (workers, variant), rows in samples.items():
                emit({'type': 'summary', 'shape': shape, 'workers': workers, 'variant': variant,
                      **{name: {'n': len(rows), 'median': statistics.median(r[name] for r in rows),
                                'minimum': min(r[name] for r in rows), 'maximum': max(r[name] for r in rows)}
                         for name in ('seconds', 'cpu_seconds', 'peak_working_set_bytes')}})


if __name__ == '__main__':
    main()
