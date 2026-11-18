# Historical Python CSV-adapter research, not a Rust Parquet input API.
# The dormant Rust Parquet feature/dependency was removed on 2026-10-24.
"""Opt-in text-only snapshot experiment; requires PyArrow, never used by production.

Measures conversion-inclusive and replay complete CLI jobs through an explicit CSV
adapter. This is an upper bound on this adapter's performance, not a benchmark of
integrated Arrow/Parquet execution. All formats retain strings without inference.
Warm uncontrolled caches. Each measurement runs in a fresh process (GNU time).
"""
import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc

csv.field_size_limit(8 * 1024 * 1024)
MAGIC = b'CHOPBLK1'
BLOCK_ROWS = 1024
MAX_BLOCK = 16 * 1024 * 1024


def batches(rows):
    while batch := list(itertools.islice(rows, BLOCK_ROWS)):
        yield batch


def write_blocks(path, rows, compact):
    # Prototype: shared field count per block, u32 bounded lengths vs current
    # row-wise u64 count/length framing. No compression or random access index.
    with path.open('wb') as output:
        output.write(MAGIC)
        for batch in batches(rows):
            width = len(batch[0])
            payload = bytearray()
            for row in batch:
                assert len(row) == width
                if not compact:
                    payload.extend(struct.pack('<Q', width))
                for value in row:
                    value = value.encode('utf-8')
                    payload.extend(struct.pack('<I' if compact else '<Q', len(value)))
                    payload.extend(value)
            if len(payload) > MAX_BLOCK:
                raise ValueError('experimental block exceeds bounded block size')
            output.write(struct.pack('<III', len(batch), width, len(payload)))
            output.write(payload)


def read_blocks(path, compact):
    with path.open('rb') as source:
        if source.read(8) != MAGIC:
            raise ValueError('bad block version')
        while header := source.read(12):
            if len(header) != 12:
                raise ValueError('truncated block header')
            count, width, size = struct.unpack('<III', header)
            if not 0 < count <= BLOCK_ROWS or not 0 < width <= 65536 or size > MAX_BLOCK:
                raise ValueError('invalid block bounds')
            data = source.read(size)
            if len(data) != size:
                raise ValueError('truncated block')
            offset = 0

            def number(fmt):
                nonlocal offset
                length = struct.calcsize(fmt)
                if offset + length > size:
                    raise ValueError('truncated field length')
                value = struct.unpack_from(fmt, data, offset)[0]
                offset += length
                return value

            for _ in range(count):
                if not compact and number('<Q') != width:
                    raise ValueError('inconsistent field count')
                row = []
                for _ in range(width):
                    length = number('<I' if compact else '<Q')
                    if offset + length > size:
                        raise ValueError('field exceeds block')
                    row.append(data[offset:offset + length].decode('utf-8'))
                    offset += length
                yield row
            if offset != size:
                raise ValueError('trailing block bytes')


def arrow_batch(pa, batch, names):
    return pa.record_batch([pa.array(column, type=pa.string()) for column in zip(*batch)], names=names)


def convert(source, path, kind):
    import pyarrow as pa
    import pyarrow.parquet as pq
    with source.open(newline='') as stream:
        rows = csv.reader(stream, strict=True)
        names = next(rows)
        if kind in ('compact', 'u64'):
            write_blocks(path, itertools.chain([names], rows), kind == 'compact')
        else:
            schema = pa.schema([(name, pa.string()) for name in names])
            if kind == 'parquet':
                with pq.ParquetWriter(path, schema, compression='snappy') as writer:
                    for batch in batches(rows):
                        writer.write_batch(arrow_batch(pa, batch, names))
            else:
                # Feather V2 is the Arrow IPC file format. Keep compression
                # disabled so this experiment isolates layout/conversion costs.
                with pa.OSFile(str(path), 'wb') as sink, pa.ipc.new_file(sink, schema) as writer:
                    for batch in batches(rows):
                        writer.write_batch(arrow_batch(pa, batch, names))


def decoded_rows(path, kind):
    if kind in ('compact', 'u64'):
        yield from read_blocks(path, kind == 'compact')
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq
        if kind == 'parquet':
            source = pq.ParquetFile(path)
            yield source.schema_arrow.names
            blocks = source.iter_batches(batch_size=BLOCK_ROWS)
        else:
            source = pa.ipc.open_file(str(path))
            yield source.schema.names
            blocks = (source.get_batch(i) for i in range(source.num_record_batches))
        for block in blocks:
            columns = [column.to_pylist() for column in block.columns]
            for row in zip(*columns):
                if any(value is None or not isinstance(value, str) for value in row):
                    raise ValueError('experiment accepts non-null text columns only')
                yield row


def field_digest(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update(struct.pack('<Q', len(row)))
        for field in row:
            value = field.encode('utf-8')
            digest.update(struct.pack('<Q', len(value)))
            digest.update(value)
    return digest.hexdigest()


def worker(args):
    root = args.root
    source, snapshot, adapted = root / 'input.csv', root / args.kind, root / 'adapted.csv'
    import pyarrow as pa
    if args.trace:
        tracemalloc.start()
    start = time.perf_counter()
    conversion = 0
    revalidation = 0
    if args.kind != 'csv':
        if args.phase == 'replay':
            digest = hashlib.sha256()
            with source.open('rb') as original:
                while chunk := original.read(1024 * 1024):
                    digest.update(chunk)
            assert digest.hexdigest() == (root / 'source.sha256').read_text()
            revalidation = time.perf_counter() - start
        if args.phase == 'first':
            convert(source, snapshot, args.kind)
            conversion = time.perf_counter() - start
        with adapted.open('w', newline='') as output:
            csv.writer(output, lineterminator='\n').writerows(decoded_rows(snapshot, args.kind))
    adapter_done = time.perf_counter()
    config = json.loads((root / 'job.json').read_text())
    config['input'] = str(source if args.kind == 'csv' else adapted)
    (root / 'active.json').write_text(json.dumps(config))
    output = root / 'output'
    shutil.rmtree(output, ignore_errors=True)
    result = subprocess.run([str(args.binary), 'run', '--config', str(root / 'active.json'), '--yes'],
                            check=True, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    analysis = json.loads(result.stdout)
    peak = tracemalloc.get_traced_memory()[1] if args.trace else None
    if args.trace:
        tracemalloc.stop()
    # Correctness checks are outside timed interval and allocation peak.
    if args.kind != 'csv':
        with source.open(newline='') as original, adapted.open(newline='') as decoded:
            assert field_digest(csv.reader(original)) == field_digest(csv.reader(decoded))
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    fingerprint = pipelines.fingerprint(output, analysis, 'none')
    print(json.dumps({'kind': args.kind, 'phase': args.phase, 'seconds': elapsed,
                      'conversion_seconds': conversion, 'source_revalidation_seconds': revalidation,
                      'adapter_seconds': adapter_done - start - conversion - revalidation,
                      'cli_seconds': elapsed - (adapter_done - start), 'python_peak_traced_bytes': peak,
                      'arrow_pool_peak_bytes': pa.default_memory_pool().max_memory(),
                      'source_bytes': source.stat().st_size,
                      'snapshot_bytes': snapshot.stat().st_size if snapshot.exists() else 0,
                      'adapter_bytes': adapted.stat().st_size if args.kind != 'csv' else 0,
                      'diagnostics': analysis['diagnostics'], 'fingerprint': fingerprint,
                      'verified': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('.tools/linux/target/release/chopper'))
    parser.add_argument('--rows', type=int, default=100000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--trace', action='store_true', help='instrument Python allocations; timings are perturbed')
    parser.add_argument('--kind', choices=['csv', 'u64', 'compact', 'ipc', 'parquet'])
    parser.add_argument('--phase', choices=['first', 'replay'])
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    if args.kind:
        worker(args)
        return
    import pyarrow as pa
    print(json.dumps({'event': 'environment', 'platform': platform.platform(), 'pyarrow': pa.__version__,
                      'rows': args.rows, 'repeats': args.repeats, 'cache': 'warm uncontrolled WSL',
                      'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                      'limitations': 'CSV disk adapter; Python prototype; traced allocations exclude Arrow native allocations; GNU time max RSS includes verification and child peak, not simultaneous parent+child sum'}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-formats-') as directory:
        root = Path(directory)
        for shape in ['narrow', 'many', 'rare_wide']:
            width = 33 if shape == 'many' else 4
            with (root / 'input.csv').open('w', newline='') as output:
                writer = csv.writer(output, lineterminator='\n')
                writer.writerow(['id'] + [f'c{i}' for i in range(width - 1)])
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + i) % 17) for i in range(width - 1)]
                    fields[-1] = (['001.00', '', 'NULL', '2026-01-01', '界,"\nline'][row % 5])
                    if shape == 'rare_wide' and row == args.rows // 2:
                        fields[-1] = '界' * 300000
                    writer.writerow(fields)
            (root / 'source.sha256').write_text(hashlib.sha256((root / 'input.csv').read_bytes()).hexdigest())
            for pipeline in ['shuffle', 'partition']:
                operations = ([{'type': 'shuffle', 'strategy': 'uniform'}, {'type': 'balanced', 'files': 4}]
                              if pipeline == 'shuffle' else [{'type': 'partition', 'columns': ['c0']}])
                config = {'output': str(root / 'output'), 'seed': 'format-experiment-v1',
                          'operations': operations, 'resources': {'memory_mb': 32, 'workers': 1,
                          'max_record_bytes': 2097152, 'temp_dir': str(root)}}
                (root / 'job.json').write_text(json.dumps(config))
                reference = None
                for repeat in range(args.repeats):
                    kinds = ['csv', 'u64', 'compact', 'ipc', 'parquet']
                    if repeat % 2:
                        kinds.reverse()
                    for kind in kinds:
                        for phase in (['first'] if kind == 'csv' else ['first', 'replay']):
                            command = ['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(root / 'time.txt'),
                                       sys.executable, __file__, '--binary', str(args.binary), '--root', str(root),
                                       '--kind', kind, '--phase', phase]
                            if args.trace:
                                command.append('--trace')
                            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=300)
                            observation = json.loads(result.stdout)
                            fingerprint = observation.pop('fingerprint')
                            if reference is None:
                                reference = fingerprint
                            assert fingerprint == reference, (shape, pipeline, kind, phase)
                            user, system, rss, reads, writes = map(float, (root / 'time.txt').read_text().split())
                            observation.update(event='allocation' if args.trace else 'job', shape=shape, pipeline=pipeline, repeat=repeat,
                                               user_seconds=user, system_seconds=system, max_rss_kib=rss,
                                               filesystem_inputs=reads, filesystem_outputs=writes)
                            print(json.dumps(observation), flush=True)
                for path in root.iterdir():
                    if path.is_file() and path.name not in ['input.csv', 'job.json', 'source.sha256']:
                        path.unlink()


if __name__ == '__main__':
    main()
