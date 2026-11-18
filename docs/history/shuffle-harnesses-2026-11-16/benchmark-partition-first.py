# Historical reproduction only: partition-first was removed on 2026-10-24.
# Requires pinned pre-removal binaries; not a current candidate or acceptance harness.
"""Measure complete adjacent flexible shuffle/partition rewrites against four plans.

Exact-v1 controls require byte/metadata parity. Distribution-equivalent plans
require independently checked field/ID conservation, parent/tuple isolation,
canonical order, strict caps and stable per-plan replay. Warm WSL cache only.
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
    for name in ['standard', 'exact', 'sequential', 'candidate']:
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--allocator', type=Path)
    for name in ['standard', 'exact', 'sequential']:
        p.add_argument('--' + name + '-allocator', type=Path)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    p.add_argument('--cases', nargs='+')
    args = p.parse_args()
    binaries = {name: getattr(args, name).resolve() for name in ['standard', 'exact', 'sequential', 'candidate']}
    allocator_paths = {name: getattr(args, name + '_allocator') for name in ['standard', 'exact', 'sequential']}
    allocator_paths['partition_shuffle'] = args.standard_allocator
    allocator_paths['candidate'] = args.allocator
    csv.field_size_limit(4 * 1024 * 1024)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'cache': 'warm uncontrolled', 'repeats': args.repeats, 'cases': args.cases, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'allocator_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in allocator_paths.items() if v}, 'sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in binaries.items()}}), flush=True)
    # name, rows, width, columns, key shape, parents, downstream split
    cases = [('balanced', 120000, 64, 0, 'few', 1, False),
             ('skewed', 120000, 256, 0, 'skew', 1, False),
             ('many', 60000, 64, 0, 'many', 1, False),
             ('presorted', 120000, 64, 0, 'sorted', 2, False),
             ('columns', 60000, 0, 32, 'few', 2, True),
             ('external', 180000, 512, 0, 'skew', 2, True),
             ('rare_wide', 40000, 64, 0, 'few', 2, True)]
    variants = ['standard', 'exact', 'partition_shuffle', 'sequential', 'candidate']
    with tempfile.TemporaryDirectory(prefix='chopper-partition-first-') as directory:
        root = Path(directory)
        for name, rows, width, columns, shape, parents, downstream in cases:
            if args.cases and name not in args.cases: continue
            source, output, config = (root / n for n in ['input.csv', 'output', 'job.json'])
            def fields(i):
                key = 'big' if shape == 'skew' and i < rows * 9 // 10 else f'{i // 16 if shape == "many" else i * 16 // rows if shape == "sorted" else i % 16:06}'
                return [str(i), key, 'x' * (1800000 if name == 'rare_wide' and i == 0 else width)] + [str((i + c) % 10) for c in range(columns)]
            header = ['id', 'key', 'payload'] + [f'c{c}' for c in range(columns)]
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n'); writer.writerow(header); writer.writerows(fields(i) for i in range(rows))
            for workers in args.workers:
                references, measures = {}, {}
                for repeat in range(args.repeats + int(any(allocator_paths.values()))):
                    allocation = repeat == args.repeats
                    for variant in variants if repeat % 2 == 0 else variants[::-1]:
                        if allocation and not allocator_paths[variant]: continue
                        partition = {'type': 'partition', 'columns': ['key']}
                        shuffle = {'type': 'shuffle', 'strategy': 'auto' if variant in ['sequential', 'candidate'] else 'uniform'}
                        operations = ([{'type': 'balanced', 'files': parents}] if parents > 1 else []) + ([partition, shuffle] if variant == 'partition_shuffle' else [shuffle, partition])
                        if downstream: operations += [{'type': 'balanced', 'files': 4 if name == 'external' else 2}]
                        job = {'input': str(source), 'output': str(output), 'seed': 'partition-first-measurement-v1', 'operations': operations, 'resources': {'memory_mb': 32, 'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(root)}, 'limits': {'rows': 50000, 'bytes': 20000000}}
                        if variant in ['sequential', 'candidate']: job['full_shuffle_policy'] = 'flexible_v1'
                        config.write_text(json.dumps(job))
                        binary = allocator_paths[variant].resolve() if allocation else binaries['standard' if variant == 'partition_shuffle' else variant]
                        command = [str(binary), str(config)] if allocation else [str(binary), 'run', '--config', str(config), '--yes']
                        stats = root / 'time.txt'
                        start = time.perf_counter()
                        result = subprocess.run(['/usr/bin/time', '-f', '%U %S %M', '-o', str(stats), *command], check=False, capture_output=True, text=True, timeout=300)
                        if result.returncode:
                            raise RuntimeError(f'{name}/{variant}: {result.stderr}')
                        elapsed = time.perf_counter() - start
                        result = json.loads(result.stdout)
                        analysis = result['analysis'] if allocation else result
                        records = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                        entries = [r for r in records if r['type'] == 'output']
                        choices = [r for r in records if r['type'] == 'execution_group']
                        rewrites = [r for r in records if r['type'] == 'execution_rewrite']
                        if variant == 'candidate':
                            assert len(rewrites) == 1
                            assert all(c['logical_operation'] == int(parents > 1) and c['random_domain_recipe'] == 'independent-partition-child-v1' for c in choices)
                        elif variant == 'sequential': assert not rewrites
                        seen = bytearray(rows)
                        digest, metadata_digest = hashlib.sha256(), hashlib.sha256()
                        last = None
                        for entry in entries:
                            lineage = entry['lineage']
                            key = next(v['values'][0] for v in lineage if 'values' in v)
                            parent = lineage[0]['part'] - 1 if parents > 1 else 0
                            order = (parent, key)
                            assert last is None or order >= last
                            last = order
                            start_id = parent * (rows // parents) + min(parent, rows % parents)
                            end_id = start_id + rows // parents + int(parent < rows % parents)
                            data = (output / entry['path']).read_bytes()
                            assert len(data) == entry['csv_bytes'] <= 20000000
                            digest.update(data)
                            metadata_digest.update(json.dumps({k: entry[k] for k in ['path', 'rows', 'csv_bytes', 'lineage']}, sort_keys=True).encode())
                            count = 0
                            with (output / entry['path']).open(newline='') as stream:
                                reader = csv.reader(stream); assert next(reader) == header
                                for row in reader:
                                    i = int(row[0]); assert start_id <= i < end_id and not seen[i]
                                    assert row == fields(i) and row[1] == key
                                    seen[i] = 1; count += 1
                            assert count == entry['rows'] <= 50000
                        assert all(seen) and len(entries) == analysis['output_files']
                        assert sum(e['csv_bytes'] for e in entries) == analysis['output_csv_bytes']
                        actual = (digest.hexdigest(), metadata_digest.hexdigest(), analysis['stages'], analysis['logical_digest'])
                        ref_key = 'exact' if variant in ['standard', 'exact'] else variant
                        assert references.setdefault(ref_key, actual) == actual, (name, variant)
                        if variant != 'partition_shuffle':
                            assert references.setdefault('logical_stages', analysis['stages']) == analysis['stages']
                        user, system, rss = map(float, stats.read_text().split())
                        record = {'type': 'allocation' if allocation else 'measurement', 'case': name, 'workers': workers, 'variant': variant, 'repeat': repeat, 'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': rss, 'peak_temp_bytes': analysis['peak_temp_bytes'], 'diagnostics': analysis['diagnostics'], 'algorithms': {a: sum(c['algorithm'] == a for c in choices) for a in sorted({c['algorithm'] for c in choices})}, 'verified': True}
                        if allocation: record['allocation_profile'] = result['allocation_profile']
                        else: measures.setdefault(variant, []).append(elapsed)
                        print(json.dumps(record), flush=True)
                        shutil.rmtree(output)
                if measures: print(json.dumps({'type': 'summary', 'case': name, 'workers': workers, 'median_seconds': {k: statistics.median(v) for k, v in measures.items()}, 'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()}}), flush=True)


if __name__ == '__main__':
    main()
