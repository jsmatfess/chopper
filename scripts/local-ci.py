#!/usr/bin/env python3
"""Execute the CI workflow with act, then guard fast-forward delivery to main."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
import platform
import re
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile


WORKFLOW = '.github/workflows/ci.yml'
IMAGE = 'ghcr.io/catthehacker/ubuntu:act-latest'
HOOK_MARKER = '# chopper-local-ci-v1'
SECRETS = ('CHOPPER_R2_ENDPOINT', 'CHOPPER_R2_READ_ACCESS_KEY_ID',
           'CHOPPER_R2_READ_SECRET_ACCESS_KEY', 'GITHUB_TOKEN')


def host_lock_path():
    # Deliberately independent of repository, Git common directory, cwd, TMPDIR
    # and XDG settings: independent clones still share act's host resources.
    return Path.home() / '.chopper' / 'local-ci.lock'


@contextmanager
def host_lock():
    path = host_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never truncate, replace or unlink this file, even on release. Otherwise
    # waiters could lock an old inode while a newcomer locks its replacement.
    # os.open descriptors are non-inheritable: an unrelated child cannot retain
    # ownership after this process exits. Windows CRT opens also deny deletion.
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                # Byte ranges may extend beyond EOF; no stale-file contents or
                # PID are needed, and LK_NBLCK never waits/retries.
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError(f'Cannot acquire host lock {path}; another local CI check/land operation '
                             'may be active. Retry after it exits; do not delete the lock file. '
                             f'OS error: {error}') from error
        # Detect replacement between open and acquisition rather than running
        # with ownership of an unlinked file. Cooperating callers never unlink.
        if not os.path.samestat(os.fstat(descriptor), path.stat()):
            raise ValueError(f'Host lock file changed during acquisition: {path}. No gate was run.')
        yield
    finally:
        # Closing releases the OS lock on normal/error exit; the OS also closes
        # it after a crash. The durable file itself never denotes ownership.
        os.close(descriptor)


def git(root, *args):
    # Hooks export repository-local Git variables. Clear Git's authoritative
    # list before -C, especially when locating another checkout's receipts.
    environment = dict(os.environ)
    local_variables = subprocess.check_output(['git', 'rev-parse', '--local-env-vars'], text=True).splitlines()
    for name in local_variables:
        environment.pop(name, None)
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, env=environment).strip()


def clean_head(root, expected=None):
    head = git(root, 'rev-parse', 'HEAD')
    if expected is not None and head != expected:
        raise ValueError('The pushed revision must be the checked-out, validated HEAD.')
    if git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Commit or remove uncommitted files before running the local CI gate.')
    return head


def storage(root):
    return Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'local-ci'


def host_profile():
    return {'Linux': 'linux', 'Windows': 'windows', 'Darwin': 'macos'}[platform.system()]


def receipt_path(root, head, base, profile=None):
    return storage(root) / f'{head}-{base}-{profile or host_profile()}.json'


def require_ancestor(root, base, head):
    if subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', base, head]).returncode:
        raise ValueError('Merge or rebase current origin/main into this branch, then rerun local CI.')


def runner_module():
    spec = importlib.util.spec_from_file_location('validation_runner', Path(__file__).with_name('validation-runner.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scope_module():
    spec = importlib.util.spec_from_file_location('ci_scope', Path(__file__).with_name('ci-scope.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def act_command(act, base, directory, full=False, profile=None):
    # No check commands or job list live here. act reads steps, needs and routing
    # directly from the same workflow used by GitHub.
    profile = profile or host_profile()
    label = {'linux': 'ubuntu-latest', 'windows': 'windows-latest', 'macos': 'macos-latest'}[profile]
    command = [act, 'workflow_dispatch', '--workflows', WORKFLOW,
               '--input', 'local_platform=' + profile,
               '--platform', label + '=' + (IMAGE if profile == 'linux' else '-self-hosted'),
               '--concurrent-jobs', '1',
               '--rm', '--use-gitignore=false',
               '--env-file', str(directory / 'empty'), '--var-file', str(directory / 'empty'),
               '--input-file', str(directory / 'empty'), '--secret-file', str(directory / 'empty')]
    if profile == 'linux':
        command += ['--container-architecture', 'linux/amd64', '--container-options',
                    '--init --label=chopper.local-ci=' + directory.name]
    if not full:
        command += ['--input', 'base_sha=' + base]
    for name in SECRETS:
        if os.environ.get(name):
            command += ['--secret', name]  # act reads the value from the environment.
    return command


def reject_act_config(root):
    # act appends user rc flags, which could otherwise turn a gate into --dryrun
    # or a single-job run. Gate invocations accept no additional act arguments.
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    locations = [Path.home() / '.actrc', config / 'act/actrc', root / '.actrc',
                 Path.home() / 'Library/Application Support/act/actrc']
    if os.environ.get('APPDATA'):
        locations.append(Path(os.environ['APPDATA']) / 'act/actrc')
    if os.environ.get('LOCALAPPDATA'):
        locations.append(Path(os.environ['LOCALAPPDATA']) / 'act/actrc')
    for path in locations:
        if path.exists():
            raise ValueError(f'Local CI requires no act rc overrides: move {path} aside first.')


def git_bash_directory(executable):
    if executable:
        # Git Bash itself may expose mingw64/bin/git.exe rather than cmd/git.exe.
        for parent in Path(executable).resolve().parents:
            for relative in ('bin/bash.exe', 'usr/bin/bash.exe'):
                bash = parent / relative
                if bash.is_file():
                    return bash.parent
    raise ValueError('Install Git for Windows with Git Bash before native workflow execution.')


def stage_evidence(root, source, base, head, full=False):
    caches = {root / 'scratch/evidence-cache', storage(root).parent.parent / 'scratch/evidence-cache'}
    caches = sorted(path for path in caches if path.is_dir())
    if not caches:
        return []
    _, selected = scope_module().revision_scope(base, head, root=root, full=full, platform=host_profile())
    if not selected['evidence']:
        return []
    spec = importlib.util.spec_from_file_location('evidence_resolver', Path(__file__).with_name('evidence-resolver.py'))
    resolver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolver)
    staged = []
    for alias, item in resolver.registry(source)['artifacts'].items():
        target = resolver.checked_path(source, alias)
        expected = {key: item[key] for key in ('bytes', 'sha256')}
        if target.exists():
            resolver.require(resolver.identity(target) == expected, 'Existing original differs: ' + alias)
            continue
        for cache in caches:
            blob = resolver.checked_path(cache, item['sha256'])
            if not blob.exists():
                continue
            resolver.require(resolver.identity(blob) == expected, 'Evidence cache mismatch: ' + str(blob))
            target.parent.mkdir(parents=True, exist_ok=True)
            with blob.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            resolver.require(resolver.identity(target) == expected, 'Copied original differs: ' + alias)
            staged.append(alias)
            break
    return staged


def fetch_base(root):
    subprocess.run(['git', '-C', str(root), 'fetch', '--no-tags', 'origin',
                    '+refs/heads/main:refs/remotes/origin/main'], check=True)
    return git(root, 'rev-parse', 'refs/remotes/origin/main')


def check(root, full=False, *, expected_head=None, expected_base=None):
    head = clean_head(root, expected_head)
    base = fetch_base(root)
    if expected_base is not None and base != expected_base:
        raise ValueError('origin/main advanced before native Windows CI. Update the branch and rerun.')
    require_ancestor(root, base, head)
    receipt = receipt_path(root, head, base)
    # A failed rerun must never leave an earlier pass usable.
    receipt.unlink(missing_ok=True)
    reject_act_config(root)
    act = shutil.which('act')
    if not act:
        candidate = root / '.tools/act' / ('act.exe' if os.name == 'nt' else 'act')
        act = str(candidate) if candidate.is_file() else None
    if not act:
        raise ValueError('Install act; see docs/ci.md. No validation receipt was issued.')
    profile = host_profile()
    if profile == 'linux':
        subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL)
    elif profile == 'windows':
        # system32/bash.exe launches WSL. Workflow shell: bash must use Git Bash.
        bash_dir = git_bash_directory(shutil.which('git'))
        os.environ['PATH'] = os.pathsep.join((str(bash_dir), str(Path(sys.executable).parent), os.environ['PATH']))
    runner = runner_module()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='attempt-', dir=receipt.parent))
    source = directory / 'source'
    # A normal clone freezes the committed inputs and gives act a self-contained
    # .git directory even when the caller uses a linked worktree.
    subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout',
                    str(root), str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--quiet', '-B', 'local-ci-validation', head], check=True)
    subprocess.run(['git', '-C', str(source), 'remote', 'set-url', 'origin',
                    git(root, 'remote', 'get-url', 'origin')], check=True)
    staged = stage_evidence(root, source, base, head, full)
    (directory / 'empty').write_text('', encoding='utf-8')
    command = act_command(act, base, directory, full)
    files = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode().split('\0')[:-1]
    files = sorted(set(files + staged))
    plan = {'root': str(source), 'batch_timeout_seconds': 7200,
            'estimated_seconds': 3600, 'estimated_disk_bytes': 20 * 1024**3,
            'toolchains': {'act': subprocess.check_output([act, '--version'], text=True).strip(),
                           'runner': IMAGE if profile == 'linux' else 'native ' + platform.platform()},
            'features': ['workflow-defined'], 'fixtures': [head, base],
            'steps': [{'id': 'workflow', 'argv': command, 'inputs': files,
                       'artifacts': [], 'depends': [], 'timeout_seconds': 7200}]}
    plan_path = directory / 'plan.json'
    runner.write_json(plan_path, plan)
    print(f'Running {WORKFLOW} ({profile} profile). Full logs: {directory / "batch"}', flush=True)
    try:
        result = runner.run(plan_path, directory / 'batch')
    finally:
        if profile == 'linux':
            # The durable runner reaps act, but Docker children outlive that
            # process group on interruption. Remove only this attempt's label.
            containers = subprocess.check_output(['docker', 'ps', '--all', '--quiet', '--filter',
                                                  'label=chopper.local-ci=' + directory.name], text=True).split()
            if containers:
                subprocess.run(['docker', 'rm', '--force', *containers], check=True)
    if result:
        raise ValueError(f'Local workflow failed or was incomplete. See {directory / "batch/status.json"}.')
    clean_head(root, head)
    status_path = directory / 'batch/status.json'
    runner.write_json(receipt, {'version': 1, 'head': head, 'base': base,
                               'profile': profile,
                               'plan': str(plan_path), 'plan_sha256': runner.digest(plan_path),
                               'status': str(status_path), 'status_sha256': runner.digest(status_path)})
    print(f'Local CI passed for {head} against {base}. Receipt: {receipt}', flush=True)
    return head, base


def accessible_path(value):
    if os.name != 'nt' and re.match(r'^[A-Za-z]:[\\/]', value):
        value = subprocess.check_output(['wslpath', '-u', value], text=True).strip()
    return Path(value)


def verify_record(root, head, base, profile):
    runner = runner_module()
    path = receipt_path(root, head, base, profile)
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
        if receipt['version'] != 1 or (receipt['head'], receipt['base'], receipt['profile']) != (head, base, profile):
            raise ValueError('receipt revision mismatch')
        for name in ('plan', 'status'):
            if runner.digest(accessible_path(receipt[name])) != receipt[name + '_sha256']:
                raise ValueError('validation record changed')
        status = json.loads(accessible_path(receipt['status']).read_text(encoding='utf-8'))
        if status['summary'] != {'passed': 1, 'incomplete': 0}:
            raise ValueError('workflow did not complete')
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise ValueError('No intact local CI pass for this commit and current main. '
                         'Run python3 scripts/local-ci.py check before merging/pushing main.') from error


def verify(root, head, base):
    clean_head(root, head)
    require_ancestor(root, base, head)
    verify_record(root, head, base, host_profile())


def windows_checkout(root):
    configured = subprocess.run(['git', '-C', str(root), 'config', '--get', 'chopper.windowsCheckout'],
                                capture_output=True, text=True)
    if configured.returncode or not configured.stdout.strip():
        raise ValueError('Native Windows validation is required. Configure chopper.windowsCheckout '
                         'to the clean native Windows validation checkout.')
    return accessible_path(configured.stdout.strip())


def check_windows_revision(root, head, base, branch, full=False):
    if host_profile() != 'windows':
        raise ValueError('Revision transfer must run under native Windows Python.')
    with host_lock():
        clean_head(root)
        if fetch_base(root) != base:
            raise ValueError('Native Windows origin/main differs from the WSL base. Update the branch and rerun.')
        subprocess.run(['git', '-C', str(root), 'fetch', '--no-tags', 'origin', branch], check=True)
        if git(root, 'rev-parse', 'FETCH_HEAD') != head:
            raise ValueError('Push the current branch to origin before running native Windows CI.')
        require_ancestor(root, base, head)
        clean_head(root)
        subprocess.run(['git', '-C', str(root), 'switch', '--detach', '--no-overwrite-ignore', head],
                       check=True)
        # Run validation from the selected Windows revision and keep the native
        # CI lock across both checkout and receipt creation.
        selected = runpy.run_path(str(root / 'scripts/local-ci.py'))
        selected['check'](root, full, expected_head=head, expected_base=base)


def check_windows(root, full=False):
    checkout = windows_checkout(root)
    head = clean_head(root)
    branch = git(root, 'symbolic-ref', 'HEAD')
    base = fetch_base(root)
    require_ancestor(root, base, head)
    script = subprocess.check_output(['wslpath', '-w', str(root / 'scripts/local-ci.py')], text=True).strip()
    # The existing dispatcher can enter a Windows checkout that still has an
    # older version of local-ci.py. Bootstrap the handoff from WSL.
    dispatch = (
        "import runpy, sys; from pathlib import Path; "
        "runpy.run_path(sys.argv[1])['check_windows_revision']("
        "Path.cwd(), *sys.argv[2:5], full='--full' in sys.argv[5:])"
    )
    command = [sys.executable, str(root / 'scripts/windows-native.py'), '--checkout', str(checkout),
               'python', '--', '-c', dispatch, script, head, base, branch]
    subprocess.run(command + (['--full'] if full else []), check=True)
    verify_record(checkout, head, base, 'windows')


def verify_delivery(root, head, base):
    verify(root, head, base)
    if host_profile() != 'linux':
        raise ValueError('Deliver from the Linux/WSL checkout, where Linux and Windows receipts are combined.')
    _, selected = scope_module().revision_scope(base, head, root=root, platform='windows')
    if any(selected.values()):
        verify_record(windows_checkout(root), head, base, 'windows')


def pre_push(root, stream):
    for line in stream:
        local_ref, head, remote_ref, base = line.split()
        if remote_ref != 'refs/heads/main':
            continue
        if set(head) == {'0'}:
            raise ValueError('The local CI hook blocks deletion of main.')
        verify_delivery(root, head, base)


def hook_text():
    python = shlex.quote(Path(sys.executable).as_posix())
    return (f'#!/bin/sh\n{HOOK_MARKER}\n'
            'updates=$(cat)\n'
            'case "$updates" in\n'
            '  *" refs/heads/main "*) ;;\n'
            '  *) exit 0 ;;\n'
            'esac\n'
            f'printf \'%s\\n\' "$updates" | {python} "$(git rev-parse --show-toplevel)/scripts/local-ci.py" pre-push\n')


def install_hooks(root):
    if subprocess.run(['git', '-C', str(root), 'config', '--get', 'core.hooksPath'],
                      stdout=subprocess.DEVNULL).returncode == 0:
        raise ValueError('core.hooksPath is already configured. Integrate the pre-push guard there; '
                         'existing hooks were not changed. See docs/ci.md.')
    hook = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks')) / 'pre-push'
    if hook.is_symlink() or (hook.exists() and hook.read_text(encoding='utf-8') != hook_text()):
        raise ValueError(f'Existing hook preserved: {hook}. Add the local CI guard to it manually.')
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(hook_text(), encoding='utf-8', newline='\n')
    hook.chmod(0o755)
    print(f'Installed {hook}. This guards main pushes from all worktrees sharing this Git directory.')


def land(root, full=False):
    # Checking occurs before main is changed. A normal fast-forward push plus
    # the hook's actual remote-old-SHA check closes the base-advance race.
    install_hooks(root)
    head, base = check(root, full)
    verify_delivery(root, head, base)
    subprocess.run(['git', '-C', str(root), 'push', 'origin', f'{head}:refs/heads/main'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'check-windows', 'land', 'install-hooks', 'pre-push'])
    parser.add_argument('--full', action='store_true', help='Run every workflow check instead of path routing')
    args = parser.parse_args()
    root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel'))
    try:
        if args.command == 'install-hooks':
            install_hooks(root)
        elif args.command == 'pre-push':
            pre_push(root, sys.stdin)
        elif args.command == 'check-windows':
            check_windows(root, args.full)
        else:
            # Acquire before hook installation, fetch, receipt revocation or
            # workflow execution; retain through teardown, verification/push.
            with host_lock():
                if args.command == 'land':
                    land(root, args.full)
                else:
                    check(root, args.full)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Local CI blocked: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
