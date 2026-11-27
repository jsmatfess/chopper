"""Capture native whole-job CPU samples, allocation census and sort wall times.

Build with CARGO_PROFILE_RELEASE_DEBUG=1 cargo build --release --locked -p chopper-csv
--bin chopper --example allocation-profile. Requires Linux perf and GNU time.
Raw perf data/reports are retained in --artifacts; stdout is portable JSONL evidence.
Allocation and CPU profiling run separately from ordinary wall/CPU/RSS measurements.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--allocator', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--cases', nargs='+', default=['resident', 'columns', 'rare_wide'],
                        choices=['resident', 'columns', 'rare_wide'])
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1 or min(args.workers) < 1:
        parser.error('require >=1000 rows and positive repeats/workers')
    for tool in ['perf', 'time']:
        if not shutil.which(tool):
            parser.error(f'{tool} is required')
    args.artifacts.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    perf_build = subprocess.check_output(['perf', 'version', '--build-options'], text=True)
    raw_offsets = any('libelf:' in line and 'OFF' in line for line in perf_build.splitlines())
    symbolizer_spec = importlib.util.spec_from_file_location('symbolizer', Path(__file__).with_name('symbolize-perf-offsets.py'))
    symbolizer = importlib.util.module_from_spec(symbolizer_spec)
    symbolizer_spec.loader.exec_module(symbolizer)

    def emit(value):
        print(json.dumps(value), flush=True)

    emit({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
          'repeats': args.repeats, 'workers': args.workers, 'cache': 'warm, uncontrolled',
          'cpu': next((s.split(':', 1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines()
                       if s.startswith('model name')), 'unknown'),
          'perf_version': subprocess.check_output(['perf', '--version'], text=True).strip(),
          'perf_build_options': perf_build,
          'binary_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                            [('before', args.before), ('binary', args.binary), ('allocator', args.allocator)]}})
    with tempfile.TemporaryDirectory(prefix='fixtures-', dir=args.artifacts.resolve()) as directory:
        root = Path(directory)
        for case in args.cases:
            source = root / 'input.csv'
            columns = 0 if case == 'resident' else 32
            with source.open('w') as f:
                f.write(','.join(['id'] + [f'c{i}' for i in range(columns)]) + '\n')
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + col) % 10) for col in range(columns)]
                    if case == 'rare_wide' and row == 0:
                        fields[1] = 'x' * 1800000
                    f.write(','.join(fields) + '\n')
            reference = None
            for workers in args.workers:
                job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'job-profiles-v1',
                       'operations': [{'type': 'shuffle', 'strategy': 'uniform'}],
                       'resources': {'memory_mb': 256 if case == 'resident' else 32,
                                     'workers': workers, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
                config = root / 'job.json'
                config.write_text(json.dumps(job))
                runs = []
                for repeat in range(args.repeats):
                    builds = [('before', args.before), ('ordinary', args.binary)]
                    runs.extend((label, binary, repeat + 1) for label, binary in
                                (builds if repeat % 2 == 0 else reversed(builds)))
                runs.extend([('allocation', args.allocator, 1), ('cpu_samples', args.binary, 1)])
                for mode, binary, repeat in runs:
                    command = [str(binary.resolve())]
                    if mode == 'allocation':
                        command += [str(config)]
                    else:
                        command += ['run', '--config', str(config), '--yes']
                    prefix = args.artifacts.resolve() / f'{case}-w{workers}'
                    if mode == 'cpu_samples':
                        command = ['perf', 'record', '-e', 'cpu-clock', '-F', '499', '--call-graph',
                                   'dwarf,16384', '-o', str(prefix) + '.perf.data', '--'] + command
                    stats = root / 'time.txt'
                    started = time.perf_counter()
                    result = subprocess.run(['/usr/bin/time', '-f', '%U %S %M', '-o', str(stats)] + command,
                                            text=True, capture_output=True, check=True, timeout=600)
                    elapsed = time.perf_counter() - started
                    user, system, rss = map(float, stats.read_text().split())
                    payload = json.loads(result.stdout)
                    analysis = payload['analysis'] if mode == 'allocation' else payload
                    actual = pipelines.fingerprint(root / 'output', analysis, 'none')
                    if reference is None:
                        reference = actual
                    if actual != reference:
                        raise AssertionError(f'{case}/{workers}/{mode}: output mismatch')
                    shutil.rmtree(root / 'output')
                    record = {'type': 'measurement', 'case': case, 'workers': workers, 'mode': mode,
                              'repeat': repeat, 'seconds': elapsed, 'cpu_seconds': user + system,
                              'peak_rss_kib': int(rss), 'diagnostics': analysis['diagnostics'],
                              'timings': analysis['timings'], 'peak_temp_bytes': analysis['peak_temp_bytes'],
                              'fingerprint': actual, 'verified': True}
                    if mode == 'allocation':
                        record['allocation_profile'] = payload['allocation_profile']
                    if mode == 'cpu_samples':
                        for name, options in [('self', ['--no-children']), ('stacks', ['--children'])]:
                            report = subprocess.check_output(['perf', 'report', '--stdio', '--percent-limit', '1',
                                '-i', str(prefix) + '.perf.data'] + options, text=True)
                            Path(str(prefix) + f'.{name}.txt').write_text(report)
                        record['perf_capture'] = result.stderr.splitlines()[-2:]
                        if raw_offsets:
                            record['cpu_profile'] = symbolizer.summarize(binary.resolve(), str(prefix) + '.perf.data')
                    emit(record)


if __name__ == '__main__':
    main()
