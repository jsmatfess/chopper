"""Reused Windows binaries must keep their original build provenance."""
import importlib.util
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('benchmark_windows', Path(__file__).with_name('benchmark-windows.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
spec = importlib.util.spec_from_file_location('external', Path(__file__).with_name('benchmark-external-shuffle.py'))
external = importlib.util.module_from_spec(spec)
spec.loader.exec_module(external)
spec = importlib.util.spec_from_file_location('resident', Path(__file__).with_name('benchmark-resident-shuffle.py'))
resident = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resident)
spec = importlib.util.spec_from_file_location('windows_profile', Path(__file__).with_name('benchmark-windows-profile.py'))
windows_profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows_profile)


def retained_analysis(rows=20):
    shape = dict.fromkeys(('decoded_payload_bytes', 'maximum_payload_bytes', 'maximum_fields',
                          'maximum_row_heap_capacity_bytes', 'maximum_key_heap_capacity_bytes',
                          'maximum_key_bytes'), 1)
    shape.update(rows_decoded=rows, rows_keyed=rows, totals_saturated=False)
    record = {'shuffle_step': 1, 'partition_step': 2, 'parent_ordinal': 0,
              'parent_offset': 0, 'parent_rows': rows, 'shape': shape,
              'observation_complete': True, 'key_observation_complete': True,
              'phase': 'emission', 'outcome': 'fused_committed',
              'admission_denial': None, 'admission_denial_phase': None,
              'terminal_admission_denial': None, 'cancelled': False, 'cleanup_failed': False,
              'context_counter_delta': dict.fromkeys(('sort_runs', 'resident_sorts', 'merge_operations',
                                                      'temporary_bytes_read', 'temporary_bytes_written'), 0)}
    audit = {'version': 1, 'policy': 'experiment_gate_v1', 'selector': None, 'calibration': None,
             'scope': 'completed retained-parent attempts; first records, not a representative sample',
             'counter_scope': 'context deltas, including failed tentative work and original-stage retry',
             'capacity': 16, 'initialized': True, 'collection_denied': False,
             'reserved_bytes': 4096, 'completed_attempts': 1, 'omitted_attempts': 0, 'records': [record]}
    return {'rows': rows, 'memory_budget_bytes': 32768, 'stages': [], 'logical_digest': 'fixture-digest',
            'diagnostics': {'shuffle_partition_fusions': 1, 'shuffle_partition_retries': 0,
                            'workspace_reserved_bytes': 4108, 'peak_workspace_reserved_bytes': 8192,
                            'temporary_path_reserved_bytes': 5, 'input_header_reserved_bytes': 7,
                            'shuffle_partition_decisions': audit}}


class RetainedParentTests(unittest.TestCase):
    def test_final_only_space_observation_does_not_scan_during_the_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sampler = benchmark.Space(root, 0)
            sampler.thread.start()
            sampler.thread.join()
            self.assertEqual(sampler.samples, 0)
            (root / 'result.csv').write_bytes(b'abc')
            nested = root / 'nested'
            nested.mkdir()
            (nested / 'manifest.jsonl').write_bytes(b'12345')
            result = sampler.finish()
            self.assertEqual(result['samples'], 1)
            self.assertEqual(result['peak_logical_bytes'], 8)
            self.assertEqual(result['interval_seconds'], 0)
            self.assertIn('not a live storage peak', result['scope'])

    def test_directory_owner_is_counted_exactly_and_malformed_charges_are_rejected(self):
        for verifier in (external.verify_workspace_owners, resident.verify_workspace_owners):
            for directory_bytes in (None, 0, 13):
                analysis = retained_analysis()
                diagnostics = analysis['diagnostics']
                diagnostics.pop('shuffle_partition_decisions')
                diagnostics['workspace_reserved_bytes'] = 12 + (directory_bytes or 0)
                if directory_bytes is not None:
                    diagnostics['directory_path_reserved_bytes'] = directory_bytes
                verifier(analysis)
                diagnostics['workspace_reserved_bytes'] += 1
                with self.subTest(verifier=verifier.__module__, directory=directory_bytes), self.assertRaises(AssertionError):
                    verifier(analysis)
            for invalid in (-1, True, 1.5, '13', None):
                analysis = retained_analysis()
                analysis['diagnostics']['directory_path_reserved_bytes'] = invalid
                with self.subTest(verifier=verifier.__module__, invalid=invalid), self.assertRaises(AssertionError):
                    verifier(analysis)

    def test_generic_owner_verifier_preserves_empty_and_denied_optional_audits(self):
        analysis = retained_analysis()
        audit = analysis['diagnostics']['shuffle_partition_decisions']
        audit.update(initialized=False, reserved_bytes=0, completed_attempts=0, records=[])
        analysis['diagnostics']['workspace_reserved_bytes'] = 12
        external.verify_workspace_owners(analysis)
        audit.update(initialized=True, collection_denied=True, completed_attempts=1, omitted_attempts=1)
        external.verify_workspace_owners(analysis)
        audit['reserved_bytes'] = 4096
        with self.assertRaises(AssertionError):
            external.verify_workspace_owners(analysis)

    def test_mode_preserves_legacy_cases_and_selects_one_parent(self):
        legacy = benchmark.selected_cells(['resident', 'skew'])
        self.assertEqual(legacy['skew'], (300000, 'skew', 'shuffle_partition_key'))
        retained = benchmark.selected_cells(['resident', 'skew'], retained_parent=True)
        self.assertEqual(retained['skew'], (300000, 'skew', 'parent_shuffle_partition'))
        self.assertEqual(benchmark.selected_cells([], [123], True),
                         {'transition_123': (123, 'columns', 'parent_shuffle_partition')})
        self.assertEqual(external.operations_for(retained['resident'][2], 'columns', 1),
                         [{'type': 'balanced', 'files': 1}, {'type': 'shuffle', 'strategy': 'uniform'},
                          {'type': 'partition', 'columns': ['c0']}])

    def test_complete_candidate_and_absent_baseline_audit(self):
        analysis = retained_analysis()
        benchmark.verify_retained_parent(analysis, 'candidate', 20, external)
        external.verify_workspace_owners(analysis)
        diagnostics = analysis['diagnostics']
        del diagnostics['shuffle_partition_decisions']
        diagnostics['shuffle_partition_fusions'] = 0
        diagnostics['workspace_reserved_bytes'] = 12
        benchmark.verify_retained_parent(analysis, 'baseline', 20, external)
        external.verify_workspace_owners(analysis)

    def test_retained_skew_routes_the_skewed_key_and_preserves_legacy_cells(self):
        operations = external.operations_for('parent_shuffle_partition', 'skew', 1)
        self.assertEqual(operations[-1], {'type': 'partition', 'columns': ['payload']})
        self.assertEqual(external.output_count('parent_shuffle_partition', 'skew', 1), 3)
        counts = {}
        for row in range(1000):
            key = external.fields(row, 'skew')[1]
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(sorted(counts.values()), [10, 90, 900])
        self.assertEqual(external.operations_for('shuffle_partition', 'skew', 4)[-1],
                         {'type': 'partition', 'columns': ['c0']})
        self.assertEqual(external.output_count('shuffle_partition', 'skew', 4), 10)
        self.assertEqual(external.operations_for('parent_shuffle_partition', 'columns', 1)[-1],
                         {'type': 'partition', 'columns': ['c0']})
        self.assertEqual(external.output_count('parent_shuffle_partition', 'columns', 1), 10)

    def test_exact_owner_equation_includes_audit_and_rejects_other_live_owners(self):
        for reserved in (12, 4107, 4109):
            analysis = retained_analysis()
            analysis['diagnostics']['workspace_reserved_bytes'] = reserved
            with self.subTest(reserved=reserved), self.assertRaises(AssertionError):
                external.verify_workspace_owners(analysis)

    def test_missing_malformed_or_unsupported_audit_is_rejected(self):
        mutations = [lambda d: d.pop('shuffle_partition_decisions'),
                     lambda d: d.update(shuffle_partition_decisions=None)]
        for field, value in [('version', 2), ('version', True), ('policy', 'other'),
                             ('selector', 'cost'), ('calibration', {}), ('capacity', 17),
                             ('initialized', False), ('initialized', 1), ('collection_denied', True),
                             ('reserved_bytes', 0), ('reserved_bytes', True), ('reserved_bytes', -1),
                             ('completed_attempts', 2), ('omitted_attempts', 1), ('records', []),
                             ('scope', 'other'), ('counter_scope', 'other')]:
            mutations.append(lambda d, k=field, v=value: d['shuffle_partition_decisions'].update({k: v}))
        for field, value in [('shuffle_step', 0), ('partition_step', 1), ('parent_ordinal', 1),
                             ('parent_offset', 1), ('parent_rows', 19), ('phase', 'preparation'),
                             ('outcome', 'original_committed'), ('observation_complete', False),
                             ('key_observation_complete', False), ('admission_denial', 'local'),
                             ('cancelled', True), ('cleanup_failed', True), ('shape', {}),
                             ('context_counter_delta', {})]:
            mutations.append(lambda d, k=field, v=value: d['shuffle_partition_decisions']['records'][0].update({k: v}))
        mutations += [lambda d: d['shuffle_partition_decisions'].pop('selector'),
                      lambda d: d['shuffle_partition_decisions']['records'][0].pop('admission_denial'),
                      lambda d: d['shuffle_partition_decisions']['records'][0]['shape'].update(rows_keyed=19),
                      lambda d: d.update(shuffle_partition_retries=1),
                      lambda d: d.update(shuffle_partition_fusions=0)]
        for index, mutate in enumerate(mutations):
            analysis = retained_analysis()
            mutate(analysis['diagnostics'])
            with self.subTest(index=index), self.assertRaises((AssertionError, KeyError, TypeError)):
                benchmark.verify_retained_parent(analysis, 'candidate', 20, external)
        with self.assertRaises(AssertionError):
            benchmark.verify_retained_parent(retained_analysis(), 'baseline', 20, external)

    def test_existing_verifier_checks_retained_membership_metadata_and_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            entries = []
            for part in range(10):
                path = output / f'界-{part}.csv'
                with path.open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['id', 'payload'] + [f'c{i}' for i in range(31)])
                    writer.writerows(external.fields(row, 'columns') for row in (part, part + 10))
                entries.append({'type': 'output', 'path': path.name, 'rows': 2,
                                'csv_bytes': path.stat().st_size,
                                'lineage': [{'operation': 0, 'part': 1},
                                            {'operation': 2, 'values': [str(part)]}]})
            manifest = output / 'manifest.jsonl'
            manifest.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries), encoding='utf-8')
            analysis = retained_analysis()
            digest = external.verify(output, analysis, 'columns', 20, 'parent_shuffle_partition', 1)
            self.assertEqual(len(digest), 64)
            entries[0]['lineage'][0]['part'] = 2
            manifest.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
            with self.assertRaises(AssertionError):
                external.verify(output, analysis, 'columns', 20, 'parent_shuffle_partition', 1)

    def test_skew_verifier_reads_utf8_fields_independently_of_windows_locale(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            groups = {}
            for row in range(1000):
                fields = external.fields(row, 'skew')
                groups.setdefault(fields[1], []).append(fields)
            entries = []
            for index, (key, records) in enumerate(groups.items()):
                path = output / f'{index}.csv'
                with path.open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['id', 'payload'] + [f'c{i}' for i in range(31)])
                    writer.writerows(records)
                entries.append({'type': 'output', 'path': path.name, 'rows': len(records),
                                'csv_bytes': path.stat().st_size,
                                'lineage': [{'operation': 0, 'part': 1},
                                            {'operation': 2, 'values': [key]}]})
            (output / 'manifest.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
            self.assertEqual(len(external.verify(output, retained_analysis(1000), 'skew', 1000,
                                               'parent_shuffle_partition', 1)), 64)


class SourceInventoryTests(unittest.TestCase):
    def test_tracked_dirty_and_untracked_nonignored_inputs_are_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            files = {'Cargo.toml': b'workspace', 'Cargo.lock': b'lock',
                     'crates/chopper/src/lib.rs': b'old',
                     'crates/chopper/src/storage/decision_audit.rs': b'audit',
                     'ui/src/browser/export.ts': b'export',
                     'vendor/zip-2.4.2/src/read.rs': b'parser-budget-hook',
                     'ui/src/browser/ignored.ts': b'ignored'}
            for name, contents in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            (root / '.gitignore').write_text('ignored.ts\n', encoding='utf-8')
            subprocess.run(['git', 'add', 'Cargo.toml', 'crates/chopper/src/lib.rs'], cwd=root, check=True)
            (root / 'crates/chopper/src/lib.rs').write_bytes(b'dirty')
            inventory = benchmark.source_inventory(root)
            self.assertEqual(set(inventory), set(files) - {'ui/src/browser/ignored.ts'})
            for name, digest in inventory.items():
                self.assertEqual(digest, benchmark.sha(root / name))


class ReusedBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.binaries = {name: self.root / (name + '.exe') for name in ['baseline', 'candidate']}
        for name, path in self.binaries.items():
            path.write_bytes(name.encode())
        self.record = {
            'type': 'environment',
            'binary_sha256': {name: benchmark.sha(path) for name, path in self.binaries.items()},
            'features': {'baseline': [], 'candidate': ['experimental-shuffle-partition']},
            'source_sha256': {'engine.rs': 'original-source'},
            'harness_sha256': {'original-harness.py': 'original-harness'},
            'revision': 'original-revision',
            'dirty_status': 'original-dirty-status',
        }
        self.evidence = self.root / 'build.jsonl'

    def write_evidence(self):
        self.evidence.write_text(json.dumps(self.record) + '\n', encoding='utf-8')

    def test_reuse_retains_build_identity_and_pins_evidence_bytes(self):
        self.write_evidence()
        result = benchmark.build_provenance(self.binaries, self.evidence)
        self.assertEqual(result['build_source_sha256'], self.record['source_sha256'])
        self.assertEqual(result['build_revision'], 'original-revision')
        self.assertEqual(result['build_dirty_status'], 'original-dirty-status')
        self.assertEqual(result['source_sha256'], benchmark.sha(self.evidence))
        self.assertEqual(result['line'], 1)

    def test_changed_binary_is_rejected_even_when_path_is_unchanged(self):
        self.write_evidence()
        self.binaries['candidate'].write_bytes(b'new-build-at-same-path')
        with self.assertRaisesRegex(ValueError, 'binaries do not match'):
            benchmark.build_provenance(self.binaries, self.evidence)

    def test_missing_or_incompatible_environment_is_rejected(self):
        for field, replacement in [('type', 'measurement'), ('features', {}),
                                   ('source_sha256', {}), ('harness_sha256', {})]:
            with self.subTest(field=field):
                original = self.record[field]
                self.record[field] = replacement
                self.write_evidence()
                with self.assertRaises(ValueError):
                    benchmark.build_provenance(self.binaries, self.evidence)
                self.record[field] = original


class ProfileBuildTests(unittest.TestCase):
    def test_profile_cli_and_census_artifacts_require_their_own_pinned_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {'source_sha256': {'engine.rs': 'source'}, 'source_identity_unchanged': True, 'builds': {}}
            for variant in ('baseline', 'candidate'):
                cli, allocator = root / (variant + '.exe'), root / (variant + '-allocator.exe')
                cli.write_bytes(variant.encode())
                allocator.write_bytes((variant + '-census').encode())
                record['builds'][variant] = {
                    'features': [] if variant == 'baseline' else ['experimental-parallel-profile'],
                    'returncode': 0, 'artifact': str(cli), 'sha256': benchmark.sha(cli),
                    'allocator': {'artifact': str(allocator), 'sha256': benchmark.sha(allocator)}}
            binaries, allocators = windows_profile.validate_build(record)
            self.assertEqual(set(binaries), {'baseline', 'candidate'})
            self.assertEqual(set(allocators), {'baseline', 'candidate'})
            for path in (binaries['candidate'], allocators['baseline']):
                old = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    windows_profile.validate_build(record)
                path.write_bytes(old)
            for field, value in [('features', ['experimental-shuffle-partition']), ('returncode', 1)]:
                old = record['builds']['candidate'][field]
                record['builds']['candidate'][field] = value
                with self.assertRaisesRegex(ValueError, 'incompatible or unsuccessful'):
                    windows_profile.validate_build(record)
                record['builds']['candidate'][field] = old
            record['source_identity_unchanged'] = False
            with self.assertRaisesRegex(ValueError, 'matched build source'):
                windows_profile.validate_build(record)


if __name__ == '__main__':
    unittest.main()
