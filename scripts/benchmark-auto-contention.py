#!/usr/bin/env python3
"""Matched native CLI resource tests. Timings include publication and job cleanup."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import os
import runpy
import shutil
import signal
import subprocess
from threading import Barrier
import time

MIB = 2**20
CAP = 4 * MIB
HEADER = b'id,key,payload\n'


def emit(record):
    print(json.dumps(record), flush=True)


def fixture(root, rows, width, groups):
    path = root / f'fixture-{rows}-{width}-{groups}.csv'
    digest = hashlib.sha256(HEADER)
    with path.open('xb') as file:
        file.write(HEADER)
        suffix = b'x' * (width - 15) + b'\n'
        rows_per_block = min(4096, max(1, 2 * MIB // width))
        for start in range(0, rows, rows_per_block):
            block = b''.join(
                f'{row:08},{row % groups:04},'.encode() + suffix
                for row in range(start, min(rows, start + rows_per_block)))
            file.write(block)
            digest.update(block)
    assert path.stat().st_size == rows * width + len(HEADER)
    emit({'type': 'fixture', 'rows': rows, 'row_bytes': width, 'groups': groups,
          'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    return path


def verify(output, rows, width, groups, partition, ordered=False, cap=CAP, balanced_parts=0, interleaved=0, shuffled=False, chain=None, quota_groups=0, exact_strata=False, output_encoding="utf-8", approximate=False):
    csv.field_size_limit(max(csv.field_size_limit(), width))
    manifest = (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()
    assert json.loads(manifest[0])['analysis']['rows'] == rows
    seen = bytearray(rows)
    payload = 'x' * (width - 15)
    group_last = {}
    chain_membership = bytearray(rows) if chain else None
    count = 0
    files = 0
    nonidentity = False
    for line in manifest[1:]:
        entry = json.loads(line)
        if entry['type'] != 'output':
            continue
        files += 1
        path = output / entry['path']
        opener = gzip.open if path.suffix == '.gz' else open
        assert cap is None or entry['csv_bytes'] <= cap
        if path.suffix == '.csv':
            assert path.stat().st_size == entry['csv_bytes']
        group = int(entry['lineage'][0]['values'][0]) if partition else None
        if balanced_parts:
            part = entry['lineage'][int(partition)]['part'] - 1
            group_rows = (rows + groups - 1 - group) // groups if partition else rows
            base, remainder = divmod(group_rows, balanced_parts)
            assert 0 <= part < balanced_parts
            assert entry['rows'] == base + (part < remainder)
            first = part * base + min(part, remainder)
        if interleaved:
            lane = entry['lineage'][0]['part'] - 1
            assert 0 <= lane < interleaved
            assert entry['rows'] == (rows + interleaved - 1 - lane) // interleaved
        if chain:
            reverse = chain == 'reverse'
            lane = entry['lineage'][int(reverse)]['part'] - 1
            allocation = {'a': 0, 'b': 1}[entry['lineage'][int(not reverse)]['allocation']]
            assert 0 <= lane < 4
            leaf = allocation * 4 + lane + 1
        if quota_groups:
            quota = int(entry['lineage'][0]['allocation'])
            assert 0 <= quota < quota_groups
            if exact_strata or approximate:
                counts_by_key = [0] * groups
            else:
                assert entry['rows'] == rows // quota_groups + (quota < rows % quota_groups)
        with opener(path, 'rt', encoding=output_encoding, newline='') as stream:
            reader = csv.reader(stream)
            heading = next(reader)
            heading[0] = heading[0].lstrip(chr(0xfeff))
            assert heading == ['id', 'key', 'payload']
            actual = 0
            for identifier, key_field, field in reader:
                row, key = int(identifier), int(key_field)
                assert 0 <= row < rows and not seen[row] and key == row % groups and field == payload
                if balanced_parts and not shuffled:
                    index = first + actual
                    assert row == (index * groups + group if partition else index)
                if interleaved:
                    assert row == lane + actual * interleaved
                nonidentity |= shuffled and row != count + actual
                if group is not None:
                    assert key == group
                    if ordered:
                        assert group_last.get(group, -1) < row
                        group_last[group] = row
                if exact_strata or approximate:
                    counts_by_key[key] += 1
                if chain or quota_groups:
                    order_key = leaf if chain else quota
                    assert group_last.get(order_key, -1) < row
                    group_last[order_key] = row
                if chain:
                    chain_membership[row] = leaf
                    if not reverse:
                        assert row % 4 == lane
                seen[row] = 1
                actual += 1
        assert actual == entry['rows']
        if exact_strata or approximate:
            for key, actual_in_stratum in enumerate(counts_by_key):
                rows_in_stratum = (rows + groups - 1 - key) // groups
                base, remainder = divmod(rows_in_stratum, quota_groups)
                if approximate:
                    assert abs(actual_in_stratum - base) <= base * 0.03
                else:
                    assert actual_in_stratum == base + (quota < remainder)
        count += actual
    assert count == rows and all(seen)
    assert not shuffled or nonidentity
    assert not interleaved or files == interleaved
    if chain:
        assert files == 8
        if chain == 'reverse':
            rank = [0, 0]
            for leaf in chain_membership:
                member, lane = divmod(leaf - 1, 4)
                assert rank[member] % 4 == lane
                rank[member] += 1
            assert all(abs(value * 2 - rows) <= rows * 0.02 for value in rank)
        else:
            for lane in range(4):
                leaves = chain_membership[lane::4]
                assert abs(leaves.count(lane + 1) * 2 - len(leaves)) <= len(leaves) * 0.03
    if quota_groups:
        assert files == quota_groups


def run_case(directory, binary, source, shape, request, timers, barrier):
    operations, compression, rows, width, groups, partition = shape
    directory.mkdir()
    tmp = directory / 'tmp'
    tmp.mkdir()
    output = directory / 'out'
    config = {'input': str(source), 'output': str(output), 'operations': operations,
              'compression': compression, 'limits': {'bytes': request.get('cap', CAP)},
              **({'output_csv':{'encoding':request['output_encoding']}} if 'output_encoding' in request else {}),
              'resources': {'memory_mb': request.get('memory_mb', 'auto'),
                            'workers': request.get('workers', 0),
                            'grouping': request.get('grouping', 'auto'),
                            'max_files': request.get('max_files', 4096),
                            **({'max_record_bytes': request['max_record_bytes']} if 'max_record_bytes' in request else {}),
                            'temp_dir': str(tmp)}}
    path = directory / 'job.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    command = [str(binary), 'run', '--config', str(path), '--yes']
    windows = platform.system() == 'Windows'
    if barrier:
        barrier.wait(timeout=20)
    start = time.perf_counter()
    analyze_seconds = None
    if request.get('analyze'):
        report = directory / 'profile.json'
        with report.open('wb') as out, (directory / 'profile.log').open('wb') as err:
            subprocess.run([str(binary), 'analyze', '--config', str(path)], stdout=out,
                           stderr=err, check=True, timeout=180)
        command += ['--analysis', str(report)]
        analyze_seconds = time.perf_counter() - start
    if not windows:
        command = ['/usr/bin/time', '-f', '%U %S %M', '-o', str(directory / 'process.time'), *command]
    environment = os.environ.copy()
    if request.get('digest_mode'):
        environment['CHOPPER_EXPERIMENT_DIGEST'] = request['digest_mode']
    run_start = time.perf_counter()
    with (directory / 'stdout.json').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
        with subprocess.Popen(command, stdout=out, stderr=err, start_new_session=not windows, env=environment) as process:
            try:
                status = process.wait(timeout=360)
            except subprocess.TimeoutExpired:
                if windows:
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
            end = time.perf_counter()
            system = timers['counters'](process) if windows else {}
    if not windows:
        user, sys, rss = (directory / 'process.time').read_text().splitlines()[-1].split()
        system = {'cpu_seconds': float(user) + float(sys), 'peak_rss_bytes': int(rss) * 1024}
    record = {'exit': status, 'elapsed_seconds': end - run_start,
              'analyze_seconds': analyze_seconds, 'request': request, **system}
    stderr = (directory / 'stderr.log').read_text(encoding='utf-8', errors='replace')
    digest_cpu = re.findall(r'^digest_profile_cpu_ns=(\d+)$', stderr, re.MULTILINE)
    if digest_cpu:
        record['digest_hash_cpu_seconds'] = sum(map(int, digest_cpu)) / 1e9
    if status == 0:
        result = json.loads((directory / 'stdout.json').read_text(encoding='utf-8'))
        fields = ['sort_runs', 'merge_operations', 'merge_inputs', 'peak_workspace_reserved_bytes',
                  'temporary_bytes_read', 'temporary_bytes_written', 'peak_temporary_files']
        record.update(memory_budget_bytes=result['memory_budget_bytes'], workers=result['workers'],
                      logical_digest=result['logical_digest'], output_files=result['output_files'],
                      output_csv_bytes=result['output_csv_bytes'],
                      auto_plan=result['auto_plan'],
                      diagnostics={key: result['diagnostics'][key] for key in fields})
    return record, start, end, output, tmp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('panel', choices=[
        'workers', 'writers', 'writer-low', 'quick',
        'bounded-partition', 'bounded-partition-control',
        'bounded-interleaved', 'bounded-probabilistic', 'wide-utf16',
        'chain-forward', 'chain-reverse', 'retained-exact',
        'counted-partition', 'counted-balanced', 'counted-zstd',
        'final-sync', 'final-sync-control', 'final-sync-ceiling',
        'merge', 'merge-dense', 'merge-small', 'terminal-wide', 'terminal-short',
        'quota-index', 'quota-index-heavy', 'quota-index-wide', 'quota-control',
        'publication', 'publication-coarse', 'publication-competing',
        'digest', 'digest-narrow', 'digest-wide', 'digest-very-wide',
    ])
    parser.add_argument('root', type=Path)
    parser.add_argument('default', type=Path)
    parser.add_argument('--writers-binary', type=Path)
    parser.add_argument('--existing-source', type=Path, help='Reuse a fixture generated by this driver')
    parser.add_argument('--overlap-digest', action='store_true', help='Compare same-size serial and background digest buffers')
    parser.add_argument('--rounds', type=int, choices=[1, 2], default=2)
    parser.add_argument('--integrated', action='store_true', help='Verify routes in a feature-free Auto build')
    parser.add_argument('--planned', action='store_true', help='Compare integrated Auto with and without Analyze on merge panels')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True)
    binary = args.default.resolve()
    writers = args.writers_binary.resolve() if args.writers_binary else None
    support = runpy.run_path(str(Path(__file__).with_name('benchmark-windows.py')))
    sources = support['source_inventory']()
    native_compiler = subprocess.check_output(['rustc', '-Vv'], text=True)
    emit({'type': 'environment', 'panel': args.panel, 'platform': platform.platform(),
          'cpu': platform.processor(), 'compiler': native_compiler,
          'available_cpu_count': getattr(os, 'process_cpu_count', os.cpu_count)(),
          'affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
          'execution_checkout_sources_digest': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
          'harness_sha256': support['sha'](__file__),
          'binaries': {str(path): support['sha'](path) for path in [binary, writers] if path},
          'clock': 'CLI including publication and workspace cleanup, excluding independent verification'})
    shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
    partition = {'type': 'partition', 'columns': [1]}
    if args.panel.startswith('merge'):
        assert shutil.disk_usage(root).free >= 25 * 2**30
        rows, row_bytes, tiers = {
            'merge': (4_200_000, 1024, [256, 384, 512]),
            'merge-dense': (7_700_000, 512, [256, 384]),
            'merge-small': (2_100_000, 1024, [256, 384]),
        }[args.panel]
        shape = ([shuffle], 'none', rows, row_bytes, 8, False)
        variants = [(str(tier), binary, {'memory_mb': tier, 'workers': 1}) for tier in tiers]
        competitors = [1]
    elif args.panel.startswith('publication'):
        assert writers and writers.is_file()
        shape = ([partition], 'none', 4_200_000, 512, 192, True)
        cap = (16 if args.panel == 'publication-coarse' else 2) * MIB
        variants = [('serial', binary, {'memory_mb': 256, 'workers': 4, 'cap': cap}),
                    ('parallel', writers, {'memory_mb': 256, 'workers': 4, 'cap': cap})]
        competitors = [2] if args.panel == 'publication-competing' else [1]
    elif args.panel.startswith('digest'):
        assert writers and writers.is_file()
        rows, row_bytes = {'digest': (4_200_000, 512), 'digest-narrow': (4_200_000, 256),
                           'digest-wide': (524_288, 4096), 'digest-very-wide': (2048, 512 * 1024)}[args.panel]
        shape = ([{'type': 'balanced', 'files': 8}], 'none', rows, row_bytes, 8, False)
        resources = {'memory_mb': 256, 'workers': 4, 'cap': 300 * MIB}
        variants = [('serial', binary, resources)]
        if args.overlap_digest:
            variants.extend([('serial-buffer', writers, {**resources, 'digest_mode': 'serial-buffer'}),
                             ('overlap', writers, {**resources, 'digest_mode': 'overlap'})])
        else:
            variants.append(('challenger', writers, resources))
        competitors = [1]
    elif args.panel.startswith('bounded-partition'):
        assert writers and writers.is_file()
        control = args.panel.endswith('-control')
        shape = ([partition], 'none', 600_000 if control else 4_200_000, 512, 8, True)
        windows = platform.system() == 'Windows'
        request = {'memory_mb': 256, 'workers': 1, 'max_files': 16 if windows else 32,
                   'max_record_bytes': 128 * 1024, 'cap': (300 if windows else 96) * MIB}
        variants = [('baseline', binary, request), ('bounded', writers, request)]
        competitors = [1] if control else [2]
    elif args.panel.startswith('counted-'):
        parts = 8
        partitioned = args.panel == 'counted-partition'
        operations = ([partition] if partitioned else []) + [{'type': 'balanced', 'files': parts}]
        shape = (operations, 'none', 4_200_000, 512, 8, partitioned)
        if partitioned and platform.system() == 'Windows':
            parts = 2
            operations[-1]['files'] = parts
        request = {'memory_mb': 256, 'workers': 1, 'max_files': (8 * parts if partitioned else 64),
                   'max_record_bytes': 128 * 1024, 'cap': ((40 if parts == 8 else 150) if partitioned else 300) * MIB}
        variants = [('baseline', binary, request), ('counted', writers, request)]
        competitors = [1]
    elif args.panel.startswith('final-sync'):
        assert platform.system() == 'Linux'
        files = {'final-sync-control':1024, 'final-sync-ceiling':16384}.get(args.panel,8192)
        shape = ([{'type': 'interleaved', 'files': files}], 'none', 4_200_000, 512, 8, False)
        request = {'memory_mb': 1024, 'workers': 1, 'max_files': files,
                   'max_record_bytes': 4 * 1024, 'cap': None}
        variants = [('serial-sync', binary, request), ('batched-sync', writers, request)]
        competitors = [1]
    elif args.panel in ('wide-utf16','bounded-interleaved'):
        wide = args.panel == 'wide-utf16'
        shape = ([{'type':'interleaved','files':16}],'none',
                 2048 if wide else 4_200_000, 768*1024 if wide else 512,8,False)
        request = {'memory_mb':256,'workers':1,'max_files':16,
                   'max_record_bytes':(1024 if wide else 128)*1024,
                   'cap':None, **({'output_encoding':'utf-16le'} if wide else {})}
        variants = [('baseline',binary,request),('bounded',writers,request)]
        competitors = [1]
    elif args.panel == 'bounded-probabilistic':
        guess = {'type':'assign_probabilistic','strata':[1],
                 'groups':[{'name':str(i),'percent':'12.5'} for i in range(8)]}
        shape = ([guess],'none',4_200_000,512,8,False)
        request = {'memory_mb':256,'workers':1,'max_files':16,'max_record_bytes':128*1024,'cap':None}
        variants = [('baseline',binary,request),('bounded',writers,request)]
        competitors = [1]
    elif args.panel.startswith('chain-'):
        interleaved = {'type':'interleaved','files':4}
        probability = {'type':'assign_probabilistic','strata':[1],
                       'groups':[{'name':name,'percent':'50'} for name in ('a','b')]}
        operations = [interleaved,probability] if args.panel == 'chain-forward' else [probability,interleaved]
        shape = (operations, 'none', 4_200_000, 512, 8, False)
        request = {'memory_mb':256,'workers':1,'max_files':16,'max_record_bytes':128*1024,'cap':300*MIB}
        variants = [('baseline',binary,request),('composed',writers,request)]
        competitors = [1]
    elif args.panel.startswith('terminal-'):
        shape = ([shuffle,{'type':'balanced','files':8}], 'none', 16_777_216, 512, 8, False)
        request = {'memory_mb':96 if args.panel == 'terminal-short' else 256,
                   'workers':1,'max_files':8,'max_record_bytes': 128*1024, 'cap':1200*MIB}
        variants = [('baseline',binary,request),('terminal',writers,request)]
        competitors = [1]
    elif args.panel.startswith('quota-') or args.panel == 'retained-exact':
        destinations = 8 if args.panel == 'retained-exact' else {'quota-control':128, 'quota-index-wide':1024}.get(args.panel,1000)
        units, left = divmod(100_000_000, destinations)
        assignment = {'type':'assign','groups':[{'name':str(i),'percent':f'{(units+(i<left))/1_000_000:.6f}'}
                                                for i in range(destinations)]}
        if args.panel == 'retained-exact':
            assignment['strata'] = [1]
            shape = ([assignment],'none',4_200_000,512,8,False)
            request = {'memory_mb':256,'workers':1,'max_files':8,'cap':300*MIB}
            variants = [('baseline',binary,request),('retained',writers,request)]
        else:
            shape = ([assignment],'none',4_200_000 if args.panel.endswith(('-heavy','-wide')) else 1_050_000,96,8,False)
            request = {'memory_mb':128,'workers':1,'max_files':destinations,'cap':None}
            variants = [('linear',binary,request),('indexed',writers,request)]
        competitors = [1]
    elif args.panel in ('writers', 'writer-low'):
        assert writers and writers.is_file()
        low = args.panel == 'writer-low'
        rows, width, groups = (360_000, 128, 12) if low else (580_000, 512, 96)
        shape = ([partition], 'none', rows, width, groups, True)
        maximum = 16 if low else 128
        variants = [('auto', binary, {'max_files': maximum}),
                    ('sort', binary, {'max_files': maximum, 'grouping': 'sort'}),
                    ('writers', writers, {'max_files': maximum})]
        competitors = [1, 2]
    else:
        rows = 24_000 if args.panel == 'quick' else 420_000
        shape = ([partition, shuffle], 'gzip', rows, 512, 24, True)
        variants = [(str(workers), binary, {'workers': workers}) for workers in [0, 1, 2, 4]]
        competitors = [1, 2]
    if args.planned:
        assert args.panel.startswith('merge')
        variants = [('auto', binary, {'workers': 1}), ('auto-with-analyze', binary, {'workers': 1, 'analyze': True})]
    source = args.existing_source.resolve() if args.existing_source else fixture(root, *shape[2:5])
    if args.existing_source:
        rows, row_bytes, groups = shape[2:5]
        with source.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        assert source.stat().st_size == rows * row_bytes + len(HEADER)
        emit({'type': 'fixture', 'rows': rows, 'row_bytes': row_bytes, 'groups': groups,
              'bytes': source.stat().st_size, 'sha256': digest})
    if args.panel == 'counted-zstd':
        from compression import zstd
        compressed = root/'source.csv.zst'
        compressor = zstd.ZstdCompressor(options={zstd.CompressionParameter.compression_level:3, zstd.CompressionParameter.checksum_flag:1})
        compressor.set_pledged_input_size(source.stat().st_size)
        with source.open('rb') as plain, compressed.open('xb') as out:
            for chunk in iter(lambda:plain.read(2*MIB),b''):
                out.write(compressor.compress(chunk))
            out.write(compressor.flush())
        with compressed.open('rb') as data:
            digest = hashlib.file_digest(data,'sha256').hexdigest()
        emit({'type':'compressed_fixture','bytes':compressed.stat().st_size,'sha256':digest})
        source = compressed
    logical_digest = None
    for width in competitors:
        for repetition in range(1 if args.panel == 'quick' else args.rounds):
            arms = variants if repetition == 0 else variants[::-1]
            for name, executable, request in arms:
                barrier = Barrier(width) if width > 1 else None
                trial = root / f'{name}-{width}-{repetition}'
                trial.mkdir()
                with ThreadPoolExecutor(max_workers=width) as work:
                    tasks = [work.submit(run_case, trial / str(index), executable, source, shape,
                                         request, support, barrier) for index in range(width)]
                    results = [task.result() for task in tasks]
                makespan = max(item[2] for item in results) - min(item[1] for item in results)
                for record, start, _, output, tmp in results:
                    record.update(type='run', arm=name, concurrency=width, round=repetition,
                                  makespan_seconds=makespan, start_offset_seconds=start-min(item[1] for item in results),
                                  verified=False)
                    try:
                        assert record['exit'] == 0
                        assert not any(tmp.iterdir())
                        verify(output, *shape[2:], ordered=args.panel in ('writers', 'writer-low') or args.panel.startswith(('publication', 'bounded-partition')),
                               cap=request.get('cap', CAP),
                               balanced_parts=(shape[0][-1]['files'] if args.panel.startswith(('digest','counted-','terminal-')) else 0),
                               interleaved=shape[0][0]['files'] if args.panel.startswith('final-sync') or args.panel in ('wide-utf16','bounded-interleaved') else 0,
                               shuffled=args.panel.startswith('terminal-'),
                               chain=args.panel.removeprefix('chain-') if args.panel.startswith('chain-') else None,
                               quota_groups=len(shape[0][0]['groups']) if args.panel.startswith('quota-') or args.panel in ('retained-exact','bounded-probabilistic') else 0,
                               exact_strata=args.panel == 'retained-exact',output_encoding=request.get('output_encoding','utf-8'),
                               approximate=args.panel == 'bounded-probabilistic')
                        if args.panel.startswith('publication'):
                            assert record['auto_plan']['physical_plan'] == 'snapshot'
                        if args.panel.startswith('bounded-partition'):
                            expected = 'bounded_writers' if name == 'bounded' and not args.planned else 'snapshot'
                            assert record['auto_plan']['physical_plan'] == expected
                        if args.integrated and name == 'bounded':
                            assert record['auto_plan']['actual_strategy'] == 'bounded_final_writers'
                        if args.integrated and name in ('batched-sync','counted','composed','terminal','indexed','retained'):
                            expected = {'batched-sync':'batched_final_sync','counted':
                                'counted_partition_balanced' if args.panel == 'counted-partition' else 'counted_balanced',
                                'composed':'bounded_writer_chain','terminal':
                                'short_tail_uniform_merge' if args.panel == 'terminal-short' else 'wide_uniform_merge',
                                'retained':'retained_exact_writers',
                                'indexed':'existing' if args.panel in ('quota-control','quota-index') else 'indexed_exact_quota_lookup'}[name]
                            if args.panel == 'final-sync-control':
                                expected = 'existing'
                            assert record['auto_plan']['actual_strategy'] == expected, record['auto_plan']
                        if args.panel.startswith('digest'):
                            assert record['auto_plan']['physical_plan'] == 'counted'
                        if args.planned:
                            expected = 384 if request.get('analyze') and args.panel != 'merge-small' else 256
                            assert record['memory_budget_bytes'] == expected * MIB
                            assert record['auto_plan']['analysis_status'] == ('matched' if request.get('analyze') else 'absent')
                        if logical_digest is None:
                            logical_digest = record['logical_digest']
                        else:
                            assert record['logical_digest'] == logical_digest
                        record['verified'] = True
                    except (AssertionError, KeyError, OSError, ValueError, csv.Error) as error:
                        record['verification_error'] = repr(error)
                        emit(record)
                        raise
                    emit(record)
                    shutil.rmtree(output)


if __name__ == '__main__':
    main()
