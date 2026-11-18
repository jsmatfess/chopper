#!/usr/bin/env python3
"""Reproduce the curated 2026-10-20 decision cells; never run benchmarks.

Each selection is explicit and stays within one artifact. Raw environment and
fixture records are retained as context, not completed from adjacent artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks/performance-decisions-2026-10-20.json'
DOCUMENT = ROOT / 'docs/performance-decisions.md'

# ID, artifact, filters, baseline label, candidate label. Untyped engine records
# are admitted only for the named engine harness files below, with verified=True.
CELLS = []
EXCLUDED = {
    'parallel-profile-initial-native-2026-10-16.jsonl': 'Superseded batch sizing; preserve narrow/rare-wide regressions as design evidence.',
    'parallel-profile-revised-first-wide-2026-10-16.jsonl': 'Superseded first-record sizing failure; final serial guard is a separate pass.',
    'parallel-groups-revised-native-2026-10-16.jsonl': 'Previous default baseline; final matched-source native matrix selected instead.',
    'nested-balanced-initial-native-2026-10-17.jsonl': 'Interrupted superseded candidate with different lineage retention.',
    'partition-balanced-recheck-2026-10-18.jsonl': 'Separate five-repeat sensitivity pass; does not replace noisy primary cells.',
    'streaming-chain-initial-native-2026-10-18.jsonl': 'Superseded eager-routing candidate; retain its small-job regression.',
    'flexible-policy-initial-native-2026-10-18.jsonl': 'Overlapped validation/build activity; final isolated pass selected.',
    'allocation-ranges-native-2026-10-18.jsonl': 'Prototype before final borrowed-audit build; not pooled with final native timings.',
    'allocation-ranges-input-eviction-2026-10-19.jsonl': 'Input-only eviction requests; not cold-device evidence or final-build repetitions.',
    'shuffle-partition-multilevel-engines-2026-10-16.jsonl': 'Incomplete browser attempt; storage failure evidence, not a complete paired timing.',
    'dynamic-pressure-boundaries-2026-10-16.jsonl': 'Configured boundary controls overlapped browser contracts; correctness only.',
    'random-buckets-diagnostics-native-2026-10-19.jsonl': 'Separate quality family with two original window flags; not throughput observations.',
    'random-buckets-window-followup-2026-10-19.jsonl': 'Separate quality follow-up; cannot erase original flags or add independent timing repetitions.',
}


def cell(key, file, case, baseline='baseline', candidate='candidate', **filters):
    CELLS.append((key, file + '.jsonl', dict(case=case, **filters), baseline, candidate))


cell('shuffle-native', 'shuffle-partition-native-2026-10-16', 'shuffle_partition', shape='columns', workers=4)
cell('shuffle-browser', 'shuffle-partition-persistent-engines-2026-10-17', 'shuffle_partition', 'browser-original', 'browser-fused', shape='columns', workers=1)
cell('nested-native', 'nested-balanced-native-2026-10-17', 'nested_deep', shape='columns', workers=4)
cell('nested-browser', 'nested-balanced-engines-2026-10-17', 'nested_deep', 'browser-serial', 'browser-fused', shape='columns', workers=1)
cell('constant-native', 'constant-partition-native-2026-10-17', 'constant_repeat', shape='columns', workers=4)
cell('constant-browser', 'constant-partition-partial-engines-2026-10-17', 'constant_partial', 'browser-original', 'browser-reduced', shape='columns', workers=1)
cell('consecutive-native', 'consecutive-partitions-independent-2026-10-17', 'consecutive', shape='independent', workers=4)
cell('consecutive-browser-small', 'consecutive-partitions-independent-engines-2026-10-17', 'consecutive', 'browser-original', 'browser-fused', shape='independent', workers=1)
cell('consecutive-browser-large', 'consecutive-partitions-multilevel-repeated-engines-2026-10-17', 'consecutive', 'browser-original', 'browser-fused', shape='independent', workers=1)
cell('partition-balanced-native', 'partition-balanced-multilevel-2026-10-18', 'partition_balanced', shape='columns', workers=4)
cell('partition-balanced-browser', 'partition-balanced-multilevel-engines-2026-10-18', 'partition_balanced', 'browser-original', 'browser-fused', shape='columns', workers=1)
for case in ['chain_probability', 'chain_interleaved']:
    cell(case + '-native', 'streaming-chain-multilevel-2026-10-18', case, shape='columns', workers=4)
    cell(case + '-browser', 'streaming-chain-multilevel-engines-2026-10-18', case, 'browser-original', 'browser-fused', shape='columns', workers=1)
# Profile CLI wall time includes startup and the full scan, not job execution.
CELLS.append(('profile-columns', 'parallel-profile-native-2026-10-16.jsonl', {'shape': 'many', 'workers': 4}, 'baseline', 'candidate'))
CELLS.append(('profile-rare-wide', 'parallel-profile-native-2026-10-16.jsonl', {'shape': 'rare_wide', 'workers': 4}, 'baseline', 'candidate'))
cell('groups-columns', 'parallel-groups-native-2026-10-16', 'grouped', shape='columns', workers=4)
cell('groups-skew', 'parallel-groups-skew-2026-10-16', 'skew', shape='skew', workers=4)
cell('spill-native', 'spill-blocks-native-2026-10-16', 'global', shape='columns', workers=4)
cell('spill-browser', 'spill-blocks-engines-2026-10-16', 'global', 'browser-v1', 'browser-blocks', shape='columns', workers=1)
cell('flexible-policy', 'flexible-policy-native-2026-10-18', 'resident', 'candidate/seeded_v1', 'candidate/auto', workers=1)
cell('partition-first-sequential', 'partition-first-native-2026-10-18', 'balanced', 'sequential', 'candidate', workers=1)
cell('partition-first-exact', 'partition-first-native-2026-10-18', 'balanced', 'exact', 'candidate', workers=1)
cell('xof-flexible', 'fast-rng-focused-native-2026-10-18', 'resident_fisher', 'after_v1', 'xof64', workers=1)
cell('xof-seeded', 'fast-rng-focused-native-2026-10-18', 'resident_fisher', 'seeded_v1', 'xof64', workers=1)
for case in ['uniform', 'external', 'many', 'rare_wide']:
    cell('ranges-' + case, 'allocation-ranges-final-native-2026-10-19', case, 'standard', 'candidate', workers=1)
cell('ranges-existing-fusion', 'allocation-ranges-final-native-2026-10-19', 'rare_wide', 'assignment_shuffle', 'candidate', workers=1)
cell('ranges-browser', 'allocation-ranges-engines-2026-10-19', 'flex_allocate_auto', 'browser-before', 'browser')
cell('buckets-native', 'random-buckets-multilevel-native-2026-10-19', 'multilevel', 'seeded_merge', 'buckets_v1', workers=1)
cell('buckets-flexible', 'random-buckets-multilevel-native-2026-10-19', 'multilevel', 'flex_merge', 'buckets_v1', workers=1)
cell('shared-admission', 'shared-memory-native-2026-10-16', 'spill', 'before', 'after', workers=1)
cell('pressure-recheck', 'dynamic-pressure-native-2026-10-16', 'spill', 'before', 'after', workers=1)
# Same binary, different explicit algorithms/cases, with no seeded-order equality.
cell('resident-native', 'resident-browser-2026-10-15', None, 'native', 'native', engine_case_pair=['uniform256', 'fisher256'])
cell('resident-browser', 'resident-browser-2026-10-15', None, 'browser', 'browser', engine_case_pair=['uniform256', 'fisher256'])


def stats(values):
    return {'n': len(values), 'median': statistics.median(values), 'min': min(values), 'max': max(values)} if values else None


def read_source(name):
    path = ROOT / 'docs/benchmarks' / name
    raw = path.read_bytes()
    rows = [(i, json.loads(line)) for i, line in enumerate(raw.decode().splitlines(), 1) if line.strip()]
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'records': rows}


def label(row):
    return row.get('variant', row.get('build', row.get('engine')))


def generate():
    sources = {name: read_source(name) for name in sorted({spec[1] for spec in CELLS})}
    output = {'schema_version': 1, 'type': 'derived_decision_table',
              'analysis_script': 'scripts/summarize-performance-decisions.py',
              'analysis_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'effect': '100 * (candidate median seconds / baseline median seconds - 1); negative is faster',
              'scope': 'Curated contrasts, not a pooled estimate or exhaustive corpus. Repetitions are nested in each cell. Ranges are observed min/max, not confidence intervals.',
              'sources': {}, 'cells': []}
    output['excluded_from_timing'] = [
        {'source': name, 'source_sha256': read_source(name)['sha256'], 'reason': reason}
        for name, reason in EXCLUDED.items()
    ]
    for name, source in sources.items():
        contexts = [{'line': i, 'data': r} for i, r in source['records'] if r.get('type', r.get('event')) in ['environment', 'fixture', 'design']]
        output['sources'][name] = {'sha256': source['sha256'], 'context_records': contexts}
    for key, name, filters, baseline, candidate in CELLS:
        source = sources[name]
        pair = filters.get('engine_case_pair')
        selected = []
        for index, variant in enumerate([baseline, candidate]):
            group = []
            for line, row in source['records']:
                if row.get('type') != 'measurement' and not ('engine' in row and row.get('type') is None):
                    continue
                if label(row) != variant:
                    continue
                if any(row.get(k) != v for k, v in filters.items() if k not in ['engine_case_pair', 'case']):
                    continue
                if 'case' in filters and row.get('case') != (pair[index] if pair else filters['case']):
                    continue
                if row.get('verified', row.get('profile_parity')) is not True:
                    raise ValueError(f'Unverified selection {name}:{line}')
                time_field = next(k for k in ['seconds', 'wall_seconds', 'elapsed_seconds'] if k in row)
                analysis = row.get('analysis', {})
                diag = row.get('diagnostics', analysis.get('diagnostics', {}))
                group.append({'line': line, 'repeat': row.get('repeat'), 'seconds_field': time_field, 'seconds': row[time_field],
                              'cpu_seconds': row.get('cpu_seconds'), 'peak_rss_kib': row.get('peak_rss_kib'),
                              'peak_workspace_reserved_bytes': diag.get('peak_workspace_reserved_bytes'),
                              'preparation_peak_temp_bytes': row.get('peak_temp_bytes', analysis.get('peak_temp_bytes')),
                              'preparation_temporary_bytes_read': diag.get('temporary_bytes_read'),
                              'preparation_temporary_bytes_written': diag.get('temporary_bytes_written'),
                              'sort_runs': diag.get('sort_runs'), 'merge_operations': diag.get('merge_operations'),
                              'workers': row.get('workers', analysis.get('workers')),
                              'rows': row.get('rows', analysis.get('rows')),
                              'memory_budget_bytes': analysis.get('memory_budget_bytes'),
                              'verified': True})
            if not group:
                raise ValueError(f'Empty selection {key}: {variant}, {filters}')
            repeats = [r['repeat'] for r in group]
            if len(set(repeats)) != len(repeats):
                raise ValueError(f'Duplicate repeats in {key}')
            selected.append({'label': variant, 'samples': group, 'seconds': stats([r['seconds'] for r in group])})
        if [r['repeat'] for r in selected[0]['samples']] != [r['repeat'] for r in selected[1]['samples']]:
            raise ValueError(f'Unmatched repeat identities {key}')
        output['cells'].append({'id': key, 'source': name, 'source_sha256': source['sha256'], 'filters': filters,
                                'timing_scope': 'CLI startup plus fresh full-file profile' if key.startswith('profile-') else 'Complete job including publication/export; see source context and dated narrative for exclusions',
                                'baseline': selected[0], 'candidate': selected[1],
                                'median_elapsed_change_percent': 100 * (selected[1]['seconds']['median'] / selected[0]['seconds']['median'] - 1)})
    return json.dumps(output, indent=2, ensure_ascii=False) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check retained analysis without rewriting it')
    args = parser.parse_args()
    rendered = generate()
    audit = []
    for entry in json.loads(rendered)['cells']:
        before, after = entry['baseline']['seconds'], entry['candidate']['seconds']
        audit.append(
            f"| `{entry['id']}` | {before['median']:.4f} ({before['min']:.4f}–{before['max']:.4f}) "
            f"| {after['median']:.4f} ({after['min']:.4f}–{after['max']:.4f}) "
            f"| {entry['median_elapsed_change_percent']:+.1f}% | {before['n']} / {after['n']} |"
        )
    document = DOCUMENT.read_text()
    table_start = '| Cell ID | Baseline seconds | Candidate seconds | Change | Samples per side |\n| --- | ---: | ---: | ---: | ---: |\n'
    prefix, found_start, rest = document.partition(table_start)
    _, found_end, suffix = rest.partition('\n## Eligibility, controls and gaps\n')
    if not found_start or not found_end:
        raise SystemExit('Cannot locate the numerical audit table boundaries')
    updated_document = prefix + found_start + '\n'.join(audit) + '\n' + found_end + suffix
    if args.check:
        if OUT.read_text() != rendered or document != updated_document:
            raise SystemExit('Decision cells are stale; rerun scripts/summarize-performance-decisions.py')
    else:
        OUT.write_text(rendered)
        DOCUMENT.write_text(updated_document)
    print(f'{len(CELLS)} matched decision cells {"checked" if args.check else "written"}')


if __name__ == '__main__':
    main()
