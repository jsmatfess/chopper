"""Complete-job comparison of independently versioned exact-allocation ranges.

Warm WSL caches. Invariants compare distribution-equivalent plans; exact bytes
and logical metadata compare only repeated executions of the same pinned plan.
"""
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from benchmark_storage import StorageSampler




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['standard', 'sequential', 'candidate']:
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-allocator', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--sample-storage', action='store_true', help='Sample filesystem space only during allocator censuses; perturbs census wall time')
    parser.add_argument('--input-cache', choices=['warm', 'evict'], default='warm', help='evict requests Linux input-only clean page-cache eviction; host cache remains uncontrolled')
    args = parser.parse_args()
    binaries = {k: getattr(args, k).resolve() for k in ['standard', 'sequential', 'candidate']}
    allocators = {k: getattr(args, k + '_allocator') for k in binaries}
    variants = ['standard', 'assignment_shuffle', 'sequential', 'candidate']
    csv.field_size_limit(4 * 1024 * 1024)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'cache': 'warm uncontrolled' if args.input_cache == 'warm' else 'input fsync plus POSIX_FADV_DONTNEED requested; spill/host caches uncontrolled', 'repeats': args.repeats, 'workers': args.workers, 'sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in binaries.items()}, 'allocator_sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in allocators.items() if p}, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'storage_sampler_sha256': hashlib.sha256(Path(__file__).with_name('benchmark_storage.py').read_bytes()).hexdigest()}), flush=True)
    # name, rows, payload, columns, partition parents, downstream split, strategy
    cases = [('resident', 120003, 64, 0, 1, False, 'auto'),
             ('uniform', 120003, 64, 0, 1, False, 'uniform'),
             ('fisher', 120003, 64, 0, 1, False, 'fisher_yates'),
             ('sparse', 120003, 64, 0, 16, False, 'auto'),
             ('many', 60003, 16, 0, 257, False, 'auto'),
             ('columns', 60003, 0, 32, 1, True, 'auto'),
             ('external', 180003, 512, 0, 1, True, 'auto'),
             ('rare_wide', 40003, 64, 0, 1, True, 'auto')]
    groups = [{'name': 'small', 'percent': '17'}, {'name': 'named zero', 'percent': '0'}, {'name': 'middle', 'percent': '33'}, {'name': 'large', 'percent': '50'}]
    def quotas(count):
        base = [count * w // 100 for w in [17, 0, 33, 50]]
        order = sorted(range(4), key=lambda i: (-(count * [17, 0, 33, 50][i] % 100), i))
        for i in order[:count - sum(base)]: base[i] += 1
        return base
    with tempfile.TemporaryDirectory(prefix='chopper-allocation-ranges-') as directory:
        root = Path(directory)
        source, output, config, stats = (root / n for n in ['input.csv', 'output', 'job.json', 'time.txt'])
        for name, rows, width, columns, parents, downstream, strategy in cases:
            if args.cases and name not in args.cases: continue
            def fields(i):
                return [str(i), f'{i % parents:06}', 'x' * (1800000 if name == 'rare_wide' and i == 0 else width)] + [str((i + c) % 10) for c in range(columns)]
            header = ['id', 'key', 'payload'] + [f'c{c}' for c in range(columns)]
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n'); writer.writerow(header); writer.writerows(fields(i) for i in range(rows))
            for workers in args.workers:
                references, measures = {}, collections.defaultdict(list)
                for repeat in range(args.repeats + int(any(allocators.values()))):
                    census = repeat == args.repeats
                    for variant in variants if repeat % 2 == 0 else variants[::-1]:
                        build = 'standard' if variant == 'assignment_shuffle' else variant
                        if census and not allocators[build]: continue
                        shuffle = {'type': 'shuffle', 'strategy': strategy if build != 'standard' or strategy == 'fisher_yates' else 'uniform'}
                        assign = {'type': 'assign', 'groups': groups, 'strata': []}
                        operations = ([{'type': 'partition', 'columns': ['key']}] if parents > 1 else []) + ([assign, shuffle] if variant == 'assignment_shuffle' else [shuffle, assign])
                        # Exact allocation also splits named empty parents into named outputs.
                        if downstream: operations.append({'type': 'assign', 'groups': [{'name': 'left', 'percent': '50'}, {'name': 'right', 'percent': '50'}], 'strata': []})
                        job = {'input': str(source), 'output': str(output), 'seed': 'allocation-ranges-measurement-v1', 'operations': operations, 'resources': {'memory_mb': 256 if name in ['resident', 'uniform', 'fisher'] else 32, 'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(root)}, 'limits': {'rows': 50000, 'bytes': 20000000}}
                        if build != 'standard': job['full_shuffle_policy'] = 'flexible_v1'
                        config.write_text(json.dumps(job))
                        binary = allocators[build].resolve() if census else binaries[build]
                        command = [str(binary), str(config)] if census else [str(binary), 'run', '--config', str(config), '--yes']
                        if args.input_cache == 'evict':
                            with source.open('rb') as stream:
                                os.fsync(stream.fileno())
                                os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                        sampler = StorageSampler(root, [source, config, stats]) if census and args.sample_storage else None
                        if sampler: sampler.thread.start()
                        start = time.perf_counter()
                        try:
                            result = subprocess.run(['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(stats), *command], capture_output=True, text=True, timeout=300)
                        finally:
                            elapsed = time.perf_counter() - start
                            storage_sample = sampler.finish() if sampler else None
                        if result.returncode: raise RuntimeError(f'{name}/{variant}: {result.stderr}')
                        result = json.loads(result.stdout); analysis = result['analysis'] if census else result
                        manifest = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                        entries = [e for e in manifest if e['type'] == 'output']
                        choices = [e for e in manifest if e['type'] == 'execution_group']
                        rewrites = [e for e in manifest if e['type'] == 'execution_rewrite']
                        assert bool(rewrites) == (variant == 'candidate')
                        if rewrites:
                            assert len(rewrites) == 1 and rewrites[0]['logical_operations'] == [int(parents > 1), int(parents > 1) + 1]
                            assert all(c['random_domain_recipe'] == 'independent-allocation-ranges-v1' for c in choices)
                        seen, counts, order, digest = bytearray(rows), collections.Counter(), [], hashlib.sha256()
                        for e in entries:
                            lineage = e['lineage']
                            parent = int(lineage[0]['values'][0]) if parents > 1 else 0
                            allocation = next(v for v in lineage if 'allocation' in v)
                            expected_step = int(parents > 1) + int(variant != 'assignment_shuffle')
                            assert allocation['operation'] == expected_step
                            group = next(i for i, g in enumerate(groups) if g['name'] == allocation['allocation'])
                            key = (parent, group); order.append(key)
                            data = (output / e['path']).read_bytes(); digest.update(data)
                            assert len(data) == e['csv_bytes'] <= 20000000
                            with (output / e['path']).open(newline='') as stream:
                                reader = csv.reader(stream); assert next(reader) == header
                                count = 0
                                for row in reader:
                                    i = int(row[0]); assert 0 <= i < rows and not seen[i]
                                    assert row == fields(i) and i % parents == parent
                                    seen[i] = 1; count += 1
                            assert count == e['rows'] <= 50000
                            counts[key] += count
                        assert order == sorted(order) and all(seen)
                        for parent in range(parents):
                            count = rows // parents + int(parent < rows % parents)
                            for group, quota in enumerate(quotas(count)):
                                assert (parent, group) in counts and counts[parent, group] == quota
                        assert len(entries) == analysis['output_files'] and sum(e['csv_bytes'] for e in entries) == analysis['output_csv_bytes']
                        metadata = [{k: e[k] for k in ['path', 'lineage', 'rows', 'csv_bytes']} for e in entries]
                        actual = (digest.hexdigest(), json.dumps(metadata, sort_keys=True), analysis['stages'], analysis['logical_digest'])
                        assert references.setdefault(variant, actual) == actual, (name, variant)
                        if variant != 'assignment_shuffle': assert references.setdefault('logical', analysis['stages']) == analysis['stages']
                        user, system, rss, filesystem_inputs, filesystem_outputs = map(float, stats.read_text().split())
                        record = {'type': 'allocation' if census else 'measurement', 'case': name, 'workers': workers, 'variant': variant, 'repeat': repeat, 'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': rss, 'filesystem_inputs': filesystem_inputs, 'filesystem_outputs': filesystem_outputs, 'peak_temp_bytes': analysis['peak_temp_bytes'], 'diagnostics': analysis['diagnostics'], 'verified': True}
                        record['output_sha256'] = digest.hexdigest()
                        record['metadata_sha256'] = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
                        record['logical_digest'] = analysis['logical_digest']
                        if storage_sample: record['storage_sample'] = storage_sample
                        if census:
                            record['allocation_profile'] = result['allocation_profile']
                            if 'post_publication_diagnostics' in result:
                                record['post_publication_diagnostics'] = result['post_publication_diagnostics']
                                record['post_publication_peak_temp_bytes'] = result['post_publication_peak_temp_bytes']
                        else: measures[variant].append(elapsed)
                        print(json.dumps(record), flush=True); shutil.rmtree(output)
                print(json.dumps({'type': 'summary', 'case': name, 'workers': workers, 'median_seconds': {k: statistics.median(v) for k, v in measures.items()}, 'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()}}), flush=True)


if __name__ == '__main__':
    main()
