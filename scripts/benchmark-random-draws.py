#!/usr/bin/env python3
"""Bounded complete-job random-draw comparison; native timing and independent CSV checks."""
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

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('verify', ROOT / 'scripts/verify-shuffle-swarm.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


def recipes():
    exact = dict(type='assign', groups=[dict(name=n, percent=str(w)) for n, w in zip(verify.NAMES, verify.WEIGHTS)])
    return [dict(name=name, rows=rows, payload_bytes=payload, wide=False, memory_mb=memory, operations=operations)
            for name, rows, payload, memory, operations in [
                ('fy-fit', 120003, 64, 256, [dict(type='shuffle', strategy='fisher_yates')]),
                ('exact-draws', 150003, 192, 32, [exact]),
                ('uniform-spill', 250003, 192, 32, [dict(type='shuffle', strategy='uniform')]),
                ('direct-control', 250003, 192, 32, []),
                ('probability-control', 250003, 192, 32, [dict(type='assign_probabilistic',groups=[dict(name='treatment',percent='80'),dict(name='control',percent='20'),dict(name='zero',percent='0')])])]]


def check(recipe, destination, analysis, job):
    if recipe['name'] != 'probability-control':
        return verify.verify(destination, recipe, job, analysis)
    destination = Path(destination)
    manifest = destination / 'manifest.jsonl'
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert records[0]['type']=='job' and records[0]['analysis']==analysis
    assert verify.matches_config(records[0]['config'], job)
    counts = dict(treatment=0,control=0,zero=0)
    last = dict.fromkeys(counts,-1)
    seen = set(); receipts = []; total = 0; paths = set(); group_order = []
    for entry in records[1:]:
        name = entry['path']; assert re.fullmatch(r'[A-Za-z0-9_.-]+[.]csv',name) and name not in paths
        paths.add(name); path=destination/name
        assert entry['type']=='output' and not path.is_symlink()
        size=path.stat().st_size
        assert size==entry['csv_bytes']==entry['stored_bytes'] and size<=job['limits']['bytes']
        label=entry['lineage'][0]['allocation']; assert label in counts
        assert entry['lineage']==[dict(operation=0,allocation=label)]
        if not group_order or group_order[-1]!=label: group_order.append(label)
        n=0
        with path.open(newline='',encoding='utf-8') as f:
            reader=csv.reader(f,strict=True); assert next(reader)==verify.header(recipe)
            for row in reader:
                identity=int(row[0]); assert 0<=identity<recipe['rows'] and identity not in seen
                assert row==verify.fields(recipe,identity) and identity>last[label]
                last[label]=identity;seen.add(identity);counts[label]+=1;n+=1
        assert n==entry['rows'] and n<=job['limits']['rows']
        total+=size;receipts.append(dict(path=name,rows=n,bytes=size,sha256=verify.sha(path)))
    assert group_order==list(counts) and counts['zero']==0
    assert seen==set(range(recipe['rows']))
    assert analysis['rows']==recipe['rows'] and analysis['groups']==3 and len(receipts)==analysis['output_files']
    assert total==analysis['output_csv_bytes'] and {p.name for p in destination.iterdir()}==paths|{'manifest.jsonl'}
    return dict(verified=True,rows=len(seen),counts=counts,output_files=receipts,
                output_csv_bytes=total,manifest_sha256=verify.sha(manifest),verifier_sha256=verify.sha(__file__))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--case', choices=[r['name'] for r in recipes()])
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
            assert recipe['name']=='direct-control' and 100 <= args.rows <= 1000000
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
                           resources=dict(memory_mb=recipe['memory_mb'], workers=1, max_record_bytes=1048576,
                                          temp_dir=str(attempt / 'temporary')),
                           limits=dict(rows=10000, bytes=4194304))
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
