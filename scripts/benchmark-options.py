"""Compare explicit opt-in algorithms with existing semantics on warm local storage.

Outputs intentionally differ. Verify complete row preservation, stable destination
subsequences for allocation/splitting, balance, logical digests and seeded replay.
Timings cover CLI preparation and publication, excluding fixture/checking time.
"""
import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=200000)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.rows < 100 or args.repeats < 1:
        parser.error('need at least 100 rows and one repeat')
    binary = args.binary.resolve()
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required')
    groups = [{'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}]
    cases = [
        ('shuffle', {'type': 'shuffle', 'strategy': 'uniform'}, {'type': 'shuffle', 'strategy': 'fisher_yates'}, 256),
        ('balanced', {'type': 'balanced', 'files': 4}, {'type': 'interleaved', 'files': 4}, 32),
        ('assign', {'type': 'assign', 'groups': groups}, {'type': 'assign_probabilistic', 'groups': groups}, 32),
        ('stratified_assign', {'type': 'assign', 'groups': groups, 'strata': ['stratum']},
         {'type': 'assign_probabilistic', 'groups': groups, 'strata': ['stratum']}, 32),
    ]
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
                      'repeats': args.repeats, 'cache': 'warm, uncontrolled',
                      'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-options-') as directory:
        root = Path(directory)
        source = root / 'input.csv'
        header = 'id,stratum,payload\n'
        records = [f'{i},{i % 10000},{"x" * 32}\n' for i in range(args.rows)]
        source.write_text(header + ''.join(records))
        for case, old, new, memory in cases:
            measurements = {'existing': [], 'option': []}
            references = {}
            logical_digest = None
            for repeat in range(args.repeats):
                versions = [('existing', old), ('option', new)]
                if repeat % 2:
                    versions.reverse()
                for label, operation in versions:
                    config = {'input': str(source), 'output': str(root / 'out'), 'seed': 'options-v1',
                              'operations': [operation], 'resources': {'memory_mb': memory, 'workers': 1,
                              'max_record_bytes': 1048576, 'temp_dir': str(root)}}
                    (root / 'job.json').write_text(json.dumps(config))
                    stats = root / 'time.txt'
                    started = time.perf_counter()
                    result = subprocess.run([timer, '-f', '%U %S %M', '-o', str(stats), str(binary),
                                             'run', '--config', str(root / 'job.json'), '--yes'],
                                            text=True, capture_output=True, timeout=300, check=True)
                    elapsed = time.perf_counter() - started
                    analysis = json.loads(result.stdout)
                    user, system, rss = map(float, stats.read_text().split())
                    if logical_digest is None:
                        logical_digest = analysis['logical_digest']
                    assert logical_digest == analysis['logical_digest']
                    seen = set()
                    fingerprint = []
                    counts = []
                    entries = [json.loads(line) for line in (root / 'out' / 'manifest.jsonl').read_text().splitlines()]
                    for entry in entries:
                        if entry['type'] != 'output':
                            continue
                        path = root / 'out' / entry['path']
                        lines = path.read_text().splitlines(keepends=True)
                        assert lines[0] == header
                        previous = -1
                        for line in lines[1:]:
                            row = int(line.split(',')[0])
                            assert 0 <= row < args.rows and row not in seen
                            assert line == records[row]
                            if case != 'shuffle':
                                assert row > previous
                            if case == 'balanced' and label == 'option':
                                assert row % 4 == len(counts)
                            previous = row
                            seen.add(row)
                        assert len(lines) - 1 == entry['rows']
                        assert path.stat().st_size == entry['csv_bytes']
                        counts.append(entry['rows'])
                        fingerprint.append((entry['path'], hashlib.sha256(path.read_bytes()).hexdigest()))
                    assert len(seen) == args.rows
                    if case == 'balanced':
                        assert len(counts) == 4 and max(counts) - min(counts) <= 1
                    if label in references:
                        assert references[label] == fingerprint
                    references[label] = fingerprint
                    measurements[label].append(elapsed)
                    print(json.dumps({'type': 'measurement', 'case': case, 'variant': label, 'repeat': repeat + 1,
                                      'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': int(rss),
                                      'counts': counts, 'diagnostics': analysis['diagnostics'], 'verified': True}), flush=True)
                    shutil.rmtree(root / 'out')
            medians = {key: statistics.median(values) for key, values in measurements.items()}
            print(json.dumps({'type': 'summary', 'case': case, 'median_seconds': medians,
                              'range_seconds': {key: [min(values), max(values)] for key, values in measurements.items()},
                              'speedup': medians['existing'] / medians['option']}), flush=True)


if __name__ == '__main__':
    main()
