# Historical reproduction only: targets pinned pre-removal builds, not the current engine.
# Buffer-shuffle requests below are retained to interpret the recorded evidence.
"""Fixed, preregistered full-shuffle diagnostics; see docs/shuffling-research.md.

Uses only the Python standard library. Output is JSONL, including every seed and
null corpus summary. No throughput inference or statistical proof is intended.
"""
import argparse
import csv
import hashlib
import inspect
import json
from pathlib import Path
import platform
import random
import shutil
import statistics
import subprocess
import tempfile


SEEDS = [f'shuffle-diagnostic-v1-{i:02}' for i in range(32)]
PATTERNS = ['ascending', 'descending', 'blocks', 'periodic', 'skewed']
METRICS = ['position_bins', 'displacement', 'source_adjacency', 'longest_label_run',
           'window_labels', 'label_adjacency']
NULL_CORPORA = 2047
PILOT = 1024


def fixture(pattern):
    groups = []
    start = 0
    for group, size in enumerate([192, 48, 16] if pattern == 'skewed' else [256]):
        rows = []
        for position in range(size):
            value = size - position - 1 if pattern == 'descending' else position
            label = position % 4 if pattern == 'periodic' else position * 4 // size
            if pattern == 'skewed':
                label = int(position >= size * 3 // 4)
            rows.append([str(start + position), str(value), str(label), str(group)])
        groups.append(rows)
        start += size
    return groups


def discrepancy(cells):
    columns = [sum(row[i] for row in cells) for i in range(len(cells[0]))]
    total = sum(columns)
    result = 0.0
    for row in cells:
        for value, marginal in zip(row, columns):
            expected = sum(row) * marginal / total
            if expected:
                result += (value - expected) ** 2 / expected
    return result


def metrics(order, labels):
    n = len(order)
    positions = [[0] * 4 for _ in range(4)]
    windows = [[0] * 4 for _ in range(3)]
    displacement = adjacent = same = 0
    longest = run = 1
    previous = None
    for output, source in enumerate(order):
        label = labels[source]
        positions[output * 4 // n][source * 4 // n] += 1
        windows[output * 3 // n][label] += 1
        displacement += abs(source - output)
        if previous is not None:
            adjacent += abs(source - previous) == 1
            equal = label == labels[previous]
            same += equal
            run = run + 1 if equal else 1
            longest = max(longest, run)
        previous = source
    return [discrepancy(positions), displacement / (n * n),
            adjacent / (n - 1), longest / n, discrepancy(windows), same / (n - 1)]


def combined(orders, groups):
    total = sum(map(len, groups))
    result = [0.0] * len(METRICS)
    for order, group in zip(orders, groups):
        values = metrics(order, [int(row[2]) for row in group])
        for index, value in enumerate(values):
            result[index] += value * len(group) / total
    return result


def null_distribution(pattern, groups, emit):
    domain = 'shuffle-diagnostic-null-v1/' + pattern
    rng = random.Random(int.from_bytes(hashlib.sha256(domain.encode()).digest(), 'big'))

    def draw():
        orders = []
        for group in groups:
            order = list(range(len(group)))
            rng.shuffle(order)
            orders.append(order)
        return combined(orders, groups)

    pilot = [draw() for _ in range(PILOT)]
    center = [statistics.mean(row[i] for row in pilot) for i in range(len(METRICS))]
    corpora = []
    for _ in range(NULL_CORPORA):
        samples = [draw() for _ in SEEDS]
        corpora.append([statistics.mean(row[i] for row in samples) for i in range(len(METRICS))])
    emit({'type': 'null', 'pattern': pattern, 'domain': domain, 'pilot': PILOT,
          'corpora': NULL_CORPORA, 'center': dict(zip(METRICS, center)),
          'statistics': {metric: {'mean': statistics.mean(row[i] for row in corpora),
                                'interval_95': [sorted(row[i] for row in corpora)[q]
                                                for q in [51, 1995]]}
                         for i, metric in enumerate(METRICS)}})
    return center, corpora


def verify(output, analysis, groups, partition_step=None):
    entries = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
    expected = {row[0]: (index, position, row) for index, group in enumerate(groups)
                for position, row in enumerate(group)}
    orders = [None] * len(groups)
    seen = set()
    group_order = []
    fingerprint = hashlib.sha256()
    for entry in entries:
        if entry['type'] != 'output':
            continue
        path = output / entry['path']
        assert path.stat().st_size == entry['csv_bytes']
        fingerprint.update(path.read_bytes())
        fingerprint.update(json.dumps({key: entry[key] for key in
                                       ['path', 'lineage', 'rows', 'csv_bytes']}, sort_keys=True).encode())
        with path.open(newline='') as source:
            reader = csv.reader(source)
            assert next(reader) == ['id', 'value', 'label', 'group']
            rows = list(reader)
        assert len(rows) == entry['rows'] and rows
        group_index = expected[rows[0][0]][0]
        group_order.append(group_index)
        if partition_step is not None:
            assert entry['lineage'][-1]=={'operation':partition_step,'values':[str(group_index)]}
        assert orders[group_index] is None
        order = []
        for row in rows:
            index, position, reference = expected[row[0]]
            assert index == group_index and row == reference and row[0] not in seen
            seen.add(row[0])
            order.append(position)
        assert len(order) == len(groups[group_index])
        orders[group_index] = order
    assert group_order==list(range(len(groups)))
    assert seen == expected.keys() and all(order is not None for order in orders)
    assert analysis['rows'] == len(expected) and analysis['output_files'] == len(groups)
    assert analysis['groups'] == len(groups)
    assert analysis['stages'][-1]['output_groups'] == len(groups)
    assert analysis['diagnostics']['workspace_reserved_bytes'] == analysis['diagnostics'].get('temporary_path_reserved_bytes', 0) + analysis['diagnostics'].get('input_header_reserved_bytes', 0)
    return orders, fingerprint.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--full-shuffle-rng',choices=['blake3_counter_v1','blake3_xof_v1'],default='blake3_counter_v1')
    parser.add_argument('--partition-first',action='store_true')
    parser.add_argument('--independent-buckets',action='store_true')
    parser.add_argument('--null-cache',type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    if (args.partition_first and args.independent_buckets) or ((args.partition_first or args.independent_buckets) and args.full_shuffle_rng!='blake3_counter_v1'):parser.error('combined family is not preregistered')
    experimental=args.partition_first or args.independent_buckets or args.full_shuffle_rng!='blake3_counter_v1'
    family='independent-buckets-full-shuffle-v1' if args.independent_buckets else 'flexible-partition-first-v1' if args.partition_first else 'blake3-xof-full-shuffle-v1' if experimental else 'shuffle-diagnostic-v1'
    null_cache=None
    if args.null_cache:
        null_cache=json.loads(args.null_cache.read_text())
        source=''.join(inspect.getsource(globals()[name]) for name in ['fixture','metrics','discrepancy','combined','null_distribution'])
        expected={'version':'shuffle-diagnostic-null-v1','python':platform.python_version(),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'seeds':SEEDS,'patterns':PATTERNS,'metrics':METRICS,'pilot':PILOT,'corpora':NULL_CORPORA}
        assert null_cache['contract']==expected,'null calibration contract changed'

    def emit(record):
        print(json.dumps(record), flush=True)

    emit({'type': 'design', 'version': family, 'full_shuffle_rng':args.full_shuffle_rng,'partition_first':args.partition_first,'independent_buckets':args.independent_buckets,'null_cache_sha256':hashlib.sha256(args.null_cache.read_bytes()).hexdigest() if args.null_cache else None,'platform': platform.platform(),
          'python': platform.python_version(), 'seeds': SEEDS, 'rows': 256, 'workers': 1,
          'memory_mb': 64, 'buffer_rows': 4, 'alpha': 0.05, 'primary_comparisons': 60,
          'control_comparisons': 30, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'design_sha256': hashlib.sha256((Path(__file__).resolve().parent.parent /
                                         ('docs/independent-buckets-acceptance.md' if args.independent_buckets else 'docs/fast-rng-acceptance.md' if experimental else 'docs/shuffling-research.md')).read_bytes()).hexdigest()})
    flags = {'primary': [], 'control': []}
    with tempfile.TemporaryDirectory(prefix='chopper-diagnostic-') as directory:
        root = Path(directory)
        for pattern in PATTERNS:
            groups = fixture(pattern)
            if null_cache:
                calibration=null_cache['patterns'][pattern];center=calibration['center'];null=calibration['corpora'];emit(calibration['record'])
                assert len(null)==NULL_CORPORA and len(center)==len(METRICS)
            else:center, null = null_distribution(pattern, groups, emit)
            source = root / 'input.csv'
            with source.open('w', newline='') as output:
                writer = csv.writer(output, lineterminator='\n')
                writer.writerow(['id', 'value', 'label', 'group'])
                writer.writerows(row for group in groups for row in group)
            samples = {algorithm: [] for algorithm in (['auto','uniform','buffer'] if args.partition_first or args.independent_buckets else ['uniform','fisher_yates','buffer'])}
            logical_digest = None
            for seed in SEEDS:
                for algorithm in samples:
                    operations = ([{'type': 'partition', 'columns': ['group']}]
                                  if len(groups) > 1 else [])
                    operations += [{'type': 'shuffle', 'strategy': algorithm, 'buffer_rows': 4}]
                    if args.partition_first:operations=[{'type':'shuffle','strategy':algorithm,'buffer_rows':4},{'type':'partition','columns':['group']}]
                    job = {'input': str(source), 'output': str(root / 'output'), 'seed': seed,
                           'operations': operations,
                           'resources': {'memory_mb': 64, 'workers': 1,
                                         'max_record_bytes': 2097152, 'temp_dir': str(root)}}
                    if experimental:job['full_shuffle_policy']='flexible_v1'
                    if args.independent_buckets:job['full_shuffle_algorithm']='independent_buckets_v1'
                    if args.full_shuffle_rng!='blake3_counter_v1':job['full_shuffle_rng']=args.full_shuffle_rng
                    config = root / 'job.json'
                    config.write_text(json.dumps(job))
                    result = subprocess.run([str(binary), 'run', '--config', str(config), '--yes'],
                                            capture_output=True, text=True, timeout=120)
                    if result.returncode:
                        raise RuntimeError(result.stderr)
                    analysis = json.loads(result.stdout)
                    orders, fingerprint = verify(root / 'output', analysis, groups,1 if args.partition_first else 0 if len(groups)>1 else None)
                    if args.independent_buckets:
                        audit=[json.loads(line) for line in (root/'output'/'manifest.jsonl').read_text().splitlines()]
                        choices=[r for r in audit if r['type']=='execution_group']
                        summaries=[r for r in audit if r['type']=='execution_bucket_summary']
                        if algorithm=='auto':
                            assert len(summaries)==len(groups) and all(c['algorithm']=='independent-random-buckets-v1' for c in choices)
                            assert all(r['statistics']['completed_routing_passes']==1 and r['statistics']['routing_attempts']==1 and r['statistics']['fallback_leaves']==0 for r in summaries)
                        else:assert not summaries and not any(c['algorithm']=='independent-random-buckets-v1' for c in choices)
                    if logical_digest is not None:
                        assert analysis['logical_digest'] == logical_digest
                    logical_digest = analysis['logical_digest']
                    values = combined(orders, groups)
                    samples[algorithm].append(values)
                    emit({'type': 'sample', 'pattern': pattern, 'algorithm': algorithm, 'seed': seed,
                          'metrics': dict(zip(METRICS, values)), 'fingerprint': fingerprint,
                          'logical_digest': logical_digest, 'verified': True})
                    shutil.rmtree(root / 'output')
            for algorithm, values in samples.items():
                family = 'control' if algorithm == 'buffer' else 'primary'
                threshold = 0.05 / (30 if family == 'control' else 60)
                for i, metric in enumerate(METRICS):
                    observed = statistics.mean(row[i] for row in values)
                    departure = abs(observed - center[i])
                    p = (1 + sum(abs(row[i] - center[i]) >= departure for row in null)) / (1 + len(null))
                    flagged = p <= threshold
                    key = f'{pattern}/{algorithm}/{metric}'
                    if flagged:
                        flags[family].append(key)
                    emit({'type': 'comparison', 'pattern': pattern, 'algorithm': algorithm,
                          'metric': metric, 'mean': observed, 'p': p, 'threshold': threshold,
                          'family': family, 'flagged': flagged})
    emit({'type': 'summary', 'jobs': len(SEEDS) * len(PATTERNS) * 3,
          'comparisons': 90, 'flags': flags, 'verified': True,
          'interpretation': 'Finite diagnostic only; no proof of uniformity or performance claim.'})


if __name__ == '__main__':
    main()
