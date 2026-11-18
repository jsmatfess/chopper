"""Summarize retained allocation experiments without pooling different builds."""
import collections
import hashlib
import json
from pathlib import Path
import statistics


def aggregate(records, fields):
    result = {}
    for field in fields:
        values = [record[field] for record in records if field in record]
        if values:
            result[field] = {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    return result


def main():
    root = Path('docs/benchmarks')
    output = {'scope': 'Different binaries/builds, timing jobs and instrumented censuses are separate groups; no physical SSD or hard RSS-cap claim.', 'files': {}, 'native': {}, 'engines': {}, 'censuses': {}}
    for path in sorted(root.glob('allocation-ranges-*.jsonl')):
        records = [json.loads(line) for line in path.open()]
        output['files'][path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'records': len(records), 'types': dict(collections.Counter(r.get('type', r.get('event', 'job')) for r in records))}
        groups = collections.defaultdict(list)
        for record in records:
            if record.get('type') == 'measurement': groups[record['case'], record['workers'], record['variant']].append(record)
        if groups:
            output['native'][path.name] = [{'case': key[0], 'workers': key[1], 'variant': key[2], 'count': len(group), **aggregate(group, ['seconds', 'cpu_seconds', 'peak_rss_kib', 'peak_temp_bytes', 'filesystem_inputs', 'filesystem_outputs'])} for key, group in groups.items()]
        groups = collections.defaultdict(list)
        for record in records:
            if 'engine' in record: groups[record['case'], record['engine']].append(record)
        if groups:
            output['engines'][path.name] = [{'case': key[0], 'engine': key[1], 'count': len(group), **aggregate(group, ['elapsed_seconds', 'analysis_wall_seconds', 'execution_seconds'])} for key, group in groups.items()]
        censuses = [r for r in records if r.get('type') == 'allocation']
        if censuses: output['censuses'][path.name] = censuses
    (root / 'allocation-ranges-summary-2026-10-19.json').write_text(json.dumps(output, indent=2) + '\n')


if __name__ == '__main__':
    main()
