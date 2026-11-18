"""Bounded Windows E4 complete-job comparison; explicit options, no selectors.

Run from the repo root with --binary, --work and --output (all fresh paths).
Raw command logs and failed outputs stay in --work. Counts are stored once per
shape/seed/variant; repeated counts must match their retained hash exactly.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ('small_unstratified', 4000, 1, 50, False),
    ('small_strata_rare', 4000, 1000, 1, True),
    ('skew', 60000, 3, 20, True),
    ('larger_strata', 200000, 1000, 80, True),
]
SEEDS = ['e4-panel-1', 'e4-panel-2', 'e4-panel-3']
CAP = 262144

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def key(case, index, rows, strata):
    if case == 'skew':
        return 'heavy' if index < rows * 90 // 100 else 'medium' if index < rows * 99 // 100 else 'rare'
    return str(index % strata)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['binary', 'work', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assert platform.system() == 'Windows', 'this pass pins Win32 process counters'
    assert not args.work.exists() and not args.output.exists(), 'refuse overwrite'
    args.work.mkdir(parents=True)
    binary = args.binary.resolve()
    spec = importlib.util.spec_from_file_location('win_counters', ROOT / 'scripts/benchmark-windows.py')
    counters = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(counters)
    started_batch = time.monotonic()
    with args.output.open('x', encoding='utf-8', newline='\n') as raw:
        def emit(record):
            raw.write(json.dumps(record, separators=(',', ':')) + '\n')
            raw.flush()
        emit({'type': 'design', 'cases': CASES, 'seeds': SEEDS, 'repeats': 2,
              'jobs': 48, 'job_timeout_seconds': 60, 'batch_ceiling_seconds': 720,
              'stop': 'first failure; no expansion; no universal savings/deviation threshold',
              'scope': 'CLI startup, decoding, prepare and publication; no optional profile; verification excluded',
              'cache': 'warm uncontrolled Windows filesystem; alternating exact/probabilistic',
              'binary_sha256': sha(binary), 'harness_sha256': sha(__file__),
              'counter_harness_sha256': sha(ROOT / 'scripts/benchmark-windows.py'),
              'source_proof_sha256': sha(ROOT / '.tools/todo-auto-20261028/final-source-identities.json'),
              'platform': platform.platform(), 'python': platform.python_version(),
              'features': [], 'memory_mb': 32, 'workers': 1, 'csv_byte_cap': CAP,
              'count_columns': ['input_rows', 'treatment', 'control', 'treatment_deviation_times100', 'control_deviation_times100', 'empty_treatment', 'empty_control'],
              'resource_scope': 'peak working set from Win32; logical temp counters and process transfer bytes are not physical device IO or complete RSS accounting'})
        for case, rows, strata, percent, stratified in CASES:
            folder = args.work / case
            folder.mkdir()
            source = folder / 'input.csv'
            with source.open('w', encoding='utf-8', newline='') as stream:
                stream.write('id,stratum,payload\n')
                for index in range(rows):
                    stream.write(f'{index},{key(case,index,rows,strata)},{"x"*64}\n')
            emit({'type': 'fixture', 'case': case, 'rows': rows, 'strata': strata,
                  'percent': percent, 'stratified': stratified, 'bytes': source.stat().st_size,
                  'sha256': sha(source)})
            reference = {}
            digest = None
            samples = {'exact': [], 'probabilistic': []}
            for seed_index, seed in enumerate(SEEDS):
                for repeat in range(2):
                    versions = ['exact', 'probabilistic']
                    if (seed_index + repeat) % 2:
                        versions.reverse()
                    for variant in versions:
                        assert time.monotonic() - started_batch < 720, 'whole-batch deadline'
                        run_id = f'{seed_index+1}-{repeat+1}-{variant}'
                        output = folder / ('output-' + run_id)
                        temp = folder / ('temp-' + run_id)
                        temp.mkdir()
                        groups = [{'name': 'treatment', 'percent': str(percent)},
                                  {'name': 'control', 'percent': str(100-percent)}]
                        job = {'input': str(source.resolve()), 'output': str(output.resolve()),
                               'seed': seed, 'operations': [{'type': 'assign' if variant == 'exact' else 'assign_probabilistic',
                               'groups': groups, 'strata': ['stratum'] if stratified else []}],
                               'limits': {'bytes': CAP}, 'resources': {'memory_mb': 32, 'workers': 1,
                               'max_record_bytes': 1048576, 'temp_dir': str(temp.resolve()), 'temp_bytes': 536870912}}
                        config = folder / (run_id + '.json')
                        config.write_text(json.dumps(job), encoding='utf-8')
                        command = [str(binary), 'run', '--config', str(config.resolve()), '--yes']
                        with (folder / (run_id + '.stdout')).open('wb') as stdout, (folder / (run_id + '.stderr')).open('wb') as stderr:
                            started = time.perf_counter()
                            process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                            try:
                                code = process.wait(timeout=60)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                                emit({'type': 'failure', 'case': case, 'run': run_id, 'timeout': True})
                                raise
                            seconds = time.perf_counter() - started
                            usage = counters.counters(process)
                        if code:
                            emit({'type': 'failure', 'case': case, 'run': run_id, 'exit_code': code, 'seconds': seconds})
                            raise RuntimeError('CLI failed; retained ' + str(folder))
                        analysis = json.loads((folder / (run_id + '.stdout')).read_text(encoding='utf-8'))
                        entries = [json.loads(line) for line in (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
                        assert entries[0]['config']['seed'] == seed and analysis['rows'] == rows
                        assert entries[0]['analysis']['logical_digest'] == analysis['logical_digest']
                        if digest is None:
                            digest = analysis['logical_digest']
                        assert analysis['logical_digest'] == digest
                        seen = bytearray(rows)
                        counts = {}
                        previous_by_group = {}
                        fingerprint = []
                        for entry in entries[1:]:
                            assert entry['type'] == 'output'
                            group = entry['lineage'][0]['allocation']
                            destination = 0 if group == 'treatment' else 1
                            assert group in ['treatment', 'control']
                            path = output / entry['path']
                            assert path.stat().st_size == entry['csv_bytes'] <= CAP
                            previous, count = previous_by_group.get(group, -1), 0
                            with path.open(encoding='utf-8', newline='') as stream:
                                reader = csv.reader(stream)
                                assert next(reader) == ['id', 'stratum', 'payload']
                                for row in reader:
                                    index = int(row[0])
                                    assert 0 <= index < rows and not seen[index] and index > previous
                                    assert row == [str(index), key(case,index,rows,strata), 'x'*64]
                                    seen[index] = 1
                                    previous = index
                                    stratum = row[1] if stratified else 'all'
                                    counts.setdefault(stratum, [0, 0])[destination] += 1
                                    count += 1
                            assert count == entry['rows']
                            previous_by_group[group] = previous
                            fingerprint.append([entry['path'], sha(path)])
                        assert sum(seen) == rows and not any(temp.iterdir()), 'conservation or temporary cleanup'
                        deviations = {}
                        for stratum, (treatment, control) in sorted(counts.items()):
                            n = treatment + control
                            if variant == 'exact':
                                expected = n*percent//100 + int((n*percent)%100 >= (n*(100-percent))%100 and n*percent%100 != 0)
                                assert treatment == expected, (stratum, treatment, expected)
                            deviations[stratum] = [n,treatment,control,100*treatment-n*percent,100*control-n*(100-percent),int(treatment==0),int(control==0)]
                        count_hash = hashlib.sha256(json.dumps(deviations, sort_keys=True).encode()).hexdigest()
                        identity = (seed, variant)
                        if identity in reference:
                            assert reference[identity] == (fingerprint, count_hash), 'seeded replay changed'
                        reference[identity] = (fingerprint, count_hash)
                        emit({'type': 'measurement', 'case': case, 'seed': seed, 'repeat': repeat+1,
                              'variant': variant, 'seconds': seconds, **usage,
                              'analysis': analysis, 'config_sha256': sha(config),
                              'counts_sha256': count_hash, 'counts': deviations if repeat == 0 else None,
                              'counts_reference': None if repeat == 0 else {'seed': seed, 'repeat': 1, 'variant': variant},
                              'verified': True})
                        samples[variant].append(seconds)
                        shutil.rmtree(output)
                        temp.rmdir()
            emit({'type': 'summary', 'case': case, 'samples_per_variant': 6,
                  'median_seconds': {k:statistics.median(v) for k,v in samples.items()},
                  'range_seconds': {k:[min(v),max(v)] for k,v in samples.items()},
                  'timing_repetitions_nested_under_three_seeds': True})

if __name__ == '__main__':
    main()
