#!/usr/bin/env python3
"""Bounded cross-tool development comparison; no engine/default changes.

Requires a fresh work directory, Chopper, qsv 29 and Python with DuckDB 2.
Complete-job clocks include process startup, input count, materialization and all
CSV writes. Verification and successful payload removal are outside the clock.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import threading
import signal

HEADER = ['id', 'key', 'empty', 'payload']
PAYLOAD = 'x' * 237


def payload(ordinal, shape):
    if shape == 'repeated':
        return PAYLOAD
    return hashlib.shake_256(ordinal.to_bytes(8, 'little')).hexdigest(119)[:237]


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def worker(a):
    out = Path(a.output)
    if a.tool == 'duckdb':
        import duckdb
        out.mkdir()
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{a.memory}MiB'")
        con.execute(f"SET threads={a.workers}")
        con.execute(f"SET temp_directory='{out.parent / 'duck-temp'}'")
        con.execute('SET preserve_insertion_order=true')
        order = ' ORDER BY random()' if a.job == 'shuffle' else ''
        # All fields stay text, including leading zeroes and empty strings.
        con.execute(f"CREATE TABLE data AS SELECT * FROM read_csv(?, header=true, all_varchar=true, nullstr='__never_null__', parallel=true){order}", [a.input])
        n = con.execute('SELECT count(*) FROM data').fetchone()[0]
        size, remainder = divmod(n, 8)
        start = 0
        for i in range(8):
            count = size + (i < remainder)
            con.execute(f"COPY (SELECT * FROM data LIMIT {count} OFFSET {start}) TO '{out / f'{i:02}.csv'}' (HEADER, DELIMITER ',')")
            start += count
        con.close()
        return
    qsv = str(Path(a.qsv).resolve())
    source = a.input
    if a.job == 'shuffle':
        source = str(out.parent / 'shuffled.csv')
        subprocess.run([qsv, 'sort', '--random', '-j', str(a.workers), a.input, '-o', source], check=True)
    subprocess.run([qsv, 'split', '--chunks', '8', '-j', str(a.workers), str(out), source], check=True)
    if a.job == 'shuffle':
        Path(source).unlink()


def verify(out, n, job, tool, shape='repeated'):
    files = list(out.rglob('*.csv'))
    assert len(files) == 8, (out, len(files))
    # qsv filenames are starting offsets; Chopper files have canonical names.
    if tool == 'qsv':
        files.sort(key=lambda p: int(p.stem))
    else:
        files.sort()
    seen = bytearray(n)
    counts = []
    hashes = {}
    sequential = 0
    changed = False
    for path in files:
        count = 0
        with path.open(newline='') as stream:
            rows = csv.reader(stream)
            assert next(rows) == HEADER
            for row in rows:
                ordinal = int(row[0])
                assert len(row) == 4 and row[1:] == ['00001', '', payload(ordinal, shape)], row[:3]
                assert row[0] == f'{ordinal:010d}' and 0 <= ordinal < n
                assert not seen[ordinal], ordinal
                seen[ordinal] = 1
                if job == 'balanced':
                    assert ordinal == sequential, (path, ordinal, sequential)
                changed |= ordinal != sequential
                sequential += 1
                count += 1
        counts.append(count)
        hashes[str(path.relative_to(out))] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    assert sequential == n and all(seen)
    assert max(counts) - min(counts) <= 1
    if job == 'shuffle':
        assert changed
    return {'rows': n, 'counts': counts, 'files': hashes, 'verification': 'exact unique IDs, all fields, conservation, quotas, balanced order; shuffle nonidentity only (not distribution proof)'}


def run(a):
    root = Path(a.work).resolve()
    root.mkdir(parents=True, exist_ok=False)
    fixture = root / 'input.csv'
    n = a.mib * 4096
    h = hashlib.sha256()
    with fixture.open('wb') as stream:
        header = (','.join(HEADER) + '\n').encode()
        stream.write(header)
        h.update(header)
        for start in range(0, n, 4096):
            block = ''.join(f'{i:010d},00001,,{payload(i, a.shape)}\n' for i in range(start, min(start + 4096, n))).encode()
            stream.write(block)
            h.update(block)
    context = {'kind': 'context', 'schema': 1, 'argv': sys.argv, 'platform': platform.platform(), 'python': sys.version, 'cpu_count': os.cpu_count(), 'fixture': {'sha256': h.hexdigest(), 'bytes': fixture.stat().st_size, 'rows': n, 'data_row_bytes': 256, 'shape': a.shape}, 'memory_mib': a.memory, 'workers': a.workers, 'cache': 'warm/uncontrolled WSL2 ext4 page cache; no cache drop', 'clock': 'CLI/Python process startup through exit, all reads/counts/materialization/output; no fsync durability claim', 'binaries': {p: sha(p) for p in [a.chopper, a.qsv, __file__]}, 'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'versions': {'qsv': subprocess.check_output([a.qsv, '--version'], text=True).strip(), 'duckdb': subprocess.check_output([sys.executable, '-c', 'import duckdb; print(duckdb.__version__)'], text=True).strip()}}
    evidence = root / 'results.jsonl'
    def record(value):
        with evidence.open('a') as stream:
            stream.write(json.dumps(value, sort_keys=True) + '\n')
    record(context)
    tools = a.tools.split(',')
    for rep in range(-1, a.repetitions):
        order = tools[rep % len(tools):] + tools[:rep % len(tools)]
        for job in a.jobs.split(','):
            for tool in order:
                label = f'{job}-{tool}-{rep + 1}'
                attempt = root / label
                attempt.mkdir()
                out = attempt / 'output'
                if tool.startswith('chopper'):
                    (attempt / 'temp').mkdir()
                    ops = []
                    if job == 'shuffle':
                        ops = [{'type': 'shuffle', 'strategy': 'fisher_yates' if tool == 'chopper-fisher' else 'uniform'}]
                    ops += [{'type': 'balanced', 'files': 8}]
                    config = {'version': 1, 'input': str(fixture), 'output': str(out), 'operations': ops, 'resources': {'memory_mb': a.memory, 'workers': a.workers, 'temp_dir': str(attempt / 'temp')}}
                    if tool == 'chopper-direct':
                        config['operations'] = []
                        config['limits'] = {'rows': n // 8}
                    (attempt / 'job.json').write_text(json.dumps(config, indent=2))
                    cmd = [str(Path(a.chopper).resolve()), 'run', '--config', str(attempt / 'job.json'), '--yes']
                else:
                    cmd = [sys.executable, str(Path(__file__).resolve()), 'worker', '--tool', tool, '--input', str(fixture), '--output', str(out), '--job', job, '--memory', str(a.memory), '--workers', str(a.workers), '--qsv', str(Path(a.qsv).resolve())]
                clock = time.perf_counter()
                with (attempt / 'stdout').open('w') as stdout, (attempt / 'stderr').open('w') as stderr:
                    proc = subprocess.Popen(['/usr/bin/time', '-v', '-o', str(attempt / 'time.txt'), *cmd], stdout=stdout, stderr=stderr, start_new_session=True)
                    def timeout():
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    watchdog = threading.Timer(600, timeout)
                    watchdog.start()
                    try:
                        code = proc.wait()
                    finally:
                        watchdog.cancel()
                seconds = time.perf_counter() - clock
                value = {'kind': 'measurement', 'tool': tool, 'job': job, 'repetition': rep, 'excluded_warmup': rep == -1, 'seconds': seconds, 'exit_code': code, 'command': cmd, 'gnu_time': (attempt / 'time.txt').read_text(), 'attempt': str(attempt)}
                if code == 0:
                    try:
                        value['verified'] = verify(out, n, job, tool, a.shape)
                    except Exception as error:
                        value['verification_error'] = repr(error)
                        record(value)
                        raise
                    if tool.startswith('chopper'):
                        value['analysis'] = json.loads((attempt / 'stdout').read_text())
                    shutil.rmtree(out)
                record(value)
                print(json.dumps({k: value[k] for k in ['tool', 'job', 'repetition', 'seconds', 'exit_code']}), flush=True)
                if code:
                    raise RuntimeError(f'failed: {attempt}')
    fixture.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['run', 'worker'])
    parser.add_argument('--work')
    parser.add_argument('--shape', choices=['repeated', 'varied'], default='repeated')
    parser.add_argument('--mib', type=int, default=128)
    parser.add_argument('--memory', type=int, default=4096)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--tools', default='chopper,duckdb,qsv')
    parser.add_argument('--jobs', default='balanced,shuffle')
    parser.add_argument('--chopper', default='target/release/chopper')
    parser.add_argument('--qsv', default='scratch/tool-comparison/qsv/qsv')
    parser.add_argument('--tool')
    parser.add_argument('--input')
    parser.add_argument('--output')
    parser.add_argument('--job')
    a = parser.parse_args()
    assert a.mib > 0 and a.memory >= 32 and a.workers > 0 and a.repetitions > 0
    (run if a.mode == 'run' else worker)(a)


if __name__ == '__main__':
    main()
