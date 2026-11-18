"""Frozen campaign separation and fresh-observation controls; no acceptance workload."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scale_acceptance import campaign_native639 as native
from scale_acceptance import campaign_host_observer_v1 as compatibility
from scale_acceptance import native_scale_identity as identity
from scale_acceptance import hosted_qualification as qualification

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    if isinstance(value, set):
        return sorted(canonical(item) for item in value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fixture_native_path(root, value):
    # These content/closure controls do not exercise WSL path transport.
    return str(PureWindowsPath('C:/campaign-controls') / Path(value).resolve().relative_to(Path(root).resolve()))


class CampaignControls(unittest.TestCase):
    def test_native_pins_and_locator_remain_exact_campaign_data(self):
        names = ['BUILD', 'BUILD_TREE', 'LINEAGE_PATH', 'LINEAGE_SHA', 'LINUX_SCALE_PLAN_SHA', 'LINUX_SCALE_REPORTS', 'PACKAGE_RECEIPT', 'PACKAGING_DELTA', 'PRODUCT', 'RECONCILIATION', 'TREE']
        data = {name: getattr(native, name) for name in names}
        # The published locator is a neutral alias; all cryptographic campaign
        # pins retain their original identities and exact consumer checks.
        self.assertEqual(digest(data), '9b3a6ec4172e049953c1f53c6ba81e70a9fbfcda4d4682c4e975925e6598770b')
        for name, value in data.items():
            self.assertEqual(getattr(identity, name), value)
        self.assertIn('scripts', identity.REQUIRED)
        tree = ast.parse(Path(native.__file__).read_text())
        self.assertTrue(all(isinstance(node, ast.Assign) or
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and
            isinstance(node.value.value, str) for node in tree.body))
        release = json.loads((ROOT / 'docs/releases/0.2.0-native-scale-acceptance.json').read_text())
        selected = release['selected_product']
        self.assertEqual(selected['source_commit'], native.PRODUCT)
        self.assertEqual(selected['runtime_build_commit'], native.BUILD)
        self.assertEqual(selected['artifact_receipt_sha256'], native.PACKAGE_RECEIPT)
        self.assertEqual(release['linux']['plan_sha256'], native.LINUX_SCALE_PLAN_SHA)
        for shape, recorded_digest in native.LINUX_SCALE_REPORTS.items():
            self.assertEqual(release['linux'][shape]['report_sha256'], recorded_digest)

    def test_legacy_exclusions_hashes_and_normalizer_are_frozen(self):
        data = {name: getattr(compatibility, name) for name in
                ('REVIEWED_CONSUMERS', 'UNRELATED', 'ADDED_IMPORTS')}
        self.assertEqual(digest(data), 'f3e00aacda2ae76fe43f596407b5b1914dae9ef3d0ba8529c18be99f28158c6a')
        source = Path(compatibility.__file__).read_text()
        tree = ast.parse(source)
        normalizer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'relevant')
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source, normalizer).encode()).hexdigest(),
                         'cb6a43a88e14990849c8df1e11351177de98165a9904433e073d36265374ab89')

    def test_fresh_identical_observation_does_not_evaluate_legacy_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'observer.py'
            path.write_text('# exact fresh producer')
            checker = SimpleNamespace(checker_sources=lambda: [path])
            with patch.object(qualification, 'native_path', side_effect=lambda p: fixture_native_path(directory, p)), \
                    patch.object(qualification.subprocess, 'check_output', side_effect=AssertionError('synthetic control must not launch host tools')), \
                    patch.object(compatibility, 'relevant', side_effect=AssertionError('legacy rules must not run')):
                observed = dict(preparation_code=[dict(path=qualification.native_path(path),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
                self.assertEqual(qualification.host_implementation(observed, None, directory, checker),
                                 dict(status='identical-producer', changed_files=[]))

    def test_new_campaign_records_are_in_the_complete_checker_closure(self):
        spec = importlib.util.spec_from_file_location('campaign_preflight', ROOT / 'scripts/acceptance-preflight.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        paths = checker.checker_sources()
        for module in (native, compatibility):
            self.assertIn(Path(module.__file__).resolve(), [path.resolve() for path in paths])
        # An older closure cannot be silently adopted for this changed checker.
        with patch.object(qualification, 'native_path', side_effect=lambda p: fixture_native_path(ROOT, p)), \
                patch.object(qualification.subprocess, 'check_output', side_effect=AssertionError('synthetic control must not launch host tools')):
            observed = dict(preparation_code=[dict(path=qualification.native_path(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths
                if path.name not in ('campaign_native639.py', 'campaign_host_observer_v1.py')])
            with self.assertRaisesRegex(ValueError, 'host producer source closure mismatch'):
                qualification.host_implementation(observed, None, ROOT, checker)


if __name__ == '__main__':
    unittest.main()
