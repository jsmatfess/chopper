#!/usr/bin/env python3
"""Summarize each recorded build/fixture separately; never pool censuses with timings."""
import collections
import hashlib
import json
from pathlib import Path
import statistics


def summarize(path):
    records = [json.loads(line) for line in path.read_text().splitlines()]
    groups = collections.defaultdict(list)
    for record in records:
        if record.get('type') == 'measurement' or record.get('engine'):
            assert record['verified']
            groups[(record['case'], record.get('workers', 1),
                    record.get('variant', record.get('engine')))].append(record)
    summaries = []
    for (case, workers, variant), samples in sorted(groups.items()):
        times = [r.get('seconds', r.get('elapsed_seconds')) for r in samples]
        item = dict(case=case, workers=workers, variant=variant, samples=len(samples),
                    median_seconds=statistics.median(times), range_seconds=[min(times), max(times)])
        for field in ['cpu_seconds', 'peak_rss_kib', 'peak_temp_bytes']:
            if all(field in r for r in samples):
                item[field] = [min(r[field] for r in samples), max(r[field] for r in samples)]
        spaces = [r.get('diagnostics', {}).get('storage') for r in samples]
        if all(spaces):
            assert all(s['workspace_bytes_after_cleanup'] == 0 and s['peak_open_handles'] <= 64 for s in spaces)
            item['browser_storage_ranges'] = {
                key: [min(s[key] for s in spaces), max(s[key] for s in spaces)]
                for key in ['workspace_peak_bytes', 'workspace_peak_files', 'profiled_destination_bytes',
                            'workspace_and_destination_peak_bytes', 'peak_open_handles']}
        summaries.append(item)
    allocations = [r for r in records if r.get('type') == 'allocation']
    assert all(r['verified'] for r in allocations)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                record_counts=dict(collections.Counter(r.get('type', r.get('event', 'engine_measurement')) for r in records)),
                environments=[r for r in records if r.get('type', r.get('event')) == 'environment'],
                timings=summaries, censuses=allocations)


if __name__ == '__main__':
    root = Path('docs/benchmarks')
    names = ['random-buckets-native-2026-10-19.jsonl', 'random-buckets-engines-2026-10-19.jsonl',
             'random-buckets-multilevel-native-2026-10-19.jsonl',
             'random-buckets-multilevel-engines-2026-10-19.jsonl',
             'random-buckets-default-engines-2026-10-19.jsonl',
             'random-buckets-default-multilevel-engines-2026-10-19.jsonl',
             'random-buckets-overflow-engines-2026-10-19.jsonl']
    result = dict(version='independent-buckets-measurements-v1',
                  scope='Warm uncontrolled WSL and Chromium OPFS; logical I/O and file sizes, no physical SSD claim.',
                  builds=[summarize(root / name) for name in names if (root / name).exists()])
    (root / 'random-buckets-summary-2026-10-19.json').write_text(json.dumps(result, indent=2) + '\n')
