"""Bounded native full-shuffle stress with exact unique-ID conservation.

Uses generate/verify-scale release examples. A single narrow warm-WSL run is not
terabyte, wide-row, device-throughput or cross-platform certification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import time


def check_verifier(verifier):
    good = 'id,country,segment,payload\n0,US,0,""\n1,GB,1,""\n'
    controls = {'valid': good,
                'duplicate': good.replace('1,GB,1', '0,US,0'),
                'missing': good.rsplit('1,GB,1', 1)[0],
                'out_of_range': good.replace('1,GB,1', '2,DE,2'),
                'wrong_value': good.replace('1,GB,1', '1,US,1'),
                'changed_id_text': good.replace('1,GB,1', '01,GB,1')}
    with tempfile.TemporaryDirectory(prefix='chopper-scale-checker-') as directory:
        root = Path(directory)
        for name, data in controls.items():
            encoded = data.encode()
            (root / 'part.csv').write_bytes(encoded)
            rows = 1 if name == 'missing' else 2
            (root / 'manifest.jsonl').write_text(json.dumps({'type': 'output', 'path': 'part.csv',
                'rows': rows, 'csv_bytes': len(encoded), 'lineage': []}) + '\n')
            result = subprocess.run([str(verifier), str(root), '2'], capture_output=True, text=True, timeout=30)
            assert (result.returncode == 0) == (name == 'valid'), (name, result.stderr)
    print(json.dumps({'event': 'checker_controls', 'cases': list(controls), 'verified': True}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('.tools/linux/target/release/chopper'))
    parser.add_argument('--rows', type=int, default=1000000)
    parser.add_argument('--memory-mb', type=int, default=256)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--disk-gib', type=int, default=256)
    parser.add_argument('--seconds', type=int, default=7200)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    if min(args.rows, args.memory_mb, args.workers, args.disk_gib, args.seconds) <= 0:
        parser.error('all limits must be positive')
    binary = args.binary.resolve()
    generator, verifier = binary.parent / 'examples/generate', binary.parent / 'examples/verify-scale'
    for path in [binary, generator, verifier]:
        if not path.is_file():
            parser.error(f'missing executable: {path}')
    check_verifier(verifier)
    budget = args.disk_gib * 1024**3
    # Four-field, empty-payload generator: <= 32 bytes/CSV row. The engine's
    # temporary budget is separate and protects algorithm spills; reserve source
    # and external destination space up front as well.
    outside = args.rows * 64 + 2 * 1024**3
    if budget <= outside:
        parser.error('disk ceiling cannot cover source and published CSV output')
    started = time.monotonic()
    deadline = started + args.seconds
    print(json.dumps({'event': 'environment', 'platform': platform.platform(),
                      'cpu': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                                   if line.startswith('model name')), 'unknown'),
                      'meminfo': Path('/proc/meminfo').read_text(), 'rows': args.rows,
                      'memory_mb': args.memory_mb, 'workers': args.workers,
                      'disk_budget_bytes': budget, 'deadline_seconds': args.seconds,
                      'cache': 'uncontrolled WSL; source generated immediately before execution; source/spills may exceed page cache; no physical-device throughput claim',
                      'binary_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [binary, generator, verifier]}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-shuffle-scale-', dir=args.work_dir) as directory:
        root = Path(directory)
        available = shutil.disk_usage(root).free
        if available < budget + 1024**3:
            raise RuntimeError('insufficient free space for requested disk ceiling plus headroom')

        def run(label, command):
            usage = root / f'{label}.usage'
            begin = time.monotonic()
            with subprocess.Popen(['/usr/bin/time', '-f', '%U %S %M %I %O', '-o', str(usage)] + command,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  start_new_session=True) as process:
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('scale experiment exceeded deadline')
                        try:
                            stdout, stderr = process.communicate(timeout=min(30, remaining))
                            break
                        except subprocess.TimeoutExpired:
                            print(json.dumps({'event': 'running', 'phase': label,
                                              'elapsed_seconds': time.monotonic() - begin,
                                              'free_bytes': shutil.disk_usage(root).free}), flush=True)
                            if shutil.disk_usage(root).free < 1024**3:
                                raise RuntimeError('scale experiment exhausted disk headroom')
                except BaseException:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise
                if process.returncode:
                    raise RuntimeError(f'{label} exited {process.returncode}: {stderr[-4000:]}')
            user, system, rss, reads, writes = map(float, usage.read_text().split())
            return stdout, {'seconds': time.monotonic() - begin, 'user_seconds': user,
                            'system_seconds': system, 'peak_rss_kib': rss,
                            'filesystem_inputs': reads, 'filesystem_outputs': writes}

        source = root / 'input.csv'
        _, generation = run('generate', [str(generator), str(source), str(args.rows), '0'])
        job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'shuffle-scale-v1',
               'operations': [{'type': 'shuffle', 'strategy': 'uniform'}, {'type': 'balanced', 'files': 4}],
               'resources': {'memory_mb': args.memory_mb, 'workers': args.workers,
                             'max_record_bytes': 1048576, 'temp_dir': str(root),
                             'temp_bytes': budget - outside}}
        config = root / 'job.json'
        config.write_text(json.dumps(job))
        print(json.dumps({'event': 'generated', 'source_bytes': source.stat().st_size,
                          'available_bytes_at_start': available, 'generation': generation,
                          'config': job}), flush=True)
        stdout, measures = run('shuffle', [str(binary), 'run', '--config', str(config), '--yes'])
        analysis = json.loads(stdout)
        assert analysis['rows'] == args.rows and analysis['output_files'] == 4
        checked, verification = run('verify', [str(verifier), str(root / 'output'), str(args.rows)])
        conservation = json.loads(checked)
        assert conservation['verified'] and conservation['rows'] == args.rows
        assert len(conservation['files']) == 4
        assert sorted(x['rows'] for x in conservation['files']) == sorted(
            args.rows // 4 + int(i < args.rows % 4) for i in range(4))
        print(json.dumps({'event': 'complete', 'rows': args.rows, 'measures': measures,
                          'source_bytes': source.stat().st_size, 'analysis': analysis,
                          'verification': verification, 'conservation': conservation,
                          'total_seconds': time.monotonic() - started, 'verified': True}), flush=True)


if __name__ == '__main__':
    main()
