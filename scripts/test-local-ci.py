"""Real Git/subprocess controls for local workflow receipts and main's push guard."""
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('local_ci', Path(__file__).with_name('local-ci.py'))
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class LocalCiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.root = directory / 'working'
        self.remote = directory / 'remote.git'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Local CI test')
        self.git('config', 'user.email', 'ci-test@example.invalid')
        self.git('config', 'core.hooksPath', str(directory / 'unused-hooks'))
        self.git('config', '--unset', 'core.hooksPath')
        # Keep these fixtures independent of the caller's installed push hook.
        (self.root / 'scripts').mkdir()
        for name in ('local-ci.py', 'validation-runner.py', 'ci-scope.py'):
            shutil.copy2(Path(__file__).with_name(name), self.root / 'scripts' / name)
        (self.root / '.github/workflows').mkdir(parents=True)
        (self.root / ci.WORKFLOW).write_text('name: fixture\non: workflow_dispatch\njobs: {}\n')
        (self.root / 'input').write_text('base\n')
        (self.root / '.gitignore').write_text('__pycache__/\n')
        self.commit('base')
        subprocess.run(['git', 'init', '-q', '--bare', str(self.remote)], check=True)
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', '-q', 'origin', 'HEAD:main')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-qb', 'feature')
        (self.root / 'input').write_text('feature\n')
        self.commit('feature')
        self.head = self.git('rev-parse', 'HEAD')

    def git(self, *args):
        return ci.git(self.root, *args)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)

    def check(self, code=0):
        # The runner still executes a real child and writes durable records;
        # unit tests substitute only act/Docker, not the Git or receipt checks.
        run = subprocess.run
        capture = subprocess.check_output
        which = shutil.which

        def docker_run(argv, **kwargs):
            if argv[0] == 'docker':
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)

        def docker_capture(argv, **kwargs):
            if argv[0] == 'docker':
                return 'Docker fixture\n'
            return capture(argv, **kwargs)

        with (patch.object(ci, 'reject_act_config'),
              patch.object(ci.shutil, 'which', side_effect=lambda name: sys.executable if name == 'act' else which(name)),
              patch.object(ci, 'act_command', return_value=[sys.executable, '-c', f'raise SystemExit({code})']),
              patch.object(ci.subprocess, 'run', side_effect=docker_run),
              patch.object(ci.subprocess, 'check_output', side_effect=docker_capture)):
            return ci.check(self.root)

    def test_command_executes_workflow_without_copying_its_checks(self):
        with patch.dict(os.environ, {}, clear=True):
            command = ci.act_command('/act', self.base, Path('/logs'), profile='linux')
        self.assertEqual(command[:4], ['/act', 'workflow_dispatch', '--workflows', ci.WORKFLOW])
        self.assertIn('local_platform=linux', command)
        self.assertIn('base_sha=' + self.base, command)
        self.assertNotIn('--job', command)
        self.assertNotIn('--dryrun', command)
        self.assertIn('--use-gitignore=false', command)
        self.assertEqual(command[command.index('--container-options')+1],
                         '--init --label=chopper.local-ci=logs')
        self.assertNotIn('base_sha=' + self.base, ci.act_command('/act', self.base, Path('/logs'), full=True))
        windows = ci.act_command('/act', self.base, Path('/logs'), profile='windows')
        self.assertIn('windows-latest=-self-hosted', windows)
        self.assertNotIn('--container-architecture', windows)
        self.assertNotIn('--container-options', windows)

    def test_git_bash_discovery_handles_both_windows_git_path_layouts(self):
        install = self.root.parent / 'Git'
        (install / 'bin').mkdir(parents=True)
        (install / 'bin/bash.exe').touch()
        for location in ('cmd/git.exe', 'mingw64/bin/git.exe'):
            executable = install / location
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.touch()
            self.assertEqual(ci.git_bash_directory(executable), install / 'bin')

    def test_windows_handoff_checks_out_pushed_head_under_native_lock(self):
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/feature')
        self.git('switch', '-q', 'main')
        lock = self.root.parent / 'windows-ci.lock'
        foreign = self.root.parent / 'foreign'
        subprocess.run(['git', 'clone', '-q', '--branch', 'main', str(self.remote), str(foreign)], check=True)

        def validate(root, full, *, expected_head, expected_base):
            self.assertEqual((root, full, expected_head, expected_base),
                             (self.root, True, self.head, self.base))
            self.assertEqual(self.git('rev-parse', 'HEAD'), self.head)
            self.assertEqual(self.git('rev-parse', 'refs/heads/main'), self.base)
            with self.assertRaisesRegex(ValueError, 'Cannot acquire host lock'):
                with ci.host_lock():
                    self.fail('handoff must hold the native CI lock during validation')

        with (patch.object(ci, 'host_profile', return_value='windows'),
              patch.object(ci, 'host_lock_path', return_value=lock),
              patch.dict(os.environ, {'GIT_DIR': str(foreign / '.git'), 'GIT_WORK_TREE': str(foreign)}),
              patch.object(ci.runpy, 'run_path', return_value={'check': validate}) as load):
            ci.check_windows_revision(self.root, self.head, self.base, 'refs/heads/feature', full=True)
        load.assert_called_once_with(str(self.root / 'scripts/local-ci.py'))
        self.assertEqual(ci.git(foreign, 'rev-parse', 'HEAD'), self.base)
        self.assertFalse((foreign / '.git/FETCH_HEAD').exists())

    def test_windows_handoff_preserves_head_on_dirty_checkout_or_revision_mismatch(self):
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/feature')
        self.git('switch', '-q', 'main')
        dirty = self.root / 'untracked'
        dirty.write_text('keep')
        with (patch.object(ci, 'host_profile', return_value='windows'),
              patch.object(ci, 'host_lock_path', return_value=self.root.parent / 'windows-ci.lock'),
              patch.object(ci.runpy, 'run_path') as load):
            with self.assertRaisesRegex(ValueError, 'uncommitted'):
                ci.check_windows_revision(self.root, self.head, self.base, 'refs/heads/feature')
            self.assertEqual(dirty.read_text(), 'keep')
            dirty.unlink()
            with self.assertRaisesRegex(ValueError, 'differs from the WSL base'):
                ci.check_windows_revision(self.root, self.head, self.head, 'refs/heads/feature')
            with self.assertRaisesRegex(ValueError, 'Push the current branch'):
                ci.check_windows_revision(self.root, self.base, self.base, 'refs/heads/feature')
        load.assert_not_called()
        self.assertEqual(self.git('symbolic-ref', 'HEAD'), 'refs/heads/main')

    def test_windows_handoff_preserves_a_paused_merge_with_no_file_changes(self):
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/feature')
        self.git('switch', '-qc', 'empty-change', self.base)
        self.git('commit', '--allow-empty', '-qm', 'merge without file changes')
        self.git('switch', '-q', 'main')
        self.git('merge', '--no-commit', '--no-ff', 'empty-change')
        merge_head = self.git('rev-parse', 'MERGE_HEAD')
        self.assertEqual(self.git('status', '--porcelain'), '')

        with (patch.object(ci, 'host_profile', return_value='windows'),
              patch.object(ci, 'host_lock_path', return_value=self.root.parent / 'windows-ci.lock'),
              patch.object(ci.runpy, 'run_path') as load):
            with self.assertRaises(subprocess.CalledProcessError):
                ci.check_windows_revision(self.root, self.head, self.base, 'refs/heads/feature')
        load.assert_not_called()
        self.assertEqual(self.git('symbolic-ref', 'HEAD'), 'refs/heads/main')
        self.assertEqual(self.git('rev-parse', 'MERGE_HEAD'), merge_head)

    def test_windows_handoff_refuses_nested_paths_and_active_bisects(self):
        self.git('push', '-q', 'origin', 'HEAD:refs/heads/feature')
        self.git('switch', '-q', 'main')
        with (patch.object(ci, 'host_profile', return_value='windows'),
              patch.object(ci, 'host_lock_path', return_value=self.root.parent / 'windows-ci.lock'),
              patch.object(ci.runpy, 'run_path') as load):
            with self.assertRaisesRegex(ValueError, 'root of the native Windows Git checkout'):
                ci.check_windows_revision(self.root / 'scripts', self.head, self.base, 'refs/heads/feature')
            self.assertEqual(self.git('symbolic-ref', 'HEAD'), 'refs/heads/main')
            self.git('bisect', 'start')
            head = self.git('rev-parse', 'HEAD')
            with self.assertRaisesRegex(ValueError, 'active Git bisect'):
                ci.check_windows_revision(self.root, self.head, self.base, 'refs/heads/feature')
            self.assertEqual(self.git('rev-parse', 'HEAD'), head)
            self.assertTrue((self.root / '.git/BISECT_START').exists())
        load.assert_not_called()

    def test_windows_dispatch_success_requires_an_exact_receipt(self):
        self.git('config', 'chopper.windowsCheckout', str(self.root))
        self.git('update-ref', 'refs/remotes/origin/main', self.head)
        invoke = subprocess.run
        capture = subprocess.check_output
        dispatches = []

        def run(argv, **kwargs):
            if argv[1] == str(self.root / 'scripts/windows-native.py'):
                dispatches.append(argv)
                return subprocess.CompletedProcess(argv, 0)
            return invoke(argv, **kwargs)

        def check_output(argv, **kwargs):
            if argv[0] == 'wslpath':
                return str(self.root / 'scripts/local-ci.py')
            return capture(argv, **kwargs)

        receipt = ci.receipt_path(self.root, self.head, self.base, 'windows')
        with (patch.object(ci.subprocess, 'run', side_effect=run),
              patch.object(ci.subprocess, 'check_output', side_effect=check_output)):
            with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
                ci.check_windows(self.root)
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'version': 1, 'head': self.head,
                                           'base': self.head, 'profile': 'windows'}))
            with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
                ci.check_windows(self.root, full=True)
        self.assertEqual(len(dispatches), 2)
        revisions = [self.head, self.base, 'refs/heads/feature']
        self.assertEqual(dispatches[0][-3:], revisions)
        self.assertEqual(dispatches[1][-4:], [*revisions, '--full'])
        self.assertEqual(self.git('rev-parse', 'refs/remotes/origin/main'), self.head)

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Evidence checks belong to the Linux profile')
    def test_evidence_cache_is_verified_staged_and_selected_by_workflow_scope(self):
        source = self.root.parent / 'frozen'
        (source / 'docs').mkdir(parents=True)
        payload = b'exact archived original\n'
        sha = hashlib.sha256(payload).hexdigest()
        alias = 'docs/benchmarks/cached.json'
        registry = {'schema_version': 1,
                    'bundles': {sha: {'bytes': len(payload), 'sha256': sha,
                                     'reader': 'r2://chopper-archive-private/sha256/' + sha}},
                    'artifacts': {alias: {'bytes': len(payload), 'sha256': sha,
                                         'bundle': sha, 'member': 'objects/' + sha}}}
        (source / 'docs/evidence-registry.v1.json').write_text(json.dumps(registry))
        cache = self.root / 'scratch/evidence-cache'
        cache.mkdir(parents=True)
        blob = cache / sha
        blob.write_bytes(payload)
        self.assertEqual(ci.stage_evidence(self.root, source, self.head, self.head), [])
        self.assertFalse((source / alias).exists())
        self.assertEqual(ci.stage_evidence(self.root, source, self.base, self.head), [alias])
        self.assertEqual((source / alias).read_bytes(), payload)
        (source / alias).unlink()
        blob.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Evidence cache mismatch'):
            ci.stage_evidence(self.root, source, self.base, self.head)
        self.assertFalse((source / alias).exists())

    def test_pass_is_bound_to_commit_and_clean_worktree(self):
        self.assertEqual(self.check(), (self.head, self.base))
        ci.verify(self.root, self.head, self.base)
        (self.root / 'input').write_text('dirty\n')
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            ci.verify(self.root, self.head, self.base)
        self.commit('new revision')
        with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
            ci.verify(self.root, self.git('rev-parse', 'HEAD'), self.base)

    def test_failed_rerun_revokes_previous_pass_and_retains_logs(self):
        self.check()
        with self.assertRaisesRegex(ValueError, 'failed or was incomplete'):
            self.check(code=7)
        with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
            ci.verify(self.root, self.head, self.base)
        states = [json.loads(path.read_text()) for path in ci.storage(self.root).glob('attempt-*/batch/status.json')]
        self.assertEqual(sorted(state['attempts'][0]['exit_code'] for state in states), [0, 7])

    def test_changed_record_cannot_authorize_a_push(self):
        self.check()
        receipt = json.loads(ci.receipt_path(self.root, self.head, self.base).read_text())
        Path(receipt['status']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
            ci.verify(self.root, self.head, self.base)

    def test_advanced_main_requires_a_new_pass(self):
        self.check()
        # Even an intervening remote revision already included in HEAD changes
        # the required base identity; no old receipt may authorize that push.
        with self.assertRaisesRegex(ValueError, 'No intact local CI pass'):
            ci.pre_push(self.root, io.StringIO(f'refs/heads/feature {self.head} refs/heads/main {self.head}\n'))
        self.git('checkout', '-q', 'main')
        (self.root / 'other').write_text('concurrent main\n')
        self.commit('concurrent main')
        self.git('push', '-q', 'origin', 'HEAD:main')
        self.git('checkout', '-q', 'feature')
        with self.assertRaisesRegex(ValueError, 'Merge or rebase'):
            self.check()

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Delivery hooks run in Linux/WSL')
    def test_actual_pre_push_hook_blocks_unvalidated_main_then_allows_pass(self):
        ci.install_hooks(self.root)
        push = ['git', '-C', str(self.root), 'push', 'origin', 'HEAD:main']
        denied = subprocess.run(push, capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('No intact local CI pass', denied.stderr)
        self.check()
        denied_windows = subprocess.run(push, capture_output=True, text=True)
        self.assertNotEqual(denied_windows.returncode, 0)
        self.assertIn('Native Windows validation is required', denied_windows.stderr)
        # Simulate a separately completed Windows workflow fixture. The actual
        # Windows command and profile routing are checked independently above.
        receipt = json.loads(ci.receipt_path(self.root, self.head, self.base).read_text())
        receipt['profile'] = 'windows'
        windows = self.root.parent / 'windows'
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(self.root), str(windows)], check=True)
        destination = ci.receipt_path(windows, self.head, self.base, 'windows')
        destination.parent.mkdir(parents=True)
        destination.write_text(json.dumps(receipt))
        self.git('config', 'chopper.windowsCheckout', str(windows))
        # Linked-worktree hooks inherit this context even though standalone
        # fixture pushes do not always populate these variables themselves.
        hook_environment = dict(os.environ, GIT_DIR=self.git('rev-parse', '--absolute-git-dir'),
                                GIT_WORK_TREE=str(self.root))
        subprocess.run(push, check=True, capture_output=True, env=hook_environment)
        self.assertEqual(subprocess.check_output(['git', '--git-dir', str(self.remote),
                                                'rev-parse', 'main'], text=True).strip(), self.head)

    def test_guard_allows_feature_pushes_and_blocks_main_deletion(self):
        ci.pre_push(self.root, io.StringIO(f'refs/heads/feature {self.head} refs/heads/feature {"0" * 40}\n'))
        with self.assertRaisesRegex(ValueError, 'deletion'):
            ci.pre_push(self.root, io.StringIO(f'(delete) {"0" * 40} refs/heads/main {self.base}\n'))

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Delivery hooks run in Linux/WSL')
    def test_shared_hook_allows_older_feature_branches_without_the_runner(self):
        ci.install_hooks(self.root)
        self.git('rm', '-q', 'scripts/local-ci.py')
        self.commit('older branch without local CI')
        self.git('push', '-q', 'origin', 'HEAD:feature')

    def test_existing_hooks_and_hook_configuration_are_preserved(self):
        hooks = Path(self.git('rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
        hook = hooks / 'pre-push'
        hook.write_text('#!/bin/sh\nexit 0\n')
        with self.assertRaisesRegex(ValueError, 'Existing hook preserved'):
            ci.install_hooks(self.root)
        self.assertEqual(hook.read_text(), '#!/bin/sh\nexit 0\n')
        self.git('config', 'core.hooksPath', 'custom-hooks')
        with self.assertRaisesRegex(ValueError, 'already configured'):
            ci.install_hooks(self.root)

    def test_land_never_pushes_after_a_failed_check(self):
        with (patch.object(ci, 'install_hooks'), patch.object(ci, 'check', side_effect=ValueError('failed')),
              patch.object(ci.subprocess, 'run') as run):
            with self.assertRaisesRegex(ValueError, 'failed'):
                ci.land(self.root)
        run.assert_not_called()

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Delivery hooks run in Linux/WSL')
    def test_land_routes_and_pushes_in_the_selected_repository(self):
        self.check()
        receipt = json.loads(ci.receipt_path(self.root, self.head, self.base).read_text())
        receipt['profile'] = 'windows'
        ci.receipt_path(self.root, self.head, self.base, 'windows').write_text(json.dumps(receipt))
        self.git('config', 'chopper.windowsCheckout', str(self.root))

        foreign = self.root.parent / 'foreign'
        foreign_remote = self.root.parent / 'foreign.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(self.remote), str(foreign_remote)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.root), str(foreign)], check=True)
        ci.git(foreign, 'remote', 'set-url', 'origin', str(foreign_remote))
        ci.git(foreign, 'config', 'core.hooksPath', 'unrelated-hooks')
        with (patch.dict(os.environ, {'GIT_DIR': str(foreign / '.git'), 'GIT_WORK_TREE': str(foreign)}),
              patch.object(ci, 'check', return_value=(self.head, self.base))):
            ci.land(self.root)
        self.assertEqual(ci.git(self.remote, 'rev-parse', 'main'), self.head)
        self.assertEqual(ci.git(foreign_remote, 'rev-parse', 'main'), self.base)


class LocalCiInvocationTests(unittest.TestCase):
    """Two real main()/runner processes; only external act/Docker are fixtures."""
    setUp = LocalCiTests.setUp
    git = LocalCiTests.git
    commit = LocalCiTests.commit

    def prepare_invocations(self):
        directory = self.root.parent
        self.lock = directory / 'shared-host.lock'
        self.resource = directory / 'act-container'
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(10)
        self.addCleanup(self.listener.close)
        self.fixture = directory / 'fake-act.py'
        self.fixture.write_text("""
from pathlib import Path
import socket
import sys
resource = Path(sys.argv[1])
try:
    resource.touch(exist_ok=False)
except FileExistsError:
    print('shared act container already exists', file=sys.stderr)
    raise SystemExit(91)
try:
    with socket.create_connection(('127.0.0.1', int(sys.argv[2])), timeout=10) as peer:
        peer.sendall(b'act')
        code = int(peer.recv(32))
        resource.unlink()
        peer.sendall(b'released')
finally:
    resource.unlink(missing_ok=True)
raise SystemExit(code)
""")
        self.bootstrap = directory / 'invoke.py'
        self.bootstrap.write_text("""
import importlib.util
from pathlib import Path
import shutil
import socket
import subprocess
import sys
spec = importlib.util.spec_from_file_location('local_ci', Path.cwd() / 'scripts/local-ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)
# Explicit fixture path, shared even by unrelated repositories. No production override.
arguments = sys.argv[:]
ci.host_lock_path = lambda: Path(arguments[1])
ci.reject_act_config = lambda root: None
which = shutil.which
ci.shutil.which = lambda name: sys.executable if name == 'act' else which(name)
act_command = ci.act_command
def fake_act(*args, **kwargs):
    if arguments[5] == 'hold-before-act':
        with socket.create_connection(('127.0.0.1', int(arguments[4])), timeout=10) as peer:
            peer.sendall(b'before-act')
            peer.recv(32)
    command = act_command(*args, **kwargs)
    return [command[0], arguments[2], arguments[3], arguments[4], *command[1:]]
ci.act_command = fake_act
run = subprocess.run
capture = subprocess.check_output
def fake_run(argv, **kwargs):
    if argv[0] == 'docker':
        return subprocess.CompletedProcess(argv, 0)
    if argv[0] == 'git' and 'push' in argv and arguments[5] == 'hold-push':
        with socket.create_connection(('127.0.0.1', int(arguments[4])), timeout=10) as peer:
            peer.sendall(b'push')
            peer.recv(32)
    return run(argv, **kwargs)
def fake_capture(argv, **kwargs):
    if argv[0] == 'docker':
        if argv[1] == 'ps' and arguments[5] == 'hold-cleanup':
            with socket.create_connection(('127.0.0.1', int(arguments[4])), timeout=10) as peer:
                peer.sendall(b'cleanup')
                peer.recv(32)
        return ''
    return capture(argv, **kwargs)
ci.subprocess.run = fake_run
ci.subprocess.check_output = fake_capture
sys.argv = [sys.argv[0], arguments[6]]
raise SystemExit(ci.main())
""")

    def invoke(self, root=None, command='check', phase='normal'):
        process = subprocess.Popen([sys.executable, str(self.bootstrap), str(self.lock),
                                    str(self.fixture), str(self.resource),
                                    str(self.listener.getsockname()[1]),
                                    phase, command],
                                   cwd=root or self.root, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        def reap():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(reap)
        return process

    def accept(self, expected=b'act'):
        peer, _ = self.listener.accept()
        peer.settimeout(10)
        self.addCleanup(peer.close)
        self.assertEqual(peer.recv(32), expected)
        return peer

    def finish(self, process, peer, code=0):
        peer.sendall(str(code).encode())
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0 if code == 0 else 1, output + error)
        return output, error

    def contender(self, root, command='check'):
        receipt = ci.receipt_path(root, self.head, self.base)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        if not receipt.exists():
            receipt.write_text('previous receipt must survive contention')
        previous_receipt = receipt.read_bytes()
        before = sorted(str(path) for path in ci.storage(root).glob('attempt-*'))
        hooks = Path(ci.git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
        hook = hooks / 'pre-push'
        previous_hook = hook.read_bytes() if hook.exists() else None
        process = self.invoke(root, command)
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 1, output + error)
        logs = '\n'.join(path.read_text() for path in ci.storage(root).glob('attempt-*/batch/*-stderr.log'))
        self.assertIn('another local CI check/land operation', error, error + logs)
        self.assertEqual(receipt.read_bytes(), previous_receipt)
        self.assertEqual(sorted(str(path) for path in ci.storage(root).glob('attempt-*')), before)
        self.assertEqual(hook.read_bytes() if hook.exists() else None, previous_hook)
        self.assertEqual(subprocess.check_output(['git', '--git-dir', str(self.remote),
                                                 'rev-parse', 'main'], text=True).strip(), self.base)

    def test_independent_repositories_reject_overlapping_check_and_land(self):
        self.prepare_invocations()
        other = self.root.parent / 'independent'
        subprocess.run(['git', 'clone', '-q', str(self.root), str(other)], check=True)
        ci.git(other, 'remote', 'set-url', 'origin', str(self.remote))
        holder = self.invoke()
        peer = self.accept()
        self.contender(other)
        self.contender(other, 'land')
        self.finish(holder, peer)
        successor = self.invoke(other)
        self.finish(successor, self.accept())
        ci.verify(other, self.head, self.base)

    def test_linked_worktree_contender_preserves_receipt_and_lock_file(self):
        self.prepare_invocations()
        linked = self.root.parent / 'linked'
        self.git('worktree', 'add', '-q', '--detach', str(linked), self.head)
        self.lock.write_text('stale contents are not ownership')
        identity = self.lock.stat()
        holder = self.invoke()
        peer = self.accept()
        self.contender(linked)
        self.finish(holder, peer)
        self.assertTrue(os.path.samestat(identity, self.lock.stat()))
        self.assertEqual(self.lock.read_text(), 'stale contents are not ownership')
        successor = self.invoke(linked)
        self.finish(successor, self.accept())
        ci.verify(linked, self.head, self.base)

    def test_normal_failure_and_stale_file_release(self):
        self.prepare_invocations()
        self.lock.write_text('stale PID 12345')
        identity = self.lock.stat()
        for code in (0, 7, 0):
            holder = self.invoke()
            self.finish(holder, self.accept(), code)
            self.assertTrue(os.path.samestat(identity, self.lock.stat()))
            if code:
                self.assertFalse(ci.receipt_path(self.root, self.head, self.base).exists())
            else:
                ci.verify(self.root, self.head, self.base)
        states = [json.loads(path.read_text()) for path in
                  ci.storage(self.root).glob('attempt-*/batch/status.json')]
        self.assertEqual(sorted(state['attempts'][0]['exit_code'] for state in states), [0, 0, 7])

    def test_process_death_releases_actual_ownership(self):
        self.prepare_invocations()
        holder = self.invoke(phase='hold-before-act')
        self.accept(b'before-act')
        self.contender(self.root)
        identity = self.lock.stat()
        holder.kill()
        holder.communicate(timeout=10)
        successor = self.invoke()
        self.finish(successor, self.accept())
        self.assertTrue(os.path.samestat(identity, self.lock.stat()))
        ci.verify(self.root, self.head, self.base)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows open/delete sharing')
    def test_windows_live_lock_cannot_be_unlinked(self):
        self.prepare_invocations()
        holder = self.invoke(phase='hold-before-act')
        before = self.accept(b'before-act')
        with self.assertRaises(PermissionError):
            self.lock.unlink()
        replacement = self.root.parent / 'replacement.lock'
        replacement.touch()
        with self.assertRaises(PermissionError):
            replacement.replace(self.lock)
        self.contender(self.root)
        before.sendall(b'continue')
        self.finish(holder, self.accept())

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Docker teardown belongs to the Linux profile')
    def test_lock_covers_teardown(self):
        self.prepare_invocations()
        holder = self.invoke(phase='hold-cleanup')
        self.accept().sendall(b'0')
        cleanup = self.accept(b'cleanup')
        self.contender(self.root, 'land')
        self.finish(holder, cleanup)

    @unittest.skipUnless(ci.host_profile() == 'linux', 'Delivery runs in Linux/WSL')
    def test_land_holds_lock_through_real_guarded_push(self):
        self.prepare_invocations()
        holder = self.invoke()
        self.finish(holder, self.accept())
        # Fixture Windows receipt only: this test exercises delivery verification,
        # not native Windows execution. No real host receipt is created.
        receipt = json.loads(ci.receipt_path(self.root, self.head, self.base).read_text())
        receipt['profile'] = 'windows'
        ci.receipt_path(self.root, self.head, self.base, 'windows').write_text(json.dumps(receipt))
        self.git('config', 'chopper.windowsCheckout', str(self.root))
        holder = self.invoke(command='land', phase='hold-push')
        self.accept().sendall(b'0')
        push = self.accept(b'push')
        self.contender(self.root)
        self.finish(holder, push)
        self.assertEqual(subprocess.check_output(['git', '--git-dir', str(self.remote),
                                                 'rev-parse', 'main'], text=True).strip(), self.head)

    def test_lock_open_failure_is_closed_before_side_effects(self):
        self.prepare_invocations()
        self.lock.mkdir()
        process = self.invoke(command='land')
        output, error = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 1, output + error)
        self.assertIn('Local CI blocked:', error)
        self.assertFalse(ci.storage(self.root).exists())
        hook = Path(self.git('rev-parse', '--path-format=absolute', '--git-path', 'hooks')) / 'pre-push'
        self.assertFalse(hook.exists())

    def test_default_host_lock_does_not_follow_checkout_or_cache_settings(self):
        expected = ci.host_lock_path()
        with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root), 'TMPDIR': str(self.remote)}):
            self.assertEqual(ci.host_lock_path(), expected)
        self.assertNotIn(str(self.root), str(expected))

    @unittest.skipUnless(os.name == 'posix', 'POSIX inode-replacement race')
    def test_replaced_lock_inode_fails_closed(self):
        import fcntl
        path = self.root.parent / 'host.lock'
        flock = fcntl.flock

        def replace_after_lock(descriptor, flags):
            flock(descriptor, flags)
            path.unlink()
            path.touch()

        with (patch.object(ci, 'host_lock_path', return_value=path),
              patch.object(fcntl, 'flock', side_effect=replace_after_lock)):
            with self.assertRaisesRegex(ValueError, 'changed during acquisition'):
                with ci.host_lock():
                    self.fail('Replaced inode must never admit a gate')


if __name__ == '__main__':
    unittest.main()
