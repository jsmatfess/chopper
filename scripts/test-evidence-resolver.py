"""Archived-original retrieval, corruption and catalog/export integration controls."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


resolver = module('resolver', 'evidence-resolver.py')
catalog = module('catalog', 'benchmark-catalog.py')


class ResolverTests(unittest.TestCase):
    def fixture(self, root, extra_member=None):
        (root / 'docs/benchmarks').mkdir(parents=True)
        (root / 'docs/performance.md').write_text('## Test\n[raw](benchmarks/raw.jsonl)\n')
        cache = root / resolver.CACHE
        cache.mkdir(parents=True)
        data = b'\n{"type":"measurement","verified":false,"seconds":0.5}\nnull\n'
        original = cache / 'original'
        original.write_bytes(data)
        identity = resolver.identity(original)
        bundle = cache / 'temporary.tar'
        with tarfile.open(bundle, 'w') as archive:
            info = tarfile.TarInfo('objects/' + identity['sha256'])
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            if extra_member:
                archive.addfile(tarfile.TarInfo(extra_member), io.BytesIO())
        bundle_identity = resolver.identity(bundle)
        sha = bundle_identity['sha256']
        bundle.rename(cache / ('bundle-' + sha + '.tar'))
        registry = {'schema_version': 1, 'bundles': {
            sha: {**bundle_identity, 'reader': 'r2://chopper-archive-private/sha256/' + sha}},
            'artifacts': {'docs/benchmarks/raw.jsonl': {
                **identity, 'bundle': sha, 'member': 'objects/' + identity['sha256']}}}
        (root / resolver.REGISTRY).write_text(json.dumps(registry))
        return data, registry

    def test_missing_original_requires_explicit_hydration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, 'not hydrated'):
                resolver.resolve(root, 'docs/benchmarks/raw.jsonl')

    def test_hydrated_original_preserves_catalog_export_and_physical_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, _ = self.fixture(root)
            self.assertEqual(resolver.hydrate(root, 'unused-wrangler.js'), 1)
            self.assertEqual(resolver.resolve(root, 'docs/benchmarks/raw.jsonl').read_bytes(), raw)
            archived = catalog.build_catalog(root)
            stream = io.StringIO()
            catalog.export_records(root, '*', stream)
            exported = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual([row['line'] for row in exported], [2, 3])
            self.assertFalse(exported[0]['data']['verified'])
            self.assertIsNone(exported[1]['data'])
            self.assertEqual(resolver.materialize(root), 1)
            self.assertEqual((root / 'docs/benchmarks/raw.jsonl').read_bytes(), raw)
            self.assertEqual(catalog.build_catalog(root), archived)
            self.assertEqual(len(archived['artifacts']), 1)

    def test_corrupt_original_cache_is_never_accepted_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, data = self.fixture(root)
            item = data['artifacts']['docs/benchmarks/raw.jsonl']
            path = root / resolver.CACHE / item['sha256']
            path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
                resolver.resolve(root, 'docs/benchmarks/raw.jsonl')
            with self.assertRaisesRegex(ValueError, 'cache mismatch'):
                resolver.hydrate(root, 'unused')
            self.assertEqual(path.read_bytes(), b'corrupt')

    def test_unsafe_archive_member_is_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, '../escape')
            with self.assertRaisesRegex(ValueError, 'Unsafe bundle member'):
                resolver.hydrate(root, 'unused')
            self.assertFalse((root / 'escape').exists())

    def test_registry_rejects_unapproved_reader_and_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, data = self.fixture(root)
            bundle = next(iter(data['bundles'].values()))
            bundle['reader'] = 'https://example.com/private?token=secret'
            (root / resolver.REGISTRY).write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'unapproved evidence reader'):
                resolver.registry(root)

    def test_s3_download_verifies_bytes_and_closes_response_on_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, data = self.fixture(root)
            sha = next(iter(data['bundles']))
            target = root / resolver.CACHE / ('bundle-' + sha + '.tar')
            raw = target.read_bytes()
            target.unlink()
            body = io.BytesIO(raw)
            client = mock.Mock()
            client.get_object.return_value = {'ContentLength': len(raw), 'Body': body}
            self.assertEqual(resolver.hydrate(root, s3_client=client), 1)
            self.assertTrue(body.closed)
            client.get_object.assert_called_once_with(Bucket='chopper-archive-private', Key='sha256/' + sha)
            target.unlink()
            denied = io.BytesIO(raw)
            client.get_object.return_value = {'ContentLength': len(raw) + 1, 'Body': denied}
            with self.assertRaisesRegex(ValueError, 'length mismatch'):
                resolver.hydrate(root, s3_client=client)
            self.assertTrue(denied.closed)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
