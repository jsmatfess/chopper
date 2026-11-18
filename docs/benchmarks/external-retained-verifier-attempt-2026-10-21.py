"""Alternate complete external-shuffle jobs and verify exact v1 parity.

Build both binaries with identical sources, changing only the experimental feature.
GNU time reports CPU, RSS and filesystem input/output blocks (not byte traffic).
Engine counters measure temporary read-ahead/write bytes, not physical disk I/O.
Use --work-dir on the storage under test. --prepare-command accepts an executable
storage preparation hook, run before each measured job (outside timing); record
its behavior separately. The default is warm, uncontrolled local storage.
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
    payload = ('common, \"界\"\ntext' if row % 1000 < 900 else 'minor' if row % 1000 < 990 else 'rare') if shape == 'skew' else 'duplicate payload'
    values = [str(row), payload]
    if shape != 'narrow':
        values += [str((row + col) % 10) for col in range(31)]
    if shape in ('independent', 'independent_wide'):
        values[3] = str((row // 10) % 10)
    if shape in ('rare_wide', 'independent_wide') and row == 0:
        values[1] = 'x' * 1800000
    return values


CHAIN_CASES = ['chain_probability', 'chain_parents', 'chain_downstream', 'chain_interleaved',
               'chain_last_probability', 'chain_both_probability']
STREAM_CONTROLS = ['stream_probability', 'stream_interleaved']


def probability_for(shape, last=False):
    return {'type': 'assign_probabilistic', 'groups': [
        {'name': 'treatment', 'percent': '60'}, {'name': 'control', 'percent': '40'},
        {'name': 'empty', 'percent': '0'}],
        'strata': ['payload' if shape == 'narrow' else 'c1' if last else 'c0']}


TRIPLE_CASES = ['partition_balanced', 'partition_balanced_parents', 'partition_balanced_downstream', 'partition_balanced_repeat']


CONSECUTIVE_CASES = ['consecutive', 'consecutive_parents', 'consecutive_downstream', 'consecutive_chain']


CONSTANT_CASES = ['constant_repeat', 'constant_partial', 'constant_downstream', 'constant_empty']


NESTED_CASES = ['nested', 'nested_downstream', 'nested_parents', 'nested_deep', 'shuffled_nested']


FUSION_CASES = ['shuffle_partition', 'parent_shuffle_partition', 'shuffle_partition_balanced',
                'repeated_shuffle_partition', 'shuffle_partition_assign', 'shuffle_partition_key']


def operations_for(case, shape, groups):
    shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
    if case in STREAM_CONTROLS:
        return [probability_for(shape) if case == 'stream_probability' else {'type': 'interleaved', 'files': 3}]
    if case in CHAIN_CASES:
        first = {'type': 'interleaved', 'files': 3} if case in ('chain_interleaved', 'chain_last_probability') else probability_for(shape)
        last = probability_for(shape, True) if case in ('chain_last_probability', 'chain_both_probability') else {'type': 'interleaved', 'files': 3}
        operations = [first, {'type': 'partition', 'columns': ['payload' if shape in ('narrow', 'skew') else 'c0']}, last]
        if case == 'chain_parents':
            operations.insert(0, {'type': 'balanced', 'files': groups})
        if case == 'chain_downstream':
            operations += [shuffle, {'type': 'balanced', 'files': 2}]
        return operations
    if case in TRIPLE_CASES:
        partition = {'type': 'partition', 'columns': ['payload' if shape in ('narrow', 'skew') else 'c0']}
        operations = [partition, shuffle] + ([shuffle] if case == 'partition_balanced_repeat' else []) + [{'type': 'balanced', 'files': 3}]
        if case == 'partition_balanced_parents':
            operations.insert(0, {'type': 'balanced', 'files': groups})
        if case == 'partition_balanced_downstream':
            operations += [shuffle, {'type': 'interleaved', 'files': 2}]
        return operations
    if case in CONSECUTIVE_CASES:
        first = {'type': 'partition', 'columns': ['payload' if shape == 'narrow' else 'c0']}
        second = {'type': 'partition', 'columns': ['payload' if shape == 'narrow' else 'c1']}
        operations = [first, second]
        if case == 'consecutive_chain':
            operations += [{'type': 'partition', 'columns': ['payload' if shape == 'narrow' else 'c2']}]
        if case == 'consecutive_parents':
            operations.insert(0, {'type': 'balanced', 'files': groups})
        if case == 'consecutive_downstream':
            operations += [shuffle, {'type': 'balanced', 'files': 2}]
        return operations
    if case in CONSTANT_CASES:
        column = 'payload' if shape == 'narrow' else 'c0'
        partition = {'type': 'partition', 'columns': [column]}
        if case == 'constant_partial':
            known = [f'c{i}' for i in range(31)]
            return [{'type': 'partition', 'columns': known}, {'type': 'partition', 'columns': known + ['payload']}, shuffle]
        if case == 'constant_downstream':
            return [partition, {'type': 'balanced', 'files': 2}, partition, shuffle, {'type': 'balanced', 'files': 2}]
        if case == 'constant_empty':
            return [partition, {'type': 'assign_probabilistic', 'groups': [
                {'name': 'keep', 'percent': '100'}, {'name': 'empty', 'percent': '0'}]}, partition, shuffle]
        return [partition, partition]
    if case in NESTED_CASES:
        nested = [{'type': 'balanced', 'files': 3}, {'type': 'balanced', 'files': 4}]
        if case == 'nested_deep':
            nested += [{'type': 'balanced', 'files': 2}, {'type': 'balanced', 'files': 2}]
        if case == 'shuffled_nested':
            return [shuffle, {'type': 'balanced', 'files': 1}] + nested
        return ([{'type': 'partition', 'columns': ['c0']}] if case == 'nested_parents' else []) + nested + ([shuffle] if case == 'nested_downstream' else [])
    column = 'payload' if shape == 'narrow' or case == 'shuffle_partition_key' else 'c0'
    partition = {'type': 'partition', 'columns': [column]}
    if case in FUSION_CASES:
        if case == 'parent_shuffle_partition':
            return [{'type': 'balanced', 'files': groups}, shuffle, partition]
        if case == 'shuffle_partition_balanced':
            return [shuffle, partition, {'type': 'balanced', 'files': 2}, shuffle]
        if case == 'repeated_shuffle_partition':
            return [shuffle, shuffle, partition, shuffle,
                    {'type': 'partition', 'columns': ['payload' if shape == 'narrow' else 'c1']}]
        if case == 'shuffle_partition_assign':
            return [shuffle, partition, {'type': 'assign', 'groups': [
                {'name': 'a', 'percent': '60'}, {'name': 'b', 'percent': '40'}]}, shuffle,
                {'type': 'partition', 'columns': ['payload' if shape == 'narrow' else 'c2']}]
        return [shuffle, partition]
    operations = ([{'type': 'balanced', 'files': groups}]
                  if case in ('grouped', 'grouped_balanced', 'multistage') else [])
    if case == 'skew':
        operations = [{'type': 'partition', 'columns': ['payload']}, {'type': 'balanced', 'files': 1}]
    operations += [shuffle]
    if case == 'balanced':
        operations += [{'type': 'balanced', 'files': 4}]
    if case in ('grouped_balanced', 'multistage'):
        operations += [{'type': 'balanced', 'files': 3}]
    if case == 'multistage':
        operations += [shuffle, {'type': 'balanced', 'files': 2}]
    return operations


def output_count(case, shape, groups):
    if case in STREAM_CONTROLS:
        return 3
    if case in CHAIN_CASES:
        partitions = 1 if shape == 'narrow' else 3 if shape == 'skew' else 10
        first = 3 if case in ('chain_interleaved', 'chain_last_probability') else 2
        return partitions * first * 3 * (groups if case == 'chain_parents' else 2 if case == 'chain_downstream' else 1)
    if case in TRIPLE_CASES:
        partitions = 1 if shape == 'narrow' else 3 if shape == 'skew' else 10
        return partitions * 3 * (groups if case == 'partition_balanced_parents' else 2 if case == 'partition_balanced_downstream' else 1)
    if case in CONSECUTIVE_CASES:
        partitions = 1 if shape == 'narrow' else 100 if shape in ('independent', 'independent_wide') else 10
        return partitions * (groups if case == 'consecutive_parents' else 2 if case == 'consecutive_downstream' else 1)
    if case in CONSTANT_CASES:
        parents = 1 if shape == 'narrow' else 10
        return (11 if shape == 'rare_wide' else 10) if case == 'constant_partial' else parents * (4 if case == 'constant_downstream' else 1)
    if case in NESTED_CASES:
        return 120 if case == 'nested_parents' else 48 if case == 'nested_deep' else 12
    if case in FUSION_CASES:
        if case == 'shuffle_partition_key':
            return 2 if shape == 'rare_wide' else 3 if shape == 'skew' else 1
        partitions = 1 if shape == 'narrow' else 10
        return partitions * (groups if case == 'parent_shuffle_partition' else
                             2 if case in ('shuffle_partition_balanced', 'shuffle_partition_assign') else 1)
    return {'global': 1, 'grouped': groups, 'balanced': 4,
            'grouped_balanced': groups * 3, 'multistage': groups * 6, 'skew': 3}[case]


def audit_reserved_bytes(diagnostics):
    """Validate the supported optional audit before counting its live owner."""
    if 'shuffle_partition_decisions' not in diagnostics:
        return 0
    audit = diagnostics['shuffle_partition_decisions']
    assert isinstance(audit, dict), 'malformed decision audit'
    assert type(audit.get('version')) is int and audit['version'] == 1, 'unsupported audit version'
    assert audit.get('policy') == 'experiment_gate_v1', 'unsupported audit policy'
    assert 'selector' in audit and audit['selector'] is None, 'unsupported audit selector'
    assert 'calibration' in audit and audit['calibration'] is None, 'unsupported audit calibration'
    assert audit.get('scope') == 'completed retained-parent attempts; first records, not a representative sample'
    assert audit.get('counter_scope') == 'context deltas, including failed tentative work and original-stage retry'
    assert type(audit.get('capacity')) is int and audit['capacity'] == 16
    for key in ('initialized', 'collection_denied'):
        assert type(audit.get(key)) is bool, f'malformed audit {key}'
    for key in ('reserved_bytes', 'completed_attempts', 'omitted_attempts'):
        assert type(audit.get(key)) is int and audit[key] >= 0, f'malformed audit {key}'
    records = audit.get('records')
    assert isinstance(records, list) and len(records) <= audit['capacity']
    assert audit['completed_attempts'] == len(records) + audit['omitted_attempts']
    if not audit['initialized']:
        assert not audit['collection_denied'] and audit['reserved_bytes'] == 0
        assert audit['completed_attempts'] == 0
    elif audit['collection_denied']:
        assert audit['reserved_bytes'] == 0 and not records
    else:
        assert audit['reserved_bytes'] > 0
    phases = ('admission', 'preparation', 'original_retry', 'emission')
    for record in records:
        assert isinstance(record, dict)
        for key in ('shuffle_step', 'partition_step', 'parent_ordinal', 'parent_offset', 'parent_rows'):
            assert type(record.get(key)) is int and record[key] >= 0, f'malformed audit record {key}'
        assert record.get('phase') in phases
        assert record.get('outcome') in ('terminal', 'fused_committed', 'original_committed')
        for key in ('admission_denial', 'terminal_admission_denial'):
            assert key in record and record[key] in (None, 'local', 'shared')
        assert 'admission_denial_phase' in record and record['admission_denial_phase'] in (None, *phases)
        for key in ('observation_complete', 'key_observation_complete', 'cancelled', 'cleanup_failed'):
            assert type(record.get(key)) is bool, f'malformed audit record {key}'
        shape = record.get('shape')
        assert isinstance(shape, dict)
        for key in ('rows_decoded', 'rows_keyed', 'decoded_payload_bytes', 'maximum_payload_bytes',
                    'maximum_fields', 'maximum_row_heap_capacity_bytes',
                    'maximum_key_heap_capacity_bytes', 'maximum_key_bytes'):
            assert type(shape.get(key)) is int and shape[key] >= 0, f'malformed audit shape {key}'
        assert type(shape.get('totals_saturated')) is bool
        assert record['observation_complete'] == (shape['rows_decoded'] == record['parent_rows'])
        assert record['key_observation_complete'] == (shape['rows_keyed'] == record['parent_rows'])
        delta = record.get('context_counter_delta')
        assert isinstance(delta, dict)
        for key in ('sort_runs', 'resident_sorts', 'merge_operations',
                    'temporary_bytes_read', 'temporary_bytes_written'):
            assert type(delta.get(key)) is int and delta[key] >= 0
    return audit['reserved_bytes']


def verify_workspace_owners(analysis):
    diagnostics = analysis['diagnostics']
    audit_bytes = audit_reserved_bytes(diagnostics)
    assert diagnostics['peak_workspace_reserved_bytes'] <= analysis['memory_budget_bytes'] // 2
    assert diagnostics['workspace_reserved_bytes'] == (
        diagnostics.get('temporary_path_reserved_bytes', 0)
        + diagnostics.get('input_header_reserved_bytes', 0) + audit_bytes)


def verify(output, analysis, shape, rows, case, groups=4):
    seen = bytearray(rows)
    fingerprint = hashlib.sha256()
    fingerprint.update(json.dumps(analysis['stages'], sort_keys=True).encode())
    fingerprint.update(analysis['logical_digest'].encode())
    count = 0
    header = ['id', 'payload'] + ([] if shape == 'narrow' else [f'c{i}' for i in range(31)])
    operations = operations_for(case, shape, groups)
    scope_positions = {}
    for line in (output / 'manifest.jsonl').read_text().splitlines():
        entry = json.loads(line)
        if entry['type'] != 'output':
            continue
        path = output / entry['path']
        assert path.stat().st_size == entry['csv_bytes']
        fingerprint.update(json.dumps({key: entry[key] for key in
                                      ['path', 'rows', 'csv_bytes', 'lineage']}, sort_keys=True).encode())
        fingerprint.update(path.read_bytes())
        members = 0
        skew_payload = None
        previous_id = -1
        nested_start, nested_length = 0, rows
        if case in NESTED_CASES and case not in ('nested_parents', 'shuffled_nested'):
            for logical, lineage in zip(operations, entry['lineage']):
                if logical['type'] == 'balanced':
                    parts, part = logical['files'], lineage['part'] - 1
                    nested_start += part * (nested_length // parts) + min(part, nested_length % parts)
                    nested_length = nested_length // parts + int(part < nested_length % parts)
        with path.open(newline='') as source:
            records = csv.reader(source)
            assert next(records) == header
            for record in records:
                row = int(record[0])
                assert 0 <= row < rows and not seen[row]
                assert record == fields(row, shape)
                if case in CHAIN_CASES or case in STREAM_CONTROLS:
                    if case != 'chain_downstream':
                        assert row > previous_id, 'routing encounter order changed'
                        previous_id = row
                    for step in entry['lineage']:
                        logical = operations[step['operation']]
                        if 'values' in step:
                            assert step['values'] == [record[header.index(c)] for c in logical['columns']]
                    if case == 'chain_parents':
                        parent = entry['lineage'][0]['part'] - 1
                        start = parent * (rows // groups) + min(parent, rows % groups)
                        assert start <= row < start + rows // groups + int(parent < rows % groups)
                    if case in ('chain_interleaved', 'chain_last_probability', 'stream_interleaved'):
                        assert entry['lineage'][0]['part'] - 1 == row % 3
                    if case in CHAIN_CASES:
                        step = 3 if case == 'chain_parents' else 2
                        if operations[step]['type'] == 'interleaved':
                            scope = json.dumps([s for s in entry['lineage'] if s['operation'] < step], sort_keys=True)
                            part = next(s['part'] for s in entry['lineage'] if s['operation'] == step)
                            scope_positions.setdefault(scope, []).append((row, part))
                if case in NESTED_CASES:
                    if case not in ('nested_parents', 'shuffled_nested'):
                        assert nested_start <= row < nested_start + nested_length, 'nested range membership changed'
                    for step in entry['lineage']:
                        if 'values' in step:
                            assert step['values'] == [record[header.index('c0')]]
                if case in CONSECUTIVE_CASES and case != 'consecutive_downstream':
                    assert row > previous_id, 'partition encounter order changed'
                    previous_id = row
                if case == 'consecutive_parents':
                    parent = entry['lineage'][0]['part'] - 1
                    start = parent * (rows // groups) + min(parent, rows % groups)
                    assert start <= row < start + rows // groups + int(parent < rows % groups)
                if case in CONSTANT_CASES or case in CONSECUTIVE_CASES:
                    for step in entry['lineage']:
                        if 'values' in step:
                            logical = operations[step['operation']]
                            assert step['values'] == [record[header.index(c)] for c in logical['columns']]
                if case in FUSION_CASES or case in TRIPLE_CASES:
                    for step in entry['lineage']:
                        if 'values' in step:
                            logical = operations[step['operation']]
                            assert logical['type'] == 'partition'
                            assert step['values'] == [record[header.index(c)] for c in logical['columns']]
                    if case in ('parent_shuffle_partition', 'partition_balanced_parents'):
                        parent = entry['lineage'][0]['part'] - 1
                        start = parent * (rows // groups) + min(parent, rows % groups)
                        assert start <= row < start + rows // groups + int(parent < rows % groups)
                if case == 'skew':
                    if skew_payload is None:
                        skew_payload = record[1]
                    assert record[1] == skew_payload, 'partition isolation changed'
                if case in ('grouped', 'grouped_balanced', 'multistage'):
                    parent = count // {'grouped': 1, 'grouped_balanced': 3, 'multistage': 6}[case]
                    start = parent * (rows // groups) + min(parent, rows % groups)
                    end = start + rows // groups + int(parent < rows % groups)
                    assert start <= row < end
                seen[row] = 1
                members += 1
        assert members == entry['rows']
        count += 1
    for positions in scope_positions.values():
        for encounter, (_, part) in enumerate(sorted(positions)):
            assert part == encounter % 3 + 1, 'logical-parent interleaved counter changed'
    assert all(seen) and analysis['rows'] == rows
    verify_workspace_owners(analysis)
    assert count == output_count(case, shape, groups)
    return fingerprint.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--baseline-allocator', type=Path)
    parser.add_argument('--candidate-allocator', type=Path)
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--groups', type=int, default=4)
    parser.add_argument('--memory-mb', type=int, default=32)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--shapes', nargs='+', choices=['narrow', 'columns', 'rare_wide', 'skew', 'independent', 'independent_wide'], default=['narrow', 'columns', 'rare_wide'])
    parser.add_argument('--cases', nargs='+', choices=['global', 'grouped', 'balanced', 'grouped_balanced', 'multistage', 'skew'] + FUSION_CASES + NESTED_CASES + CONSTANT_CASES + CONSECUTIVE_CASES + TRIPLE_CASES + CHAIN_CASES + STREAM_CONTROLS, default=['global', 'grouped', 'balanced'])
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--storage-label', default='warm, uncontrolled local storage')
    parser.add_argument('--prepare-command', nargs='+')
    args = parser.parse_args()
    if min(args.rows, args.memory_mb, args.repeats, args.groups, *args.workers) < 1 or args.rows < max(4, args.groups * (6 if 'multistage' in args.cases else 3 if 'grouped_balanced' in args.cases else 1)):
        parser.error('need at least four rows and positive memory/workers/repeats')
    if any(s in ('independent', 'independent_wide') for s in args.shapes) and not all(c in CONSECUTIVE_CASES for c in args.cases):
        parser.error('independent shapes require consecutive partition cases')
    if 'constant_partial' in args.cases and 'narrow' in args.shapes:
        parser.error('constant_partial requires column fixtures')
    if ('skew' in args.cases) and (args.shapes != ['skew'] or args.rows < 1000):
        parser.error('skew case requires --shapes skew and at least 1000 rows')
    if any(case in CHAIN_CASES for case in args.cases) and args.rows < 4000:
        parser.error('routing-chain matrix requires at least 4000 rows for all nonempty parents')
    if any(case in FUSION_CASES for case in args.cases) and args.rows < 1000:
        parser.error('fusion matrix requires at least 1000 rows for all partition/allocation children')
    if bool(args.baseline_allocator) != bool(args.candidate_allocator):
        parser.error('provide both allocation-profile builds')
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required')
    csv.field_size_limit(2097152)

    def emit(record):
        print(json.dumps(record), flush=True)

    binaries = {'baseline': args.baseline, 'candidate': args.candidate}
    allocators = {'baseline': args.baseline_allocator, 'candidate': args.candidate_allocator}
    emit({'type': 'environment', 'platform': platform.platform(),
          'cpu': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                       if line.startswith('model name')), 'unknown'),
          'rows': args.rows, 'memory_mb': args.memory_mb, 'workers': args.workers, 'groups': args.groups,
          'repeats': args.repeats, 'storage': args.storage_label, 'prepare_command': args.prepare_command,
          'seed': 'external-comparison-v1', 'binary_sha256': {
              key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in
              list(binaries.items()) + [(key + '_allocator', path) for key, path in allocators.items()] if path}})
    with tempfile.TemporaryDirectory(prefix='chopper-external-', dir=args.work_dir) as directory:
        root = Path(directory)
        for shape in args.shapes:
            source = root / 'input.csv'
            with source.open('w', newline='') as output:
                writer = csv.writer(output, lineterminator='\n')
                writer.writerow(['id', 'payload'] + ([] if shape == 'narrow' else [f'c{i}' for i in range(31)]))
                for row in range(args.rows):
                    writer.writerow(fields(row, shape))
            for case in args.cases:
                reference = None
                for workers in args.workers:
                    operations = operations_for(case, shape, args.groups)
                    config = root / 'job.json'
                    config.write_text(json.dumps({'input': str(source), 'output': str(root / 'output'),
                                                  'seed': 'external-comparison-v1', 'operations': operations,
                                                  'resources': {'memory_mb': args.memory_mb, 'workers': workers,
                                                                'max_record_bytes': 2097152, 'temp_dir': str(root)}}))
                    samples = {key: [] for key in binaries}
                    for repeat in range(args.repeats + int(args.baseline_allocator is not None)):
                        allocation = repeat == args.repeats
                        variants = list(binaries)
                        if repeat % 2:
                            variants.reverse()
                        for variant in variants:
                            if args.prepare_command:
                                subprocess.run(args.prepare_command, check=True, timeout=600)
                            binary = allocators[variant] if allocation else binaries[variant]
                            command = [str(binary.resolve())] + ([str(config)] if allocation else ['run', '--config', str(config), '--yes'])
                            stats = root / 'time.txt'
                            started = time.perf_counter()
                            result = subprocess.run([timer, '-f', '%U %S %M %I %O', '-o', str(stats)] + command,
                                                    capture_output=True, text=True, timeout=1800)
                            elapsed = time.perf_counter() - started
                            if result.returncode:
                                raise RuntimeError(f'{shape}/{case}/{variant}: {result.stderr}')
                            payload = json.loads(result.stdout)
                            analysis = payload['analysis'] if allocation else payload
                            actual = verify(root / 'output', analysis, shape, args.rows, case, args.groups)
                            shutil.rmtree(root / 'output')
                            if reference is not None:
                                assert actual == reference, 'v1 output/metadata/worker parity changed'
                            reference = actual
                            user, system, rss, reads, writes = map(float, stats.read_text().split())
                            record = {'type': 'allocation' if allocation else 'measurement', 'shape': shape,
                                      'case': case, 'workers': workers, 'variant': variant, 'repeat': repeat + 1,
                                      'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': int(rss),
                                      'filesystem_input_blocks': int(reads), 'filesystem_output_blocks': int(writes),
                                      'diagnostics': analysis['diagnostics'], 'timings': analysis['timings'],
                                      'peak_temp_bytes': analysis['peak_temp_bytes'], 'fingerprint': actual, 'verified': True}
                            if allocation:
                                record['allocation_profile'] = payload['allocation_profile']
                            else:
                                samples[variant].append(elapsed)
                            emit(record)
                    medians = {key: statistics.median(values) for key, values in samples.items()}
                    emit({'type': 'summary', 'shape': shape, 'case': case, 'workers': workers,
                          'median_seconds': medians, 'candidate_over_baseline': medians['candidate'] / medians['baseline'],
                          'range_seconds': {key: [min(values), max(values)] for key, values in samples.items()}, 'verified': True})


if __name__ == '__main__':
    main()
