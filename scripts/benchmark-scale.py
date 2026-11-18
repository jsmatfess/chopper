"""Bounded row-count benchmark. Tiny rows isolate per-record cost, not wide-row/shuffle scale.

Example: python3 scripts/benchmark-scale.py --binary .tools/linux/target/release/chopper
Reports machine metadata, elapsed time, peak RSS, CPU, phase timings and output parity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import os
import signal
import shutil
import subprocess
import tempfile
import time


def digest(path, deadline):
    h = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(8 * 1024 * 1024):
            if time.monotonic() >= deadline:
                raise TimeoutError("Verification exceeded deadline")
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=1_000_000_000)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--disk-gib', type=int, default=20)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if min(args.rows, args.seconds, args.disk_gib) <= 0:
        parser.error('limits and rows must be positive')
    budget = args.disk_gib * 1024**3
    # Source, encoded snapshot, staged output plus conservative fixed overhead.
    required = (args.rows * 2 + 2) * 3 + 512 * 1024**2
    if required > budget:
        parser.error(f'fixture needs approximately {required} bytes; exceeds disk limit')
    started = time.monotonic()
    deadline = started + args.seconds
    with tempfile.TemporaryDirectory(prefix='chopper-scale-', dir=args.work_dir) as directory:
        root = Path(directory)
        if shutil.disk_usage(root).free < required:
            raise RuntimeError('Insufficient free space')
        source = root / 'input.csv'
        block = b'x\n' * 1_000_000
        with source.open('wb') as file:
            file.write(b'v\n')
            remaining = args.rows
            while remaining:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Fixture generation exceeded deadline')
                count = min(remaining, 1_000_000)
                file.write(block[:count * 2])
                remaining -= count
        generation = time.monotonic() - started
        output = root / 'output'
        config = {'input': str(source), 'output': str(output), 'seed': 'scale-1',
                  'resources': {'memory_mb': 32, 'workers': 1, 'max_record_bytes': 1048576, 'temp_dir': str(root),
                                'temp_bytes': budget - source.stat().st_size * 2 - 128 * 1024**2}}
        job = root / 'job.json'
        job.write_text(json.dumps(config))
        print(json.dumps({'event': 'start', 'rows': args.rows, 'source_bytes': source.stat().st_size,
                          'generation_seconds': generation, 'platform': platform.platform(),
                          'disk_budget_bytes': budget, 'deadline_seconds': args.seconds}), flush=True)
        run_started = time.monotonic()
        # GNU time measures the child independently of fixture generation and verification.
        with subprocess.Popen(['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(root/'usage'),
                               str(args.binary.resolve()), 'run', '--config', str(job), '--yes'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              start_new_session=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=max(0.01, deadline-time.monotonic()))
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print(json.dumps({'event': 'timeout_or_interrupt', 'seconds': time.monotonic()-started}), flush=True)
                raise
            returncode = process.returncode
        elapsed = time.monotonic() - run_started
        if returncode:
            raise RuntimeError(f'Engine exited {returncode}: {stderr[-4000:]}')
        analysis = json.loads(stdout)
        files = list(output.glob('*.csv'))
        # Streaming fingerprints avoid loading this fixture into memory.
        assert len(files) == 1 and analysis['rows'] == args.rows
        assert source.stat().st_size == files[0].stat().st_size
        if time.monotonic() >= deadline:
            raise TimeoutError('No time remaining for verification')
        assert digest(source, deadline) == digest(files[0], deadline), 'Output differs from source'
        cpu_user, cpu_system, rss, reads, writes = map(float, (root/'usage').read_text().split())
        print(json.dumps({'event': 'complete', 'rows': args.rows, 'elapsed_seconds': elapsed,
                          'rows_per_second': args.rows/elapsed, 'analysis': analysis,
                          'execution_seconds': elapsed-analysis['analysis_seconds'],
                          'cpu_user_seconds': cpu_user, 'cpu_system_seconds': cpu_system,
                          'peak_rss_kib': rss, 'filesystem_inputs': reads, 'filesystem_outputs': writes,
                          'verified': True, 'total_seconds': time.monotonic()-started}), flush=True)


if __name__ == '__main__':
    main()
