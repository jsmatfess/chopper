"""Archived-source identity and navigation controls; never execute a benchmark."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'docs/history/shuffle-harnesses-2026-11-16'
MANIFEST = json.loads((ARCHIVE / 'manifest.json').read_text())


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class HistoricalHarnessControls(unittest.TestCase):
    def test_original_harness_and_dependency_bytes_are_preserved(self):
        self.assertEqual(MANIFEST['source_commit'], 'de93a7a728fd8652f01627b1d1483409ed499455')
        files = MANIFEST['files']
        self.assertEqual(len(files), 11)
        self.assertEqual(sum(row['role'] == 'harness' for row in files), 9)
        self.assertEqual(MANIFEST['harness_lines'], 1038)
        for row in files:
            path = ROOT / row['archived_path']
            self.assertEqual(path.parent, ARCHIVE)
            self.assertFalse(path.is_symlink())
            raw = path.read_bytes()
            self.assertEqual(len(raw), row['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
            if row['role'] == 'harness':
                self.assertFalse((ROOT / row['original_path']).exists())

    def test_legacy_mentions_route_to_the_exact_source_archive(self):
        catalog = module('benchmark-catalog')
        for row in MANIFEST['files']:
            if row['role'] == 'harness':
                self.assertEqual(catalog.SCRIPT_ARCHIVES[row['original_path']], row['archived_path'])
        guide = (ROOT / 'scripts/README.md').read_text()
        self.assertIn('not current-main benchmark entry points', guide)
        for row in MANIFEST['files']:
            if row['role'] == 'harness':
                self.assertIn(Path(row['archived_path']).name, guide)

    def test_narrative_relocation_preserves_every_original_section_identity(self):
        documents = module('evidence-documents')
        entries = {row['path']: row for row in documents.read_manifest(ROOT)['investigations']}
        self.assertEqual(len(MANIFEST['relocated_narratives']), 3)
        for row in MANIFEST['relocated_narratives']:
            entry = entries[row['path']]
            self.assertEqual(entry['original_section_sha256'], row['original_section_sha256'])
            raw = (ROOT / row['path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['sha256'])
            sections = documents.sections(documents.original_text(raw, entry))
            self.assertEqual(len(sections), 1)
            self.assertEqual(hashlib.sha256('\n'.join(sections[0]['lines']).encode()).hexdigest(),
                             row['original_section_sha256'])
            self.assertNotEqual(entry['sha256'], row['previous_rendered_sha256'])
            for name in row['sources']:
                self.assertIn('shuffle-harnesses-2026-11-16/' + Path(name).name,
                              (ROOT / row['path']).read_text())

    def test_archived_help_resolves_sibling_dependencies_without_running_jobs(self):
        for row in MANIFEST['files']:
            if row['role'] != 'harness':
                continue
            with self.subTest(source=row['archived_path']):
                result = subprocess.run([sys.executable, str(ROOT / row['archived_path']), '--help'],
                                        cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)


if __name__ == '__main__':
    unittest.main()
