"""Host sampling independent of maintained runner's synchronous hash passes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import time
from .native_scale_control import LIMITS
from .native_scale_identity import host, path, stamp, sealed_stat, Lineage, frozen_metadata
from . import native_scale_identity as identity
from .verify import require
from ._native_file import _allocated_bytes, _AllocationChange


def _prepare_source(plan, lock, campaign, entries, deadline, clock=time.monotonic):
    """Internal component hook; the root must first admit its immutable descriptor.

    No session caller or Windows lineage admission is supplied here.
    """
    from ._native_source import _SourcePool
    roots = tuple(path(r) for r in plan['source_reservation']['roots'])
    pool = _SourcePool(lock, roots, entries)
    def checkpoint(charge):
        lock.check()
        campaign.check()
        require(clock() < deadline, 'source prime OS deadline')
        require(plan['host'] == host(), 'source prime host drift')
        devices = {str(v['device']) for v in plan['volumes']}
        require(all(str(r.stat().st_dev) in devices for r in roots), 'source prime volume missing')
        for volume in plan['volumes']:
            p = path(volume['path'])
            require(str(p.stat().st_dev) == str(volume['device']), 'source prime volume drift')
            require(shutil.disk_usage(p).free >= LIMITS['start_free_bytes'], 'source prime free capacity')
        require(charge <= plan['source_reservation']['bytes'], 'source prime capacity exceeded')
        require(clock() < deadline, 'source prime OS deadline')
    while not pool.prime_step(checkpoint):
        pass
    pool.finish_prime(checkpoint)
    return pool


class Storage:
    """Conservative sampled allocation high water, including retained histories.

    Retiring a file never refunds its sampled charge. Unobserved transient
    allocations are outside this sampled bound; this is not physical I/O/RSS.
    """
    def __init__(self, baseline=None, prior=None, *, source_pool=None):
        require(source_pool is None or baseline is None, 'Windows source lineage adapter not admitted')
        self.source_pool = source_pool
        self.baseline = {}
        self.carry = 0
        if baseline is not None:
            entries = {}
            for item in baseline['entries']:
                p = Path(item['path'])
                require(p.is_absolute() and '..' not in p.parts, 'absolute nonsymlink path required')
                key = (str(p), item['stat']['dev'], item['stat']['ino'])
                require(key not in self.baseline and str(p) not in entries, 'invalid retained baseline charge')
                self.baseline[key] = item['charge_bytes']
                entries[str(p)] = item
            require(sum(self.baseline.values()) == baseline['sum_bytes'] == prior['sum_bytes'] and
                    len(self.baseline) == prior['entry_count'], 'baseline sum/count mismatch')
            for root in baseline['roots']:
                sealed_stat(root)
            self.high = {}
            self.sample([path(r['path']) for r in baseline['roots']], sealed_entries=entries)
            require(self.high == self.baseline, 'retained baseline inventory drift')
        self.high = self.baseline.copy()
        self.carry = max(prior['prior_sampled_aggregate_highwater_bytes'], sum(self.baseline.values())) if prior else 0
        require(prior is None or self.carry == prior['carry_bytes'], 'sealed carry mismatch')

    def sample(self, roots, *, sealed_entries=None, mutable_roots=()):
        if self.source_pool is not None:
            for key, charge in self.source_pool.sample(roots).items():
                self.high[key] = max(self.high.get(key, 0), charge)
            return self.carry + sum(max(0, value-self.baseline.get(key, 0)) for key, value in self.high.items())
        pending = []
        baseline_names = {Path(key[0]) for key in self.baseline} if mutable_roots else set()
        def mutable_change(error):
            name = getattr(error, 'filename', None) or getattr(error, '_storage_path', None)
            return (isinstance(error, (FileNotFoundError, _AllocationChange)) and name is not None and Path(name) not in baseline_names
                    and any(Path(name).is_relative_to(root) and Path(name) != root for root in mutable_roots))
        def prefer_error(before, error):
            return error if before is None or (mutable_change(before) and not mutable_change(error)) else before
        def record(p, s, allocated):
            key = (str(p), s.st_dev, s.st_ino)
            self.high[key] = max(self.high.get(key, 0), s.st_size, allocated)
            if sealed_entries is not None:
                item = sealed_entries.get(str(p))
                require(item is not None, 'retained baseline inventory drift')
                actual = identity.stat_fields(s, allocated)
                require(all(actual[k] == v for k, v in item['stat'].items()), 'sealed stat drift: '+str(p))
                require(item['charge_bytes'] == max(s.st_size, allocated), 'invalid retained baseline charge')
        def drain():
            batch = pending.copy()
            pending.clear()
            failure = None
            for p, s, future in batch:
                try:
                    record(p, s, future.result())
                except BaseException as error:
                    if isinstance(error, FileNotFoundError):
                        error._storage_path = str(p)
                    if isinstance(error, _AllocationChange) and sealed_entries is None:
                        for observed, allocated in error.samples:
                            record(p, observed, allocated)
                        if os.name == 'nt' and error.kind == 'growth' and mutable_change(error):
                            # Same-ID append growth is a completed observation, not a retired name.
                            continue
                    failure = prefer_error(failure, error)
            if failure is not None:
                raise failure
        # Each call owns at most eight in-flight observations and joins every worker.
        allocation_pool = ThreadPoolExecutor(max_workers=8) if os.name == 'nt' else nullcontext()
        with allocation_pool as pool:
            failure = None
            try:
                for root in roots:
                    require(root.is_dir() and not root.is_symlink(), 'owned history disappeared')
                    if os.name == 'nt':
                        for q in (root, *root.parents):
                            require(not q.lstat().st_file_attributes & 0x400, 'owned reparse point')
                    before = root.stat()
                    def walk_error(value):
                        if os.name == 'nt' or not isinstance(value, FileNotFoundError):
                            raise value
                    # Mutable publications can retire or change a name during the walk.
                    # Reconcile this root, never a sealed admission or an observed denial.
                    for retry in range(8):
                        raced = None
                        try:
                            for folder, directories, files in os.walk(root, onerror=walk_error):
                                for name in directories+files:
                                    p = Path(folder, name)
                                    try:
                                        s = p.lstat()
                                    except FileNotFoundError:
                                        if os.name == 'nt':
                                            raise
                                        continue
                                    require(stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode), 'owned symlink/special file')
                                    require(not getattr(s, 'st_file_attributes', 0) & 0x400, 'owned reparse point')
                                    if stat.S_ISREG(s.st_mode):
                                        if pool is None:
                                            record(p, s, _allocated_bytes(p, s))
                                        else:
                                            pending.append((p, s, pool.submit(_allocated_bytes, p, s)))
                                            if len(pending) == 8:
                                                drain()
                        except BaseException as error:
                            raced = error
                        try:
                            drain()
                        except BaseException as error:
                            raced = prefer_error(raced, error)
                        if raced is None:
                            break
                        if not (os.name == 'nt' and sealed_entries is None and
                                mutable_change(raced) and retry < 7):
                            if isinstance(raced,_AllocationChange):
                                raced.add_note(repr(dict(storage_root=str(root)[:512],retry=retry,
                                    mutable=mutable_change(raced),sealed=sealed_entries is not None,
                                    baseline_name=Path(raced.filename) in baseline_names))[:1024])
                            raise raced
                        require(root.is_dir() and not root.is_symlink() and
                                os.path.samestat(before, root.stat()) and
                                not root.lstat().st_file_attributes & 0x400, 'owned root identity drift')
                    if os.name == 'nt':
                        require(not root.lstat().st_file_attributes & 0x400, 'owned reparse point')
                    require(root.is_dir() and not root.is_symlink() and os.path.samestat(before, root.stat()),
                            'owned root identity drift')
            except BaseException as error:
                failure = error
            try:
                drain()
            except BaseException as error:
                failure = failure or error
            if failure is not None:
                raise failure
        return self.carry + sum(max(0, value-self.baseline.get(key, 0)) for key, value in self.high.items())


class Monitor:
    def __init__(self, plan, lock, campaign, log, clock=time.monotonic, *, source_pool=None):
        self.disk_operation = threading.Lock()
        self.source_pool = source_pool
        if source_pool is not None:
            require(os.name == 'nt' and source_pool.lock is lock and source_pool.ready and
                    getattr(lock, 'source_pool', None) is source_pool and
                    tuple(path(r) for r in plan['source_reservation']['roots']) == source_pool.roots and
                    not source_pool.pending and 'selected639_lineage' not in plan and 'windows_lineage' not in plan,
                    'prepared Windows source component required; lineage admission deferred')
            source_pool.check()
        self.plan, self.lock, self.campaign, self.log, self.clock = plan, lock, campaign, Path(log), clock
        self.storage, self.source_storage, self.groups, self.externals = Storage(), Storage(), [], {}
        self.tiny_storage = Storage() if 'qualification' in plan else None
        if source_pool is not None:
            self.source_storage = Storage(source_pool=source_pool)
        if 'qualification' in plan:
            from .native_tiny import History
            self.lineage = History(plan)
            if self.lineage.namespace_baseline is not None:
                self.tiny_storage = Storage(self.lineage.namespace_baseline, self.lineage.namespace_prior)
        else:
            self.lineage = Lineage(plan) if 'selected639_lineage' in plan or 'windows_lineage' in plan else None
        if self.lineage:
            previous = self.lineage.value['prior_storage'][plan['os']]
            self.storage = Storage(self.lineage.baselines['native'], previous['native'])
            self.source_storage = Storage(self.lineage.baselines['source'], previous['source'])
        self.deadline = float('inf')
        self.last_progress, self.progress = clock(), None
        for role in ('product', 'harness'):
            group = plan[role]
            root, names = path(group['root']), list(group['sha256'])
            # Watch whole owning source directories, so a new decoder/helper
            # cannot appear between hashes. No uncontained Git subprocesses in
            # the supervisor: actual Git blob proofs run inside the caretaker.
            patterns = sorted({n.split('/')[0] for n in names})
            self.groups.append((root, patterns, frozen_metadata(root, patterns), group))
        self.git_freezes = [(path(plan[role]['root']), git_metadata(path(plan[role]['root'])))
                            for role in ('product', 'harness')]
        for key in ('python', 'executable', 'package_receipt', 'package', 'build_proof'):
            p = path(plan[key]['path'])
            self.externals[p] = stamp(p)
        for item in plan['tools']:
            p = path(item['path'])
            self.externals[p] = stamp(p)
        for item in plan['peers'].values():
            p = path(item['path'])
            self.externals[p] = stamp(p)
        if 'qualification' in plan:
            from .native_tiny import peer_pins
            for item in peer_pins(plan):
                p = path(item['path'])
                self.externals[p] = stamp(p)
        if os.name == 'nt':
            # Windows host discovery can lazily map reviewed native dependencies.
            require(plan['host'] == host(), 'OS/host identity drift')
        self.runtime = identity.runtime_requirements()
        self.dependencies = identity.dependency_metadata(plan['dependencies'], self.runtime)
        self.roots = [path(p) for p in plan['owned_roots']]
        self.volumes = [(path(v['path']), v['device']) for v in plan['volumes']]
        if self.lineage and 'qualification' not in plan and plan['os'] == 'Linux':
            require(self.lineage.source.stat().st_dev == path(plan['owned_root']).stat().st_dev,
                    'adopted source must share runner volume')
        require({str(p.stat().st_dev) for p in self.roots} <= {str(device) for _, device in self.volumes},
                'every owned volume must be mapped')
        for p in (*[path(r) for r in plan['source_reservation']['roots']], path(plan['product']['root']), path(plan['harness']['root']),
                  *(path(plan[k]['path']) for k in ('package', 'executable', 'python', 'build_proof', 'package_receipt')),
                  *(path(item['path']) for item in plan['tools']), *(path(item['path']) for item in plan['peers'].values()),
                  *(path(g['root']) for g in plan['dependencies'])):
            require(str(p.stat().st_dev) in {str(d) for _, d in self.volumes}, 'source/cache/artifact volume missing')

    def phase(self, seconds):
        self.deadline = self.clock()+seconds
        self.last_progress, self.progress = self.clock(), None
        self.native_counters, self.native_total = {}, 0

    def native_rows(self, phase, rows):
        previous = self.native_counters.get(phase, 0)
        if rows > previous:
            self.native_counters[phase] = rows
            self.native_total += rows-previous
            self.useful(('native-rows', self.native_total))

    def useful(self, value):
        # Only parsed monotone source/output row or byte facts qualify, never
        # elapsed time, quota, file/log size or an arbitrary changed log line.
        require(isinstance(value, tuple) and len(value) == 2 and type(value[1]) is int, 'useful progress schema')
        order = {'generated-bytes': 0, 'checkpoint': 1, 'native-rows': 0,
                 'published-csv-bytes': 1, 'verify-source': 0, 'verify-output': 1, 'verify-membership': 2}
        require(value[0] in order and value[1] >= 0, 'unknown/negative useful progress')
        if self.progress is None or (value[0] == self.progress[0] and value[1] > self.progress[1]):
            self.progress, self.last_progress = value, self.clock()
        elif order[value[0]] > order[self.progress[0]]:
            self.progress, self.last_progress = value, self.clock()

    def sample(self, start=False, reviewing=False, pulse=None):
        tick = self.clock()
        failure = None
        try:
            previous = getattr(self, 'last_capacity', None)
            require(previous is None or 0 <= tick-previous['sample_started_monotonic'] < LIMITS['sample_seconds'],
                    'disk observation start interval exceeded')
            if 'qualification' in self.plan:
                from .native_tiny import budget_check
                budget_check()
            pool = getattr(self, 'source_pool', None)
            if pool is not None:
                # The old private five-field component remains unadopted.
                result = pool.bounded(lambda: self._sample(start, reviewing))
                require(self.clock()-tick < 2, 'complete native guard operation exceeded two seconds')
            else:
                from .native_scale_host import bounded
                started_unix = time.time()
                bounded(lambda: self.hot_sample(reviewing))
                last_hot = [self.clock()]
                def poll():
                    if self.clock()-last_hot[0] >= .5:
                        bounded(lambda: self.hot_sample(reviewing))
                        if pulse is not None:
                            pulse()
                        last_hot[0] = self.clock()
                remaining = LIMITS['disk_observation_seconds']-(self.clock()-tick)
                require(remaining > 0, 'disk observation deadline')
                result = bounded(lambda: self.disk_sample(start), seconds=remaining, poll=poll)
                bounded(lambda: self.hot_sample(reviewing))
                require(self.clock()-tick < LIMITS['disk_observation_seconds'], 'disk observation deadline')
                result.update(sample_started_unix=started_unix, sample_started_monotonic=tick,
                              sample_completed_monotonic=self.clock())
                def retain():
                    with self.log.open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(result)+'\n')
                bounded(retain)
                self.last_capacity = result
            return result
        except BaseException as error:
            failure = error
            if os.name == 'nt':error.native_disk_deadline = tick+LIMITS['disk_observation_seconds']
            raise
        finally:
            self.last_sample_seconds = self.clock()-tick
            if 'qualification' in self.plan or 'windows_execution' in self.plan:
                try:
                    with self.log.with_name('guard-operations.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(dict(started_monotonic=tick, seconds=self.last_sample_seconds,
                            kind='initial-full-sample' if start else 'full-sample',
                            bound_seconds=2 if getattr(self, 'source_pool', None) is not None else LIMITS['disk_observation_seconds'],
                            completed=failure is None, error=str(failure) if failure else None))+'\n')
                except BaseException as error:
                    if failure is None:
                        raise
                    failure.add_note('guard timing retention failed: '+str(error))

    def hot_sample(self, reviewing=False):
        require(identity.runtime_requirements() == self.runtime, 'runtime native image/root drift')
        self.campaign.check()
        if self.lineage:
            self.lineage.check()
        self.lock.check()
        self.last_lock_proof = self.lock.proof()
        now = self.clock()
        require(now < self.deadline, 'phase deadline')
        require(reviewing or now-self.last_progress < LIMITS['no_progress_seconds'], 'no useful progress')
        require(self.plan['host'] == host(), 'OS/host identity drift')
        for root, before in self.git_freezes:
            current = git_metadata(root)
            if current != before:
                details = []
                def difference(name, old, new):
                    if old == new:return
                    if isinstance(old,dict) and isinstance(new,dict):
                        for key in sorted(set(old)|set(new)):
                            difference(name+'/'+key,old.get(key),new.get(key))
                    elif isinstance(old,(list,tuple)) and isinstance(new,(list,tuple)) and len(old)==len(new) and len(old) in (3,6,8):
                        labels = ('dev','ino','mode') if len(old)==3 else (
                            'dev','ino','size','mtime_ns','ctime_ns','mode','nlink','attributes')[:len(old)]
                        for field,a,b in zip(labels,old,new):difference(name+'/'+field,a,b)
                    else:details.append(dict(field=name,before=old,after=new))
                difference(str(root),before,current)
                error = ValueError('Git/source-role metadata drift: '+str(root))
                try:error.add_note(json.dumps(dict(changed=details[:16],truncated=len(details)>16),sort_keys=True)[:8192])
                except BaseException:pass
                raise error
        require(all(stamp(p) == value for p, value in self.externals.items()), 'tool/executable drift')

    def filesystem_sample(self):
        # Complete filesystem identity stays part of fresh capacity before work.
        for root, names, metadata, group in self.groups:
            require(frozen_metadata(root, names) == metadata, 'source freeze drift')
        require(all(frozen_metadata(root, inputs) == before for root, inputs, before in self.dependencies),
                'runtime dependency freeze drift')

    def _sample(self, start=False, reviewing=False):
        self.hot_sample(reviewing)
        return self.disk_sample(start)

    def disk_sample(self, start=False):
        require(self.disk_operation.acquire(blocking=False), 'previous disk observation still pending')
        try:
            result = self._disk_sample(start)
            self.filesystem_sample()
            return result
        finally:
            self.disk_operation.release()

    def _disk_sample(self, start=False):
        current_mutable = (path(self.plan['owned_root']), path(self.plan['campaign']))
        owned = self.storage.sample(self.roots, mutable_roots=current_mutable)
        require(owned < LIMITS['owned_bytes'], 'aggregate native storage high water')
        if 'qualification' in self.plan:
            fresh = self.tiny_storage.sample([path(self.plan['qualification']['namespace'])],
                mutable_roots=current_mutable)
            require(fresh <= self.plan['qualification']['new_bytes'], 'tiny new-data/evidence ceiling')
        pool = getattr(self, 'source_pool', None)
        source_roots = [path(r) for r in self.plan['source_reservation']['roots']]
        if pool is None:
            source_bytes = self.source_storage.sample(source_roots)
            require(source_bytes <= self.plan['source_reservation']['bytes'], 'separate source/cache/artifact reservation exceeded')
        free = []
        for p, device in self.volumes:
            require(str(p.stat().st_dev) == str(device), 'volume mapping drift')
            value = shutil.disk_usage(p).free
            require(value >= LIMITS['start_free_bytes'] if start else value >= LIMITS['stop_free_bytes'],
                    'physical free capacity')
            free.append(dict(path=str(p), device=str(device), free_bytes=value))
        if pool is not None:
            source_bytes = self.source_storage.sample(source_roots)
            require(source_bytes <= self.plan['source_reservation']['bytes'], 'separate source/cache/artifact reservation exceeded')
        value = dict(sampled_unix=time.time(), owned_sampled_highwater=owned, source_sampled_highwater=source_bytes, volumes=free,
                     phase_seconds_left=self.deadline-self.clock(), reservation=self.last_lock_proof)
        if pool is not None:
            pool.check()
            # Component observations are returned only by a completed fenced call.
            # The root owns future Windows receipt publication/admission.
            return value
        return value


def git_metadata(root):
    """Watch the selected worktree identity, not unrelated shared Git activity."""
    result = dict(root_directory=stamp(root))
    def record(file):
        result[str(file)] = frozen_metadata(file.parent,[file.name]) if os.path.lexists(file) else None
    def text(file, limit):
        before = frozen_metadata(file.parent,[file.name])
        require(file.is_file() and file.stat().st_size <= limit, 'bounded Git metadata file: '+str(file))
        value = file.read_text()
        require(frozen_metadata(file.parent,[file.name])==before, 'Git metadata changed while reading: '+str(file))
        return value.strip()
    def directory(folder):
        info = folder.lstat()
        require(stat.S_ISDIR(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                'actual plain Git metadata directory required: '+str(folder))
        # Fetch/maintenance can change directory times without changing this role.
        result[str(folder)] = (info.st_dev,info.st_ino,info.st_mode)
    dot = root/'.git'
    if dot.is_file():
        record(dot)
        raw = text(dot,4096)
        require(raw.startswith('gitdir: '), 'invalid worktree Git directory')
        gitdir = (root/raw[8:]).resolve()
    else:
        gitdir = dot
    directory(gitdir)
    common = gitdir
    record(gitdir/'commondir')
    if (gitdir/'commondir').is_file():
        common = (gitdir/text(gitdir/'commondir',4096)).resolve()
    directory(common)
    for file in (gitdir/'HEAD',gitdir/'index',gitdir/'config',gitdir/'config.worktree',common/'config'):
        record(file)
    head = text(gitdir/'HEAD',4096)
    def oid(value):
        require(len(value)==40 and all(c in '0123456789abcdef' for c in value), 'selected Git object ID required')
        return value
    if head.startswith('ref: '):
        name = head[5:]
        require(name.startswith('refs/') and all(part not in ('','.','..') for part in name.split('/')) and
                all(c.isalnum() or c in '/-_.' for c in name), 'bounded selected Git ref required')
        selected = common/name
        record(selected)
        if selected.is_file():
            value = oid(text(selected,256))
        else:
            packed = common/'packed-refs'
            # A packed file also owns unrelated refs. Validate a fresh stable read,
            # but freeze only this selected ref's value, not container timestamps.
            rows = [line.split() for line in text(packed,1024**2).splitlines()
                    if line and not line.startswith(('#','^'))]
            require(all(len(row)==2 for row in rows), 'invalid packed Git ref row')
            for row in rows:oid(row[0])
            values = [row[0] for row in rows if row[1]==name]
            require(len(values)==1, 'selected packed Git ref missing/ambiguous')
            value = oid(values[0])
        result['selected_ref'] = dict(name=name,oid=value)
    else:
        result['selected_commit'] = oid(head)
    return result
