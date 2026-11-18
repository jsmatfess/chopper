"""Explicit native acceptance stages. No default actions, retries or resume.

See scale_acceptance/NATIVE.md before preparing a parent-reviewed plan.
"""
import sys
_WINDOWS_STARTUP = (sys.platform == 'win32' and __name__ == '__main__'
                    and sys.argv[1:2] in (['qualify'], ['session'], ['_lifecycle']))
_PREPARATION_UNTIL = None
if _WINDOWS_STARTUP:
    sys.stderr.write('CHOPPER_NATIVE_PYTHON_ENTRY\n')
    sys.stderr.flush()
    import os
    _startup_token = os.environ.pop('CHOPPER_NATIVE_STARTUP_TOKEN', '')
    _preparation_until = os.environ.pop('CHOPPER_NATIVE_PREPARATION_UNTIL', '')
    if len(_startup_token) != 64 or set(_startup_token) - set('0123456789abcdef'):
        raise OSError('Windows session/qualify requires supervised startup')
    sys.stderr.write('CHOPPER_NATIVE_STARTUP_ENTRY '+_startup_token+'\n')
    sys.stderr.flush()
import argparse
import json
import os
import re
from pathlib import Path
import time
sys.dont_write_bytecode = True
from scale_acceptance.native_scale_control import (
    Campaign, TinyCampaign, LIMITS, approve, approved, canonical_claim, create as durable_create, proposal, validate)
from scale_acceptance.native_scale_identity import Identity, Lineage, LINEAGE_PATH, LINEAGE_SHA, PRODUCT, digest, path, stamp
from scale_acceptance.native_scale_host import HostLock, Caretaker, bounded, caretaker, module, windows_lock_owner, publish, pending_calls
from scale_acceptance.native_scale_monitor import Monitor
from scale_acceptance.native_scale_fixture import checkpoint, checkpoint_record, validate_metadata
from scale_acceptance.guard import load_runner
from scale_acceptance.verify import require, read_json, sha256, verify
from scale_acceptance import native_tiny as tiny

if _WINDOWS_STARTUP:
    sys.stderr.write('CHOPPER_NATIVE_STARTUP_IMPORTS_COMPLETE '+_startup_token+'\n')
    sys.stderr.flush()


def preparation_call(phase, call):
    """One Windows setup deadline; Linux keeps its direct existing path."""
    if _PREPARATION_UNTIL is None:
        return call()
    print(json.dumps(dict(native_preparation_phase=phase)), file=sys.stderr, flush=True)
    try:
        remaining = _PREPARATION_UNTIL-time.monotonic()
        require(remaining > 0, 'Windows preparation deadline expired')
        return bounded(call, seconds=remaining)
    except BaseException as error:
        try:
            print(json.dumps(dict(native_preparation_failed=phase, error=repr(error),
                pending_calls=bool(pending_calls()))), file=sys.stderr, flush=True)
        except BaseException:
            pass
        # Before HostLock, keep the process while a tracked query is unfinished.
        while pending_calls():
            time.sleep(.05)
        raise


def create(file, value):
    return bounded(lambda: durable_create(file, value))


def operation_plan_binding(plan_path, operation):
    require(operation['plan_sha256'] == sha256(plan_path),
            'operation does not match actual plan')


def report_progress(phase, rows):
    print(json.dumps(dict(phase=phase, rows=rows)), flush=True)


def peer_report(plan, shape, actual_sha=None):
    if tiny.enabled(plan):
        return tiny.peer_report(plan, shape, actual_sha)
    if plan['os'] != 'Windows':
        return None
    item = plan['peers'][shape]
    require(sha256(item['path']) == item['sha256'], 'Linux peer report hash mismatch')
    envelope = read_json(item['path'], 8*1024**2)
    require(envelope['os'] == 'Linux' and envelope['slot'] == 'Linux'+shape
            and envelope['product'] == plan['product']['commit'] and envelope['passed'] is True
            and envelope['host']['os'] == 'Linux' and envelope['plan_sha256'] == item['plan_sha256'],
            'actual native Linux peer labels required')
    if 'windows_lineage' in plan:
        descriptor,_=tiny.pinned_json(plan['windows_lineage'],64*1024**2)
        committed,_=tiny.pinned_json(descriptor['linux']['records'][shape],65536)
    else:
        committed = read_json(Path(plan['campaign'])/('Linux'+shape+'-verified.json'))
    require(committed['sha256'] == item['sha256'] and committed['plan_sha256'] == item['plan_sha256'],
            'peer must be the consumed campaign Linux slot')
    report = envelope['report']
    require(report['shape'] == shape and report['source_sha256'] == item['source_sha256']
            and report['rows'] == (99_999_999 if shape == 'D' else 9_999_999), 'peer same-size/input required')
    require(actual_sha is None or report['source_sha256'] == actual_sha, 'peer actual checkpoint SHA mismatch')
    return report


def actual_checkpoint(plan, shape, data):
    data = Path(data)
    source = source_path(plan, shape, data)
    _, meta = validate_metadata(data/'job.json', data/'fixture.json', plan['fixtures'][shape], source=source)
    digest(meta['sha256'])
    recipe = plan['fixtures'][shape]
    require('sha256' not in recipe or recipe['sha256'] == meta['sha256'], 'optional expected SHA mismatch')
    value = read_json(data/'checkpoint.json')
    require(json.dumps(value, sort_keys=True) == json.dumps(checkpoint_record(meta), sort_keys=True),
            'actual checkpoint/fixture binding mismatch')
    peer_report(plan, shape, value['sha256'])
    return value


def source_path(plan, shape, data):
    if not tiny.enabled(plan) and 'selected639_lineage' in plan and plan['os'] == 'Linux' and shape == 'D':
        lineage = Lineage(plan)
        require(path(str(data)) == path(plan['owned_root'])/'D-data', 'fixed adopted data root required')
        return lineage.source
    return Path(data)/'input.csv'


def adoption_payload(plan, data):
    lineage = Lineage(plan)
    require(path(str(data)) == path(plan['owned_root'])/'D-data', 'fixed adoption destination required')
    return dict(slot='LinuxD', lineage_sha256=LINEAGE_SHA, source=lineage.adopt,
                recipe=plan['fixtures']['D'], data=str(data), output=str(Path(data)/'output'),
                temp=str(Path(data)/'temp'), limits=LIMITS,
                prior_generation_ms=lineage.value['prior_generation_ms'])


def adoption_binding(plan, operation):
    require(plan['os'] == 'Linux' and operation['shape'] == 'D' and
            operation['stage'] == 'checkpoint-adoption', 'only LinuxD checkpoint adoption allowed')
    require(sha256(operation['proposal']) == operation['proposal_sha256'] and
            approved(operation['proposal'], operation['approval']), 'NEW checkpoint-adoption approval required')
    value = read_json(operation['proposal'], 64*1024**2)
    require(value == dict(schema='native-scale-proposal-v1', stage='checkpoint-adoption',
            plan_sha256=operation['plan_sha256'], payload=adoption_payload(plan, operation['data'])),
            'checkpoint-adoption stage/plan/payload mismatch')


def generation_binding(plan, operation):
    if tiny.enabled(plan):
        root = path(plan['owned_root'])
        require(operation['shape'] in ('D', 'G') and operation['stage'] == 'generation' and
                operation['data'] == str(root/(operation['shape']+'-data')), 'fixed tiny generation required')
        require(sha256(operation['proposal']) == operation['proposal_sha256'] and
                approved(operation['proposal'], operation['approval']), 'exact tiny generation approval required')
        value = read_json(operation['proposal'], 64*1024**2)
        require(value == dict(schema='native-scale-proposal-v1', stage='generation',
            plan_sha256=operation['plan_sha256'], payload=dict(slot=plan['os']+operation['shape'],
            recipe=plan['fixtures'][operation['shape']], data=operation['data'],
            reservation=read_json(root/'reservation.json')['actual_lock'], limits=LIMITS)),
            'tiny generation payload mismatch')
        return
    require(operation['shape'] in ('D','G') and operation['stage'] == 'generation' and
            (plan['os'] == 'Windows' or operation['shape'] == 'G'), 'LinuxD cannot generate')
    root = path(plan['owned_root'])
    require(operation['data'] == str(root/(operation['shape']+'-data')) and
            sha256(operation['proposal']) == operation['proposal_sha256'] and
            approved(operation['proposal'], operation['approval']), 'NEW generation approval required')
    value = read_json(operation['proposal'], 64*1024**2)
    require(value == dict(schema='native-scale-proposal-v1', stage='generation', plan_sha256=operation['plan_sha256'],
            payload=dict(slot=plan['os']+operation['shape'], recipe=plan['fixtures'][operation['shape']], data=operation['data'],
                         reservation=read_json(root/'reservation.json')['actual_lock'], limits=LIMITS)),
            'generation stage/plan/payload mismatch')


def run_proposal_binding(plan, operation):
    """Load only the exact separately approved Run, also during verification."""
    require(sha256(operation['proposal']) == operation['proposal_sha256'] and
            approved(operation['proposal'], operation['approval']), 'exact Run approval lost before admission')
    value = read_json(operation['proposal'], 64*1024**2)
    payload = value['payload']
    require(value['stage'] == 'Run' and value['plan_sha256'] == operation['plan_sha256']
            and payload['slot'] == plan['os']+operation['shape'], 'Run stage/plan/slot mismatch')
    actual = actual_checkpoint(plan, operation['shape'], operation['data'])
    require(payload['checkpoint'] == actual and payload['input_sha256'] == actual['sha256'],
            'approved actual input/checkpoint SHA mismatch')
    expected_paths = {str(Path(operation['data'], n)) for n in ('job.json', 'fixture.json', 'checkpoint.json')}
    require(set(payload['actual']) == expected_paths, 'complete approved actual Job/fixture/checkpoint map required')
    for name, expected in payload['actual'].items():
        require(sha256(name) == expected['sha256'] and stamp(Path(name)) == expected['stat'],
                'approved actual metadata changed')
    if 'selected639_lineage' in plan or 'windows_lineage' in plan:
        source = source_path(plan, operation['shape'], operation['data'])
        require(payload['source'] == dict(path=str(source), stat=stamp(source)) and
                payload['lineage_sha256'] == LINEAGE_SHA, 'approved source/lineage drift')
        require(payload['executable'] == plan['executable'] and payload['python'] == plan['python'] and
                payload['tools'] == plan['tools'] and payload['source_roles'] == dict(product=plan['product'], harness=plan['harness'])
                and payload['limits'] == LIMITS and payload['peer'] == plan['peers'].get(operation['shape'], {}),
                'Run proposal plan identity mismatch')
    return payload


def run_binding(plan, operation):
    payload = run_proposal_binding(plan, operation)
    if ('selected639_lineage' in plan or 'windows_lineage' in plan) and not tiny.enabled(plan):
        lineage = Lineage(plan)
        slot = plan['os']+operation['shape']
        claim = lineage.claim_path(slot)
        require(sha256(claim) == operation['claim_sha256'], 'canonical Run claim drift')
        receipt = read_json(claim)
        local = read_json(path(plan['campaign'])/(slot+'-consumed.json'))
        require(receipt['proposal_sha256'] == operation['proposal_sha256'] and
                receipt['plan_sha256'] == operation['plan_sha256'] and receipt['lineage_sha256'] == LINEAGE_SHA and
                local['claim_sha256'] == operation['claim_sha256'] and local['slot'] == slot and
                local['plan_sha256'] == operation['plan_sha256'], 'local/canonical Run binding mismatch')
    return payload



def tiny_proposal_binding(plan, plan_path, name, exact_sha):
    """Validate an entire Tiny proposal before any parent approval is created."""
    from scale_acceptance.native_scale_identity import execution_shapes
    require((tiny.enabled(plan) or (plan['os'] == 'Windows' and 'windows_lineage' in plan)) and name in
            (('D-generation','D-Run','G-generation','G-Run','failure') if tiny.enabled(plan) else
             tuple(shape+'-'+stage for shape in execution_shapes(plan) for stage in ('generation','Run'))),
            'only selected complete Tiny or Windows Large approvals')
    root = path(plan['owned_root'])
    proposal_path = root/(name+'-proposal.json')
    require(sha256(proposal_path) == exact_sha, 'exact complete Tiny proposal digest')
    value = read_json(proposal_path,64*1024**2)
    stage = 'generation' if name.endswith('-generation') else ('Run' if name.endswith('-Run') else 'failure')
    shape = name[0] if name != 'failure' else 'D'
    data = root/(shape+'-data')
    if stage == 'generation':
        initialized = read_json(root/'guard-initialization.json')
        cold_seconds = tiny.cold_admission_seconds(plan)
        require(initialized['completed'] is True and initialized['kind'] == 'cold-full-constructor' and
                initialized['bound_seconds'] == cold_seconds and 0 <= initialized['seconds'] < cold_seconds,
                'actual selected native cold admission receipt required')
        with (root/'guard-operations.jsonl').open('rb') as stream:
            raw = stream.readline(65537)
        require(len(raw)<=65536,'bounded initial full-guard receipt')
        initial = json.loads(raw)
        require(initial['kind'] == 'initial-full-sample' and initial['completed'] is True and
                initial['error'] is None and initial['bound_seconds'] == LIMITS['disk_observation_seconds'] and
                0 <= initial['seconds'] < LIMITS['disk_observation_seconds'], 'actual initial complete live guard required')
        payload = dict(slot=plan['os']+shape,recipe=plan['fixtures'][shape],data=str(data),
            reservation=read_json(root/'reservation.json')['actual_lock'],limits=LIMITS)
    elif stage == 'failure':
        payload = tiny.failure_payload(plan,root/'failure-data')
    else:
        checked = actual_checkpoint(plan,shape,data)
        source = source_path(plan,shape,data)
        actual = {str(p):dict(stat=stamp(p),sha256=sha256(p)) for p in
                  (data/'job.json',data/'fixture.json',data/'checkpoint.json')}
        payload = dict(slot=plan['os']+shape,checkpoint=checked,actual=actual,input_sha256=checked['sha256'],
            executable=plan['executable'],source=dict(path=str(source),stat=stamp(source)),lineage_sha256=LINEAGE_SHA,
            session_authority=dict(start_sha256=sha256(Path(plan['campaign'])/(plan['os']+'-started.json')),
                reservation_sha256=sha256(root/'reservation.json')),
            python=plan['python'],tools=plan['tools'],source_roles=dict(product=plan['product'],harness=plan['harness']),
            peer=plan['peers'].get(shape,{}),reservation=read_json(root/'reservation.json')['actual_lock'],limits=LIMITS)
    require(value == dict(schema='native-scale-proposal-v1',stage=stage,plan_sha256=sha256(plan_path),payload=payload),
            'complete Tiny stage/shape/recipe/checkpoint/job/policy proposal mismatch')

def claim_run(plan_path, exact_sha, proposal_path):
    """Parent's sole writer. Requires an actual approved Run and a live session."""
    require(os.name != 'nt' and sha256(plan_path) == digest(exact_sha), 'Linux parent exact plan authority required')
    plan = read_json(plan_path, 64*1024**2)
    require(not tiny.enabled(plan), 'tiny qualification cannot claim a scale slot')
    validate(plan)
    lineage = Lineage(plan)
    root, campaign = path(plan['owned_root']), path(plan['campaign'])
    p = read_json(proposal_path, 64*1024**2)
    slot = p['payload']['slot']
    require(slot in ('LinuxD', 'LinuxG') and proposal_path == root/(slot[-1]+'-Run-proposal.json'),
            'fixed actual Run proposal required; Windows admission deferred')
    operation = dict(stage='Run', shape=slot[-1], data=str(root/(slot[-1]+'-data')),
                     proposal=str(proposal_path), approval=str(root/(slot[-1]+'-Run-approved.json')),
                     proposal_sha256=sha256(proposal_path), plan_sha256=exact_sha)
    start_path, authority_path = campaign/'Linux-started.json', root/'reservation.json'
    start_sha, authority_sha = sha256(start_path), sha256(authority_path)
    def recheck():
        require(sha256(plan_path) == exact_sha and sha256(start_path) == start_sha and
                sha256(authority_path) == authority_sha and not os.path.lexists(root/'session-result.json'),
                'current session authority drift/terminal')
        start, authority = read_json(start_path), read_json(authority_path)
        require(start['plan_sha256'] == exact_sha and start['prior_generation_ms'] == 324064 and
                0 <= time.time()-start['started'] < LIMITS['os_seconds']-324.064 and
                0 <= time.monotonic()-start['monotonic_started'] < LIMITS['os_seconds']-324.064,
                'current session clock/debit mismatch')
        held = authority['actual_lock']
        lock = path(held['path'])
        require(held['path'] == plan['reservation']['lock_path'] and stamp(lock) == held['stat'] and
                held['mechanism'] == 'flock-exclusive' and authority['plan'] == plan['reservation'],
                'current reservation mismatch')
        # Read-only kernel proof; acquiring this lock would deadlock the session.
        s = lock.stat()
        expected = f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}'
        require(any(parts[1:5] == ['FLOCK', 'ADVISORY', 'WRITE', str(held['owner_pid'])] and parts[5] == expected
                    for parts in (line.split() for line in Path('/proc/locks').read_text().splitlines())),
                'current session does not hold original flock')
        ticks = Path('/proc', str(held['owner_pid']), 'stat').read_text().rsplit(')', 1)[1].split()[19]
        require(ticks == authority['owner_start_ticks'], 'current session owner identity drift')
        with (root/'capacity.jsonl').open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-16384))
            sample = json.loads(stream.read().splitlines()[-1])
        require(0 <= time.time()-sample['sample_started_unix'] < LIMITS['stale_seconds'] and
                sample['reservation'] == held and sample['owned_sampled_highwater'] < LIMITS['owned_bytes'] and
                sample['source_sampled_highwater'] <= plan['source_reservation']['bytes'],
                'current session capacity sample stale/mismatched')
        binding = run_proposal_binding(plan, operation)
        require(binding['session_authority'] == dict(start_sha256=start_sha, reservation_sha256=authority_sha),
                'Run session authority mismatch')
        require(binding['reservation'] == held, 'Run held reservation mismatch')
        require(not os.path.lexists(campaign/(slot+'-consumed.json')), 'local permanently consumed slot')
        if slot == 'LinuxG':
            previous = read_json(campaign/'LinuxD-verified.json')
            consumed = read_json(campaign/'LinuxD-consumed.json')
            claim = path(lineage.value['current']['canonical_slot_ledger'])/'LinuxD-consumed.json'
            canonical, report = read_json(claim), read_json(root/'D-verified.json', 8*1024**2)
            require(previous['passed'] is True and previous['plan_sha256'] == exact_sha and
                    previous['sha256'] == sha256(root/'D-verified.json') and
                    consumed['claim_sha256'] == sha256(claim) and
                    canonical['proposal_sha256'] == consumed['proposal_sha256'] and
                    canonical['plan_sha256'] == consumed['plan_sha256'] == exact_sha and
                    canonical['slot'] == consumed['slot'] == previous['slot'] == report['slot'] == 'LinuxD' and
                    canonical['lineage_sha256'] == LINEAGE_SHA and canonical['product'] == report['product'] == PRODUCT and
                    canonical['campaign'] == str(campaign) and canonical['owned_root'] == str(root) and
                    report['passed'] is True and report['plan_sha256'] == exact_sha and
                    report['report']['source_sha256'] == lineage.adopt['input']['expected_sha256'],
                    'canonical ordered predecessor required')
        lineage.check()
    recheck()  # invalid authority must not even create a ledger/lock
    return canonical_claim(lineage, slot, dict(schema='selected639-canonical-claim-v1', slot=slot,
           product=PRODUCT, lineage_sha256=LINEAGE_SHA, plan_sha256=exact_sha,
           proposal_sha256=operation['proposal_sha256'], campaign=str(campaign), owned_root=str(root),
           session_start_sha256=start_sha, session_authority_sha256=authority_sha), recheck)


def windows_claim_observation(plan, plan_path, operation, monitor):
    """Answer one parent nonce through the actual idle Original owner's RPC."""
    root = path(plan['owned_root'])
    shape = operation['shape']
    challenge_path = root/(shape+'-claim-challenge.json')
    proof_path = root/(shape+'-claim-proof.json')
    if not challenge_path.exists() or proof_path.exists():
        return
    with challenge_path.open('rb') as stream:raw=stream.read(65537)
    require(len(raw)<=65536,'bounded Windows claim challenge')
    if not raw.endswith(b'\n'):return
    challenge = json.loads(raw)
    require(set(challenge) == {'nonce','plan_sha256','proposal_sha256','slot','created_unix'} and
            challenge['plan_sha256'] == sha256(plan_path) and
            challenge['proposal_sha256'] == operation['proposal_sha256'] and
            challenge['slot'] == 'Windows'+shape and 0 <= time.time()-challenge['created_unix'] < 30,
            'current exact Windows claim challenge required')
    digest(challenge['nonce'])
    binding = run_proposal_binding(plan,operation)
    sample = monitor.last_capacity
    require(0 <= time.time()-sample['sample_started_unix'] < LIMITS['stale_seconds'], 'fresh claim capacity required')
    lock = monitor.lock
    result = bounded(lambda:lock.owner.request(dict(command='observe')),seconds=4)
    require(result == dict(ok=True,idle=True), 'idle Original owner acknowledgement required')
    held = lock.proof()
    windows = module('browser-small-windows')
    require(windows.process_identity(held['owner_pid']) == held['owner_identity'] and
            held['mechanism'] == 'msvcrt-byte-0' and binding['reservation'] == held,
            'actual held Windows owner identity mismatch')
    create(proof_path,dict(schema='selected639-windows-claim-proof-v1',challenge=challenge,
        controller=windows.process_identity(os.getpid()),owner=held,host=plan['host'],
        session_start_sha256=sha256(path(plan['campaign'])/'Windows-started.json'),
        session_authority_sha256=sha256(root/'reservation.json'),capacity=sample,
        observed_unix=time.time(),proposal_validated=True,idle_owner_acknowledged=True))
    monitor.externals.update({p:stamp(p) for p in (challenge_path,proof_path)})


def wait_windows_claim(plan, plan_path, operation, monitor, lineage):
    slot = 'Windows'+operation['shape']
    claim = lineage.claim_path(slot)
    while True:
        monitor.campaign.check()  # Same absolute planstop/8h endpoint; never renew it for partial publication.
        disk_sample(monitor,reviewing=True)
        windows_claim_observation(plan,plan_path,operation,monitor)
        if claim.exists():
            with claim.open('rb') as stream:raw=stream.read(65537)
            require(len(raw)<=65536,'bounded canonical Windows receipt')
            if raw.endswith(b'\n'):
                receipt=json.loads(raw)  # Complete malformed records fail, never retry them.
                require(receipt['slot']==slot and receipt['plan_sha256']==operation['plan_sha256'] and
                    receipt['proposal_sha256']==operation['proposal_sha256'] and
                    receipt['lineage_sha256']==LINEAGE_SHA,'canonical Windows receipt identity mismatch')
                return claim  # Existing bounded Campaign.consume validates remaining ownership/session fields before local consumption.
        time.sleep(.1)


def claim_windows_run(plan_path, exact_sha, proposal_path):
    """Linux parent only: observe the native owner, then write the existing family."""
    import secrets
    from pathlib import PureWindowsPath
    from types import SimpleNamespace
    require(os.name != 'nt' and sha256(plan_path) == digest(exact_sha), 'Linux parent exact Windows plan authority required')
    plan = read_json(plan_path,4*1024**2)
    require(plan['os'] == 'Windows' and not tiny.enabled(plan), 'Windows Large claim only')
    def mapped(name):
        value = PureWindowsPath(name)
        require(value.drive.upper() == 'C:' and value.is_absolute() and '..' not in value.parts,
                'selected local Windows C path required')
        return path(str(Path('/mnt/c',*value.parts[1:])))
    require(plan_path == mapped(str(PureWindowsPath(plan['owned_root']).parent/'scale-plan.json')),
            'exact mapped selected Windows plan required')
    require(sha256(__file__) == plan['harness']['sha256']['scripts/native-scale-runner.py'] and
            sha256(mapped(str(PureWindowsPath(plan['harness']['root'])/'scripts/native-scale-runner.py'))) == sha256(__file__),
            'exact reviewed native/parent claim implementation required')
    root, campaign = mapped(plan['owned_root']),mapped(plan['campaign'])
    proposal = read_json(proposal_path,16*1024**2)
    slot = proposal['payload']['slot']
    require(slot in ('WindowsD','WindowsG') and proposal['schema'] == 'native-scale-proposal-v1' and proposal['stage'] == 'Run' and
            proposal['plan_sha256'] == exact_sha and proposal_path == root/(slot[-1]+'-Run-proposal.json'),
            'exact current Windows Run proposal required')
    proposal_sha = sha256(proposal_path)
    require(approved(proposal_path,root/(slot[-1]+'-Run-approved.json')), 'native Run approval required')
    lineage_record = path(LINEAGE_PATH)
    require(sha256(lineage_record) == LINEAGE_SHA, 'fixed original family lineage required')
    family = read_json(lineage_record,8*1024**2)
    descriptor = read_json(mapped(plan['windows_lineage']['path']),64*1024**2)
    require(sha256(mapped(plan['windows_lineage']['path'])) == plan['windows_lineage']['sha256'] and
            descriptor['linux']['canonical_slot_ledger'] == family['current']['canonical_slot_ledger'],
            'unchanged canonical family required')
    require('retained_windows_d' not in descriptor or slot=='WindowsG', 'retained WindowsD cannot be claimed again')
    parent=descriptor['claim_parent']
    require(str(Path(sys.executable).resolve())==parent['python'] and sha256(sys.executable)==parent['python_sha256'] and
        str(Path(__file__).resolve())==parent['runner'], 'exact declared Linux parent runtime/source required')
    ledger = path(family['current']['canonical_slot_ledger'])
    for shape in ('D','G'):
        require(sha256(ledger/('Linux'+shape+'-consumed.json')) == descriptor['linux']['claims'][shape]['sha256'],
                'actual accepted Linux canonical predecessor required')
    controller_path = plan_path.parent/'controller-pid.json'
    created_path = plan_path.parent/'controller-startup-created.json'
    controller_sha,created_sha = sha256(controller_path),sha256(created_path)
    controller_record,created_record = read_json(controller_path,65536),read_json(created_path,65536)
    controller_identity = controller_record['identity']
    require(controller_record['pid'] == controller_identity['pid'] and
            created_record['identity'] == controller_identity and
            type(controller_identity['pid']) is int and controller_identity['pid'] > 0 and
            type(controller_identity['created']) is int and controller_identity['created'] > 0,
            'held controller startup identity required')
    challenge = dict(nonce=secrets.token_hex(32),plan_sha256=exact_sha,proposal_sha256=proposal_sha,
        slot=slot,created_unix=time.time())
    create(root/(slot[-1]+'-claim-challenge.json'),challenge)
    proof_path = root/(slot[-1]+'-claim-proof.json')
    until = time.monotonic()+30
    while True:
        require(time.monotonic() < until, 'Windows challenged claim observation deadline')
        if proof_path.exists():
            with proof_path.open('rb') as stream:raw=stream.read(65537)
            require(len(raw) <= 65536, 'bounded Windows claim proof')
            if raw.endswith(b'\n'):
                proof = json.loads(raw)
                break
        time.sleep(.05)
    proof_sha = sha256(proof_path)
    start_path,authority_path = campaign/'Windows-started.json',root/'reservation.json'
    start_sha,authority_sha = sha256(start_path),sha256(authority_path)
    def recheck():
        require(sha256(plan_path) == exact_sha and sha256(proposal_path) == proposal_sha and
                sha256(proof_path) == proof_sha and sha256(start_path) == start_sha and
                sha256(authority_path) == authority_sha and sha256(controller_path) == controller_sha and
                sha256(created_path) == created_sha and not (root/'session-result.json').exists(),
                'Windows claim authority drift/terminal')
        start,authority = read_json(start_path),read_json(authority_path)
        owner = authority['actual_lock'];sample = proof['capacity']
        debit = descriptor['storage']['prior_generation_ms']/1000
        require(time.time() < plan['windows_execution']['launch_cutoff_unix'] < plan['windows_execution']['stop_unix'] and
                proof['schema'] == 'selected639-windows-claim-proof-v1' and proof['challenge'] == challenge and
                proof['host'] == plan['host'] and proof['controller'] == controller_identity and proof['proposal_validated'] is True and
                proof['idle_owner_acknowledged'] is True and proof['owner'] == owner and
                owner['mechanism'] == 'msvcrt-byte-0' and owner['owner_identity']['pid'] == owner['owner_pid'] and
                proof['session_start_sha256'] == start_sha and proof['session_authority_sha256'] == authority_sha and
                0 <= time.time()-proof['observed_unix'] < 5 and
                start['plan_sha256'] == exact_sha and start['prior_generation_ms'] == descriptor['storage']['prior_generation_ms'] and
                0 <= time.time()-start['started'] < LIMITS['os_seconds']-debit and
                sample['reservation'] == owner and 0 <= time.time()-sample['sample_started_unix'] < LIMITS['stale_seconds'] and
                sample['owned_sampled_highwater'] < LIMITS['owned_bytes'] and
                sample['source_sampled_highwater'] <= plan['source_reservation']['bytes'],
                'fresh native owner/session/capacity proof required')
        if slot == 'WindowsG' and 'retained_windows_d' in descriptor:
            from scale_acceptance.native_scale_identity import retained_windows_d
            accepted = retained_windows_d(plan,descriptor['retained_windows_d'],resolve_path=mapped)
            require(sha256(ledger/'WindowsD-consumed.json') == accepted['descriptor']['canonical']['sha256'],
                    'actual retained canonical WindowsD drift')
            require(time.time() < accepted['started']['started']+LIMITS['os_seconds']-
                    accepted['started']['prior_generation_ms']/1000, 'original Windows OS deadline')
        elif slot == 'WindowsG':
            previous = read_json(campaign/'WindowsD-verified.json')
            require(previous['passed'] is True and previous['plan_sha256'] == exact_sha and
                    previous['sha256'] == sha256(root/'D-verified.json') and
                    sha256(ledger/'WindowsD-consumed.json') == sha256(campaign/'WindowsD-canonical.json'),
                    'verified canonical WindowsD required')
    recheck()
    local = campaign/(slot+'-canonical.json')
    require(not local.exists(), 'local canonical receipt already exists')
    proxy = SimpleNamespace(value=family,check=recheck)
    canonical = canonical_claim(proxy,slot,dict(schema='selected639-canonical-claim-v1',slot=slot,
        product=PRODUCT,lineage_sha256=LINEAGE_SHA,plan_sha256=exact_sha,proposal_sha256=proposal_sha,
        campaign=plan['campaign'],owned_root=plan['owned_root'],session_start_sha256=start_sha,
        session_authority_sha256=authority_sha,windows_claim_proof_sha256=proof_sha,
        controller_record_sha256=controller_sha,controller_startup_created_sha256=created_sha),recheck)
    # Byte-identical receipt transport, never a copy or reset of the family directory.
    create(local,read_json(canonical))
    require(sha256(local) == sha256(canonical), 'canonical transport bytes mismatch')
    return canonical


def phase(plan, operation):
    """Only known generation/checkpoint and independent verification commands."""
    shape, stage = operation['shape'], operation['stage']
    data = Path(operation['data'])
    if stage == 'generation':
        require(tiny.enabled(plan) or not ('selected639_lineage' in plan and plan['os'] == 'Linux' and shape == 'D'),
                'LinuxD must adopt; regeneration forbidden')
        if 'selected639_lineage' in plan or 'windows_lineage' in plan:
            generation_binding(plan, operation)
        from scale_acceptance.generate import prepare
        if tiny.enabled(plan):
            prepare(data, shape, 'native', plan['fixtures'][shape]['rows'])
        else:
            prepare(data, shape, 'native')
        result = checkpoint(data/'job.json', data/'fixture.json', plan['fixtures'][shape],
                            lambda rows: report_progress('checkpoint', rows))
        create(data/'checkpoint.json', result)
    elif stage == 'checkpoint-adoption':
        adoption_binding(plan, operation)  # before the first source open
        lineage = Lineage(plan)
        old = lineage.adopt
        result = checkpoint(old['job']['path'], old['fixture']['path'], plan['fixtures']['D'],
                            lambda rows: (lineage.check(), report_progress('checkpoint', rows)))
        require(result == read_json(old['checkpoint']['path']) and
                result['sha256'] == old['input']['expected_sha256'], 'adopted checkpoint mismatch')
        adoption_binding(plan, operation)
        config, meta = validate_metadata(old['job']['path'], old['fixture']['path'], plan['fixtures']['D'])
        data.mkdir()  # no retries after partial creation
        (data/'temp').mkdir()
        config['output'] = str(data/'output')
        config['resources']['temp_dir'] = str(data/'temp')
        create(data/'fixture.json', meta)
        create(data/'job.json', config)
        create(data/'checkpoint.json', result)
        actual_checkpoint(plan, shape, data)
        lineage.check()
    elif stage == 'verify':
        binding = run_binding(plan, operation)
        peer = peer_report(plan, shape, binding['input_sha256'])
        peer_path = None
        if peer is not None:
            peer_path = Path(operation['report']).with_name(shape+'-linux-peer-oracle.json')
            create(peer_path, peer)
        # Uses the maintained independent verifier's --peer implementation.
        report = verify(data/'job.json', data/'fixture.json', bitmap_dir=data/'temp', peer=peer_path)
        require(report['source_sha256'] == binding['input_sha256'], 'verified source differs from approved actual input')
        run_binding(plan, operation)
        require(peer is None or report == peer, 'peer changed during independent verification')
        analysis_path = Path(operation['run_stdout'])
        analysis = read_json(analysis_path, 8*1024**2)
        diagnostics = analysis.get('diagnostics') or {}
        require(isinstance(diagnostics, dict), 'invalid native diagnostic schema')
        facts = {k: diagnostics[k] for k in ('sort_runs', 'merge_operations', 'merge_inputs',
                 'resident_sorts', 'temporary_bytes_written', 'temporary_bytes_read', 'temporary_cleanup_failures')
                 if k in diagnostics}
        spill = all(type(facts.get(k)) is int and facts[k] > 0 for k in ('sort_runs', 'merge_operations'))
        require(diagnostics.get('temporary_cleanup_failures', 0) == 0, 'reported native cleanup failure')
        require(tiny.enabled(plan) or shape != 'G' or spill, 'native G external-memory spill/merge claim unmet')
        require(not any((data/'temp').iterdir()), 'native temp cleanup incomplete')
        # Chopper staging is on the output parent: no extra sibling is allowed.
        entries = {'fixture.json', 'job.json', 'checkpoint.json', 'temp', 'output'}
        if source_path(plan, shape, data) == data/'input.csv':
            entries.add('input.csv')
        require({p.name for p in data.iterdir()} == entries,
                'unexpected native staging/extra data artifact')
        create(Path(operation['report']), dict(os=plan['os'], slot=plan['os']+shape,
               product=plan['product']['commit'], passed=True, report=report,
               evidence_kind='native-tiny' if tiny.enabled(plan) else 'native-scale',
               host=plan['host'], plan_sha256=operation['plan_sha256'],
               spill_facts=facts, external_memory_claim='present' if spill else 'unmet',
               cleanup='temp empty; exact data siblings; owned descendants checked by caretaker'))
    elif stage == 'failure-prepare':
        require(tiny.enabled(plan) and shape == 'D', 'tiny malformed-input journey only')
        require(data == path(plan['owned_root'])/'failure-data', 'fixed tiny failure preparation directory required')
        from scale_acceptance.native_tiny import prepare_failure
        prepare_failure(plan, data)
    elif stage == 'failure-verify':
        from scale_acceptance.native_tiny import verify_failure
        verify_failure(plan, operation)
    else:
        raise ValueError('no arbitrary phase command')


def runner_plan(plan, operation, plan_path, operation_path, directory):
    stage, data = operation['stage'], Path(operation['data'])
    # A common filesystem root lets the maintained runner hash local data and
    # plan without moving/copying the frozen product. Cross-drive source/tool
    # maps are independently admitted and checked in this worker, not relabelled.
    source = source_path(plan, operation['shape'], data)
    paths = [plan_path, operation_path, directory, data, source]
    if stage == 'checkpoint-adoption':
        paths.append(path(plan['selected639_lineage']['path']))
    root = Path(os.path.commonpath(paths))
    relative = lambda p: str(Path(p).relative_to(root))
    inputs = [relative(plan_path), relative(operation_path)]
    artifacts = []
    if stage in ('generation', 'failure-prepare'):
        artifacts = [relative(data)]
        if stage == 'generation' and ('selected639_lineage' in plan or 'windows_lineage' in plan):
            inputs += [relative(operation[k]) for k in ('proposal', 'approval')]
    elif stage == 'checkpoint-adoption':
        lineage = Lineage(plan)
        inputs += [relative(lineage.adopt[k]['path']) for k in ('job', 'fixture', 'checkpoint')]
        inputs += [relative(plan['selected639_lineage']['path'])]
        inputs += [relative(operation[k]) for k in ('proposal', 'approval')]
        artifacts = [relative(data/n) for n in ('job.json', 'fixture.json', 'checkpoint.json')]
    elif stage in ('failure', 'failure-verify'):
        inputs += [relative(source)] + [relative(data/n) for n in ('job.json', 'fixture.json', 'failure.json')]
        inputs += [relative(operation[k]) for k in ('proposal', 'approval')]
        if stage == 'failure-verify':
            inputs += [relative(Path(operation['failed_batch'])/n) for n in
                       ('status.json', '1-stdout.log', '1-stderr.log')]
            artifacts = [relative(operation['report'])]
    else:
        inputs += [relative(source)] + [relative(data/n) for n in ('job.json', 'fixture.json', 'checkpoint.json')]
        if stage == 'Run':
            artifacts = [relative(data/'output')]
        else:
            inputs += [relative(data/'output')]
            inputs += [relative(operation['run_stdout'])]
            artifacts = [relative(operation['report'])]
        inputs += [relative(operation[k]) for k in ('proposal', 'approval')]
    argv = [plan['executable']['path'], 'run', '--config', str(data/'job.json'), '--yes'] if stage in ('Run', 'failure') else [
        plan['python']['path'], '-B', str(Path(__file__).resolve()), '_phase', str(plan_path), str(operation_path)]
    seconds = (LIMITS['generation_seconds']-324.064 if stage == 'checkpoint-adoption' else
               LIMITS[{'generation': 'generation_seconds', 'failure-prepare': 'generation_seconds',
                       'Run': 'run_seconds', 'failure': 'run_seconds', 'verify': 'verify_seconds',
                       'failure-verify': 'verify_seconds'}[stage]])
    return dict(root=str(root), batch_timeout_seconds=seconds, estimated_seconds=seconds,
                estimated_disk_bytes=LIMITS['owned_bytes'], toolchains=dict(python=plan['python']),
                features=[], fixtures=[plan['fixtures'][operation['shape']]],
                steps=[dict(id=stage, argv=argv, inputs=inputs, artifacts=artifacts, depends=[], timeout_seconds=seconds)])


def worker(plan_path, operation_path, directory):
    require(os.environ.pop('CHOPPER_NATIVE_WORKER', None) == '1', 'internal worker requires caretaker')
    directory = Path(directory)
    runner = load_runner()
    if os.name == 'nt':
        runner.contain_session()
        session = runner.owned_windows_job()
        publish(directory/'startup.json', dict(pid=os.getpid(), **session))
    else:
        import ctypes
        import signal
        libc = ctypes.CDLL(None, use_errno=True)
        require(libc.prctl(1, signal.SIGKILL, 0, 0, 0) == 0 and
                os.getppid() == int(os.environ['CHOPPER_NATIVE_CARETAKER_PID']),
                'actual Linux parent-death containment unavailable')
        publish(directory/'startup.json', dict(pid=os.getpid()))
    until = time.monotonic()+4
    while not (directory/'ready.json').exists():
        require(time.monotonic() < until, 'caretaker handoff timeout')
        time.sleep(.02)
    if os.name == 'nt':
        module('browser-small-windows').close(session['handle'])
    plan, operation = read_json(plan_path, 64*1024**2), read_json(operation_path)
    operation_plan_binding(plan_path, operation)
    validate(plan)
    identity = Identity(plan)  # external supervisor already watching all hash gaps
    peer_report(plan, operation['shape'])
    binding = run_binding(plan, operation) if operation['stage'] in ('Run', 'verify') else None
    if operation['stage'] in ('failure', 'failure-verify'):
        tiny.failure_binding(plan, operation)
    if operation['stage'] == 'checkpoint-adoption':
        adoption_binding(plan, operation)
    if operation['stage'] == 'generation':
        generation_binding(plan, operation)
    os.environ['CHOPPER_NATIVE_PHASE_PLAN_SHA256'] = sha256(plan_path)
    os.environ['CHOPPER_NATIVE_PHASE_OPERATION_SHA256'] = sha256(operation_path)
    execution = runner_plan(plan, operation, plan_path, operation_path, directory)
    execution_path = directory/'runner-plan.json'
    create(execution_path, execution)
    def guard():
        if tiny.enabled(plan):
            tiny.budget_check()
        identity.check()
        if operation['stage'] == 'checkpoint-adoption':
            adoption_binding(plan, operation)
        if operation['stage'] == 'generation':
            generation_binding(plan, operation)
        if operation['stage'] in ('Run', 'verify'):
            status = read_json(directory/'batch/status.json', 64*1024**2)
            run_binding(plan, operation)
            check_run_inputs(status['attempts'][-1], execution['root'], operation, plan, binding)
        if operation['stage'] in ('failure', 'failure-verify'):
            tiny.failure_binding(plan, operation)
        if tiny.enabled(plan) and not getattr(guard, 'launched', False):
            tiny.launch_check(plan)
            guard.launched = True
    publication = tiny.PublicationWatch(Path(operation['data'])) if tiny.enabled(plan) and operation['stage'] == 'Run' else None
    if publication:
        publication.start()
    try:
        code = runner.run(execution_path, directory/'batch', guard=guard)
    finally:
        if publication:
            publication.finish()
    if operation['stage'] == 'failure':
        # The raw runner receipt stays failed. Only the exact expected product
        # parse failure can satisfy this controlled journey.
        tiny.expected_failure(plan, operation, directory/'batch', execution['root'])
        require(code == 1, 'malformed product Run unexpectedly passed')
        code = 0
    Identity(plan)  # full post-source/tool/blob proof; watcher stays active
    if tiny.enabled(plan):
        tiny.budget_check()
    publish(directory/'worker-result.json', dict(code=code, runner_capture_closed=True,
            atomic_publication_observed=publication.observed if publication else None,
            metadata_usage=tiny.budget_usage() if tiny.enabled(plan) else None))
    while True:  # caretaker owns final termination and descendant census
        time.sleep(.1)


def check_run_inputs(attempt, root, operation, plan, binding):
    tool = plan['python'] if operation.get('stage') == 'verify' else plan['executable']
    require(attempt['runtime']['executable_sha256'] == tool['sha256'] and
            attempt['runtime']['executable'] == tool['path'], 'Run/verify executable mismatch')
    source = str(source_path(plan, operation['shape'], operation['data']).relative_to(root))
    require(digest(binding['input_sha256']) == binding['checkpoint']['sha256'] and
            attempt['inputs'][source]['sha256'] == binding['input_sha256'],
            'actual prelaunch input SHA mismatch')
    approved_actual = binding['actual']
    require(set(approved_actual) == {str(Path(operation['data'], n)) for n in ('job.json', 'fixture.json', 'checkpoint.json')},
            'complete approved actual Job/fixture/checkpoint map required')
    for name, expected in approved_actual.items():
        relative_name = str(Path(name).relative_to(root))
        require(attempt['inputs'][relative_name]['sha256'] == expected['sha256'],
                'actual approved Job/fixture/checkpoint hash mismatch')


def progress(monitor, operation, directory):
    data, stage = Path(operation['data']), operation['stage']
    if stage == 'generation' and (data/'input.csv').exists():
        monitor.useful(('generated-bytes', (data/'input.csv').stat().st_size))
    if stage == 'Run' and (data/'output').exists():
        monitor.useful(('published-csv-bytes', sum(p.stat().st_size for p in (data/'output').glob('*.csv'))))
    stderr = directory/'batch/1-stderr.log'
    if stage == 'Run' and stderr.exists():
        with stderr.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-4096))
            matches = re.findall(rb'([^\n]+) \| ([0-9]+) rows \| [0-9]+ MiB temporary\r?\n', stream.read(4096))
        for native_phase, rows in matches:
            monitor.native_rows(native_phase.decode('utf-8', errors='strict'), int(rows))
    # Only the independent checker/verifier's known numeric counters qualify.
    log = directory/'batch/1-stdout.log'
    if stage != 'Run' and log.exists():
        with log.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-4096))
            lines = stream.read(4096).splitlines()
        for line in reversed(lines):
            try:
                value = json.loads(line)
                if value.get('phase') in ('checkpoint', 'verify-source', 'verify-output', 'verify-membership'):
                    monitor.useful((value['phase'], value['rows']))
                    break
            except (ValueError, AttributeError):
                continue


def disk_sample(monitor, **kwargs):
    return bounded(lambda: monitor.sample(**kwargs), seconds=LIMITS['disk_observation_seconds'])


def execute(plan_path, plan, operation, monitor, lock):
    if tiny.enabled(plan):
        tiny.launch_check(plan)
    root = Path(plan['owned_root'])
    operation = dict(operation, plan_sha256=sha256(plan_path))
    op_path = root/(operation['shape']+'-'+operation['stage']+'.json')
    create(op_path, operation)
    directory = root/(operation['shape']+'-'+operation['stage'])
    disk_sample(monitor)  # Fresh complete capacity before ANY worker can start.
    owner = Caretaker(plan_path, op_path, directory, lock)
    failure = None
    try:
        owner.ready(monitor.last_capacity, monitor.hot_sample)
        while not (directory/'worker-result.json').exists():
            bounded(lambda: progress(monitor, operation, directory))
            disk_sample(monitor, pulse=lambda: bounded(lambda: owner.pulse(monitor.last_capacity)))
            owner.pulse(monitor.last_capacity)  # never fed by quota/log chatter; only completed census
            time.sleep(.5)
        result = read_json(directory/'worker-result.json')
        require(result['code'] == 0, 'maintained runner phase failed')
        if tiny.enabled(plan):
            require(result['runner_capture_closed'] is True, 'runner capture close proof missing')
            if operation['stage'] == 'Run':
                require(result['atomic_publication_observed'] is True, 'native public-directory observation missing')
        disk_sample(monitor, pulse=lambda: bounded(lambda: owner.pulse(monitor.last_capacity)))
        owner.pulse(monitor.last_capacity)
    except BaseException as error:
        failure = error
        if getattr(error,'process_handle_close_uncertain',False):lock.cleanup_uncertain = True
    finally:
        try:
            deadline = getattr(failure,'native_disk_deadline',None) if os.name == 'nt' else None
            last_hot = time.monotonic()
            while deadline is not None and pending_calls() and time.monotonic() < deadline:
                for thread in pending_calls():
                    thread.join(timeout=min(.05,max(0,deadline-time.monotonic())))
                if time.monotonic()-last_hot >= .5 and time.monotonic() < deadline:
                    try:bounded(monitor.hot_sample,seconds=min(2,deadline-time.monotonic()))
                    except BaseException as error:
                        try:failure.add_note('failed observation drain: '+repr(error))
                        except BaseException:pass
                    last_hot = time.monotonic()
            owner.finish(lambda: monitor.hot_sample())
            if getattr(owner,'phase_failed',None):
                require(not pending_calls(),'failed observation callback not joined')
                bounded(monitor.hot_sample)
            else:
                disk_sample(monitor)
        except BaseException as error:
            lock.cleanup_uncertain = (bool(getattr(lock,'cleanup_uncertain',False)) or
                bool(getattr(error,'process_handle_close_uncertain',False)) or not getattr(owner,'cleanup_proven',False))
            create(directory/'controller-cleanup-failure.json', dict(error=str(error), primary=str(failure)))
            if failure is None:
                failure = error
    if failure:
        raise failure
    if tiny.enabled(plan):
        cleanup = read_json(directory/'cleanup.json')
        require(cleanup['controller_eof'] is True and cleanup['monitor_threads_joined'] is True and
                cleanup['capture_writers_reaped'] is True and not pending_calls(),
                'tiny EOF/join/reap proof incomplete')


def wait_approval(file, approval_file, monitor):
    # Parent review consumes fixed OS time. No phase work is running here.
    while not bounded(lambda: approved(file, approval_file)):
        disk_sample(monitor, reviewing=True)
        time.sleep(.5)
    disk_sample(monitor, reviewing=True)


def failure_journey(plan_path, plan, monitor, lock):
    """Actual malformed work through the same runner/guard/owner boundaries."""
    root, exact_sha = path(plan['owned_root']), sha256(plan_path)
    data = root/'failure-data'
    monitor.phase(LIMITS['generation_seconds'])
    execute(plan_path, plan, dict(stage='failure-prepare', shape='D', data=str(data)), monitor, lock)
    file, approval = root/'failure-proposal.json', root/'failure-approved.json'
    create(file, dict(schema='native-scale-proposal-v1', stage='failure', plan_sha256=exact_sha,
                      payload=tiny.failure_payload(plan, data)))
    monitor.deadline = float('inf')
    wait_approval(file, approval, monitor)
    monitor.externals.update({p: stamp(p) for p in (file, approval, *(data/n for n in
        ('input.csv', 'job.json', 'fixture.json', 'failure.json')))})
    operation = dict(shape='D', data=str(data), proposal=str(file), approval=str(approval),
                     proposal_sha256=sha256(file))
    monitor.phase(LIMITS['run_seconds'])
    execute(plan_path, plan, dict(operation, stage='failure'), monitor, lock)
    monitor.phase(LIMITS['verify_seconds'])
    execute(plan_path, plan, dict(operation, stage='failure-verify',
        failed_batch=str(root/'D-failure/batch'), report=str(root/'failure-verified.json')), monitor, lock)


def session_failure_record(root, error):
    """Keep the primary callable/trace before cleanup may retain the owner."""
    try:
        import traceback
        create(root/'session-failure.json',dict(error=str(error)[:4096],
            notes=[str(note)[:1024] for note in getattr(error,'__notes__',())[:8]],
            traceback=''.join(traceback.format_exception(error))[-8192:],
            pending_callbacks=bool(pending_calls()),qualification=False))
    except BaseException as diagnostic_error:
        try:error.add_note('session failure diagnostic unavailable: '+repr(diagnostic_error))
        except BaseException:pass


def windows_scale_result(plan, exact_sha, code, failure, original_lock):
    """The current session's receipt; an accepted historical D remains separate."""
    from scale_acceptance.native_scale_identity import execution_shapes
    return dict(schema='native-windows-scale-result-v1',passed=code == 0,
            error=failure,evidence_kind='native-scale',scale_acceptance=code == 0,scale_slots_consumed=len(execution_shapes(plan)) if code == 0 else None,
            plan_sha256=exact_sha,original_lock=original_lock,os=plan['os'],host=plan['host'],
            current_session_shapes=list(execution_shapes(plan)))


def session(plan_path, exact_sha, preflight_path=None, preflight_sha=None, *, cancelled=None):
    from scale_acceptance.native_scale_identity import execution_shapes
    before = preparation_call('plan stat', lambda: stamp(plan_path))
    require(preparation_call('plan hash', lambda: sha256(plan_path)) == digest(exact_sha), 'exact OS session plan approval required')
    plan = preparation_call('plan read', lambda: read_json(plan_path, 64*1024**2))
    preparation_call('plan validation', lambda: validate(plan))
    qualification = tiny.enabled(plan)
    windows_scale = plan['os'] == 'Windows' and not qualification
    controlled = qualification or windows_scale
    execution = plan['qualification'] if qualification else plan.get('windows_execution',{})
    if controlled:
        require(preflight_path is not None and preflight_sha is not None, 'matching preflight is required for tiny')
        prepared = preparation_call('preflight custody', lambda: tiny.preflight(plan_path, plan, preflight_path, preflight_sha))
        if qualification:tiny.launch_check(plan)
        else:require(time.time() < execution['launch_cutoff_unix'], 'original native launch cutoff expired')
        require(preparation_call('original lock stat', lambda: stamp(path(plan['reservation']['lock_path']))) == execution['original_lock_stat'],
                'original tiny lock identity drift')
    lineage = preparation_call('retained history', lambda: tiny.History(plan) if qualification else Lineage(plan))
    require(plan['host']['os'] == ('Windows' if os.name == 'nt' else 'Linux'), 'native OS mismatch')
    root = path(plan['owned_root'])
    require(plan_path.drive == root.drive, 'plan/data must share a runner volume; source/tool roles may use other volumes')
    require(not preparation_call('root absence', root.exists), 'fresh OS root required; no retries/resume')
    held_lock = HostLock()
    held_lock.existing = controlled
    if _PREPARATION_UNTIL is not None:
        print(json.dumps(dict(native_preparation_phase='HostLock')), file=sys.stderr, flush=True)
    with held_lock as lock:
        require(stamp(plan_path) == before and sha256(plan_path) == exact_sha, 'approved session plan drift')
        require(str(lock.path) == plan['reservation']['lock_path'], 'approved actual local-ci lock path mismatch')
        if controlled:
            require(lock.proof()['stat'] == execution['original_lock_stat'], 'original held lock mismatch')
        lineage.check()
        if not qualification and plan['os'] == 'Linux':
            ledger = path(lineage.value['current']['canonical_slot_ledger'])
            require(not ledger.exists() or not any(ledger.glob('*-consumed.json')), 'canonical slot already consumed; no new session')
        root.mkdir()
        create(root/'reservation.json', dict(plan=plan['reservation'], actual_lock=lock.proof(),
                   owner_start_ticks=(Path('/proc', str(os.getpid()), 'stat').read_text().rsplit(')', 1)[1].split()[19]
                                      if os.name != 'nt' else None),
                   volumes=plan['volumes'], source_reservation=plan['source_reservation']))
        cancellation = dict(cancelled=cancelled) if cancelled is not None else {}
        if windows_scale:cancellation['stop_unix'] = execution['stop_unix']
        campaign = TinyCampaign(plan, exact_sha, lineage, **cancellation) if qualification else Campaign(plan['campaign'], plan['os'], exact_sha, lineage=lineage, **cancellation)
        failure = None
        try:
            if not qualification and plan['os'] == 'Linux':
                ledger.mkdir(exist_ok=True)
            preparation_call('prepared under original lock', lambda: None)
            if _PREPARATION_UNTIL is not None:
                print(json.dumps(dict(native_preparation_complete=True)), file=sys.stderr, flush=True)
            tick = time.monotonic()
            initialization_seconds = tiny.cold_admission_seconds(plan)
            constructed = False
            try:
                monitor = bounded(lambda: Monitor(plan, lock, campaign, root/'capacity.jsonl'),
                                  seconds=initialization_seconds)
                constructed = True
            finally:
                if controlled:
                    create(root/'guard-initialization.json', dict(seconds=time.monotonic()-tick,
                        bound_seconds=initialization_seconds, completed=constructed, kind='cold-full-constructor'))
            monitor.externals[plan_path] = stamp(plan_path)
            disk_sample(monitor, start=True)
            if plan['os'] == 'Windows':
                require(lock.owner.request(dict(command='observe')) == dict(ok=True,idle=True),
                        'qualified idle Original owner observation required')
            monitor.externals.update({p: stamp(p) for p in
                (root/'reservation.json', Path(plan['campaign'])/(plan['os']+'-started.json'))})
            if controlled:
                monitor.externals[path(str(preflight_path))] = stamp(path(str(preflight_path)))
                monitor.externals.update({path(p): stamp(path(p)) for p in prepared['checker']['files']})
            for shape in execution_shapes(plan):
                slot, data = plan['os']+shape, root/(shape+'-data')
                if not qualification:
                    bounded(lambda: campaign.predecessor(slot))
                monitor.deadline = float('inf')
                stage = 'checkpoint-adoption' if shape == 'D' and not qualification and plan['os'] == 'Linux' else 'generation'
                gen, approval = root/(shape+'-'+stage+'-proposal.json'), root/(shape+'-'+stage+'-approved.json')
                payload = adoption_payload(plan, data) if stage == 'checkpoint-adoption' else dict(slot=slot, recipe=plan['fixtures'][shape],
                          data=str(data), reservation=lock.proof(), limits=LIMITS)
                bounded(lambda: proposal(gen, stage, exact_sha, payload))
                wait_approval(gen, approval, monitor)
                monitor.phase(LIMITS['generation_seconds']-(324.064 if stage == 'checkpoint-adoption' else 0))
                execute(plan_path, plan, dict(stage=stage, shape=shape, data=str(data), proposal=str(gen),
                        approval=str(approval), proposal_sha256=sha256(gen)), monitor, lock)
                # Pin actual source/Job/checkpoint metadata throughout review,
                # Run, verifier hashes and cleanup. Runner additionally hashes.
                source = source_path(plan, shape, data)
                pinned = {p: stamp(p) for p in (source, *(data/n for n in ('job.json', 'fixture.json', 'checkpoint.json')))}
                monitor.externals.update(pinned)
                checked = bounded(lambda: actual_checkpoint(plan, shape, data))
                run_proposal = root/(shape+'-Run-proposal.json')
                bounded(lambda: proposal(run_proposal, 'Run', exact_sha, dict(slot=slot, checkpoint=checked,
                         actual={str(p): dict(stat=s, sha256=sha256(p)) for p, s in pinned.items() if p.name != 'input.csv'},
                         input_sha256=checked['sha256'], executable=plan['executable'],
                         source=dict(path=str(source), stat=stamp(source)), lineage_sha256=LINEAGE_SHA,
                         session_authority=dict(start_sha256=sha256(Path(plan['campaign'])/(plan['os']+'-started.json')),
                                                reservation_sha256=sha256(root/'reservation.json')),
                         python=plan['python'], tools=plan['tools'], source_roles=dict(product=plan['product'], harness=plan['harness']),
                         peer=plan['peers'].get(shape, {}), reservation=lock.proof(), limits=LIMITS)))
                monitor.deadline = float('inf')
                wait_approval(run_proposal, root/(shape+'-Run-approved.json'), monitor)
                monitor.externals.update({p: stamp(p) for p in (run_proposal, root/(shape+'-Run-approved.json'))})
                if qualification:
                    claim = None
                else:
                    claim = (wait_windows_claim(plan,plan_path,dict(stage='Run',shape=shape,data=str(data),
                        proposal=str(run_proposal),approval=str(root/(shape+'-Run-approved.json')),
                        proposal_sha256=sha256(run_proposal),plan_sha256=exact_sha),monitor,lineage)
                        if plan['os'] == 'Windows' else bounded(lambda: claim_run(plan_path, exact_sha, run_proposal)))
                    bounded(lambda: campaign.consume(slot, run_proposal, claim))
                    monitor.externals.update({p: stamp(p) for p in
                        (claim, Path(plan['campaign'])/(slot+'-consumed.json'))})
                monitor.phase(LIMITS['run_seconds'])
                execute(plan_path, plan, dict(stage='Run', shape=shape, data=str(data), proposal=str(run_proposal),
                        approval=str(root/(shape+'-Run-approved.json')), proposal_sha256=sha256(run_proposal),
                        claim_sha256=sha256(claim) if claim else None), monitor, lock)
                monitor.phase(LIMITS['verify_seconds'])
                report = root/(shape+'-verified.json')
                execute(plan_path, plan, dict(stage='verify', shape=shape, data=str(data), report=str(report),
                        proposal=str(run_proposal), approval=str(root/(shape+'-Run-approved.json')),
                        proposal_sha256=sha256(run_proposal),
                        claim_sha256=sha256(claim) if claim else None,
                        run_stdout=str(root/(shape+'-Run')/'batch/1-stdout.log')), monitor, lock)
                record = Path(plan['campaign'])/(slot+('-tiny-verified.json' if qualification else '-verified.json'))
                create(record, dict(slot=slot, passed=True,
                       evidence_kind='native-tiny' if qualification else 'native-scale',
                       report=str(report), sha256=sha256(report), plan_sha256=exact_sha))
                monitor.externals.update({p: stamp(p) for p in
                    (report, record)})
            if qualification:
                failure_journey(plan_path, plan, monitor, lock)
            disk_sample(monitor)
        except BaseException as error:
            failure = str(error)
            session_failure_record(root,error)
        # A future admitted source adapter must close before success metadata.
        # HostLock retains the original owner if quiescence cannot be proven.
        if getattr(lock, 'source_pool', None) is not None:
            try:
                lock.close_source_pool()
            except BaseException as error:
                failure = str(error) if failure is None else failure+'; source cleanup: '+str(error)
        create(root/'session-result.json', dict(passed=failure is None, error=failure,
               next_steps='parent review, real containment integration/platform gates/local CI and costly approvals pending'))
        if failure is None:
            if getattr(monitor, 'source_pool', None) is None:
                disk_sample(monitor)
            if not qualification:
                create(Path(plan['campaign'])/(plan['os']+'-completed.json'), dict(passed=True,
                       plan_sha256=exact_sha, session_result_sha256=sha256(root/'session-result.json')))
        code = int(failure is not None)
    if qualification:
        # No clean qualification exists until the original descriptor/owner has
        # closed after every phase's captures, monitors, stop/reap and census.
        require(not pending_calls() and lock.released['original_descriptor_closed'] is True,
                'tiny original lock release unproven')
        require(stamp(lock.path) == plan['qualification']['original_lock_stat'], 'original lock file replaced at release')
        release_error = None
        try:
            tiny.check_clock(plan)
            tiny.budget_check()
        except ValueError as error:
            release_error = str(error)
            code = 1
        create(root/'qualification-result.json', dict(schema=tiny.SCHEMA, passed=code == 0,
            error=failure or release_error,
            evidence_kind='native-tiny', scale_acceptance=False, scale_slots_consumed=0,
            os=plan['os'], host=plan['host'], plan_sha256=exact_sha,
            preflight=dict(path=str(preflight_path), sha256=preflight_sha),
            accounting=(dict(scope='fresh native allocation baseline and future no-refund growth',
                             allocation_origin=lineage.allocation_origin, historical_allocation_bound=None)
                        if plan['os'] == 'Windows' else dict(scope='original sealed Linux history and future no-refund growth')),
            original_lock=lock.released, session_result_sha256=sha256(root/'session-result.json')))
        if code == 0:
            tiny.check_clock(plan)
            create(Path(plan['campaign'])/(plan['os']+'-tiny-completed.json'), dict(passed=True,
                evidence_kind='native-tiny', scale_acceptance=False, scale_slots_consumed=0,
                plan_sha256=exact_sha, qualification_sha256=sha256(root/'qualification-result.json')))
    if windows_scale:
        if time.time() >= execution['stop_unix']:
            failure = failure or 'original Windows scale stop expired before release receipt'
            code = 1
        require(not pending_calls() and lock.released['original_descriptor_closed'] is True and
                lock.released['capture_eof_joined'] is True, 'Windows scale Original release unproven')
        create(root/'scale-result.json',windows_scale_result(plan,exact_sha,code,failure,lock.released))
        if code == 0:
            create(Path(plan['campaign'])/'Windows-scale-completed.json',dict(passed=True,plan_sha256=exact_sha,
                scale_result_sha256=sha256(root/'scale-result.json')))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preparation = sub.add_parser('prepare', help='derive one disabled selected native packet; never launch')
    preparation.add_argument('definition', type=Path)
    preparation.add_argument('directory', type=Path)
    preparation.add_argument('--sha256', required=True)
    staging = sub.add_parser('stage', help='fresh bounded WSL source bootstrap; never a Native session')
    staging.add_argument('definition',type=Path)
    staging.add_argument('receipt',type=Path)
    staging.add_argument('--sha256',required=True)
    supervisor = sub.add_parser('supervise', help='exact parent-driven Tiny/Windows scale operator; no implicit approvals')
    supervisor.add_argument('definition', type=Path)
    supervisor.add_argument('--sha256', required=True)
    supervisor.add_argument('--execute', action='store_true', help='explicit grant for exactly the selected definition/journey')
    audit = sub.add_parser('after-exit', help='independent selected native exit audit; never stops actors')
    audit.add_argument('--verifier-sha256',help='Explicit separate verifier module pin; frozen runtime source stays checked')
    audit.add_argument('definition', type=Path)
    audit.add_argument('--sha256', required=True)
    lifecycle = sub.add_parser('_lifecycle', help='internal supervised temporary-lock lifecycle control')
    lifecycle.add_argument('directory', type=Path)
    lifecycle.add_argument('output', type=Path)
    approve_parser = sub.add_parser('approve', help='write explicit approval of an existing exact proposal')
    approve_parser.add_argument('proposal', type=Path)
    approve_parser.add_argument('approval', type=Path)
    approve_parser.add_argument('--sha256', required=True)
    launch = sub.add_parser('session', help='parent-only: hold reservation across D/G and reviews')
    launch.add_argument('plan', type=Path)
    launch.add_argument('--sha256', required=True)
    launch.add_argument('--preflight',type=Path)
    launch.add_argument('--preflight-sha256')
    qualify = sub.add_parser('qualify', help='parent-only: full native tiny journey, no scale slots')
    qualify.add_argument('plan', type=Path)
    qualify.add_argument('--sha256', required=True)
    qualify.add_argument('--preflight', type=Path, required=True)
    qualify.add_argument('--preflight-sha256', required=True)
    claim = sub.add_parser('claim-run', help='Linux parent: burn one canonical slot for an actual approved Run')
    claim.add_argument('plan', type=Path)
    claim.add_argument('proposal', type=Path)
    claim.add_argument('--sha256', required=True)
    claim.add_argument('--windows',action='store_true',help='Linux parent claims a challenged native Windows Run')
    for name in ('_caretaker', '_worker'):
        internal = sub.add_parser(name)
        internal.add_argument('plan', type=Path)
        internal.add_argument('operation', type=Path)
        internal.add_argument('directory', type=Path)
    internal = sub.add_parser('_lock_owner')
    internal.add_argument('lock', type=Path)
    internal.add_argument('--existing', action='store_true')
    internal = sub.add_parser('_phase')
    internal.add_argument('plan', type=Path)
    internal.add_argument('operation', type=Path)
    args = parser.parse_args()
    if args.command in ('qualify', '_worker', '_phase', '_caretaker'):
        selected = preparation_call('selected plan read', lambda: read_json(args.plan, 64*1024**2))
        if tiny.enabled(selected):
            require(args.plan.stat().st_size <= 4*1024**2, 'tiny plan metadata ceiling')
            tiny.budget = preparation_call('metadata budget', lambda: tiny.ReadBudget(selected, args.plan))
    if args.command in ('prepare','stage'):
        from scale_acceptance.native_preflight import prepare_current,stage_current
        require(sha256(args.definition) == args.sha256, 'preparation definition pin drift')
        definition = read_json(args.definition)
        os.environ.update({'_': str(Path(sys.executable).resolve()),
            'GIT_OPTIONAL_LOCKS': '0', 'PYTHONDONTWRITEBYTECODE': '1'})
        limits = definition['preparation_limits'] if args.command == 'prepare' else definition['limits']
        meter = tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=limits['read_bytes'], visits=limits['visits']))), args.definition)
        until = time.monotonic()+limits['seconds']
        class PreparationBudget:
            def check(self):
                meter.check()
                require(time.monotonic() < until, 'native packet preparation deadline')
            @property
            def read_bytes(self):
                return meter.read_bytes
            @property
            def visits(self):
                return meter.visits
            @property
            def remaining_seconds(self):
                return max(0, until-time.monotonic())
        tiny.budget = meter
        try:
            result = bounded(lambda: (prepare_current(definition,args.directory,PreparationBudget())
                if args.command == 'prepare' else stage_current(definition,args.receipt,PreparationBudget())),
                             seconds=limits['seconds'])
        except BaseException as error:
            try:
                print(json.dumps(dict(native_preparation_failed=args.command,error=repr(error)[:4096],
                    notes=[str(note)[:1024] for note in getattr(error,'__notes__',())[:4]],
                    pending_calls=bool(pending_calls()),
                    owned_subprocess_pending=bool(getattr(error,'owned_subprocess_pending',False)))),
                    file=sys.stderr,flush=True)
            except BaseException:
                pass
            while pending_calls() or getattr(error,'owned_subprocess_pending',False):
                time.sleep(.05)
            raise
        print(json.dumps(result))
    elif args.command == 'supervise':
        from scale_acceptance.native_scale_windows import supervise
        return supervise(args.definition, args.sha256, execute=args.execute)
    elif args.command == 'after-exit':
        require(sha256(args.definition) == args.sha256, 'independent audit definition pin drift')
        definition = read_json(args.definition)
        root = path(definition['namespace'])
        frozen = read_json(root/'Root-freeze.json')
        require(definition['schema'] in ('native-tiny-operator-v1','native-scale-operator-v1') and
                frozen['definition_sha256'] == args.sha256 and
                frozen['source_maps'] == definition['source_maps'], 'exact frozen operator/audit binding')
        return tiny.after_exit(root, frozen['plan_sha256'],verifier_sha256=args.verifier_sha256)
    elif args.command == '_lifecycle':
        module('test-native-scale-runner').native_lock_owner_probe(args.directory,args.output)
    elif args.command == 'approve':
        approve(args.proposal, args.approval, args.sha256)
    elif args.command in ('session', 'qualify'):
        if args.command == 'session':
            require(not tiny.enabled(read_json(args.plan, 64*1024**2)), 'use explicit qualify command for tiny')
        else:
            require(preparation_call('qualification mode', lambda: tiny.enabled(read_json(args.plan, 64*1024**2))), 'qualify requires explicit tiny plan')
        arguments = (args.plan.absolute(), args.sha256)
        if args.preflight is not None:
            arguments += (args.preflight.absolute(), args.preflight_sha256)
        if sys.platform.startswith('linux'):
            import signal
            cancelled = [False]
            def cancel(signum, frame):
                cancelled[0] = True
            previous = signal.signal(signal.SIGINT, cancel)
            try:
                return session(*arguments, cancelled=lambda: cancelled[0])
            finally:
                signal.signal(signal.SIGINT, previous)
        return session(*arguments)
    elif args.command == 'claim-run':
        (claim_windows_run if args.windows else claim_run)(args.plan.absolute(), args.sha256, args.proposal.absolute())
    elif args.command == '_caretaker':
        return caretaker(args.plan, args.operation, args.directory)
    elif args.command == '_lock_owner':
        windows_lock_owner(args.lock, existing=args.existing)
    elif args.command == '_worker':
        worker(args.plan, args.operation, args.directory)
    elif args.command == '_phase':
        require(os.environ.get('CHOPPER_NATIVE_PHASE_PLAN_SHA256') == sha256(args.plan),
                'internal phase requires exact worker plan binding')
        require(os.environ.get('CHOPPER_NATIVE_PHASE_OPERATION_SHA256') == sha256(args.operation),
                'internal phase requires exact worker operation binding')
        plan, operation = read_json(args.plan, 64*1024**2), read_json(args.operation)
        operation_plan_binding(args.plan, operation)
        validate(plan)
        phase(plan, operation)
    return 0


if __name__ == '__main__':
    if _WINDOWS_STARTUP:
        from scale_acceptance.native_scale_windows import controller_entry
        controller_entry(_startup_token, sys.stdin, lambda line: print(line, file=sys.stderr, flush=True))
        _PREPARATION_UNTIL = float(_preparation_until)
        require(time.monotonic() < _PREPARATION_UNTIL <= time.monotonic()+180,
                'explicit shared Windows preparation deadline required')
    try:
        code = main()
    except BaseException as error:
        closed = getattr(error, 'native_owner_no_start_closed', None)
        if _WINDOWS_STARTUP and closed is not None:
            try:
                print(json.dumps(dict(native_preparation_failed='HostLock',
                    no_worker_owner_closed=closed, pending_calls=bool(pending_calls()))),
                    file=sys.stderr, flush=True)
            except BaseException:
                pass  # Diagnostic allocation/stdio failure cannot replace the primary error.
        raise
    finally:
        if tiny.budget_usage() is not None:
            print(json.dumps(dict(native_tiny_metadata_usage=tiny.budget_usage())), file=sys.stderr, flush=True)
    raise SystemExit(code)
