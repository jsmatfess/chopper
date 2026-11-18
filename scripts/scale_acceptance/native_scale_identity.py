"""Native product/harness source roles and externally approved byte identities."""
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import time
from .guard import frozen_metadata as raw_frozen_metadata
from .verify import require, read_json, sha256
from ._native_file import _allocated_bytes, _directory_size
from .campaign_native639 import (PRODUCT, TREE, PACKAGE_RECEIPT, BUILD, BUILD_TREE,
    RECONCILIATION, PACKAGING_DELTA, LINEAGE_PATH, LINEAGE_SHA, LINUX_SCALE_PLAN_SHA, LINUX_SCALE_REPORTS)

REQUIRED = {'Cargo.toml', 'Cargo.lock', 'crates', 'vendor', 'ui/public',
            'ui/index.html', 'ui/style.css', 'ui/src', 'scripts',
            'ui/package.json', 'ui/package-lock.json'}



def stat_fields(s, allocated, p=None):
    size = s.st_size
    if p is not None and os.name == 'nt' and stat.S_ISDIR(s.st_mode):
        size = _directory_size(p, s)
    return dict(dev=s.st_dev, ino=s.st_ino, size=size, mtime_ns=s.st_mtime_ns,
                ctime_ns=s.st_ctime_ns, mode=s.st_mode, nlink=s.st_nlink,
                blocks=getattr(s, 'st_blocks', 0), allocated_bytes=allocated)


def sealed_stat(item):
    p, expected = path(item['path']), item['stat']
    s = p.stat()
    if os.name == 'nt':
        for q in (p, *p.parents):
            require(not q.lstat().st_file_attributes & 0x400, 'sealed reparse point')
    allocated = _allocated_bytes(p, s) if stat.S_ISREG(s.st_mode) else getattr(s, 'st_blocks', 0)*512
    actual = stat_fields(s, allocated, p)
    require(all(actual[k] == v for k, v in expected.items()), 'sealed stat drift: '+str(p))
    require(stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode), 'sealed special file')
    return p


def windows_root_union(before, additions):
    roots={path(name) for name in [*before,*additions]}
    return sorted(str(root) for root in roots if not any(root!=other and root.is_relative_to(other) for other in roots))


def execution_shapes(plan):
    if plan['os'] == 'Windows' and 'qualification' not in plan and 'windows_lineage' in plan:
        from .native_tiny import pinned_json
        descriptor, _ = pinned_json(plan['windows_lineage'], 64*1024**2)
        if 'retained_windows_d' in descriptor:
            return ('G',)
    return ('D','G')


def retained_windows_d(plan, descriptor, pins=None, *, resolve_path=None):
    """An accepted D keeps its original plan; only a fresh unspent G may follow."""
    from .native_tiny import pinned_json
    from .native_scale_control import native_recipe
    require(set(descriptor) == {'plan','report','canonical','consumed','verified','result','independent','capacity_log','started','linux_d_report'},
            'complete retained WindowsD proof required')
    pins = {} if pins is None else pins
    resolve_path = path if resolve_path is None else resolve_path
    def load(name):
        item = descriptor[name]
        value, before = pinned_json(dict(item,path=str(resolve_path(item['path']))),16*1024**2)
        pins[resolve_path(item['path'])] = before
        return value
    old, report, claim, consumed, verified, result, audit, started = (
        load(name) for name in ('plan','report','canonical','consumed','verified','result','independent','started'))
    old_sha = descriptor['plan']['sha256']
    linux_d = load('linux_d_report')
    require(descriptor['linux_d_report']['sha256'] == LINUX_SCALE_REPORTS['D'] and
            linux_d['passed'] is True and linux_d['slot'] == 'LinuxD' and
            linux_d['plan_sha256'] == LINUX_SCALE_PLAN_SHA, 'exact accepted LinuxD parity proof required')
    require(old['os'] == 'Windows' and old['host'] == plan['host'] and 'qualification' not in old and
            old['product']['commit'] == plan['product']['commit'] == PRODUCT and
            {key:value for key,value in old['product'].items() if key!='root'} ==
            {key:value for key,value in plan['product'].items() if key!='root'} and
            old['features'] == plan['features'] and
            all(old[key]['sha256'] == plan[key]['sha256'] for key in ('executable','package','package_receipt','build_proof')) and
            old['limits'] == plan['limits'] and old['reservation'] == plan['reservation'] and
            old['fixtures'] == {shape:native_recipe(shape) for shape in ('D','G')} and
            old['source_reservation']['bytes'] == plan['source_reservation']['bytes'],
            'retained WindowsD host/product/policy mismatch')
    data, campaign = resolve_path(old['owned_root']), resolve_path(old['campaign'])
    require(data.parent == campaign.parent == resolve_path(old['windows_execution']['namespace']) and
            data.name == 'data' and campaign.name == 'campaign', 'exact retained Windows namespace required')
    require(all(resolve_path(descriptor[name]['path']) == data/file for name,file in (
                ('report','D-verified.json'),('result','scale-result.json'),('capacity_log','capacity.jsonl'))) and
            all(resolve_path(descriptor[name]['path']) == campaign/file for name,file in (
                ('canonical','WindowsD-canonical.json'),('consumed','WindowsD-consumed.json'),
                ('verified','WindowsD-verified.json'),('started','Windows-started.json'))) and
            resolve_path(descriptor['independent']['path']) == data.parent/'after-exit-proof.json',
            'retained WindowsD exact original record paths required')
    require(report['passed'] is True and report['evidence_kind'] == 'native-scale' and
            report['slot'] == claim['slot'] == consumed['slot'] == verified['slot'] == 'WindowsD' and
            report['host'] == old['host'] and report['product'] == claim['product'] == PRODUCT and
            report['plan_sha256'] == claim['plan_sha256'] == consumed['plan_sha256'] == verified['plan_sha256'] == old_sha and
            claim['lineage_sha256'] == LINEAGE_SHA and verified['passed'] is True and
            verified['sha256'] == descriptor['report']['sha256'] and
            resolve_path(verified['report']) == resolve_path(descriptor['report']['path']) and
            claim['campaign'] == old['campaign'] and claim['owned_root'] == old['owned_root'] and
            consumed['claim_sha256'] == descriptor['canonical']['sha256'] and
            consumed['proposal_sha256'] == claim['proposal_sha256'] and
            report['report']['source_sha256'] == linux_d['report']['source_sha256'],
            'retained WindowsD report/canonical chain mismatch')
    require(result['passed'] is False and result['scale_acceptance'] is False and result['plan_sha256'] == old_sha and
            result['os'] == 'Windows' and result['host'] == old['host'] and
            result['original_lock']['original_descriptor_closed'] is True and
            result['original_lock']['capture_eof_joined'] is True and
            result['original_lock']['path'] == old['reservation']['lock_path'] and
            audit['schema'] == 'native103-windows-scale-after-exit-v1' and audit['qualification_passed'] is False and
            audit['qualification_sha256'] == descriptor['result']['sha256'] and
            audit['original_byte_zero_available'] is True and audit['independent_probe_released'] is True and
            audit['administrative_recovery'] is False and
            audit['original_lock_stat'] == result['original_lock']['stat'] == old['windows_execution']['original_lock_stat'] and
            audit['verifier_role']['sha256'] == old['harness']['sha256']['scripts/scale_acceptance/native_tiny.py'] and
            audit['owned_births'] and all(row['absent'] is True for row in audit['owned_births']) and
            all(row['empty_owned_job'] is True for row in audit['phases']) and
            {'D-generation','D-Run','D-verify'} <= {resolve_path(row['directory']).name for row in audit['phases']} and
            started['plan_sha256'] == old_sha,
            'retained WindowsD normal failed-session closure required')
    item = descriptor['capacity_log'];file = resolve_path(item['path']);before = stamp(file)
    require(file.is_file() and file.stat().st_size <= 16*1024**2 and sha256(file) == digest(item['sha256']),
            'retained Windows capacity log pin mismatch')
    raw = file.read_bytes()
    require(raw.endswith(b'\n') and stamp(file) == before, 'complete retained Windows capacity log required')
    samples = [json.loads(line) for line in raw.splitlines()]
    require(samples, 'retained capacity samples required')
    # Every sample is from the same original keeper and exact retained Original.
    require(all(all(result['original_lock'].get(key) == value for key,value in row['reservation'].items())
                for row in samples), 'retained capacity owner mismatch')
    pins[file] = before
    floors = {pool:max(row[field] for row in samples) for pool,field in
              (('native','owned_sampled_highwater'),('source','source_sampled_highwater'))}
    require(all(type(amount) is int and amount >= 0 for amount in floors.values()) and
            floors['source'] <= plan['source_reservation']['bytes'] and floors['native'] < plan['limits']['owned_bytes'],
            'retained highwater counters/capacity required')
    return dict(descriptor=descriptor,plan=old,report=report,floors=floors,started=started)


class Lineage:
    """One immutable Linux predecessor, never a selectable recovery manifest."""
    def __init__(self, plan):
        if plan['os'] == 'Windows':
            self._windows(plan)
            return
        require(plan['os'] == 'Linux', 'Windows admission deferred: fresh OS-local proof and current Linux seal/parity required')
        require(plan['selected639_lineage'] == dict(path=LINEAGE_PATH, sha256=LINEAGE_SHA),
                'fixed selected639 lineage required')
        p = path(LINEAGE_PATH)
        before = stamp(p)
        require(sha256(p) == LINEAGE_SHA, 'lineage SHA mismatch')
        self.value = v = read_json(p, 8*1024**2)
        self.pinned = {p: before}
        require(v['schema'] == 'selected639-lineage-v1' and v['selected_product']['commit'] == PRODUCT
                and v['prior_generation_ms'] == 324064, 'lineage product/debit mismatch')
        current = v['current']
        require(plan['campaign'] == current['campaign'] and plan['owned_root'] == current['linux_os_root'],
                'fixed current namespace/OS root required')
        self.adopt = v['adopt_linux_d']
        self.source = path(self.adopt['input']['path'])
        require(self.source == path(self.adopt['data_directory'])/'input.csv', 'literal old input required')
        roots = [path(r) for r in plan['owned_roots']]
        sources = [path(r) for r in plan['source_reservation']['roots']]
        require(path(current['canonical_slot_ledger']) in roots, 'canonical ledger must be reserved')
        require(plan['source_reservation']['bytes'] == v['prior_storage']['Linux']['source_reservation_bytes'],
                'sealed source reservation required')
        self.baselines = {}
        for pool, reserved in (('native', roots), ('source', sources)):
            item = v['prior_storage']['Linux'][pool]
            require(all(path(r['path']) in reserved for r in item['retained_roots']), 'retained roots missing')
            for old in item['retained_roots']:
                require(not path(plan['owned_root']).is_relative_to(path(old['path'])) and
                        not path(old['path']).is_relative_to(path(plan['owned_root'])), 'old/new roots overlap')
        def pin_records(value):
            if isinstance(value, dict):
                if {'path', 'sha256'} <= value.keys():
                    q = path(value['path'])
                    if 'stat' in value:
                        sealed_stat(value)
                    s = stamp(q)
                    require(q.is_file() and q.stat().st_size <= 64*1024**2 and
                            sha256(q) == digest(value['sha256']) and stamp(q) == s, 'sealed record bytes drift: '+str(q))
                    self.pinned[q] = s
                elif {'path', 'stat', 'expected_sha256'} <= value.keys():
                    # Parent stat-only artifact commitments grant no content read.
                    q = sealed_stat(value)
                    self.pinned[q] = stamp(q)
                for child in value.values():
                    pin_records(child)
            elif isinstance(value, list):
                for child in value:
                    pin_records(child)
        pin_records(v)
        for pool in ('native', 'source'):
            item = v['prior_storage']['Linux'][pool]
            self.baselines[pool] = read_json(item['path'], 64*1024**2)
        old_start = read_json(v['prior_records']['original_start']['path'])
        old_result = read_json(v['prior_records']['original_result']['path'])
        require(old_start['plan_sha256'] == v['old_plan']['sha256'] and
                time.time()-old_start['started'] >= 28800 and old_result['passed'] is False
                and old_result['error'] == 'source freeze drift', 'old session not terminal/expired')
        custody = read_json(v['parent_custody']['path'])
        require(custody['old_plan_sha256'] == v['old_plan']['sha256'] and
                custody['original_lock_available_and_released'] is True and
                all(p['pid_absent'] is True for p in custody['processes']) and
                all(not c['pids'] for c in custody['owned_cgroup_census']), 'old custody proof incomplete')
        self.check()

    def _windows(self, plan):
        """Current NTFS measurements plus exact opaque accepted Linux custody."""
        from .native_tiny import pinned_json, History, namespace_retirement_debt
        descriptor = plan['windows_lineage']
        value, before = pinned_json(descriptor, 64*1024**2)
        require(value['schema'] == 'selected639-windows-lineage-v1' and value['host'] == plan['host'] and
                value['selected_product'] == PRODUCT and value['provenance'], 'current Windows lineage required')
        self.pinned = {path(descriptor['path']):before}
        def pin(item, maximum=16*1024**2):
            record, observed = pinned_json(item, maximum)
            self.pinned[path(item['path'])] = observed
            return record
        for item in value['provenance']:
            pin(item, 64*1024**2)
        linux = value['linux']
        require(linux['plan']['sha256'] == LINUX_SCALE_PLAN_SHA,
                'exact accepted Linux plan required')
        previous = pin(linux['plan'])
        require(previous['os'] == 'Linux' and previous['product']['commit'] == PRODUCT and
                previous['selected639_lineage'] == dict(path=LINEAGE_PATH,sha256=LINEAGE_SHA),
                'selected Linux predecessor identity mismatch')
        completed = pin(linux['completion'])
        require(completed['passed'] is True and completed['plan_sha256'] == linux['plan']['sha256'],
                'accepted Linux OS completion required')
        expected = LINUX_SCALE_REPORTS
        for shape in ('D','G'):
            peer = plan['peers'][shape]
            require(peer['sha256'] == expected[shape] and peer['plan_sha256'] == linux['plan']['sha256'],
                    'exact accepted same-size Linux peer required')
            report = pin(peer)
            claim = pin(linux['claims'][shape])
            record = pin(linux['records'][shape])
            consumed = pin(linux['consumed'][shape])
            require(report['os'] == report['host']['os'] == 'Linux' and report['passed'] is True and
                    report['product'] == PRODUCT and report['slot'] == claim['slot'] == record['slot'] ==
                    consumed['slot'] == 'Linux'+shape and report['plan_sha256'] == claim['plan_sha256'] ==
                    record['plan_sha256'] == consumed['plan_sha256'] == linux['plan']['sha256'] and
                    record['passed'] is True and record['sha256'] == peer['sha256'] and
                    consumed['claim_sha256'] == linux['claims'][shape]['sha256'] and
                    claim['product'] == PRODUCT and claim['lineage_sha256'] == LINEAGE_SHA and
                    claim['proposal_sha256'] == consumed['proposal_sha256'] and
                    report['report']['source_sha256'] == peer['source_sha256'], 'Linux canonical/report chain mismatch')
            require(shape != 'G' or report['external_memory_claim'] == 'present', 'accepted Linux G spill required')
        history = value['storage']
        require(history['allocation_origin']['kind'] == 'fresh-native-baseline; legacy metrics retained separately' and
                history['allocation_origin']['legacy_records'], 'Windows origin/legacy attribution required')
        for item in history['allocation_origin']['legacy_records']:
            pin(item,64*1024**2)
        require(type(history['prior_generation_ms']) is int and history['prior_generation_ms'] >= 0,
                'retained Windows elapsed debit required')
        self.baselines = history['baselines']
        self.allocation_origin = history['allocation_origin']
        fresh = {plan['owned_root'],plan['campaign']}
        require(set(history['fresh_roots']) == fresh, 'exact current Windows scale roots required')
        for pool, roots in (('native',set(plan['owned_roots'])-fresh),
                            ('source',set(plan['source_reservation']['roots']))):
            baseline = self.baselines[pool]
            charges = History._baseline_charges(baseline)
            prior = history['prior_storage'][pool]
            require({r['path'] for r in baseline['roots']} == roots and
                    prior['sum_bytes'] == sum(charges.values()) and prior['entry_count'] == len(charges) and
                    prior['carry_bytes'] == prior['prior_sampled_aggregate_highwater_bytes'] >= prior['sum_bytes'],
                    'complete Windows baseline/carry required')
        transition = history['retained_transition']
        prior_plan = pin(transition['previous_plan'])
        require(prior_plan['os'] == 'Windows' and prior_plan['host'] == plan['host'],
                'retained Windows host mismatch')
        from .native_tiny import preflight
        preflight(path(transition['previous_plan']['path']),prior_plan,
            path(transition['previous_preflight']['path']),transition['previous_preflight']['sha256'])
        pin(transition['previous_preflight'])
        old = pin(prior_plan['qualification']['windows_history'],64*1024**2)
        require(old['prior_generation_ms'] <= history['prior_generation_ms'], 'Windows elapsed debit cannot refund')
        for pool in ('native','source'):
            before = History._baseline_charges(old['baselines'][pool])
            current = History._baseline_charges(self.baselines[pool])
            growth = sum(max(0,amount-before.get(key,0)) for key,amount in current.items())
            missing_namespace_debt = namespace_retirement_debt(prior_plan,self.baselines[pool]) if pool=='native' else 0
            require(all(any(path(r['path']).is_relative_to(path(current['path'])) for current in self.baselines[pool]['roots'])
                        for r in old['baselines'][pool]['roots']) and
                    history['prior_storage'][pool]['carry_bytes'] >= old['prior_storage'][pool]['carry_bytes']+growth+missing_namespace_debt,
                    'retained Windows allocation cannot refund')
        if 'retained_windows_d' in value:
            self.retained_d = retained_windows_d(plan,value['retained_windows_d'],self.pinned)
            require(all(history['prior_storage'][pool]['carry_bytes'] >= amount
                        for pool,amount in self.retained_d['floors'].items()), 'retained Windows highwater cannot refund')
            require(history['prior_generation_ms'] >= self.retained_d['started']['prior_generation_ms'],
                    'retained Windows OS debit cannot refund')
            require(all(any(path(root).is_relative_to(path(current)) for current in plan['owned_roots'])
                        for root in self.retained_d['plan']['owned_roots']), 'retained Windows roots missing')
        self.value = dict(prior_generation_ms=history['prior_generation_ms'],
            prior_storage=dict(Windows=history['prior_storage']),current=dict(
                canonical_slot_ledger=linux['canonical_slot_ledger'],windows_os_root=plan['owned_root']))
        self.windows_plan = plan
        self.check()

    def claim_path(self, slot):
        if hasattr(self,'windows_plan'):
            return path(self.windows_plan['campaign'])/(slot+'-canonical.json')
        return path(self.value['current']['canonical_slot_ledger'])/(slot+'-consumed.json')

    def check(self):
        for p, before in self.pinned.items():
            require(stamp(path(str(p))) == before, 'lineage metadata drift: '+str(p))
        if hasattr(self,'windows_plan'):
            return
        for item in (self.adopt['input'], self.adopt['job'], self.adopt['fixture'], self.adopt['checkpoint']):
            sealed_stat(item)
        sealed_stat(dict(path=self.adopt['data_directory'], stat=self.adopt['data_directory_stat']))
        require(self.source.stat().st_nlink == 1, 'adopted input alias')
        old = path(self.adopt['data_directory'])
        require({p.name for p in old.iterdir()} == set(self.adopt['original_entries']) and
                not any((old/'temp').iterdir()), 'old data entries/temp drift')
        absence = self.value['prior_absence']
        for item in absence['completion_seals'] + [s[k] for s in absence['slots'] for k in ('consumed', 'verified')]:
            require(not os.path.lexists(path(item['path'])), 'old consumed/verified/completion appeared')
        require({p.name for p in path(self.value['old_campaign']).iterdir()} ==
                set(absence['observed_campaign_entries']), 'old campaign entries drift')


def path(value):
    p = Path(value)
    require(p.is_absolute() and '..' not in p.parts and
            all(not q.is_symlink() for q in (p, *p.parents)), 'absolute nonsymlink path required')
    return p


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value), 'expected SHA-256 required')
    return value


def stamp(p):
    s = p.stat()
    size = s.st_size
    if os.name == 'nt' and stat.S_ISDIR(s.st_mode):
        size = _directory_size(p, s)
    return [s.st_dev, s.st_ino, size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode]


def frozen_metadata(root, patterns):
    """Native directory snapshots use the same bound logical EOF as their seals."""
    if patterns == ['**/*']:
        patterns = [glob.escape(child.name) for child in root.iterdir()]
        require(patterns, 'frozen input missing: **/*')
    entries = raw_frozen_metadata(root, patterns)
    if os.name == 'nt':
        for name, before in entries.items():
            if stat.S_ISDIR(before[5]):
                p = root/name
                observed = p.lstat()
                actual = (observed.st_dev, observed.st_ino, before[2], observed.st_mtime_ns,
                          observed.st_ctime_ns, observed.st_mode)
                if len(before) > 6:
                    actual += (observed.st_nlink, getattr(observed, 'st_file_attributes', 0))
                require(actual == before, 'directory source metadata drift')
                entries[name] = (*before[:2], _directory_size(p, observed), *before[3:])
    return entries


def git(root, *args, raw=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    env['GIT_NO_REPLACE_OBJECTS'] = '1'
    value = subprocess.check_output(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args], env=env, timeout=4)
    return value if raw else value.decode().strip()


def producing_source(root, selected, reconciliation):
    """Attribute the three packaging edits without relabelling the original build."""
    require(reconciliation['selected_commit'] == PRODUCT and reconciliation['selected_tree'] == TREE
            and reconciliation['artifact_build_commit'] == BUILD
            and reconciliation['artifact_build_tree'] == BUILD_TREE
            and set(reconciliation['changed_paths']) == PACKAGING_DELTA,
            'selected/build reconciliation mismatch')
    require(git(root, 'rev-parse', BUILD+'^{tree}') == BUILD_TREE
            and set(git(root, 'diff', '--name-only', '--no-renames', BUILD, PRODUCT).splitlines()) == PACKAGING_DELTA,
            'only three packaging/docs source changes permitted')
    unchanged = set(selected) - PACKAGING_DELTA
    require(len(unchanged) == 1116 and
            set(reconciliation['unchanged_product_source_files']) == unchanged,
            'complete 1116 unchanged source proof required')
    return {**selected, **{name: hashlib.sha256(git(root, 'show', BUILD+':'+name, raw=True)).hexdigest()
                          for name in PACKAGING_DELTA}}


def source_map(group):
    """Compare actual bytes to actual Git blobs, including the complete vendor tree."""
    root = path(group['root'])
    require(git(root, 'rev-parse', 'HEAD') == group['commit'] and
            git(root, 'rev-parse', 'HEAD^{tree}') == group['tree'], 'Git source identity mismatch')
    require(not git(root, 'status', '--porcelain', '--untracked-files=normal'), 'dirty source root')
    entries = git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD').split('\0')
    blobs = {}
    for entry in filter(None, entries):
        info, name = entry.split('\t', 1)
        mode, kind, oid = info.split()
        require(mode in ('100644', '100755') and kind == 'blob', 'nonregular Git source')
        blobs[name] = oid
    require(blobs == group['git_blobs'], 'complete actual Git blob map required')
    actual = {}
    for name, oid in blobs.items():
        p = path(str(root / name))
        size = p.stat().st_size
        blob, hashed = hashlib.sha1(b'blob ' + str(size).encode() + b'\0'), hashlib.sha256()
        before = stamp(p)
        with p.open('rb') as stream:
            while raw := stream.read(1024*1024):
                blob.update(raw)
                hashed.update(raw)
        require(stamp(p) == before and blob.hexdigest() == oid,
                'Git/worktree byte mismatch: ' + name)
        actual[name] = hashed.hexdigest()
    require(actual == group['sha256'], 'full source SHA map mismatch')
    require(all(any(n == r or n.startswith(r + '/') for n in actual) for r in REQUIRED),
            'full source/vendor/native embedded assets required')
    return root, frozen_metadata(root, list(actual))


def runtime_requirements():
    """Discover this interpreter's stdlib/extension roots and mapped native images.

    No caller-supplied dependency label establishes coverage. Unsupported census
    or an unreadable mapping fails closed. Parent preloads runtime modules before
    freezing the plan; subsequent native-image changes invalidate that freeze.
    """
    roots = {Path(sysconfig.get_path(key)).resolve() for key in ('stdlib', 'platstdlib')}
    extension = sysconfig.get_config_var('DESTSHARED')
    if extension:
        roots.add(Path(extension).resolve())
    executable = Path(sys.executable).resolve()
    files, images = {executable}, set()
    # A configured stdlib ZIP may be absent in an ordinary directory install.
    files.update(Path(p).resolve() for p in sys.path if p.endswith('.zip') and Path(p).is_file())
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes as W
        dll = ctypes.WinDLL('kernel32', use_last_error=True)
        dll.GetCurrentProcess.restype = W.HANDLE
        dll.K32EnumProcessModules.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
        dll.K32EnumProcessModules.restype = W.BOOL
        dll.K32GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
        dll.K32GetModuleFileNameExW.restype = W.DWORD
        handles, needed = (W.HMODULE * 2048)(), W.DWORD()
        process = dll.GetCurrentProcess()
        require(dll.K32EnumProcessModules(process, handles, ctypes.sizeof(handles), ctypes.byref(needed))
                and 0 < needed.value <= ctypes.sizeof(handles)
                and needed.value % ctypes.sizeof(W.HMODULE) == 0, 'runtime native image census failed')
        for handle in handles[:needed.value // ctypes.sizeof(W.HMODULE)]:
            name = ctypes.create_unicode_buffer(32768)
            size = dll.K32GetModuleFileNameExW(process, handle, name, len(name))
            require(0 < size < len(name), 'runtime native image path unavailable')
            images.add(Path(name.value).resolve())
    else:
        for line in Path('/proc/self/maps').read_text().splitlines():
            parts = line.split(maxsplit=5)
            if len(parts) == 6 and parts[5].startswith('/'):
                require(not parts[5].endswith(' (deleted)'), 'runtime mapped image deleted')
                images.add(Path(parts[5]).resolve())
    require(executable in images, 'runtime executable mapping unavailable')
    files.update(images)
    require(roots and files and all(p.is_dir() for p in roots), 'runtime roots unavailable')
    return roots, files


def dependency_metadata(groups, requirements):
    """Require nonempty exact maps and all independently discovered runtime bytes."""
    require(groups, 'explicit Python runtime/dependency byte maps required')
    covered, result = set(), []
    for group in groups:
        require(group['inputs'] and group['sha256'], 'nonempty runtime dependency maps required')
        root = path(group['root'])
        before = frozen_metadata(root, group['inputs'])
        actual_names = {name for name in before if (root/name).is_file()}
        require(actual_names == set(group['sha256']), 'runtime dependency file coverage mismatch')
        covered.update(root/name for name in actual_names)
        result.append((root, group['inputs'], before))
    roots, files = requirements
    required = set(files)
    for root in roots:
        inventory = frozen_metadata(root, ['**/*'])
        required.update(root/name for name in inventory if (root/name).is_file())
        # Watch independently required directories, even when approved maps use
        # explicit filenames; a newly introduced Python module is also drift.
        result.append((root, ['**/*'], inventory))
    require(required <= covered, 'actual Python runtime/dependency coverage missing')
    return result


def build_receipt(value, source, executable):
    """Bind one executable-producing attempt, never a union of unrelated steps.

    Maintained runner attempts store their own inputs/artifacts; dependencies
    name attempt IDs but do not prove which intermediate bytes a command read.
    Until an explicit byte-linked chain is supported, require direct coverage.
    """
    require(value['summary']['incomplete'] == 0 and value['attempts'] and
            all(a['status'] == 'passed' and a['exit_code'] == 0 for a in value['attempts']),
            'incomplete native build proof')
    needed = {n: h for n, h in source.items()
              if n in ('Cargo.toml', 'Cargo.lock', 'ui/index.html', 'ui/style.css') or
              n.startswith(('crates/', 'vendor/', 'ui/public/', '.cargo/'))}
    require(needed, 'actual build input/artifact source coverage missing')
    def matches(attempt):
        covered = {n.replace('\\', '/'): item['sha256'] for n, item in attempt['inputs'].items()
                   if isinstance(item, dict) and 'sha256' in item}
        artifacts = {item.get('sha256') for item in attempt['artifacts'].values() if isinstance(item, dict)}
        return executable in artifacts and all(covered.get(n) == h for n, h in needed.items())
    require(any(matches(a) for a in value['attempts']), 'actual build input/artifact coverage mismatch')


def build_binding(plan, proof, pin):
    """Check fresh package attribution and original same-attempt build receipts."""
    require(proof['schema'] == 'native-scale-build-binding-v2' and proof['features'] == []
            and proof['product_commit'] == PRODUCT and proof['product_tree'] == TREE
            and proof['source_sha256'] == plan['product']['sha256']
            and proof['executable_sha256'] == plan['executable']['sha256']
            and proof['package_receipt_sha256'] == PACKAGE_RECEIPT
            and proof['package_sha256'] == plan['package']['sha256'], 'build/package/source proof mismatch')
    pin(proof['source_reconciliation'])
    require(proof['source_reconciliation']['sha256'] == RECONCILIATION,
            'immutable selected639 reconciliation required')
    original = producing_source(path(plan['product']['root']), plan['product']['sha256'],
                               read_json(proof['source_reconciliation']['path']))
    require(proof['artifact_build_commit'] == BUILD and proof['artifact_build_tree'] == BUILD_TREE
            and proof['artifact_build_source_sha256'] == original,
            'original feb build source binding mismatch')
    # A binding is not a substitute for the maintained runner's original receipts.
    for receipt in proof['runner_receipts']:
        pin(receipt)
        value = read_json(receipt['path'], 64 * 1024**2)
        build_receipt(value, original, plan['executable']['sha256'])
    require(proof['runner_receipts'], 'original successful build receipts required')


class Identity:
    def __init__(self, plan):
        self.plan, self.groups, self.external = plan, [], {}
        require(plan['schema'] == 'native-scale-v1' and plan['features'] == [], 'native default plan required')
        require(plan['product']['commit'] == PRODUCT and plan['product']['tree'] == TREE, 'selected product639 required')
        if 'qualification' in plan:
            from .native_tiny import History
            self.lineage = History(plan)
        else:
            self.lineage = Lineage(plan)
        require(path(plan['product']['root']) != path(plan['harness']['root']), 'distinct source roles required')
        for role in ('product', 'harness'):
            group = plan[role]
            root, metadata = source_map(group)
            self.groups.append((root, list(group['sha256']), metadata))
        require(Path(__file__).resolve() == path(plan['harness']['root']) / 'scripts/scale_acceptance/native_scale_identity.py',
                'actual harness role mismatch')
        require(plan['host'] == host(), 'actual native OS/host mismatch')
        require(plan['environment_sha256'] == environment_digest(), 'approved environment mismatch')
        require(plan['host']['os'] in ('Linux', 'Windows'), 'unsupported native platform')
        require(path(plan['python']['path']) == Path(sys.executable).resolve() and
                plan['python']['version'] == sys.version, 'actual Python mismatch')
        for key in ('python', 'executable', 'package_receipt', 'package', 'build_proof'):
            self.pin(plan[key])
        for item in plan['tools']:
            self.pin(item)
        if plan.get('execution_kind') == 'batch':
            from .hosted_qualification import batch_inputs
            for item in batch_inputs(plan['frozen_batch']):
                self.pin(item)
        for item in plan['peers'].values():
            self.pin(item)
        if 'qualification' in plan:
            from .native_tiny import peer_pins
            for item in peer_pins(plan):
                self.pin(item)
        require(plan['tools'], 'expected external tool byte map required')
        selected_git = str(Path(shutil.which('git') or '').resolve())
        require(any(item['path'] == selected_git for item in plan['tools']), 'actual selected Git bytes must be bound')
        self.runtime = runtime_requirements()
        dependencies = dependency_metadata(plan['dependencies'], self.runtime)
        for group, (root, inputs, before) in zip(plan['dependencies'], dependencies):
            actual = {name: sha256(root/name) for name in before if (root/name).is_file()}
            require(actual == group['sha256'], 'runtime dependency byte map mismatch')
            require(before == frozen_metadata(root, inputs), 'runtime dependency admission drift')
        self.groups.extend(dependencies)
        require(plan['package_receipt']['sha256'] == PACKAGE_RECEIPT, 'immutable package receipt required')
        package = read_json(plan['package_receipt']['path'], 8*1024**2)
        kind, member, target = ('linux_x86_64', 'chopper', 'x86_64-unknown-linux-gnu') if plan['os'] == 'Linux' else (
            'windows_x86_64', 'chopper.exe', 'x86_64-pc-windows-msvc')
        package_name = Path(plan['package']['path']).name
        native = package['native'][kind]
        require(package['schema_version'] == package['packaging_schema_version'] == 1
                and package['release_source_commit'] == PRODUCT and package['release_source_tree'] == TREE
                and package['dirty_source'] is False and native['target'] == target,
                'actual package/source/platform receipt mismatch')
        require(package['packages'][package_name] == dict(bytes=Path(plan['package']['path']).stat().st_size,
                    sha256=plan['package']['sha256'])
                and package['package_members'][package_name][member] == dict(
                    bytes=Path(plan['executable']['path']).stat().st_size, sha256=plan['executable']['sha256'])
                and native['sha256'] == plan['executable']['sha256'], 'actual package/executable member mismatch')
        proof = read_json(plan['build_proof']['path'], 64 * 1024**2)
        build_binding(plan, proof, self.pin)
        self.check()

    def pin(self, item):
        p = path(item['path'])
        before = stamp(p)
        require(p.is_file() and sha256(p) == digest(item['sha256']) and stamp(p) == before,
                'expected external bytes mismatch: ' + str(p))
        self.external[p] = before

    def check(self):
        self.lineage.check()
        current = runtime_requirements()
        if current != self.runtime:
            error = ValueError('runtime native image/root drift')
            try:
                changes = {kind+'_'+direction: sorted(map(str, values))
                    for kind, before, after in zip(('roots','images'), self.runtime, current)
                    for direction, values in (('added',after-before),('removed',before-after))}
                note = json.dumps(changes, sort_keys=True)
                error.add_note(note[:8192]+(' [truncated]' if len(note)>8192 else ''))
            except BaseException:
                pass  # Diagnostics cannot replace the strict identity denial.
            raise error
        for root, names, metadata in self.groups:
            require(frozen_metadata(root, names) == metadata, 'source freeze drift')
        require(all(stamp(p) == s for p, s in self.external.items()), 'external tool/exe/proof drift')
        require(self.plan['host'] == host(), 'host drift')


def host():
    if os.name == 'nt':
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32),
                        ('total', ctypes.c_uint64), ('remaining', ctypes.c_uint64*6)]
        value = Memory()
        value.length = ctypes.sizeof(value)
        require(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)), 'actual RAM identity unavailable')
        ram = value.total
    else:
        ram = os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    cpu = os.cpu_count()
    require(type(cpu) is int and cpu > 0 and ram > 0, 'actual CPU/RAM identity unavailable')
    return dict(os=platform.system(), release=platform.release(), version=platform.version(),
                machine=platform.machine(), node=platform.node(), cpu_count=cpu, ram_bytes=ram)


def environment_digest():
    value = {k: v for k, v in os.environ.items() if not k.startswith('CHOPPER_NATIVE_')}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
