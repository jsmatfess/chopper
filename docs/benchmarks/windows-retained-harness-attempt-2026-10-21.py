"""Focused native Windows exact shuffle/partition calibration (no cache eviction).

Build/copy matching default and experimental-shuffle-partition binaries first.
Uses Win32 process counters; transfer bytes include cached I/O, not device I/O.
Fixture generation, verification and cleanup are outside the complete CLI clock.
Use --retained-parent to measure balanced(1) -> uniform -> partition(c0),
including charged bounded observations; legacy cells keep their ingestion path.
"""
import argparse
import csv
import ctypes as C
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inventory(root=Path('.')):
    """Include new compilation inputs as well as tracked dirty source files."""
    names = subprocess.check_output([
        'git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z',
        '--', 'crates', 'ui', 'Cargo.toml', 'Cargo.lock'], cwd=root).decode('utf-8').split('\0')
    return {name: sha(root / name) for name in sorted(set(names))
            if name and (root / name).is_file()}


def selected_cells(cells, transition_rows=None, retained_parent=False):
    available = {'resident': (3000, 'columns', 'shuffle_partition'),
                 'external': (300000, 'columns', 'shuffle_partition'),
                 'hierarchical': (1400000, 'columns', 'shuffle_partition'),
                 'skew': (300000, 'skew', 'shuffle_partition_key'),
                 'rare_wide': (300000, 'rare_wide', 'shuffle_partition')}
    selected = ({f'transition_{n}': (n, 'columns', 'shuffle_partition') for n in transition_rows}
                if transition_rows else {name: available[name] for name in cells})
    return {name: (rows, shape, 'parent_shuffle_partition' if retained_parent else case)
            for name, (rows, shape, case) in selected.items()}


def verify_retained_parent(analysis, variant, rows, external):
    assert variant in ('baseline', 'candidate')
    diagnostics = analysis['diagnostics']
    assert diagnostics['shuffle_partition_fusions'] == int(variant == 'candidate')
    assert diagnostics.get('shuffle_partition_retries') == 0
    audit = diagnostics.get('shuffle_partition_decisions')
    if variant == 'baseline':
        assert 'shuffle_partition_decisions' not in diagnostics, 'baseline must not expose candidate audit'
        return
    assert isinstance(audit, dict), 'candidate requires a retained-parent audit'
    external.audit_reserved_bytes(diagnostics)
    assert audit['initialized'] is True and audit['collection_denied'] is False
    assert audit['reserved_bytes'] > 0
    assert audit['completed_attempts'] == 1 and audit['omitted_attempts'] == 0
    assert len(audit['records']) == 1
    record = audit['records'][0]
    for key, value in {'shuffle_step': 1, 'partition_step': 2, 'parent_ordinal': 0,
                       'parent_offset': 0, 'parent_rows': rows,
                       'observation_complete': True, 'key_observation_complete': True,
                       'phase': 'emission', 'outcome': 'fused_committed',
                       'admission_denial': None, 'admission_denial_phase': None,
                       'terminal_admission_denial': None, 'cancelled': False,
                       'cleanup_failed': False}.items():
        assert record[key] == value, f'unexpected retained-parent {key}'
    assert record['shape']['rows_decoded'] == rows and record['shape']['rows_keyed'] == rows
    assert record['shape']['totals_saturated'] is False


def emit(record):
    print(json.dumps(record), flush=True)


def build_provenance(binaries, evidence):
    """Bind reused binaries to an explicit prior environment, never today's sources."""
    if evidence is None:
        return None
    with evidence.open(encoding='utf-8') as stream:
        record = json.loads(next(stream))
    if record.get('type') != 'environment':
        raise ValueError('build evidence must start with an environment record')
    actual = {name: sha(path) for name, path in binaries.items()}
    if actual != record.get('binary_sha256'):
        raise ValueError('binaries do not match the supplied build evidence')
    if record.get('features') != {'baseline': [], 'candidate': ['experimental-shuffle-partition']}:
        raise ValueError('build evidence has incompatible feature identities')
    if not record.get('source_sha256') or not record.get('harness_sha256'):
        raise ValueError('build evidence lacks source or harness identities')
    return {'source': str(evidence.resolve()), 'source_sha256': sha(evidence), 'line': 1,
            'binary_sha256': actual, 'build_source_sha256': record['source_sha256'],
            'build_features': record['features'], 'build_revision': record.get('revision'),
            'build_dirty_status': record.get('dirty_status'),
            'original_harness_sha256': record['harness_sha256']}


class Memory(C.Structure):
    _fields_ = [('cb', W.DWORD), ('faults', W.DWORD)] + [
        (name, C.c_size_t) for name in ('peak_ws', 'ws', 'peak_paged', 'paged',
                                      'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]


class IO(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in (
        'read_operations', 'write_operations', 'other_operations',
        'read_transfer_bytes', 'write_transfer_bytes', 'other_transfer_bytes')]


def counters(process):
    kernel = C.WinDLL('kernel32', use_last_error=True)
    psapi = C.WinDLL('psapi', use_last_error=True)
    handle = W.HANDLE(int(process._handle))
    creation, exit_time, user, system = (W.FILETIME() for _ in range(4))
    memory, io = Memory(), IO()
    memory.cb = C.sizeof(memory)
    for success in (kernel.GetProcessTimes(handle, C.byref(creation), C.byref(exit_time),
                                          C.byref(system), C.byref(user)),
                    psapi.GetProcessMemoryInfo(handle, C.byref(memory), C.sizeof(memory)),
                    kernel.GetProcessIoCounters(handle, C.byref(io))):
        if not success:
            raise C.WinError(C.get_last_error())
    ticks = lambda value: (value.dwHighDateTime << 32) | value.dwLowDateTime
    return {'cpu_seconds': (ticks(user) + ticks(system)) / 10_000_000,
            'peak_working_set_bytes': memory.peak_ws,
            'peak_pagefile_bytes': memory.peak_pagefile,
            'process_io': {name: getattr(io, name) for name, _ in IO._fields_}}


class Space:
    def __init__(self, root):
        self.root, self.stop = root, threading.Event()
        self.peak, self.samples = 0, 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        total = 0
        for directory, _, names in os.walk(self.root):
            for name in names:
                try:
                    total += (Path(directory) / name).stat().st_size
                except FileNotFoundError:
                    pass
        self.peak = max(self.peak, total)
        self.samples += 1

    def run(self):
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(.02)

    def finish(self):
        self.stop.set()
        self.thread.join()
        self.sample()
        return {'peak_logical_bytes': self.peak, 'samples': self.samples,
                'interval_seconds': .02,
                'scope': 'temp plus staging plus final outputs; excludes fixture/config/logs; sampled lower bound'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new UTF-8 JSONL artifact (refuses overwrite)')
    parser.add_argument('--hardware', type=Path, help='JSON from read-only Windows CIM/storage queries')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--build-evidence', type=Path,
                        help='prior JSONL environment pinning reused binaries and their build sources')
    parser.add_argument('--transition-rows', type=int, nargs='+',
                        help='replace fixed cells with narrow-column row counts around a spill transition')
    parser.add_argument('--retained-parent', action='store_true',
                        help='balanced(1) then uniform/partition; require complete charged parent audit')
    parser.add_argument('--cells', nargs='+', default=['resident', 'external', 'hierarchical', 'skew', 'rare_wide'],
                        choices=['resident', 'external', 'hierarchical', 'skew', 'rare_wide'])
    args = parser.parse_args()
    if os.name != 'nt' or args.repeats < 1 or (args.transition_rows and any(n < 1 for n in args.transition_rows)):
        parser.error('requires Windows, positive repeats and positive row counts')
    if args.transition_rows and len(set(args.transition_rows)) != len(args.transition_rows):
        parser.error('transition row counts must be distinct')
    binaries = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    provenance = build_provenance(binaries, args.build_evidence)
    sys.stdout = args.output.open('x', encoding='utf-8', buffering=1)
    spec = importlib.util.spec_from_file_location('external', Path(__file__).with_name('benchmark-external-shuffle.py'))
    external = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(external)
    csv.field_size_limit(2097152)
    sources = source_inventory()
    emit({'type': 'environment', 'platform': platform.platform(), 'python': platform.python_version(),
          'processor': platform.processor(), 'logical_processors': os.cpu_count(),
          'hardware': json.loads(args.hardware.read_text(encoding='utf-8-sig')) if args.hardware else None,
          'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
          'dirty_status': subprocess.check_output(['git', 'status', '--short'], text=True),
          'measurement_source_sha256': sources,
          'source_sha256': provenance['build_source_sha256'] if provenance else sources,
          'reused_build_provenance': provenance,
          'harness_sha256': {str(p): sha(p) for p in [Path(__file__), Path(external.__file__)]},
          'binary_sha256': {k: sha(p) for k, p in binaries.items()},
          'features': {'baseline': [], 'candidate': ['experimental-shuffle-partition']},
          'work_dir': str(args.work_dir.resolve()), 'free_bytes': shutil.disk_usage(args.work_dir).free,
          'cache': 'warm/uncontrolled; fixture generation and verification touch cache; no eviction',
          'physical_io_bytes': None,
          'io_scope': 'Win32 process transfer counts, including cached I/O; not physical device traffic',
          'timing_scope': 'complete CLI startup, preparation, execution, publication; excludes generation/verification/cleanup',
          'seed': 'external-comparison-v1', 'workers': 4, 'memory_mb': 32,
          'retained_parent': args.retained_parent, 'groups': 1 if args.retained_parent else 4,
          'shared_limit': os.environ.get('CHOPPER_MEMORY_LIMIT_MB'), 'repeats': args.repeats,
          'stop_criterion': f'{args.repeats} matched pairs per selected cell; stop on failure/parity or cleanup mismatch; no default promotion'})
    cells = selected_cells(args.cells, args.transition_rows, args.retained_parent)
    groups = 1 if args.retained_parent else 4
    with tempfile.TemporaryDirectory(prefix='windows-calibration-', dir=args.work_dir) as directory:
        root = Path(directory)
        for cell in cells:
            rows, shape, case = cells[cell]
            source = root / 'input.csv'
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['id', 'payload'] + [f'c{i}' for i in range(31)])
                writer.writerows(external.fields(row, shape) for row in range(rows))
            emit({'type': 'fixture', 'cell': cell, 'rows': rows, 'shape': shape, 'case': case,
                  'groups': groups, 'retained_parent': args.retained_parent,
                  'sha256': sha(source), 'bytes': source.stat().st_size})
            reference, samples = None, {'baseline': [], 'candidate': []}
            for repeat in range(args.repeats):
                for variant in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                    owned = root / 'owned'
                    owned.mkdir()
                    temp, output = owned / 'temp', owned / 'output'
                    temp.mkdir()
                    job = {'input': str(source), 'output': str(output), 'seed': 'external-comparison-v1',
                           'operations': external.operations_for(case, shape, groups),
                           'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152,
                                         'temp_dir': str(temp)}, 'limits': {'bytes': 100000000}}
                    config = root / 'job.json'
                    config.write_text(json.dumps(job), encoding='utf-8')
                    sampler = Space(owned)
                    sampler.thread.start()
                    started = time.perf_counter()
                    try:
                        with (root / 'stdout').open('wb') as stdout, (root / 'stderr').open('wb') as stderr:
                            process = subprocess.Popen([str(binaries[variant]), 'run', '--config', str(config), '--yes'],
                                                       stdout=stdout, stderr=stderr)
                            process.wait(timeout=180)
                            elapsed = time.perf_counter() - started
                            metrics = counters(process)
                        storage = sampler.finish()
                        analysis = json.loads((root / 'stdout').read_text(encoding='utf-8')) if process.returncode == 0 else None
                        if process.returncode:
                            raise RuntimeError((root / 'stderr').read_text(encoding='utf-8'))
                        actual = external.verify(output, analysis, shape, rows, case, groups)
                        if args.retained_parent:
                            verify_retained_parent(analysis, variant, rows, external)
                        assert analysis['diagnostics']['shuffle_partition_fusions'] == int(variant == 'candidate')
                        assert all(p.stat().st_size <= 100000000 for p in output.glob('*.csv'))
                        assert not list(temp.iterdir()), 'temporary files leaked'
                        assert set(owned.iterdir()) == {temp, output}, 'publication staging leaked'
                        if reference is None:
                            reference = actual
                        assert actual == reference, 'exact output/metadata parity mismatch'
                        samples[variant].append(elapsed)
                        emit({'type': 'measurement', 'cell': cell, 'variant': variant, 'repeat': repeat + 1,
                              'seconds': elapsed, **metrics, 'storage': storage, 'config': job,
                              'diagnostics': analysis['diagnostics'], 'timings': analysis['timings'],
                              'peak_temp_bytes': analysis['peak_temp_bytes'], 'fingerprint': actual,
                              'verified': True, 'cleanup_verified': True})
                    except BaseException as error:
                        if 'process' in locals() and process.poll() is None:
                            process.kill()
                            process.wait()
                        sampler.finish()
                        emit({'type': 'failure', 'cell': cell, 'variant': variant, 'repeat': repeat + 1,
                              'error': repr(error), 'stdout': (root / 'stdout').read_text(encoding='utf-8', errors='replace'),
                              'stderr': (root / 'stderr').read_text(encoding='utf-8', errors='replace')})
                        raise
                    shutil.rmtree(owned)
            medians = {k: statistics.median(v) for k, v in samples.items()}
            emit({'type': 'summary', 'cell': cell, 'median_seconds': medians,
                  'range_seconds': {k: [min(v), max(v)] for k, v in samples.items()},
                  'samples_per_variant': args.repeats,
                  'candidate_over_baseline': medians['candidate'] / medians['baseline']})


if __name__ == '__main__':
    main()
