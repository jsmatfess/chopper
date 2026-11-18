# Historical reproduction only: requires matching pinned pre-removal bucket builds.
# Not a candidate harness for the current engine; preserve original diagnostic flags.
"""Independent-bucket full jobs versus seeded merge, flexible merge and v1 prefix.

Timing excludes fixture preparation and independent verification. Matching v1
plans require exact bytes/metadata; distribution-equivalent buckets require
conservation, tuple isolation, logical stages, exact downstream quotas and caps.
Allocator/storage censuses are separate from timing. No physical SSD claim.
"""
import argparse
import collections
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
from benchmark_storage import StorageSampler


def prepare_skew(root, candidate, generator, seed):
    probe, job_path, output, lineage_path = (root / name for name in ['probe.csv', 'probe.json', 'probe-output', 'lineage.json'])
    probe.write_text('id,key,payload\n0,target,\n1,other,\n')
    job = {'input': str(probe), 'output': str(output), 'seed': seed, 'operations': [{'type': 'partition', 'columns': ['key']}], 'resources': {'memory_mb': 32, 'workers': 1, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
    job_path.write_text(json.dumps(job))
    probe_result = subprocess.run([str(candidate), 'run', '--config', str(job_path), '--yes'], capture_output=True, text=True)
    if probe_result.returncode: raise RuntimeError('prepare skew lineage: ' + probe_result.stderr)
    records = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
    lineage = next(e['lineage'] for e in records if e['type'] == 'output' and e['lineage'][-1]['values'] == ['target'])
    lineage_path.write_text(json.dumps(lineage))
    result = subprocess.run([str(generator), str(root / 'input.csv'), seed, str(lineage_path), '20', '600000'], check=True, capture_output=True, text=True)
    fixture = json.loads(result.stdout)
    shutil.rmtree(output)
    for path in [probe, job_path, lineage_path]: path.unlink()
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['standard', 'merge', 'prefix', 'candidate']:
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-allocator', type=Path)
    parser.add_argument('--skew-generator', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--cases', nargs='+', help='multilevel is opt-in; other cases run by default')
    parser.add_argument('--sample-storage', action='store_true')
    args = parser.parse_args()
    binaries = {k: getattr(args, k).resolve() for k in ['standard', 'merge', 'prefix', 'candidate']}
    allocators = {k: getattr(args, k + '_allocator') for k in binaries}
    variants = ['seeded_merge', 'flex_merge', 'flex_prefix', 'buckets_v1', 'buckets_xof64']
    builds = {'seeded_merge': 'standard', 'flex_merge': 'merge', 'flex_prefix': 'prefix', 'buckets_v1': 'candidate', 'buckets_xof64': 'candidate'}
    csv.field_size_limit(4 * 1024 * 1024)
    seed = 'independent-buckets-measurement-v1'
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'cache': 'warm uncontrolled WSL; no physical-device throughput claim', 'repeats': args.repeats, 'workers': args.workers, 'cases': args.cases, 'sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in binaries.items()}, 'allocator_sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in allocators.items() if p}, 'generator_sha256': hashlib.sha256(args.skew_generator.read_bytes()).hexdigest(), 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'storage_sampler_sha256': hashlib.sha256(Path(__file__).with_name('benchmark_storage.py').read_bytes()).hexdigest()}), flush=True)
    # name, rows, payload, extra columns, parents, downstream balanced parts, memory
    cases = [('resident', 120003, 64, 0, 1, 0, 256),
             ('narrow_external', 400003, 64, 0, 1, 0, 32),
             ('wide_external', 180003, 512, 0, 1, 8, 32),
             ('sparse', 120003, 64, 0, 16, 0, 32),
             ('skewed', 120003, 256, 0, 16, 0, 32),
             ('presorted', 120003, 64, 0, 16, 0, 32),
             ('many', 40003, 64, 0, 128, 0, 32),
             ('columns', 60003, 0, 32, 1, 0, 32),
             ('rare_wide', 40003, 64, 0, 1, 4, 32),
             ('forced_overflow', 0, 0, 0, 2, 0, 32),
             ('multilevel', 1500000, 0, 32, 1, 0, 32)]
    with tempfile.TemporaryDirectory(prefix='chopper-random-buckets-') as directory:
        root = Path(directory)
        source, output, config, stats = (root / n for n in ['input.csv', 'output', 'job.json', 'time.txt'])
        for name, rows, width, columns, parents, downstream, memory in cases:
            if args.cases and name not in args.cases or not args.cases and name == 'multilevel': continue
            suffixes = [[str((i + c) % 10) for c in range(columns)] for i in range(10)]
            payload, rare = 'x' * width, 'x' * 1800000 if name == 'rare_wide' else ''
            header = ['id', 'key', 'payload'] + [f'c{c}' for c in range(columns)]
            target_ids = set()
            if name == 'forced_overflow':
                fixture = prepare_skew(root, binaries['candidate'], args.skew_generator.resolve(), seed)
                rows = fixture['rows']; target_ids = set(fixture['target_source_ids']); payload = 'x' * 600000
                print(json.dumps({'type': 'fixture', 'case': name, **fixture}), flush=True)
            def key(i):
                if name == 'forced_overflow': return 'target' if i in target_ids else 'other'
                index = 0 if name == 'skewed' and i < rows * 9 // 10 else i * parents // rows if name == 'presorted' else i % max(parents, 16)
                return f'{index:06}'
            def fields(i):
                value = payload if name != 'forced_overflow' or i in target_ids else ''
                return [str(i), key(i), rare if name == 'rare_wide' and i == 0 else value] + suffixes[i % 10]
            if name != 'forced_overflow':
                with source.open('w', newline='') as stream:
                    writer = csv.writer(stream, lineterminator='\n'); writer.writerow(header); writer.writerows(fields(i) for i in range(rows))
            parent_counts = collections.Counter(key(i) for i in range(rows)) if parents > 1 else {'all': rows}
            print(json.dumps({'type': 'fixture_summary', 'case': name, 'rows': rows, 'payload_bytes': width, 'extra_columns': columns, 'parents': len(parent_counts), 'downstream_balanced': downstream, 'input_csv_bytes': source.stat().st_size, 'input_csv_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}), flush=True)
            for workers in args.workers:
                references, measures = {}, collections.defaultdict(list)
                for repeat in range(args.repeats + int(any(allocators.values()))):
                    census = repeat == args.repeats
                    for variant in variants if repeat % 2 == 0 else variants[::-1]:
                        build = builds[variant]
                        if census and not allocators[build]: continue
                        print(f'{name}/{workers}/{variant}/{repeat}', file=__import__('sys').stderr, flush=True)
                        operations = ([{'type': 'partition', 'columns': ['key']}] if parents > 1 else []) + [{'type': 'shuffle', 'strategy': 'auto' if variant.startswith('buckets_') else 'uniform'}]
                        if downstream: operations.append({'type': 'balanced', 'files': downstream})
                        job = {'input': str(source), 'output': str(output), 'seed': seed, 'operations': operations, 'resources': {'memory_mb': memory, 'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(root)}, 'limits': {'rows': 50000, 'bytes': 20000000}}
                        if variant != 'seeded_merge': job['full_shuffle_policy'] = 'flexible_v1'
                        if variant.startswith('buckets_'): job['full_shuffle_algorithm'] = 'independent_buckets_v1'
                        if variant == 'buckets_xof64': job['full_shuffle_rng'] = 'blake3_xof_v1'
                        config.write_text(json.dumps(job))
                        binary = allocators[build].resolve() if census else binaries[build]
                        command = [str(binary), str(config)] if census else [str(binary), 'run', '--config', str(config), '--yes']
                        sampler = StorageSampler(root, [source, config, stats]) if census and args.sample_storage else None
                        if sampler: sampler.thread.start()
                        start = time.perf_counter()
                        try:
                            result = subprocess.run(['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(stats), *command], capture_output=True, text=True, timeout=900)
                        finally:
                            elapsed = time.perf_counter() - start
                            sample = sampler.finish() if sampler else None
                        if result.returncode: raise RuntimeError(f'{name}/{variant}: {result.stderr}')
                        result = json.loads(result.stdout); analysis = result['analysis'] if census else result
                        manifest = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                        entries = [e for e in manifest if e['type'] == 'output']
                        summaries = [e for e in manifest if e['type'] == 'execution_bucket_summary']
                        choices = [e for e in manifest if e['type'] == 'execution_group']
                        assert len(summaries) == (len(parent_counts) if variant.startswith('buckets_') else 0)
                        if summaries:
                            assert all(s['fanout'] == 16 and s['maximum_routing_depth'] == 2 and s['maximum_routing_attempts'] == 17 and s['statistics']['routing_attempts'] <= 17 and s['statistics']['maximum_depth'] <= 2 for s in summaries)
                            assert all(c['algorithm'] == 'independent-random-buckets-v1' and c['uniform_full_permutation'] for c in choices)
                            if name == 'forced_overflow':
                                target = next(s for s in summaries if s['physical_parent_lineage'][-1]['values'] == ['target'])
                                assert target['statistics']['maximum_depth'] == 2 and target['statistics']['fallback_leaves'] == 1 and target['statistics']['completed_routing_passes'] == 2
                        seen, counts, order, digest = bytearray(rows), collections.Counter(), [], hashlib.sha256()
                        for e in entries:
                            lineage = e['lineage']
                            parent = next(v['values'][0] for v in lineage if 'values' in v) if parents > 1 else 'all'
                            part = lineage[-1]['part'] if downstream else 0
                            assert len(lineage) == int(parents > 1) + int(bool(downstream))
                            if parents > 1: assert lineage[0]['operation'] == 0
                            if downstream: assert lineage[-1]['operation'] == int(parents > 1) + 1
                            order.append((parent, part))
                            data = (output / e['path']).read_bytes(); digest.update(data)
                            assert len(data) == e['csv_bytes'] <= 20000000
                            with (output / e['path']).open(newline='') as stream:
                                reader = csv.reader(stream); assert next(reader) == header; count = 0
                                for row in reader:
                                    i = int(row[0]); assert 0 <= i < rows and not seen[i] and row == fields(i)
                                    if parents > 1: assert row[1] == parent
                                    seen[i] = 1; count += 1
                            assert count == e['rows'] <= 50000
                            counts[parent, part] += count
                        assert all(seen) and order == sorted(order)
                        for parent, count in parent_counts.items():
                            if downstream:
                                for part in range(1, downstream + 1): assert counts[parent, part] == count // downstream + int(part <= count % downstream)
                            else: assert counts[parent, 0] == count
                        assert len(entries) == analysis['output_files'] and sum(e['csv_bytes'] for e in entries) == analysis['output_csv_bytes']
                        metadata = [{k: e[k] for k in ['path', 'lineage', 'rows', 'csv_bytes']} for e in entries]
                        metadata_hash = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
                        actual = (digest.hexdigest(), metadata_hash, analysis['stages'], analysis['logical_digest'])
                        reference_key = 'v1_exact' if not variant.startswith('buckets_') else variant
                        assert references.setdefault(reference_key, actual) == actual, (name, workers, variant)
                        assert references.setdefault('logical', (analysis['stages'], analysis['logical_digest'])) == (analysis['stages'], analysis['logical_digest'])
                        user, system, rss, fs_in, fs_out = map(float, stats.read_text().split())
                        record = {'type': 'allocation' if census else 'measurement', 'case': name, 'workers': workers, 'variant': variant, 'repeat': repeat, 'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': rss, 'filesystem_inputs': fs_in, 'filesystem_outputs': fs_out, 'peak_temp_bytes': analysis['peak_temp_bytes'], 'diagnostics': analysis['diagnostics'], 'bucket_summaries': summaries, 'output_sha256': digest.hexdigest(), 'metadata_sha256': metadata_hash, 'logical_digest': analysis['logical_digest'], 'verified': True}
                        if sample: record['storage_sample'] = sample
                        if census:
                            record['allocation_profile'] = result['allocation_profile']
                            if 'post_publication_diagnostics' in result:
                                record['post_publication_diagnostics'] = result['post_publication_diagnostics']; record['post_publication_peak_temp_bytes'] = result['post_publication_peak_temp_bytes']
                        else: measures[variant].append(elapsed)
                        print(json.dumps(record), flush=True); shutil.rmtree(output)
                if measures: print(json.dumps({'type': 'summary', 'case': name, 'workers': workers, 'median_seconds': {k: statistics.median(v) for k, v in measures.items()}, 'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()}}), flush=True)


if __name__ == '__main__':
    main()
