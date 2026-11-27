"""Contract tests for which platform/ownership checks can be skipped."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ci_scope', Path(__file__).with_name('ci-scope.py'))
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class ScopeTests(unittest.TestCase):
    def selected(self, *paths):
        return {job for job, enabled in scope.classify(paths).items() if enabled}

    def test_documentation_does_not_build_engines(self):
        self.assertEqual(self.selected('README.md', 'AGENTS.md', 'docs/browser.md'), set())

    def test_hosted_qualification_selects_owning_fake_controls(self):
        for path in ('scripts/hosted_picker/control.py', 'scripts/hosted_picker/uia.ps1',
                     'scripts/test-hosted-qualification.py', 'scripts/browser-hosted-qualification.test.mjs'):
            self.assertEqual(self.selected(path), {'browser', 'tooling'})
            self.assertTrue(scope.classify([path], platform='windows')['tooling'])

    def test_shared_core_checks_every_runtime_and_portable_target(self):
        self.assertEqual(self.selected('crates/chopper-core/src/config.rs'),
                         {'native', 'features', 'core', 'browser', 'tooling'})

    def test_python_paths_select_native_tooling_on_supported_platforms(self):
        for path in ('pyproject.toml', 'crates/chopper-python/Cargo.toml',
                     'crates/chopper-python/Cargo.lock', 'crates/chopper-python/src/lib.rs',
                     'crates/chopper-python/python/chopper_csv/__init__.py',
                     'crates/chopper-python/tests/installed_wheel.py'):
            for platform in scope.PLATFORM_JOBS:
                with self.subTest(path=path, platform=platform):
                    jobs = scope.classify([path], platform=platform)
                    self.assertEqual({job for job, enabled in jobs.items() if enabled},
                                     {'tooling'} if platform != 'macos' else set())
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').read_text()
        tooling = workflow.split('  tooling:\n', 1)[1].split('  result:\n', 1)[0]
        self.assertIn('cargo check --locked --all-targets --manifest-path crates/chopper-python/Cargo.toml', tooling)

    def test_library_publish_controls_run_in_tooling_without_publishing(self):
        paths = ['scripts/publish-library-release.py', 'scripts/test-publish-library-release.py']
        for path in paths:
            for platform in ('linux', 'windows'):
                jobs = scope.classify([path], platform=platform)
                self.assertEqual({job for job, enabled in jobs.items() if enabled}, {'tooling'})
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').read_text()
        self.assertIn('run: python scripts/test-publish-library-release.py', workflow)
        self.assertNotIn('run: python scripts/publish-library-release.py', workflow)

    def test_job_authoring_artifact_and_guide_select_native_checks(self):
        for path in ('schemas/0.5.0/job.schema.json', 'docs/job-json.md',
                     'scripts/test-job-schema.py', 'scripts/requirements-job-schema.txt',
                     'docs/cli-reference.md', 'docs/job-recipes.md',
                     'scripts/cli-reference.py', 'scripts/test-job-recipes.py', 'docs/native-manifest.md',
                     'examples/verify_manifest.py', 'scripts/test-native-manifest.py',
                     'docs/compatibility.md', 'scripts/test-release-upgrade.py',
                     'scripts/fixtures/release-upgrade/v0.3.0/input.csv.zst'):
            self.assertEqual(self.selected(path), {'native'}, path)

    def test_packaged_job_selects_native_browser_and_packaging_checks(self):
        self.assertEqual(self.selected('examples/quickstart-job.json'), {'native', 'browser', 'tooling'})

    def test_native_engine_and_vendored_code_reach_browser_and_python(self):
        for path in ('crates/chopper/src/storage.rs', 'vendor/zip-2.4.2/src/lib.rs'):
            self.assertEqual(self.selected(path), {'native', 'features', 'browser', 'tooling'})
        self.assertEqual(self.selected('crates/chopper-browser/src/lib.rs'), {'native', 'features', 'browser'})

    def test_ui_checks_embedded_and_hosted_builds(self):
        self.assertEqual(self.selected('ui/src/app.ts'), {'native', 'browser'})

    def test_ownership_boundaries_select_their_own_checks(self):
        self.assertEqual(self.selected('scripts/windows-native.py'), {'tooling'})
        for path in ('scripts/package-release.py', 'scripts/test-package-release.py',
                     'docs/releases/native-quickstart.txt'):
            self.assertEqual(self.selected(path), {'tooling'})
        self.assertEqual(self.selected('docs/releases/native-usage.txt'), {'browser', 'tooling'})
        self.assertEqual(self.selected('docs/formula-functions.md'), {'browser'})
        self.assertEqual(self.selected('scripts/browser-artifacts.mjs'), {'browser', 'tooling'})
        for path in ('scripts/browser-small-contract.mjs', 'scripts/browser-small-observer.mjs', 'scripts/browser-small-observer.test.mjs', 'scripts/browser-launch.mjs', 'scripts/browser-acceptance.mjs', 'scripts/browser-acceptance.test.mjs', 'scripts/test-browser-editor-submission.mjs', 'scripts/test-browser-cleanup.mjs', 'scripts/test-browser-graph-lifecycle.mjs', 'scripts/test-browser-graph-inspection.mjs',
                     'scripts/graph-codec-fixtures.py', 'scripts/test-browser-graph-bounds.mjs',
                     'scripts/benchmark-execution-graph.mjs', 'scripts/analyze-execution-graph.py',
                     'scripts/test-execution-graph-analysis.py', 'scripts/extend-execution-graph-analysis.py',
                     'scripts/final-execution-graph-analysis.py',
                     'scripts/execution_graph_statistics.py', 'scripts/test-execution-graph-extension.py'):
            self.assertEqual(self.selected(path), {'browser'})
        self.assertEqual(self.selected('docs/benchmarks/new.jsonl', 'scripts/evidence-resolver.py'), {'evidence'})

    def test_workflow_policy_locks_and_unknown_paths_run_everything(self):
        for path in ('.github/workflows/ci.yml', 'scripts/ci-scope.py', 'scripts/local-ci.py',
                     'scripts/test-local-ci.py', 'Cargo.lock', '.gitattributes', 'new/code.rs',
                     'evidence-site/worker.mjs', 'evidence-site/manifest.v1.json'):
            self.assertEqual(self.selected(path), set(scope.JOBS))
        self.assertEqual(scope.classify([], full=True), dict.fromkeys(scope.JOBS, True))

    def test_small_python_controls_keep_browser_and_add_owning_tooling(self):
        for path in ('scripts/browser-small-runner.py', 'scripts/browser-small-windows.py',
                     'scripts/test-browser-small-runner.py'):
            for platform, expected in (('all', {'browser', 'tooling'}),
                                       ('linux', {'browser', 'tooling'}),
                                       ('windows', {'tooling'}), ('macos', set())):
                with self.subTest(path=path, platform=platform):
                    jobs = scope.classify([path], platform=platform)
                    self.assertEqual(jobs, {job: job in expected for job in scope.JOBS})

    def test_small_python_routing_preserves_unions_and_unknown_fallback(self):
        for path in ('scripts/browser-small-runner.py', 'scripts/browser-small-windows.py',
                     'scripts/test-browser-small-runner.py'):
            for platform in scope.PLATFORM_JOBS:
                with self.subTest(path=path, platform=platform):
                    combined = scope.classify([path, 'ui/src/app.ts', 'docs/performance.md'],
                                              platform=platform)
                    expected = {'browser', 'tooling', 'native', 'evidence'}
                    self.assertEqual(combined, {job: job in expected and job in scope.PLATFORM_JOBS[platform]
                                                for job in scope.JOBS})
                    self.assertEqual(scope.classify([path, 'new/unknown.py'], platform=platform),
                                     scope.classify([], full=True, platform=platform))

    def test_small_mjs_and_other_browser_helpers_remain_browser_only(self):
        for path in ('scripts/browser-small-contract.mjs', 'scripts/browser-small-bootstrap.mjs',
                     'scripts/browser-small-bootstrap.test.mjs', 'scripts/browser-small-observer.mjs',
                     'scripts/browser-small-observer.test.mjs', 'scripts/browser-launch.mjs',
                     'scripts/test-browser-cleanup.mjs'):
            with self.subTest(path=path):
                self.assertEqual(self.selected(path), {'browser'})
                self.assertFalse(any(scope.classify([path], platform='windows').values()))

    def test_browser_only_focused_suites_are_imported_by_the_selected_job(self):
        root = Path(__file__).resolve().parents[1]
        entry = (root / 'scripts/browser-acceptance.test.mjs').read_text()
        workflow = (root / '.github/workflows/ci.yml').read_text()
        browser = workflow.split('  browser:\n', 1)[1].split('  tooling:\n', 1)[0]
        self.assertIn('node --test scripts/browser-acceptance.test.mjs', browser)
        for source, suite in [('browser-small-bootstrap.mjs', 'browser-small-bootstrap.test.mjs'),
                              ('browser-launch.mjs', 'browser-launch-options.test.mjs')]:
            for name in (source, suite):
                self.assertEqual(self.selected('scripts/' + name), {'browser'})
            self.assertIn("import './" + suite + "';", entry)

    def test_browser_build_controls_cover_both_host_platforms(self):
        for name in ('build-browser.mjs', 'build-browser.sh', 'browser-build.test.mjs'):
            self.assertEqual(self.selected('scripts/' + name), {'browser', 'tooling'})
            self.assertTrue(scope.classify(['scripts/' + name], platform='windows')['tooling'])

    def test_small_python_selected_tooling_cannot_be_skipped_by_result_gate(self):
        for platform in ('linux', 'windows'):
            with self.subTest(platform=platform):
                jobs = scope.classify(['scripts/browser-small-runner.py'], platform=platform)
                results = {scope.JOB_IDS[job]: {'result': 'success' if enabled else 'skipped'}
                           for job, enabled in jobs.items()}
                results['changes'] = {'result': 'success', 'outputs':
                                      {job: str(enabled).lower() for job, enabled in jobs.items()}}
                self.assertEqual(scope.failed_jobs(results), [])
                results['tooling']['result'] = 'skipped'
                self.assertEqual(scope.failed_jobs(results), ['tooling'])

    def test_performance_registry_and_its_contract_links_select_evidence(self):
        for path in ('docs/performance/decisions/example.json', 'docs/performance/decision.schema.json',
                     'docs/performance/README.md', 'docs/performance-overview.md',
                     'scripts/performance-registry.py', 'scripts/test-performance-registry.py',
                     'scripts/evidence-documents.py', 'scripts/performance-narratives.py',
                     'scripts/test-performance-narratives.py', 'scripts/evidence-views.py',
                     'scripts/test-evidence-views.py', 'docs/validation-index.md',
                     'docs/specification.md', 'docs/pipeline-rewrites.md', 'docs/validation.md',
                     'docs/direct-execution.md', 'docs/resource-policy-research.md',
                     'docs/csv-ingestion-techniques.md'):
            self.assertEqual(self.selected(path), {'evidence'}, path)

    def test_combined_change_sets_are_a_union(self):
        self.assertEqual(self.selected('scripts/windows-native.py', 'docs/performance.md'), {'tooling', 'evidence'})

    def test_local_platform_profiles_select_only_their_workflow_jobs(self):
        for platform, expected in [('windows', {'native', 'tooling'}), ('macos', {'native'})]:
            selected = scope.classify([], full=True, platform=platform)
            self.assertEqual({job for job, enabled in selected.items() if enabled}, expected)
        self.assertFalse(any(scope.classify(['README.md'], platform='windows').values()))
        self.assertEqual(scope.classify([], full=True, platform='linux'), scope.classify([], full=True))

    def test_evidence_tools_and_artifacts_keep_their_checks_without_site_manifest(self):
        for path in ('scripts/evidence-migration.py', 'scripts/test-evidence-migration.py',
                     'scripts/evidence-resolver.py', 'docs/benchmarks/archived-original.json'):
            self.assertEqual(self.selected(path), {'evidence'})

    def test_workflow_jobs_and_outputs_match_classifier_after_reader_retirement(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/ci.yml').read_text()
        self.assertNotIn('evidence-site', workflow)
        self.assertNotIn('outputs.site', workflow)
        outputs = workflow.split('    outputs:\n', 1)[1].split('    steps:\n', 1)[0]
        self.assertEqual({line.strip().split(':', 1)[0] for line in outputs.splitlines()},
                         set(scope.JOBS))
        result = workflow.split('  result:\n', 1)[1]
        needs = next(line.strip() for line in result.splitlines() if line.strip().startswith('needs: ['))
        self.assertEqual(set(needs.removeprefix('needs: [').removesuffix(']').split(', ')),
                         {'changes', *scope.JOB_IDS.values()})

    def test_result_gate_allows_only_intentional_skips(self):
        results = {job: {'result': 'skipped'} for job in scope.JOB_IDS.values()}
        results['changes'] = {'result': 'success', 'outputs': dict.fromkeys(scope.JOBS, 'false')}
        self.assertEqual(scope.failed_jobs(results), [])
        results['changes']['outputs']['browser'] = 'true'
        self.assertEqual(scope.failed_jobs(results), ['browser'])
        results['browser']['result'] = 'success'
        self.assertEqual(scope.failed_jobs(results), [])
        results['browser']['result'] = 'cancelled'
        self.assertEqual(scope.failed_jobs(results), ['browser'])
        results['changes']['result'] = 'failure'
        self.assertIn('changes', scope.failed_jobs(results))

    def test_missing_planner_outputs_cannot_pass(self):
        self.assertEqual(scope.failed_jobs({'changes': {'result': 'success', 'outputs': {}}}), ['changes'])

    def test_every_selected_job_requires_success(self):
        # Each routed job must fail closed independently, including absent results.
        for flag, job in scope.JOB_IDS.items():
            for status in ('success', 'failure', 'cancelled', 'skipped', None):
                with self.subTest(job=job, status=status):
                    results = {name: {'result': 'skipped'} for name in scope.JOB_IDS.values()}
                    flags = dict.fromkeys(scope.JOBS, 'false')
                    flags[flag] = 'true'
                    results['changes'] = {'result': 'success', 'outputs': flags}
                    if status is None:
                        del results[job]
                    else:
                        results[job] = {'result': status}
                    self.assertEqual(scope.failed_jobs(results), [] if status == 'success' else [job])

    def test_invalid_planner_flags_never_pass_with_successful_jobs(self):
        for flag in scope.JOBS:
            for value in (None, '', 'TRUE', True):
                with self.subTest(flag=flag, value=value):
                    flags = dict.fromkeys(scope.JOBS, 'true')
                    flags[flag] = value
                    results = {job: {'result': 'success'} for job in scope.JOB_IDS.values()}
                    results['changes'] = {'result': 'success', 'outputs': flags}
                    self.assertEqual(scope.failed_jobs(results), ['changes'])

    def test_routing_no_longer_reads_retired_manifest(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected manifest read')):
            self.assertEqual(self.selected('README.md'), set())
            self.assertEqual(self.selected('evidence-site/worker.mjs'), set(scope.JOBS))
            self.assertEqual(self.selected('scripts/evidence-migration.py'), {'evidence'})

    def test_invalid_diff_fails_without_publishing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'outputs'
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('ci-scope.py')),
                                     '--base', 'invalid-base-for-ci-test', '--output', str(output)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
            self.assertIn('invalid-base-for-ci-test', result.stderr)

    def test_real_git_diff_preserves_deleted_and_renamed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'CI test')
            git('config', 'user.email', 'ci-test@example.invalid')
            old = Path('ui/old name.ts')
            new = Path('docs/benchmarks/new name.json')
            (root / old).parent.mkdir(parents=True)
            (root / new).parent.mkdir(parents=True)
            (root / old).write_text('same content\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            (root / old).rename(root / new)
            git('add', '-A')
            git('commit', '-qm', 'rename')
            head = git('rev-parse', 'HEAD')
            for platform, expected in {'linux': {'native', 'browser', 'evidence'}, 'windows': {'native'}}.items():
                with self.subTest(platform=platform):
                    paths, jobs = scope.revision_scope(base, head, root=root, platform=platform)
                    self.assertEqual(set(paths), {old.as_posix(), new.as_posix()})
                    self.assertEqual({job for job, enabled in jobs.items() if enabled}, expected)
                    result = subprocess.check_output(
                        [sys.executable, str(Path(__file__).with_name('ci-scope.py').resolve()),
                         '--base', base, '--head', head, '--platform', platform], cwd=root, text=True)
                    self.assertEqual(json.loads(result), {'paths': paths, 'jobs': jobs})

    def test_revision_scope_preserves_non_utf8_and_newline_in_path(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args, data=None):
                return subprocess.check_output(['git', *args], cwd=directory, input=data).strip()
            git('init', '-q')
            git('config', 'user.name', 'CI test')
            git('config', 'user.email', 'ci-test@example.invalid')
            git('commit', '-qm', 'base', '--allow-empty')
            base = git('rev-parse', 'HEAD').decode('ascii')
            # Store the name in a tree so the host filesystem need not accept it.
            name = b'unclassified-\xff\npath'
            blob = git('hash-object', '-w', '--stdin', data=b'fixture\n')
            tree = git('mktree', '-z', data=b'100644 blob ' + blob + b'\t' + name + b'\0').decode('ascii')
            head = git('commit-tree', tree, '-p', base, '-m', 'add path').decode('ascii')
            paths, jobs = scope.revision_scope(base, head, root=directory)
            self.assertEqual([path.encode('utf-8', errors='surrogateescape') for path in paths], [name])
            self.assertTrue(all(jobs.values()))

    @unittest.skipUnless(os.name == 'posix', 'Relative PATH resolution follows POSIX subprocess rules')
    def test_explicit_root_preserves_relative_git_lookup_from_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            caller = Path(directory)
            root = caller / 'repo'
            root.mkdir()
            subprocess.run(['git', '-C', str(root), 'init', '-q'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=CI test',
                            '-c', 'user.email=ci-test@example.invalid', 'commit',
                            '-qm', 'base', '--allow-empty'], check=True)
            bin_dir = caller / 'bin'
            bin_dir.mkdir()
            launcher = bin_dir / 'git'
            git_path = Path(shutil.which('git')).absolute()
            original_path = os.environ.get('PATH', os.defpath)
            # Resolve the launcher through the relative PATH entry, then allow
            # the discovered Git to find its own shell and other dependencies.
            launcher.write_text(f'#!/bin/sh\nexport PATH={shlex.quote(original_path)}\n'
                                f'exec {shlex.quote(str(git_path))} "$@"\n', encoding='utf-8')
            launcher.chmod(0o755)
            previous = Path.cwd()
            try:
                os.chdir(caller)
                with patch.dict(os.environ, {'PATH': 'bin'}):
                    paths, jobs = scope.revision_scope('HEAD', 'HEAD', root=root)
            finally:
                os.chdir(previous)
            self.assertEqual(paths, [])
            self.assertFalse(any(jobs.values()))

    def test_full_scope_selects_platform_jobs_without_diffing(self):
        with patch.object(scope, 'changed_paths', side_effect=AssertionError('unexpected diff')):
            paths, jobs = scope.revision_scope(None, 'HEAD', full=True, platform='windows')
        self.assertEqual(paths, [])
        self.assertEqual({job for job, enabled in jobs.items() if enabled}, {'native', 'tooling'})


if __name__ == '__main__':
    unittest.main()
