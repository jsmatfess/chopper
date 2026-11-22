#!/usr/bin/env python3
"""Actual-host preparation. Preflight is read-only; materialize copies declared source, never acceptance."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import shutil
import stat
import subprocess
import sys
import time
import threading

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCHEMA = 'chopper-acceptance-preflight-v1'


class UnsafeDestination(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ValueError(message)


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def checker_sources():
    return [Path(__file__).resolve(), HERE / 'acceptance-syntax.mjs',
            HERE / 'browser-small-runner.py', HERE / 'browser-small-windows.py',
            HERE / 'validation-runner.py', HERE / 'local-ci.py', HERE / 'windows-native.py', *sorted((HERE / 'scale_acceptance').glob('*.py')),
            *sorted((HERE / 'hosted_picker').rglob('*.py')),
            *sorted((HERE / 'native_smoke').glob('*.py')), HERE / 'native_smoke' / 'browser.cjs']


def result_base(value, request_path):
    return dict(schema=SCHEMA, status='failed', workload_started=False,
        acceptance_window_started=False, scale_slot_consumed=False,
        host=dict(os=platform.system(), release=platform.release(), version=platform.version(),
                  machine=platform.machine(), node=platform.node()),
        request_sha256=hashlib.sha256(Path(request_path).read_bytes()).hexdigest(),
        plan_sha256=value['plan_sha256'], profile=value['profile'],
        checker=dict(path=str(Path(__file__).resolve()),
                     sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


class Budget:
    """Conservative Python-open charges, including imports and repeated reads.

    These are preparation accounting, not physical I/O or a filesystem quota.
    The supervisor separately bounds elapsed time and sampled capture/storage.
    """
    def __init__(self, limits, directory, *, mutation_roots=None):
        self.limits, self.directory = limits, Path(directory).absolute()
        self.mutation_roots = [Path(p).absolute() for p in mutation_roots] if mutation_roots is not None else [self.directory]
        self.started = time.monotonic()
        self.read_bytes = self.visits = 0
        self.active = False
        self.auditing = False
        self.probes = []
        self.allowed_commands = set()
        self.last_reads = []

    def check(self):
        need(time.monotonic() - self.started < self.limits['seconds'], 'preparation deadline exceeded')
        need(self.read_bytes <= self.limits['read_bytes'], 'preparation read allowance exceeded' +
             (': ' + self.last_reads[-1]['path'] if self.last_reads else ''))
        need(self.visits <= self.limits['visits'], 'preparation visit allowance exceeded')

    def visit(self, path):
        self.visits += 1
        self.check()
        return Path(path).stat()

    @staticmethod
    def command_key(argv):
        # Windows emits its formatted command line in the Popen audit event;
        # POSIX emits the argv list. Compare both to the same exact spelling.
        return argv if isinstance(argv, str) else subprocess.list2cmdline(argv)

    @staticmethod
    def readonly_git(argv):
        need(isinstance(argv, (list, tuple)) and argv and
             Path(str(argv[0])).name.lower() in ('git', 'git.exe'), 'unexpected preparation subprocess')
        words = list(argv[1:])
        while words and words[0] in ('-c', '-C'):
            words = words[2:]
        need(words and words[0] in ('show', 'ls-tree', 'ls-files', 'status', 'rev-parse', 'diff'),
             'non-read-only Git command denied')

    def audit(self, event, args):
        if not self.active or self.auditing or event not in ('open', 'os.scandir', 'os.listdir',
                'os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'subprocess.Popen'):
            return
        self.auditing = True
        try:
            if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).resolve()
                flags = args[2]
                writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
                if writing:
                    self.visits += 1
                    self.check()
                    need(any(path.is_relative_to(root) for root in self.mutation_roots), 'preflight source mutation denied: ' + str(path))
                else:
                    info = self.visit(path)
                    need(stat.S_ISREG(info.st_mode), 'preflight regular input required: ' + str(path))
                    self.read_bytes += info.st_size
                    self.last_reads.append(dict(path=str(path), charged_bytes=info.st_size))
                    self.last_reads = self.last_reads[-16:]
                    self.check()
            elif event in ('os.scandir', 'os.listdir'):
                path = args[0]
                # Enumeration itself can block; the enclosing runner deadline remains authoritative.
                self.visits += 2 * (len(os.listdir(path)) + 1)
                self.check()
            elif event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir'):
                need(any(Path(args[0]).resolve().is_relative_to(root) for root in self.mutation_roots), 'preflight mutation denied')
                if event == 'os.rename':
                    need(any(Path(args[1]).resolve().is_relative_to(root) for root in self.mutation_roots), 'preflight rename destination denied')
            elif event == 'subprocess.Popen':
                self.check()
                argv = args[1]
                if self.command_key(argv) not in self.allowed_commands:
                    self.readonly_git(argv)
        finally:
            self.auditing = False

    def read(self, path):
        return Path(path).read_bytes()

    def usage(self):
        return dict(seconds=time.monotonic() - self.started,
                    charged_read_bytes=self.read_bytes, directory_entries_and_opens=self.visits,
                    probes=self.probes, last_charged_reads=self.last_reads)

    def install(self):
        # Python has no stat audit event. Count actual metadata visits as well as
        # directory enumeration; wrappers live only in this one-shot child.
        for name in ('stat', 'lstat'):
            original = getattr(os, name)
            def metered(*args, _original=original, **kwargs):
                if self.active:
                    self.visits += 1
                    self.check()
                return _original(*args, **kwargs)
            setattr(os, name, metered)
        original_output = subprocess.check_output
        def git_output(argv, *args, **kwargs):
            if not self.active:
                return original_output(argv, *args, **kwargs)
            self.readonly_git(argv)
            key = self.command_key(argv)
            self.allowed_commands.add(key)
            try:
                return original_output(argv, *args, **kwargs)
            finally:
                self.allowed_commands.discard(key)
        subprocess.check_output = git_output
        sys.addaudithook(self.audit)
        self.active = True


def request(path):
    need(Path(path).stat().st_size <= 65536, 'preflight request exceeds 64 KiB')
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    fields={'schema', 'profile', 'host_os', 'plan', 'plan_sha256', 'limits'}
    need(set(value)==fields or (value.get('profile')=='browser-scale' and set(value)==fields|{'recovery'}), 'request fields')
    need(value['schema'] == SCHEMA, 'preflight schema')
    need(value['profile'] in ('native', 'native-ui', 'small', 'browser-scale', 'actual-picker'), 'unsupported preparation profile')
    need(value['host_os'] in ('Linux', 'Windows'), 'supported actual host required')
    need(Path(value['plan']).is_absolute(), 'absolute selected plan required')
    need(len(value['plan_sha256']) == 64 and all(c in '0123456789abcdef' for c in value['plan_sha256']), 'plan SHA-256 required')
    limits = value['limits']
    need(set(limits) == {'seconds', 'read_bytes', 'visits', 'capture_bytes', 'storage_bytes'}, 'explicit preparation allowances required')
    need(all(type(n) is int and n > 0 for n in limits.values()), 'positive integer preparation allowances required')
    need(limits['seconds'] <= 900, 'preparation exceeds fifteen minutes')
    need(limits['capture_bytes'] >= 4096 and limits['storage_bytes'] >= limits['capture_bytes'] + 65536,
         'deterministic receipt/capture storage shortfall')
    return value


def probe(argv, budget, name, *, cwd=None):
    """Fixed adapter-owned probes only; no request-supplied command dispatch."""
    budget.check()
    output_path = budget.directory / (name + '.log')
    started = time.monotonic()
    try:
        budget.allowed_commands.add(budget.command_key(argv))
        with output_path.open('wb') as output:
            subprocess.run(argv, cwd=cwd, check=True, timeout=max(.001, min(10,
                budget.limits['seconds'] - (time.monotonic() - budget.started))),
                stdin=budget.null_input, stdout=output, stderr=subprocess.STDOUT)
    finally:
        budget.allowed_commands.discard(budget.command_key(argv))
        active = budget.active
        budget.active = False
        try:
            captured = output_path.stat().st_size
        finally:
            budget.active = active
        budget.visits += 1
        budget.probes.append(dict(argv=argv, seconds=time.monotonic() - started,
                                  capture_bytes=captured))
    need(output_path.stat().st_size <= budget.limits['capture_bytes'], 'probe capture allowance exceeded')
    budget.check()
    return output_path


def javascript(root, node, scripts, budget, declared_inputs):
    need(not os.environ.get('ESBUILD_BINARY_PATH'), 'undeclared ESBUILD_BINARY_PATH override')
    path = probe([node, str(HERE / 'acceptance-syntax.mjs'), root, *scripts], budget, 'syntax')
    syntax = json.loads(budget.read(path))
    need(syntax['status'] == 'passed', 'selected JavaScript helper closure failed')
    declared = {os.path.normcase(str(Path(p).resolve())) for p in declared_inputs}
    dependencies = [Path(root) / p for p in syntax['metafile']['inputs']]
    dependencies += [Path(syntax['compiler']), *[Path(p['resolved']) for p in syntax['packages']]]
    need(all(os.path.normcase(str(p.resolve())) in declared for p in dependencies),
         'JavaScript dependency outside declared frozen inputs')
    return syntax


def minimum_inventory(paths, budget):
    """Deny a known full-file hashing shortfall before reading those payloads."""
    paths = sorted(set(paths))
    need(2 * len(paths) <= budget.limits['visits'] - budget.visits, 'declared inventory visit allowance shortfall')
    total = 0
    for name in paths:
        path = Path(name)
        need(path.is_absolute() and path.resolve() == path, 'canonical inventory input required: ' + name)
        info = budget.visit(path)
        need(stat.S_ISREG(info.st_mode), 'regular inventory input required: ' + name)
        total += info.st_size
    need(total <= budget.limits['read_bytes'] - budget.read_bytes,
         'declared full inventory requires at least ' + str(total) + ' read bytes; preparation remainder is ' +
         str(budget.limits['read_bytes'] - budget.read_bytes))
    return dict(files=len(paths), minimum_full_file_read_bytes=total)


def inspect(value, budget):
    need(platform.system() == value['host_os'], 'selected host OS differs from actual host')
    path = Path(value['plan'])
    raw = budget.read(path)
    need(hashlib.sha256(raw).hexdigest() == value['plan_sha256'], 'selected plan drift')
    plan = json.loads(raw)
    if value['profile'] == 'native':
        from scale_acceptance.native_preflight import inspect as native, preparation_inputs
        if plan['os'] == 'Linux' or 'qualification' in plan:
            minimum_inventory(preparation_inputs(plan), budget)
        return native(plan, budget, probe=lambda: probe([plan['python']['path'], '-B',
            str(Path(plan['harness']['root']) / 'scripts/native-scale-runner.py'), '--help'],
            budget, 'native-command', cwd=plan['harness']['root']))
    if value['profile'] == 'native-ui':
        from native_smoke.config import inspect as native_ui
        minimum_inventory([entry['path'] for entry in plan['inputs']], budget)
        return native_ui(plan, budget, probe=probe)
    if value['profile'] == 'actual-picker':
        from hosted_picker.config import inspect as picker
        minimum_inventory([entry['path'] for entry in plan['inputs']], budget)
        return picker(plan, budget, probe=probe)
    if value['profile'] == 'browser-scale':
        from scale_acceptance.browser_scale_identity import ScaleIdentity, validate_packet
        need(platform.system() == 'Windows', 'browser-scale preparation requires its actual native Windows host')
        need(Path(plan['python']['path']).resolve() == Path(sys.executable).resolve(),
             'run preflight with the selected Python')
        validate_packet(plan, preparation=True)
        extra = [plan['borrowed_input']['path']] if 'borrowed_input' in plan else []
        if plan.get('execution_kind') == 'batch':
            from scale_acceptance.hosted_qualification import batch_inputs
            extra += [row['path'] for row in batch_inputs(plan['frozen_batch'])]
        minimum_inventory([str(Path(plan[key]['root']) / name) for key in ('product', 'harness', 'assets', 'evidence')
                           for name in plan[key]['sha256']] +
                          [row['path'] for row in plan['external_runtime']['inputs']] + extra, budget)
        identity = ScaleIdentity(dict(packet=str(path), sha256=value['plan_sha256']), preparation=True)
        identity.require_windows()
        packet = identity.packet
        recovery={}
        if 'recovery' in value:
            from scale_acceptance.browser_scale_guard import recovery_request
            definition,original,_=recovery_request(value['recovery'])
            need(original==packet and definition['frozen_packet']==dict(path=str(path),sha256=value['plan_sha256']),
                 'exact completed-run recovery context required')
            minimum_inventory([row['path'] for row in definition['recovery_code']],budget)
            for row in definition['recovery_code']:
                need(hashlib.sha256(budget.read(row['path'])).hexdigest()==row['sha256'],'recovery code drift')
            recovery=dict(recovery=value['recovery'])
        root = packet['harness']['root']
        declared = [str(Path(packet[key]['root']) / name) for key in ('product', 'harness', 'assets', 'evidence')
                    for name in packet[key]['sha256']]
        syntax = javascript(root, packet['node']['path'],
                            [str(Path(root) / 'scripts/scale_acceptance/browser-scale-driver.mjs')], budget, declared)
        identity.check()
        return dict(bindings=packet, syntax=syntax, **recovery,
                    runtime_pending=['complete actual-host tiny journey', 'full cold guard timing',
                                     'live capacity, quota and original reservation ownership',
                                     'complete cleanup and matching frozen batch'])
    small = load('browser-small-runner')
    need(plan.get('schema') == 'chopper-small-runner-config-v1', 'selected SMALL config schema')
    need(platform.system() == 'Windows', 'SMALL preparation requires its actual native Windows host')
    need(Path(plan['python']).resolve() == Path(sys.executable).resolve(), 'run preflight with the selected Python')
    estimate = minimum_inventory([entry['path'] for entry in plan['inputs']], budget)
    for key in ('node', 'python', 'browser'):
        selected = Path(plan[key])
        need(selected.is_absolute() and selected.resolve() == selected and selected.is_file(),
             'select a real absolute executable: ' + key)
        need(shutil.which(str(selected)) == str(selected), 'unresolved executable: ' + key)
    checked = small.validate_config(plan, producer_root=plan['root'])
    budget.check()
    if any(command['script'] == 'test-browser-graph.mjs' for command in plan['commands']):
        # Parse the selected stdin-driven helper without running its top level.
        helper = Path(plan['root']) / 'scripts/graph-codec-fixtures.py'
        compile(budget.read(helper), str(helper), 'exec')
    # Kernel symbol/signature binding creates no Job and opens no process.
    small.windows.kernel()
    scripts = [str(Path(plan['root']) / 'scripts' / command['script']) for command in plan['commands']]
    syntax = javascript(plan['root'], plan['node'], scripts, budget, [entry['path'] for entry in checked['frozen']])
    # History charges must be consumable now, not first discovered after prepare.
    debit, adopted, priming = small.retained_origin(plan, with_priming=True) if 'retained_origin_manifest' in plan else (0, [], None)
    if priming is not None:
        storage=small.primed_storage(priming,[p for p in priming['fresh_roots'] if Path(p)!=Path(plan['owned_root'])])
    else:
        storage = small.Storage([*map(Path, plan['history_roots']), *adopted])
        storage.total += debit
        for root in plan['history_roots']:
            ledger = json.loads(budget.read(Path(root) / 'storage-ledger.json'))
            need(ledger['method'] == 'sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny' and
                 type(ledger['cumulative_owned_bytes']) is int and ledger['cumulative_owned_bytes'] >= 0,
                 'retained ledger accounting mismatch: ' + root)
            storage.total += ledger['cumulative_owned_bytes']
    total = storage.sample()
    need(sum(command['timeout_seconds'] for command in plan['commands']) < small.LIMITS['batch_seconds'],
         'selected command budgets leave no batch setup/cleanup time')
    need(all(shutil.disk_usage(volume).free >= small.LIMITS['start_free_bytes'] for volume in plan['volumes']),
         'current physical free capacity below start floor')
    small.check_inputs(checked)
    return dict(bindings=dict(product=small.PRODUCT, harness=plan['harness_commit'],
                              inputs=checked['frozen'], inventories=checked['inventories']),
                retained_storage_sample_bytes=total,
                preparation_estimate=estimate,
                syntax=syntax,
                runtime_pending=['complete actual-host tiny journey', 'full cold guard timing',
                                 'live capacity and quota', 'actual picker/permission ownership',
                                 'EOF/reap/quiescence and original reservation release'])


def worker(request_path, directory):
    directory = Path(directory)
    value = request(request_path)
    limits = dict(value['limits'])
    context_path = directory / 'worker-budget.json'
    has_context = context_path.exists()
    if has_context:
        remaining = json.loads(context_path.read_text())
        need(set(remaining) == {'seconds', 'read_bytes', 'visits'}, 'supervisor budget fields')
        for key, amount in remaining.items():
            need(type(amount) in (int, float) and 0 < amount <= limits[key], 'invalid remaining preparation budget')
            limits[key] = amount
    budget = Budget(limits, directory)
    containment = None
    result = dict(schema=SCHEMA, status='failed', profile=value['profile'], plan_sha256=value['plan_sha256'],
                  workload_started=False, acceptance_window_started=False, scale_slot_consumed=False)
    budget.read_bytes = Path(request_path).stat().st_size
    budget.visits = 8  # bounded request/context/null-handle bootstrap; variable work is metered below
    if has_context:
        budget.read_bytes += context_path.stat().st_size
    # Open the OS null device before the read-only source guard. It is a
    # fixed stdin handle, not a source path or an allowed external write.
    budget.null_input = open(os.devnull, 'rb')
    budget.install()
    try:
        result.update(result_base(value, request_path))
        budget.check()
        if os.name == 'nt':
            containment = load('validation-runner')
            containment.contain_session()
        checker_paths = checker_sources()
        result['checker']['files'] = {str(p): hashlib.sha256(budget.read(p)).hexdigest() for p in checker_paths}
        result['environment_sha256'] = hashlib.sha256(json.dumps(dict(os.environ), sort_keys=True).encode()).hexdigest()
        result.update(inspect(value, budget))
        need({str(p): hashlib.sha256(budget.read(p)).hexdigest() for p in checker_sources()} == result['checker']['files'],
             'preflight checker source drift')
        if containment is not None:
            census = containment.owned_windows_job()
            need(census['kill_on_close'] and census['pids'] == [os.getpid()], 'preparation Job not quiescent')
            result['preparation_containment'] = dict(kill_on_close=True, final_pids=census['pids'])
        budget.check()
        result.setdefault('runtime_pending', [])
        if result['status'] != 'blocked':
            result['status'] = 'passed'
    except Exception as error:
        result['status'] = 'failed'
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        budget.active = False
        budget.null_input.close()
        result['usage'] = budget.usage()
        (directory / 'worker-result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return 0 if result['status'] == 'passed' else 1


def declared_source_roots(selected_plan, profile=None):
    """Collect raw protected roots for native execution and offline declaration checks."""
    schema = selected_plan.get('schema')
    schemas = {'native-ui': 'chopper-native-ui-smoke-v1',
               'actual-picker': 'chopper-hosted-picker-qualification-v1'}
    if profile in schemas and schema == schemas[profile]:
        # These schemas define actual roles. A sampled volume's `root` is
        # observation metadata, not an immutable source or retained artifact.
        protected = [selected_plan['root'], selected_plan['controller_root'],
                     *selected_plan['input_directories'], *selected_plan['runtime_roots']]
        if schema == 'chopper-native-ui-smoke-v1':
            protected.extend(selected_plan['owned_roots'])
        else:
            from hosted_picker.config import read
            custody_path = selected_plan['documents']['custody.json']
            pins = {row['path']: row['sha256'] for row in selected_plan['inputs']}
            custody = read(custody_path, expected_sha256=pins[custody_path])
            protected.extend(custody['ownedRoots'])
        return list(dict.fromkeys(protected))
    protected = []
    def roots(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ('root', 'owned_root', 'controller_root') and isinstance(child, str):
                    protected.append(child)
                elif key == 'input_directories' and isinstance(child, dict):
                    protected.extend(child)
                elif key in ('input_directories', 'history_roots', 'owned_roots', 'roots') and isinstance(child, list):
                    protected.extend(p for p in child if isinstance(p, str))
                roots(child)
        elif isinstance(node, list):
            for child in node:
                roots(child)
    roots(selected_plan)
    return protected


def check_evidence_destination(directory, protected):
    if any(directory.is_relative_to(root) for root in protected):
        raise UnsafeDestination('evidence overlaps selected source/retained roots')


def owned_preparation_root(value, plan):
    roles = {'native-ui': ('chopper-native-ui-smoke-v1', 'native105-smoke-'),
             'actual-picker': ('chopper-hosted-picker-qualification-v1', 'hosted105-')}
    role = roles.get(value['profile'])
    if role is None or plan.get('schema') != role[0] or not isinstance(plan.get('root'), str):
        return None
    root = PureWindowsPath(plan['root'])
    if (root.parent != PureWindowsPath('C:/') or not root.name.startswith(role[1])
            or PureWindowsPath(value['plan']) != root / 'candidate.json'):
        return None
    return Path(plan['root'])


def check_preparation_destination(directory, selected_plan, value):
    protected = [HERE, *(Path(name).resolve() for name in declared_source_roots(selected_plan, value['profile']))]
    root = owned_preparation_root(value, selected_plan)
    if root is not None and directory == root / 'preflight':
        if root.resolve() != root or not root.is_dir():
            raise UnsafeDestination('plain existing owned case root required')
        if (root / 'attempt1').exists():
            raise UnsafeDestination('preparation cannot mutate an attempted case')
        for member in (root, *root.parents):
            info = member.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise UnsafeDestination('case-root alias/reparse path')
        candidate = Path(value['plan']).lstat()
        if (not stat.S_ISREG(candidate.st_mode) or candidate.st_nlink != 1
                or getattr(candidate, 'st_file_attributes', 0) & 0x400):
            raise UnsafeDestination('ordinary owned candidate required')
        immutable = [HERE.parent, Path(selected_plan['controller_root']), Path(value['plan']),
                     *(Path(name) for name in selected_plan['input_directories']),
                     *(Path(row['path']) for row in selected_plan['inputs'])]
        if any(directory.is_relative_to(path.resolve()) or path.resolve().is_relative_to(directory)
               for path in immutable):
            raise UnsafeDestination('owned preparation evidence overlaps immutable input/source')
        protected = [path for path in protected if path != root]
    check_evidence_destination(directory, protected)


def supervise(request_path, directory, value, budget, parent_base):
    started = budget.started
    need(Path(value['plan']).stat().st_size <= value['limits']['read_bytes'], 'selected plan exceeds preparation read allowance')
    directory = Path(directory).absolute()
    if directory.resolve() != directory:
        raise UnsafeDestination('canonical evidence destination required')
    need(not directory.exists(), 'fresh preparation evidence directory required')
    if value['profile'] in ('native-ui', 'actual-picker'):
        selected_raw = budget.read(Path(value['plan']))
        need(hashlib.sha256(selected_raw).hexdigest() == value['plan_sha256'], 'selected plan drift before output admission')
        selected_plan = json.loads(selected_raw)
    else:
        selected_plan = json.loads(Path(value['plan']).read_text())
    check_preparation_destination(directory, selected_plan, value)
    directory.mkdir()
    runner = load('validation-runner')
    selected = Path(request_path).resolve()
    original_stop = runner.stop
    def stop(process):
        # Exhausting a preparation allowance must never deny owned cleanup.
        active = budget.active
        budget.active = False
        try:
            return original_stop(process)
        finally:
            budget.active = active
    runner.stop = stop
    # This is a preparation runner, never an acceptance plan/session/claim.
    plan = dict(root=str(HERE.parent), batch_timeout_seconds=value['limits']['seconds'],
                estimated_seconds=value['limits']['seconds'], estimated_disk_bytes=value['limits']['storage_bytes'],
                toolchains={'python': sys.version}, features=['read-only-preparation'], fixtures=[value['profile']],
                steps=[dict(id='preflight', argv=[str(Path(sys.executable).resolve()), '-B', str(Path(__file__).resolve()),
                    '_worker', str(selected), str(directory)], timeout_seconds=value['limits']['seconds'],
                    inputs=[str(p.resolve()) for p in (selected, Path(value['plan']), Path(__file__).resolve())],
                    artifacts=[str(directory / 'worker-result.json')])])
    plan_path = directory / 'preparation-plan.json'
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    budget.allowed_commands.add(budget.command_key(plan['steps'][0]['argv']))

    context_written = False

    def guard():
        nonlocal context_written
        budget.check()
        files = [p for p in directory.rglob('*') if p.is_file()]
        need(sum(p.stat().st_size for p in files) <= value['limits']['storage_bytes'], 'preparation storage stop exceeded')
        need(sum(p.stat().st_size for p in files if p.suffix == '.log') <= value['limits']['capture_bytes'],
             'preparation capture stop exceeded')
        if not context_written:
            # Leave room for the runner's final identity/custody reads. The
            # child gets the remainder, never a fresh copy of the allowance.
            reserve = 3 * (sum(Path(p).stat().st_size for p in (selected, Path(value['plan']), Path(__file__).resolve()))
                           + value['limits']['storage_bytes'])
            remaining = dict(seconds=value['limits']['seconds'] - (time.monotonic() - started),
                             read_bytes=value['limits']['read_bytes'] - budget.read_bytes - reserve,
                             visits=value['limits']['visits'] - budget.visits - 1024 -
                             64 * (5 * value['limits']['seconds'] + 5))
            need(all(amount > 0 for amount in remaining.values()), 'preparation supervisor/receipt allowance shortfall')
            (directory / 'worker-budget.json').write_text(json.dumps(remaining))
            context_written = True

    try:
        code = runner.run(plan_path, directory / 'runner', guard=guard)
        guard()
    except (OSError, ValueError) as error:
        code = 1
        supervisor_error = str(error)
    finally:
        budget.active = False
    # Fixed final receipt work: at most five stats, two reads and one write.
    budget.visits += 8
    worker_path, result_path = directory / 'worker-result.json', directory / 'result.json'
    if worker_path.exists():
        budget.read_bytes += 2 * worker_path.stat().st_size
        budget.visits += 1
    result = dict(parent_base)
    if worker_path.exists():
        result.update(json.loads(worker_path.read_text()))
    else:
        result['error'] = 'worker incomplete; inspect retained runner status'
    if 'supervisor_error' in locals():
        result.update(status='failed', error=supervisor_error)
    elif code and result['status'] != 'blocked':
        result['status'] = 'failed'
        result.setdefault('error', 'preparation runner failed; inspect retained status')
    result.update(schema=SCHEMA, workload_started=False, acceptance_window_started=False, scale_slot_consumed=False)
    result['supervisor_usage'] = budget.usage()
    result['total_preparation_seconds'] = time.monotonic() - started
    if worker_path.exists():
        result['worker_receipt_sha256'] = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    used = result.get('usage', {})
    if (budget.read_bytes + used.get('charged_read_bytes', 0) > value['limits']['read_bytes'] or
            budget.visits + used.get('directory_entries_and_opens', 0) > value['limits']['visits'] or
            result['total_preparation_seconds'] >= value['limits']['seconds']):
        code = 1
        result.update(status='failed', error='total preparation allowance exceeded')
    result_path.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('Preflight ' + result['status'] + ': ' + result.get('error', 'runtime qualification remains required'))
    print('Receipt: ' + str(result_path))
    return code


def preflight(request_path, directory):
    started = time.monotonic()
    value = request(request_path)
    budget = Budget(value['limits'], directory)
    budget.started = started
    budget.read_bytes = Path(request_path).stat().st_size
    budget.visits = 3  # request admission, size charge, external-command freshness check
    base = dict(schema=SCHEMA, status='failed', profile=value['profile'], plan_sha256=value['plan_sha256'],
                host=dict(os=platform.system()), request_path=str(request_path),
                workload_started=False, acceptance_window_started=False, scale_slot_consumed=False)
    budget.install()
    try:
        base = result_base(value, request_path)
        return supervise(request_path, directory, value, budget, base)
    except Exception as error:
        base.update(error=type(error).__name__ + ': ' + str(error), supervisor_usage=budget.usage(),
                    total_preparation_seconds=time.monotonic()-started)
        error.preflight_result = base
        raise
    finally:
        budget.active = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preflight', '_worker', 'batch-definition', 'packet', 'packet-host-plan', 'packet-host', 'materialize', 'after-exit', 'image-exit-plan', 'image-exit'))
    parser.add_argument('request')
    parser.add_argument('evidence')
    parser.add_argument('--sha256')
    parser.add_argument('--receipt-sha256')
    args = parser.parse_args()
    need(args.receipt_sha256 is None or args.operation=='after-exit','receipt SHA applies only to after-exit')
    fresh = not Path(args.evidence).exists()
    packet_timer = None
    try:
        if args.operation in ('packet-host','materialize','after-exit','image-exit'):
            packet_timer=threading.Timer(30 if args.operation in ('after-exit','image-exit') else 180,lambda:os._exit(124))
            packet_timer.daemon=True;packet_timer.start()
        if args.operation in ('batch-definition','packet', 'packet-host-plan', 'packet-host', 'materialize', 'after-exit', 'image-exit-plan', 'image-exit'):
            if args.operation in ('packet-host','materialize','after-exit','image-exit'):
                need(args.sha256 and len(args.sha256) == 64, 'exact input SHA required')
                need(Path(args.request).stat().st_size <= 16*1024**2, 'packet memory bound')
                raw = Path(args.request).read_bytes()
                need(hashlib.sha256(raw).hexdigest() == args.sha256, 'packet input pin')
                body = json.loads(raw)
                pins = {str(Path(p['path'])):p['sha256'] for p in body['preparation_code']}
                for source in checker_sources():
                    need(str(source) in pins and hashlib.sha256(source.read_bytes()).hexdigest() == pins[str(source)],
                         'pre-import checker closure mismatch: '+str(source))
            # Execute the checked source, never an ignored working-tree bytecode cache.
            sys.pycache_prefix=str(Path(args.evidence).absolute()/'.unused-bytecode')
            need(not Path(sys.pycache_prefix).exists(),'unexpected preparation bytecode cache')
            from scale_acceptance import hosted_qualification
            if args.operation == 'batch-definition':
                result = hosted_qualification.prepare_batch_definition(args.request,args.evidence)
            elif args.operation == 'image-exit-plan':
                result = hosted_qualification.prepare_image_control(args.request,args.evidence,sys.modules[__name__])
            elif args.operation == 'packet-host-plan':
                result = hosted_qualification.prepare_host_observation(args.request,args.evidence,sys.modules[__name__])
            elif args.operation == 'packet':
                result = hosted_qualification.prepare_packet(args.request, args.evidence, sys.modules[__name__])
            elif args.operation=='after-exit':
                result=hosted_qualification.after_exit(args.request,args.evidence,args.sha256,sys.modules[__name__],timer=packet_timer,receipt_sha256=args.receipt_sha256)
            else:
                need(args.sha256 and len(args.sha256) == 64, 'exact input SHA required')
                result = {'packet-host':hosted_qualification.observe_packet_host,
                          'materialize':hosted_qualification.materialize_packet,
                          'after-exit':hosted_qualification.after_exit,'image-exit':hosted_qualification.image_exit_control}[args.operation](args.request,args.evidence,args.sha256,sys.modules[__name__],timer=packet_timer)
            print(json.dumps(result,sort_keys=True))
            return 0
        return (worker if args.operation == '_worker' else preflight)(args.request, args.evidence)
    except Exception as error:
        result = getattr(error, 'preflight_result', dict(schema=SCHEMA, status='failed',
            error=type(error).__name__ + ': ' + str(error), workload_started=False,
            acceptance_window_started=False, scale_slot_consumed=False))
        if args.operation == 'preflight' and fresh and not isinstance(error, UnsafeDestination):
            directory = Path(args.evidence)
            try:
                directory.mkdir(exist_ok=True)
                (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            except OSError as evidence_error:
                result['evidence_error'] = str(evidence_error)
        print(json.dumps(result))
        return 1
    finally:
        if packet_timer is not None:
            packet_timer.cancel();packet_timer.join()


if __name__ == '__main__':
    raise SystemExit(main())
