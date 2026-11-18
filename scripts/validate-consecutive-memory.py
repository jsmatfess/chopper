"""Configured shared-admission controls for complete consecutive-partition jobs.

These are capacity-ledger boundaries, not OS/cgroup/RSS pressure experiments.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--rows', type=int, default=100001)
    args = parser.parse_args()
    assert args.rows >= 1000
    csv.field_size_limit(2097152)
    harness_path = Path(__file__).with_name('benchmark-external-shuffle.py')
    spec = importlib.util.spec_from_file_location('external', harness_path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    env = os.environ.copy()
    env.pop('CHOPPER_MEMORY_LIMIT_MB', None)
    print(json.dumps({'type': 'environment', 'rows': args.rows, 'memory_mb': 32, 'workers': 4,
                      'caps_mib': [1, 2, 4, 8, 16], 'scope': __doc__,
                      'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'binary_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in binaries.items()}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-consecutive-memory-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / name for name in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        for shape in ['independent', 'independent_wide']:
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['id', 'payload'] + [f'c{i}' for i in range(31)])
                writer.writerows(harness.fields(i, shape) for i in range(args.rows))
            for case in ['consecutive', 'consecutive_downstream']:
                job = {'input': str(source), 'output': str(output), 'seed': 'external-comparison-v1',
                       'operations': harness.operations_for(case, shape, 4),
                       'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152, 'temp_dir': str(temp)}}
                config.write_text(json.dumps(job))
                reference = None
                for cap in [None, 1, 2, 4, 8, 16]:
                    run_env = env.copy()
                    if cap is not None:
                        run_env['CHOPPER_MEMORY_LIMIT_MB'] = str(cap)
                    for variant, binary in binaries.items():
                        result = subprocess.run([str(binary), 'run', '--config', str(config), '--yes'],
                                                env=run_env, text=True, capture_output=True, timeout=300)
                        assert not list(temp.iterdir()), 'temporary leak'
                        record = {'type': 'control', 'shape': shape, 'case': case, 'variant': variant, 'cap_mib': cap, 'verified': True}
                        if result.returncode:
                            assert cap is not None and not output.exists(), result.stderr
                            assert any(term in result.stderr.lower() for term in ['memory', 'admission']), result.stderr
                            record.update(outcome='clean rejection', error=result.stderr.strip())
                        else:
                            analysis = json.loads(result.stdout)
                            fingerprint = harness.verify(output, analysis, shape, args.rows, case, 4)
                            if reference is not None:
                                assert fingerprint == reference, 'capacity changed logical output'
                            reference = fingerprint
                            record.update(outcome='success', fingerprint=fingerprint, diagnostics=analysis['diagnostics'])
                            shutil.rmtree(output)
                        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
