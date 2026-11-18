"""A/B compact resident consumers on complete many-column shuffle/group jobs.

Alternates native builds, verifies output bytes/order, names, lineage, stages and
logical digests. Optional allocation-profile examples count whole-job allocations.
Requires GNU time. Warm uncontrolled storage; not a storage/scale certificate.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--before-allocator', type=Path)
    parser.add_argument('--after-allocator', type=Path)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--rows', type=int, default=300000)
    parser.add_argument('--cases', nargs='+', choices=['catalog_pipeline', 'catalog_wide', 'plain', 'plain_wide', 'streaming_pipeline', 'streaming_pipeline_sort', 'interleaved_pipeline', 'streaming_pipeline_wide', 'fused_balanced_pipeline_wide', 'fused_balanced_spill', 'fused_balanced_wide', 'probabilistic_route', 'balanced_terminal', 'balanced_terminal_wide', 'uniform_pipeline', 'uniform_pipeline_spill', 'uniform_pipeline_wide', 'fisher_pipeline', 'resident', 'pipeline', 'fisher', 'spill', 'rare_wide', 'partition', 'partition_shuffle', 'assign', 'assign_shuffle', 'partition_spill', 'partition_wide', 'probabilistic_sort', 'assign_pipeline', 'partition_pipeline', 'partition_pipeline_wide', 'assign_pipeline_spill', 'stratified_assign_shuffle', 'stratified_assign_pipeline_spill'], default=['resident', 'pipeline', 'fisher', 'spill', 'rare_wide'])
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--output-encoding', help='override output encoding for serializer accounting experiments')
    parser.add_argument('--output-bom', action='store_true')
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1:
        parser.error('need at least 1000 rows and positive repeats')
    if bool(args.before_allocator) != bool(args.after_allocator) or min(args.workers) < 1:
        parser.error('provide both allocators and positive workers')
    timer = shutil.which('time')
    if not timer:
        parser.error('GNU time is required for per-process CPU and peak RSS')
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    print(json.dumps({'type': 'environment', 'platform': platform.platform(), 'rows': args.rows,
                      'cpu': next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                                   if line.startswith('model name')), 'unknown'),
                      'workers': args.workers, 'repeats': args.repeats, 'cache': 'warm, uncontrolled',
                      'output_encoding': args.output_encoding or 'utf-8', 'output_bom': args.output_bom,
                      'binary_sha256': {k: hashlib.sha256(v.read_bytes()).hexdigest()
                                        for k, v in [('before', args.before), ('after', args.after),
                                                     ('before_allocator', args.before_allocator),
                                                     ('after_allocator', args.after_allocator)] if v}}), flush=True)
    with tempfile.TemporaryDirectory(prefix='chopper-compact-', dir=args.work_dir) as directory:
        root = Path(directory)
        for case in args.cases:
            source = root / 'input.csv'
            columns = 32
            with source.open('w') as output:
                output.write(','.join(['id'] + [f'c{i}' for i in range(columns)]) + '\n')
                for row in range(args.rows):
                    fields = [str(row)] + [str((row + col) % 10) for col in range(columns)]
                    if case in ['plain_wide', 'streaming_pipeline_wide', 'rare_wide', 'partition_wide', 'partition_pipeline_wide', 'uniform_pipeline_wide', 'balanced_terminal_wide', 'fused_balanced_wide', 'fused_balanced_pipeline_wide'] and row == 0:
                        fields[2 if case == 'balanced_terminal_wide' else 1] = 'x' * 1800000
                    if case.startswith('catalog_'):
                        fields[1] = ('界' * 512 if case == 'catalog_wide' else 'group-') + str(row % 256)
                    output.write(','.join(fields) + '\n')
            job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'compact-v1',
                   'operations': ([{'type': 'shuffle', 'strategy': 'fisher_yates' if case == 'fisher' else 'uniform'}]
                                  + ([{'type': 'balanced', 'files': 4}, {'type': 'partition', 'columns': ['c0']}] if case == 'pipeline' else [])),
                   'resources': {'memory_mb': 32 if case in ['spill', 'rare_wide'] else 1024,
                                 'workers': 1, 'max_record_bytes': 2097152, 'temp_dir': str(root)}}
            if case.startswith('catalog_'):
                job['operations'] = [{'type': 'balanced', 'files': 2},
                                     {'type': 'partition', 'columns': ['c0']},
                                     {'type': 'shuffle', 'strategy': 'uniform'}]
            if args.output_encoding or args.output_bom:
                job['output_csv'] = {'encoding': args.output_encoding or 'utf-8', 'bom': args.output_bom}
            if case in ['plain', 'plain_wide']:
                job['operations'] = []
            partition = {'type': 'partition', 'columns': ['c2', 'c0']}
            assignment = {'type': 'assign', 'groups': [
                {'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}]}
            if case.startswith('fused_balanced'):
                job['operations'].append({'type': 'balanced', 'files': 4})
                job['resources']['memory_mb'] = 32
            if case == 'fused_balanced_pipeline_wide':
                job['operations'].insert(0, {'type': 'balanced', 'files': 1})
            if case == 'probabilistic_route':
                job['operations'] = [{**assignment, 'type': 'assign_probabilistic'}]
            if case.startswith('partition'):
                job['operations'] = [partition]
            elif case.startswith('assign'):
                job['operations'] = [assignment]
            elif case == 'probabilistic_sort':
                job['operations'] = [{**assignment, 'type': 'assign_probabilistic'}]
                job['resources']['grouping'] = 'sort'
            if case in ['partition_shuffle', 'assign_shuffle']:
                job['operations'].append({'type': 'shuffle', 'strategy': 'uniform'})
            if case in ['partition_spill', 'partition_wide']:
                job['resources']['memory_mb'] = 32
            if case.startswith('assign_pipeline') or case.startswith('partition_pipeline'):
                operation = assignment if case.startswith('assign') else partition
                job['operations'] = [{'type': 'balanced', 'files': 2}, operation,
                                     {'type': 'shuffle', 'strategy': 'uniform'}]
                if case.endswith(('spill', 'wide')):
                    job['resources']['memory_mb'] = 32
            if case.startswith('stratified_assign'):
                job['operations'] = [{**assignment, 'strata': ['c2', 'c0']},
                                     {'type': 'shuffle', 'strategy': 'uniform'}]
                if case.endswith('spill'):
                    job['operations'].insert(0, {'type': 'balanced', 'files': 2})
                    job['resources']['memory_mb'] = 32
            if case.startswith(('uniform_pipeline', 'fisher_pipeline')):
                job['operations'] = [
                    {'type': 'balanced', 'files': 2},
                    {'type': 'shuffle', 'strategy': 'fisher_yates' if case == 'fisher_pipeline' else 'uniform'}]
                if case.endswith(('spill', 'wide')):
                    job['resources']['memory_mb'] = 32
            if case.startswith('balanced_terminal'):
                job['operations'] = [partition, {'type': 'balanced', 'files': 2}]
                if case.endswith('wide'):
                    job['resources']['memory_mb'] = 32
            if case.startswith('streaming_pipeline') or case == 'interleaved_pipeline':
                membership = ({'type': 'interleaved', 'files': 3} if case == 'interleaved_pipeline'
                              else {**assignment, 'type': 'assign_probabilistic', 'strata': ['c2', 'c0']})
                job['operations'] = [{'type': 'balanced', 'files': 2}, membership,
                                     {'type': 'shuffle', 'strategy': 'uniform'}]
                job['resources']['memory_mb'] = 32
                if case == 'streaming_pipeline_sort':
                    job['resources']['grouping'] = 'sort'
            for workers in args.workers:
                config = root / 'job.json'
                job['resources']['workers'] = workers
                config.write_text(json.dumps(job))
                reference = None
                measures = {'before': [], 'after': []}
                for repeat in range(args.repeats):
                    builds = [('before', args.before), ('after', args.after)]
                    if repeat % 2:
                        builds.reverse()
                    for label, binary in builds:
                        stats = root / 'time.txt'
                        cmd = [timer, '-f', '%U %S %M', '-o', str(stats), str(binary.resolve()), 'run',
                               '--config', str(config), '--yes']
                        started = time.perf_counter()
                        try:
                            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                        except subprocess.CalledProcessError as error:
                            raise RuntimeError(f'{case}/{label}: {error.stderr}') from error
                        elapsed = time.perf_counter() - started
                        user, system, rss = map(float, stats.read_text().split())
                        analysis = json.loads(result.stdout)
                        actual = pipelines.fingerprint(root / 'output', analysis, 'none')
                        shutil.rmtree(root / 'output')
                        if reference is None:
                            reference = actual
                        assert actual == reference, f'{case}/{label}: changed output'
                        measures[label].append(elapsed)
                        print(json.dumps({'type': 'measurement', 'case': case, 'workers': workers, 'build': label, 'repeat': repeat + 1,
                                          'seconds': elapsed, 'cpu_seconds': user + system, 'peak_rss_kib': int(rss),
                                          'diagnostics': analysis.get('diagnostics'), 'timings': analysis.get('timings'),
                                          'peak_temp_bytes': analysis.get('peak_temp_bytes'), 'verified': True}), flush=True)
                print(json.dumps({'type': 'summary', 'case': case, 'workers': workers,
                                  'median_seconds': {k: statistics.median(v) for k, v in measures.items()},
                                  'range_seconds': {k: [min(v), max(v)] for k, v in measures.items()},
                                  'verified': True}), flush=True)
                if args.before_allocator:
                    for label, binary in [('before', args.before_allocator), ('after', args.after_allocator)]:
                        result = subprocess.run([str(binary.resolve()), str(config)], capture_output=True,
                                                text=True, check=True, timeout=300)
                        profile = json.loads(result.stdout)
                        assert pipelines.fingerprint(root / 'output', profile['analysis'], 'none') == reference
                        shutil.rmtree(root / 'output')
                        print(json.dumps({'type': 'allocation', 'case': case, 'workers': workers,
                                          'build': label, 'profile': profile['allocation_profile'],
                                          'verified': True}), flush=True)



if __name__ == '__main__':
    main()
