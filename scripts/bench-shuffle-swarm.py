#!/usr/bin/env python3
"""Small named native complete-job A/B harness. Execution requires lead authorization."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time
import threading
import traceback

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('swarm_verify', Path(__file__).with_name('verify-shuffle-swarm.py'))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def exclusive_copy(source, target):
    with Path(source).open('rb') as src, Path(target).open('xb') as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())


def provenance(binary, source, target, candidate=False):
    """Bind artifacts to retained build records, never infer a build from current HEAD."""
    source = source.resolve(strict=True)
    verify.require(source.stat().st_mode & 0o222 == 0, 'build manifest must be read-only')
    before = verify.sha(source)
    record = json.loads(source.read_text())
    for field in ('source_head', 'features', 'artifacts', 'runner_receipt', 'runner_receipt_sha256', 'plan_sha256'):
        verify.require(field in record, f'provenance missing {field}')
    matches = [a for a in record['artifacts'] if Path(a['path']).resolve() == binary]
    verify.require(len(matches) == 1, 'binary absent/ambiguous in artifact manifest')
    actual = verify.sha(binary)
    verify.require(actual == matches[0]['sha256'] and binary.stat().st_size == matches[0]['size'],
                   'binary differs from build artifact record')
    target.mkdir()
    exclusive_copy(source, target / 'artifact-manifest.json')
    (target / 'artifact-manifest.json').chmod(0o444)
    refs = [dict(path=record['runner_receipt'], sha256=record['runner_receipt_sha256'], role='runner')]
    # Existing pinned baseline stores its source/toolchain inventory beside its manifest.
    if not candidate:
        verify.require(record['source_head'] == 'de93a7a728fd8652f01627b1d1483409ed499455',
                       'unexpected production baseline revision')
        for name in ('tracked-before.json', 'toolchain-details.json'):
            path = source.parent / 'provenance' / name
            refs.append(dict(path=str(path), sha256=verify.sha(path), role=name))
    refs.extend(record.get('provenance', []))
    if candidate:
        roles = {ref.get('role') for ref in refs}
        verify.require({'source', 'toolchain'} <= roles, 'candidate needs frozen source and toolchain provenance refs')
    receipts = []
    for index, ref in enumerate(refs):
        path = Path(ref['path'])
        verify.require(path.is_absolute(), 'provenance reference must be absolute')
        verify.require(verify.sha(path) == ref['sha256'], 'provenance reference hash mismatch')
        copy = target / f'{index:02d}-{path.name}'
        exclusive_copy(path, copy)
        copy.chmod(0o444)
        if candidate and ref.get('role') in ('source', 'toolchain'):
            verify.require(path.stat().st_mode & 0o222 == 0, 'candidate source/toolchain record must be read-only')
        if candidate and ref.get('role') == 'source':
            frozen = json.loads(copy.read_text())
            verify.require(frozen['captured_after_source_freeze'] is True, 'source record must follow source freeze')
            verify.require(frozen['source_head'] == record['source_head'] and 'git_status' in frozen, 'source identity mismatch')
            verify.require(bool(frozen['files']), 'empty source manifest')
            frozen_root = Path(frozen.get('source_root', ROOT)).resolve(strict=True)
            verify.require(frozen_root.is_relative_to(ROOT), 'frozen source root escapes checkout')
            for relative, digest in frozen['files'].items():
                item = (frozen_root / relative).resolve(strict=True)
                verify.require(item.is_relative_to(frozen_root), 'source manifest path escapes snapshot')
                verify.require(verify.sha(item) == digest, f'frozen source changed: {relative}')
        verify.require(verify.sha(copy) == ref['sha256'], 'provenance copy mismatch')
        receipts.append(dict(**ref, retained_path=str(copy)))
    verify.require(verify.sha(source) == before, 'build manifest changed during capture')
    return dict(path=str(source), sha256=before, binary_path=str(binary), binary_sha256=actual,
                source_head=record['source_head'], features=record['features'], references=receipts)


def order(repetition):
    return ('baseline', 'candidate') if repetition % 2 == 0 else ('candidate', 'baseline')


def make_job(recipe, fixture, destination):
    return dict(version=1, input=str(fixture), output=str(destination),
                seed='shuffle-swarm-v1', operations=recipe['operations'],
                resources=dict(memory_mb=32, workers=1, max_record_bytes=1048576,
                               temp_dir=str(destination.parent / 'temporary')),
                limits={} if recipe['name'].startswith('balanced-') else dict(rows=10000, bytes=4194304))


def run_process(command, attempt, timeout):
    # GNU time is a separate per-process record. Its fs counters are OS accounting,
    # not device bytes/SSD throughput. No cumulative getrusage is used.
    timed = ['/usr/bin/time', '-o', str(attempt / 'time.txt'), '-f',
             '{"user_seconds":%U,"system_seconds":%S,"max_rss_kib":%M,"fs_inputs":%I,"fs_outputs":%O}',
             *command]
    with (attempt / 'stdout').open('xb') as stdout, (attempt / 'stderr').open('xb') as stderr:
        start = time.perf_counter_ns()
        process = subprocess.Popen(timed, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = threading.Event()
        interrupted = False

        def expire():
            if process.poll() is None:
                timed_out.set()
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # A blocking wait avoids wait(timeout)'s exponential polling delays in
        # short complete jobs. The watchdog never samples output directories.
        watchdog = threading.Timer(timeout, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            exit_code = process.wait()
        except KeyboardInterrupt:
            interrupted = True
            expire()
            exit_code = process.wait()
        finally:
            wall = (time.perf_counter_ns() - start) / 1e9
            watchdog.cancel()
            watchdog.join()
    result = dict(exit_code=exit_code, timed_out=timed_out.is_set(), interrupted=interrupted, wall_seconds=wall,
                  clock='GNU-time wrapper launch through wait/CLI exit, includes publication and product cleanup')
    save(attempt / 'process.json', result)
    lines = (attempt / 'time.txt').read_text().splitlines()
    result['process_usage'] = json.loads(lines[-1]) if lines else None
    if not lines:
        result['process_usage_unavailable'] = 'GNU time was interrupted before writing its record'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for variant in ('baseline', 'candidate'):
        parser.add_argument('--' + variant, type=Path, required=True)
        parser.add_argument('--' + variant + '-provenance', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='must not exist')
    parser.add_argument('--output', type=Path, required=True, help='exclusive JSONL')
    parser.add_argument('--recipes', nargs='+', choices=tuple(verify.recipes()), required=True)
    parser.add_argument('--timeout', type=float, default=120, help='seconds per process; failures stop the batch')
    parser.add_argument('--cache-context', required=True, help='actual cache policy; never implies cold cache')
    parser.add_argument('--storage-context', required=True, help='actual filesystem/device/WSL context')
    args = parser.parse_args()
    verify.require(len(args.recipes) == len(set(args.recipes)), 'duplicate recipe')
    verify.require(math.isfinite(args.timeout) and args.timeout > 0, 'timeout must be positive and finite')
    verify.require(sys.platform == 'linux' and Path('/usr/bin/time').is_file(), 'Linux GNU time required')
    work = args.work.absolute()
    output = args.output.absolute()
    verify.require(not os.path.lexists(work), 'work must be fresh')
    verify.require(not os.path.lexists(output), 'output must not exist')
    binaries = {v: getattr(args, v).resolve(strict=True) for v in ('baseline', 'candidate')}
    # Fresh work contains only owned attempts/fixtures; never clean arbitrary paths.
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as raw:
        def emit(value):
            raw.write(json.dumps(value, sort_keys=True) + '\n')
            raw.flush()
            os.fsync(raw.fileno())
        identities = {}
        code_hashes = {str(p): verify.sha(p) for p in (Path(__file__), Path(verify.__file__))}
        emit(dict(kind='start', schema='shuffle-swarm-v1', work=str(work), recipes=args.recipes,
                  warmups=1, repetitions=3, cache_context=args.cache_context,
                  storage_context=args.storage_context, timeout_seconds=args.timeout,
                  harness_sha256=verify.sha(__file__), verifier_sha256=verify.sha(verify.__file__),
                  platform=platform.platform(), python=sys.version, executable=sys.executable,
                  cpu_count=os.cpu_count(), affinity=sorted(os.sched_getaffinity(0)),
                  disk_free_bytes=shutil.disk_usage(work).free,
                  environment_sha256=__import__('hashlib').sha256(
                      json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest(),
                  environment_values={k: os.environ.get(k) for k in ('LANG', 'LC_ALL', 'TZ')},
                  timing='complete CLI job; fixture/config/hash/verification/receipt/output cleanup outside clock',
                  io_scope='GNU time filesystem counters are OS counters; no device throughput claim',
                  analysis_scope='Analysis temp/diagnostics are pre-publication, not whole-job I/O'))
        try:
            for variant in binaries:
                identities[variant] = provenance(binaries[variant], getattr(args, variant + '_provenance'),
                                                  work / (variant + '-build'), candidate=variant == 'candidate')
            emit(dict(kind='builds', variants=identities))
            for name in args.recipes:
                recipe = verify.recipes()[name]
                cell = work / name
                cell.mkdir()
                fixture = cell / 'input.csv'
                verify.fixture(fixture, recipe)
                fixture_hash = verify.sha(fixture)
                save(cell / 'recipe.json', recipe)
                emit(dict(kind='fixture', recipe=recipe, path=str(fixture), sha256=fixture_hash,
                          bytes=fixture.stat().st_size, generator_sha256=verify.sha(verify.__file__)))
                elapsed = {v: [] for v in binaries}
                for repetition in range(-1, 3):
                    for variant in order(repetition):
                        attempt = cell / f'{repetition + 1}-{variant}'
                        attempt.mkdir()
                        destination = attempt / 'output'
                        verify.require(not os.path.lexists(destination), 'existing destination rejected')
                        job = make_job(recipe, fixture, destination)
                        temporary = attempt / 'temporary'
                        temporary.mkdir()
                        config = attempt / 'job.json'
                        save(config, job)
                        sample = dict(kind='sample', recipe=name, variant=variant, repetition=repetition,
                                      warmup=repetition == -1, attempt=str(attempt), exit_code=None,
                                      config_sha256=verify.sha(config),
                                      fixture_sha256=fixture_hash, binary_before_sha256=verify.sha(binaries[variant]))
                        emit(dict(sample, kind='attempt-start'))
                        try:
                            verify.require(sample['binary_before_sha256'] == identities[variant]['binary_sha256'],
                                           'binary changed before invocation')
                            sample.update(run_process([str(binaries[variant]), 'run', '--config', str(config), '--yes'],
                                                      attempt, args.timeout))
                            verify.require(sample['exit_code'] == 0 and not sample['timed_out'], 'process failed/timed out')
                            analysis = json.loads((attempt / 'stdout').read_text())
                            receipt = verify.verify(destination, recipe, job, analysis)
                            verify.require(not any(temporary.iterdir()), 'product temporary cleanup incomplete')
                            exclusive_copy(destination / 'manifest.jsonl', attempt / 'manifest.jsonl')
                            save(attempt / 'verification.json', receipt)
                            sample['verification_sha256'] = verify.sha(attempt / 'verification.json')
                            sample['binary_after_sha256'] = verify.sha(binaries[variant])
                            verify.require(sample['binary_after_sha256'] == sample['binary_before_sha256'], 'binary changed during job')
                            verify.require(verify.sha(fixture) == fixture_hash, 'fixture changed')
                            sample.update(verified=True, product_temp_cleanup_verified=True, analysis_temp_bytes=analysis['temp_bytes'],
                                          analysis_peak_temp_bytes=analysis['peak_temp_bytes'],
                                          analysis_diagnostics=analysis['diagnostics'])
                            # Receipt and manifest are durable before any successful output removal.
                            emit(dict(sample, kind='verified-before-cleanup'))
                            shutil.rmtree(destination)
                            sample['output_cleanup'] = 'successful output only, after receipt, outside process clock'
                            emit(sample)
                            if repetition >= 0:
                                elapsed[variant].append(sample['wall_seconds'])
                        except BaseException as error:
                            sample.update(kind='failure', exception=repr(error), traceback=traceback.format_exc(),
                                          binary_after_sha256=(verify.sha(binaries[variant]) if binaries[variant].is_file() else None),
                                          output_preserved=destination.exists())
                            save(attempt / 'failure.json', sample)
                            emit(sample)
                            raise
                emit(dict(kind='summary', recipe=name, wall_seconds={v: dict(median=statistics.median(t),
                          min=min(t), max=max(t), samples=t) for v, t in elapsed.items()}))
            for path, digest in code_hashes.items():
                verify.require(verify.sha(path) == digest, 'harness/verifier changed during batch')
            emit(dict(kind='complete', binary_after_sha256={v: verify.sha(p) for v, p in binaries.items()}))
        except BaseException as error:
            emit(dict(kind='batch-failure', exception=repr(error), traceback=traceback.format_exc()))
            raise


if __name__ == '__main__':
    main()
