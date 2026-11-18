"""Only four native slots. Immutable proposals, approvals and no recovery/retry."""
import json
import os
from pathlib import Path
import time
from .verify import read_json, require, sha256
from .native_scale_identity import digest, path, LINEAGE_PATH, LINEAGE_SHA, PRODUCT

SLOTS = ('LinuxD', 'LinuxG', 'WindowsD', 'WindowsG')
GIB = 1024**3
LIMITS = dict(os_seconds=8*3600, generation_seconds=3600, run_seconds=7200,
              verify_seconds=3600, owned_bytes=160*GIB, start_free_bytes=200*GIB,
              stop_free_bytes=20*GIB, sample_seconds=45, stale_seconds=90,
              disk_observation_seconds=30,
              no_progress_seconds=600)


def native_recipe(shape):
    """Exact generation commitment; source digest is learned in the checkpoint."""
    from .recipe import job
    require(shape in ('D', 'G'), 'native D/G recipe required')
    width = 100 if shape == 'D' else 1000
    return dict(generator='release-acceptance-v1', shape=shape, runtime='native',
                width=width, rows=10_000_000_000//width-1, bytes=10_000_000_000,
                tiny=False, job=job(shape, 'native', '@input', '@output', '@temp'))


def create(file, value):
    """Exclusive durable one-shot record; partial crash records also deny reuse."""
    file = Path(file)
    with file.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != 'nt':
        fd = os.open(file.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def validate(plan):
    require(plan['actions_enabled'] is True and plan['parent_scheduled'] is True, 'actions disabled/unapproved')
    require(plan['os'] == 'Linux' or 'qualification' in plan or 'windows_lineage' in plan,
            'Windows admission deferred: fresh OS-local proof and current Linux seal/parity required')
    validate_preparation(plan)
    if plan['os'] == 'Windows' and 'qualification' not in plan:
        from .hosted_qualification import batch_admission
        require(plan.get('execution_kind') == 'batch', 'Windows scale requires its matching qualified frozen batch')
        batch_admission(plan,'native')


def validate_preparation(plan):
    """Read-only plan checks; passing these grants no session or slot authority."""
    require(plan['schema'] == 'native-scale-v1' and plan['limits'] == LIMITS, 'fixed native limits required')
    require(plan['features'] == [] and set(plan['fixtures']) == {'D', 'G'}, 'only selected default D/G recipes required')
    require(plan['selected639_lineage'] == dict(path=LINEAGE_PATH, sha256=LINEAGE_SHA), 'fixed selected639 lineage required')
    require(plan['os'] in ('Linux', 'Windows') and plan['host']['os'] == plan['os'], 'native platform labels')
    for key in ('campaign', 'owned_root'):
        path(plan[key])
    reservation = plan['source_reservation']
    require(reservation['id'] and reservation['owner'] and type(reservation['bytes']) is int
            and reservation['bytes'] > 0 and reservation['roots'], 'separate source/cache/artifact capacity reservation required')
    require(plan['reservation']['id'] and plan['reservation']['owner'] and
            plan['reservation']['os'] == plan['os'], 'named reservation/owner required')
    path(plan['reservation']['lock_path'])
    require(plan['volumes'] and plan['owned_roots'], 'all involved volumes and histories required')
    roots = [path(x) for x in plan['owned_roots']]
    require(path(plan['owned_root']) in roots, 'current root must count toward shared storage')
    require(any(path(plan['campaign']).is_relative_to(r) for r in roots), 'campaign metadata must count toward storage')
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(roots) for b in roots[i+1:]), 'overlapping owned histories')
    source_roots = [path(p) for p in reservation['roots']]
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(source_roots) for b in source_roots[i+1:]), 'overlapping source reservations')
    require(all(a != b and a not in b.parents and b not in a.parents for a in roots for b in source_roots),
            'native data/source reservations must be separate')
    require(all(any(path(plan[role]['root']).is_relative_to(r) for r in source_roots)
                for role in ('product', 'harness')), 'source-role capacity reservation missing')
    require(all(any(path(plan[key]['path']).is_relative_to(r) for r in source_roots)
                for key in ('package', 'executable', 'package_receipt', 'build_proof')), 'artifact capacity reservation missing')
    tiny = 'qualification' in plan
    if tiny:
        from .native_tiny import validate as validate_tiny
        validate_tiny(plan)
    for shape in ('D', 'G'):
        fixture = plan['fixtures'][shape]
        if 'sha256' in fixture:
            digest(fixture['sha256'])
        recipe = {k: v for k, v in fixture.items() if k != 'sha256'}
        require(tiny or json.dumps(recipe, sort_keys=True) == json.dumps(native_recipe(shape), sort_keys=True),
                'exact native 10GB recipe/Job commitment required')
    if plan['os'] == 'Windows' and not tiny:
        if 'windows_lineage' in plan:
            digest(plan['windows_lineage']['sha256']);path(plan['windows_lineage']['path'])
            execution = plan['windows_execution']
            require(set(execution) == {'namespace','original_lock_stat','launch_cutoff_unix','stop_unix'} and
                    path(plan['owned_root']).parent == path(plan['campaign']).parent == path(execution['namespace']) and
                    execution['launch_cutoff_unix'] < execution['stop_unix'], 'exact bounded Windows scale execution required')
        require(set(plan['peers']) == {'D', 'G'}, 'Linux same-size peers mandatory on Windows')
        for shape, peer in plan['peers'].items():
            digest(peer['sha256'])
            digest(peer['plan_sha256'])
            digest(peer['source_sha256'])
            require(peer['slot'] == 'Linux'+shape and
                    ('sha256' not in plan['fixtures'][shape] or
                     peer['source_sha256'] == plan['fixtures'][shape]['sha256']),
                    'exact Linux peer fixture/shape binding')
    else:
        require(plan['peers'] == {}, 'Linux is the first peer')


class Campaign:
    def __init__(self, root, os_name, plan_sha, now=time.time, clock=time.monotonic, lineage=None, cancelled=None, stop_unix=None):
        self.root, self.os, self.sha, self.now = Path(root), os_name, plan_sha, now
        self.root.mkdir(parents=True, exist_ok=True)
        self.started = now()
        self.clock, self.monotonic_started = clock, clock()
        self.lineage = lineage
        self.cancelled, self.stop_unix = cancelled, stop_unix
        self.debit = lineage.value['prior_generation_ms']/1000 if lineage else 0
        self.retained_d = getattr(lineage,'retained_d',None)
        self.original_os_stop = (self.retained_d['started']['started']+LIMITS['os_seconds']-
            self.retained_d['started']['prior_generation_ms']/1000 if self.retained_d else None)
        # The single OS owner remains alive through D/G and parent review. Never resume.
        create(self.root / (os_name+'-started.json'), dict(started=self.started, plan_sha256=plan_sha,
               prior_generation_ms=int(self.debit*1000), monotonic_started=self.monotonic_started))

    def check(self):
        require(self.stop_unix is None or self.now() < self.stop_unix, 'original Windows scale absolute stop expired')
        require(self.original_os_stop is None or self.now() < self.original_os_stop, 'original retained Windows OS deadline')
        require(self.cancelled is None or not self.cancelled(), 'native session cancelled by SIGINT')
        require(0 <= self.now()-self.started < LIMITS['os_seconds']-self.debit, 'fixed OS clock expired/reversed')
        require(0 <= self.clock()-self.monotonic_started < LIMITS['os_seconds']-self.debit, 'fixed monotonic OS clock expired')

    def predecessor(self, slot):
        if self.os == 'Windows' and self.lineage:
            self.lineage.check()
            require(slot in ('WindowsD','WindowsG'), 'selected Windows slot required')
            require(not (self.root/(slot+'-consumed.json')).exists() and not self.lineage.claim_path(slot).exists(),
                    'permanently consumed Windows slot')
            if self.retained_d is not None:
                require(slot == 'WindowsG', 'retained WindowsD cannot be executed again')
            if slot == 'WindowsG' and self.retained_d is None:
                previous = read_json(self.root/'WindowsD-verified.json')
                consumed = read_json(self.root/'WindowsD-consumed.json')
                require(previous['passed'] is True and previous['plan_sha256'] == self.sha and
                        consumed['claim_sha256'] == sha256(self.lineage.claim_path('WindowsD')),
                        'verified claimed WindowsD required before G')
            return
        if self.lineage:
            self.lineage.check()
        index = SLOTS.index(slot)
        require(slot.startswith(self.os), 'slot OS mismatch')
        if index:
            previous = self.root / (SLOTS[index-1]+'-verified.json')
            value = read_json(previous)
            require(value['slot'] == SLOTS[index-1] and value['passed'] is True, 'previous slot not verified')
            consumed = read_json(self.root/(SLOTS[index-1]+'-consumed.json'))
            require(consumed['slot'] == SLOTS[index-1] and consumed['plan_sha256'] == value['plan_sha256'],
                    'previous consumed slot binding mismatch')
        if slot == 'WindowsD':
            completed = read_json(self.root/'Linux-completed.json')
            require(completed['passed'] is True and completed['plan_sha256'] == value['plan_sha256'],
                    'Linux OS session not completed/matched')
        require(not (self.root / (slot+'-consumed.json')).exists(), 'permanently consumed slot')
        if self.lineage:
            ledger = path(self.lineage.value['current']['canonical_slot_ledger'])
            require(not os.path.lexists(ledger/(slot+'-consumed.json')), 'canonical permanently consumed slot')
            if index:
                canonical = read_json(ledger/(SLOTS[index-1]+'-consumed.json'))
                require(consumed['claim_sha256'] == sha256(ledger/(SLOTS[index-1]+'-consumed.json')) and
                        canonical['proposal_sha256'] == consumed['proposal_sha256'] and
                        canonical['plan_sha256'] == consumed['plan_sha256'], 'canonical predecessor mismatch')

    def consume(self, slot, proposal, claim=None):
        self.check()
        if self.lineage:
            self.lineage.check()
            require(claim == self.lineage.claim_path(slot),
                    'canonical claim path required')
            value = read_json(claim)
            require(value['slot'] == slot and value['plan_sha256'] == self.sha and
                    value['proposal_sha256'] == sha256(proposal) and value['lineage_sha256'] == LINEAGE_SHA and
                    value['campaign'] == str(self.root) and value['product'] == PRODUCT and
                    value['owned_root'] == self.lineage.value['current']['windows_os_root' if self.os == 'Windows' else 'linux_os_root'] and
                    value['session_start_sha256'] == sha256(self.root/(self.os+'-started.json')) and
                    value['session_authority_sha256'] == sha256(path(value['owned_root'])/'reservation.json'),
                    'canonical receipt binding mismatch')
        else:
            self.predecessor(slot)
        create(self.root / (slot+'-consumed.json'), dict(slot=slot, proposal_sha256=sha256(proposal),
               consumed=self.now(), plan_sha256=self.sha, **(dict(claim_sha256=sha256(claim)) if claim else {})))


class TinyCampaign(Campaign):
    """Same fixed session clock/debit, separate terminal records and no slots."""
    def __init__(self, plan, plan_sha, lineage, cancelled=None):
        self.plan = plan
        super().__init__(plan['campaign'], plan['os'], plan_sha, lineage=lineage, cancelled=cancelled)

    def check(self):
        from .native_tiny import check_clock
        super().check()
        check_clock(self.plan)

    def predecessor(self, slot):
        raise ValueError('tiny qualification has no scale slots')

    def consume(self, slot, proposal, claim=None):
        raise ValueError('tiny qualification cannot consume a scale slot')


def canonical_claim(lineage, slot, value, recheck):
    """Separate family metadata lock; never reacquire the waiting session's host lock."""
    import fcntl
    ledger = path(lineage.value['current']['canonical_slot_ledger'])
    ledger.mkdir(exist_ok=True)
    parent_fd = os.open(ledger.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    lock = path(str(ledger/'writer.lock'))
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(os.path.samestat(os.fstat(fd), lock.stat()), 'family lock replaced')
        lineage.check()
        recheck()
        target = ledger/(slot+'-consumed.json')
        require(not os.path.lexists(target), 'canonical permanently consumed slot')
        require(all(not os.path.lexists(ledger/(later+'-consumed.json')) for later in SLOTS[SLOTS.index(slot)+1:]),
                'canonical slots out of order')
        create(target, value)
        return target
    finally:
        os.close(fd)


def proposal(file, stage, plan_sha, payload):
    create(file, dict(schema='native-scale-proposal-v1', stage=stage,
                     plan_sha256=plan_sha, payload=payload))
    return sha256(file)


def approve(proposal_path, approval_path, exact_sha):
    require(sha256(proposal_path) == digest(exact_sha), 'exact proposal SHA approval required')
    value = read_json(proposal_path, 64*1024**2)
    require(value['stage'] in ('generation', 'checkpoint-adoption', 'Run', 'failure'), 'unsupported approval stage')
    create(approval_path, dict(stage=value['stage'], proposal_sha256=exact_sha,
                               plan_sha256=value['plan_sha256']))


def approved(proposal_path, approval_path):
    if not Path(approval_path).exists():
        return False
    a, p = read_json(approval_path), read_json(proposal_path, 64*1024**2)
    require(a == dict(stage=p['stage'], proposal_sha256=sha256(proposal_path),
                      plan_sha256=p['plan_sha256']), 'approval stage/plan/proposal mismatch')
    return True
