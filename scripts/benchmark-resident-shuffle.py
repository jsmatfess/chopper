"""Compare complete resident random-key v1 and Fisher–Yates v1 jobs.

Build: cargo build --release --locked -p chopper-csv --bin chopper --example allocation-profile
Warm, uncontrolled local storage only. Timings include process startup, ingestion,
RNG, preparation, allocation, CSV serialization and publication; verification and
fixture creation are outside timing. Loop diagnostics exclude ingestion/output
and random-key generation. Algorithms have different seeded orders, so compare
exact bytes only within each algorithm, including across worker counts.
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


def fields(row, shape):
    values = [str(row), 'duplicate payload' if shape == 'narrow' else '0']
    if shape != 'narrow':
        values += [str((row + column) % 10) for column in range(31)]
    if shape == 'rare_wide' and row == 0:
        values[1] = 'x' * 1800000
    return values


def verify_workspace_owners(analysis):
    diagnostics = analysis['diagnostics']
    owners = [diagnostics.get(key, 0) for key in (
        'temporary_path_reserved_bytes', 'directory_path_reserved_bytes',
        'input_header_reserved_bytes')]
    assert all(type(value) is int and value >= 0 for value in owners), 'malformed owner charge'
    assert diagnostics['workspace_reserved_bytes'] == sum(owners)


def verify(output, analysis, shape, rows, groups):
    """Exact unique-ID conservation, field text, group isolation and byte counts."""
    seen = bytearray(rows)
    digest = hashlib.sha256()
    digest.update(json.dumps(analysis['stages'], sort_keys=True).encode())
    digest.update(analysis['logical_digest'].encode())
    entries = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
    count = 0
    header = ['id', 'payload'] + ([] if shape == 'narrow' else [f'c{i}' for i in range(31)])
    for entry in entries:
        if entry['type'] != 'output':
            continue
        path = output / entry['path']
        assert path.stat().st_size == entry['csv_bytes']
        digest.update(json.dumps({key: entry[key] for key in
                                 ['path', 'rows', 'csv_bytes', 'lineage']}, sort_keys=True).encode())
        with path.open('rb') as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
        members = 0
        # Balanced input groups are consecutive ranges, with larger groups first.
        start = count * (rows // groups) + min(count, rows % groups)
        end = start + rows // groups + int(count < rows % groups)
        with path.open(newline='') as source:
            records = csv.reader(source)
            assert next(records) == header
            for record in records:
                row = int(record[0])
                assert start <= row < end and not seen[row]
                assert record == fields(row, shape)
                seen[row] = 1
                members += 1
        assert members == entry['rows'] == end - start
        count += 1
    assert count == groups and all(seen)
    assert analysis['rows'] == rows and analysis['output_files'] == groups
    diagnostics = analysis['diagnostics']
    assert diagnostics['sort_runs'] == diagnostics['merge_operations'] == 0
    verify_workspace_owners(analysis)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--allocator', type=Path)
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--tiny-rows', type=int, default=16)
    parser.add_argument('--small-groups', type=int, default=100)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--memory-mb', type=int, default=1024)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--shapes', nargs='+', choices=['narrow', 'columns', 'rare_wide'],
                        default=['narrow', 'columns', 'rare_wide'])
    args = parser.parse_args()
    if min(args.rows, args.tiny_rows, args.small_groups, args.repeats, args.memory_mb, *args.workers) < 1:
        parser.error('all sizes, repeats and workers must be positive')
    if args.small_groups > args.rows:
        parser.error('small-groups must not exceed rows')
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required')
    csv.field_size_limit(2097152)

    def emit(record):
        print(json.dumps(record), flush=True)

    emit({'type': 'environment', 'platform': platform.platform(),
          'cpu': next((line.split(':', 1)[1].strip() for line in
                       Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown'),
          'rows': args.rows, 'tiny_rows': args.tiny_rows, 'small_groups': args.small_groups,
          'workers': args.workers, 'repeats': args.repeats, 'memory_mb': args.memory_mb,
          'seed': 'resident-comparison-v1', 'cache': 'warm, uncontrolled',
          'binary_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                            [('binary', args.binary), ('allocator', args.allocator)] if path}})
    with tempfile.TemporaryDirectory(prefix='chopper-resident-', dir=args.work_dir) as directory:
        root = Path(directory)
        for shape in args.shapes:
            for size, rows, groups in [('tiny', args.tiny_rows, 1), ('large', args.rows, 1),
                                       ('small_groups', args.rows, args.small_groups)]:
                source = root / 'input.csv'
                with source.open('w', newline='') as output:
                    writer = csv.writer(output, lineterminator='\n')
                    writer.writerow(['id', 'payload'] + ([] if shape == 'narrow' else [f'c{i}' for i in range(31)]))
                    for row in range(rows):
                        writer.writerow(fields(row, shape))
                references = {}
                logical_digest = None
                for workers in args.workers:
                    samples = {'uniform': [], 'fisher_yates': []}
                    for repeat in range(args.repeats + int(args.allocator is not None)):
                        allocation = repeat == args.repeats
                        variants = ['uniform', 'fisher_yates']
                        if repeat % 2:
                            variants.reverse()
                        for algorithm in variants:
                            operations = ([{'type': 'balanced', 'files': groups}] if groups > 1 else [])
                            operations += [{'type': 'shuffle', 'strategy': algorithm}]
                            job = {'input': str(source), 'output': str(root / 'output'),
                                   'seed': 'resident-comparison-v1', 'operations': operations,
                                   'resources': {'memory_mb': args.memory_mb, 'workers': workers,
                                                 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
                            config = root / 'job.json'
                            config.write_text(json.dumps(job))
                            binary = args.allocator if allocation else args.binary
                            command = [str(binary.resolve())] + ([str(config)] if allocation else
                                       ['run', '--config', str(config), '--yes'])
                            stats = root / 'time.txt'
                            started = time.perf_counter()
                            result = subprocess.run([timer, '-f', '%U %S %M', '-o', str(stats)] + command,
                                                    capture_output=True, text=True, timeout=600)
                            elapsed = time.perf_counter() - started
                            if result.returncode:
                                raise RuntimeError(f'{shape}/{size}/{algorithm}: {result.stderr}')
                            payload = json.loads(result.stdout)
                            analysis = payload['analysis'] if allocation else payload
                            actual = verify(root / 'output', analysis, shape, rows, groups)
                            shutil.rmtree(root / 'output')
                            if algorithm in references:
                                assert actual == references[algorithm], 'seeded replay/worker parity changed'
                            references[algorithm] = actual
                            if logical_digest is not None:
                                assert logical_digest == analysis['logical_digest']
                            logical_digest = analysis['logical_digest']
                            diagnostics = analysis['diagnostics']
                            prefix = 'fisher_yates' if algorithm == 'fisher_yates' else 'sort'
                            assert diagnostics[prefix + '_rows'] == rows
                            assert diagnostics[prefix + '_calls'] == groups
                            user, system, rss = map(float, stats.read_text().split())
                            record = {'type': 'allocation' if allocation else 'measurement',
                                      'shape': shape, 'size': size, 'rows': rows, 'groups': groups,
                                      'workers': workers, 'algorithm': algorithm, 'repeat': repeat + 1,
                                      'seconds': elapsed, 'cpu_seconds': user + system,
                                      'peak_rss_kib': int(rss), 'diagnostics': diagnostics,
                                      'timings': analysis['timings'], 'peak_temp_bytes': analysis['peak_temp_bytes'],
                                      'fingerprint': actual, 'verified': True}
                            if allocation:
                                record['allocation_profile'] = payload['allocation_profile']
                            else:
                                samples[algorithm].append(elapsed)
                            emit(record)
                    medians = {key: statistics.median(values) for key, values in samples.items()}
                    emit({'type': 'summary', 'shape': shape, 'size': size, 'workers': workers,
                          'median_seconds': medians,
                          'range_seconds': {key: [min(values), max(values)] for key, values in samples.items()},
                          'uniform_over_fisher_yates': medians['uniform'] / medians['fisher_yates'],
                          'verified': True})


if __name__ == '__main__':
    main()
