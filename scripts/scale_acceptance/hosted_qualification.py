"""Preparation for the existing hosted controllers; never acquire Original or start a workload."""
import hashlib
import json
import os
import subprocess
import base64
import datetime
import inspect
import shutil
import tempfile
import sys
import stat
import re
import time
import threading
from pathlib import PureWindowsPath, PurePosixPath
from pathlib import Path
import platform

from .verify import require

SCHEMA = 'chopper-hosted-tiny-qualification-v1'
PROFILES = ('actual-picker', 'small', 'browser-scale')


def host():
    return {key: getattr(platform, method)() for key, method in (
        ('os', 'system'), ('release', 'release'), ('version', 'version'),
        ('machine', 'machine'), ('node', 'node'))}


def bound_json(binding, maximum=16 * 1024**2):
    path = Path(binding['path'])
    require(path.is_absolute() and '..' not in path.parts, 'absolute receipt path required')
    require(all(not p.is_symlink() and not getattr(p, 'is_junction', lambda: False)()
                for p in (path, *path.parents)), 'receipt alias denied')
    before = path.stat()
    require(0 < before.st_size <= maximum, 'receipt size bound')
    raw = path.read_bytes()
    after = path.stat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(stamp(before) == stamp(after) and len(raw) == before.st_size, 'receipt changed while reading')
    require(hashlib.sha256(raw).hexdigest() == binding['sha256'], 'receipt hash drift')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate receipt field')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def preflight(binding, selected, profile):
    """Match exact selected bytes and complete checker contents, including paths.

    The existing adapters still revalidate every mutable capacity/identity under
    their original guard. This receipt only admits entry to that path.
    """
    require(profile in (*PROFILES, 'native-ui'), 'unsupported preparation receipt profile')
    value = bound_json(binding)
    require(value['schema'] == 'chopper-acceptance-preflight-v1' and value['status'] == 'passed',
            'matching passed preflight required')
    require(value['profile'] == profile and value['host'] == host(),
            'preflight host/profile mismatch')
    bound_json(dict(path=str(selected), sha256=value['plan_sha256']))
    require(all(value.get(key) is False for key in
                ('workload_started', 'acceptance_window_started', 'scale_slot_consumed')),
            'not a preparation receipt')
    files = value['checker']['files']
    require(files and all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                          for path, digest in files.items()), 'preflight checker drift')
    require(value.get('worker_receipt_sha256'), 'supervised preparation receipt required')
    worker = dict(path=str(Path(binding['path']).with_name('worker-result.json')),
                  sha256=value['worker_receipt_sha256'])
    admitted = bound_json(worker)
    for key in ('schema', 'status', 'profile', 'host', 'plan_sha256', 'checker', 'bindings'):
        require(admitted[key] == value[key], 'preflight parent/worker mismatch: ' + key)
    require(admitted.get('recovery')==value.get('recovery'),'preflight parent/worker recovery mismatch')
    return value


def borrowed_input_stamp(path):
    value = Path(path).lstat()
    require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and
            not getattr(value,'st_file_attributes',0) & 0x400, 'borrowed input regular single-link required')
    return [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,
            value.st_mode,value.st_nlink,getattr(value,'st_file_attributes',0)]


def batch_admission(selected, profile, channel=None):
    kind = selected.get('execution_kind', 'qualification')
    require(kind in ('qualification','batch'), 'explicit qualification or frozen batch only')
    if profile == 'browser-scale' and selected['mode'] == 'scale':
        require(kind == 'batch', 'Large requires a complete matching Tiny frozen batch')
        require(browser_scale_campaign(selected['campaign_qualification'])['reservation']==selected['campaign_reservation'],
            'canonical reservation must be the actual qualified Tiny reservation')
        require(selected['reservation']['sha256']==selected['campaign_reservation']['sha256'],
            'current reservation differs from qualified canonical campaign')
    if kind == 'qualification':
        require('frozen_batch' not in selected, 'qualification cannot masquerade as a frozen batch')
        return None
    require('frozen_batch' in selected, 'matching frozen batch definition required before launch')
    return qualified_batch(selected['frozen_batch'], selected, profile, channel)


def execution_selection(selection):
    kind = selection.get('execution_kind', 'qualification')
    require(kind in ('qualification','batch'), 'explicit qualification or frozen batch only')
    require(('frozen_batch' in selection) == (kind == 'batch'), 'batch requires a qualification definition; qualification never consumes one')
    return {key:selection[key] for key in ('execution_kind','frozen_batch') if key in selection}


def batch_inputs(binding):
    """The small immutable proof closure also participates in live identity checks."""
    definition = _local_binding(binding)
    pins = [binding,*[definition[key] for key in
            ('configuration','preflight','tiny','independent','verifier')]]
    pins += [definition[key] for key in ('summary','supplement','release') if key in definition]
    if 'failure' in definition:pins += list(definition['failure'].values())
    for proof in [definition,*([definition['failure']] if 'failure' in definition else [])]:
        pref = _local_binding(proof['preflight'])
        name = proof['preflight']['path']
        sibling = PureWindowsPath(name) if PureWindowsPath(name).is_absolute() else Path(name)
        pins.append(dict(path=str(sibling.with_name('worker-result.json')),sha256=pref['worker_receipt_sha256']))
    reference=_local_binding(definition['configuration'])
    if 'time_continuation'in reference:pins += browser_scale_time_inputs(reference['time_continuation'],history=reference.get('time_continuation_history'))
    return pins


def check_borrowed_input(binding, *, observe=False):
    """No copy, generation, ownership transfer or refund of an existing fixture."""
    require(set(binding) == {'path','sha256','bytes','stat','owner_root','qualification'},
            'complete borrowed input identity/ownership required')
    name, root = PureWindowsPath(binding['path']), PureWindowsPath(binding['owner_root'])
    # Tests may use native POSIX files; Windows declarations always keep native names.
    native = name.is_absolute()
    require((name.is_relative_to(root) and name != root) if native else
            (Path(binding['path']).is_absolute() and Path(binding['path']).is_relative_to(Path(binding['owner_root'])) and
             binding['path'] != binding['owner_root']), 'borrowed fixture must retain its original owner root')
    local = binding['path']
    if native and os.name != 'nt':
        local = subprocess.check_output(['wslpath','-u',local],text=True,timeout=4).strip()
    path = Path(local)
    require(all(not p.is_symlink() and not getattr(p,'is_junction',lambda:False)()
                for p in (path,*path.parents)), 'borrowed input alias denied')
    stamp = lambda: borrowed_input_stamp(path)
    require(type(binding['bytes']) is int and 0 < binding['bytes'] <= 128000, 'bounded borrowed Tiny bytes required')
    before = stamp()
    require(before[2] == binding['bytes'], 'borrowed input byte count drift')
    # WSL metadata is a different producer; only actual native materialization
    # may capture the Windows identity used by every subsequent live check.
    if not native or os.name == 'nt':
        require((observe and binding['stat'] is None) or before == binding['stat'], 'borrowed input metadata drift')
    proof = _local_binding(binding['qualification'])
    require(proof['schema'] == SCHEMA and proof['passed'] is True and proof['profile'] == 'browser-scale' and
            proof['details']['generated_input_bytes']+proof['details'].get('reused_input_bytes',0) == binding['bytes'] and
            proof['details']['fixture']['sha256'] == binding['sha256'], 'borrowed input prior debit/qualification missing')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream,'sha256').hexdigest()
    require(actual == binding['sha256'] and stamp() == before, 'borrowed input body/identity drift')
    return dict(binding,stat=before) if observe else binding


def prepare_batch_definition(selection_path, destination):
    """Seal original qualification pins and their reusable execution projection."""
    from .generate import write_new
    from .verify import read_json
    selection = read_json(selection_path,1024**2)
    require(selection['schema'] == 'chopper-frozen-batch-selection-v1', 'frozen batch selection schema')
    definition = dict(selection,schema='chopper-frozen-batch-v1')
    reference = _local_binding(definition['configuration'])
    definition['frozen'] = batch_projection(reference,definition['profile'])
    if definition['profile']=='actual-picker':
        failure = _local_binding(definition['failure']['configuration'])
        definition['frozen'] = {reference['case']:definition['frozen'],failure['case']:batch_projection(failure,'actual-picker')}
    # Validate the exact same owning receipt predicate before producing a definition.
    # A temporary in-memory reader is unnecessary: the checker accepts a parsed
    # definition internally and the public launch boundary always hashes its file.
    check_qualified_batch(definition,reference,definition['profile'],definition['channel'])
    destination = Path(destination).absolute()
    roots = [reference[key]['root'] for key in ('product','harness')
             if isinstance(reference.get(key),dict) and 'root' in reference[key]]
    if reference.get('root'):roots.append(reference['root'])
    require(all(not destination.is_relative_to(Path(root)) for root in roots), 'batch definition overlaps frozen source')
    require(not destination.exists(),'fresh immutable batch definition required')
    write_new(destination,definition)
    return dict(path=str(destination),sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                profile=definition['profile'],channel=definition['channel'],workload_started=False)


def picker_case(proof, channel):
    """Original output oracle plus normal ownership closure, not a fabricated audit."""
    reference=_local_binding(proof['configuration']);pref=_local_binding(proof['preflight'])
    report=_local_binding(proof['tiny']);outcome=_local_binding(proof['independent'])
    require(reference['schema']=='chopper-hosted-picker-qualification-v1' and reference['channel']==channel and
        report['profile']=='actual-picker' and report['channel']==channel and report['case']==reference['case'] and
        report['configSha256']==proof['configuration']['sha256'] and report['preflight']==proof['preflight'] and
        report['tinyCaseQualified'] is True and report['scaleAcceptance'] is False and report['acceptance'] is False,
        'matching original actual-picker case required')
    require(pref['schema']=='chopper-acceptance-preflight-v1' and pref['status']=='passed' and
        pref['profile']=='actual-picker' and pref['plan_sha256']==proof['configuration']['sha256'] and
        all(pref.get(key) is False for key in ('workload_started','acceptance_window_started','scale_slot_consumed')),
        'matching picker preflight required')
    name=proof['preflight']['path'];source=PureWindowsPath(name) if PureWindowsPath(name).is_absolute() else Path(name)
    worker=_local_binding(dict(path=str(source.with_name('worker-result.json')),sha256=pref['worker_receipt_sha256']))
    require(all(worker[key]==pref[key] for key in ('schema','status','profile','host','plan_sha256','checker','bindings')),
        'picker preflight parent/worker mismatch')
    require(report['windowsVersion'][:3]==[int(value) for value in pref['host']['version'].split('.')],
            'picker actual Windows version mismatch')
    cleanup=report['privateCleanup'];parent=report['reservation']['owner']['pid']
    require(report['observationComplete'] is True and report['originalReservationClosedAfterQuiescence'] is True and
        report['parentPipeEOF']==dict(stdout=True,stderr=True) and report['innerFinal']['pids']==[] and
        report['outerFinal']['pids']==[parent] and cleanup['complete'] is True and cleanup['errors']==[] and
        cleanup['jobPids']==[report['workerBirth']['pid']] and cleanup['reaped']==2 and
        cleanup['eof']==dict(browser=dict(stdout=True,stderr=True),uia=dict(stdout=True,stderr=True)),
        'complete picker EOF/reap/Original cleanup required')
    require(outcome['receipt_sha256']==proof['tiny']['sha256'] and outcome['status'] in
        ('passed','passed-actual-edge-success','passed-scoped-actual-edge-header-cap-failure'),
        'picker independent output/cleanup receipt chain mismatch')
    source_commit=outcome.get('head',outcome.get('selected_controller_commit',outcome.get('source_commit')))
    require(source_commit==reference['qualification_source']['commit'],'picker outcome/source identity mismatch')
    if reference['case']=='success':
        oracle=outcome.get('export_oracle',outcome.get('export'))
        require(report['tinyExportComplete'] is True and oracle==report['exportOracle'] and
            oracle['complete'] is True and oracle['rows']==2 and oracle['csvBytes']==66 and oracle['strictCsvCapBytes']==40 and
            oracle['marker']==dict(complete=True,engine='chopper-browser',files=3,version=1) and
            set(oracle['files'])=={'CHOPPER-COMPLETE.json','manifest.jsonl','part-00000001.csv','part-00000002.csv'} and
            all(type(row['bytes']) is int and row['bytes']>0 and re.fullmatch('[0-9a-f]{64}',row['sha256'])
                for row in oracle['files'].values()),
            'complete independent literal CSV/manifest/marker oracle required')
    else:
        require(reference['case']=='failure' and report['controlledFailureComplete'] is True,
                'complete selected picker controlled failure required')
        oracle=outcome['failure_oracle']
        if 'cleanup' in oracle:
            require(oracle['kind']=='controlled-failure-complete' and oracle['status']=='FAILED' and
                oracle['error']=='Error: header/BOM exceeds output byte limit' and oracle['runs']==1 and
                oracle['cleanup']==dict(locks=[],workspaces=[]),'original Chrome failure oracle required')
        else:
            require(oracle==dict(expected_error='Error: header/BOM exceeds output byte limit',output_empty=True,
                workspace_and_lock_cleanup=dict(locks=[],workspaces=[])), 'original Edge failure oracle required')
    pins={row['path']:row['sha256'] for row in reference['inputs']}
    oracle=str(PureWindowsPath(reference['controller_root'])/'scripts/hosted_picker/suite.py')
    require(proof['verifier']['sha256']==pins[oracle], 'verifier is not the qualified picker oracle')
    name=proof['verifier']['path']
    if os.name!='nt' and PureWindowsPath(name).is_absolute():
        name=subprocess.check_output(['wslpath','-u',name],text=True,timeout=4).strip()
    require(hashlib.sha256(Path(name).read_bytes()).hexdigest()==proof['verifier']['sha256'], 'picker verifier drift')
    return reference


def qualified_batch(binding, selected, profile, channel=None):
    """Bind completed qualification separately from a fresh attempt's admission.

    The reference configuration and its original preflight/independent receipts
    remain immutable. Only the explicit projection below is reusable across roots.
    """
    name = PureWindowsPath(binding['path']) if PureWindowsPath(binding['path']).is_absolute() else Path(binding['path'])
    require(name.is_absolute() and '..' not in name.parts, 'absolute receipt path required')
    definition = _local_binding(binding)
    frozen = check_qualified_batch(definition, selected, profile, channel)
    return dict(definition=binding, profile=profile, channel=channel,
                qualification=definition['tiny'], independent=definition['independent'],
                frozen_sha256=hashlib.sha256(_json_bytes(frozen)).hexdigest())


def check_qualified_batch(definition, selected, profile, channel):
    required = {'schema','profile','channel','configuration','preflight','tiny','independent','verifier','frozen'}
    extra = {'native': {'summary'}, 'small': {'supplement','release'}, 'actual-picker': {'failure'}}.get(profile,set())
    require(required <= set(definition) <= required|extra and
            definition['schema'] == 'chopper-frozen-batch-v1', 'versioned frozen batch definition required')
    require(definition['profile'] == profile and definition['channel'] == channel,
            'qualification profile/channel mismatch; select that profile qualification')
    reference = _local_binding(definition['configuration'])
    require(reference.get('execution_kind','qualification') == 'qualification',
            'batch admission requires a qualification receipt, not another batch chain')
    if os.name == 'nt':
        if profile == 'native':
            from .native_tiny import preflight as native_preflight
            native_preflight(Path(definition['configuration']['path']),reference,
                Path(definition['preflight']['path']),definition['preflight']['sha256'])
        else:
            preflight(definition['preflight'],definition['configuration']['path'],profile)
    pref = _local_binding(definition['preflight'])
    tiny = _local_binding(definition['tiny'])
    audit = _local_binding(definition['independent'])
    require(pref['schema'] == 'chopper-acceptance-preflight-v1' and
            all(pref.get(key) is False for key in ('workload_started','acceptance_window_started','scale_slot_consumed')) and
            pref['status'] == 'passed' and pref['profile'] == profile and
            pref['plan_sha256'] == definition['configuration']['sha256'],
            'qualification preflight/configuration mismatch; regenerate the definition')
    worker = _local_binding(dict(path=str((PureWindowsPath(definition['preflight']['path']) if PureWindowsPath(definition['preflight']['path']).is_absolute() else Path(definition['preflight']['path'])).with_name('worker-result.json')),
                             sha256=pref['worker_receipt_sha256']))
    require(all(worker[key] == pref[key] for key in
                ('schema','status','profile','host','plan_sha256','checker','bindings')),
            'qualification preflight parent/worker mismatch')
    if profile != 'actual-picker':
        require(tiny['passed'] is True and tiny['scale_acceptance'] is False and
                tiny['preflight'] == definition['preflight'], 'complete matching Tiny qualification required')
    if profile == 'actual-picker':
        require('failure' in definition and set(definition['failure'])=={'configuration','preflight','tiny','independent','verifier'},
                'both original picker success/failure proof chains required')
        picker_case(definition,channel)
        failure = picker_case(definition['failure'],channel)
        require(reference['case']=='success' and failure['case']=='failure' and
                reference['browser']==failure['browser'] and reference['browser_version']==failure['browser_version'] and
                pref['host']==_local_binding(definition['failure']['preflight'])['host'],
                'same-channel picker success/failure pair required')
    elif profile == 'native':
        require(channel is None and tiny['schema'] == 'native-tiny-qualification-v1' and tiny['evidence_kind'] == 'native-tiny' and
                tiny['scale_slots_consumed'] == 0 and
                tiny['plan_sha256'] == definition['configuration']['sha256'] and
                tiny['original_lock']['original_descriptor_closed'],
                'complete native Tiny/Original proof required')
        if reference['os'] == 'Linux':
            require(tiny['original_lock']['mechanism']=='flock-exclusive' and
                tiny['original_lock']['original_owner_lock_absent'] is True,'original Linux Tiny/Original proof required')
            if 'summary' in definition:
                summary = _local_binding(definition['summary'])
                root = Path(summary['namespace'])
                expected = {'tiny-plan.json':definition['configuration']['sha256'],
                    'preflight/result.json':definition['preflight']['sha256'],
                    'data/qualification-result.json':definition['tiny']['sha256'],
                    'after-exit-proof.json':definition['independent']['sha256']}
                require(summary['schema']=='native178-linux-tiny-summary-v1' and summary['passed'] is True and
                    summary['controller_exit']==summary['operator_exit']==summary['scale_slots']==0 and
                    summary['head']==reference['harness']['commit'] and summary['pins']==expected and
                    Path(definition['configuration']['path'])==root/'tiny-plan.json', 'matching original Linux Tiny summary required')
            else:
                require(audit.get('verifier_role',{}).get('sha256')==
                    reference['harness']['sha256']['scripts/scale_acceptance/native_tiny.py'],
                    'maintained Linux verifier identity or original Q8 summary required')
            require(audit['schema']=='native178-q3-after-exit-proof-v1' and
                audit['qualification_sha256']==definition['tiny']['sha256'] and
                audit['original_lock_stat']==tiny['original_lock']['stat'] and
                audit['original_owner_lock_absent'] is True and audit['other_locks_on_original_inode']==[] and
                audit['owned_pid_absent'] and all(v is True for v in audit['owned_pid_absent'].values()) and
                len(audit['phases'])==9, 'complete Linux independent cleanup proof required')
            for phase in audit['phases']:
                cgroup=phase['cgroup']
                require((cgroup.get('absent') is True and set(cgroup)=={'path','absent'}) or
                    (cgroup.get('same_identity') is True and cgroup.get('members') and
                     all(value=='' for value in cgroup['members'].values())), 'Linux cgroup cleanup proof incomplete')
                cleanup=_local_binding(dict(path=str(Path(phase['directory'])/'cleanup.json'),sha256=phase['cleanup_sha256']))
                require(cleanup['errors']==cleanup['cleanup_errors']==cleanup['remaining']==[] and
                    all(cleanup[key] is True for key in ('capture_writers_reaped','controller_eof','monitor_threads_joined')),
                    'Linux phase cleanup/reap proof incomplete')
            completion=_local_binding(dict(path=str(Path(reference['campaign'])/'Linux-tiny-completed.json'),
                                            sha256=audit['completion_sha256']))
            require(completion==dict(evidence_kind='native-tiny',passed=True,scale_acceptance=False,scale_slots_consumed=0,
                plan_sha256=definition['configuration']['sha256'],qualification_sha256=definition['tiny']['sha256']),
                'matching Linux Tiny completion required')
        else:
            require(tiny['original_lock']['capture_eof_joined'] is True and
                    audit['schema'] == 'native178-full-tiny-after-exit-v1' and
                    audit['qualification_passed'] is True and audit['setup_only'] is False and
                    audit['qualification_sha256'] == definition['tiny']['sha256'] and
                    audit['original_byte_zero_available'] and audit['independent_probe_released'] and
                    audit['administrative_recovery'] is False and len(audit['phases']) == 9 and
                    audit['verifier_role']['sha256'] == definition['verifier']['sha256'],
                    'matching independent native proof required')
    else:
        require(profile in PROFILES and tiny['schema'] == SCHEMA and tiny['profile'] == profile and
                tiny['channel'] == channel and tiny['qualifies_other_profiles'] is False and
                tiny['qualifies_other_channels'] is False, 'complete selected hosted profile required')
        require(audit['original_byte0_available'] and audit['probe_closed'] and audit['timer_joined'],
                'matching independent hosted proof required')
        supplemented = profile=='small' and 'supplement' in definition
        if supplemented:
            supplement=_local_binding(definition['supplement'])
            unresolved=[row for row in audit['processes'] if row['status']=='unavailable']
            positive=[row for row in audit['processes'] if row['status'] in ('absent','pid-reused-unrelated-original-ended')]
            require(audit['status']=='failed' and len(unresolved)==1 and unresolved[0]['native_open_error']==5 and
                len(positive)+1==len(audit['processes']) and supplement['status']=='passed' and
                supplement['prior_audit_sha256']==definition['independent']['sha256'] and
                supplement['target_pid']==unresolved[0]['pid'] and supplement['known_births']==unresolved[0]['previous_birth'] and
                supplement['prior_positive_process_facts']==len(positive) and
                supplement['combined_process_facts']==len(audit['processes']) and
                supplement['combined_audit_passed'] is True and supplement['timer_joined'] is True and
                supplement['held_observation']==dict(pid=unresolved[0]['pid'],previous_birth=unresolved[0]['previous_birth'],
                    native_open_error=87,status='absent'), 'matching exact Edge SMALL audit supplement required')
        else:
            require(audit['status']=='passed-after-exit','matching independent hosted proof required')
        if profile == 'browser-scale':
            require(audit['qualification_passed'] is True and audit['qualification_receipt'] == definition['tiny'],
                    'matching independent BrowserScale Tiny required')
        else:
            require(tiny['details']['full_cold_guard_required'] is True and
                    tiny['details']['controller_result']['passed'] is True and
                    tiny['details']['reservation_release']['passed'] is True and
                    tiny['details']['reservation_release']['released_after_supervision'] is True,
                    'complete fifteen-contract SMALL proof required')
            release_path = str((PureWindowsPath(definition['tiny']['path']) if PureWindowsPath(definition['tiny']['path']).is_absolute() else Path(definition['tiny']['path'])).with_name('reservation-released.json'))
            if supplemented:
                source = PureWindowsPath(definition['independent']['path'])
                prepared = _local_binding(dict(path=str(source.parent.parent/'packet.json'),sha256=audit['packet_sha256']))
                require(PureWindowsPath(prepared['paths']['config'])==PureWindowsPath(definition['configuration']['path']),
                        'supplemented audit original configuration mismatch')
                require('release' in definition and PureWindowsPath(definition['release']['path'])==PureWindowsPath(release_path),
                        'original supplemented SMALL release binding required')
                current_release = _local_binding(definition['release'])
            else:
                pins = [row for row in audit['source_receipts'] if row['path'] == release_path]
                require(len(pins)==1,'SMALL original release pin missing')
                current_release = _local_binding(pins[0])
            require(current_release == tiny['details']['reservation_release'],
                    'SMALL independent/release qualification mismatch')
    actual_host = selected['host'] if 'host' in selected else (host() if os.name == 'nt' else pref['host'])
    reported_host=pref['host'] if profile=='actual-picker' else tiny['host']
    require(all(reported_host[key] == value and actual_host[key] == value for key,value in pref['host'].items()),
            'qualification host drift; requalify on the selected host')
    verifier = definition['verifier']
    if profile == 'browser-scale' or (profile == 'native' and reference['os']=='Linux'):
        oracle = ('scripts/scale_acceptance/native_tiny.py'
                  if profile=='native' and 'summary' not in definition else 'scripts/scale_acceptance/verify.py')
        require(verifier['sha256']==reference['harness']['sha256'][oracle],
                'verifier is not the qualified independent oracle')
    elif profile == 'small':
        names={row['git_path']:row['path'] for row in reference['harness_source']}
        pins={row['path']:row['sha256'] for row in reference['inputs']}
        require(verifier['sha256']==pins[names['scripts/browser-small-runner.py']],
                'verifier is not the qualified SMALL assertion owner')
    verifier_path = verifier['path']
    if os.name != 'nt' and PureWindowsPath(verifier_path).is_absolute():
        verifier_path = subprocess.check_output(['wslpath','-u',verifier_path],text=True,timeout=4).strip()
    require(hashlib.sha256(Path(verifier_path).read_bytes()).hexdigest() == verifier['sha256'],
            'qualification verifier drift; select the original verifier or requalify')
    comparison = selected
    if profile == 'browser-scale' and selected['mode'] == 'scale':
        from .browser_scale_identity import validate_packet
        validate_packet(selected, preparation=True)
        require(reference['mode'] == 'qualify', 'Large requires original Tiny qualification')
        # #104 selects exactly the existing D/G 1 GB recipes. These workload
        # dimensions are intentional; every product/runner/verifier/tool/host/
        # storage-policy byte remains compared against the qualified Tiny.
        comparison = dict(selected, **{key:reference[key] for key in ('mode','shape','fixture')})
        comparison.pop('borrowed_input', None)
        if 'borrowed_input' in reference:comparison['borrowed_input'] = reference['borrowed_input']
    before, after = batch_projection(reference, profile), batch_projection(comparison, profile)
    if profile=='actual-picker':
        expected = {'success':before,'failure':batch_projection(failure,profile)}
        require(definition['frozen']==expected,'batch definition picker projections differ from qualification')
        require(selected['case'] in expected,'picker case is unqualified; qualify the affected case first')
        before=expected[selected['case']]
    else:
        require(definition['frozen'] == before, 'batch definition projection differs from original qualification')
    changed = [key for key in before if before[key] != after[key]]
    if changed:
        def digest(value):return hashlib.sha256(_json_bytes(value)).hexdigest()
        drift = {key:dict(expected_sha256=digest(before[key]),observed_sha256=digest(after[key])) for key in changed}
        raise ValueError('frozen batch drift in '+','.join(changed)+'; regenerate and requalify the affected profile; '+
                         json.dumps(drift,sort_keys=True))
    return after


def batch_projection(selected, profile):
    """Roots/clocks/attempt names vary; execution bodies, policy and tools do not."""
    if profile == 'native':
        def source(group):
            return {key:group[key] for key in ('sha256','git_blobs') if key in group}
        return dict(product=dict(commit=selected['product']['commit'],tree=selected['product']['tree'],files=source(selected['product'])), harness=source(selected['harness']),
            dependencies=[source(group) for group in selected['dependencies']],
            package={key:selected[key]['sha256'] for key in ('package','executable','package_receipt','build_proof','selected639_lineage')},
            tools=dict(python=selected['python'], tools=selected['tools']), host=selected['host'],
            policy=dict(features=selected['features'],limits=selected['limits']))
    if profile == 'browser-scale':
        # The compiler records an entry hash containing the selected absolute
        # roots. Validate that derivation before comparing the remaining body;
        # all execution bytes and semantic provenance still freeze exactly.
        paths = PureWindowsPath if PureWindowsPath(selected['harness']['root']).is_absolute() else Path
        root, product = paths(selected['harness']['root']), paths(selected['product']['root'])
        harness = dict(selected['harness']['sha256'])
        name = selected['bundle_provenance']
        provenance = _local_binding(dict(path=str(root/name),sha256=harness[name]))
        quote = lambda value: json.dumps(str(value),ensure_ascii=False)
        entry = ('import '+quote(product/'ui/src/app.ts')+';\n'
            'import {browserApi, executionHistory} from '+quote(product/'ui/src/browser/client.ts')+';\n'
            'import {installPageAdapter} from '+quote(root/'scripts/scale_acceptance/browser-page.mjs')+';\n'
            'installPageAdapter(browserApi, () => executionHistory);')
        require(provenance['entry_sha256']==hashlib.sha256(entry.encode()).hexdigest(),
                'bridge entry does not match the exact owning roots; regenerate and requalify')
        require(provenance['bundle_sha256']==harness[selected['bundle']], 'bridge provenance/bundle mismatch')
        del harness[name]
        return dict(product=dict(source=selected['source'],files=selected['product']['sha256']),
            harness=harness,bridge_provenance={key:value for key,value in provenance.items() if key!='entry_sha256'},
            assets=selected['assets']['sha256'],package=selected['package'],
            evidence=selected['evidence']['sha256'],tools={key:selected[key] for key in
                ('browser','python','node','git','toolchains','external_runtime')},
            host=selected['host'],channel=selected['channel'],browser_version=selected['browser_version'],
            policy=dict(features=selected['features'],fixture=selected['fixture'],shape=selected['shape'],mode=selected['mode'],storage=selected['storage'],build_receipts=selected['build_receipts']),
            borrowed_input=selected.get('borrowed_input'))
    if profile == 'actual-picker':
        pins = {row['path']:row['sha256'] for row in selected['inputs']}
        controller = PureWindowsPath(selected['controller_root'])
        source = _local_binding(selected['source_selection'])
        product_root = PureWindowsPath(source['root'])
        def names(root):
            return {PureWindowsPath(name).relative_to(root).as_posix():value for name,value in pins.items()
                    if PureWindowsPath(name).is_relative_to(root)}
        runtime = {}
        for directory in selected['runtime_roots']:
            root=PureWindowsPath(directory)
            role=('source:'+root.relative_to(product_root).as_posix()) if root.is_relative_to(product_root) else str(root)
            runtime[role]=names(root)
        job_binding = dict(path=selected['documents']['job.json'],sha256=pins[selected['documents']['job.json']])
        recipe = _local_binding(job_binding)
        recipe = dict(recipe,input='@input',output='@output',resources=dict(recipe['resources'],temp_dir=None))
        return dict(product=selected['product'],controller=names(controller/'scripts'),
            product_source=names(product_root),runtime=runtime,case=selected['case'],
            tools={key:selected[key] for key in ('python','node','browser','browser_version','toolchains')},
            channel=selected['channel'],input=selected['input'],recipe=recipe,
            policy=dict(seconds=selected['seconds'],input_cap_bytes=selected['input_cap_bytes']))
    require(profile == 'small', 'unsupported frozen batch profile')
    pins = {row['path']:row['sha256'] for row in selected['inputs']}
    roles = {}
    for role in ('product_source','harness_source'):
        roles[role] = {row['git_path']:pins[row['path']] for row in selected[role]}
    root = PureWindowsPath(selected['root'])
    roles['assets'] = {PureWindowsPath(name).relative_to(root).as_posix():pins[name]
                       for name in selected['product_assets']}
    tools = {key:dict(path=selected[key],sha256=pins[selected[key]]) for key in ('python','node','browser','zstd_dll') if key in selected}
    return dict(source=roles,tools=tools,preparation=selected['preparation'],
        package={PureWindowsPath(name).name:pins[name] for name in [selected['package_receipt'],*selected['package_zips']]},
        channel=selected['channel'],browser_version=selected['browser_version'],commands=selected['commands'],limits=selected['limits'])


def receipt(profile, channel, preflight_binding, *, passed, details):
    require(profile in PROFILES and channel in ('chrome', 'msedge'), 'installed hosted profile required')
    return dict(schema=SCHEMA, profile=profile, channel=channel, host=host(),
                passed=passed, preflight=preflight_binding, scale_acceptance=False,
                qualifies_other_profiles=False, qualifies_other_channels=False, details=details)


PACKET_SCHEMA = 'chopper-hosted-preparation-packet-v1'


def preparation_paths(prefix):
    """One native namespace owns every generated path; callers cannot copy stale roots."""
    value = PureWindowsPath(prefix)
    require(value.is_absolute() and value.drive.upper() == 'C:' and '..' not in value.parts
            and value.parent == PureWindowsPath('C:/') and value.name not in ('', '.', '..'),
            'explicit top-level C: preparation namespace required')
    require(all(c.isascii() and (c.isalnum() or c in '-_') for c in value.name),
            'simple preparation namespace required')
    source = value.with_name(value.name + '-source')
    metadata = value.with_name(value.name + '-preparation')
    owned = value.with_name(value.name + '-runtime')
    return dict(source=str(source), root=str(source / 'checkout'), metadata=str(metadata),
                owned_root=str(owned), config=str(metadata / 'candidate.json'),
                origin=str(metadata / 'origin.json'), request=str(metadata / 'request.json'),
                preflight=str(metadata / 'preflight'), plan=str(source / 'plan.json'),
                denial=str(metadata / 'safe-denial.json'),packet=str(metadata / 'packet.json'),
                after_exit=str(metadata / 'after-exit'))


def native_path(value):
    """Translate local artifact pins through the maintained WSL converter, once."""
    candidate = PureWindowsPath(str(value))
    if not candidate.is_absolute():
        require(os.name != 'nt' and Path(value).is_absolute(), 'absolute local/native artifact path required')
        candidate = PureWindowsPath(subprocess.check_output(['wslpath', '-w', str(value)], text=True).strip())
    require(candidate.is_absolute() and candidate.drive and candidate.root
            and '..' not in candidate.parts, 'native drive/share artifact path required')
    return str(candidate)


def selected_source_projection(repository, product, harness, payload, target, checker_sources):
    """Derive bodies from selected Git roles and data from a pinned build inventory.

    The payload is a build/dependency inventory, never a candidate/attempt template.
    All maintained scripts come from HARNESS except files required by PRODUCT's
    build provenance. Nothing copies Python generators or outputs from evidence.
    """
    repository = Path(repository).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repository), *args], timeout=30)
    def names(commit, *paths):
        return git('ls-tree', '-rz', '--name-only', commit, '--', *paths).decode().split('\0')[:-1]
    require(git('rev-parse', 'HEAD').decode().strip() == harness, 'selected harness HEAD mismatch')
    require(not git('status', '--porcelain', '--untracked-files=no').strip(), 'clean harness source required')
    product_files = names(product, 'crates', 'vendor', '.cargo', 'Cargo.toml', 'Cargo.lock',
                          'ui/src', 'ui/public', 'ui/index.html', 'ui/style.css',
                          'ui/package.json', 'ui/package-lock.json', 'scripts/build-browser.mjs')
    harness_files = names(harness, 'scripts', 'ui/tests/resource-contract-tests.ts',
                          'ui/tests/resource-contract-worker.ts')
    require(product_files and harness_files, 'complete selected Git roles required')
    product_set = set(product_files)
    harness_files = [name for name in harness_files if name not in product_set]
    required = {Path(path).resolve().relative_to(repository).as_posix() for path in checker_sources}
    require(required <= set(harness_files), 'selected checker closure missing from harness Git tree')
    rows = {}
    origin = PureWindowsPath(payload['native_root'])
    for entry in payload['files']:
        relative = PureWindowsPath(entry['relative'])
        require(not relative.is_absolute() and '..' not in relative.parts and relative.parts,
                'payload member traversal denied')
        name = relative.as_posix()
        if name == '.git':
            continue  # Historical build inventory pointer; always generate fresh dual-role Git.
        require(name not in rows and '.git' not in relative.parts, 'duplicate/Git payload member denied')
        require(type(entry['bytes']) is int and 0 <= entry['bytes'] <= 16*1024**2,
                'payload member memory bound')
        require(isinstance(entry['sha256'], str) and len(entry['sha256']) == 64
                and all(c in '0123456789abcdef' for c in entry['sha256']), 'payload digest required')
        rows[name] = dict(relative=name, source=str(origin / relative),
                          sha256=entry['sha256'], bytes=entry['bytes'], role='frozen-build-dependency')
    # Every actual current checker file must itself equal its selected Git body.
    for path in checker_sources:
        name = Path(path).resolve().relative_to(repository).as_posix()
        require(Path(path).read_bytes() == git('show', harness + ':' + name), 'checker source differs from Git: '+name)
    for role, commit, selected in [('product', product, product_files), ('harness', harness, harness_files)]:
        for name in selected:
            body = git('show', commit + ':' + name)
            require(len(body) <= 16*1024**2, 'Git member memory bound')
            digest = hashlib.sha256(body).hexdigest()
            previous = rows.get(name)
            selected = dict(relative=name, sha256=digest, bytes=len(body), role=role,
                            git_commit=commit, git_path=name)
            if previous is not None and previous['sha256'] == digest and previous['bytes'] == len(body):
                selected['source'] = previous['source']
            else:
                selected['inline'] = base64.b64encode(body).decode('ascii')
            rows[name] = selected
    require(required <= set(rows), 'incomplete projected checker closure')
    require({name for name in product_files if name.startswith('ui/src/')} ==
            {name for name in rows if name.startswith('ui/src/')}, 'product UI membership mismatch')
    return dict(root=native_path(target), product_commit=product, harness_commit=harness,
                files=[rows[name] for name in sorted(rows)],
                product_source=product_files, harness_source=harness_files,
                required_checker_sources=sorted(required))


def browser_scale_host_bindings(observed):
    """Canonicalize only newly derived declarations; retain the bound host receipt."""
    value=json.loads(json.dumps(observed));all_pins={}
    for section in (value,value['preparation']):
        pins={};sizes={}
        for row in section['inputs']:
            path=native_path(row['path']);digest=row['sha256']
            require(all_pins.setdefault(path,digest)==digest,'conflicting canonical runtime pin')
            pins[path]=dict(row,path=path)
        for path,size in section['input_sizes'].items():
            path=native_path(path)
            require(type(size)is int and size>=0 and sizes.setdefault(path,size)==size,'conflicting canonical runtime size')
        section['inputs']=[pins[name]for name in sorted(pins)];section['input_sizes']=sizes
        directories={}
        for directory,members in section['input_directories'].items():
            directory=native_path(directory);names=sorted({native_path(name)for name in members})
            require(directories.setdefault(directory,names)==names,'conflicting canonical directory membership')
            require(all(name in pins for name in names),'canonical runtime member lacks pin')
        section['input_directories']=directories
        for row in section['tools'].values():row['path']=native_path(row['path'])
    value['git_exec_path']=native_path(value['git_exec_path'])
    if 'zstd_dll'in value:value['zstd_dll']=native_path(value['zstd_dll'])
    return value


def browser_scale_projection(repository, product, harness, payload, checker):
    """Separate clean Git roles plus the exact borrowed build/dependency bodies."""
    from .browser_scale_identity import PRODUCT_INPUTS, HARNESS_INPUTS, ASSETS
    repository=Path(repository).resolve()
    def git(*args):return subprocess.check_output(['git','-C',str(repository),*args],timeout=30)
    require(git('rev-parse','HEAD').decode().strip()==harness and not
            git('status','--porcelain','--untracked-files=no').strip(),'clean selected harness required')
    maps={};role_bytes={}
    for role,commit,roots in [('product',product,PRODUCT_INPUTS),('harness',harness,{'scripts'})]:
        names=git('ls-tree','-rz','--name-only',commit,'--',*sorted(roots)).decode().split('\0')[:-1]
        require(names and len(names)==len(set(names)),'complete unique Git role')
        maps[role]={};role_bytes[role]=0
        for name in names:
            raw=git('show',commit+':'+name);maps[role][name]=hashlib.sha256(raw).hexdigest();role_bytes[role]+=len(raw)
    required={Path(p).resolve().relative_to(repository).as_posix() for p in checker.checker_sources()}
    require(required<=maps['harness'].keys(),'complete selected checker closure required')
    for name in required:
        require(hashlib.sha256((repository/name).read_bytes()).hexdigest()==maps['harness'][name],
                'selected checker Git body mismatch: '+name)
    dependencies=[];assets=[];seen=set()
    for row in payload['files']:
        name=PureWindowsPath(row['relative']).as_posix();parts=PureWindowsPath(name)
        require(not parts.is_absolute() and '..'not in parts.parts,'payload destination traversal')
        if not(name.startswith('ui/node_modules/') or name in {'ui/dist/'+n for n in ASSETS}):continue
        require(name not in seen and re.fullmatch('[0-9a-f]{64}',row['sha256']) and type(row['bytes'])is int and 0<=row['bytes']<=16*1024**2,
                'unique bounded dependency body required')
        seen.add(name)
        item=dict(relative=name,source=str(PureWindowsPath(payload['native_root'])/parts),
                  sha256=row['sha256'],bytes=row['bytes'])
        (dependencies if name.startswith('ui/node_modules/') else assets).append(item)
    require({r['relative'].removeprefix('ui/dist/') for r in assets}==set(ASSETS),'exact seven production assets')
    require(all(any(r['relative'].startswith(name+'/') for r in dependencies)
                for name in HARNESS_INPUTS if name.startswith('ui/node_modules/')),'complete build dependencies')
    return dict(product=maps['product'],harness=maps['harness'],git_bytes=role_bytes,dependencies=dependencies,assets=assets,
        product_inputs=sorted(PRODUCT_INPUTS),harness_inputs=sorted(HARNESS_INPUTS),
        product_tree=git('rev-parse',product+'^{tree}').decode().strip(),
        harness_tree=git('rev-parse',harness+'^{tree}').decode().strip())


SMALL_PREPARATION_CAMPAIGN_BYTES = 16*1024**3
SMALL_PREPARATION = dict(seconds=180, read_bytes=2*1024**3, visits=2000000,
                         capture_bytes=65536, storage_bytes=512*1024**2)


def _local_binding(binding):
    """Read existing native receipts from WSL without changing their native role."""
    value = str(binding['path'])
    if os.name != 'nt' and PureWindowsPath(value).is_absolute():
        value = subprocess.check_output(['wslpath', '-u', value], text=True).strip()
    return bound_json(dict(path=str(Path(value).absolute()), sha256=binding['sha256']))


def _disjoint_native_roots(values):
    roots = [PureWindowsPath(value) for value in values]
    require(all(p.is_absolute() and p.drive.upper() == 'C:' and '..' not in p.parts for p in roots),
            'canonical explicit C: owned roots required')
    require(len(set(roots)) == len(roots) and all(a == b or not a.is_relative_to(b)
            for a in roots for b in roots), 'overlapping/duplicate owned roots')
    return [str(p) for p in roots]


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()


# Planning margins from actual complete phases; original phase/channel limits stay fixed.
BROWSER_SCALE_FORECAST = {
    'D': dict(seconds=600, cleanup_margin_seconds=120,
        basis='planning: twice actual complete Chrome D284.991s, rounded to600s plus120s cleanup; not an Edge performance claim'),
    'G': dict(seconds=480, cleanup_margin_seconds=120,
        basis='planning: twice Chrome G original phases plus actual extraction/verify/guards/indie, approximately213s, rounded to480s plus120s cleanup; not an Edge performance claim'),
}


def _window(value, now=None, *, seconds=7920):
    now = time.time() if now is None else now
    require(value['schema'] == 'chopper-unattended-continuation-v1'
            and value['non_time_allowances_renewed'] is False, 'continuation authority required')
    cutoff = datetime.datetime.fromisoformat(value['launch_cutoff_utc']).timestamp()
    deadline = datetime.datetime.fromisoformat(value['deadline_utc']).timestamp()
    require(now < cutoff and now + seconds < deadline, 'preparation/run/cleanup forecast cannot fit frozen window')
    return dict(launch_cutoff=cutoff,deadline=deadline)


def retained_packet_roots(packet, *, fresh=False):
    """Closed immutable inventories, independently of their storage-ledger role."""
    value = packet.get('retained_after_ledger')
    if value is None:
        return {}
    partition = packet['origin']['metadata']['storage_priming']
    require(set(value)=={'schema','base_ledger_sha256','roots'}
            and value['schema']=='chopper-hosted-retained-roots-v1'
            and value['base_ledger_sha256']==partition['ledger']['sha256'], 'retained root ledger binding')
    require(type(value['roots']) is list and value['roots'], 'nonempty retained root declarations')
    inventories = {}
    pins = {row['path']:row['sha256'] for row in packet['configuration']['inputs']}
    for row in value['roots']:
        require(set(row)=={'root','inputs'}, 'retained root declaration')
        root = _disjoint_native_roots([row['root']])[0]
        require(root not in inventories and row['inputs'], 'unique nonempty retained root required')
        names = [entry['path'] for entry in row['inputs']]
        require(len(names)==len(set(names)) and all(PureWindowsPath(name).is_relative_to(PureWindowsPath(root))
            and PureWindowsPath(name)!=PureWindowsPath(root) and '..' not in PureWindowsPath(name).parts for name in names),
            'retained root file membership')
        require(all(set(entry)=={'path','sha256','bytes'} and type(entry['bytes']) is int and 0<=entry['bytes']<=16*1024**2 for entry in row['inputs']), 'retained file read forecast')
        require(all(pins.get(entry['path'])==entry['sha256'] for entry in row['inputs']), 'retained root pins absent/conflicting')
        inventories[root] = sorted(names)
    _disjoint_native_roots(inventories)
    covered = set(map(PureWindowsPath, partition['covered_roots']))
    require(all(root in partition['covered_roots'] for root in inventories if PureWindowsPath(root) in covered),
            'covered inventory root spelling mismatch')
    extra = {root: names for root,names in inventories.items() if PureWindowsPath(root) not in covered}
    _disjoint_native_roots([*partition['covered_roots'], *extra,
        packet['paths']['source'], packet['paths']['metadata'],
        *([] if packet.get('profile')=='browser-scale' else [packet['paths']['owned_root']])])
    return extra if fresh else inventories


def browser_scale_paths(namespace, *, mode='qualify'):
    require(mode in ('qualify','scale'), 'explicit browser scale mode required')
    paths=preparation_paths(namespace)
    source=PureWindowsPath(paths['source']);root=source/'harness';metadata=PureWindowsPath(paths['metadata'])
    attempt=root/'scratch'/('tiny' if mode=='qualify' else 'scale')
    paths.update(root=str(root),product=str(source/'product'),assets=str(source/'assets'),
        owned_root=str(attempt),config=str(root/'scratch'/'frozen.json'),
        plan=str(attempt/'plan.json'),policy=str(attempt/'policy.json'),
        approval=str(metadata/'approval.json'),reservation=str(metadata/'reservation.json'),claims=str(metadata/'claims'))
    return paths


def browser_scale_slots(cells):
    """Derive the four future cell directories from declarative namespaces."""
    require(type(cells) is list and len(cells)==4,'four selected Large cells required')
    slots=[];roots=[]
    for cell in cells:
        require(set(cell)=={'plan_id','shape','channel','namespace'} and
            re.fullmatch('[a-zA-Z0-9_-]{1,80}',cell['plan_id']),'exact declarative Large cell required')
        paths=browser_scale_paths(cell['namespace'],mode='scale')
        slots.append(dict(plan_id=cell['plan_id'],shape=cell['shape'],channel=cell['channel'],directory=paths['owned_root']))
        roots.extend(paths[key] for key in ('source','metadata'))
    require({(row['channel'],row['shape']) for row in slots}==
        {(channel,shape) for channel in ('chrome','msedge') for shape in ('D','G')} and
        len({row['plan_id'] for row in slots})==4,'four unique selected Large cells required')
    _disjoint_native_roots(roots)
    return slots


def browser_scale_time_inputs(binding, *, history=None):
    """The explicit Edge-only time amendment uses the existing proof closure."""
    value=_local_binding(binding)
    require(set(value)=={'schema','original_reservation','authority','history','chrome','prior_edge_scale_seconds'} and
        value['schema']=='chopper-browser-edge-time-continuation-v1' and
        type(value['prior_edge_scale_seconds'])is int and value['prior_edge_scale_seconds']==0,
        'only the original unstarted Edge scale pair may continue')
    require(set(value['chrome'])=={'D','G'},'both consumed Chrome proofs required')
    pins=[binding,value['original_reservation'],value['authority']]
    for retained in [value['history'],*([history]if history is not None else [])]:
        pins += [retained[key]for key in ('configuration','origin','ledger')]
        context=retained['ledger'].get('recovery_context')
        if context:
            pins += [context['packet'],context['after_exit']]
            recovery=_local_binding(context['packet'])
            if 'recovery'in recovery:pins.append(recovery['recovery'])
    for row in value['chrome'].values():
        require(set(row)=={'consumed','independent'},'Chrome claim and independent proof required')
        pins += [row['consumed'],row['independent']]
    for row in pins:
        path=PureWindowsPath(row['path'])
        require(path.is_absolute() and path.drive and '..'not in path.parts and
            re.fullmatch('[0-9a-f]{64}',row['sha256']),'native exact continuation proof pin required')
    return pins


def browser_scale_time_context(binding, *, partition=None, history=None):
    """No new family, identity, elapsed credit or storage pool is created."""
    pins=browser_scale_time_inputs(binding,history=history);value=_local_binding(binding)
    old=_local_binding(value['original_reservation']);authority=_local_binding(value['authority'])
    require(authority['old_reservation_sha256']==value['original_reservation']['sha256'] and
        authority['non_time_allowances_renewed'] is False and authority['publication_authorized'] is False,
        'time-only owner authority must bind the unchanged original reservation')
    require(old['version']==1 and old['parent_scheduled'] is True and len(old['slots'])==4 and
        {(r['channel'],r['shape'])for r in old['slots']}=={(c,s)for c in ('chrome','msedge')for s in ('D','G')},
        'same original four-cell family required')
    original=old['channels']['msedge'];old_stop=datetime.datetime.fromisoformat(authority['old_channel_stop'].replace('Z','+00:00')).timestamp()
    require(abs(original['deadline_unix']-old_stop)<.001 and
        0<original['deadline_unix']-original['start_unix']<=21600,'original Edge clock changed')
    end=datetime.datetime.fromisoformat(authority['overall_deadline'].replace('Z','+00:00')).timestamp()
    cutoff=datetime.datetime.fromisoformat(authority['overall_launch_cutoff'].replace('Z','+00:00')).timestamp()
    require(cutoff<end,'current authority timing')
    ledger,covered=retained_storage_ledger(value['history'])
    require(any(PureWindowsPath(old['claims_root']).is_relative_to(PureWindowsPath(root)) and
        PureWindowsPath(native_path(value['original_reservation']['path'])).is_relative_to(PureWindowsPath(root))
        for root in covered),'original campaign owner missing from retained debt')
    if partition is not None:
        require(history is not None,'authoritative latest continuation history required')
        latest,latest_roots=retained_storage_ledger(history)
        require(latest['cumulative_owned_bytes']==partition['ledger']['cumulative_owned_bytes'] and
            latest_roots==partition['covered_roots'] and partition['ledger']['sha256']==history['ledger']['sha256'] and
            PureWindowsPath(partition['ledger']['path'])==PureWindowsPath(native_path(history['ledger']['path'])),
            'latest producer ledger/history binding mismatch')
        require(latest['cumulative_owned_bytes']>=ledger['cumulative_owned_bytes'] and
            set(map(PureWindowsPath,covered))<=set(map(PureWindowsPath,latest_roots)),
            'continuation cannot refund debt or omit baseline roots')
    claims=PureWindowsPath(old['claims_root'])
    for shape,row in value['chrome'].items():
        slot=next(s for s in old['slots'] if s['channel']=='chrome' and s['shape']==shape)
        require(PureWindowsPath(native_path(row['consumed']['path']))==claims/(slot['plan_id']+'.consumed'),
            'Chrome consumed claim family/ID mismatch')
        require(type(_local_binding(row['consumed']))in(int,float) and _local_binding(row['consumed'])>0,
            'permanent Chrome consumed claim required')
        audit=_local_binding(row['independent'])
        require(audit['status']=='passed-after-exit' and audit.get('channel')=='chrome' and audit.get('shape')==shape and all(audit.get(k)is True for k in
            ('original_byte0_available','probe_closed','timer_joined')) and
            (audit.get('profile')=='browser-scale' and audit.get('scale_cell_passed')is True and audit.get('campaign_active_retirement',{}).get('consumed')==row['consumed'] if shape=='D' else
             audit.get('operation')==RECOVERY_OPERATION and audit.get('recovery_passed')is True and audit.get('consumed_claim')==row['consumed']),
            'accepted Chrome independent/claim chain required')
    return value,old,end,cutoff,pins


def browser_scale_time_reservation(binding, reservation):
    value,old,end,cutoff,_=browser_scale_time_context(binding)
    require(set(reservation)==set(old)|{'time_continuation'} and reservation['time_continuation']==binding,
        'exact time-only reservation lineage required')
    for key in old:
        if key not in ('channels','qualifications'):require(reservation[key]==old[key],'original family/slots/claims changed: '+key)
    require(reservation['channels']['chrome']==old['channels']['chrome'] and
        set(reservation['channels'])==set(old['channels']),'Chrome clock or channel membership changed')
    channel=reservation['channels']['msedge'];start,stop=channel['start_unix'],channel['deadline_unix']
    require(type(start)in(int,float) and type(stop)in(int,float) and
        start>=old['channels']['msedge']['start_unix'] and start<cutoff and
        0<stop-start<=21600-value['prior_edge_scale_seconds'] and stop<=end-120,
        'fresh Edge window exceeds remaining six-hour/overall time')
    previous=old['qualifications'];rows=reservation['qualifications']
    require(rows[:-1]==previous and len(rows)==len(previous)+1 and rows[-1]['channel']=='msedge' and
        rows[-1]['shape']=='D' and set(rows[-1])=={'plan_id','shape','channel','directory'} and
        all(rows[-1]['plan_id']!=r['plan_id'] and rows[-1]['directory']!=r['directory'] for r in old['slots']+previous),
        'one fresh Edge Tiny identity must retain prior qualification history')
    return value,old


def browser_scale_time_available(binding, *, plan_id=None, initial=False):
    """Live preclaim checks; static/audit consumers never pretend claims vanished."""
    _,old,_,_,_=browser_scale_time_context(binding)
    name=old['claims_root']
    if os.name!='nt' and PureWindowsPath(name).is_absolute():name=subprocess.check_output(['wslpath','-u',name],text=True).strip()
    claims=Path(name)
    require(claims.is_dir() and not claims.is_symlink() and not os.path.lexists(claims/'active.lock'),
        'original family has an active owner or missing claims root')
    edges=[r for r in old['slots'] if r['channel']=='msedge']
    selected=edges if initial else [r for r in edges if r['plan_id']==plan_id]
    require(selected and all(not os.path.lexists(claims/(r['plan_id']+'.consumed'))for r in selected),
        'only original unspent Edge IDs eligible')
    if initial:
        for row in edges:
            for root in (PureWindowsPath(row['directory']).parents[2],PureWindowsPath(row['directory']).parents[2].with_name(
                    PureWindowsPath(row['directory']).parents[2].name.removesuffix('-source')+'-preparation')):
                path=str(root)
                if os.name!='nt':path=subprocess.check_output(['wslpath','-u',path],text=True).strip()
                require(not os.path.lexists(path),'prior Edge scale namespace exists; no zero-elapsed assumption')
    return old


def browser_scale_make_reservation(packet, channel_start):
    """Emit the existing reservation body, or its narrow same-family Edge successor."""
    paths=packet['paths'];channel=packet['host_receipt']['channel']
    qualify=dict(plan_id=packet['selection']['plan_id'],shape='D',channel=channel,directory=paths['owned_root'])
    if 'time_continuation'in packet:
        binding=packet['time_continuation'];_,old,end,cutoff,_=browser_scale_time_context(binding,
            partition=packet['origin']['metadata']['storage_priming'],history=packet['origin']['metadata'].get('history'))
        require(channel=='msedge' and 'large_cells'not in packet and packet['timing']['deadline']==end and
            packet['selection']['approval_reference']==old['campaign'] and channel_start<cutoff,
            'Edge-only current-authority continuation required')
        browser_scale_time_available(binding,initial=True)
        reservation=json.loads(json.dumps(old));reservation['time_continuation']=binding
        reservation['channels']['msedge']=dict(start_unix=channel_start,deadline_unix=min(end-120,channel_start+21600))
        reservation['qualifications']=[*old['qualifications'],qualify]
        require(channel_start+1200<reservation['channels']['msedge']['deadline_unix'],'Tiny/cleanup cannot fit fresh Edge window')
        browser_scale_time_reservation(binding,reservation);return reservation
    deadline=min(packet['timing']['deadline']-120,channel_start+21600)
    require(channel_start+1200<deadline,'complete Tiny journey/cleanup cannot fit channel')
    slots=browser_scale_slots(packet['large_cells'])if'large_cells'in packet else []
    channels=('chrome','msedge')if slots else(channel,)
    return dict(version=1,parent_scheduled=True,campaign=packet['selection']['approval_reference'],slots=slots,
        qualifications=[qualify],claims_root=paths['claims'],channels={c:dict(start_unix=channel_start,deadline_unix=deadline)for c in channels})


def browser_scale_campaign(binding):
    """The shared schedule must originate in an actually qualified Tiny."""
    definition=_local_binding(binding);reference=_local_binding(definition['configuration'])
    require(reference['mode']=='qualify','campaign origin must be Tiny')
    qualified_batch(binding,reference,'browser-scale',reference['channel'])
    return reference


def browser_scale_reservation(packet, value, *, now=None):
    """Use the owning schedule predicate before dispatch and materialization."""
    from .browser_scale_guard import schedule_declaration
    selection=packet['selection'];paths=packet['paths']
    if 'time_continuation'in value:
        require(packet.get('time_continuation')==value['time_continuation'] and packet['host_receipt']['channel']=='msedge','only continued Edge cells eligible')
        browser_scale_time_reservation(value['time_continuation'],value)
    selected=dict(mode='scale',plan_id=selection['plan_id'],shape=packet['shape'],channel=packet['host_receipt']['channel'])
    deadline=schedule_declaration(selected,PureWindowsPath(paths['owned_root']),value,
        time.time() if now is None else now,path_type=PureWindowsPath)
    require(value['campaign']==selection['approval_reference'] and len(value['slots'])==4 and
        {(row['channel'],row['shape']) for row in value['slots']}==
        {(channel,shape) for channel in ('chrome','msedge') for shape in ('D','G')},
        'one shared four-cell Large campaign required')
    claims=PureWindowsPath(value['claims_root']);canonical=PureWindowsPath(packet['large_reservation']['path'])
    partition=packet['origin']['metadata']['storage_priming']
    owners=[PureWindowsPath(root)for root in [*partition['covered_roots'],*partition['fresh_roots']]]
    if 'time_continuation'in value:
        predecessor=[PureWindowsPath(value['qualifications'][-1]['directory']).parents[2],canonical.parent]
        previous=next(row for row in value['slots']if row['channel']=='msedge'and row['shape']=='D')
        claim=str(claims/(previous['plan_id']+'.consumed'))
        if os.name!='nt':claim=subprocess.check_output(['wslpath','-u',claim],text=True).strip()
        if packet['shape']=='G' and os.path.lexists(claim):
            source=PureWindowsPath(previous['directory']).parents[2]
            predecessor += [source,source.with_name(source.name.removesuffix('-source')+'-preparation')]
        require(all(any(path.is_relative_to(root)for root in owners)for path in (claims,canonical,*predecessor)),
            'continued original claims or completed predecessor missing from storage union')
    else:
        require(any(claims.is_relative_to(root) and canonical.is_relative_to(root)for root in owners),
            'Large claim owner absent from storage union')
    cell_roots=[]
    for row in value['slots']:
        target=PureWindowsPath(row['directory'])
        require(set(row)=={'plan_id','shape','channel','directory'} and len(target.parents)>=3,
            'exact Large campaign cell required')
        source=target.parents[2]
        namespace=source.with_name(source.name.removesuffix('-source'))
        expected=browser_scale_paths(str(namespace),mode='scale')
        cell_roots.extend(expected[key] for key in ('source','metadata'))
        require(target==PureWindowsPath(expected['owned_root']) and all(
            not path.is_relative_to(PureWindowsPath(expected[key])) and
            not PureWindowsPath(expected[key]).is_relative_to(path)
            for path in (claims,canonical) for key in ('source','metadata')), 'Large claims/canonical owner overlaps cell')
    _disjoint_native_roots(cell_roots)
    return deadline


def browser_scale_packet_declarations(packet, checker):
    """Validate the selected two clean roots and exact maintained profile launches."""
    require(packet['schema']==PACKET_SCHEMA and packet['profile']=='browser-scale','BrowserScale packet schema')
    execution_selection(packet)
    mode=packet.get('mode','qualify');shape=packet.get('shape','D')
    from .browser_scale_identity import tiny_fixture, scale_fixture
    require((mode=='qualify' and shape=='D' and packet['coverage']=='tiny-D' and packet['fixture']==tiny_fixture('D')) or
        (mode=='scale' and packet['coverage']=='scale-'+shape and packet['fixture']==scale_fixture(shape) and
         packet.get('execution_kind')=='batch' and 'large_reservation' in packet), 'exact selected browser workload required')
    if 'borrowed_input' in packet:
        from .browser_scale_identity import tiny_fixture
        borrowed=packet['borrowed_input']
        require(packet['fixture']==tiny_fixture('D') and borrowed['bytes']==packet['fixture']['bytes'] and
                borrowed['sha256']==packet['fixture']['sha256'],'borrowed Tiny declaration mismatch')
        covered=packet['origin']['metadata']['storage_priming']['covered_roots']
        require(PureWindowsPath(borrowed['owner_root']) in map(PureWindowsPath,covered),
                'borrowed input owner missing from retained storage union')
        check_borrowed_input(borrowed,observe=borrowed['stat'] is None)
    paths=packet['paths'];source=PureWindowsPath(paths['source']);metadata=PureWindowsPath(paths['metadata'])
    base=preparation_paths(str(source.with_name(source.name.removesuffix('-source'))))
    require(source.name.endswith('-source') and paths==browser_scale_paths(str(source.with_name(source.name.removesuffix('-source'))),mode=mode),
            'generated BrowserScale namespace drift')
    require(PureWindowsPath(paths['root'])==source/'harness' and PureWindowsPath(paths['product'])==source/'product'
        and PureWindowsPath(paths['owned_root'])==source/'harness'/'scratch'/('tiny' if mode=='qualify' else 'scale'),
        'separate clean product/harness roots')
    outputs=[PureWindowsPath(paths[name]) for name in ('config','request','plan','policy','approval','reservation','packet')]
    require(len(outputs)==len(set(outputs)) and all(p.is_relative_to(source) or p.is_relative_to(metadata) for p in outputs),
            'generated output collision/escape')
    pins=[packet['bundle'],*packet['preparation_code'],*packet['tools'].values()]
    pins += [packet[key] for key in ('frozen_batch','campaign_qualification','large_reservation','peer') if key in packet]
    if 'borrowed_input' in packet:pins += [packet['borrowed_input'],packet['borrowed_input']['qualification']]
    if 'time_continuation'in packet:pins += browser_scale_time_inputs(packet['time_continuation'],history=packet['origin']['metadata'].get('history'))
    for pin in pins:
        path=PureWindowsPath(pin['path'])
        require(path.is_absolute() and path.drive and '..'not in path.parts and re.fullmatch('[0-9a-f]{64}',pin['sha256']),
                'absolute native exact pin required')
        require(path not in outputs,'input/output collision')
    require(type(packet['selection']['origin_port'])is int and 1024<=packet['selection']['origin_port']<=65535,
            'selected integer loopback port required')
    projection=packet['projection']
    for group in ('product','harness'):
        require(projection[group] and all(not PureWindowsPath(n).is_absolute() and '..'not in PureWindowsPath(n).parts
            and re.fullmatch('[0-9a-f]{64}',h) for n,h in projection[group].items()),'closed clean Git role')
    required={Path(p).resolve().relative_to(Path(checker.__file__).resolve().parent.parent).as_posix()
              for p in checker.checker_sources()}
    require(required<=projection['harness'].keys(),'complete selected BrowserScale checker closure')
    require([row['phase'] for row in packet['commands']]==['materialize','preflight','qualify','after-exit'],'complete BrowserScale phases')
    prefix=[packet['tools']['python']['path'],'-E','-s','-B']
    require(all(row['argv'][:4]==prefix for row in packet['commands']),'isolated exact native launch')
    materialize=packet['commands'][0]['argv']
    require(materialize[4:]==[native_path(checker.__file__),'materialize',packet['source_packet'],paths['metadata'],
        '--sha256','$ACTUAL_PACKET_SHA'],'exact maintained materialization')
    qualify=packet['commands'][2]['argv']
    require(qualify[4:]==[str(PureWindowsPath(paths['root'])/'scripts/scale-acceptance.py'),'browser-scale-run',paths['plan'],
        paths['policy'],'--approval',paths['approval'],'--preflight',str(PureWindowsPath(paths['preflight'])/'result.json'),
        '--preflight-sha256','$ACTUAL_PREFLIGHT_SHA'],'exact owning BrowserScale execution')
    independent=PureWindowsPath(packet['commands'][3]['argv'][4])
    require(independent==PureWindowsPath(native_path(checker.__file__)) and any(
        PureWindowsPath(row['path'])==independent for row in packet['preparation_code']),'pinned independent entrypoint')
    retained=retained_packet_roots(packet,fresh=True)
    partition=packet['origin']['metadata']['storage_priming']
    require(partition['fresh_roots']==[*retained,paths['source'],paths['metadata']],'fresh retained-root closure')
    _disjoint_native_roots([*partition['covered_roots'],*partition['fresh_roots']])
    if 'time_continuation'in packet:
        _,old,end,_,_=browser_scale_time_context(packet['time_continuation'],partition=partition,history=packet['origin']['metadata'].get('history'))
        require(packet['host_receipt']['channel']=='msedge' and packet['timing']['deadline']==end and 'large_cells'not in packet,
            'Edge continuation must retain authority/debt; never create another campaign')
    if 'large_cells' in packet:
        require(mode=='qualify','only Tiny creates the canonical campaign')
        slots=browser_scale_slots(packet['large_cells'])
        _disjoint_native_roots([paths['source'],paths['metadata'],*[str(PureWindowsPath(row['directory']).parents[2]) for row in slots]])
    if mode=='scale':
        require(browser_scale_campaign(packet['campaign_qualification'])['reservation']==packet['large_reservation'],
            'canonical reservation must be the actual qualified Tiny reservation')
        require(packet['execution_forecast']==BROWSER_SCALE_FORECAST[packet['shape']],'reviewed Large execution forecast required')
        reservation=_local_binding(packet['large_reservation'])
        # Static validation must remain usable for independent cleanup after a
        # deadline failure; materialization and launch check the actual clock.
        browser_scale_reservation(packet,reservation,
            now=reservation['channels'][packet['host_receipt']['channel']]['start_unix'])
    return dict(native_pins=len(pins),product_files=len(projection['product']),harness_files=len(projection['harness']))


RECOVERY_OPERATION = 'completed-export-recovery'


def recovery_paths(root):
    root=PureWindowsPath(root)
    return {name:str(root/relative) for name,relative in dict(owned_root='.',metadata='preparation',
        definition='recovery.json',plan='plan.json',policy='policy.json',approval='approval.json',
        request='request.json',preflight='preparation/preflight',after_exit='preparation/after-exit',
        packet='preparation/packet.json').items()}


def recovery_transport(packet, checker, *, executable=None):
    """WSL launch metadata is never a command executed by the native consumer."""
    dispatch=packet['dispatch'];executable=sys.executable if executable is None else executable
    checkout=PureWindowsPath(dispatch['checkout'])
    require(checkout.is_absolute() and '..' not in checkout.parts and
        re.fullmatch('[0-9a-f]{40}',dispatch['commit']), 'exact native checkout/commit required')
    producer=not PureWindowsPath(executable).is_absolute()
    for row in packet['commands']:
        outer=row['dispatch_argv']
        require(type(outer)is list and len(outer)>=4 and all(type(value)is str and value and
            not any(c in value for c in ('\x00','\n','\r')) for value in outer), 'literal WSL transport argv required')
        require(outer[1]=='-B' and all(PurePosixPath(outer[index]).is_absolute() and
            '..' not in PurePosixPath(outer[index]).parts for index in (0,2)) and
            PurePosixPath(outer[2]).name=='windows-native.py', 'absolute POSIX transport prefix required')
        if producer:
            repository=Path(checker.__file__).resolve().parent.parent
            require(outer[:3]==[executable,'-B',str(repository/'scripts/windows-native.py')],
                'exact WSL producer prefix required')
        require(outer[3:]==['--checkout',dispatch['checkout'],'--expect-commit',dispatch['commit'],
            'python',*row['argv'][1:]], 'exact selected native transport tail required')


def recovery_packet_declarations(packet,checker):
    from .browser_scale_guard import recovery_request,recovery_documents,recovery_code
    require(packet['schema']==PACKET_SCHEMA and packet['profile']=='browser-scale' and
        packet['operation']==RECOVERY_OPERATION,'explicit recovery packet required')
    r,p,_=recovery_request(packet['recovery'])
    require(packet['paths']==recovery_paths(r['root']),'derived recovery paths')
    require(packet['definition']==r and packet['recovery_code']==recovery_code(),'exact recovery definition/code')
    plan,policy=recovery_documents(packet['recovery'],p,path_type=PureWindowsPath)
    require(packet['manifest']==plan and packet['policy']==policy,'owning recovery documents required')
    current=[dict(path=native_path(path),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())
        for path in checker.checker_sources()]
    require(packet['preparation_code']==current,'complete current checker pin required')
    ledger=_local_binding(packet['history_ledger'])
    require(packet['storage_priming']==dict(covered_roots=ledger['covered_roots'],fresh_roots=[r['root']],
        ledger=dict(packet['history_ledger'],cumulative_owned_bytes=ledger['cumulative_owned_bytes'])),
        'exact retained charged floor and fresh recovery root')
    _disjoint_native_roots([*ledger['covered_roots'],r['root']])
    immutable=[row['path'] for row in [*current,*r['recovery_code']]]
    immutable += [r[key]['path'] for key in ('frozen_packet','public_state','browser_receipt','independent',
        'release','consumed_claim','closed_profile_observation')]
    root=PureWindowsPath(r['root'])
    require(all(not PureWindowsPath(path).is_relative_to(root) for path in immutable),'immutable recovery input/output overlap')
    paths=packet['paths'];prefix=[p['python']['path'],'-E','-s','-B'];entry=native_path(checker.__file__)
    expected=[dict(phase='materialize',argv=prefix+[entry,'materialize',packet['source_packet'],paths['metadata'],'--sha256','$ACTUAL_PACKET_SHA']),
        dict(phase='preflight',argv=prefix+[entry,'preflight',paths['request'],paths['preflight']]),
        dict(phase='recover',argv=prefix+[str(PureWindowsPath(entry).parent/'scale-acceptance.py'),'browser-scale-run',
            paths['plan'],paths['policy'],'--approval',paths['approval'],'--preflight',str(PureWindowsPath(paths['preflight'])/'result.json'),
            '--preflight-sha256','$ACTUAL_PREFLIGHT_SHA']),
        dict(phase='after-exit',argv=prefix+[entry,'after-exit',paths['packet'],paths['after_exit'],'--sha256','$ACTUAL_PACKET_SHA'])]
    require([{key:row[key] for key in ('phase','argv')} for row in packet['commands']]==expected,'exact maintained recovery commands')
    dispatch=packet['dispatch']
    require(dispatch['environment']==dict(CHOPPER_WINDOWS_GIT=p['git']['path'],CHOPPER_WINDOWS_PYTHON=p['python']['path']),
        'selected dispatch tools required')
    recovery_transport(packet,checker)
    require(packet['product_runs']==0 and packet['new_claims']==0 and packet['generated_input_bytes']==0,'recovery cannot start or claim a Run')
    return dict(commands=4,recovery_code=len(r['recovery_code']),preparation_code=len(current))


def prepare_recovery_packet(selection,destination,checker):
    """Derive extraction-only recovery from linked actual failed-run records."""
    from .browser_scale_guard import recovery_code,recovery_request,recovery_documents
    destination=Path(destination);repository=Path(checker.__file__).resolve().parent.parent
    checker.check_evidence_destination(destination,[repository]);require(not destination.exists(),'fresh packet output required')
    def binding(value):return dict(path=native_path(value['path']),sha256=value['sha256'])
    old=_local_binding(selection['original_packet']);pref=_local_binding(selection['original_preflight'])
    require(old['profile']=='browser-scale' and old['mode']=='scale' and old['shape']=='G','selected old G packet required')
    require(pref['status']=='passed' and pref['profile']=='browser-scale' and pref['host']==old['host'],'actual original preflight required')
    frozen=dict(path=old['paths']['config'],sha256=pref['plan_sha256']);p=_local_binding(frozen)
    require(p['profile']==str(PureWindowsPath(old['paths']['owned_root'])/'work/profile'),'old packet/profile linkage')
    status=_local_binding(selection['original_status']);original=PureWindowsPath(p['profile']).parent.parent
    require(PureWindowsPath(native_path(selection['original_preflight']['path']))==PureWindowsPath(old['paths']['preflight'])/'result.json' and
        PureWindowsPath(native_path(selection['original_status']['path']))==original/'batch/status.json',
        'original preflight/status path binding')
    browser_path=str(original/'work/browser-receipt.json')
    artifacts=[attempt['artifacts'] for attempt in status['attempts'] if attempt['id']=='browser-scale']
    matches=[row for group in artifacts for row in group.values() if isinstance(row,dict) and PureWindowsPath(row.get('resolved',''))==PureWindowsPath(browser_path)]
    require(len(artifacts)==1 and len(matches)==1,'actual failed browser artifact required')
    browser=dict(path=browser_path,sha256=matches[0]['sha256'])
    indie=_local_binding(selection['independent']);release_path=str(original/'batch/reservation-released.json')
    releases=[row for row in indie['source_receipts'] if PureWindowsPath(row['path'])==PureWindowsPath(release_path)]
    require(len(releases)==1,'unique actual failed release binding')
    timing=_window(_local_binding(selection['window']),seconds=5520)
    require(time.time()<selection['deadline_unix'] and selection['start_unix']<timing['launch_cutoff'] and
        selection['deadline_unix']+120<timing['deadline'],'fresh recovery operation/cleanup fit')
    root=PureWindowsPath(selection['namespace']);paths=recovery_paths(root)
    observed=_local_binding(selection['host']);ledger=_local_binding(selection['history_ledger'])
    require(ledger['cumulative_owned_bytes']>=old['origin']['metadata']['storage_priming']['ledger']['cumulative_owned_bytes'],
        'retained historical floor cannot decrease')
    r=dict(schema='browser-scale-export-recovery-v1',root=str(root),profile=str(root/'profile'),
        profile_copy_receipt=str(root/'profile-copy.json'),start_unix=selection['start_unix'],deadline_unix=selection['deadline_unix'],
        frozen_packet=frozen,public_state=binding(selection['public_state']),browser_receipt=browser,
        independent=binding(selection['independent']),release=binding(releases[0]),consumed_claim=binding(selection['consumed_claim']),
        closed_profile_observation=binding(selection['host']),recovery_code=recovery_code(),
        limits=dict(read_bytes=16*1024**3,profile_bytes=2*1024**3,visits=2000000,metadata_bytes=16*1024**2,
            growth_bytes=4*1024**3,copy_seconds=1800,extract_seconds=1800,verify_seconds=1800))
    directory=next((members for directory,members in observed['input_directories'].items()
        if PureWindowsPath(directory)==PureWindowsPath(p['profile'])),None)
    require(directory is not None,'complete actual closed profile observation required')
    sizes={PureWindowsPath(name):size for name,size in observed['input_sizes'].items()}
    profile_bytes=sum(sizes[PureWindowsPath(name)] for name in directory)
    forecast=dict(profile_files=len(directory),profile_bytes=profile_bytes,
        read_bytes=3*profile_bytes+2*p['fixture']['bytes']+64*1024**2,
        growth_bytes=profile_bytes+2*p['fixture']['bytes']+64*1024**2)
    require(profile_bytes<=r['limits']['profile_bytes'] and forecast['read_bytes']<=r['limits']['read_bytes'] and
        forecast['growth_bytes']<r['limits']['growth_bytes'],'observed recovery forecast exceeds allowance')
    destination.mkdir();definition=destination/'recovery.json';definition.write_bytes(_json_bytes(r))
    ref=dict(path=native_path(definition),sha256=hashlib.sha256(definition.read_bytes()).hexdigest())
    recovery_request(ref)
    manifest,policy=recovery_documents(ref,p,path_type=PureWindowsPath)
    code=[dict(path=native_path(path),sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest()) for path in checker.checker_sources()]
    entry=native_path(checker.__file__);prefix=[p['python']['path'],'-E','-s','-B']
    commands=[dict(phase='materialize',argv=prefix+[entry,'materialize',native_path(destination/'packet.json'),paths['metadata'],'--sha256','$ACTUAL_PACKET_SHA']),
        dict(phase='preflight',argv=prefix+[entry,'preflight',paths['request'],paths['preflight']]),
        dict(phase='recover',argv=prefix+[str(PureWindowsPath(entry).parent/'scale-acceptance.py'),'browser-scale-run',paths['plan'],paths['policy'],
            '--approval',paths['approval'],'--preflight',str(PureWindowsPath(paths['preflight'])/'result.json'),'--preflight-sha256','$ACTUAL_PREFLIGHT_SHA']),
        dict(phase='after-exit',argv=prefix+[entry,'after-exit',paths['packet'],paths['after_exit'],'--sha256','$ACTUAL_PACKET_SHA'])]
    dispatch=dict(selection['dispatch']);dispatch['checkout']=native_path(dispatch['checkout'])
    dispatch['environment']=dict(CHOPPER_WINDOWS_GIT=p['git']['path'],CHOPPER_WINDOWS_PYTHON=p['python']['path'])
    for command in commands:
        command['dispatch_argv']=[sys.executable,'-B',str(repository/'scripts/windows-native.py'),'--checkout',dispatch['checkout'],
            '--expect-commit',dispatch['commit'],'python',*command['argv'][1:]]
    ledger_pin=binding(selection['history_ledger'])
    packet=dict(schema=PACKET_SCHEMA,profile='browser-scale',operation=RECOVERY_OPERATION,host=observed['host'],
        source_packet=native_path(destination/'packet.json'),source_commit=subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip(),
        recovery=ref,definition=r,recovery_code=r['recovery_code'],paths=paths,manifest=manifest,policy=policy,
        preparation_code=code,history_ledger=ledger_pin,
        storage_priming=dict(covered_roots=ledger['covered_roots'],fresh_roots=[str(root)],ledger=dict(ledger_pin,cumulative_owned_bytes=ledger['cumulative_owned_bytes'])),
        provenance={key:binding(selection[key]) for key in ('original_packet','original_preflight','original_status','public_state','independent','consumed_claim','host')},
        window=binding(selection['window']),timing=timing,forecast=forecast,dispatch=dispatch,commands=commands,
        approval_reference=selection['approval_reference'],product_runs=0,new_claims=0,generated_input_bytes=0,
        limits=dict(SMALL_PREPARATION,read_bytes=2*1024**3),preflight_limits=dict(SMALL_PREPARATION,read_bytes=4*1024**3,storage_bytes=5*1024**2),
        qualification=False)
    recovery_packet_declarations(packet,checker)
    target=destination/'packet.json';target.write_bytes(_json_bytes(packet))
    return dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),qualification=False,commands=4)


def materialize_recovery(packet,destination,expected_sha256,checker,*,timer=None):
    from .browser_scale_guard import recovery_request
    from .browser_scale_identity import ScaleIdentity
    recovery_packet_declarations(packet,checker)
    r,p,_=recovery_request(packet['recovery']);paths=packet['paths'];root=Path(r['root']);metadata=Path(destination)
    require(metadata==Path(paths['metadata']) and not root.exists(),'fresh recovery root required')
    _window(bound_json(packet['window']),seconds=5520)
    require(time.time()<r['deadline_unix']-120,'recovery launch window exhausted')
    small=checker.load('browser-small-runner');runner=small.runner;runner.contain_session()
    budget=checker.Budget(packet['limits'],metadata,mutation_roots=[root]);budget.read_bytes=64*1024**2;budget.visits=8192
    if timer is None:timer=threading.Timer(180,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',operation=RECOVERY_OPERATION,original_acquired=False,workload_started=False,product_runs=0,new_claims=0)
    try:
        budget.install()
        for row in packet['preparation_code']+packet['recovery_code']:_observed_file(row['path'],budget,row['sha256'])
        storage=small.primed_storage(packet['storage_priming'],[]);baseline=storage.total
        require(baseline+r['limits']['growth_bytes']<small.LIMITS['stop_owned_bytes'],'global retained floor plus recovery allowance')
        require(shutil.disk_usage('C:/').free-r['limits']['growth_bytes']>=128*1024**3,'prospective physical free floor')
        started=time.monotonic();identity=ScaleIdentity(dict(packet=r['frozen_packet']['path'],sha256=r['frozen_packet']['sha256']),preparation=True)
        identity.require_windows();cold=time.monotonic()-started
        started=time.monotonic();identity.check();duration=time.monotonic()-started
        root.mkdir();metadata.mkdir();storage.roots.append(root)
        for name,value in [('definition',r),('plan',packet['manifest']),('policy',packet['policy'])]:Path(paths[name]).write_bytes(_json_bytes(value))
        approval=dict(version=1,decision='approved',contract=packet['manifest']['contract'],plan_id=p['plan_id'],shape=p['shape'],channel=p['channel'],
            plan_sha256=hashlib.sha256(_json_bytes(packet['manifest'])).hexdigest(),policy_sha256=hashlib.sha256(_json_bytes(packet['policy'])).hexdigest(),
            packet_sha256=r['frozen_packet']['sha256'],reservation_sha256=p['reservation']['sha256'],
            approved_by='parent-reviewed maintained recovery packet',approval_reference=packet['approval_reference'])
        Path(paths['approval']).write_bytes(_json_bytes(approval))
        request=dict(schema=checker.SCHEMA,profile='browser-scale',host_os='Windows',plan=r['frozen_packet']['path'],
            plan_sha256=r['frozen_packet']['sha256'],limits=packet['preflight_limits'],recovery=packet['recovery'])
        Path(paths['request']).write_bytes(_json_bytes(request));Path(paths['packet']).write_bytes(_json_bytes(packet))
        total=storage.sample(mutable_roots=[root],deadline=budget.started+180)
        own=small.windows.query_job(runner._SESSION_JOB)
        require(own['kill_on_close'] and own['pids']==[os.getpid()],'cold owner-only Job required')
        result.update(status='passed',cold_identity_seconds=cold,full_metadata_check_seconds=duration,owned_bytes=total,
            retained_floor=baseline,job=own,observer=small.windows.process_identity(os.getpid()))
        return result
    except BaseException as error:result['error']=repr(error);raise
    finally:
        budget.active=False;timer.cancel();timer.join();result.update(timer_joined=not timer.is_alive(),usage=budget.usage())
        if metadata.is_dir():(metadata/'materialization-result.json').write_bytes(_json_bytes(result))


def recovery_after_exit(packet,destination,expected_sha256,checker,*,timer=None):
    """New extraction/oracle proof; the old failed receipt and consumed claim stay unchanged."""
    from .browser_scale_guard import recovery_request
    recovery_packet_declarations(packet,checker);r,p,_=recovery_request(packet['recovery'])
    paths=packet['paths'];destination=Path(destination)
    require(destination==Path(paths['after_exit']) and not destination.exists(),'fresh declared independent output')
    destination.mkdir();root=Path(r['root']);metadata=Path(paths['metadata'])
    budget=checker.Budget(dict(seconds=30,read_bytes=2*1024**3,visits=2000000,capture_bytes=65536,storage_bytes=1024**2),
        destination,mutation_roots=[destination,metadata/'storage-ledger.json'])
    if timer is None:timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',operation=RECOVERY_OPERATION,packet_sha256=expected_sha256,recovery_passed=False,product_runs=0,new_claims=0,generated_input_bytes=0)
    try:
        budget.install();small=checker.load('browser-small-runner')
        require(not (root/'batch/owner-retained.json').exists(),'retained owner blocks completion')
        pin=_observed_file(root/'batch/reservation-released.json',budget);release=bound_json(pin)
        require(release['operation']=='completed-export extraction only' and release['recovery']==packet['recovery']
            and release['product_runs']==0 and release['new_claims']==0,'exact extraction-only release required')
        require(release['cleanup']['original_release_safe'] and release['released_after_supervision'],'positive current release required')
        facts=current_process_facts([dict(process_identities=[dict(pid=release['pid'],created=release['created']),*release['cleanup']['processes']])])
        require(facts and all(row['created'] for row in facts),'current process births required')
        independent_observation(small.windows,facts,release,small.module('local-ci').host_lock_path(),budget.started+30,result,budget=budget)
        result.update(status='passed-after-exit',source_receipts=[pin],original_failed_run=r['browser_receipt'],original_independent=r['independent'],consumed_claim=r['consumed_claim'])
        if release['passed'] is True:
            verified_pin=_observed_file(root/'verified.json',budget);verified=bound_json(verified_pin,8*1024**2)
            extract_pin=_observed_file(root/'work/extraction-receipt.json',budget);extracted=bound_json(extract_pin)
            require(extracted['status']=='extracted; independent streaming verification pending' and not extracted['failures'] and
                extracted['product_run_count']==0 and extracted['new_scale_claims']==0
                and extracted['original_consumed_claim_unchanged'] is True,'completed OPFS extraction receipt required')
            require(extracted['definition_sha256']==packet['recovery']['sha256'],'matching recovery extraction required')
            browser_scale_evidence(p,p['fixture'],verified,extracted,bound_json(r['public_state']),recovery=True)
            result.update(recovery_passed=True,verified=verified_pin,extraction=extract_pin,channel=p['channel'],shape=p['shape'],fixture=p['fixture'])
        else:result['reason']='failed recovery; ownership proof only'
        storage=small.primed_storage(packet['storage_priming'],[]);storage.roots.append(root)
        total=storage.sample()+1024**2;require(total<small.LIMITS['stop_owned_bytes'],'final retained logical cap')
        (metadata/'storage-ledger.json').write_bytes(_json_bytes(dict(method=STORAGE_LEDGER_METHOD,cumulative_owned_bytes=total,
            covered_roots=[*packet['storage_priming']['covered_roots'],r['root']],unseen_transient_allocations='UNKNOWN; sampled logical union is not physical highwater')))
        result['cumulative_owned_bytes']=total;budget.check();return result
    except BaseException as error:result.update(status='failed',recovery_passed=False,error=repr(error));raise
    finally:
        budget.active=False;timer.cancel();timer.join();result.update(timer_joined=not timer.is_alive(),usage=budget.usage())
        (destination/'result.json').write_bytes(_json_bytes(result))


STORAGE_LEDGER_METHOD = 'sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny'


def retained_storage_ledger(history, *, declared=None):
    """Admit the complete matching pool, preserving its old roots and charged floor."""
    def read(binding):
        if declared is not None:
            require(any(row['path'] == native_path(binding['path']) and row['sha256'] == binding['sha256'] for row in declared),
                    'retained accounting receipt missing from input closure')
        return _local_binding(binding)
    old = read(history['configuration'])
    origin = read(history['origin'])
    require(any(e['path'] == old['retained_origin_manifest'] and e['sha256'] == history['origin']['sha256']
                for e in old['inputs']), 'prior generated configuration/origin mismatch')
    required = _disjoint_native_roots([old['owned_root'], *old['history_roots'], *origin['adopted_roots']])
    binding = history['ledger']; ledger = read(binding)
    floor = origin.get('metadata', {}).get('storage_priming', {}).get('ledger', {}).get('cumulative_owned_bytes', 0)
    require(type(floor) is int and floor >= 0 and type(ledger['cumulative_owned_bytes']) is int
            and ledger['cumulative_owned_bytes'] >= floor, 'retained historical floor cannot decrease')
    covered = _disjoint_native_roots(ledger.get('covered_roots', required))
    require(set(map(PureWindowsPath, required)) <= set(map(PureWindowsPath, covered)), 'prior owned roots missing from aggregate')
    if ledger.get('method') != STORAGE_LEDGER_METHOD:
        require('method' not in ledger and 'recovery_context' in binding, 'retained aggregate method mismatch')
        context = binding['recovery_context']
        packet = read(context['packet']); audit = read(context['after_exit'])
        require(packet['schema'] == PACKET_SCHEMA and packet['profile'] == 'browser-scale'
                and packet['operation'] == RECOVERY_OPERATION, 'exact recovery ledger context required')
        r = read(packet['recovery']); paths = recovery_paths(r['root'])
        require(packet['paths'] == paths and PureWindowsPath(native_path(binding['path'])) == PureWindowsPath(paths['metadata'])/'storage-ledger.json'
                and PureWindowsPath(native_path(context['after_exit']['path'])) == PureWindowsPath(paths['after_exit'])/'result.json',
                'recovery ledger/output binding mismatch')
        require(audit['status'] == 'passed-after-exit' and audit['operation'] == RECOVERY_OPERATION
                and audit['packet_sha256'] == context['packet']['sha256'] and audit['recovery_passed'] is True
                and all(audit.get(key) is True for key in ('original_byte0_available','probe_closed','timer_joined'))
                and audit['cumulative_owned_bytes'] == ledger['cumulative_owned_bytes'], 'positive bound recovery audit required')
        require(all(audit[key] == r[source] for key,source in (
            ('original_failed_run','browser_receipt'),('original_independent','independent'),('consumed_claim','consumed_claim'))),
            'recovery audit original operation mismatch')
        expected = _disjoint_native_roots([*packet['storage_priming']['covered_roots'], r['root']])
        require(covered == expected and ledger['cumulative_owned_bytes'] >= packet['storage_priming']['ledger']['cumulative_owned_bytes'],
                'recovery aggregate root/floor binding mismatch')
    elif 'covered_roots' not in ledger:
        require(PureWindowsPath(native_path(binding['path'])).parent == PureWindowsPath(old['owned_root']), 'legacy aggregate owner mismatch')
    return ledger, covered


def packet_declarations(packet, checker):
    """One executable check for every derived native root, pin and launch path."""
    if packet.get('operation')==RECOVERY_OPERATION:return recovery_packet_declarations(packet,checker)
    if packet.get('profile')=='browser-scale':return browser_scale_packet_declarations(packet,checker)
    require(packet['schema'] == PACKET_SCHEMA and packet['profile'] == 'small', 'packet schema/profile')
    execution_selection(packet['configuration'])
    paths = packet['paths']
    prefix = PureWindowsPath(paths['source'])
    require(prefix.name.endswith('-source'), 'source suffix')
    require(paths == preparation_paths(str(prefix.with_name(prefix.name[:-7]))), 'generated namespace drift')
    config, origin = packet['configuration'], packet['origin']
    require(config['root'] == paths['root'] and config['owned_root'] == paths['owned_root']
            and config['retained_origin_manifest'] == paths['origin'], 'configuration namespace drift')
    if 'overall_deadline_ms' in config:
        authority = _local_binding(packet['window'])
        deadline = datetime.datetime.fromisoformat(authority['deadline_utc']).timestamp()
        require(config['overall_deadline_ms'] == int(deadline*1000) == int(packet['timing']['deadline']*1000),
                'SMALL overall deadline must match frozen authority')
    partition = origin['metadata']['storage_priming']
    history = origin['metadata'].get('history')
    if history is not None:
        ledger, covered = retained_storage_ledger(history)
        require(covered == partition['covered_roots'] and ledger['cumulative_owned_bytes'] == partition['ledger']['cumulative_owned_bytes']
                and partition['ledger']['sha256'] == history['ledger']['sha256']
                and PureWindowsPath(partition['ledger']['path']) == PureWindowsPath(native_path(history['ledger']['path'])),
                'emitted storage partition/history mismatch')
    retained = retained_packet_roots(packet)
    require(partition['fresh_roots'] == [*retained_packet_roots(packet,fresh=True),paths['source'],paths['metadata'],paths['owned_root']], 'fresh root closure')
    require(all(root in config['input_directories'] for root in retained), 'retained inventory missing')
    _disjoint_native_roots([*partition['covered_roots'],*partition['fresh_roots']])
    pins = [packet['bundle'],*packet['preparation_code'],*packet['tools'].values(),*config['inputs']]
    for pin in pins:
        path = PureWindowsPath(pin['path'])
        require(path.is_absolute() and path.drive and '..' not in path.parts, 'native drive/share pin required: '+pin['path'])
        require(len(pin['sha256']) == 64 and all(c in '0123456789abcdef' for c in pin['sha256']), 'exact file digest required')
    rows = packet['projection']['files']
    names = [row['relative'] for row in rows]
    require(len({PureWindowsPath(name) for name in names}) == len(names), 'duplicate projected destination')
    for name in names:
        p = PureWindowsPath(name)
        require(not p.is_absolute() and not p.drive and '..' not in p.parts and p.parts[0] != '.git', 'invalid payload destination')
    required = {Path(p).resolve().relative_to(Path(checker.__file__).resolve().parent.parent).as_posix()
                for p in checker.checker_sources()}
    require(required <= set(names), 'complete selected checker source closure required')
    coverage=packet.get('coverage','full15')
    require(coverage in ('full15','first-command-control'),'unsupported packet coverage')
    require(config['commands']==checker.load('browser-small-runner').command_specs(first_only=coverage=='first-command-control'),
            'exact authoritative selected commands required')
    prefix = [packet['tools']['python']['path'],'-E','-s','-B']
    require(all(command['argv'][:4] == prefix for command in packet['commands']), 'exact isolated native launch mode')
    qualifier=next(command['argv'] for command in packet['commands'] if command['phase']=='qualify')
    require(('--first-command-control' in qualifier)==(coverage=='first-command-control'), 'coverage/qualify mode mismatch')
    independent=next(command['argv'] for command in packet['commands'] if command['phase']=='after-exit')
    entry=PureWindowsPath(independent[4])
    require(entry==PureWindowsPath(native_path(checker.__file__)) and any(
        PureWindowsPath(row['path'])==entry for row in packet['preparation_code']),
        'independent observer entrypoint/preparation pin mismatch')
    outputs = [PureWindowsPath(paths[name]) for name in ('config','origin','request','plan')]
    require(len(set(outputs)) == len(outputs), 'generated output collision')
    inputs = [PureWindowsPath(packet['bundle']['path']),*[PureWindowsPath(p['path']) for p in packet['preparation_code']]]
    require(not set(outputs) & set(inputs), 'input/output collision')
    inspect.signature(checker.probe).bind([], object(), 'clone', cwd=Path.cwd())
    return dict(native_pins=len(pins), projected_files=len(rows), commands=len(config['commands']))


def prepare_browser_scale_packet(selection, destination, checker):
    """Derive Tiny or one reserved 1 GB cell through the same preparation path."""
    from .browser_scale_identity import SOURCE, TREE, tiny_fixture, scale_fixture
    repository=Path(checker.__file__).resolve().parent.parent
    checker.check_evidence_destination(destination,[repository])
    require(not destination.exists(),'fresh packet output required')
    mode=selection.get('mode','qualify');shape=selection.get('shape','D')
    require(mode in ('qualify','scale') and (shape=='D' if mode=='qualify' else shape in ('D','G')),
        'bounded D Tiny or exact selected Large D/G required')
    timing=_window(_local_binding(selection['window']),seconds=1800 if mode=='qualify' else BROWSER_SCALE_FORECAST[shape]['seconds']+BROWSER_SCALE_FORECAST[shape]['cleanup_margin_seconds'])
    fixture=tiny_fixture('D',127) if mode=='qualify' else scale_fixture(shape)
    execution = execution_selection(selection)
    if 'frozen_batch' in execution:
        execution['frozen_batch']=dict(execution['frozen_batch'],path=native_path(execution['frozen_batch']['path']))
    if mode=='scale':
        require(execution.get('execution_kind')=='batch' and 'campaign_qualification' in selection,
            'Large requires actual qualified frozen batch and shared four-cell reservation')
        campaign_reference=browser_scale_campaign(selection['campaign_qualification'])
        require('large_reservation' not in selection,'canonical binding is derived from actual campaign qualification')
    borrowed = selection.get('borrowed_input')
    if borrowed:
        require(mode=='qualify','Large uses its separately reserved generation, not a borrowed Tiny input')
        check_borrowed_input(borrowed)
        require(borrowed['sha256'] == fixture['sha256'] and borrowed['bytes'] == fixture['bytes'], 'borrowed D fixture mismatch')
    if mode=='qualify':
        require(selection['retained_input_bytes']+(0 if borrowed else fixture['bytes'])<=1024**2,'cumulative original input cap')
    release=_local_binding(selection['release'])
    package=selection['hosted_package']
    require(PureWindowsPath(package).name==package and package.endswith('-hosted.zip') and package in release['packages'],
            'explicit selected hosted package required')
    require(release['release_source_commit']==SOURCE and release['release_source_tree']==TREE,'selected release source/tree')
    observed=_local_binding(selection['host'])
    time_binding=selection.get('time_continuation')
    if time_binding:
        require(mode=='qualify' and observed['channel']=='msedge' and 'large_cells'not in selection,'only fresh Edge Tiny may adopt a time continuation')
        browser_scale_time_context(time_binding)
    require(observed['status']=='passed' and observed['host']['os']=='Windows' and
            observed['channel']in('chrome','msedge'),'actual installed channel host receipt')
    relevance=host_implementation(observed,selection.get('host_producer_commit'),repository,checker)
    observed=browser_scale_host_bindings(observed)
    tools=observed['tools']
    for role,tool in tools.items():
        require(tool['signature']['status']==selection['tool_signature_status'][role],'tool signature status: '+role)
    paths=browser_scale_paths(selection['namespace'],mode=mode)
    source=PureWindowsPath(paths['source']);root=PureWindowsPath(paths['root']);metadata=PureWindowsPath(paths['metadata'])
    harness=subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip()
    payload=_local_binding(selection['payload']['manifest'])
    require(payload['selected_product']==SOURCE,'build payload product identity')
    payload=dict(payload,native_root=native_path(selection['payload']['native_root']))
    projection=browser_scale_projection(repository,SOURCE,harness,payload,checker)
    require(projection['product_tree']==TREE,'exact product tree')
    for row in projection['assets']:
        require(release['hosted'][PureWindowsPath(row['relative']).name]['sha256']==row['sha256'],'production asset pin')
    history=_local_binding(selection['history']['configuration']);origin=_local_binding(selection['history']['origin'])
    ledger=_local_binding(selection['history']['ledger'])
    require(type(ledger['cumulative_owned_bytes'])is int and ledger['cumulative_owned_bytes']>=0,'retained ledger floor')
    previous_roots=_disjoint_native_roots([history['owned_root'],*history['history_roots'],*origin['adopted_roots']])
    covered=_disjoint_native_roots(ledger.get('covered_roots',previous_roots))
    if borrowed:
        require(any(PureWindowsPath(borrowed['owner_root']) == PureWindowsPath(root) for root in covered),
                'borrowed input owner must remain in the retained storage union')
    require(set(previous_roots)<=set(covered),'latest floor omits historical covered roots')
    retained_after=_local_binding(selection['retained_after_ledger']) if 'retained_after_ledger'in selection else None
    retained_roots=_disjoint_native_roots([row['root'] for row in retained_after['roots']]) if retained_after else []
    extra=[root for root in retained_roots if PureWindowsPath(root) not in set(map(PureWindowsPath,covered))]
    _disjoint_native_roots([*covered,*extra,paths['source'],paths['metadata']])
    require(selection['retained_preparation_bytes']+SMALL_PREPARATION['storage_bytes']<SMALL_PREPARATION_CAMPAIGN_BYTES,'cumulative preparation cap')
    require(type(selection['origin_port'])is int and 1024<=selection['origin_port']<=65535,'selected loopback port')
    require(re.fullmatch('[a-zA-Z0-9_-]{1,80}',selection['plan_id']),'simple selected attempt identity')
    if mode=='scale':
        definition=_local_binding(execution['frozen_batch'])
        reference=_local_binding(definition['configuration'])
        qualified_batch(execution['frozen_batch'],reference,'browser-scale',observed['channel'])
        require(reference['mode']=='qualify' and reference['harness_source']['commit']==harness and
            all(reference[key]==tools[key] for key in ('browser','python','node','git')) and
            all(reference['host'][key]==value for key,value in observed['host'].items()),
            'Large requires the current complete Tiny harness/tools/host; requalify before staging')
    destination.mkdir()
    bundle=destination/'product-harness.bundle'
    subprocess.run(['git','-C',str(repository),'bundle','create',str(bundle),'HEAD',SOURCE],check=True,timeout=60)
    with tempfile.TemporaryDirectory(prefix='browser-scale-transport-') as control:
        subprocess.run(['git','-c','gc.auto=0','clone','--no-checkout','--quiet',str(bundle),control],check=True,timeout=30)
        for role,commit in [('product',SOURCE),('harness',harness)]:
            for name,digest in projection[role].items():
                raw=subprocess.check_output(['git','-C',control,'show',commit+':'+name],timeout=10)
                require(hashlib.sha256(raw).hexdigest()==digest,'transported '+role+' body: '+name)
    runtime_bytes=sum(observed['input_sizes'].values())+sum(observed['preparation']['input_sizes'].values())
    generated_bound=64*1024**2+2*bundle.stat().st_size
    source_bytes=sum(projection['git_bytes'].values())+sum(row['bytes'] for row in projection['dependencies']+projection['assets'])
    pref_read=((128*1024**2+2*(runtime_bytes+source_bytes+generated_bound)+1024**2-1)//1024**2)*1024**2
    sizes=dict(observed['input_sizes'],**observed['preparation']['input_sizes'])
    tool_bytes=sum(sizes[tool['path']]for tool in tools.values())
    package_bytes=release['artifact_receipt']['bytes']+release['packages'][package]['bytes']
    materialize_forecast=(96*1024**2+runtime_bytes+sum(observed['preparation']['input_sizes'].values())+
        tool_bytes+3*source_bytes+3*package_bytes)
    require(materialize_forecast<=SMALL_PREPARATION['read_bytes'],
            'metadata-derived materialization read forecast needs reviewed allowance: '+str(materialize_forecast))
    code=[dict(path=native_path(p),sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest()) for p in checker.checker_sources()]
    prefix=[tools['python']['path'],'-E','-s','-B'];entry=str(root/'scripts/scale-acceptance.py')
    commands=[dict(phase='materialize',argv=prefix+[native_path(checker.__file__),'materialize',native_path(destination/'packet.json'),
        paths['metadata'],'--sha256','$ACTUAL_PACKET_SHA']),dict(phase='preflight',argv=prefix+[str(root/'scripts/acceptance-preflight.py'),'preflight',paths['request'],paths['preflight']]),
        dict(phase='qualify',argv=prefix+[entry,'browser-scale-run',paths['plan'],paths['policy'],
            '--approval',paths['approval'],'--preflight',str(PureWindowsPath(paths['preflight'])/'result.json'),
            '--preflight-sha256','$ACTUAL_PREFLIGHT_SHA']),
        dict(phase='after-exit',argv=prefix+[native_path(checker.__file__),'after-exit',paths['packet'],paths['after_exit'],
            '--sha256','$ACTUAL_PACKET_SHA'])]
    packet=dict(schema=PACKET_SCHEMA,profile='browser-scale',coverage='tiny-D',source_commit=harness,
        source_packet=native_path(destination/'packet.json'),
        source_tree=projection['harness_tree'],paths=paths,host=observed['host'],tools=tools,host_receipt=observed,
        host_observation=dict(path=native_path(selection['host']['path']),sha256=selection['host']['sha256']),
        host_producer_relevance=relevance,release=release,projection=projection,fixture=fixture,
        selection=dict(plan_id=selection['plan_id'],origin_port=selection['origin_port'],
            packages=native_path(selection['packages']),hosted_package=package,approval_reference=selection['approval_reference']),
        window=dict(path=native_path(selection['window']['path']),sha256=selection['window']['sha256']),timing=timing,
        origin=dict(metadata=dict(storage_priming=dict(covered_roots=covered,fresh_roots=[*extra,paths['source'],paths['metadata']],
            ledger=dict(path=native_path(selection['history']['ledger']['path']),sha256=selection['history']['ledger']['sha256'],
                cumulative_owned_bytes=ledger['cumulative_owned_bytes'])))),
        bundle=dict(path=native_path(bundle),sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),bytes=bundle.stat().st_size),
        preparation_code=code,limits=SMALL_PREPARATION,preflight_limits=dict(SMALL_PREPARATION,read_bytes=pref_read,storage_bytes=5*1024**2),
        preparation_read_forecast=dict(runtime_bytes=runtime_bytes,source_bytes=source_bytes,generated_bound=generated_bound,
            materialization_read_bytes=materialize_forecast,preflight_read_bytes=pref_read),
        retained_preparation_bytes=selection['retained_preparation_bytes'],retained_input_bytes=selection['retained_input_bytes'],
        dispatch=selection['dispatch'],commands=commands,qualification=False,workload_started=False,scale_slot_consumed=False)
    if time_binding:packet['time_continuation']=dict(time_binding,path=native_path(time_binding['path']))
    if time_binding or mode=='scale' and 'time_continuation'in campaign_reference:
        packet['origin']['metadata']['history']=selection['history']
    if 'large_cells' in selection:
        require(mode=='qualify','only Tiny creates a future Large campaign')
        browser_scale_slots(selection['large_cells']);packet['large_cells']=selection['large_cells']
    if mode=='scale':
        packet.update(mode=mode,shape=shape,coverage='scale-'+shape,large_reservation=campaign_reference['reservation'],
            campaign_qualification=dict(selection['campaign_qualification'],path=native_path(selection['campaign_qualification']['path'])),execution_forecast=dict(BROWSER_SCALE_FORECAST[shape]))
        if 'peer' in selection:packet['peer']=dict(selection['peer'],path=native_path(selection['peer']['path']))
        if 'time_continuation'in campaign_reference:packet['time_continuation']=campaign_reference['time_continuation']
    packet.update(execution)
    if borrowed:packet['borrowed_input']=dict(borrowed,path=native_path(borrowed['path']),owner_root=native_path(borrowed['owner_root']),
        qualification=dict(borrowed['qualification'],path=native_path(borrowed['qualification']['path'])))
    if retained_after is not None:packet['retained_after_ledger']=retained_after
    packet['configuration']=dict(inputs=[dict(path=row['path'],sha256=row['sha256'])
        for group in (retained_after['roots'] if retained_after else []) for row in group['inputs']])
    packet['dispatch']['environment']=dict(CHOPPER_WINDOWS_GIT=tools['git']['path'],CHOPPER_WINDOWS_PYTHON=tools['python']['path'])
    packet['dispatch']['checkout']=native_path(packet['dispatch']['checkout'])
    for command in commands:
        command['dispatch_argv']=[sys.executable,'-B',str(repository/'scripts/windows-native.py'),'--checkout',packet['dispatch']['checkout'],
            '--expect-commit',packet['dispatch']['commit'],'python',*command['argv'][1:]]
    packet_declarations(packet,checker)
    path=destination/'packet.json';path.write_bytes(_json_bytes(packet))
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),qualification=False,commands=len(commands))


def prepare_packet(selection_path, destination, checker):
    """Generate the real SMALL preparation and launch declarations, without a clock.

    Inputs are selected release/build/host observations and retained ownership,
    not an existing attempt template or a Python program copied from evidence.
    """
    selection_path, destination = Path(selection_path).resolve(), Path(destination).resolve()
    require(selection_path.stat().st_size <= 1024**2, 'selection document memory bound')
    selection = json.loads(selection_path.read_bytes())
    require(selection['schema'] == 'chopper-hosted-packet-selection-v1','maintained hosted packet selection required')
    if selection.get('operation')==RECOVERY_OPERATION:return prepare_recovery_packet(selection,destination,checker)
    if selection['profile']=='browser-scale':return prepare_browser_scale_packet(selection,destination,checker)
    require(selection['schema'] == 'chopper-hosted-packet-selection-v1'
            and selection['profile'] == 'small', 'maintained SMALL packet selection required')
    execution = execution_selection(selection)
    repository = Path(checker.__file__).resolve().parent.parent
    protected = [repository, selection_path]
    checker.check_evidence_destination(destination, protected)
    require(not destination.exists(), 'fresh packet output required')
    paths = preparation_paths(selection['namespace'])
    continuation = _local_binding(selection['window'])
    timing = _window(continuation,seconds=900)
    release = _local_binding(selection['release'])
    small = checker.load('browser-small-runner')
    require(release['release_source_commit'] == small.PRODUCT
            and release['release_source_tree'] == small.PRODUCT_TREE,
            'selected release source/tree mismatch')
    payload = _local_binding(selection['payload']['manifest'])
    require(payload['selected_product'] == small.PRODUCT, 'build inventory product mismatch')
    payload = dict(payload, native_root=native_path(selection['payload']['native_root']))
    observed_host = _local_binding(selection['host'])
    require(observed_host['schema'] == 'chopper-hosted-host-v1' and observed_host['status']=='passed'
            and observed_host['host']['os'] == 'Windows'
            and observed_host['channel'] in ('chrome','msedge'), 'actual installed Windows host observation required')
    host_relevance=host_implementation(observed_host,selection.get('host_producer_commit'),repository,checker)
    tools = observed_host['tools']
    require(set(tools)=={'git','python','node','browser','powershell'}, 'complete selected tool roles required')
    for role,tool in tools.items():
        require(PureWindowsPath(tool['path']).is_absolute() and len(tool['sha256']) == 64,
                'concrete native tool pin required: '+role)
        require(tool['signature']['status'] == selection['tool_signature_status'][role],
                'observed tool signature status mismatch: '+role)
    prior = selection['history']['ledger']
    ledger, covered = retained_storage_ledger(selection['history'])
    retained_after = _local_binding(selection['retained_after_ledger']) if 'retained_after_ledger' in selection else None
    retained_roots = _disjoint_native_roots([row['root'] for row in retained_after['roots']]) if retained_after else []
    extra_roots = [root for root in retained_roots if PureWindowsPath(root) not in set(map(PureWindowsPath,covered))]
    fresh = [*extra_roots, paths['source'], paths['metadata'], paths['owned_root']]
    _disjoint_native_roots([*covered, *fresh])
    # Pure executable declaration checks use the SAME native overlap predicate.
    check_roots = [PureWindowsPath(p) for p in [paths['root'], paths['owned_root'], *covered]]
    checker.check_evidence_destination(PureWindowsPath(paths['preflight']), check_roots)
    inspect.signature(checker.probe).bind([], object(), 'clone', cwd=Path.cwd())
    harness = subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'], text=True).strip()
    projection = selected_source_projection(repository, small.PRODUCT, harness, payload, paths['root'], checker.checker_sources())
    source_rows = {row['relative']:row for row in projection['files']}
    for name, expected in release['hosted'].items():
        require(source_rows['ui/dist/'+name]['sha256'] == expected['sha256'], 'selected production asset mismatch: '+name)
    require(all(name in source_rows for name in ('ui/package.json','ui/package-lock.json')),
            'UI dependency manifests absent')
    require(any(name.startswith('ui/node_modules/playwright/') for name in source_rows)
            and any(name.startswith('ui/node_modules/playwright-core/') for name in source_rows), 'complete build dependency inventory required')
    runtime_pins = {}
    for row in observed_host['inputs']:
        previous = runtime_pins.setdefault(row['path'], row['sha256'])
        require(previous == row['sha256'], 'conflicting host runtime pin')
    cold_pins={row['path']:row['sha256'] for row in observed_host['preparation']['inputs']}
    for role, tool in tools.items():
        require({**runtime_pins,**cold_pins}.get(tool['path']) == tool['sha256'], 'host tool missing from runtime closure: '+role)
    for members in observed_host['input_directories'].values():
        require(all(name in runtime_pins for name in members), 'host inventory lacks exact file pins')
    root = PureWindowsPath(paths['root'])
    pins = dict(runtime_pins)
    for group in retained_after['roots'] if retained_after else []:
        for row in group['inputs']:
            require(pins.setdefault(row['path'],row['sha256'])==row['sha256'], 'retained root pin conflict')
    for row in projection['files']:pins[str(root/PureWindowsPath(row['relative']))] = row['sha256']
    packages = PureWindowsPath(native_path(selection['packages']))
    receipt = packages/release['artifact_receipt']['name']
    pins[str(receipt)] = release['artifact_receipt']['sha256']
    for name, value in release['packages'].items():pins[str(packages/name)] = value['sha256']
    history = {key:dict(value,path=native_path(value['path'])) for key,value in selection['history'].items()}
    if 'recovery_context' in prior:
        history['ledger']['recovery_context'] = {key:dict(value,path=native_path(value['path']))
            for key,value in prior['recovery_context'].items()}
    history_pins = list(history.values())
    if 'recovery_context' in prior:
        context = prior['recovery_context']
        recovery_packet = _local_binding(context['packet'])
        history_pins += [context['packet'], context['after_exit'], recovery_packet['recovery']]
    for row in history_pins:
        require(pins.setdefault(native_path(row['path']), row['sha256']) == row['sha256'], 'history receipt pin conflict')
    retained = dict(schema='chopper-small-retained-origin-v1', additional_retained_bytes=0,
        adopted_roots=[*covered, *extra_roots, paths['source'], paths['metadata']], metadata=dict(storage_priming=dict(
            covered_roots=covered, fresh_roots=fresh, ledger=dict(path=native_path(prior['path']),
                sha256=prior['sha256'], cumulative_owned_bytes=ledger['cumulative_owned_bytes'])),
            history=history))
    pins[paths['origin']] = hashlib.sha256(_json_bytes(retained)).hexdigest()
    if execution.get('execution_kind') == 'batch':
        for row in batch_inputs(execution['frozen_batch']):
            require(pins.setdefault(row['path'],row['sha256']) == row['sha256'], 'conflicting batch proof pin')
    coverage=selection.get('coverage','full15')
    require(coverage in ('full15','first-command-control'),'explicit supported SMALL coverage required')
    commands=small.command_specs(first_only=coverage=='first-command-control')
    config = dict(**execution, schema='chopper-small-runner-config-v1', root=paths['root'], owned_root=paths['owned_root'],
        source_commit=small.PRODUCT, source_tree=small.PRODUCT_TREE, harness_commit=harness,
        channel=observed_host['channel'], overall_deadline_ms=int(timing['deadline']*1000), browser=tools['browser']['path'], browser_version=observed_host['browser_version'],
        node=tools['node']['path'], python=tools['python']['path'],
        package_receipt=str(receipt), package_zips=[str(packages/name) for name in sorted(release['packages'])],
        product_assets=[str(root/'ui/dist'/name) for name in sorted(release['hosted'])],
        product_source=[dict(path=str(root/PureWindowsPath(name)),git_path=name) for name in projection['product_source']],
        harness_source=[dict(path=str(root/PureWindowsPath(name)),git_path=name) for name in projection['harness_source']],
        preparation=observed_host['preparation'],retained_origin_manifest=paths['origin'], history_roots=[],
        volumes=sorted({PureWindowsPath(value).anchor for value in [paths['root'],paths['owned_root'],*pins,*cold_pins]}), limits=small.LIMITS,
        commands=commands, inputs=[dict(path=p,sha256=v) for p,v in sorted(pins.items())],
        input_directories=[str(root/PureWindowsPath(p)) for p in ('scripts','ui/src','ui/dist','ui/node_modules','.git')]
                          +list(observed_host['input_directories'])+retained_roots)
    # Future owned roots and outputs all come from paths above; never copied from history.
    prefix = [tools['python']['path'],'-E','-s','-B']
    entry = str(root/'scripts/browser-small-runner.py')
    denial = dict(schema=checker.SCHEMA,status='failed')
    commands_exact = [dict(phase='safe-import-denial',argv=prefix+[entry,'qualify',paths['plan'],
        '--approve-sha256','0'*64,'--config',paths['config'],'--preflight',paths['denial'],
        '--preflight-sha256',hashlib.sha256(_json_bytes(denial)).hexdigest()],
        expected_exit=1,expected_error='matching passed preflight required',
        absent=[paths['plan'],paths['owned_root']]),dict(phase='preflight', argv=prefix+[str(root/'scripts/acceptance-preflight.py'),'preflight',paths['request'],paths['preflight']]),
        dict(phase='prepare',argv=prefix+[entry,'prepare',paths['config'],paths['plan']]),
        dict(phase='qualify',argv=prefix+[entry,'qualify',paths['plan'],'--approve-sha256','$ACTUAL_PLAN_SHA',
            '--config',paths['config'],'--preflight',str(PureWindowsPath(paths['preflight'])/'result.json'),
            '--preflight-sha256','$ACTUAL_PREFLIGHT_SHA']),
        dict(phase='after-exit',argv=prefix+[native_path(checker.__file__),'after-exit',
            paths['packet'],paths['after_exit'],'--sha256','$ACTUAL_PACKET_SHA'])]
    require(type(selection['retained_preparation_bytes']) is int and selection['retained_preparation_bytes'] >= 0,
            'nonnegative retained preparation debit required')
    require(selection['retained_preparation_bytes'] + SMALL_PREPARATION['storage_bytes'] < SMALL_PREPARATION_CAMPAIGN_BYTES,
            'cumulative preparation allowance')
    destination.mkdir()
    bundle = destination/'product-harness.bundle'
    subprocess.run(['git','-C',str(repository),'bundle','create',str(bundle),'HEAD',small.PRODUCT],check=True,timeout=60)
    with tempfile.TemporaryDirectory(prefix='hosted-packet-transport-') as control:
        subprocess.run(['git','-c','gc.auto=0','clone','--no-checkout','--quiet',str(bundle),control],check=True,timeout=30)
        for row in projection['files']:
            if 'git_commit' in row:
                body=subprocess.check_output(['git','-C',control,'show',row['git_commit']+':'+row['git_path']],timeout=10)
                require(hashlib.sha256(body).hexdigest()==row['sha256'], 'transported Git body mismatch')
    code = checker.checker_sources()
    with bundle.open('rb') as stream:
        bundle_sha = hashlib.file_digest(stream,'sha256').hexdigest()
    live_bytes=sum(observed_host['input_sizes'].values())+sum(row['bytes'] for row in projection['files'])
    live_bytes+=sum(row['bytes'] for group in retained_after['roots'] for row in group['inputs']) if retained_after else 0
    cold_bytes=sum(observed_host['preparation']['input_sizes'].values())
    preflight_read=128*1024**2+2*(live_bytes+64*1024**2+16*1024**2+sum(v['bytes'] for v in release['packages'].values()))+cold_bytes
    preflight_read=max(SMALL_PREPARATION['read_bytes'],((preflight_read+1024**2-1)//1024**2)*1024**2)
    config_bytes=len(_json_bytes(config))
    preflight_storage=max(5*1024**2,((2*(4*config_bytes+1024**2)+1024**2-1)//1024**2)*1024**2)
    require(preflight_storage<=SMALL_PREPARATION['storage_bytes'],'preflight metadata forecast exceeds preparation storage allowance')
    if coverage=='first-command-control':
        next(c for c in commands_exact if c['phase']=='qualify')['argv'].append('--first-command-control')
    packet = dict(schema=PACKET_SCHEMA, profile='small', coverage=coverage, host_producer_relevance=host_relevance,source_commit=harness, paths=paths,
        host=observed_host['host'], tools=tools, projection=projection, configuration=config, origin=retained,
        bundle=dict(path=native_path(bundle),sha256=bundle_sha,bytes=bundle.stat().st_size),
        preparation_code=[dict(path=native_path(p),sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest()) for p in code],
        limits=SMALL_PREPARATION,preflight_limits=dict(SMALL_PREPARATION,read_bytes=preflight_read,storage_bytes=preflight_storage),
        preparation_read_forecast=dict(live_bytes=live_bytes,cold_bytes=cold_bytes,preflight_read_bytes=preflight_read,config_bytes=config_bytes,preflight_storage_bytes=preflight_storage),
        retained_preparation_bytes=selection['retained_preparation_bytes'],
        window=dict(path=native_path(selection['window']['path']),sha256=selection['window']['sha256']),
        timing=timing,dispatch=selection['dispatch'],commands=commands_exact,
        future_bindings=['candidate_sha256','preflight_sha256','plan_sha256','actual_batch_started_ms','actual_input_count'],
        qualification=False, workload_started=False, acceptance_window_started=False, scale_slot_consumed=False)
    if retained_after is not None:packet['retained_after_ledger']=retained_after
    packet['dispatch']['checkout'] = native_path(packet['dispatch']['checkout'])
    require(PureWindowsPath(packet['dispatch']['checkout']).drive.upper() == 'C:'
            and len(packet['dispatch']['commit']) == 40, 'selected clean native dispatcher checkout required')
    packet['dispatch']['environment'] = dict(CHOPPER_WINDOWS_GIT=tools['git']['path'],
                                           CHOPPER_WINDOWS_PYTHON=tools['python']['path'])
    for command in packet['commands']:
        command['dispatch_argv'] = [sys.executable,'-B',str(repository/'scripts/windows-native.py'),
            '--checkout',packet['dispatch']['checkout'],'--expect-commit',packet['dispatch']['commit'],
            'python',*command['argv'][1:]]
    packet_declarations(packet,checker)
    packet_path=destination/'packet.json'
    packet_path.write_bytes(_json_bytes(packet))
    return dict(path=str(packet_path),sha256=hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                source_files=len(projection['files']),commands=len(commands),qualification=False)


def _observed_file(path, budget, expected=None):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute native input required')
    require(all(not p.is_symlink() and not getattr(p,'is_junction',lambda:False)()
                for p in (path,*path.parents)), 'input alias denied: '+str(path))
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), 'regular input required: '+str(path))
    if not budget.active:
        budget.read_bytes += before.st_size; budget.visits += 2
    budget.check()
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream,'sha256').hexdigest()
    stamp = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(stamp(before) == stamp(path.stat()), 'input changed during hash: '+str(path))
    require(expected is None or actual == expected,
            'pin mismatch: '+str(path)+' expected='+str(expected)+' actual='+actual)
    return dict(path=str(path),sha256=actual)


def _pinned_bytes(binding, budget, maximum=16*1024**2):
    path = Path(binding['path'])
    require(path.is_absolute(), 'native absolute pinned file required')
    require(all(not p.is_symlink() and not getattr(p,'is_junction',lambda:False)()
                for p in (path,*path.parents)), 'pinned input alias denied')
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), 'regular pinned input required')
    require(0 <= before.st_size <= maximum, 'pinned file memory bound: '+str(path))
    if not budget.active:
        budget.read_bytes += before.st_size
        budget.visits += 2
    budget.check()
    raw = path.read_bytes()
    after = path.stat()
    stamp = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(stamp(before) == stamp(after) and len(raw) == before.st_size, 'pinned file changed: '+str(path))
    actual = hashlib.sha256(raw).hexdigest()
    require(actual == binding['sha256'], 'pin mismatch: '+str(path)+' expected='+binding['sha256']+' actual='+actual)
    return raw


def browser_scale_future_capacity(reservation, channel, retained_roots):
    """Reserve unallocated live channel bytes, never refund historical allocation debt."""
    started=time.time()
    from .browser_scale_guard import channel_owned_roots, Guard, real_path
    from .browser_scale_plan import LIMITS
    claims=real_path(reservation['claims_root'])
    require(claims.is_dir() and not os.path.lexists(claims/'active.lock'),'cold channel reservation has an active/missing owner')
    roots=[path.resolve(strict=True) for path in channel_owned_roots(reservation,channel)]
    owners=[Path(path).resolve(strict=True) for path in retained_roots]
    require(roots and len(set(roots))==len(roots) and all(not a.is_relative_to(b)
        for i,a in enumerate(roots) for j,b in enumerate(roots) if i!=j),'missing/overlapping channel roots')
    require(all(any(path.is_relative_to(owner) for owner in owners) for path in roots),
        'channel current bytes outside reconciled retained union')
    try:
        owned=Guard.disk_values(roots,roots)['owned']
    except BaseException as error:
        error.add_note('Guard.disk_values cold channel='+channel+' roots='+str(roots))
        raise
    require(not os.path.lexists(claims/'active.lock'),'channel owner appeared during cold reservation')
    require(type(owned) is int and 0 <= owned < LIMITS['owned_bytes'],
        f'current channel owned-tree ceiling: observed={owned!r}, maximum={LIMITS["owned_bytes"]}')
    return dict(roots=[str(path) for path in roots],current_owned_bytes=owned,
        channel_limit_bytes=LIMITS['owned_bytes'],future_bytes=LIMITS['owned_bytes']-owned,
        observation_started_unix=started,metric='current regular-file logical bytes; historical identity-HWM debt remains in global baseline')


def materialize_browser_scale(packet, destination, expected_sha256, checker, *, timer=None):
    """Cold separate clean clones, bridge and authoritative admission files."""
    from .browser_scale_identity import ScaleIdentity, SOURCE, TREE
    from .browser_scale_plan import documents
    packet_declarations(packet,checker)
    mode=packet.get('mode','qualify');shape=packet.get('shape','D')
    _window(bound_json(packet['window']),seconds=1500 if mode=='qualify' else BROWSER_SCALE_FORECAST[shape]['seconds']+BROWSER_SCALE_FORECAST[shape]['cleanup_margin_seconds'])
    require(packet['host']==host() and Path(destination)==Path(packet['paths']['metadata']),'actual host/output binding')
    paths=packet['paths'];source=Path(paths['source']);metadata=Path(destination);root=Path(paths['root'])
    require(not source.exists() and not metadata.exists(),'fresh source/preparation targets required')
    require(packet['limits']==SMALL_PREPARATION,'reviewed materialization limits')
    small=checker.load('browser-small-runner');runner=small.runner;runner.contain_session()
    budget=checker.Budget(packet['limits'],metadata,mutation_roots=[source,metadata]);budget.read_bytes=64*1024**2;budget.visits=8192
    if timer is None:timer=threading.Timer(180,lambda:os._exit(124));timer.daemon=True;timer.start()
    null=open(os.devnull,'rb');budget.null_input=null
    result=dict(schema=PACKET_SCHEMA,profile='browser-scale',status='failed',qualification=False,
        packet_sha256=expected_sha256,original_acquired=False,workload_started=False,scale_slot_consumed=False,paths=paths)
    try:
        budget.install()
        actual_host=json.loads(_pinned_bytes(packet['host_observation'],budget))
        require(browser_scale_host_bindings(actual_host)==packet['host_receipt'],'bound host declaration drift')
        for row in packet['preparation_code']:_observed_file(row['path'],budget,row['sha256'])
        for row in packet['tools'].values():_observed_file(row['path'],budget,row['sha256'])
        for row in packet['host_receipt']['preparation']['inputs']:_observed_file(row['path'],budget,row['sha256'])
        if 'time_continuation'in packet:
            browser_scale_time_available(packet['time_continuation'],initial=mode=='qualify',plan_id=packet['selection']['plan_id'])
        partition=packet['origin']['metadata']['storage_priming']
        ledger=json.loads(_pinned_bytes(partition['ledger'],budget,1024**2))
        require(ledger['cumulative_owned_bytes']==partition['ledger']['cumulative_owned_bytes'],'retained ledger floor')
        storage=small.primed_storage(partition,[])
        existing=retained_packet_roots(packet)
        for directory,names in existing.items():
            require(small.inventory(directory)==names,'retained current root membership')
            for row in next(group['inputs'] for group in packet['retained_after_ledger']['roots'] if group['root']==directory):
                require(Path(row['path']).stat().st_size==row['bytes'],'retained current file size')
                _observed_file(row['path'],budget,row['sha256'])
            require(small.inventory(directory)==names,'retained membership changed during check')
        storage.roots.extend(Path(p) for p in retained_packet_roots(packet,fresh=True));storage.sample()
        baseline=storage.total
        future=0
        if mode=='scale':
            reservation=json.loads(_pinned_bytes(packet['large_reservation'],budget))
            result['admission_query']=dict(phase='remaining-channel-current-tree',api='Guard.disk_values',
                channel=packet['host_receipt']['channel'],reservation=packet['large_reservation'],maximum_seconds=30)
            future_scope=small.bounded_cleanup(lambda:browser_scale_future_capacity(
                reservation,packet['host_receipt']['channel'],storage.roots),timeout=30)
            future=future_scope['future_bytes']
            result['future_channel_reservation']=future_scope
        require(baseline+future+packet['limits']['storage_bytes']<small.LIMITS['stop_owned_bytes'],
            'global logical admission including current Large reservation')
        require(shutil.disk_usage('C:/').free-(24*1024**3+packet['limits']['storage_bytes'])>=128*1024**3,'physical prospective C floor')
        source.mkdir();metadata.mkdir();storage.roots.extend([source,metadata])
        port=packet['selection']['origin_port']
        ps="$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$rows=@();try{$rows=@(Get-NetTCPConnection -LocalPort "+str(port)+" -ErrorAction Stop)}catch{if($_.FullyQualifiedErrorId -ne 'CmdletizationQuery_NotFound_LocalPort,Get-NetTCPConnection'){throw}};@{port="+str(port)+";rows=$rows.Count;complete=$true;tcp=@($rows|Select-Object -First 4 LocalAddress,LocalPort,State,OwningProcess)}|ConvertTo-Json -Compress -Depth 4"
        port_log=checker.probe([packet['tools']['powershell']['path'],'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',
            base64.b64encode(ps.encode('utf-16le')).decode('ascii')],budget,'selected-origin',cwd=source)
        port_state=json.loads(port_log.read_bytes().decode('utf-8-sig'))
        require(port_state['port']==port and port_state['complete'] is True and port_state['rows']==0,
                'selected origin has current TCP state; no browser admission')
        result['origin_readiness']=dict(sampled_unix=time.time(),**port_state)
        bundle=packet['bundle'];_observed_file(bundle['path'],budget,bundle['sha256'])
        git=packet['tools']['git']['path']
        for role,commit in [('product',SOURCE),('harness',packet['source_commit'])]:
            target=Path(paths['product'] if role=='product' else paths['root'])
            checker.probe([git,'-c','gc.auto=0','clone','--no-checkout',bundle['path'],str(target)],budget,'clone-'+role,cwd=source)
            checker.probe([git,'-c','core.autocrlf=false','-c','core.eol=lf','-c','core.hooksPath=NUL','-c','core.fsmonitor=false',
                '-C',str(target),'checkout','--detach',commit],budget,'checkout-'+role,cwd=source)
            for name,digest in packet['projection'][role].items():_observed_file(target/name,budget,digest)
        for row in packet['projection']['dependencies']+packet['projection']['assets']:
            target=(root/row['relative'] if row in packet['projection']['dependencies'] else Path(paths['assets'])/PureWindowsPath(row['relative']).name)
            raw=_pinned_bytes(dict(path=row['source'],sha256=row['sha256']),budget)
            require(len(raw)==row['bytes'],'borrowed body size');target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
        scratch=root/'scratch';scratch.mkdir();bridge=scratch/'bridge'
        checker.probe([packet['tools']['node']['path'],str(root/'scripts/scale_acceptance/browser-scale-bundle.mjs'),
            paths['product'],str(bridge)],budget,'production-bridge',cwd=root)
        provenance=json.loads((bridge/'bundle-provenance.json').read_bytes())
        require(provenance['hosted'] is True and provenance['node_version']==packet['host_receipt']['tools']['node']['version'],
                'actual bridge Node identity')
        packages=Path(packet['selection']['packages']);evidence=metadata/'evidence';evidence.mkdir()
        release=packet['release']
        evidence_rows=[dict(name=release['artifact_receipt']['name'],sha256=release['artifact_receipt']['sha256'])]
        package=packet['selection']['hosted_package']
        require(package in release['packages'] and package.endswith('-hosted.zip'),'explicit selected hosted package')
        evidence_rows.append(dict(name=package,sha256=release['packages'][package]['sha256']))
        for row in evidence_rows:
            require(Path(row['name']).name==row['name'],'package leaf name')
            raw=_pinned_bytes(dict(path=str(packages/row['name']),sha256=row['sha256']),budget)
            (evidence/row['name']).write_bytes(raw)
        from hosted_picker.assets import read_package
        read_package(evidence/package,dict(package=release['packages'][package],assets=release['hosted']))
        if mode=='qualify':
            if 'time_continuation'not in packet:Path(paths['claims']).mkdir()
            reservation=browser_scale_make_reservation(packet,time.time())
            reservation_raw=_json_bytes(reservation)
        else:
            reservation_raw=_pinned_bytes(packet['large_reservation'],budget,65536)
            reservation=json.loads(reservation_raw)
            browser_scale_reservation(packet,reservation)
            claims=Path(reservation['claims_root'])
            require(claims.is_dir() and all(not claims.is_relative_to(Path(row['directory']))
                for row in reservation['slots']), 'original external Large claims owner required')
        # Large copies these exact immutable bytes; every cell still uses the
        # same external irreversible claim files, never a new per-case ledger.
        Path(paths['reservation']).write_bytes(reservation_raw)
        def group(directory,inputs):
            actual=runner.identity(directory,inputs)
            require(not runner.incomplete_identity(actual),'complete generated identity group')
            return dict(root=str(directory),inputs=inputs,sha256={Path(name).as_posix():row['sha256'] for name,row in actual.items() if not row.get('directory')})
        harness_inputs=[*packet['projection']['harness_inputs'],'scratch/bridge/bridge.js','scratch/bridge/bundle-provenance.json']
        runtime=packet['host_receipt'];runtime_rows={row['path']:row for row in runtime['inputs']+runtime['preparation']['inputs']}
        directories=dict(runtime['input_directories'],**runtime['preparation']['input_directories'])
        for directory,members in directories.items():require(small.inventory(directory)==members,'full runtime membership drift')
        p=dict(version=1,runtime='browser',mode=mode,features=[],parent_scheduled=True,
            source=dict(commit=SOURCE,tree=TREE,clean=True),harness_source=dict(commit=packet['source_commit'],tree=packet['source_tree'],clean=True),
            host=dict(packet['host'],node_os_release=provenance['node_os_release'],node_os_version=provenance['node_os_version']),
            channel=runtime['channel'],browser_version=runtime['browser_version'],shape=shape,fixture=packet['fixture'],
            product=group(Path(paths['product']),packet['projection']['product_inputs']),harness=group(root,harness_inputs),
            assets=group(Path(paths['assets']),['*']),evidence=group(evidence,['*']),
            bundle='scratch/bridge/bridge.js',bundle_provenance='scratch/bridge/bundle-provenance.json',
            toolchains=dict(python_version=sys.version,node_version=provenance['node_version'],esbuild_version=provenance['esbuild_version'],
                playwright_version=json.loads((root/'ui/node_modules/playwright/package.json').read_bytes())['version']),
            storage=dict(metric='sampled logical owned union; unseen transient allocation UNKNOWN',owned_limit_bytes=24*1024**3),
            browser=packet['tools']['browser'],python=packet['tools']['python'],node=packet['tools']['node'],git=packet['tools']['git'],
            external_runtime=dict(inputs=list(runtime_rows.values()),input_directories=directories,git_exec_path=runtime['git_exec_path']),
            reservation=dict(path=paths['reservation'],sha256=hashlib.sha256(Path(paths['reservation']).read_bytes()).hexdigest()),
            profile=str(Path(paths['owned_root'])/'work'/'profile'),plan_id=packet['selection']['plan_id'],
            origin='http://127.0.0.1:'+str(packet['selection']['origin_port']),build_receipts=[release['artifact_receipt']['name']],
            package=dict(path=package,sha256=release['packages'][package]['sha256']))
        p.update(execution_selection(packet))
        if mode=='scale':
            p.update(campaign_qualification=packet['campaign_qualification'],campaign_reservation=packet['large_reservation'])
            if 'peer' in packet:p['peer']=packet['peer']
        if 'time_continuation'in packet:
            p['time_continuation']=packet['time_continuation'];p['time_continuation_history']=packet['origin']['metadata']['history']
        if 'borrowed_input' in packet:p['borrowed_input']=check_borrowed_input(packet['borrowed_input'],observe=True)
        batch_admission(p,'browser-scale',p['channel'])
        raw=_json_bytes(p);require(len(raw)<=16*1024**2,'identity document memory bound');Path(paths['config']).write_bytes(raw)
        binding=dict(packet=paths['config'],sha256=hashlib.sha256(raw).hexdigest())
        started=time.monotonic();identity=ScaleIdentity(binding,preparation=True);cold=time.monotonic()-started
        started=time.monotonic();identity.check();check_seconds=time.monotonic()-started
        identity.require_windows()
        if mode=='scale':
            from .browser_scale_guard import schedule
            _,_,channel_deadline=schedule(p,Path(paths['owned_root']),time.time())
            require(time.time()+BROWSER_SCALE_FORECAST[shape]['seconds']+BROWSER_SCALE_FORECAST[shape]['cleanup_margin_seconds']-240<min(channel_deadline,packet['timing']['deadline']),
                'current Large cell forecast cannot fit original channel/overall deadline')
        directory=Path(paths['owned_root']);directory.mkdir();manifest,policy=documents(directory,binding,p,harness_root=root)
        Path(paths['plan']).write_bytes(_json_bytes(manifest));Path(paths['policy']).write_bytes(_json_bytes(policy))
        approval=dict(version=1,decision='approved',contract=manifest['contract'],plan_id=p['plan_id'],shape=shape,channel=p['channel'],
            plan_sha256=hashlib.sha256(Path(paths['plan']).read_bytes()).hexdigest(),policy_sha256=hashlib.sha256(Path(paths['policy']).read_bytes()).hexdigest(),
            packet_sha256=binding['sha256'],reservation_sha256=p['reservation']['sha256'],
            approved_by='parent-reviewed maintained execution packet',approval_reference=packet['selection']['approval_reference'])
        Path(paths['approval']).write_bytes(_json_bytes(approval))
        request=dict(schema=checker.SCHEMA,profile='browser-scale',host_os='Windows',plan=paths['config'],plan_sha256=binding['sha256'],limits=packet['preflight_limits'])
        Path(paths['request']).write_bytes(_json_bytes(request));Path(paths['packet']).write_bytes(_json_bytes(packet))
        current=storage.sample(mutable_roots=[source,metadata],deadline=budget.started+budget.limits['seconds'])
        require(current-baseline<packet['limits']['storage_bytes'],'complete preparation growth allowance')
        own=small.windows.query_job(runner._SESSION_JOB)
        require(own['kill_on_close'] and own['pids']==[os.getpid()],'cold materialization owner-only Job')
        result.update(status='passed',candidate_sha256=binding['sha256'],cold_identity_seconds=cold,
            full_metadata_check_seconds=check_seconds,owned_bytes=current,usage=budget.usage(),job=own,
            observer=small.windows.process_identity(os.getpid()),commands=packet['commands'])
        return result
    except BaseException as error:
        result.update(error=repr(error),error_notes=list(getattr(error,'__notes__',()))[:2],usage=budget.usage())
        error.preflight_result=result
        raise
    finally:
        budget.active=False;null.close();timer.cancel();timer.join();result['timer_joined']=not timer.is_alive()
        if metadata.is_dir():(metadata/'materialization-result.json').write_bytes(_json_bytes(result))


def materialize_packet(packet_path, destination, expected_sha256, checker, *, timer=None):
    """Materialize the declared source and candidate; no Original, clock or browser.

    Clone and copies are fixed owning operations, never packet-supplied programs.
    A failed materialization retains its partial root and is never retried here.
    """
    require(os.name == 'nt', 'materialization requires actual Windows')
    packet = bound_json(dict(path=str(Path(packet_path).absolute()),sha256=expected_sha256))
    require(packet['schema'] == PACKET_SCHEMA and packet['host'] == host(), 'packet host/schema mismatch')
    if packet.get('operation')==RECOVERY_OPERATION:return materialize_recovery(packet,destination,expected_sha256,checker,timer=timer)
    if packet.get('profile')=='browser-scale':return materialize_browser_scale(packet,destination,expected_sha256,checker,timer=timer)
    packet_declarations(packet,checker)
    _window(bound_json(packet['window']),seconds=900 if 'overall_deadline_ms' in packet['configuration'] else 7920)
    paths = packet['paths']
    require(paths == preparation_paths(str(PureWindowsPath(paths['source']).with_name(
        PureWindowsPath(paths['source']).name.removesuffix('-source')))), 'generated namespace drift')
    require(Path(destination) == Path(paths['metadata']), 'materialization output must match declared metadata')
    for row in packet['preparation_code']:
        require(hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() == row['sha256'],
                'preparation implementation drift: '+row['path'])
    limits = packet['limits']
    require(limits == SMALL_PREPARATION, 'unreviewed materialization limits')
    budget = checker.Budget(limits, destination,mutation_roots=[paths['source'],paths['metadata']])
    budget.read_bytes=64*1024**2;budget.visits=8192
    small = checker.load('browser-small-runner')
    runner = small.runner
    runner.contain_session()
    if timer is None:
        timer = threading.Timer(limits['seconds'],lambda:os._exit(124))
        timer.daemon=True;timer.start()
    null_input=open(os.devnull,'rb');budget.null_input=null_input
    result = dict(schema=PACKET_SCHEMA,status='failed',packet_sha256=expected_sha256,
        workload_started=False,acceptance_window_started=False,scale_slot_consumed=False,
        original_acquired=False,host=host(),paths=paths)
    try:
        budget.install()
        config, origin = packet['configuration'], packet['origin']
        partition = origin['metadata']['storage_priming']
        _disjoint_native_roots([*partition['covered_roots'],*partition['fresh_roots']])
        existing = retained_packet_roots(packet)
        require(all(not Path(paths[key]).exists() for key in ('source','metadata','owned_root')), 'fresh target already exists')
        for directory,names in existing.items():
            require(small.inventory(directory)==names, 'retained root membership drift')
            for name in names:
                selected=next(row for group in packet['retained_after_ledger']['roots'] for row in group['inputs'] if row['path']==name)
                require(Path(name).stat().st_size==selected['bytes'], 'retained file size drift')
                _observed_file(name,budget,selected['sha256'])
            require(small.inventory(directory)==names, 'retained root membership drift')
        checker.check_evidence_destination(Path(destination), [Path(config['root']),*map(Path,partition['covered_roots'])])
        require(shutil.disk_usage('C:/').free - 64*1024**3 >= 128*1024**3,
                'fresh physical C: headroom below admission floor')
        for row in packet['tools'].values():
            _observed_file(row['path'],budget,row['sha256'])
        cold=small.preparation_state(config)
        small.check_inputs(cold)
        ledger_raw = _pinned_bytes(partition['ledger'],budget,1024**2)
        require(json.loads(ledger_raw)['cumulative_owned_bytes'] == partition['ledger']['cumulative_owned_bytes'],
                'immutable accounting baseline mismatch')
        storage = small.primed_storage(partition,[])
        visible = sum(storage.high.values())
        baseline_total = storage.total
        storage.roots.extend(Path(p) for p in retained_packet_roots(packet,fresh=True))
        storage.sample()
        require(storage.total + limits['storage_bytes'] < small.LIMITS['stop_owned_bytes'], 'prospective source storage cap')
        require(packet['retained_preparation_bytes'] + limits['storage_bytes'] < SMALL_PREPARATION_CAMPAIGN_BYTES, 'cumulative preparation cap')
        # Every payload body is validated before its destination is created.
        source = Path(paths['source']); source.mkdir()
        metadata = Path(destination); metadata.mkdir()
        storage.roots.extend([source,metadata])
        root = Path(paths['root']); root.mkdir()
        bundle = packet['bundle']
        require(Path(bundle['path']).stat().st_size <= 64*1024**2, 'bundle disk/input bound')
        _observed_file(bundle['path'],budget,bundle['sha256'])
        checker.probe([packet['tools']['git']['path'],'-c','gc.auto=0','clone','--no-checkout',bundle['path'],str(root)],
                      budget,'git-clone',cwd=source)
        small.check_inputs(cold)
        for row in packet['projection']['files']:
            budget.check()
            target = root / row['relative']
            require(target.is_relative_to(root) and '..' not in Path(row['relative']).parts,
                    'payload destination traversal')
            raw = (base64.b64decode(row['inline'],validate=True) if 'inline' in row
                   else _pinned_bytes(dict(path=row['source'],sha256=row['sha256']),budget))
            require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
                    'projected body mismatch: '+row['relative'])
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream: stream.write(raw)
        # Git metadata is generated by the actual clone and pinned before admission.
        pins = {row['path']:row['sha256'] for row in config['inputs']}
        for name in small.inventory(root/'.git'):
            path = Path(name)
            pins[name] = _observed_file(path,budget)['sha256']
        Path(paths['packet']).write_bytes(_json_bytes(packet))
        Path(paths['origin']).write_bytes(_json_bytes(origin))
        Path(paths['denial']).write_bytes(_json_bytes(dict(schema=checker.SCHEMA,status='failed')))
        config = dict(config,inputs=[dict(path=p,sha256=v) for p,v in sorted(pins.items())])
        candidate = _json_bytes(config)
        require(len(candidate) <= 16*1024**2, 'candidate document memory bound')
        Path(paths['config']).write_bytes(candidate)
        actual_live=sum(Path(row['path']).stat().st_size for row in config['inputs'])
        actual_cold=sum(Path(row['path']).stat().st_size for row in config['preparation']['inputs'])
        require(128*1024**2+2*actual_live+actual_cold<=packet['preflight_limits']['read_bytes'],
                'actual native preflight read forecast exceeds declared allowance')
        request = dict(schema=checker.SCHEMA,profile='small',host_os='Windows',plan=paths['config'],
                       plan_sha256=hashlib.sha256(candidate).hexdigest(),limits=packet['preflight_limits'])
        Path(paths['request']).write_bytes(_json_bytes(request))
        current = storage.sample()
        require(current-baseline_total <= limits['storage_bytes'], 'materialization growth limit')
        own = small.windows.query_job(runner._SESSION_JOB)
        require(own['kill_on_close'] and set(own['pids']) == {os.getpid()}, 'materializer Job not owner-only')
        result.update(status='passed',candidate_sha256=request['plan_sha256'],owned_bytes=current,
                      usage=budget.usage(),job=own,observer=small.windows.process_identity(os.getpid()),
                      commands=packet['commands'])
        return result
    except BaseException as error:
        result.update(error=type(error).__name__+': '+str(error),usage=budget.usage())
        raise
    finally:
        budget.active=False;null_input.close()
        timer.cancel(); timer.join()
        result['timer_joined'] = not timer.is_alive()
        if Path(destination).is_dir():
            (Path(destination)/'materialization-result.json').write_bytes(_json_bytes(result))


def signature_facts(path):
    """The fixed probe emits JSON only; unexpected progress/errors remain a denial."""
    try:
        return json.loads(Path(path).read_bytes().decode('utf-8-sig'))
    except (UnicodeError,json.JSONDecodeError) as error:
        raise ValueError('packet-host tool-signatures JSON decode at '+str(path)+': '+str(error)) from error


def host_runtime_inventory(selected, roots, destination, small):
    """Use the same plain inventory for explicitly selected complete runtime trees."""
    extra=[Path(name) for name in selected.get('extra_runtime_roots',[])]
    require(len(extra)<=8 and len(set(extra))==len(extra) and all(name.is_absolute() for name in extra),
            'bounded explicit absolute extra runtime roots required')
    require(all(not destination.is_relative_to(name) and not name.is_relative_to(destination) for name in extra),
            'observation output/runtime overlap')
    return {str(root):small.inventory(root) for root in sorted(set(roots)|set(extra))}


def observe_packet_host(selection_path, destination, expected_sha256, checker, *, timer=None):
    """Observe actual tool publishers and complete selected runtime byte membership."""
    require(os.name == 'nt', 'host observation requires actual Windows')
    selected = bound_json(dict(path=str(Path(selection_path).absolute()),sha256=expected_sha256),1024**2)
    require(selected['schema'] == 'chopper-hosted-host-selection-v1'
            and selected['channel'] in ('chrome','msedge'), 'host selection schema/channel')
    destination = Path(destination)
    checker.check_evidence_destination(destination,[Path(checker.__file__).parent.parent,Path(selection_path)])
    require(not destination.exists(), 'fresh host evidence destination required')
    for role in ('git','python','node','browser','powershell'):
        require(Path(selected['tools'][role]).is_absolute(), 'absolute actual tool required: '+role)
    require(Path(selected['tools']['python']) == Path(sys.executable), 'observe with selected actual Python')
    destination.mkdir()
    limits = dict(SMALL_PREPARATION,read_bytes=selected.get('read_bytes',SMALL_PREPARATION['read_bytes']))
    require(type(limits['read_bytes']) is int and limits['read_bytes']>0,'positive explicitly reviewed host read allowance')
    budget = checker.Budget(limits,destination)
    budget.read_bytes=64*1024**2;budget.visits=8192
    if timer is None:
        timer=threading.Timer(limits['seconds'],lambda:os._exit(124));timer.daemon=True;timer.start()
    null_input=None
    phase='bootstrap';probe_path=None
    try:
        null_input=open(os.devnull,'rb');budget.null_input=null_input
        small = checker.load('browser-small-runner')
        small.runner.contain_session()
        actual_host=host()
        budget.install()
        tool_stamps={path:small.stamp(path) for path in selected['tools'].values()}
        paths = base64.b64encode(json.dumps(selected['tools']).encode()).decode()
        script = "$ProgressPreference='SilentlyContinue';$p=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+paths+"')));$r=@{};"
        script += "foreach($v in $p.PSObject.Properties){$f=Get-Item -LiteralPath $v.Value;$s=Get-AuthenticodeSignature -LiteralPath $v.Value;$r[$v.Name]=@{status=$s.Status.ToString();publisher=$s.SignerCertificate.Subject;version=$f.VersionInfo.FileVersion}};$r|ConvertTo-Json -Compress"
        encoded = base64.b64encode(script.encode('utf-16-le')).decode()
        phase='tool-signatures';probe_path=str(destination/'tool-signatures.log')
        signatures = signature_facts(checker.probe([selected['tools']['powershell'],'-NoProfile','-NonInteractive',
            '-EncodedCommand',encoded],budget,'tool-signatures'))
        versions = {}
        for role in ('git','python','node'):
            phase=role+'-version';probe_path=str(destination/(phase+'.log'))
            versions[role] = checker.probe([selected['tools'][role],'--version'],budget,role+'-version').read_text().strip()
        from .native_scale_identity import runtime_requirements
        roots, files = runtime_requirements()
        runtime = (set(roots),set(files))
        phase='git-exec-path';probe_path=str(destination/'git-exec-path.log')
        git_exec=Path(checker.probe([selected['tools']['git'],'--exec-path'],budget,'git-exec-path').read_text().strip())
        require(git_exec.is_absolute() and git_exec.name=='git-core' and git_exec.parent.name=='libexec',
                'unsupported selected Git runtime layout')
        cold_roots={git_exec,git_exec.parent.parent/'bin'}
        roots.update(cold_roots)
        browser_version=signatures['browser']['version']
        require(re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}',browser_version or ''),'unsupported installed browser file version')
        browser_root=Path(selected['tools']['browser']).parent/browser_version
        if selected.get('browser_inventory_roots'):
            require(set(map(Path,selected['browser_inventory_roots']))=={browser_root},'selected browser version directory mismatch')
        roots.add(browser_root)
        files.update(Path(p) for p in selected['tools'].values())
        if 'zstd_dll' in selected:
            files.add(Path(selected['zstd_dll']))
        phase='runtime-inventory';probe_path=None
        before=host_runtime_inventory(selected,roots,destination,small)
        roots.update(map(Path,before))
        files.update(Path(p) for members in before.values() for p in members)
        stamps={str(path):small.stamp(path) for path in files}
        require(all(stamps[path]==stamp for path,stamp in tool_stamps.items()),'tool changed during version observation')
        sizes={path:stamp[2] for path,stamp in stamps.items()}
        total=sum(sizes.values())
        forecast=budget.read_bytes+2*total+1024**2
        if forecast>limits['read_bytes']:
            report=dict(schema='chopper-hosted-host-budget-v1',status='needs-budget',
                forecast_read_bytes=forecast,read_limit=limits['read_bytes'],inventory_files=len(files),
                inventory_bytes=total,host_inventory_body_hashes_started=False,workload_started=False,
                original_acquired=False,controller_started=False,
                git_exec_path=str(git_exec),browser_root=str(browser_root),
                inventories={name:dict(files=len(members),bytes=sum(sizes[p] for p in members)) for name,members in before.items()},
                usage=budget.usage(),observer=small.windows.process_identity(os.getpid()))
            proof=small.windows.query_job(small.runner._SESSION_JOB)
            require(proof['kill_on_close'] and set(proof['pids'])=={os.getpid()},'metadata observer Job not owner-only')
            report['job']=proof
            budget_error=ValueError('host observation repeated-read forecast exceeds reviewed allowance')
            budget_error.preflight_result=report;raise budget_error
        phase='runtime-body-hashes'
        pins = []
        for path in sorted(files):
            pins.append(_observed_file(path,budget))
        require(before == {str(root):small.inventory(root) for root in sorted(roots)}, 'host runtime membership changed')
        pinmap = {row['path']:row['sha256'] for row in pins}
        cold_names={name for root in cold_roots for name in before[str(root)]}
        cold_names.update(selected['tools'][role] for role in ('git','powershell'))
        result = dict(schema='chopper-hosted-host-v1',status='passed',host=actual_host,channel=selected['channel'],
            preparation_code=selected['preparation_code'],selection_sha256=expected_sha256,
            git_exec_path=str(git_exec),observed_start_ms=int((time.time()-(time.monotonic()-budget.started))*1000),
            tools={role:dict(path=path,sha256=pinmap[path],signature=signatures[role],
                            version=versions.get(role,signatures[role]['version'])) for role,path in selected['tools'].items()},
            browser_version=signatures['browser']['version'],
            input_sizes={path:size for path,size in sizes.items() if path not in cold_names},
            inputs=[row for row in pins if row['path'] not in cold_names],
            input_directories={name:members for name,members in before.items() if Path(name) not in cold_roots},
            preparation=dict(tools={role:dict(path=selected['tools'][role],sha256=pinmap[selected['tools'][role]]) for role in ('git','powershell')},
                input_sizes={path:size for path,size in sizes.items() if path in cold_names},
                inputs=[row for row in pins if row['path'] in cold_names],
                input_directories={name:members for name,members in before.items() if Path(name) in cold_roots}),
            read_forecast_bytes=forecast,read_metric='Python-open bytes plus bootstrap reserve; fixed child probes separately time/capture bounded',usage=budget.usage(),
            workload_started=False,acceptance_window_started=False,scale_slot_consumed=False,original_acquired=False,controller_started=False)
        if 'zstd_dll' in selected:
            result['zstd_dll'] = selected['zstd_dll']
        require(runtime_requirements() == runtime, 'runtime image/root drift')
        for pin in pins:
            _observed_file(pin['path'],budget,pin['sha256'])
        own=small.windows.query_job(small.runner._SESSION_JOB)
        require(own['kill_on_close'] and set(own['pids'])=={os.getpid()},'host observer Job not owner-only')
        result.update(job=own,observer=small.windows.process_identity(os.getpid()))
        small.check_inputs(dict(frozen=[dict(path=path,stat=stamp) for path,stamp in stamps.items()],inventories=before))
        result['usage']=budget.usage()
    except BaseException as error:
        failure=getattr(error,'preflight_result',dict(schema='chopper-hosted-host-v1',status='failed'))
        failure.update(error=type(error).__name__+': '+str(error),phase=phase,probe_path=probe_path,
            usage=budget.usage(),original_acquired=False,workload_started=False,acceptance_window_started=False)
        error.preflight_result=failure
        raise
    finally:
        budget.active=False
        if null_input is not None:null_input.close()
        timer.cancel();timer.join()
        if 'failure' in locals():
            failure['timer_joined']=not timer.is_alive()
            raw=_json_bytes(failure)
            require(len(raw)<=65536,'failed observation receipt bound')
            (destination/('needs-budget.json' if failure['status']=='needs-budget' else 'failure.json')).write_bytes(raw)
    result['timer_joined']=not timer.is_alive()
    raw=_json_bytes(result)
    require(len(raw)<=16*1024**2,'host observation document memory bound')
    (destination/'host.json').write_bytes(raw)
    return dict(path=str(destination/'host.json'),sha256=hashlib.sha256(raw).hexdigest(),
                files=len(pins),timer_joined=result['timer_joined'],qualification=False)


def prepare_host_observation(selection_path, destination, checker):
    """Derive native observation source pins from the current maintained checkout."""
    selection_path, destination = Path(selection_path).absolute(), Path(destination).absolute()
    require(selection_path.stat().st_size <= 65536, 'host selection memory bound')
    selected = json.loads(selection_path.read_bytes())
    require(selected['schema'] == 'chopper-hosted-host-selection-v1', 'host selection schema')
    checker.check_evidence_destination(destination,[Path(checker.__file__).parent.parent,selection_path])
    require(not destination.exists(), 'fresh host-plan destination required')
    selected['tools'] = {role:native_path(path) for role,path in selected['tools'].items()}
    selected['browser_inventory_roots'] = [native_path(path) for path in selected.get('browser_inventory_roots',[])]
    if 'zstd_dll' in selected:
        selected['zstd_dll'] = native_path(selected['zstd_dll'])
    if 'extra_runtime_roots' in selected:
        selected['extra_runtime_roots']=[native_path(path) for path in selected['extra_runtime_roots']]
    selected['preparation_code'] = [dict(path=native_path(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                                    for p in checker.checker_sources()]
    raw = _json_bytes(selected)
    destination.mkdir()
    path = destination/'host-selection.json';path.write_bytes(raw)
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),
        argv=[selected['tools']['python'],'-E','-s','-B',native_path(checker.__file__),
              'packet-host',native_path(path),'$FRESH_HOST_EVIDENCE','--sha256',hashlib.sha256(raw).hexdigest()],
        workload_started=False,acceptance_window_started=False)


def current_process_facts(documents, maximum=4096):
    """Only typed current-run observations; never recurse through input/history data."""
    facts = {}
    def add(pid,birth=None):
        if type(pid) is not int or pid <= 0:return
        known = facts.setdefault(pid,set())
        if type(birth) is int and birth > 0:known.add(birth)
        require(len(facts) <= maximum and len(known) <= 64, 'current process fact bound')
    def observation(value):
        for key in ('runner_pid','supervisor_pid','child_pid','pid'):add(value.get(key))
        for key in ('owned_pids','census_pids'):
            for pid in value.get(key,[]):add(pid)
        for key in ('process_identities','completed_processes','retired_snapshots'):
            for row in value.get(key,[]):
                add(row.get('pid'),row.get('created',row.get('previous_birth')))
                for pid in row.get('fresh_census',{}).get('pids',[]):add(pid)
        for cause in value.get('causes',[])[:4]:
            add(cause.get('pid'))
            for pid in cause.get('fresh_census',{}).get('pids',[]):add(pid)
            held = cause.get('held_observation',{})
            add(held.get('pid'),held.get('birth'))
            lineage = cause.get('census_child_observation',{})
            add(lineage.get('runner_pid'),lineage.get('runner_birth'))
            for pid in lineage.get('pids',[]):add(pid)
            member = lineage.get('process') or {}
            add(member.get('pid'),member.get('created'))
        for event in value.get('sample_trace',[]):observation(event)
    for value in documents:observation(value)
    return [dict(pid=pid,created=sorted(births) or None) for pid,births in sorted(facts.items())]


def process_observation(windows,kernel,pid,expected_birth):
    """A held object may outlive its process. Never query an exited image path."""
    known = ([expected_birth] if type(expected_birth) is int and expected_birth>0 else
             expected_birth if type(expected_birth) is list and 0<len(expected_birth)<=64
             and all(type(v) is int and v>0 for v in expected_birth) else [])
    windows.ctypes.set_last_error(0)
    handle=kernel.OpenProcess(0x100000|0x1000,False,pid)
    error=windows.ctypes.get_last_error()
    row=dict(pid=pid,previous_birth=expected_birth,native_open_error=error,
             status='absent' if not handle and error==87 else 'unavailable')
    if not handle:return row
    try:
        require(kernel.GetProcessId(handle)==pid,'opened process PID mismatch')
        before=windows._held_birth(kernel,handle)
        wait0=kernel.WaitForSingleObject(handle,0)
        code=windows.W.DWORD()
        windows.checked(kernel.GetExitCodeProcess(handle,windows.ctypes.byref(code)))
        after=windows._held_birth(kernel,handle)
        wait1=kernel.WaitForSingleObject(handle,0)
        row.update(actual_birth=before,birth_after=after,wait_before=wait0,wait_after=wait1,exit_code=code.value)
        require(before==after and wait0 in (0,258) and wait1 in (0,258),'process observation changed/unavailable')
        if known and before not in known:row['status']='pid-reused-unrelated-original-ended'
        elif known and wait1==0 and code.value!=259:row['status']='ended-known-birth-signaled'
        else:row['status']='exists-unattributed-or-live'
    except BaseException as error:
        row.update(status='unavailable',error=repr(error))
    finally:
        row['handle_closed']=bool(kernel.CloseHandle(handle))
        if not row['handle_closed']:row['status']='handle-close-unproven'
    return row


def independent_observation(windows, facts, release, original, deadline, result, *, budget=None):
    """Shared ended-process and unchanged Original proof for current controllers."""
    require(release['released_after_supervision'] is True,'explicit Original release proof required')
    result['processes']=[]
    for fact in facts:
        require(time.monotonic()<deadline,'independent process observation deadline')
        row=process_observation(windows,windows.kernel(),fact['pid'],fact['created'])
        result['processes'].append(row)
        if row['status']=='unavailable' and row.get('native_open_error')==5:
            from .native_tiny import complete_snapshot_absence
            row['independent_absence']=complete_snapshot_absence(windows.kernel(),fact['pid'],deadline)
            row['status']='absent-complete-kernel-snapshot'
    import msvcrt
    original=Path(original)
    # This noncreating coordination descriptor is not an output mutation. Only
    # its exact open is exempt; identity, lock, close and all other I/O stay audited.
    active=budget.active if budget is not None else None
    if budget is not None:
        budget.visits+=1;budget.check();budget.active=False
    try:fd=os.open(original,os.O_RDWR)
    finally:
        if budget is not None:budget.active=active
    try:
        actual=os.fstat(fd)
        require([actual.st_dev,actual.st_ino]==release['original_lock_identity']
                and os.path.samestat(actual,original.stat()),'original inode changed')
        os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        result['original_byte0_available']=True
    finally:
        os.close(fd);result['probe_closed']=True
    require(time.monotonic()<deadline and all(row['status'] in
        ('absent','ended-known-birth-signaled','pid-reused-unrelated-original-ended','absent-complete-kernel-snapshot')
        for row in result['processes']),'current process existence/identity unresolved')
    return result


def browser_scale_evidence(candidate, fixture, verified, browser, state, *, recovery=False):
    """Check actual retained Large oracle and public graph, after ownership proof."""
    shape=candidate['shape']
    require(verified['source_sha256']==fixture['sha256'] and verified['rows']==fixture['rows'] and
        verified['shape']==shape and verified['limits']==dict(bytes=10000000,rows=1000000,compressed_bytes=None),
        'complete exact Large independent oracle required')
    expected_status='extracted; independent streaming verification pending' if recovery else 'extracted; independent verification still required'
    require(browser['status']==expected_status and not browser['failures'] and
        browser['channel']==candidate['channel'] and browser['shape']==shape and
        browser['actual_browser_version']==candidate['browser_version'] and state['status']=='complete' and
        state['graph'] and state['graph']['unavailable'] is False and
        not state['graph'].get('truncated') and type(state['graph']['eventsOmitted']) is int and
        state['graph']['eventsOmitted']>=0,
        'complete actual selected browser/public graph required')
    if shape=='G':
        facts=browser['spill_coverage']['facts']
        require(state.get('error') is None and len(state['graph']['steps'])<=1156,
            'successful bounded public graph required')
        expected=[]
        for step in state['graph']['steps']:
            if step.get('kind') not in ('spill','merge','hierarchical_merge','merge_traversal'):continue
            outcomes={name:{key:step['outcomes'][name][key] for key in ('rows','runs','attempts')}
                for name in ('completed','interrupted','failed','handed_off')}
            require(all(type(value)is int and value>=0 for outcome in outcomes.values() for value in outcome.values()) and
                all(not (outcome['rows'] or outcome['runs']) or outcome['attempts']>0 for outcome in outcomes.values()) and
                not any(outcomes['failed'].values()) and
                (step['status']=='completed' or step['kind']=='merge_traversal' and step['status']=='interrupted'),
                'failed or nonterminal physical work cannot qualify')
            expected.append(dict(id=step['id'],kind=step['kind'],status=step['status'],outcomes=outcomes))
        require(facts==expected and any(row['kind']=='spill' and all(row['outcomes']['completed'][key]>0
            for key in ('rows','runs','attempts')) for row in facts),
            'actual completed spill facts must match retained public state')
        completed=any(row['kind']!='spill' and row['outcomes']['completed']['rows']>0 and
            row['outcomes']['completed']['attempts']>0 and
            (row['kind']=='merge_traversal' and row['outcomes']['interrupted']['attempts']==0 or
             row['kind']!='merge_traversal' and row['outcomes']['completed']['runs']>0) for row in facts)
        # Quota assignment can read every row, then Drop without another EOF poll.
        quota=any(row['kind']=='merge_traversal' and row['status'] in ('completed','interrupted') and
            row['outcomes']['interrupted']['attempts']>0 and
            row['outcomes']['completed']['rows']+row['outcomes']['interrupted']['rows']==fixture['rows'] for row in facts)
        require(completed or quota,'actual merge work must cover the successful Run')


def retire_browser_scale_active(candidate, release, budget):
    """Parent retirement after independent quiescence and storage reconciliation."""
    reservation=bound_json(candidate['reservation'])
    if 'time_continuation'in candidate:browser_scale_time_reservation(candidate['time_continuation'],reservation)
    claims=Path(reservation['claims_root'])
    active=claims/'active.lock';stamp=borrowed_input_stamp(active)
    pin=_observed_file(active,budget)
    require(_pinned_bytes(pin,budget,32)==str(release['pid']).encode('ascii'),
        'campaign active owner differs from independently ended controller')
    consumed=claims/(candidate['plan_id']+('.tiny' if candidate['mode']=='qualify' else '')+'.consumed')
    consumed_pin=_observed_file(consumed,budget)
    require(0<float(_pinned_bytes(consumed_pin,budget,64))<=time.time(),'exact permanent consumed claim required')
    require(stamp==borrowed_input_stamp(active),'campaign active file changed before retirement')
    active.unlink()
    return dict(active=pin,owner_pid=release['pid'],consumed=consumed_pin,
        active_retired=True,consumed_retained=True,after_independent_quiescence_and_storage=True)


def browser_scale_after_exit(packet, destination, expected_sha256, checker, *, timer=None):
    """Reuse the independent current-birth/Original proof for the scale schema."""
    packet_declarations(packet,checker);paths=packet['paths'];destination=Path(destination)
    require(destination==Path(paths['after_exit']) and not destination.exists(),'fresh declared independent output')
    destination.mkdir()
    large=packet.get('mode','qualify')=='scale';shape=packet.get('shape','D')
    retire_active=large or 'large_cells' in packet or 'time_continuation'in packet
    mutations=[destination,Path(paths['metadata'])/'storage-ledger.json']
    if retire_active:
        if large:
            claims=Path(_local_binding(packet['large_reservation'])['claims_root'])
        elif 'time_continuation'in packet:
            claims=Path(browser_scale_time_context(packet['time_continuation'])[1]['claims_root'])
        else:
            claims=Path(paths['claims'])
        mutations.append(claims/'active.lock')
    budget=checker.Budget(dict(seconds=30,read_bytes=(2*1024**3 if large else 256*1024**2),
        visits=(2000000 if large else 200000),capture_bytes=65536,storage_bytes=1024**2),destination,
        mutation_roots=mutations)
    if timer is None:timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',qualification=False,profile='browser-scale',packet_sha256=expected_sha256)
    try:
        if large:budget.install()
        small=checker.load('browser-small-runner');batch=Path(paths['owned_root'])/'batch'
        require(not (batch/'owner-retained.json').exists(),'retained owner blocks completion')
        release_path=batch/'reservation-released.json';pin=_observed_file(release_path,budget);release=bound_json(pin)
        require(release['cleanup']['original_release_safe'] and release['released_after_supervision'],
                'explicit positive cleanup/release proof required')
        facts=current_process_facts([dict(process_identities=[dict(pid=release['pid'],created=release['created']),
            *release['cleanup']['processes']])])
        require(facts and all(row['created'] for row in facts),'complete actual current births required')
        independent_observation(small.windows,facts,release,small.module('local-ci').host_lock_path(),budget.started+30,result,budget=budget)
        candidate = bound_json(dict(path=paths['config'],sha256=bound_json(_observed_file(Path(paths['preflight'])/'result.json',budget))['plan_sha256']))
        borrowed = candidate.get('borrowed_input')
        input_path=Path(borrowed['path']) if borrowed else Path(paths['owned_root'])/shape/'input.csv'
        if borrowed:check_borrowed_input(borrowed)
        generated=0
        if input_path.exists():
            if large and release['passed'] is not True:
                require(all(not p.is_symlink() and not getattr(p,'is_junction',lambda:False)()
                    for p in (input_path,*input_path.parents)), 'failed input alias denied')
                stamp=borrowed_input_stamp(input_path)
                generated=stamp[2]
                require(stamp==borrowed_input_stamp(input_path),'failed retained input changed during observation')
                result['retained_incomplete_input']=dict(path=str(input_path),bytes=generated,stat=stamp,
                    fixture_verified=False)
            else:
                require(input_path.stat().st_size==packet['fixture']['bytes'],'actual selected input byte debit')
                _observed_file(input_path,budget,packet['fixture']['sha256']);generated=packet['fixture']['bytes']
        require(not release['passed'] or generated==packet['fixture']['bytes'],'passed journey requires actual fixture')
        reused = generated if borrowed else 0
        if borrowed:generated=0
        pref_path=Path(paths['preflight'])/'result.json';pref_pin=_observed_file(pref_path,budget)
        preflight(pref_pin,paths['config'],'browser-scale')
        admission = batch_admission(candidate,'browser-scale',packet['host_receipt']['channel'])
        if large and release['passed'] is True:
            from .browser_scale_identity import scale_fixture
            require(candidate['mode']=='scale' and candidate['fixture']==scale_fixture(shape), 'exact Large fixture required')
            verified_pin=_observed_file(Path(paths['owned_root'])/'verified.json',budget)
            verified=bound_json(verified_pin,8*1024**2)
            if candidate.get('peer'):
                require(verified==bound_json(candidate['peer'],8*1024**2),'Large peer membership/order/name/hash drift')
            work=Path(paths['owned_root'])/'work'
            browser_pin=_observed_file(work/'browser-receipt.json',budget);browser=bound_json(browser_pin)
            state_pin=_observed_file(work/'public-state.json',budget);state=bound_json(state_pin)
            browser_scale_evidence(candidate,packet['fixture'],verified,browser,state)
            result.update(status='passed-after-exit',scale_cell_passed=True,source_receipts=[pin,verified_pin,browser_pin,state_pin],
                channel=candidate['channel'],shape=shape,fixture=packet['fixture'],product=candidate['source'],
                package=candidate['package'],generated_input_bytes=generated,reused_input_bytes=0,batch_admission=admission,
                graph_event_details_omitted=state['graph']['eventsOmitted'],
                peer_parity='passed' if candidate.get('peer') else 'pending same-input other-channel receipt')
        elif large:
            result.update(status='passed-after-exit',scale_cell_passed=False,source_receipts=[pin],
                channel=candidate['channel'],shape=shape,generated_input_bytes=generated,reused_input_bytes=0,
                batch_admission=admission,reason='controller failed; independent ownership/Original proof only')
        else:
            proof=receipt('browser-scale',packet['host_receipt']['channel'],pref_pin,passed=release['passed'],
                details=dict(mode='tiny-D',fixture=packet['fixture'],generated_input_bytes=generated,reused_input_bytes=reused,
                             execution_kind=candidate.get('execution_kind','qualification'),batch_admission=admission,
                             cleanup=release['cleanup'],release=pin,independent_processes=result['processes']))
            proof_path=destination/'tiny-receipt.json';proof_path.write_bytes(_json_bytes(proof))
            result.update(status='passed-after-exit',qualification_passed=release['passed'],source_receipts=[pin],
                generated_input_bytes=generated,reused_input_bytes=reused,batch_admission=admission,qualification_receipt=dict(path=str(proof_path),sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest()))
        partition=packet['origin']['metadata']['storage_priming'];storage=small.primed_storage(partition,[])
        fresh=retained_packet_roots(packet,fresh=True)
        storage.roots.extend(Path(p) for p in [*fresh,paths['source'],paths['metadata']])
        total=storage.sample()+1024**2
        require(total<small.LIMITS['stop_owned_bytes'],'final aggregate cap')
        ledger=dict(method='sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny',
            cumulative_owned_bytes=total,covered_roots=[*partition['covered_roots'],*fresh,paths['source'],paths['metadata']],
            unseen_transient_allocations='UNKNOWN; sampled logical union is not physical highwater')
        (Path(paths['metadata'])/'storage-ledger.json').write_bytes(_json_bytes(ledger))
        result['cumulative_owned_bytes']=total
        if retire_active:
            result['campaign_active_retirement']=retire_browser_scale_active(candidate,release,budget)
        budget.check();return result
    except BaseException as error:
        result.update(status='failed',error=repr(error))
        for key in ('scale_cell_passed','qualification_passed'):
            if key in result:result[key]=False
        raise
    finally:
        budget.active=False
        timer.cancel();timer.join();result['timer_joined']=not timer.is_alive();result['usage']=budget.usage()
        (destination/'result.json').write_bytes(_json_bytes(result))


def picker_release_facts(plan, report, private, births):
    """Current picker cleanup schema only; historical accounting is never a PID source."""
    from hosted_picker.control import require_private_cleanup
    owner=report['reservation']['owner']
    require(report['originalReservationClosedAfterQuiescence'] is True and not report.get('releaseBlocked'), 'normal picker Original close required')
    require(report['reservation']['identity']==plan['original_lock']['identity'] and report['outerFinal']['pids']==[owner['pid']], 'picker Original/outer Job mismatch')
    require(report['diskSamplerJoined'] is True and report['watchdogJoined'] is True and 'diskStopError' not in report, 'joined picker monitors required')
    identities=[owner];pids=[]
    if report.get('noWorkerLaunched') is True:
        require(private is None and not births and report['innerFinal'] is None and 'workerBirth' not in report and 'privateCleanup' not in report, 'no-worker picker proof contains uncertain launch')
        require(report.get('observationComplete') is False and report.get('smokeCaseQualified') is False, 'no-worker cannot qualify a case')
    else:
        require(isinstance(private,dict),'private picker cleanup receipt required')
        require_private_cleanup(private)
        require(report['privateCleanup']==private['privateCleanup'] and private['privateCleanup']['owner']==report['workerBirth']['pid'], 'private worker mismatch')
        require(report['innerFinal']['pids']==[] and report['parentPipeEOF']==dict(stdout=True,stderr=True), 'picker inner Job/EOF incomplete')
        require(private['serverStopped'] is True and private['helperTempCleanup']['complete'] is True and 'diagnosticHandleCleanupError' not in private, 'picker server/helper/handle cleanup incomplete')
        identities += [report['workerBirth'],*births]
        if private.get('browserIdentity'):identities.append(private['browserIdentity'])
        forests=private.get('diagnosticForests',[]);require(len(forests)<=32,'picker forest bound')
        for forest in forests:
            identities += forest.get('identities',[])+forest.get('retiredIdentities',[])
            pids += forest.get('captured',{}).get('pids',[])
            if forest.get('last'):pids += forest['last'].get('pids',[])
            if forest.get('membershipChange'):
                for name in ('expected','actual'):
                    snapshot=forest['membershipChange'].get(name)
                    require(isinstance(snapshot,dict) and isinstance(snapshot.get('pids'),list),
                        'picker membership '+name+' census requires its PID list')
                    pids += snapshot['pids']
    def census(value):
        for key in ('outer','workerJob'):
            if value.get(key):pids.extend(value[key]['pids'])
    for name in ('jobCensusInitial','jobCensusLast'):
        if report.get(name):census(report[name])
    for row in report.get('extraOuterFirstSeen',{}).values():
        pids.append(row['pid'])
        if row.get('identity'):identities.append(row['identity'])
        if row.get('census'):census(row['census'])
    facts=current_process_facts([dict(process_identities=identities,census_pids=pids)])
    require(facts,'current picker owner identity required')
    return dict(released_after_supervision=True,original_lock_identity=report['reservation']['identity']),facts


def picker_after_exit(packet,destination,expected_sha256,checker,receipt_sha256,*,timer=None):
    """Existing independent observer applied to current actual-picker receipts."""
    require(packet['schema']=='chopper-picker-after-exit-v1' and packet['profile']=='actual-picker','picker independent request schema')
    require(receipt_sha256 and re.fullmatch('[0-9a-f]{64}',receipt_sha256),'actual terminal picker receipt SHA required')
    root=Path(packet['root']);destination=Path(destination)
    require(destination==Path(packet['output']) and not destination.exists(),'fresh declared picker independent output')
    require(Path(packet['configuration'])==root/'candidate.json' and Path(packet['receipt'])==root/'attempt1/receipt.json','exact current picker paths required')
    require(destination==root/'after-exit','independent artifacts must stay in the existing owned case root')
    checker.check_evidence_destination(destination,[Path(checker.__file__).parent.parent,Path(packet['configuration']),Path(packet['receipt'])])
    budget=checker.Budget(dict(seconds=30,read_bytes=128*1024**2,visits=200000,capture_bytes=65536,storage_bytes=1024**2),destination)
    if timer is None:timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',profile='actual-picker',qualification=False,request_sha256=expected_sha256,receipt_sha256=receipt_sha256)
    try:
        small=checker.load('browser-small-runner');small.runner.contain_session()
        budget.install()
        report=bound_json(dict(path=packet['receipt'],sha256=receipt_sha256))
        plan=bound_json(dict(path=packet['configuration'],sha256=report['configSha256']))
        require(plan['root']==packet['root'] and report['profile']=='actual-picker' and report['channel']==plan['channel'] and report['case']==plan['case'],'current picker case/config mismatch')
        require(plan['original_lock']==packet['original_lock'],'independent Original baseline drift')
        require(report['preflight']['path']==packet['preflight'],'exact current picker preflight path')
        preflight(report['preflight'],packet['configuration'],'actual-picker')
        checker.check_evidence_destination(destination,[Path(plan['controller_root']),*[Path(name) for name in plan['input_directories']]])
        private=None;births=[]
        if report.get('noWorkerLaunched') is not True:
            private=bound_json(_observed_file(root/'attempt1/worker-result.json',budget))
            names=private['captureNames'];require(len(names)<=16 and len(set(names))==len(names),'bounded picker capture names')
            for name in names:
                require(re.fullmatch('[a-z][a-z0-9_-]{0,31}',name),'unsafe picker birth leaf')
                births.append(bound_json(_observed_file(root/'attempt1'/(name+'.birth.json'),budget)))
        release,facts=picker_release_facts(plan,report,private,births)
        destination.mkdir()
        independent_observation(small.windows,facts,release,packet['original_lock']['path'],budget.started+30,result,budget=budget)
        result.update(status='passed-after-exit',smoke_case_qualification_passed=bool(report.get('smokeCaseQualified')),no_worker=bool(report.get('noWorkerLaunched')))
        budget.check();return result
    except BaseException as error:
        result['error']=repr(error);error.preflight_result=result;raise
    finally:
        budget.active=False;timer.cancel();timer.join();result['timer_joined']=not timer.is_alive();result['usage']=budget.usage()
        if destination.exists():
            raw=_json_bytes(result);require(len(raw)<=budget.limits['storage_bytes'],'picker independent receipt storage bound')
            (destination/'result.json').write_bytes(raw)


def after_exit(packet_path,destination,expected_sha256,checker,*,timer=None,receipt_sha256=None):
    """Independent current-birth and unchanged-original byte-zero observation."""
    require(os.name=='nt','after-exit observation requires actual Windows')
    packet=bound_json(dict(path=str(Path(packet_path).absolute()),sha256=expected_sha256))
    if packet.get('schema')=='chopper-picker-after-exit-v1':return picker_after_exit(packet,destination,expected_sha256,checker,receipt_sha256,timer=timer)
    require(receipt_sha256 is None,'unused actual-picker receipt SHA')
    if packet.get('operation')==RECOVERY_OPERATION:return recovery_after_exit(packet,destination,expected_sha256,checker,timer=timer)
    if packet.get('profile')=='browser-scale':return browser_scale_after_exit(packet,destination,expected_sha256,checker,timer=timer)
    packet_declarations(packet,checker)
    destination=Path(destination)
    checker.check_evidence_destination(destination,[Path(packet['paths']['root']),Path(packet['paths']['owned_root'])])
    require(not destination.exists(),'fresh independent observation output required')
    destination.mkdir()
    budget=checker.Budget(dict(seconds=30,read_bytes=256*1024**2,visits=200000,
        capture_bytes=65536,storage_bytes=1024**2),destination)
    if timer is None:
        timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    result=dict(status='failed',qualification=False,packet_sha256=expected_sha256)
    try:
        small=checker.load('browser-small-runner');owned=Path(packet['paths']['owned_root'])
        require(not (owned/'owner-retained.json').exists(),'retained owner blocks independent completion')
        proofs=[];release=[None]
        def documents():
            count=0
            for name in ('job.json','job-owned.json','ready.json','runner-observation.json','control-failure.json','reservation-released.json'):
                path=owned/name
                if not path.exists():continue
                pin=_observed_file(path,budget);proofs.append(pin)
                budget.read_bytes+=path.stat().st_size;budget.check()
                value=bound_json(pin)
                if 'original_lock_identity' in value:release[0]=value
                yield value
            for path in [owned/'guard-history.jsonl',*(owned/('command-'+str(i)+'.jsonl') for i in range(1,16))]:
                if not path.exists():continue
                pin=_observed_file(path,budget);proofs.append(pin)
                with path.open('rb') as stream:
                    budget.read_bytes+=path.stat().st_size;budget.check()
                    while line:=stream.readline(small.Receipts.MAX_BYTES+1):
                        require(len(line)<=small.Receipts.MAX_BYTES,
                            f'current observation line memory bound: {path}; observed_at_least={len(line)}, maximum={small.Receipts.MAX_BYTES}')
                        count+=1;require(count<=200000,'current observation count bound')
                        budget.check();yield json.loads(line)
                _observed_file(path,budget,pin['sha256'])
        facts=current_process_facts(documents())
        release=release[0]
        require(release,'explicit Original release proof required')
        independent_observation(small.windows,facts,release,
            small.module('local-ci').host_lock_path(),budget.started+30,result)
        budget.check();result.update(status='passed-after-exit',source_receipts=proofs,usage=budget.usage())
        return result
    except BaseException as error:
        result['error']=repr(error);raise
    finally:
        timer.cancel();timer.join();result['timer_joined']=not timer.is_alive()
        raw=_json_bytes(result);require(len(raw)<=1024**2,'independent result disk bound')
        (destination/'result.json').write_bytes(raw)


def prepare_image_control(selection_path,destination,checker):
    """Freeze the one real held-child image-query discriminator, not a batch."""
    selection_path,destination=Path(selection_path).absolute(),Path(destination).absolute()
    require(selection_path.stat().st_size<=65536,'component selection memory bound')
    selected=json.loads(selection_path.read_bytes())
    require(selected['schema']=='chopper-hosted-image-exit-selection-v1','component selection schema')
    _window(_local_binding(selected['window']),seconds=60)
    checker.check_evidence_destination(destination,[Path(checker.__file__).parent.parent,selection_path])
    require(not destination.exists(),'fresh component preparation output required')
    selected['schema']='chopper-hosted-image-exit-control-v1'
    selected['python']['path']=native_path(selected['python']['path'])
    selected['window']['path']=native_path(selected['window']['path'])
    selected['preparation_code']=[dict(path=native_path(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in checker.checker_sources()]
    destination.mkdir();path=destination/'image-control.json';raw=_json_bytes(selected);path.write_bytes(raw)
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),
        argv=[selected['python']['path'],'-E','-s','-B',native_path(checker.__file__),'image-exit',
              native_path(path),'$FRESH_COMPONENT_OUTPUT','--sha256',hashlib.sha256(raw).hexdigest()],
        qualification=False,original_acquired=False,workload_started=False)


def image_exit_control(selection_path,destination,expected_sha256,checker,*,timer=None):
    """Hold a real process query handle across its actual exit, using the owning helper."""
    require(os.name=='nt','image-query component requires actual Windows')
    selected=bound_json(dict(path=str(Path(selection_path).absolute()),sha256=expected_sha256),1024**2)
    require(selected['schema']=='chopper-hosted-image-exit-control-v1','component selection schema')
    _window(bound_json(selected['window']),seconds=60)
    destination=Path(destination)
    checker.check_evidence_destination(destination,[Path(checker.__file__).parent.parent,Path(selection_path)])
    require(not destination.exists(),'fresh component observation output required')
    destination.mkdir()
    if timer is None:
        timer=threading.Timer(30,lambda:os._exit(124));timer.daemon=True;timer.start()
    budget=checker.Budget(dict(seconds=30,read_bytes=128*1024**2,visits=200000,
        capture_bytes=65536,storage_bytes=1024**2),destination)
    budget.read_bytes=64*1024**2;budget.visits=8192
    child=inner=small=original=out=err=None;closed=False;reaped=False;errors=[]
    result=dict(status='failed',qualification=False,Chopper=False,browser=False,original_acquired=False,
                fixture_bytes=0,request_sha256=expected_sha256)
    try:
        small=checker.load('browser-small-runner');small.runner.contain_session()
        from .native_scale_windows import create_job,SuspendedWorker
        _observed_file(selected['python']['path'],budget,selected['python']['sha256'])
        require(Path(selected['python']['path'])==Path(sys.executable),'component actual Python mismatch')
        inner=create_job(small.windows);child=SuspendedWorker()
        from .native_scale_identity import runtime_requirements
        _,runtime_files=runtime_requirements()
        result['observed_runtime']=[_observed_file(path,budget) for path in sorted(runtime_files)]
        result['runtime_scope']='observed inspector runtime; not a product qualification or learned admission binding'
        out=(destination/'child-stdout.log').open('xb');err=(destination/'child-stderr.log').open('xb')
        argv=[selected['python']['path'],'-I','-B','-c','pass']
        child.start(argv,out,err,dict(os.environ));child.assign(inner)
        held=small.windows.held_identity(child.handle,child.pid)
        require(held['parent']==os.getpid() and Path(held['image'])==Path(selected['python']['path']), 'held child provenance mismatch')
        census=small.windows.query_job(inner)
        require(census['kill_on_close'] and census['pids']==[child.pid],'exact child-only Job required')
        result.update(argv=argv,held_child=held,initial_census=census)
        original=small.windows._held_identity
        transition={}
        result['transition']=transition
        def exit_while_query_held(dll,handle,pid):
            nonlocal closed,reaped
            require(not transition and pid==child.pid,'component transition may occur once on actual child')
            transition['query_birth_before']=small.windows._held_birth(dll,handle,pid)
            require(transition['query_birth_before']==held['created'],'query handle child birth mismatch')
            child.resume();deadline=time.monotonic()+5
            while True:
                require(all(os.fstat(stream.fileno()).st_size<=65536 for stream in (out,err)), 'component capture bound')
                try:
                    code=child.wait(.025);break
                except subprocess.TimeoutExpired:
                    require(time.monotonic()<deadline,'controlled child exit deadline')
            reaped=True
            require(code==0,'fixed child did not exit normally')
            child.close();closed=True
            transition.update(child_exit_code=code,query_birth_after=small.windows._held_birth(dll,handle,pid),
                query_wait=dll.WaitForSingleObject(handle,0),raw_job=small.windows.query_job(inner))
            require(transition['query_birth_after']==held['created'] and transition['query_wait']==0,'held child end proof mismatch')
            try:return original(dll,handle,pid)
            except small.windows.ProcessImageQueryError as error:
                transition['raw_image_error']=dict(api=error.api,pid=error.pid,winerror=error.winerror)
                raise
        small.windows._held_identity=exit_while_query_held
        started=time.monotonic()
        try:
            sampled=small.windows.job_processes(inner,census,[held])
            result.update(sampler_status='passed',sampled=sampled)
        except small.windows.ProcessImageQueryError as error:
            result.update(sampler_status='denied-image-query',error=dict(api=error.api,pid=error.pid,winerror=error.winerror,
                held_observation=getattr(error,'held_observation',None),fresh_census=getattr(error,'fresh_census',None)))
        require(all(os.fstat(stream.fileno()).st_size<=65536 for stream in (out,err)), 'component capture bound')
        result.update(component_seconds=time.monotonic()-started,transition=transition,status='observed')
        require(transition and reaped and closed,'real held-query exit transition incomplete')
    except BaseException as error:
        result['primary_error']=dict(kind=type(error).__name__,error=str(error)[:4096],
            api=getattr(error,'api',None),pid=getattr(error,'pid',None),winerror=getattr(error,'winerror',None),
            process_handle_close_uncertain=bool(getattr(error,'process_handle_close_uncertain',False)))
        raise
    finally:
        if original is not None:small.windows._held_identity=original
        def attempt(phase,action):
            try:return action()
            except BaseException as error:errors.append(dict(phase=phase,error=repr(error)))
        if child is not None and not reaped:
            attempt('stop-owned-child',child.kill)
            code=attempt('reap-owned-child',lambda:child.wait(5));reaped=code is not None
        if child is not None and not closed:
            before=len(errors);attempt('close-owned-child',child.close);closed=len(errors)==before
        for stream in (out,err):
            if stream is not None:attempt('close-capture',stream.close)
        if inner is not None:
            proof=attempt('final-child-job',lambda:small.windows.query_job(inner))
            if proof is None or proof['pids']:errors.append(dict(phase='child-job-empty',error='not proved'))
            attempt('close-child-job',lambda:small.windows.close(inner))
        if small is not None:
            proof=attempt('outer-job',lambda:small.windows.query_job(small.runner._SESSION_JOB))
            if proof is None or not proof['kill_on_close'] or set(proof['pids'])!={os.getpid()}:
                errors.append(dict(phase='outer-owner-only',error='not proved'))
            result['observer']=attempt('observer-birth',lambda:small.windows.process_identity(os.getpid()))
            result['outer_job']=proof
        timer.cancel();timer.join()
        result.update(child_reaped=reaped,child_closed=closed,captures_closed=all(s is None or s.closed for s in (out,err)),
                      timer_joined=not timer.is_alive(),cleanup_errors=errors,usage=budget.usage())
        if errors:result['status']='failed-cleanup'
        raw=_json_bytes(result);require(len(raw)<=65536,'component result memory bound')
        (destination/'result.json').write_bytes(raw)
    require(not errors,'component cleanup unresolved')
    return result


def host_implementation(observed,producer_commit,repository,checker):
    """Reuse observed data only across reviewed, unrelated consumer edits.

    Historical producer bodies remain Git objects, never evidence-directory code.
    Every other module and every observer/called metadata function stays identical.
    """
    repository=Path(repository)
    current=[dict(path=native_path(p),sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest()) for p in checker.checker_sources()]
    if observed['preparation_code']==current:return dict(status='identical-producer',changed_files=[])
    expected={Path(p).resolve().relative_to(repository).as_posix() for p in checker.checker_sources()}
    anchors=[PureWindowsPath(row['path']) for row in observed['preparation_code']
             if PureWindowsPath(row['path']).parts[-2:]==('scripts','acceptance-preflight.py')]
    require(len(anchors)==1,'unique historical producer entrypoint required')
    native_root=anchors[0].parent.parent
    rows={PureWindowsPath(row['path']).relative_to(native_root).as_posix():row['sha256'] for row in observed['preparation_code']}
    require(len(rows)==len(observed['preparation_code']) and set(rows)==expected,'host producer source closure mismatch')
    changed={name:digest for name,digest in rows.items() if hashlib.sha256((repository/name).read_bytes()).hexdigest()!=digest}
    if not changed:return dict(status='identical-producer',changed_files=[])
    require(isinstance(producer_commit,str) and len(producer_commit)==40
            and all(c in '0123456789abcdef' for c in producer_commit),'exact historical host producer commit required')
    # Preserve the frozen campaign rules; new tooling edits need fresh observation.
    from . import campaign_host_observer_v1 as campaign
    reviewed_consumers = campaign.REVIEWED_CONSUMERS
    unrelated = campaign.UNRELATED
    # The observer uses stamp/inventory/check_inputs, session containment and
    # process_identity/query_job; none calls the consumer I/O or census above.
    added_imports = campaign.ADDED_IMPORTS
    relevant = campaign.relevant
    for name,digest in rows.items():
        previous=subprocess.check_output(['git','-C',str(repository),'show',producer_commit+':'+name],timeout=10)
        require(hashlib.sha256(previous).hexdigest()==digest,'historical producer Git body mismatch: '+name)
        if name in changed:
            if name in reviewed_consumers and hashlib.sha256((repository/name).read_bytes()).hexdigest()==reviewed_consumers[name]:continue
            require(name in unrelated and relevant(previous,unrelated[name],name)==relevant((repository/name).read_bytes(),unrelated[name],name),
                    'actual host observer/helper implementation changed: '+name)
    return dict(status='observer-and-metadata-helpers-identical',producer_commit=producer_commit,
                changed_files=sorted(changed),excluded_functions={name:sorted(unrelated[name]) for name in changed if name in unrelated},
                pinned_consumer_bodies={name:reviewed_consumers[name]for name in changed if name in reviewed_consumers},
                excluded_imports={name:list(added_imports[name]) for name in changed if name in added_imports},
                default_writer='exact default AST; only reviewed optional callback normalized',
                default_module_loader='exact default AST; only reviewed optional selected-root extension normalized')
