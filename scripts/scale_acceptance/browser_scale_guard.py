"""Full-scale guard: approved exact plan, one-shot reservation, no retry/resume."""
import contextlib
import hashlib
import json
import os
import stat
from pathlib import Path, PureWindowsPath
import sys
import time
from .browser_scale_identity import ScaleIdentity, concrete, real_path
from .browser_scale_plan import documents, destination_path, GiB
from .guard import Guard, DiskObservation, load_runner
from .browser_scale_watchdog import Watchdog
from .native_scale_host import module
from .owner_retention import retain_owner
from .verify import read_json, require, sha256, validate_job, unique_object, MAX_LINE


def channel_owned_roots(reservation, channel):
    roots=[real_path(slot['directory']) for slot in
        [*reservation['slots'],*reservation.get('qualifications',[])] if slot['channel']==channel]
    return [path for path in roots if path.exists()]


def read_quota_journal(path, previous=None):
    """Read one complete append-only record within the existing JSON bound."""
    path=Path(path)
    def ancestors():
        rows=[]
        for parent in path.parents:
            s=parent.lstat()
            require(stat.S_ISDIR(s.st_mode) and not getattr(s,'st_file_attributes',0)&0x400,
                    'quota ancestor reparse/type')
            rows.append((str(parent),s.st_dev,s.st_ino))
        return rows
    lineage=ancestors()
    def leaf(s):
        require(stat.S_ISREG(s.st_mode) and s.st_nlink==1
                and not getattr(s,'st_file_attributes',0)&0x400, 'quota regular single-link file required')
        return (s.st_dev,s.st_ino,getattr(s,'st_birthtime_ns',None))
    before=path.lstat();identity=leaf(before)
    if previous:
        require(identity==previous['identity'] and lineage==previous['ancestors']
                and before.st_size>=previous['bytes'], 'quota identity/truncation drift')
    with path.open('rb') as stream:
        held=os.fstat(stream.fileno())
        require(leaf(held)==identity and held.st_size>=before.st_size,'quota opened identity/truncation drift')
        end=held.st_size;offset=max(0,end-MAX_LINE)
        stream.seek(offset);tail=stream.read(end-offset)
        newline=tail.rfind(b'\n')
        require(newline>=0,'quota has no bounded complete record')
        end=offset+newline
        del tail
        offset=max(0,end-MAX_LINE)
        stream.seek(offset);record=stream.read(end-offset)
        if offset:
            newline=record.rfind(b'\n')
            require(newline>=0,'quota record exceeds JSON bound')
            record=record[newline+1:]
        else:record=record.rsplit(b'\n',1)[-1]
        require(0<len(record)<MAX_LINE,'quota complete JSON record bound')
        sample=json.loads(record,object_pairs_hook=unique_object)
        after=os.fstat(stream.fileno())
        require(leaf(after)==identity and after.st_size>=held.st_size,'quota held identity/truncation drift')
    current=path.lstat()
    require(leaf(current)==identity and current.st_size>=after.st_size and ancestors()==lineage,
            'quota path identity/truncation drift')
    return sample,dict(identity=identity,ancestors=lineage,bytes=current.st_size)


def approval_record(approval, manifest, plan, policy, binding, packet):
    expected = dict(version=1, decision='approved', contract=manifest['contract'],
                    plan_id=packet['plan_id'], shape=packet['shape'], channel=packet['channel'],
                    plan_sha256=sha256(plan), policy_sha256=sha256(policy), packet_sha256=binding['sha256'],
                    reservation_sha256=packet['reservation']['sha256'])
    require(all(approval.get(key) == value for key, value in expected.items()), 'explicit per-shape parent approval binding required')
    require(concrete(approval.get('approved_by')) and concrete(approval.get('approval_reference')),
            'named parent approval and reference required')
    require(manifest['plan_id'] == approval['plan_id'], 'approval plan mismatch')


def schedule_declaration(packet, directory, r, now, *, path_type=Path):
    """The same reservation predicate at preparation and actual launch."""
    require(r['version'] == 1 and r['parent_scheduled'] is True and concrete(r['campaign']), 'parent reservation required')
    qualifying = packet['mode'] == 'qualify'
    slots = r['qualifications'] if qualifying else r['slots']
    require(1 <= len(slots) <= 4 and len({(s['shape'], s['channel']) for s in slots}) == len(slots)
            and len({s['plan_id'] for s in slots}) == len(slots), 'four unique large Runs maximum')
    require(all(s['shape'] in ('D', 'G') and s['channel'] in ('chrome', 'msedge') for s in slots), 'invalid campaign cell')
    selected = [s for s in slots if s['plan_id'] == packet['plan_id']]
    require(len(selected) == 1 and selected[0] == dict(plan_id=packet['plan_id'], shape=packet['shape'],
            channel=packet['channel'], directory=str(directory)), 'reservation shape/channel/attempt mismatch')
    if qualifying:
        require(all(s['plan_id'] != packet['plan_id'] and path_type(s['directory']) != directory
                    for s in r['slots']), 'tiny reservation must not occupy a large Run identity/root')
    if 'time_continuation'in r:
        from .hosted_qualification import browser_scale_time_reservation
        require(packet['channel']=='msedge','continued reservation cannot authorize Chrome')
        browser_scale_time_reservation(r['time_continuation'],r)
    channel = r['channels'][packet['channel']]
    require(type(channel['start_unix']) in (float, int) and type(channel['deadline_unix']) in (float, int)
            and 0 < channel['deadline_unix'] - channel['start_unix'] <= 21600
            and channel['start_unix'] <= now < channel['deadline_unix'], 'parent six-hour channel reservation required')
    claims = path_type(r['claims_root'])
    require(claims.is_absolute() and not claims.is_relative_to(directory), 'external parent claims root required')
    return channel['deadline_unix']


def schedule(packet, directory, now):
    r = read_json(packet['reservation']['path'])
    deadline = schedule_declaration(packet, directory, r, now)
    claims = real_path(r['claims_root'])
    require(claims.is_dir() and not claims.is_relative_to(directory), 'existing external parent claims root required')
    if 'time_continuation'in r:
        from .hosted_qualification import browser_scale_time_available
        browser_scale_time_available(r['time_continuation'],initial=False,plan_id=packet['plan_id']) if packet['mode']=='scale' else require(not os.path.lexists(claims/'active.lock'),'original campaign has an active owner')
    return r, claims, deadline


class ScaleGuard(Guard):
    def __init__(self, policy, log, identity, channel_deadline, clock=time.monotonic, disk=None, fixture_pinned=False):
        self.identity, self.channel_deadline = identity, channel_deadline
        self.quota_seen = False
        self.quota_state = None
        self.fixture_pinned = fixture_pinned
        self.runner_attempts = ()
        self.samples = 0
        super().__init__(policy, log, clock, disk=disk)

    def observe(self, observation):
        # Detached immutable checkpoints are published before the runner's guard.
        self.runner_attempts = observation.attempts

    def sample(self, start=False, force=False):
        tick = time.monotonic()
        error = None
        try:
            return self.full_sample(start=start, force=force)
        except BaseException as failure:
            error = str(failure)
            raise
        finally:
            self.samples += 1
            with Path(self.log).with_name('full-guard-samples.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(sequence=self.samples, initial=start, force=force,
                    seconds=time.monotonic()-tick, error=error)) + '\n')

    def full_sample(self, start=False, force=False):
        self.identity.check()
        attempts = self.runner_attempts
        if not self.fixture_pinned:
            if attempts and attempts[-1].id in ('browser-scale', 'verify'):
                p = self.identity.packet
                directory = Path(self.log).parent.parent / p['shape']
                fixture = read_json(directory / 'fixture.json')
                config = read_json(directory / 'job.json')
                validate_job(config, fixture)
                require(fixture['tiny'] is (p['mode'] == 'qualify') and fixture['shape'] == p['shape'] and fixture['runtime'] == 'browser'
                        and {key: fixture[key] for key in p['fixture']} == p['fixture'], 'frozen scale fixture mismatch')
                self.identity.pin(Path(p['borrowed_input']['path']) if 'borrowed_input' in p else directory/'input.csv', p['fixture']['sha256'])
                for name in ('fixture.json', 'job.json'):
                    self.identity.pin(directory / name, sha256(directory / name))
                self.fixture_pinned = True
        if time.time() >= self.channel_deadline:
            raise OSError('scale guard: channel deadline')
        super().sample(start=start, force=force)
        quota_path = Path(self.log).parent.parent / 'work/quota.jsonl'
        # Startup has no origin yet. The driver independently gates Run on the
        # first real quota sample; once observed it may never disappear/go stale.
        # Once the owned browser step has exited, independent host verification
        # has no live origin sampler. Physical/storage/source guards continue.
        verifying = bool(attempts and attempts[-1].id == 'verify')
        if not verifying and (quota_path.exists() or quota_path.is_symlink() or self.quota_seen):
            sample,self.quota_state = read_quota_journal(quota_path,self.quota_state)
            now = time.time()
            minimum = 2 * GiB if self.quota_seen else 16 * GiB
            require(type(sample['sampled_unix']) in (int, float) and 0 <= now - sample['sampled_unix'] <= 90
                    and type(sample['usable_bytes']) is int and sample['usable_bytes'] >= minimum,
                    'scale origin quota stale/denied')
            self.quota_seen = True


@contextlib.contextmanager
def claim_slot(claims, plan_id):
    # Exclusive global campaign lock plus permanent consumed slot. A failed
    # attempt consumes its slot too. A crash leaves the lock for parent audit.
    lock = claims / 'active.lock'
    with lock.open('x', encoding='ascii') as stream:
        stream.write(str(os.getpid()))
    with (claims / (plan_id + '.consumed')).open('x', encoding='ascii') as stream:
        stream.write(str(time.time()))
    # Retain the active lock after success/failure/crash. The parent retires it
    # only after the controller has exited (closing its kill-on-close Job), all
    # owned processes are gone and prior shape storage has been reconciled.
    yield


def capture_process(process, ownership, windows):
    if process is None:
        require(not ownership['launch_pending'],'overlapping process launch')
        ownership['launch_pending']=True
        return
    row=dict(process=process,pid=process.pid,created=None,close_attempted=False,closed=False)
    ownership['processes'].append(row)
    require(len(ownership['processes'])<=3,'three planned processes maximum')
    kernel=windows.kernel()
    require(kernel.GetProcessId(process._handle)==process.pid,'returned process handle PID mismatch')
    row['created']=windows._held_birth(kernel,process._handle,process.pid)
    ownership['launch_pending']=False


def close_uncertain(error):
    for _ in range(4):
        if error is None:return False
        if getattr(error,'process_handle_close_uncertain',False):return True
        error=error.__cause__ or error.__context__
    return False


def finish_scale(ownership, windows, job, watchdog, disk, controls, stop_owned):
    """Attempt every closer; only positive quiescence can release Original."""
    report=dict(errors=[],processes=[],original_release_safe=False)
    uncertain=(ownership.get('handle_uncertain',False) or close_uncertain(watchdog.error)
               or watchdog.termination_error is not None)
    def attempt(phase, action, *, ownership_error=True):
        nonlocal uncertain
        try:return action()
        except BaseException as error:
            report['errors'].append(dict(phase=phase,error=repr(error)[:2048]))
            uncertain|=ownership_error
            uncertain|=close_uncertain(error)
            return None
    watchdog.done.set()
    attempt('stop-owned-descendants',stop_owned)
    for row in ownership['processes']:
        process=row['process']
        def reap():
            require(row['created'] is not None,'process birth unproved')
            code=process.wait(timeout=10)
            kernel=windows.kernel()
            require(kernel.GetProcessId(process._handle)==row['pid'] and
                windows._held_birth(kernel,process._handle,row['pid'])==row['created'] and
                kernel.WaitForSingleObject(process._handle,0)==0,'held process end/birth unproved')
            row['exit_code']=code
        attempt('process-wait',reap)
        if row.get('exit_code') is not None:
            row['close_attempted']=True
            def close():
                process._handle.Close()
                row['closed']=True
            attempt('process-close',close)
        report['processes'].append({key:value for key,value in row.items() if key!='process'})
    try:watchdog.stop()
    except BaseException as error:
        report['watchdog_error']=repr(error)[:2048]
        if watchdog.failure is None:uncertain=True
    report['watchdog_joined']=not watchdog.sampler.is_alive() and not watchdog.monitor.is_alive()
    uncertain|=close_uncertain(watchdog.error)
    if watchdog.termination_error is not None:
        uncertain=True
        error=watchdog.termination_error
        report['termination_error']=dict(error=repr(error)[:2048],
            **{key:getattr(error,key) for key in ('api','pid','path','winerror') if hasattr(error,key)})
    if disk.thread is not None:
        attempt('post-write-capacity',lambda:disk.after(time.monotonic()),ownership_error=False)
        if controls:attempt('final-full-guard',lambda:controls[0].sample(force=True),ownership_error=False)
    attempt('disk-stop',disk.stop)
    report['disk_stopped']=not disk.pending
    final=attempt('final-job-census',lambda:windows.query_job(job))
    report['job']=final
    report['launch_pending']=ownership['launch_pending']
    report['runner_active']=ownership['runner_active']
    report['watchdog_launch_uncertain']=watchdog.launch_uncertain
    report['original_release_safe']=(not uncertain and not ownership['runner_active']
        and not watchdog.launch_uncertain and report['watchdog_joined'] and report['disk_stopped']
        and final is not None and final['kill_on_close'] and final['pids']==[os.getpid()]
        and all(row['closed'] and row.get('exit_code') is not None for row in report['processes']))
    return report


def retain_original(runner, batch, report):
    retain_owner(lambda: runner.write_json(batch/'owner-retained.json',report))


def record_cleanup(runner,batch,cleanup,ownership,original,lock,stamp,owner_birth):
    try:runner.write_json(batch/'cleanup.json',cleanup)
    except BaseException as error:
        ownership['receipt_error']=True
        ownership['handle_uncertain']|=close_uncertain(error)
        cleanup['receipt_error']=repr(error)[:2048]
    if not cleanup['original_release_safe'] or ownership.get('handle_uncertain'):
        retain_original(runner,batch,dict(pid=os.getpid(),created=owner_birth,original=original,cleanup=cleanup))
    try:
        require(stamp is not None,'Original pathname identity unproved')
        current=lock.stat()
        require((current.st_dev,current.st_ino)==(stamp.st_dev,stamp.st_ino),'Original pathname identity changed')
    except BaseException as error:
        retain_original(runner,batch,dict(pid=os.getpid(),created=owner_birth,error=repr(error)[:2048]))



def recovery_code():
    from .hosted_qualification import native_path
    source_root=Path(__file__).resolve().parents[1]
    paths=[*source_root.joinpath('scale_acceptance').glob('*.py'),
        *source_root.joinpath('hosted_picker').glob('*.py'),source_root/'validation-runner.py',
        source_root/'browser-small-windows.py',source_root/'local-ci.py',source_root/'scale-acceptance.py',
        source_root/'acceptance-preflight.py',*source_root.joinpath('scale_acceptance').glob('*.mjs'),
        source_root/'browser-artifacts.mjs']
    return [dict(path=native_path(path),sha256=sha256(path)) for path in sorted(set(paths))]


def recovery_request(binding):
    from .hosted_qualification import _local_binding
    r=_local_binding(binding)
    require(not sys.flags.optimize,'recovery metadata assertions must remain enabled')
    require(r['schema']=='browser-scale-export-recovery-v1','explicit completed-export recovery only')
    root=PureWindowsPath(r['root']);source_root=Path(__file__).resolve().parents[1]
    require(root.is_absolute() and root.parent==PureWindowsPath('C:/') and '..' not in root.parts
        and root.name.startswith('hosted104-') and '-recovery-' in root.name
        and all(ch.isascii() and (ch.isalnum() or ch in '-_') for ch in root.name),'fresh disjoint recovery namespace')
    require(PureWindowsPath(r['profile'])==root/'profile' and PureWindowsPath(r['profile_copy_receipt'])==root/'profile-copy.json',
        'derived recovery destinations')
    require(r['limits']==dict(read_bytes=16*1024**3,profile_bytes=2*1024**3,visits=2000000,
        metadata_bytes=16*1024**2,growth_bytes=4*1024**3,copy_seconds=1800,extract_seconds=1800,verify_seconds=1800),
        'bounded read/copy/extraction limits')
    require(type(r['start_unix']) in (int,float) and type(r['deadline_unix']) in (int,float)
        and 0<r['deadline_unix']-r['start_unix']<=5400,'fresh bounded recovery window')
    code={PureWindowsPath(row['path']):row['sha256'] for row in r['recovery_code']}
    expected={PureWindowsPath(row['path']):row['sha256'] for row in recovery_code()}
    require(len(code)==len(r['recovery_code']) and code==expected,'exact complete current recovery code pin required')
    p=_local_binding(r['frozen_packet']);state=_local_binding(r['public_state']);browser=_local_binding(r['browser_receipt'])
    independent=_local_binding(r['independent']);release=_local_binding(r['release'])
    original=PureWindowsPath(p['profile']).parent.parent
    require(all(PureWindowsPath(r[key]['path'])==original/relative for key,relative in
        [('public_state','work/public-state.json'),('browser_receipt','work/browser-receipt.json'),
         ('release','batch/reservation-released.json')]),'derive original evidence paths from selected profile')
    require(state['profile']==p['profile'] and state['origin']==p['origin'],'original state origin/profile binding')
    require(p['mode']=='scale' and p['shape']=='G' and state['status']=='complete' and state['error'] is None,
        'actual completed selected G Run required; no Run recovery')
    require(browser['status']=='failed' and browser['packet_sha256']==r['frozen_packet']['sha256']
        and browser['profile']==p['profile'] and browser['origin']==p['origin'] and browser['source']==p['source']
        and browser['browser']==p['browser'] and browser['actual_browser_version']==p['browser_version']
        and browser['plan_id']==p['plan_id'],'exact original failed extraction context')
    require(independent['status']=='passed-after-exit' and independent['scale_cell_passed'] is False
        and any(PureWindowsPath(row['path'])==PureWindowsPath(r['release']['path']) and row['sha256']==r['release']['sha256']
            for row in independent['source_receipts']) and release['passed'] is False
        and release['cleanup']['original_release_safe'] is True and release['released_after_supervision'] is True,
        'positive original failed-controller cleanup required')
    require(not root.is_relative_to(PureWindowsPath(p['harness']['root'])) and not PureWindowsPath(p['harness']['root']).is_relative_to(root)
        and not root.is_relative_to(PureWindowsPath(p['profile'])) and not PureWindowsPath(p['profile']).is_relative_to(root),
        'recovery/source/profile overlap')
    reservation=_local_binding(p['reservation'])
    original_deadline=schedule_declaration(p,original,reservation,r['start_unix'],path_type=PureWindowsPath)
    require(r['deadline_unix']<=original_deadline,'recovery cannot extend original channel deadline')
    claim=PureWindowsPath(reservation['claims_root'])/(p['plan_id']+'.consumed')
    consumed=_local_binding(r['consumed_claim'])
    require(claim==PureWindowsPath(r['consumed_claim']['path']) and type(consumed) in (int,float) and consumed>0,
        'original permanently consumed claim required, unchanged')
    observed=_local_binding(r['closed_profile_observation'])
    require(observed['status']=='passed' and observed['host']['os']=='Windows'
        and all(observed.get(key) is False for key in ('workload_started','original_acquired','controller_started')),
        'full read-only closed-profile observation required')
    observed_pins={PureWindowsPath(row['path']):row['sha256'] for row in observed['inputs']}
    require(all(observed_pins.get(PureWindowsPath(p[role]['path']))==p[role]['sha256'] for role in ('python','node','browser')),
        'observed selected runtime drift; stop before profile copy')
    require(PureWindowsPath(p['profile']) in {PureWindowsPath(name) for name in observed['input_directories']},
        'complete observed original profile membership required')
    return r,p,reservation


def recovery_documents(binding,p,*,path_type=Path,scripts=None):
    from .hosted_qualification import _local_binding,native_path
    r=_local_binding(binding);root=path_type(r['root'])
    scripts=path_type(native_path(Path(__file__).resolve().parents[1]) if scripts is None else scripts)
    code=[row['path'] for row in r['recovery_code']]
    profile_receipt=path_type(r['profile_copy_receipt'])
    require(profile_receipt==root/'profile-copy.json','derived profile-copy receipt required')
    profile_relative=profile_receipt.relative_to(root).as_posix()
    base=[p['python']['path'],'-E','-s','-B']
    original=path_type(p['profile']).parent.parent
    inputs=[*code,binding['path'],*[r[key]['path'] for key in
        ('frozen_packet','public_state','browser_receipt','independent','release','consumed_claim','closed_profile_observation')],
        str(original/p['shape']/'job.json'),str(original/p['shape']/'fixture.json')]
    steps=[dict(id='copy-profile',argv=[*base,str(scripts/'scale-acceptance.py'),
                'browser-scale-copy-profile',binding['path'],'--sha256',binding['sha256']],
            timeout_seconds=1800,inputs=inputs,artifacts=[profile_relative],depends=[]),
        dict(id='extract-completed',argv=[p['node']['path'],str(scripts/'scale_acceptance/browser-scale-driver.mjs'),
                '--extract-completed',binding['path'],binding['sha256']],timeout_seconds=1800,
            inputs=[*inputs,profile_relative],artifacts=['work/extraction-receipt.json','work/G'],depends=['copy-profile']),
        dict(id='verify',argv=[*base,str(scripts/'scale-acceptance.py'),'verify',str(original/'G/job.json'),
                str(original/'G/fixture.json'),str(root/'verified.json'),'--output',str(root/'work/G'),
                '--bitmap-dir',str(root)],timeout_seconds=1800,inputs=[*inputs,'work/G'],
            artifacts=['verified.json'],depends=['extract-completed'])]
    plan=dict(root=str(root),contract='browser-scale-export-recovery-v1',plan_id=p['plan_id'],shape=p['shape'],
        channel=p['channel'],recovery=binding,steps=steps,batch_timeout_seconds=5400,estimated_seconds=900,
        estimated_disk_bytes=4*GiB,toolchains=p['toolchains'],features=[],fixtures=[p['fixture']])
    policy=dict(version=1,contract=plan['contract'],owned_bytes=24*GiB,start_free_bytes=40*GiB,
        stop_free_bytes=8*GiB,deadline_seconds=5400,no_progress_seconds=600,sample_seconds=1,
        owned_roots=[str(root)],volumes=[str(root)],scale_frozen=dict(packet=r['frozen_packet']['path'],sha256=r['frozen_packet']['sha256']),
        progress_paths=[str(root/'work/progress.jsonl'),str(root/'batch/1-stdout.log'),str(root/'batch/3-stdout.log')])
    return plan,policy


def _copy_recovery_profile(binding,budget):
    """A bounded owned child copies only the observed closed profile, never CSV input."""
    from .hosted_qualification import bound_json
    from hosted_picker.config import path as plain_path
    from hosted_picker.suite import _inventory_match
    r,p,_=recovery_request(binding);root=Path(r['root']);source=plain_path(p['profile']);target=plain_path(r['profile'])
    observed=bound_json(r['closed_profile_observation']);members=[str(Path(name)) for name in next(value for key,value in
        observed['input_directories'].items() if Path(key)==source)]
    expected={}
    for row in observed['inputs']:
        key=str(Path(row['path']));require(expected.setdefault(key,row['sha256'])==row['sha256'],'conflicting observed alias pin')
    require(len(members)==len(set(members)) and all(name in expected for name in members),'observed profile pins required')
    started=time.monotonic();visits=read_bytes=copied_bytes=published_bytes=0;metadata_bytes=0;files={};directories={}
    def check():
        require(time.monotonic()-started<1800 and time.time()<r['deadline_unix'],'profile-copy deadline')
        require(visits<=r['limits']['visits'] and read_bytes<=r['limits']['read_bytes'],'profile-copy accounting bound')
        budget.check()
    def walk():
        nonlocal visits,metadata_bytes
        result={};dirs={}
        def denied(error):raise error
        for base,names,leaves in os.walk(source,onerror=denied):
            for name in [base,*[str(Path(base)/name) for name in names+leaves]]:
                visits+=1;check();q=plain_path(name);s=q.lstat()
                require(not getattr(s,'st_file_attributes',0)&0x400 and (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)),
                    'plain closed profile only')
                if stat.S_ISREG(s.st_mode):
                    require(s.st_nlink==1,'profile hardlink denied: '+str(q));result[str(q)]=s
                    metadata_bytes+=len(str(q).encode())+256
                else:dirs[str(q)]=(s.st_dev,s.st_ino)
                require(metadata_bytes<=r['limits']['metadata_bytes'],'bounded profile inventory')
        return result,dirs
    import stat
    files,directories=walk();require(set(files)==set(members),'profile membership changed since observation; firstmissing='+repr(sorted(set(members)-set(files))[:4])+'; firstextra='+repr(sorted(set(files)-set(members))[:4]))
    size=sum(s.st_size for s in files.values());forecast=3*size+2*p['fixture']['bytes']+64*1024**2
    require(size<=r['limits']['profile_bytes'] and forecast<=r['limits']['read_bytes'] and
        size+2*p['fixture']['bytes']+64*1024**2<r['limits']['growth_bytes'],'profile metadata forecast needs-budget: '+json.dumps(dict(files=len(files),profile_bytes=size,read_forecast=forecast,
            growth_forecast=size+2*p['fixture']['bytes']+64*1024**2,limits=r['limits']),sort_keys=True))
    require(not target.exists(),'fresh copied profile required')
    root.mkdir(exist_ok=True);target.mkdir()
    for name in sorted(directories,key=lambda x:len(Path(x).parts)):
        if Path(name)!=source:(target/Path(name).relative_to(source)).mkdir()
    for name,before in files.items():
        check();src=plain_path(name);dest=plain_path(target/src.relative_to(source));digest=hashlib.sha256()
        with src.open('rb') as stream, dest.open('xb') as output:
            opened=os.fstat(stream.fileno());_inventory_match(src,'named-to-held-open',before,opened,held=True)
            while chunk:=stream.read(65536):
                read_bytes+=len(chunk);check();digest.update(chunk)
                require(output.write(chunk)==len(chunk),'profile copy short write')
                copied_bytes+=len(chunk)
                if copied_bytes-published_bytes>=16*1024**2:
                    print(json.dumps(dict(phase='closed-profile copy',copied_bytes=copied_bytes)),flush=True)
                    published_bytes=copied_bytes
            after=os.fstat(stream.fileno());_inventory_match(src,'held-before-to-after',opened,after)
            _inventory_match(src,'named-to-held-after',before,after,held=True)
        _inventory_match(src,'named-after-close',before,src.lstat())
        require(digest.hexdigest()==expected[name] and dest.stat().st_size==before.st_size,
            'observed profile body drift: '+str(src)+'; expected='+expected[name]+'; actual='+digest.hexdigest())
        read_bytes+=before.st_size;check();require(sha256(dest)==expected[name],'copied profile hash mismatch')
    final,final_dirs=walk();require(set(final)==set(files) and final_dirs==directories,'source profile membership/identity changed')
    for name,value in files.items():_inventory_match(name,'final-named-profile',value,final[name])
    result=dict(status='passed',definition_sha256=binding['sha256'],source=str(source),destination=str(target),
        source_unchanged=True,files=len(files),bytes=size,read_bytes=read_bytes,visits=visits,
        metadata_forecast_read_bytes=forecast,elapsed_seconds=time.monotonic()-started,
        usage=budget.usage(),bootstrap_read_allowance=64*1024**2,bootstrap_read_allowance_is_measurement=False)
    with Path(r['profile_copy_receipt']).open('x',encoding='utf-8') as stream:json.dump(result,stream)
    return result


def copy_recovery_profile(binding):
    require(os.name=='nt','closed-profile copy requires actual Windows')
    from .hosted_qualification import _local_binding
    # The fixed bootstrap admits this definition and imports; the existing audit
    # then charges code/proof reads, repeated opens and every profile-body read.
    selected=_local_binding(binding)
    from hosted_picker import config,suite
    checker=module('acceptance-preflight')
    root=Path(selected['root'])
    budget=checker.Budget(dict(seconds=1800,read_bytes=16*1024**3,visits=2000000,
        capture_bytes=65536,storage_bytes=4*1024**3),root,mutation_roots=[root])
    budget.install()
    try:return _copy_recovery_profile(binding,budget)
    finally:budget.active=False


def run_scale(plan, policy, approval, *, preparation=None):
    plan, policy, approval = map(lambda p: real_path(str(Path(p).absolute())), (plan, policy, approval))
    proposed=read_json(plan);recovery=proposed.get('recovery')
    admitted=recovery_request(recovery) if recovery is not None else None
    directory=Path(admitted[0]['root']) if admitted else destination_path(plan.parent)
    require(plan.parent==directory,'derived recovery plan directory') if admitted else None
    batch = directory / 'batch'
    batch.mkdir(exist_ok=False)  # Fresh attempt only; preserve prelaunch denials.
    runner = load_runner()
    try:
        manifest, observation = proposed, read_json(policy)
        runner.write_json(batch / 'requested-plan.json', manifest)
        runner.write_json(batch / 'guard-policy.json', observation)
        binding = observation['scale_frozen']
        require(not admitted or binding==dict(packet=admitted[0]['frozen_packet']['path'],sha256=admitted[0]['frozen_packet']['sha256']),'exact original recovery packet required')
        identity = ScaleIdentity(binding)
        p = identity.packet
        if admitted:
            original=Path(p['profile']).parent.parent
            fixture=read_json(original/p['shape']/'fixture.json');config=read_json(original/p['shape']/'job.json')
            validate_job(config,fixture)
            require(fixture['tiny'] is False and fixture['runtime']=='browser' and fixture['shape']==p['shape']
                and {key:fixture[key] for key in p['fixture']}==p['fixture'],'original completed fixture binding')
            identity.pin(original/p['shape']/'input.csv',p['fixture']['sha256'])
            for item in (original/p['shape']/'fixture.json',original/p['shape']/'job.json'):
                identity.pin(item,sha256(item))
            for row in admitted[0]['recovery_code']:identity.pin(Path(row['path']),row['sha256'])
        from .hosted_qualification import preflight
        require(preparation is not None, 'matching actual-host preflight required before any Run')
        prepared=preflight(preparation, binding['packet'], 'browser-scale')
        require(not admitted or prepared.get('recovery')==recovery,'matching current recovery-code preflight required')
        from .hosted_qualification import batch_admission
        batch_admission(p, 'browser-scale', p['channel'])
        identity.require_windows()
        require(Path(sys.executable).resolve() == Path(p['python']['path']).resolve(), 'selected Python mismatch')
        expected_plan, expected_policy = recovery_documents(recovery,p) if admitted else documents(directory, binding, p)
        require(manifest == expected_plan and observation == expected_policy, 'scale plan/policy changed or ceilings expanded')
        approved = read_json(approval)
        approval_record(approved, manifest, plan, policy, binding, p)
        runner.write_json(batch / 'parent-approval.json', approved)
        for path in (plan, policy, approval):
            require(not path.is_relative_to(batch), 'approval/plan must be immutable outside batch')
            identity.pin(path, sha256(path))
        if admitted:
            reservation,claims,channel_deadline=admitted[2],None,admitted[0]['deadline_unix']
            require(admitted[0]['start_unix']<=time.time()<channel_deadline,'fresh recovery window')
        else:reservation, claims, channel_deadline = schedule(p, directory, time.time())
        runner.contain_session()  # Before Original and before all children.
        windows,ci=module('browser-small-windows'),module('local-ci')
        kernel=windows.kernel();owner=os.getpid();job=runner._SESSION_JOB
        own=windows.query_job(job)
        require(own['kill_on_close'] and own['pids']==[owner],'initial controller-only Job required')
        owner_birth=windows._held_birth(kernel,kernel.GetCurrentProcess(),owner)
        ownership=dict(processes=[],launch_pending=False,runner_active=False,handle_uncertain=False)
        effective_policy=dict(observation)
        effective_policy['owned_roots']=[str(path) for path in channel_owned_roots(reservation,p['channel'])]+([str(directory)] if admitted else [])
        effective_policy['volumes']=effective_policy['owned_roots']
        disk=DiskObservation(lambda:Guard.disk_values(
            [Path(value) for value in effective_policy['owned_roots']],
            [Path(value) for value in effective_policy['volumes']]))
        controls=[];stop_end=[None]
        def stop_owned():
            if stop_end[0] is None:stop_end[0]=time.monotonic()+10
            return windows.stop_descendants(job,owner,stop_end[0])
        def sample():
            if not controls:
                controls.append(ScaleGuard(effective_policy,batch/'capacity.jsonl',identity,channel_deadline,disk=disk,**(dict(fixture_pinned=True) if admitted else {})))
            else:controls[0]()
        watchdog=Watchdog(sample,batch/'watchdog-failure.json',terminate=stop_owned)
        entered=released=False;failure=None;result=1
        lock=ci.host_lock_path();stamp=None;original=dict(path=str(lock))
        def record(path,value):
            try:runner.write_json(path,value)
            except BaseException as error:
                ownership['receipt_error']=True
                ownership['handle_uncertain']|=close_uncertain(error)
                raise
        try:
            with ci.host_lock():
                entered=True
                try:
                    stamp=lock.stat();original.update(device=stamp.st_dev,inode=stamp.st_ino)
                    if admitted:
                        from .hosted_qualification import bound_json
                        require([stamp.st_dev,stamp.st_ino]==bound_json(admitted[0]['release'])['original_lock_identity'],
                            'recovery must use the unchanged original lock')
                    record(batch/'ownership.json',dict(pid=owner,created=owner_birth,original=original,acquired=True))
                    with (contextlib.nullcontext() if admitted else claim_slot(claims,p['plan_id']+('.tiny' if p['mode']=='qualify' else ''))):
                        record(batch/'scale-authority.json',dict(packet_sha256=binding['sha256'],
                            plan_sha256=sha256(plan),policy_sha256=sha256(policy),plan_id=p['plan_id'],
                            parent_pid=owner,channel_deadline_unix=channel_deadline))
                        marker=time.monotonic();disk.start();disk.after(marker)
                        watchdog.start()
                        require(watchdog.initial.wait(watchdog.stale),'full cold guard did not finish within five seconds')
                        watchdog.check()
                        ownership['runner_active']=True
                        try:
                            result=runner.run(plan,batch,guard=watchdog.check,observe=controls[0].observe,
                                on_process=lambda process:capture_process(process,ownership,windows))
                        finally:
                            ownership['runner_active']=False
                except BaseException as error:
                    failure=error
                    ownership['handle_uncertain']|=close_uncertain(error)
                finally:
                    try:
                        cleanup=finish_scale(ownership,windows,job,watchdog,disk,controls,stop_owned)
                    except BaseException as error:
                        # Even an unexpected cleanup failure cannot unwind Original.
                        for close in (watchdog.stop,disk.stop):
                            try:close()
                            except BaseException:pass
                        retain_original(runner,batch,dict(pid=owner,created=owner_birth,error=repr(error)[:2048]))
                    record_cleanup(runner,batch,cleanup,ownership,original,lock,stamp,owner_birth)
            released=True
        except BaseException as error:
            if entered and not released:
                retain_original(runner,batch,dict(pid=owner,created=owner_birth,error=repr(error)[:2048],original_close_unproved=True))
            raise
        passed=(result==0 and failure is None and not cleanup['errors'] and watchdog.failure is None
                and not ownership.get('receipt_error'))
        runner.write_json(batch/'reservation-released.json',dict(pid=owner,created=owner_birth,original=original,
            original_lock_identity=[stamp.st_dev,stamp.st_ino],
            released_after_supervision=True,passed=passed,cleanup=cleanup,
            **(dict(operation='completed-export extraction only',product_runs=0,new_claims=0,recovery=recovery) if admitted else {})))
        if failure is not None:raise failure
        return 0 if passed else 1
    except BaseException as error:
        attempts=[dict(id=a.id,attempt=a.attempt,status=a.status) for a in controls[0].runner_attempts] if locals().get('controls') else []
        runner.write_json(batch / 'guard-failure.json', dict(status='failed', error=str(error),
            attempts=attempts, unrun_steps=[s['id'] for s in locals().get('manifest', {}).get('steps', [])
                if s['id'] not in {a['id'] for a in attempts}]))
        raise
