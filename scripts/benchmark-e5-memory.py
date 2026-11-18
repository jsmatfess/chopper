"""Bounded E5 native memory-rule panel; run with fresh work/output paths.

No selector tuning or default promotion. Complete CLI jobs include publication;
verification is outside timing. Windows cache is warm/uncontrolled, not device IO.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CASES = [('small', 1000, 64), ('shuffle', 100000, 64),
         ('skew', 20000, 64), ('late_wide', 8000, 64),
         ('low_headroom', 50000, 16), ('denial', 100, 4)]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fields(case, i, rows):
    return [str(i), 'heavy' if i < rows * 9 // 10 else str(i % 7),
            'x' * (32768 if case == 'late_wide' and i >= rows - 8 else 64)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['binary', 'work', 'output', 'source-proof']:
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    assert platform.system() == 'Windows'
    assert not args.work.exists() and not args.output.exists(), 'refuse overwrite'
    args.work.mkdir(parents=True)
    binary = args.binary.resolve()
    spec = importlib.util.spec_from_file_location('counters', ROOT / 'scripts/benchmark-windows.py')
    counters = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(counters)
    start = time.monotonic()
    with args.output.open('x', encoding='utf-8', newline='\n') as raw:
        def emit(record):
            raw.write(json.dumps(record, separators=(',', ':')) + '\n')
            raw.flush()
        emit({'type': 'design', 'cases': CASES, 'repeats': 3, 'jobs': 36,
              'baseline': 'numeric 256 MiB', 'candidate': 'delivered auto memory; seeded policy; workers 1',
              'decision': 'does headroom sizing justify omitted-memory promotion on this runtime?',
              'stop': 'first unexpected failure; no expansion or threshold tuning; uncertainty retains explicit opt-in',
              'job_timeout_seconds': 60, 'batch_ceiling_seconds': 600,
              'estimated_seconds': 120, 'estimated_disk_bytes': 536870912,
              'timing': 'process startup through CLI exit including parsing/preparation/publication; no optional profile',
              'cache': 'warm uncontrolled Windows filesystem; alternating variants; no physical IO claim',
              'platform': platform.platform(), 'python': platform.python_version(), 'features': [],
              'binary_sha256': sha(binary), 'harness_sha256': sha(__file__),
              'counter_harness_sha256': sha(ROOT / 'scripts/benchmark-windows.py'),
              'source_proof_sha256': sha(args.source_proof),
              'resources': 'Win32 CPU/peak working set/process transfer counters; not physical IO or complete RSS cap',
              'held_out': 'late_wide and skew are fixed before measurement, not used for rule tuning'})
        for case, rows, ceiling in CASES:
            folder = args.work / case
            folder.mkdir()
            source = folder / 'input.csv'
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['id', 'key', 'payload'])
                writer.writerows(fields(case, i, rows) for i in range(rows))
            emit({'type': 'fixture', 'case': case, 'rows': rows, 'bytes': source.stat().st_size, 'sha256': sha(source)})
            references = None
            samples = {'numeric': [], 'auto': []}
            for repeat in range(3):
                for variant in (['numeric', 'auto'] if repeat % 2 == 0 else ['auto', 'numeric']):
                    assert time.monotonic() - start < 600, 'batch deadline'
                    run = f'{repeat + 1}-{variant}'
                    output = folder / ('output-' + run)
                    temp = folder / ('temp-' + run)
                    temp.mkdir()
                    operations = [] if case in ['small', 'denial'] else [{'type': 'shuffle', 'strategy': 'uniform'}]
                    if case == 'skew':
                        operations.append({'type': 'partition', 'columns': ['key']})
                    job = {'input': str(source.resolve()), 'output': str(output.resolve()),
                           'seed': 'e5-held-fixed-v1', 'operations': operations,
                           'limits': {'bytes': 262144, 'rows': 2000},
                           'resources': {'memory_mb': 'auto' if variant == 'auto' else 256,
                                         'workers': 1, 'max_record_bytes': 1048576,
                                         'temp_dir': str(temp.resolve()), 'temp_bytes': 268435456}}
                    config = folder / (run + '.json')
                    config.write_text(json.dumps(job), encoding='utf-8')
                    command = [str(binary), 'run', '--config', str(config.resolve()), '--yes']
                    env = dict(os.environ, CHOPPER_MEMORY_LIMIT_MB=str(ceiling))
                    with (folder / (run + '.stdout')).open('wb') as out, (folder / (run + '.stderr')).open('wb') as err:
                        began = time.perf_counter()
                        process = subprocess.Popen(command, stdout=out, stderr=err, env=env)
                        try:
                            code = process.wait(timeout=60)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                            emit({'type': 'failure', 'case': case, 'run': run, 'timeout': True})
                            raise
                        seconds = time.perf_counter() - began
                        usage = counters.counters(process)
                    emit({'type': 'attempt', 'case': case, 'run': run, 'command': command,
                          'config_sha256': sha(config), 'shared_ceiling_mb': ceiling,
                          'exit_code': code, 'seconds': seconds, **usage})
                    if case == 'denial' and variant == 'auto':
                        error = (folder / (run + '.stderr')).read_text(encoding='utf-8')
                        assert code and ('memory' in error or 'admission' in error), error
                        assert not output.exists() and not any(temp.iterdir())
                        emit({'type': 'denial_control', 'case': case, 'run': run, 'verified': True, 'error': error})
                        continue
                    assert code == 0, (folder / (run + '.stderr')).read_text(encoding='utf-8')
                    analysis = json.loads((folder / (run + '.stdout')).read_text(encoding='utf-8'))
                    manifest = [json.loads(s) for s in (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
                    fingerprint = []
                    seen = bytearray(rows)
                    for entry in manifest:
                        if entry['type'] != 'output':
                            continue
                        path = output / entry['path']
                        assert path.stat().st_size == entry['csv_bytes'] <= 262144
                        count = 0
                        with path.open(encoding='utf-8', newline='') as stream:
                            reader = csv.reader(stream)
                            assert next(reader) == ['id', 'key', 'payload']
                            for row in reader:
                                i = int(row[0])
                                assert 0 <= i < rows and not seen[i] and row == fields(case, i, rows)
                                seen[i] = 1
                                count += 1
                        assert count == entry['rows'] <= 2000
                        fingerprint.append([entry, sha(path)])
                    assert sum(seen) == rows and analysis['rows'] == rows and not any(temp.iterdir())
                    identity = [fingerprint, analysis['logical_digest']]
                    if references is None:
                        references = identity
                    assert identity == references, 'logical output/metadata/bytes differ across budgets'
                    samples[variant].append(seconds)
                    emit({'type': 'measurement', 'case': case, 'variant': variant, 'repeat': repeat + 1,
                          'seconds': seconds, 'analysis': analysis, 'verified': True,
                          'output_identity_sha256': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()})
            if case != 'denial':
                emit({'type': 'summary', 'case': case, 'samples_per_variant': 3,
                      'median_seconds': {k: statistics.median(v) for k, v in samples.items()},
                      'range_seconds': {k: [min(v), max(v)] for k, v in samples.items()}})


if __name__ == '__main__':
    main()
