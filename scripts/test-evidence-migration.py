#!/usr/bin/env python3
"""Synthetic corruption, provenance and archive attack controls; no repo evidence writes."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('migration', Path(__file__).with_name('evidence-migration.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'raw.jsonl').write_bytes(b'{"outcome":"failed"}\r\n{"partial":true}\n')
        self.item = {'id': 'attempt', 'aliases': ['raw.jsonl'], 'kind': 'file',
                     'metadata': dict.fromkeys(m.METADATA), 'storage': None}
        self.item['metadata'].update(outcome='failed', failure='exit 1', incomplete=True)

    def prepare(self, item=None):
        return m.prepare(self.root, {'schema_version': 1, 'artifacts': [item or self.item]})

    def receipt(self, manifest):
        path = self.root / 'manifest.json'
        if path.exists():
            path.unlink()  # synthetic fixture only
        m.write(path, manifest)
        return path, {'schema_version': 1, 'manifest_sha256': m.identity(path)['sha256'],
                      'reader': 'local', 'objects': {'attempt': {'path': 'raw.jsonl', 'reader': None}}}

    def test_local_failed_incomplete_exact_bytes_and_aliases(self):
        (self.root / 'alias').write_bytes((self.root / 'raw.jsonl').read_bytes())
        self.item['aliases'].append('alias')
        manifest = self.prepare()
        self.assertEqual(manifest['artifacts'][0]['metadata'], self.item['metadata'])
        self.assertEqual(manifest['artifacts'][0]['aliases'], ['raw.jsonl', 'alias'])
        path, receipt = self.receipt(manifest)
        self.assertEqual(m.verify(path, self.root, receipt)['scope'], 'local')
        self.assertEqual((self.root / 'raw.jsonl').read_bytes(), b'{"outcome":"failed"}\r\n{"partial":true}\n')

    def test_missing_corrupt_stale_incomplete_receipts(self):
        manifest = self.prepare()
        path, receipt = self.receipt(manifest)
        for mutate in [lambda r: r.update(manifest_sha256='0' * 64),
                       lambda r: r.update(objects={}),
                       lambda r: r['objects']['attempt'].update(path='missing')]:
            trial = copy.deepcopy(receipt)
            mutate(trial)
            with self.assertRaises(ValueError):
                m.verify(path, self.root, trial)
        (self.root / 'raw.jsonl').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            m.verify(path, self.root, receipt)

    def test_provenance_is_resolved_and_not_inferred(self):
        manifest = self.prepare()
        self.assertIsNone(manifest['artifacts'][0]['metadata']['vendor'])
        ref = {'path': 'raw.jsonl', **manifest['artifacts'][0]['original']}
        self.item['metadata']['harness'] = [ref]
        self.prepare()
        ref['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.prepare()
        ref['path'] = 'absent-source'
        with self.assertRaises(ValueError):
            self.prepare()

    def test_path_and_alias_attacks(self):
        for path in ['../x', '/x', 'a/../b', 'a\\b', 'C:/x', './x', 'a//b', 'NUL', 'a.']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                m.relative(path)
        for paths in [['a', 'A'], ['a', 'a/b'], ['é', 'e\u0301']]:
            with self.assertRaises(ValueError):
                m.unique(paths)
        (self.root / 'different').write_bytes(b'other')
        self.item['aliases'].append('different')
        with self.assertRaises(ValueError):
            self.prepare()

    def test_link_rejection(self):
        try:
            (self.root / 'link').symlink_to(self.root / 'raw.jsonl')
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        with self.assertRaises(ValueError):
            m.local(self.root, 'link')

    def zip(self, entries):
        path = self.root / 'bundle.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def test_zip_happy_and_member_mismatch(self):
        self.zip([('log.txt', b'failed'), ('source.rs', b'source')])
        self.item.update(aliases=['bundle.zip'], kind='zip')
        manifest = self.prepare()
        path, receipt = self.receipt(manifest)
        receipt['objects']['attempt']['path'] = 'bundle.zip'
        self.assertEqual(m.verify(path, self.root, receipt)['result'], 'verified')
        manifest['artifacts'][0]['container']['members'][0]['sha256'] = '0' * 64
        path, receipt = self.receipt(manifest)
        receipt['objects']['attempt']['path'] = 'bundle.zip'
        with self.assertRaises(ValueError):
            m.verify(path, self.root, receipt)

    def test_zip_attacks(self):
        for names in [['../escape'], ['a', 'a'], ['a', 'A'], ['a', 'a/b'], ['folder/']]:
            path = self.zip([(name, b'x') for name in names])
            with self.subTest(names=names), self.assertRaises(ValueError):
                m.members(path, 'zip')
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        path = self.zip([(info, b'target')])
        with self.assertRaises(ValueError):
            m.members(path, 'zip')

    def test_tar_happy_links_and_traversal(self):
        path = self.root / 'bundle.tar.gz'
        for kind, name in [(tarfile.REGTYPE, 'raw'), (tarfile.SYMTYPE, 'link'),
                           (tarfile.LNKTYPE, 'hard'), (tarfile.REGTYPE, '../escape')]:
            with tarfile.open(path, 'w:gz') as archive:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = 1 if kind == tarfile.REGTYPE else 0
                info.linkname = 'raw' if kind != tarfile.REGTYPE else ''
                archive.addfile(info, io.BytesIO(b'x'))
            if name == 'raw':
                self.assertEqual(m.members(path, 'tar')[0]['bytes'], 1)
            else:
                with self.assertRaises(ValueError):
                    m.members(path, 'tar')

    def test_intended_reader_and_signed_url_rejection(self):
        manifest = self.prepare()
        artifact = manifest['artifacts'][0]
        sha = artifact['original']['sha256']
        artifact['storage'] = {'bucket': 'chopper-evidence-public', 'key': 'sha256/' + sha,
                               'version': sha, 'access': 'public-https',
                               'reader': 'https://evidence.example.org/sha256/' + sha}
        path, receipt = self.receipt(manifest)
        receipt['reader'] = 'intended-reader'
        with self.assertRaises(ValueError):
            m.verify(path, self.root, receipt)
        receipt['objects']['attempt']['reader'] = artifact['storage']['reader']
        self.assertEqual(m.verify(path, self.root, receipt)['scope'], 'intended-reader')
        artifact['storage']['reader'] += '?token=secret'
        with self.assertRaises(ValueError):
            m.validate(manifest)

    def test_duplicate_json_and_no_overwrite(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"a":1,"a":2}', encoding='utf-8')
        with self.assertRaises(ValueError):
            m.load(path)
        with self.assertRaises(FileExistsError):
            m.write(path, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
