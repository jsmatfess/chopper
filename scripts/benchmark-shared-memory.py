"""Complete native jobs/profiles under process-wide admission ceilings.

Compares successful constrained jobs with an unconstrained copied baseline,
checks exact profiles/output/metadata, and verifies failure cleanup and absence
of publication. These configured ledger ceilings are not OS/RSS pressure tests.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--groups', type=int, default=0, help='positive: split into independent groups before shuffling')
    parser.add_argument('--memory-mb', type=int, default=256)
    parser.add_argument('--shuffle-partition', action='store_true', help='partition after uniform shuffle before the terminal balanced stage')
    parser.add_argument('--partition-balanced', action='store_true', help='partition before uniform shuffle and balanced emission')
    parser.add_argument('--streaming-chain', action='store_true', help='probabilistic/partition/interleaved chain before downstream shuffle/balanced')
    args = parser.parse_args()
    if sum([args.shuffle_partition, args.partition_balanced, args.streaming_chain]) > 1:
        parser.error('choose only one fusion pipeline')
    if args.rows < max(1000, args.groups * 4) or args.groups < 0 or args.memory_mb < 32:
        parser.error('need rows >= max(1000, groups * 4), groups >= 0, memory >= 32 MiB')
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    env = os.environ.copy()
    env.pop('CHOPPER_MEMORY_LIMIT_MB', None)
    def emit(value):
        print(json.dumps(value), flush=True)
    emit({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows, 'groups': args.groups, 'memory_mb': args.memory_mb, 'shuffle_partition': args.shuffle_partition, 'partition_balanced': args.partition_balanced, 'streaming_chain': args.streaming_chain,
          'cache': 'warm uncontrolled WSL filesystem; configured capacity pressure, not cgroup/RSS pressure',
          'binary_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in [('before', args.before), ('after', args.after)]}})
    with tempfile.TemporaryDirectory(prefix='chopper-shared-boundaries-') as directory:
        root = Path(directory)
        for shape in ['many', 'wide']:
            source = root / 'input.csv'
            with source.open('w') as output:
                output.write('id,' + ','.join(f'c{i}' for i in range(32)) + '\n')
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + c) % 10) for c in range(32)]
                    if shape == 'wide' and row == args.rows - 2:
                        fields[1] = '界' * 600000
                    output.write(','.join(fields) + '\n')
            for workers in [1, 4]:
                temp = root / 'temp'
                temp.mkdir()
                destination = root / 'output'
                operations = ([{'type': 'balanced', 'files': args.groups}] if args.groups else []) + [{'type': 'shuffle', 'strategy': 'uniform'}]
                if args.streaming_chain:
                    operations[-1:-1] = [
                        {'type': 'assign_probabilistic', 'groups': [
                            {'name': 'treatment', 'percent': '60'}, {'name': 'control', 'percent': '40'},
                            {'name': 'empty', 'percent': '0'}], 'strata': ['c1']},
                        {'type': 'partition', 'columns': ['c2']}, {'type': 'interleaved', 'files': 3}]
                if args.partition_balanced:
                    operations.insert(-1, {'type': 'partition', 'columns': ['c2']})
                if args.shuffle_partition:
                    operations.append({'type': 'partition', 'columns': ['c2']})
                operations.append({'type': 'balanced', 'files': 4})
                job = {'input': str(source), 'output': str(destination), 'seed': 'shared-admission-v1',
                       'operations': operations,
                       'resources': {'memory_mb': args.memory_mb, 'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(temp)}}
                config = root / 'job.json'
                config.write_text(json.dumps(job))
                references = {}
                for command in ['profile', 'run']:
                    for cap in [None, 1, 4, 8, 16, 64]:
                        binary = args.before if cap is None else args.after
                        run_env = env.copy()
                        if cap is not None:
                            run_env['CHOPPER_MEMORY_LIMIT_MB'] = str(cap)
                        started = time.perf_counter()
                        result = subprocess.run([str(binary.resolve()), command, '--config', str(config)] + (['--yes'] if command == 'run' else []),
                                                capture_output=True, text=True, timeout=300, env=run_env)
                        elapsed = time.perf_counter() - started
                        assert not list(temp.iterdir()), (shape, workers, command, cap, 'leaked temporary files')
                        if result.returncode:
                            assert cap is not None and 'memory' in result.stderr.lower(), result.stderr
                            assert not destination.exists(), 'failed preparation published output'
                            emit({'type': 'boundary', 'shape': shape, 'workers': workers, 'command': command,
                                  'process_limit_mib': cap, 'outcome': 'bounded failure', 'seconds': elapsed,
                                  'error': result.stderr.strip(), 'verified_cleanup': True, 'verified_no_publication': True})
                            continue
                        data = json.loads(result.stdout)
                        if command == 'run':
                            actual = pipelines.fingerprint(destination, data, 'none')
                            if cap is None:
                                # Independent baseline conservation and values;
                                # later successful jobs must match exact bytes.
                                csv.field_size_limit(4 * 1024 * 1024)
                                seen = bytearray(args.rows)
                                entries = {entry['path']: entry for entry in
                                           map(json.loads, (destination / 'manifest.jsonl').read_text().splitlines())
                                           if entry['type'] == 'output'}
                                assert len(entries) == max(1, args.groups) * 4 * (60 if args.streaming_chain else 10 if args.shuffle_partition or args.partition_balanced else 1)
                                for output in destination.glob('*.csv'):
                                    with output.open(newline='') as stream:
                                        records = csv.reader(stream)
                                        assert next(records) == ['id'] + [f'c{i}' for i in range(32)]
                                        for record in records:
                                            assert len(record) == 33
                                            index = int(record[0])
                                            assert 0 <= index < args.rows and record[0] == str(index) and not seen[index]
                                            seen[index] = 1
                                            expected = [str(index)] + [str((index + c) % 10) for c in range(32)]
                                            if shape == 'wide' and index == args.rows - 2:
                                                expected[1] = '界' * 600000
                                            assert record == expected
                                            if args.shuffle_partition or args.partition_balanced or args.streaming_chain:
                                                entry = entries[output.relative_to(destination).as_posix()]
                                                partition = next(step for step in entry['lineage'] if 'values' in step)
                                                assert partition['values'] == [record[3]], 'partition membership changed'
                                            if args.groups:
                                                entry = entries[output.relative_to(destination).as_posix()]
                                                part = next(step['part'] for step in entry['lineage'] if step['operation'] == 0) - 1
                                                start = part * (args.rows // args.groups) + min(part, args.rows % args.groups)
                                                end = start + args.rows // args.groups + int(part < args.rows % args.groups)
                                                assert start <= index < end, 'parent group isolation changed'
                                assert all(seen)
                            shutil.rmtree(destination)
                            process = data.get('diagnostics', {}).get('process_memory')
                            if cap is not None:
                                assert process['limit_bytes'] <= cap * 1024 * 1024
                                assert process['peak_reserved_bytes'] <= process['limit_bytes']
                        else:
                            actual = {k: v for k, v in data.items() if k not in ['seconds', 'cache_hit']}
                            process = None
                        if cap is None:
                            references[command] = actual
                        else:
                            assert actual == references[command], (shape, workers, command, cap, 'parity')
                        emit({'type': 'boundary', 'shape': shape, 'workers': workers, 'command': command,
                              'process_limit_mib': cap, 'outcome': 'success', 'seconds': elapsed,
                              'process_memory': process, 'verified': True, 'verified_cleanup': True,
                              'peak_rss_note': 'not collected; ledger capacity is not RSS',
                              'diagnostics': data.get('diagnostics')})
                temp.rmdir()
        # Environment configuration is parsed once at process startup. Invalid
        # ceilings must fail before input processing and leave no job directory.
        for value in ['0', '-1', 'x', '18446744073709551615']:
            invalid = env.copy()
            invalid['CHOPPER_MEMORY_LIMIT_MB'] = value
            result = subprocess.run([str(args.after.resolve()), 'run', '--config', str(config), '--yes'], capture_output=True, text=True, timeout=30, env=invalid)
            assert result.returncode and 'CHOPPER_MEMORY_LIMIT_MB' in result.stderr
            assert not destination.exists() and not temp.exists()
            emit({'type': 'invalid_configuration', 'value': value, 'verified': True})


if __name__ == '__main__':
    main()
