"""Narrative extraction must preserve bytes, destinations and old source identities."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


cli = module('narratives', 'performance-narratives.py')
doc = cli.DOC
catalog = module('catalog', 'benchmark-catalog.py')


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / doc.DIRECTORY).mkdir(parents=True)
        (self.root / 'docs/benchmarks').mkdir()
        self.original = ('# Performance\n\n## Example\n\n[raw](benchmarks/raw.jsonl) '
                         '[contract](specification.md#csv) [other](#second)\n'
                         '[reference]: ../README.md\n\n'
                         '```sh\n## Not a section\npython scripts/reproduce.py\n'
                         'echo "[do not relocate](benchmarks/raw.jsonl)"\n```\n\n'
                         '## Second\n\n### Nested\n[web](https://example.invalid/a)\n')
        self.manifest = self.migrate(self.original)
        self.write_manifest()
        (self.root / doc.LEGACY).write_text(doc.render_compatibility(self.manifest), newline='\n')

    def migrate(self, text):
        entries = []
        for section in doc.sections(text):
            raw = '\n'.join(section['lines']) + '\n'
            path = (doc.DIRECTORY / (section['anchor'] + '.md')).as_posix()
            moved, relocations = doc.relocate(raw, path)
            (self.root / path).write_text(moved, newline='\n')
            entries.append({'id': section['anchor'], 'anchor': section['anchor'], 'title': section['title'],
                            'path': path, 'topic': 'reviewed-family', 'legacy_anchors': [section['anchor']],
                            'sha256': doc.sha256(moved.encode()), 'relocations': relocations,
                            'original_section_sha256': doc.sha256('\n'.join(section['lines']).encode())})
        entries[1]['legacy_anchors'].append('nested')
        return {'schema_version': 1, 'type': 'performance_narrative_manifest',
                'original_preamble': '# Performance\n\n', 'original_document_sha256': doc.sha256(text.encode()),
                'migrated_count': len(entries), 'investigations': entries}

    def write_manifest(self):
        (self.root / doc.MANIFEST).write_text(json.dumps(self.manifest))

    def prepare_derivative(self):
        self.original = self.original.replace('## Example\n\n',
            '## Example\n\nCompleted in 1.25 s at `C:/Users/demo-operator/work/run`. '
            'Output: `C:/work/demo-operator/result.csv`.\n\n')
        self.manifest = self.migrate(self.original)
        entry = self.manifest['investigations'][0]
        path = self.root / entry['path']
        archived = path.read_bytes()
        digest = entry['sha256']
        entry['sanitized_derivative'] = {'policy': 'windows-workstation-root-v1', 'original_sha256': digest}
        alias = 'docs/benchmarks/example-private-narrative.md'
        bundle = 'a' * 64
        registry = {'schema_version': 1,
                    'bundles': {bundle: {'bytes': 1, 'sha256': bundle,
                                         'reader': 'r2://chopper-archive-private/sha256/' + bundle}},
                    'artifacts': {alias: {'bytes': len(archived), 'sha256': digest, 'bundle': bundle,
                                          'member': 'objects/' + digest}}}
        (self.root / catalog.RESOLVER.REGISTRY).write_text(json.dumps(registry))
        cache = self.root / catalog.RESOLVER.CACHE / digest
        cache.parent.mkdir(parents=True)
        cache.write_bytes(archived)
        rendered = archived.replace(b'C:/Users/demo-operator/', b'C:/Users/USER/')
        entry['sha256'] = doc.sha256(rendered)
        path.write_bytes(rendered)
        self.write_manifest()
        return entry, path, alias, cache, registry

    def test_derivative_reconstructs_frozen_sections_from_the_archived_cache(self):
        self.prepare_derivative()
        restored = doc.performance_sections(self.root)
        self.assertEqual([s['lines'] for s in restored], [s['lines'] for s in doc.sections(self.original)])

    def test_derivative_preserves_old_issue_links_behind_curated_summaries(self):
        self.original = self.original.replace('[contract](specification.md#csv)',
            '[prior](https://github.com/jsmatfess/chopper/issues/20#issuecomment-123) '
            '[unrelated](https://example.invalid/issues/20)')
        entry, path, _, _, _ = self.prepare_derivative()
        entry['sanitized_derivative']['policy'] = 'workstation-and-historical-issues-v1'
        rendered = path.read_bytes().replace(
            b'https://github.com/jsmatfess/chopper/issues/20#issuecomment-123',
            b'../../history/prior-issues.md#issue-20')
        path.write_bytes(rendered)
        entry['sha256'] = doc.sha256(rendered)
        self.write_manifest()
        restored = doc.performance_sections(self.root)
        self.assertEqual(restored[0]['lines'], doc.sections(self.original)[0]['lines'])
        self.assertIn(b'https://example.invalid/issues/20', rendered)
        changed = rendered.replace(b'#issue-20', b'#issue-21')
        path.write_bytes(changed)
        entry['sha256'] = doc.sha256(changed)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Sanitized narrative differs'):
            doc.performance_sections(self.root)

    def test_derivative_allows_only_archive_registry_link_redirects(self):
        entry, path, _, _, registry = self.prepare_derivative()
        bundle = next(iter(registry['bundles']))
        digest = 'b' * 64
        registry['artifacts']['docs/benchmarks/raw.jsonl'] = {
            'bytes': 1, 'sha256': digest, 'bundle': bundle, 'member': 'objects/' + digest}
        (self.root / catalog.RESOLVER.REGISTRY).write_text(json.dumps(registry))
        old = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Sanitized narrative differs'):
            doc.performance_sections(self.root)

        updated = old.replace(b'../../benchmarks/raw.jsonl', b'../../evidence-originals.md#sha256-' + digest.encode())
        path.write_bytes(updated)
        entry['sha256'] = doc.sha256(updated)
        self.write_manifest()
        restored = doc.performance_sections(self.root)
        self.assertEqual(restored[0]['lines'], doc.sections(self.original)[0]['lines'])

        wrong = updated.replace(digest.encode(), bundle.encode())
        path.write_bytes(wrong)
        entry['sha256'] = doc.sha256(wrong)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Sanitized narrative differs'):
            doc.performance_sections(self.root)

    def test_derivative_rejects_measurement_edits_and_other_redactions_even_when_rehashed(self):
        entry, path, _, _, _ = self.prepare_derivative()
        rendered = path.read_bytes()
        for before, after in ((b'1.25 s', b'1.15 s'), (b'C:/work/demo-operator/', b'C:/work/USER/')):
            with self.subTest(before=before):
                changed = rendered.replace(before, after)
                path.write_bytes(changed)
                entry['sha256'] = doc.sha256(changed)
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, 'Sanitized narrative differs'):
                    doc.performance_sections(self.root)

    def test_derivative_rejects_another_registry_identity_and_wrong_local_bytes(self):
        _, _, alias, cache, registry = self.prepare_derivative()
        wrong = cache.read_bytes().replace(b'1.25 s', b'1.15 s')
        wrong_digest = doc.sha256(wrong)
        (cache.parent / wrong_digest).write_bytes(wrong)
        item = registry['artifacts'][alias]
        original = item.copy()
        item.update(sha256=wrong_digest, member='objects/' + wrong_digest)
        registry_path = self.root / catalog.RESOLVER.REGISTRY
        registry_path.write_text(json.dumps(registry))
        with self.assertRaisesRegex(ValueError, 'Archived narrative identity differs'):
            doc.performance_sections(self.root)

        registry['artifacts'][alias] = original
        registry_path.write_text(json.dumps(registry))
        (self.root / alias).write_bytes(wrong)
        with self.assertRaisesRegex(ValueError, 'Archived narrative bytes differ'):
            doc.performance_sections(self.root)

    def test_derivative_requires_a_hydrated_original(self):
        _, _, _, cache, _ = self.prepare_derivative()
        cache.unlink()
        with self.assertRaisesRegex(ValueError, 'Archived evidence is not hydrated'):
            doc.performance_sections(self.root)

    def test_derivative_rejects_unsupported_policy_and_stale_original_relocations(self):
        entry, _, _, _, _ = self.prepare_derivative()
        entry['sanitized_derivative']['policy'] = 'windows-workstation-root-v2'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsupported sanitized narrative policy'):
            doc.performance_sections(self.root)

        entry['sanitized_derivative']['policy'] = 'windows-workstation-root-v1'
        entry['relocations'][0]['to'] = 'stale'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Narrative link changed'):
            doc.performance_sections(self.root)

    def test_lossless_reconstruction_relocated_links_and_fenced_commands(self):
        sections = doc.performance_sections(self.root)
        self.assertEqual([s['lines'] for s in sections], [s['lines'] for s in doc.sections(self.original)])
        moved = (self.root / self.manifest['investigations'][0]['path']).read_text()
        self.assertIn('[raw](../../benchmarks/raw.jsonl)', moved)
        self.assertIn('[other](../../performance.md#second)', moved)
        self.assertIn('[reference]: ../../../README.md', moved)
        self.assertIn('echo "[do not relocate](benchmarks/raw.jsonl)"', moved)
        self.assertIn('id="nested"', (self.root / doc.LEGACY).read_text())

    def test_ambiguous_original_link_spellings_restore_exactly(self):
        raw = '[a](#x) [b](performance.md#x) [c](./specification.md)\n'
        moved, relocations = doc.relocate(raw, 'docs/performance/investigations/test.md')
        self.assertEqual(doc.restore(moved, relocations), raw)

    def test_archived_original_links_route_to_hash_addressed_access_guidance(self):
        raw = '[raw](benchmarks/archived.jsonl)\n'
        moved, relocations = doc.relocate(raw, 'docs/performance/investigations/test.md',
                                         {'docs/benchmarks/archived.jsonl': {'sha256': 'a' * 64}})
        self.assertIn('../../evidence-originals.md#sha256-' + 'a' * 64, moved)
        self.assertEqual(doc.restore(moved, relocations), raw)

    def test_section_separators_reconstruct_without_blank_lines_at_standalone_eof(self):
        for entry in self.manifest['investigations']:
            path = self.root / entry['path']
            raw = path.read_bytes()
            canonical = raw.rstrip(b'\n') + b'\n'
            entry['separator_newlines'] = len(raw) - len(canonical)
            entry['sha256'] = doc.sha256(canonical)
            path.write_bytes(canonical)
            self.assertFalse(canonical.endswith(b'\n\n'))
        self.write_manifest()
        self.assertEqual([s['lines'] for s in doc.performance_sections(self.root)],
                         [s['lines'] for s in doc.sections(self.original)])

    def test_hash_changes_unregistered_documents_and_missing_links_fail(self):
        entry = self.manifest['investigations'][0]
        path = self.root / entry['path']
        original = path.read_bytes()
        path.write_bytes(original + b'changed\n')
        with self.assertRaisesRegex(ValueError, 'Narrative hash changed'):
            doc.performance_sections(self.root)
        path.write_bytes(original)
        extra = self.root / doc.DIRECTORY / 'unregistered.md'
        extra.write_text('## Unregistered\n')
        with self.assertRaisesRegex(ValueError, 'Unregistered'):
            doc.performance_sections(self.root)
        extra.unlink()
        entry['relocations'][0]['to'] = 'wrong'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'link changed'):
            doc.performance_sections(self.root)

    def test_original_prose_and_source_identity_cannot_be_silently_rewritten(self):
        entry = self.manifest['investigations'][0]
        path = self.root / entry['path']
        path.write_text(path.read_text().replace('python scripts/reproduce.py', 'python scripts/other.py'))
        entry['sha256'] = doc.sha256(path.read_bytes())
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Original narrative identity changed'):
            doc.performance_sections(self.root)

    def test_catalog_retains_legacy_associations_and_direct_narrative_routes(self):
        (self.root / 'docs/benchmarks/raw.jsonl').write_text('{"type":"measurement","seconds":1}\n')
        result = catalog.build_catalog(self.root)
        first = result['experiments'][0]
        self.assertEqual(first['evidence'], 'docs/performance.md#example')
        self.assertEqual(first['artifacts'], ['docs/benchmarks/raw.jsonl'])
        self.assertEqual(first['scripts'], ['scripts/reproduce.py'])
        self.assertIn('performance/investigations/example.md', catalog.render_index(result))

    def test_duplicate_legacy_anchors_and_unsafe_paths_fail(self):
        baseline = copy.deepcopy(self.manifest)
        self.manifest['investigations'][1]['legacy_anchors'].append('example')
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Duplicate legacy'):
            doc.performance_sections(self.root)
        self.manifest = baseline
        self.manifest['investigations'][0]['path'] = '../outside.md'
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            doc.performance_sections(self.root)

    def test_check_rejects_stale_index_without_writing(self):
        path = self.root / doc.LEGACY
        path.write_text('stale\n')
        with mock.patch('sys.stdout', io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(cli.main(['--check'], self.root), 1)
        self.assertEqual(path.read_text(), 'stale\n')

    def test_new_registration_does_not_change_migrated_provenance(self):
        path = doc.DIRECTORY / 'new-decision.md'
        (self.root / path).write_text('## New decision\n\nNew reviewed prose.\n', newline='\n')
        with mock.patch('sys.stdout', io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(cli.main(['--register', path.as_posix(), '--topic', 'new-topic'], self.root), 0)
            self.assertEqual(cli.main(['--check'], self.root), 0)
        self.assertEqual(len(doc.performance_sections(self.root)), 3)
        self.assertEqual(doc.read_manifest(self.root)['original_document_sha256'], self.manifest['original_document_sha256'])

    def test_registration_rejects_crlf_before_pinning_git_unstable_bytes(self):
        path = doc.DIRECTORY / 'new-decision.md'
        (self.root / path).write_bytes(b'## New decision\r\n\r\nNew reviewed prose.\r\n')
        manifest = (self.root / doc.MANIFEST).read_bytes()
        error = io.StringIO()
        with mock.patch('sys.stdout', io.StringIO()), mock.patch('sys.stderr', error):
            self.assertEqual(cli.main(['--register', path.as_posix(), '--topic', 'new-topic'], self.root), 1)
        self.assertIn('LF line endings', error.getvalue())
        self.assertEqual((self.root / doc.MANIFEST).read_bytes(), manifest)


if __name__ == '__main__':
    unittest.main()
