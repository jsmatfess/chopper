"""Alternate complete WSL jobs for flexible policy overhead and per-group admission.

Warm uncontrolled filesystem cache; this is not a physical SSD calibration.
Exact byte/metadata parity is required for explicit uniform and default controls.
Auto is independently checked for fields, unique IDs, parent isolation and caps.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--allocator', type=Path)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    args = p.parse_args()
    csv.field_size_limit(2 * 1024 * 1024)
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'cache': 'warm uncontrolled', 'repeats': args.repeats, 'workers': args.workers, 'sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in binaries.items()}}), flush=True)
    cases = [('resident', 100000, 16, 0, False, False, 256),
             ('columns', 60000, 0, 32, False, False, 32),
             ('external', 60000, 512, 0, False, False, 32),
             ('partitioned', 120000, 64, 0, True, False, 32),
             ('skewed', 120000, 256, 0, True, True, 32)]
    variants = [('baseline', 'seeded_v1'), ('candidate', 'seeded_v1'), ('candidate', 'flexible_v1'), ('candidate', 'auto')]
    with tempfile.TemporaryDirectory(prefix='chopper-flexible-') as directory:
        root = Path(directory)
        for name, rows, width, columns, partitioned, skewed, memory in cases:
            source, output, config = (root / n for n in ['input.csv', 'output', 'job.json'])
            def fields(i):
                return [str(i), 'big' if skewed and i < rows * 9 // 10 else f'{i % 16:02}', 'x' * width] + [str((i + c) % 10) for c in range(columns)]
            header = ['id', 'key', 'payload'] + [f'c{c}' for c in range(columns)]
            with source.open('w', newline='') as f:
                w = csv.writer(f, lineterminator='\n'); w.writerow(header)
                w.writerows(fields(i) for i in range(rows))
            for workers in args.workers:
                references = {}
                measures = {}
                for repeat in range(args.repeats + int(bool(args.allocator))):
                    allocation = repeat == args.repeats
                    for build, policy in (variants if repeat % 2 == 0 else variants[::-1]):
                        if allocation and build == 'baseline':
                            continue
                        operations = ([{'type': 'partition', 'columns': ['key']}] if partitioned else []) + [{'type': 'shuffle', 'strategy': 'auto' if policy == 'auto' else 'uniform'}]
                        job = {'input': str(source), 'output': str(output), 'seed': 'flexible-measurement-v1', 'full_shuffle_policy': 'flexible_v1' if policy == 'auto' else policy, 'operations': operations, 'resources': {'memory_mb': memory, 'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(root)}, 'limits': {'rows': 100000, 'bytes': 20000000}}
                        if policy == 'seeded_v1':
                            del job['full_shuffle_policy']
                        config.write_text(json.dumps(job))
                        executable = args.allocator.resolve() if allocation else binaries[build]
                        command = [str(executable), str(config)] if allocation else [str(executable), 'run', '--config', str(config), '--yes']
                        stats = root / 'time.txt'
                        started = time.perf_counter()
                        process = subprocess.run(['/usr/bin/time', '-f', '%U %S %M', '-o', str(stats), *command], capture_output=True, text=True, check=True, timeout=300)
                        elapsed = time.perf_counter() - started
                        result = json.loads(process.stdout)
                        analysis = result['analysis'] if allocation else result
                        manifest = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                        outputs = [r for r in manifest if r['type'] == 'output']
                        groups = [r for r in manifest if r['type'] == 'execution_group']
                        if policy in ('auto', 'flexible_v1'):
                            audit = next(r for r in manifest if r['type'] == 'execution_plan')
                            assert audit['replay_guarantee'] == 'prepared_snapshot_only'
                            assert audit['logical_operations'] == operations or all(a.items() <= b.items() for a, b in zip(operations, audit['logical_operations']))
                            assert audit['source_logical_digest'] == analysis['logical_digest']
                            assert len(groups) == analysis['groups']
                            assert all(g['uniform_full_permutation'] and g['rng'] and g['implementation'] for g in groups)
                        seen = bytearray(rows)
                        digest = hashlib.sha256()
                        last_key = None
                        for entry in outputs:
                            data = (output / entry['path']).read_bytes()
                            assert len(data) == entry['csv_bytes'] <= 20000000
                            digest.update(json.dumps({k: entry[k] for k in ['path', 'rows', 'csv_bytes', 'lineage']}, sort_keys=True).encode()); digest.update(data)
                            if partitioned:
                                key = entry['lineage'][-1]['values'][0]
                                assert last_key is None or key >= last_key
                                last_key = key
                            count = 0
                            with (output / entry['path']).open(newline='') as f:
                                reader = csv.reader(f); assert next(reader) == header
                                for row in reader:
                                    i = int(row[0]); assert 0 <= i < rows and not seen[i]
                                    assert row == fields(i)
                                    if partitioned: assert row[1] == key
                                    seen[i] = 1; count += 1
                            assert count == entry['rows'] <= 100000
                        assert all(seen)
                        assert sum(r['csv_bytes'] for r in outputs) == analysis['output_csv_bytes']
                        assert len(outputs) == analysis['output_files']
                        fingerprint = (digest.hexdigest(), analysis['logical_digest'], analysis['stages'])
                        ref_key = 'auto' if policy == 'auto' else 'uniform'
                        assert references.setdefault(ref_key, fingerprint) == fingerprint
                        label = f'{build}/{policy}'
                        user, system, rss = map(float, stats.read_text().split())
                        record = {'type': 'allocation' if allocation else 'measurement', 'case': name, 'workers': workers, 'variant': label, 'repeat': repeat, 'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': rss, 'diagnostics': analysis['diagnostics'], 'peak_temp_bytes': analysis['peak_temp_bytes'], 'algorithms': {a: sum(g['algorithm'] == a for g in groups) for a in sorted({g['algorithm'] for g in groups})}, 'verified': True}
                        if allocation: record['allocation_profile'] = result['allocation_profile']
                        else: measures.setdefault(label, []).append(elapsed)
                        print(json.dumps(record), flush=True)
                        shutil.rmtree(output)
                print(json.dumps({'type': 'summary', 'case': name, 'workers': workers, 'median_seconds': {k: statistics.median(v) for k, v in measures.items()}, 'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()}}), flush=True)


if __name__ == '__main__':
    main()
