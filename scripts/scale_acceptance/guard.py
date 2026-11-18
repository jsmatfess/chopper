"""Capacity/progress policy on the existing validation runner, not a scheduler."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
from .verify import read_json, require, sha256

RUNNER = Path(__file__).resolve().parents[1] / 'validation-runner.py'


class DiskObservation:
    """One owned disk sampler; only completed, oldest-start-aware facts publish.

    Hot identity/watchdog work never runs on this thread. A blocked call remains
    owned after a timeout and must join before its controller releases ownership.
    """
    def __init__(self, sample, *, launch=None, clock=time.monotonic, wall=time.time,
                 seconds=30, interval=15, age=90):
        require(0 < seconds <= 30 and 0 < interval <= 45 and 0 < age <= 90, 'disk observation bounds')
        self.sample, self.launch, self.clock, self.wall = sample, launch, clock, wall
        self.seconds, self.interval, self.age = seconds, min(interval, 15), age
        self.changed = threading.Condition()
        self.wake, self.done = threading.Event(), threading.Event()
        self.thread = None
        self.launch_uncertain = False
        self.started = self.finished = self.value = self.error = None

    def start(self):
        require(self.thread is None, 'disk sampler already started')
        if self.launch is None:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
        else:
            try:
                self.thread = self.launch(self.run)
            except BaseException:
                self.launch_uncertain = True
                raise
        return self

    def run(self):
        previous = None
        while not self.done.is_set():
            started, wall = self.clock(), self.wall()
            try:
                require(previous is None or started-previous <= 45, 'disk sampling cadence exceeded')
                with self.changed:
                    self.started = started
                    self.changed.notify_all()
                value = self.sample()
                finished = self.clock()
                require(0 <= finished-started <= self.seconds, 'disk observation late/blocked')
                with self.changed:
                    self.value = dict(value=value, started=started, finished=finished,
                                      started_ms=int(wall*1000), finished_ms=int(self.wall()*1000))
                    self.finished = finished
                    self.changed.notify_all()
            except BaseException as error:
                with self.changed:
                    self.error = error
                    self.changed.notify_all()
                return
            previous = started
            self.wake.wait(max(0, self.interval-(self.clock()-started)))
            self.wake.clear()

    def check(self):
        require(not self.launch_uncertain, 'disk sampler launch ownership uncertain')
        if self.error is not None:
            raise self.error
        require(self.started is None or self.done.is_set() or self.clock()-self.started <= 45,
                'disk sampling cadence exceeded')
        require(self.started is None or self.finished is not None and self.finished >= self.started
                or self.clock()-self.started <= self.seconds, 'disk observation late/blocked')

    def read(self):
        with self.changed:
            self.check()
            require(self.value is not None, 'no completed disk observation')
            require(0 <= self.clock()-self.value['started'] <= self.age, 'disk capacity stale from observation start')
            return self.value

    def after(self, marker, timeout=30):
        """Wait for a complete census that began after a known write boundary."""
        deadline = time.monotonic()+timeout
        if self.started is None or self.started <= marker:
            self.wake.set()
        with self.changed:
            while self.value is None or self.value['started'] <= marker:
                self.check()
                remaining = deadline-time.monotonic()
                require(remaining > 0, 'disk observation completion timed out')
                self.changed.wait(min(remaining, .05))
            self.check()
        return self.read()

    @property
    def pending(self):
        return self.launch_uncertain or self.thread is not None and self.thread.is_alive()

    def stop(self, timeout=30):
        self.done.set(); self.wake.set()
        require(not self.launch_uncertain, 'disk sampler launch ownership uncertain')
        if self.thread is not None:
            self.thread.join(timeout)
            require(not self.thread.is_alive(), 'disk observation still owns a pending call')


def load_runner():
    spec = importlib.util.spec_from_file_location('scale_validation_runner', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen_metadata(root, patterns):
    """Inventory immutable source names/metadata without rereading file bodies."""
    entries = {}
    def record(path):
        value = path.lstat()
        require(not stat.S_ISLNK(value.st_mode), 'frozen input symlink/escape: ' + str(path))
        require((stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode))
                and not getattr(value, 'st_file_attributes', 0) & 0x400,
                'frozen input is not a plain regular file/directory')
        require(path.resolve().is_relative_to(root), 'frozen input symlink/escape: ' + str(path))
        entries[path.relative_to(root).as_posix()] = (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_nlink, getattr(value, 'st_file_attributes', 0))
        return stat.S_ISDIR(value.st_mode)
    for pattern in patterns:
        require(not Path(pattern).is_absolute() and '..' not in Path(pattern).parts,
                'frozen inputs must stay under source root')
        matches = list(root.glob(pattern))
        require(matches, 'frozen input missing: ' + pattern)
        for match in matches:
            if record(match):
                def fail(error):
                    raise error
                for folder, directories, files in os.walk(match, followlinks=False, onerror=fail):
                    # Validate directory entries before os.walk can descend into a
                    # Windows junction; collect no paths outside the frozen root.
                    for name in directories + files:
                        record(Path(folder) / name)
    return entries


class FrozenIdentity:
    """Bind approved byte hashes once, then reject any metadata/name drift."""
    def __init__(self, binding):
        self.root = Path(binding['root']).resolve()
        packet_path = Path(binding['packet']).resolve()
        require(packet_path.is_relative_to(self.root), 'frozen packet must stay under source root')
        require(sha256(packet_path) == binding['sha256'], 'frozen packet hash changed')
        self.packet = read_json(packet_path)
        freeze = self.packet
        require(freeze['runtime'] == 'native' and freeze['features'] == []
                and freeze['parent_scheduled'] is True, 'parent-scheduled default native freeze required')
        for key in ('source', 'package', 'host', 'storage', 'toolchains'):
            require(isinstance(freeze[key], dict) and freeze[key], 'missing frozen identity: ' + key)
        require(freeze['source']['clean'] is True and len(freeze['source']['commit']) == 40
                and all(c in '0123456789abcdef' for c in freeze['source']['commit']),
                'clean frozen source required')
        require(freeze['inputs'] and all(isinstance(p, str) for p in freeze['inputs']),
                'declared frozen inputs required')
        required = {'Cargo.toml', 'Cargo.lock', 'crates', 'vendor', 'ui/public', 'ui/index.html', 'ui/style.css'}
        require(required <= set(freeze['inputs']), 'complete source/vendor/embedded inputs required')
        self.executable = Path(freeze['executable']).resolve()
        require(self.executable.is_relative_to(self.root), 'frozen executable must stay under source root')
        executable_name = self.executable.relative_to(self.root).as_posix()
        packet_name = packet_path.relative_to(self.root).as_posix()
        self.patterns = [*freeze['inputs'], executable_name, packet_name]
        before = frozen_metadata(self.root, self.patterns)
        source_names = frozen_metadata(self.root, freeze['inputs'])
        runner = load_runner()
        identities = {Path(name).as_posix(): value
                      for name, value in runner.identity(self.root, self.patterns).items()}
        require(not runner.incomplete_identity(identities), 'incomplete frozen input identity')
        expected = freeze.get('input_sha256')
        require(isinstance(expected, dict) and expected, 'approved frozen input_sha256 map required')
        actual = {name: identities[name]['sha256'] for name in source_names
                  if not identities[name].get('directory')}
        require(actual == expected, 'frozen source input hashes changed')
        require(identities[executable_name]['sha256'] == freeze['executable_sha256'],
                'frozen executable hash changed')
        require(identities[packet_name]['sha256'] == binding['sha256'], 'frozen packet changed during admission')
        self.metadata = frozen_metadata(self.root, self.patterns)
        require(self.metadata == before, 'frozen source/package changed during admission')

    def check(self):
        try:
            require(frozen_metadata(self.root, self.patterns) == self.metadata,
                    'frozen source/package metadata changed')
        except (OSError, ValueError, KeyError) as error:
            raise OSError('scale guard frozen drift: ' + str(error)) from error


class Guard:
    def __init__(self, policy, log, clock=time.monotonic, disk=None):
        self.disk = disk
        self.policy, self.log, self.clock = policy, Path(log), clock
        require(policy['version'] == 1, 'guard policy version')
        for key in ('owned_bytes', 'start_free_bytes', 'stop_free_bytes', 'deadline_seconds',
                    'no_progress_seconds', 'sample_seconds'):
            require(type(policy[key]) in (int, float) and policy[key] > 0, 'positive guard limits required')
        require(policy['sample_seconds'] <= 5 and policy['no_progress_seconds'] <= 600,
                'sample/progress interval exceeds plan')
        require(policy['stop_free_bytes'] <= policy['start_free_bytes'], 'invalid free-space thresholds')
        require(all(not Path(path).is_symlink() for path in policy['owned_roots']), 'owned root symlink')
        self.roots = [Path(path).resolve() for path in policy['owned_roots']]
        require(self.roots and all(root.is_dir() for root in self.roots), 'owned roots must exist')
        require(all(a != b and a not in b.parents and b not in a.parents
                    for i, a in enumerate(self.roots) for b in self.roots[i + 1:]), 'overlapping owned roots')
        self.volumes = [Path(path).resolve() for path in policy['volumes']]
        require(self.volumes and all(path.exists() for path in self.volumes), 'capacity volumes required')
        require({p.stat().st_dev for p in self.roots} <= {p.stat().st_dev for p in self.volumes},
                'each owned volume must be inventoried')
        require(policy['progress_paths'], 'explicit progress paths required')
        self.started = self.last_progress = clock()
        self.next_sample, self.previous = 0, None
        if policy.get('browser_frozen'):
            from .browser_identity import BrowserIdentity
            require(policy['owned_bytes'] <= 64 * 1024**2 and policy['deadline_seconds'] <= 600
                    and policy['no_progress_seconds'] <= 60, 'tiny browser guard ceilings exceeded')
            require(not policy.get('frozen'), 'distinct native/browser identity layers required')
            self.frozen = BrowserIdentity(policy['browser_frozen'])
        else:
            self.frozen = FrozenIdentity(policy['frozen']) if policy.get('frozen') else None
        self.sample(start=True)

    @staticmethod
    def disk_values(roots, volumes):
        owned = 0
        def census_error(error):
            # Intermediate children can be retired while a job is running.
            if not isinstance(error, FileNotFoundError):
                raise error
        for root in roots:
            if root.is_symlink() or not root.is_dir():
                raise OSError('owned root changed/disappeared')
            for folder, directories, files in os.walk(root, followlinks=False, onerror=census_error):
                for name in directories + files:
                    path = Path(folder) / name
                    try:
                        entry = path.lstat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISLNK(entry.st_mode):
                        raise OSError('owned-tree symlink: ' + str(path))
                    if stat.S_ISREG(entry.st_mode):
                        owned += entry.st_size
                    elif name in files:
                        raise OSError('owned entry is not a regular file')
            if root.is_symlink() or not root.is_dir():
                raise OSError('owned root changed/disappeared')
        free = [shutil.disk_usage(path).free for path in volumes]
        return dict(owned=owned, free=free)

    def sample(self, start=False, force=False):
        if self.frozen is not None and (start or force):
            self.frozen.check()
        now = self.clock()
        if now - self.started >= self.policy['deadline_seconds']:
            raise OSError('scale guard: attempt deadline')
        if not start and not force and now < self.next_sample:
            return
        self.next_sample = now + self.policy['sample_seconds']
        try:
            observation = self.disk.read() if self.disk else None
            values = observation['value'] if observation else self.disk_values(self.roots, self.volumes)
            owned, free = values['owned'], values['free']
            progress = []
            for value in self.policy['progress_paths']:
                path = Path(value)
                try:
                    with path.open('rb') as stream:
                        stream.seek(0, 2)
                        offset=max(0,stream.tell()-4096)
                        stream.seek(offset)
                        tail=stream.read(4096)
                        if path.suffix=='.jsonl':
                            newline=tail.rfind(b'\n')
                            if newline<0:
                                progress.append((str(path),dict(self.previous or []).get(str(path))))
                                continue
                            # Anchor the fingerprint to the completed record,
                            # not a shifting suffix of an unfinished append.
                            end=offset+newline
                            stream.seek(max(0,end-4096))
                            tail=stream.read(end-stream.tell())
                        lines=tail.splitlines()
                    last = next((line for line in reversed(lines) if line.strip()), b'')
                    # Repeated identical CLI/JSON checkpoints are not forward progress.
                    progress.append((str(path), hashlib.sha256(last).hexdigest()))
                except FileNotFoundError:
                    progress.append((str(path), None))
            if progress != self.previous:
                self.previous, self.last_progress = progress, now
            reason = None
            if owned >= self.policy['owned_bytes']:
                reason = 'owned-tree capacity'
            elif min(free) < max(self.policy['start_free_bytes' if start else 'stop_free_bytes'],
                                 (128*1024**3 + (self.policy['owned_bytes'] if start else 0)) if self.disk else 0):
                reason = 'physical free space'
            elif now - self.last_progress >= self.policy['no_progress_seconds']:
                reason = 'no progress'
            reservation = self.policy.get('reservation')
            if reservation and sha256(reservation['path']) != reservation['sha256']:
                reason = 'host reservation changed/conflict'
            quota = self.policy.get('browser_quota')
            if quota:
                status = read_json(quota['path'])
                # The browser adapter must sample the real origin, including engine reserve.
                if time.time() - status['sampled_unix'] > 90 or status['usable_bytes'] < quota['start_bytes' if start else 'stop_bytes']:
                    reason = 'origin quota stale/denied'
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(sampled_unix=time.time(), owned_bytes=owned,
                                             free_bytes=free, capacity_started_ms=observation['started_ms'] if observation else None, progress=progress, reason=reason)) + '\n')
            if reason:
                raise OSError('scale guard: ' + reason)
        except (ValueError, KeyError, TypeError) as error:
            raise OSError('scale guard invalid observation: ' + str(error)) from error

    def __call__(self):
        # The runner calls this immediately before each launch and while waiting.
        # Do not throttle immutable identity checks with capacity sampling.
        if self.frozen is not None:
            self.frozen.check()
        self.sample()


def run(plan, directory, policy):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    runner = load_runner()
    try:
        # Preserve prelaunch denials as well as the existing runner's attempts.
        manifest = read_json(plan)
        runner.write_json(directory / 'requested-plan.json', manifest)
        observation = read_json(policy)
        runner.write_json(directory / 'guard-policy.json', observation)
        policy_path = Path(policy).absolute()
        # Native and browser planners may use different separator spellings.
        relative = policy_path.relative_to(Path(manifest['root']).resolve())
        require(all(relative in map(Path, step['inputs']) for step in manifest['steps']),
                'guard policy must be a declared input')
        guard = Guard(observation, directory / 'capacity.jsonl')
        runner.contain_session()
        result = runner.run(Path(plan), directory, guard=guard)
        guard.sample(force=True)
        return result
    except BaseException as error:
        state = read_json(directory / 'status.json') if (directory / 'status.json').exists() else {'attempts': []}
        attempted = {attempt['id'] for attempt in state['attempts']}
        declared = locals().get('manifest', {}).get('steps', [])
        runner.write_json(directory / 'guard-failure.json', dict(error=str(error), status='failed',
            checkpoint='runner-or-final-guard' if attempted else 'prelaunch',
            unrun_steps=[step['id'] for step in declared if step['id'] not in attempted]))
        raise
