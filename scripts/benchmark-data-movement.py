#!/usr/bin/env python3
"""Paired complete-job CSV data-movement comparison; native timing and independent CSV checks."""
import argparse
import csv
import re
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time
import threading
import signal

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify', ROOT / 'scripts/verify-shuffle-swarm.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def recipes():
    fy = dict(type='shuffle', strategy='fisher_yates')
    balanced = dict(type='balanced', files=8)
    return [dict(name=name, rows=rows, payload_bytes=payload, wide=wide, memory_mb=memory, operations=ops)
            for name, rows, payload, wide, memory, ops in [
                ('fy-balanced-root',524291,237,False,4096,[fy,balanced]),
                ('fy-balanced-retained',524291,237,False,4096,[dict(type='balanced',files=4),fy,balanced]),
                ('uniform-balanced-control',524291,237,False,4096,[dict(type='shuffle',strategy='uniform'),balanced]),
                ('fy-balanced-wide',240003,192,True,4096,[fy,balanced]),
                ('plain-balanced-small',524291,237,False,4096,[balanced]),
                ('plain-balanced-large',8388611,237,False,256,[balanced]),
                ('plain-balanced-wide',240003,192,True,4096,[balanced]),
                ('plain-balanced-auto-small',524291,237,False,4096,[balanced]),
                ('plain-balanced-eight-large',8388611,237,False,256,[balanced])]]


def check(recipe, destination, analysis, job):
    if recipe['operations'] != [dict(type='balanced', files=8)]:
        return verify.verify(destination, recipe, job, analysis)
    destination = Path(destination)
    require = verify.require
    require(destination.is_dir() and not destination.is_symlink(), 'missing/unsafe destination')
    manifest = destination / 'manifest.jsonl'
    require(manifest.is_file() and not manifest.is_symlink(), 'missing/unsafe manifest')
    records = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines()]
    require(len(records) == 9 and records[0]['type'] == 'job' and records[0]['schema_version'] == 1,
            'manifest job/output count mismatch')
    require(records[0]['analysis'] == analysis and verify.matches_config(records[0]['config'], job),
            'manifest job mismatch')
    n = recipe['rows']
    requested = job['resources']['workers']
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count()
    workers = requested or min(cpus, 4, max(job['resources']['memory_mb'] // 64, 1))
    require(analysis['workers'] == workers and
            analysis['memory_budget_bytes'] == job['resources']['memory_mb'] * 1024**2,
            'effective resources mismatch')
    require(analysis['rows'] == n and analysis['columns'] == len(verify.header(recipe)) and
            analysis['header'] == verify.header(recipe) and analysis['groups'] == 8,
            'input/group statistics mismatch')
    require(analysis['stages'] == [dict(operation=1, input_groups=1, output_groups=8,
            smallest_group=n//8, largest_group=(n+7)//8, empty_groups=0)], 'stage statistics mismatch')
    paths = set()
    receipts = []
    identity = 0
    total = 0
    for part, entry in enumerate(records[1:]):
        name = entry['path']
        require(re.fullmatch(r'[A-Za-z0-9_.-]+[.]csv', name) is not None and name not in paths,
                'unsafe/duplicate output path')
        paths.add(name)
        path = destination / name
        require(path.is_file() and not path.is_symlink(), 'missing/unsafe output')
        size = path.stat().st_size
        require(entry['type'] == 'output' and size == entry['csv_bytes'] == entry['stored_bytes'] and
                entry['compressed_target_exceeded'] is False, 'output metadata mismatch')
        require(job['limits'].get('bytes') is None or size <= job['limits']['bytes'], 'CSV byte cap')
        require(entry['lineage'] == [dict(operation=0, part=part+1)], 'lineage/order mismatch')
        quota = n//8 + (part < n%8)
        rows = 0
        with path.open(newline='', encoding='utf-8') as stream:
            reader = csv.reader(stream, strict=True)
            require(next(reader) == verify.header(recipe), 'CSV header mismatch')
            for row in reader:
                require(row == verify.fields(recipe, identity), 'field/ID/conservation/encounter-order mismatch')
                identity += 1
                rows += 1
        require(rows == quota == entry['rows'], 'balanced quota mismatch')
        require(job['limits'].get('rows') is None or rows <= job['limits']['rows'], 'row cap')
        receipts.append(dict(path=name, rows=rows, bytes=size, sha256=verify.sha(path)))
        total += size
    require(identity == n and analysis['output_files'] == 8 and analysis['output_csv_bytes'] == total,
            'final conservation/count/byte mismatch')
    require({p.name for p in destination.iterdir()} == paths | {'manifest.jsonl'}, 'unlisted output')
    return dict(verified=True, rows=n, groups=8, output_files=receipts,
                output_csv_bytes=total, manifest_sha256=verify.sha(manifest),
                exact_encounter_order=True, verifier_sha256=verify.sha(__file__))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--case', choices=[r['name'] for r in recipes()], required=True)
    parser.add_argument('--rows', type=int)
    args = parser.parse_args()
    assert 3 <= args.repeats <= 9
    work = args.output.resolve(); work.mkdir()
    binaries = {name: path.resolve(strict=True) for name, path in [('baseline', args.baseline), ('candidate', args.candidate)]}
    save(work / 'environment.json', dict(platform=platform.platform(), processor=platform.processor(),
         cpu_count=os.cpu_count(), harness_sha256=verify.sha(__file__), verifier_sha256=verify.sha(verify.__file__),
         binaries={name: dict(path=str(path), sha256=verify.sha(path)) for name, path in binaries.items()},
         clock='GNU-time launch to CLI exit, including publication and product cleanup; verification outside clock',
         caches='warm uncontrolled WSL2/ext4; not native Windows or physical-device I/O', features=[]))
    summary = []
    for recipe in recipes():
        if args.case and args.case != recipe['name']: continue
        if args.rows:
            assert 100 <= args.rows <= 10000000
            recipe={**recipe,'rows':args.rows}
        cell = work / recipe['name']; cell.mkdir()
        fixture = cell / 'input.csv'; verify.fixture(fixture, recipe)
        save(cell / 'fixture.json', dict(recipe=recipe, sha256=verify.sha(fixture), bytes=fixture.stat().st_size))
        samples = {name: [] for name in binaries}
        for repeat in range(-1, args.repeats):
            for variant in (('baseline', 'candidate') if repeat % 2 == 0 else ('candidate', 'baseline')):
                attempt = cell / f'{repeat+1}-{variant}'; attempt.mkdir()
                destination = attempt / 'results'
                (attempt / 'temporary').mkdir()
                job = dict(input=str(fixture), output=str(destination), operations=recipe['operations'],
                           resources=dict(memory_mb=recipe['memory_mb'], workers=(0 if recipe['name']=='plain-balanced-auto-small' else 8 if recipe['name']=='plain-balanced-eight-large' else 1), max_record_bytes=1048576,
                                          temp_dir=str(attempt / 'temporary')),
                           limits=dict(rows=2000000 if recipe['name'].startswith('plain-') else 200000,
                                       bytes=536870912 if recipe['name'].startswith('plain-') else 134217728))
                save(attempt / 'job.json', job)
                command = ['/usr/bin/time', '-o', str(attempt / 'time.json'), '-f',
                           '{"user_seconds":%U,"system_seconds":%S,"max_rss_kib":%M,"fs_inputs":%I,"fs_outputs":%O}',
                           str(binaries[variant]), 'run', '--config', str(attempt / 'job.json'), '--yes']
                with (attempt / 'stdout.json').open('xb') as out, (attempt / 'stderr.log').open('xb') as err:
                    start = time.perf_counter()
                    result = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
                    expired = threading.Event()
                    def stop():
                        expired.set()
                        try: os.killpg(result.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    timer = threading.Timer(120, stop); timer.start()
                    try: result.wait()
                    finally: timer.cancel(); timer.join()
                    elapsed = time.perf_counter() - start
                    assert not expired.is_set(), 'complete-job deadline exceeded'
                sample = dict(variant=variant, repeat=repeat, warmup=repeat < 0, seconds=elapsed, exit_code=result.returncode)
                save(attempt / 'process.json', sample)
                assert result.returncode == 0, str(attempt)
                analysis = json.loads((attempt / 'stdout.json').read_text())
                receipt = check(recipe, destination, analysis, job)
                save(attempt / 'verification.json', receipt)
                sample.update(json.loads((attempt / 'time.json').read_text()))
                sample['analysis'] = analysis
                sample['attempt'] = str(attempt)
                if repeat >= 0: samples[variant].append(sample)
                # Verified file hashes/metadata persist in receipts; successful payloads are disposable.
                shutil.rmtree(destination)
                assert not any((attempt / 'temporary').iterdir()), 'temporary files remain after CLI exit'
                print(json.dumps(dict(recipe=recipe['name'], **{k:v for k,v in sample.items() if k!='analysis'})), flush=True)
        stats = {name: dict(median=statistics.median(s['seconds'] for s in values),
                           minimum=min(s['seconds'] for s in values), maximum=max(s['seconds'] for s in values))
                 for name, values in samples.items()}
        summary.append(dict(recipe=recipe, samples=samples, stats=stats,
                            reduction_percent=100*(1-stats['candidate']['median']/stats['baseline']['median'])))
    save(work / 'summary.json', summary)


if __name__ == '__main__':
    main()
