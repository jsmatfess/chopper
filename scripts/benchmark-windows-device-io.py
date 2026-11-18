"""Bounded warm-cache whole-device follow-up; uses retained Windows builds."""
import argparse
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def window(device, seconds, before):
    if not math.isfinite(seconds) or seconds < 1:
        raise ValueError('device control windows require at least one second')
    if before is not device.last_snapshot:
        raise ValueError('control must reuse the latest device boundary')
    after, waited = device.snapshot_when_ready(
        not_before_ns=before['query_end_perf_ns'] + int(seconds * 1e9))
    return {'before': before, 'after': after, 'delta': deviceio.delta(before, after),
            'requested_seconds': seconds, 'wait_seconds': waited}


def finish_job_window(device, before, started_ns, ended_ns):
    """End CLI timing before any explicit counter-cadence padding."""
    if not before['query_end_perf_ns'] <= started_ns <= ended_ns:
        raise ValueError('CLI interval must follow its device start boundary')
    if before is not device.last_snapshot:
        raise ValueError('job must reuse the latest device boundary')
    after, waited = device.snapshot_when_ready()
    flags = []
    if ended_ns - started_ns < deviceio.MIN_COLLECTION_NS:
        flags.append('short_cli_interval')
    if waited > 0:
        flags.append('device_window_padded_after_cli')
    return {'before': before, 'after': after, 'delta': deviceio.delta(before, after),
            'cli_start_perf_ns': started_ns, 'cli_end_perf_ns': ended_ns,
            'cli_seconds': (ended_ns - started_ns) / 1e9,
            'pre_cli_boundary_gap_seconds': (started_ns - before['query_end_perf_ns']) / 1e9,
            'post_cli_boundary_gap_seconds': (after['query_start_perf_ns'] - ended_ns) / 1e9,
            'post_cli_padding_seconds': waited, 'attribution_flags': flags}


def noise_flags(job, pre, drain, post):
    flags = []
    for direction in ('read', 'write'):
        key = direction + '_bytes'
        amount = job[key]
        if amount == 0:
            flags.append(direction + ':zero_job_delta')
            continue
        for name, control in [('pre_idle', pre), ('drain', drain), ('post_idle', post)]:
            # Compare rates for idle controls; drain compares total bytes because
            # delayed writes outside the job window limit interpretation directly.
            value = control['delta'][key]
            if name != 'drain':
                value *= job['snapshot_midpoint_seconds'] / control['delta']['snapshot_midpoint_seconds']
            if value > amount * .1:
                flags.append(direction + ':' + name + '_exceeds_10pct')
    return flags


windows = module('windows', 'benchmark-windows.py')
external = module('external', 'benchmark-external-shuffle.py')
deviceio = module('deviceio', 'windows-device-io.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--build-evidence', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--cells', nargs='+', choices=['external', 'hierarchical'], default=['external', 'hierarchical'])
    args = parser.parse_args()
    if os.name != 'nt' or not 1 <= args.repeats <= 3 or len(set(args.cells)) != len(args.cells):
        parser.error('requires Windows, 1..3 repeats and distinct cells')
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    provenance = windows.build_provenance(binaries, args.build_evidence)
    csv.field_size_limit(2097152)
    with args.output.open('x', encoding='utf-8', newline='\n', buffering=1) as artifact, deviceio.DeviceIO(args.work_dir) as device:
        def emit(value):
            artifact.write(json.dumps(value) + '\n')
        emit({'type': 'environment', 'platform': platform.platform(), 'python': platform.python_version(),
              'binary_sha256': {k: windows.sha(v) for k, v in binaries.items()},
              'features': {'baseline': [], 'candidate': ['experimental-shuffle-partition']},
              'reused_build_provenance': provenance, 'source_sha256': provenance['build_source_sha256'],
              'harness_sha256': {str(Path(p)): windows.sha(p) for p in [__file__, windows.__file__, external.__file__, deviceio.__file__]},
              'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'dirty_status': subprocess.check_output(['git', 'status', '--short'], text=True),
              'device_mapping': device.mapping, 'free_bytes': shutil.disk_usage(args.work_dir).free,
              'scope': 'whole device stack aggregate; all processes; not NAND or process attribution',
              'cache': 'warm/uncontrolled; no eviction/flush; generation and verification touch cache',
              'timing_scope': 'CLI spawn through wait only; device interval separately records boundary gaps and explicit post-CLI cadence padding',
              'collection_cadence': 'at least 1s from previous collection end to next start; immediate collection rejects early calls; shared adjacent boundaries',
              'controls': '2s pre-idle, 2s drain after job device boundary before verification, 2s post-idle; never subtract noise',
              'attribution_rule': 'short CLI (<1s) or any explicit post-CLI padding makes physical-effect inference ineligible even if noise checks pass',
              'noise_rule': 'per direction: zero job delta, idle rate >10% job rate, or drain bytes >10% job bytes makes physical-effect inference ineligible',
              'shared_limit': os.environ.get('CHOPPER_MEMORY_LIMIT_MB'), 'repeats': args.repeats,
              'stop_criterion': 'selected cells/repeats only; abort first correctness/cleanup/counter failure; preserve noise; no promotion'})
        with tempfile.TemporaryDirectory(prefix='device-io-', dir=args.work_dir) as directory:
            root = Path(directory)
            for cell in args.cells:
                rows = {'external': 300000, 'hierarchical': 1400000}[cell]
                source = root / 'input.csv'
                with source.open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream, lineterminator='\n')
                    writer.writerow(['id', 'payload'] + [f'c{i}' for i in range(31)])
                    writer.writerows(external.fields(row, 'columns') for row in range(rows))
                emit({'type': 'fixture', 'cell': cell, 'rows': rows, 'shape': 'columns', 'case': 'shuffle_partition',
                      'sha256': windows.sha(source), 'bytes': source.stat().st_size})
                reference, observations = None, []
                for repeat in range(args.repeats):
                    order = ['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']
                    for variant in order:
                        owned = root / 'owned'
                        owned.mkdir()
                        temp, output = owned / 'temp', owned / 'output'
                        temp.mkdir()
                        job = {'input': str(source), 'output': str(output), 'seed': 'external-comparison-v1',
                               'operations': external.operations_for('shuffle_partition', 'columns', 4),
                               'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152, 'temp_dir': str(temp)},
                               'limits': {'bytes': 100000000}}
                        config = root / 'job.json'
                        config.write_text(json.dumps(job), encoding='utf-8')
                        process, sampler = None, windows.Space(owned)
                        try:
                            pre_start, pre_start_wait = device.snapshot_when_ready()
                            pre = window(device, 2, pre_start)
                            pre['start_cadence_wait_seconds'] = pre_start_wait
                            with (root / 'stdout').open('wb') as stdout, (root / 'stderr').open('wb') as stderr:
                                sampler.thread.start()
                                before = pre['after']
                                started = time.perf_counter_ns()
                                process = subprocess.Popen([str(binaries[variant]), 'run', '--config', str(config), '--yes'], stdout=stdout, stderr=stderr)
                                process.wait(timeout=180)
                                ended = time.perf_counter_ns()
                                job_window = finish_job_window(device, before, started, ended)
                                elapsed = job_window['cli_seconds']
                                metrics = windows.counters(process)
                                drain = window(device, 2, job_window['after'])
                                storage = sampler.finish()
                                post = window(device, 2, drain['after'])
                            analysis = json.loads((root / 'stdout').read_text(encoding='utf-8')) if process.returncode == 0 else None
                            if process.returncode:
                                raise RuntimeError((root / 'stderr').read_text(encoding='utf-8'))
                            actual = external.verify(output, analysis, 'columns', rows, 'shuffle_partition')
                            assert analysis['diagnostics']['shuffle_partition_fusions'] == int(variant == 'candidate')
                            assert all(p.stat().st_size <= 100000000 for p in output.glob('*.csv'))
                            assert not list(temp.iterdir()), 'temporary files leaked'
                            assert set(owned.iterdir()) == {temp, output}, 'publication staging leaked'
                            if reference is None:
                                reference = actual
                            assert actual == reference, 'exact output/metadata parity mismatch'
                            job_delta = job_window['delta']
                            flags = noise_flags(job_delta, pre, drain, post)
                            observation = {'type': 'measurement', 'cell': cell, 'variant': variant, 'repeat': repeat + 1,
                                           'seconds': elapsed, **metrics, 'storage': storage, 'config': job,
                                           'diagnostics': analysis['diagnostics'], 'timings': analysis['timings'],
                                           'peak_temp_bytes': analysis['peak_temp_bytes'], 'fingerprint': actual,
                                           'verified': True, 'cleanup_verified': True,
                                           'device_io': {**job_window,
                                                         'pre_idle': pre, 'drain': drain, 'post_idle': post},
                                           'physical_effect_inference_eligible': not flags and not job_window['attribution_flags'],
                                           'noise_flags': flags}
                            observations.append(observation)
                            emit(observation)
                        except BaseException as error:
                            if process is not None and process.poll() is None:
                                process.kill()
                                process.wait()
                            if sampler.thread.ident is not None:
                                sampler.finish()
                            emit({'type': 'failure', 'cell': cell, 'variant': variant, 'repeat': repeat + 1,
                                  'error': repr(error), 'stdout': (root / 'stdout').read_text(encoding='utf-8', errors='replace') if (root / 'stdout').exists() else None,
                                  'stderr': (root / 'stderr').read_text(encoding='utf-8', errors='replace') if (root / 'stderr').exists() else None})
                            raise
                        shutil.rmtree(owned)
                emit({'type': 'summary', 'cell': cell, 'samples_per_variant': args.repeats,
                      'median_seconds': {v: statistics.median(r['seconds'] for r in observations if r['variant'] == v) for v in binaries},
                      'range_seconds': {v: [min(r['seconds'] for r in observations if r['variant'] == v), max(r['seconds'] for r in observations if r['variant'] == v)] for v in binaries},
                      'eligible_physical_inference_jobs': sum(r['physical_effect_inference_eligible'] for r in observations),
                      'noise_subtracted': False})


if __name__ == '__main__':
    main()
