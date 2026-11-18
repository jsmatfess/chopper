"""Exact, bounded inputs for the retained actual-picker controller; no launch."""
import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
import stat
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
SOURCE = '639d1fe97d985b1544df0932321c6a93cca2567b'
TREE = 'b3bde79d552ee29760cb283d07938f9248cee0bb'
BUILD = 'feb9e099e5e0f22c4da8d0f5ba7269e221c91e9d'
INPUT_HASH = 'ecbed63ad30d497bcbaf3ad45ec86b0ab6651215e6d086bf87afe157fb3e610b'
IMAGES = {'chrome': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
          'msedge': r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'}
DOCUMENTS = {'package-binding.json', 'custody.json', 'uia-binding.json', 'input-layout.json',
             'output-layout.json', 'permission-layout.json', 'job.json', 'accounting.json'}


def path(value):
    p = Path(value)
    assert p.is_absolute() and '..' not in p.parts, 'absolute canonical path required'
    for q in (p, *p.parents):
        try:
            info = q.lstat()
        except FileNotFoundError:
            continue
        assert not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, 'alias/reparse path'
    return p


def stamp(p):
    s = path(p).stat()
    # Immutable source aliases keep the existing SMALL rule; owned outputs,
    # the reused input and selected ZIP retain their separate single-link gates.
    assert stat.S_ISREG(s.st_mode), 'regular immutable input required'
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def inventory(root):
    root = path(root)
    assert root.is_dir(), 'inventory root missing'
    names = []
    def fail(error):
        raise error
    for base, dirs, files in os.walk(root, onerror=fail):
        for name in dirs + files:
            path(Path(base) / name)
        names.extend(str(Path(base) / name) for name in files)
    return sorted(names)


def read(p, maximum=16*1024**2, *, expected_sha256=None):
    before = stamp(p)
    assert before[2] <= maximum, 'input JSON bound'
    raw = Path(p).read_bytes()
    assert stamp(p) == before, 'JSON changed during read'
    if expected_sha256 is not None:
        assert hashlib.sha256(raw).hexdigest()==expected_sha256, 'JSON expected hash drift'
    def unique(pairs):
        value = {}
        for key, item in pairs:
            assert key not in value, 'duplicate JSON field'
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def storage_limits(plan):
    owned, growth = plan['owned_cap_bytes'], plan['growth_bytes']
    assert type(owned) is int and owned in (256*1024**2, 672*1024**2, 32*1024**3), 'reviewed owned storage limit required'
    maximum = 4*1024**3 if owned == 32*1024**3 else (10 if owned == 256*1024**2 else 32)*1024**2
    assert type(growth) is int and 0 < growth <= maximum, 'reviewed aggregate growth limit required'
    expanded = owned == 32*1024**3
    return dict(stop=owned-(8*1024**3 if expanded else 8*1024**2),
                profile=2*1024**3 if expanded else 20*1024**2,
                temp=512*1024**2 if expanded else 4*1024**2)


def storage_stop(plan):
    return storage_limits(plan)['stop']


def physical_capacity(plan):
    # One explicit shared C: volume; no extrapolation from separate packet caps.
    if plan.get('owned_cap_bytes') == 32*1024**3:
        free = shutil.disk_usage('C:/').free
        assert free-plan['growth_bytes'] >= 128*1024**3, 'physical C: headroom after planned new growth'
        return free


def validate(p, *, fresh=True, producer_root=None, preparing=False):
    assert not sys.flags.optimize, 'assertions are acceptance gates'
    assert p['schema'] == 'chopper-hosted-picker-qualification-v1'
    scripts=path(p['controller_root'])/'scripts'
    assert scripts == (SCRIPTS if producer_root is None else path(producer_root)/'scripts'), 'selected controller root mismatch'
    assert p['channel'] in IMAGES and p['case'] in ('success', 'failure', 'observe-input', 'observe-output', 'observe-permission', 'processing-cancel', 'export-cancel', 'malformed-retry')
    assert p['product'] == dict(commit=SOURCE, tree=TREE, runtime_build=BUILD), 'product bytes unchanged'
    root = path(p['root'])
    assert root.parent == Path('C:/') and root.name.startswith('hosted105-'), 'owned #105 namespace'
    assert root.is_dir() or (preparing and not root.exists()), 'existing owned namespace required'
    assert not fresh or not (root / 'attempt1').exists(), 'no resume/retry'
    assert p['seconds'] == 180 and p['input_cap_bytes'] == 1024**2
    storage_stop(p)
    assert p['browser']['path'].casefold() == IMAGES[p['channel']].casefold(), 'selected installed channel image'
    assert p['browser_version'] and p['parent_reviewed'] is True, 'reviewed browser binding required'
    assert p['toolchains']['python_version'] == sys.version
    assert Path(p['python']['path']).resolve() == Path(sys.executable).resolve(), 'selected Python required'
    lock=p['original_lock'];lock_path=path(lock['path'])
    assert lock_path == Path.home()/'.chopper/local-ci.lock', 'original host lock path required'
    lock_stat=lock_path.stat()
    assert stat.S_ISREG(lock_stat.st_mode) and [lock_stat.st_dev,lock_stat.st_ino]==lock['identity'], 'original lock identity drift'
    assert p['profile']['channel'] == p['channel'], 'profiles cannot cross channels'
    profile = path(p['profile']['path'])
    assert type(p['profile']['reuse']) is bool
    if p['profile']['reuse']:
        assert profile.is_dir() and p['profile']['nativeIdentity'], 'explicit retained profile identity required'
        if p['channel'] == 'msedge':
            prior = p['profile']['prior_receipt']
            row = read(prior['path'])
            assert hashlib.sha256(Path(prior['path']).read_bytes()).hexdigest() == prior['sha256']
            assert (row['tinyCaseQualified'] is True or row.get('diagnosticComplete') is True) and row['originalReservationClosedAfterQuiescence'] is True
            assert row['browserProfile'] == dict(path=str(profile), channel='msedge', nativeIdentity=p['profile']['nativeIdentity']), 'Edge profile needs its own actual quiescent receipt'
    else:
        assert profile == root / 'attempt1/profile' and (not fresh or not profile.exists()), 'fresh channel-specific profile required'
    assert set(p['documents']) == DOCUMENTS
    assert hashlib.sha256(Path(p['documents']['job.json']).read_bytes()).hexdigest() == '1887e06beeffdf116b76469975c589af4f49036b30079833f6b0dff0e4142442', 'exact original tiny Job required'
    declared = {e['path']: e for e in p['inputs']}
    assert len(declared) == len(p['inputs']) and declared, 'unique complete input inventory'
    assert str(scripts / 'hosted_picker') in p['input_directories'], 'complete maintained picker source inventory required'
    required = [str(f) for f in scripts.joinpath('hosted_picker').iterdir() if f.is_file()]
    required += [str(scripts / n) for n in ('validation-runner.py', 'browser-small-windows.py')]
    required += [str(scripts / 'scale_acceptance' / n) for n in
                 ('hosted_qualification.py', 'verify.py', 'guard.py')]
    required += [p[k]['path'] for k in ('python', 'node', 'browser')]
    required += list(p['documents'].values())
    custody=read(p['documents']['custody.json'])
    required += [*custody['retainedInputPaths'],custody['selectedZIP']['path']]
    runtime = read(p['documents']['uia-binding.json'])
    uia_files = [runtime['powershell'], *runtime['assemblies'].values(), *runtime['nativeImages'].values()]
    required += [row['path'] for row in uia_files]
    assert all(row['path'] in declared and declared[row['path']]['sha256'] == row['sha256']
               for row in uia_files), 'UIA runtime must belong to the frozen input inventory'
    required += [p['input']['path'], p['source_selection']['path']]
    anchor = p['historical_anchor']
    assert anchor == dict(path=r'C:\hosted105-tiny-export-r31\attempt1\receipt.json',
        sha256='6d1e80caeac181d9670fd7f72ea44f1bb5fbd6a085b542621537fabf86e68e0a'), 'original R31 history anchor required'
    required.append(anchor['path'])
    assert anchor['path'] in declared and declared[anchor['path']]['sha256'] == anchor['sha256']
    sys.path.insert(0,str(SCRIPTS))
    from hosted_picker import suite as policy
    assert Path(policy.__file__).resolve()==(SCRIPTS/'hosted_picker/suite.py').resolve(), 'selected history validator module required'
    policy.validate_history(p,read(p['documents']['accounting.json']))
    if p['profile']['reuse'] and p['channel'] == 'msedge':
        required.append(p['profile']['prior_receipt']['path'])
    selection = read(p['source_selection']['path'])
    assert hashlib.sha256(Path(p['source_selection']['path']).read_bytes()).hexdigest() == p['source_selection']['sha256']
    assert selection['source_commit'] == SOURCE and selection['source_tree'] == TREE
    assert all(e['path'] in declared and declared[e['path']]['sha256'] == e['sha256'] for e in selection['inputs']), 'complete selected source/runtime inventory required'
    for directory in selection['input_directories']:
        expected = sorted(e['path'] for e in selection['inputs'] if Path(e['path']).is_relative_to(Path(directory)))
        assert p['input_directories'].get(directory) == inventory(directory) == expected, 'selected inventories cannot be shortened or expanded'
    assert all(name in declared for name in required), 'undeclared controller/runtime/document dependency'
    assert all(p[k]['sha256'] == declared[p[k]['path']]['sha256'] for k in ('python', 'node', 'browser'))
    for directory, expected in p['input_directories'].items():
        assert inventory(directory) == expected and all(name in declared for name in expected), 'complete directory inventory drift'
    # Enumerate full selected dependency/runtime roots, rather than just their entry point.
    assert p['playwright_root'] in p['input_directories']
    spec = read(p['documents']['package-binding.json'])
    assert spec['source_commit'] == SOURCE and spec['source_tree'] == TREE and spec['runtime_build_commit'] == BUILD
    assert spec['package'] == dict(bytes=873522, sha256='c321df0c684439da7c622578b7685705cbf667e65f0039d7318674c7fc1f8e9d'), 'exact selected hosted package required'
    custody = read(p['documents']['custody.json'])
    assert custody['selectedZIP']['path'] in declared and declared[custody['selectedZIP']['path']]['sha256'] == spec['package']['sha256']
    needed = [] if p['case']=='observe-input' else ['input-layout.json'] if p['case']=='observe-output' else ['input-layout.json','output-layout.json'] if p['case']=='observe-permission' else ['input-layout.json','output-layout.json','permission-layout.json']
    for name in needed:
        layout = read(p['documents'][name])
        assert layout['channel'] == p['channel'] and layout['reviewed'] is True and layout['receipt_sha256'], 'channel-specific actual layout review required'
        assert layout['receipt_path'] in declared and declared[layout['receipt_path']]['sha256'] == layout['receipt_sha256']
    assert p['runtime_roots'] and all(root in p['input_directories'] for root in p['runtime_roots'])
    for e in p['inputs']:
        before = stamp(e['path'])
        assert before == e['stat'], 'input metadata drift: ' + e['path']
        h = hashlib.sha256()
        with Path(e['path']).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                h.update(chunk)
        assert h.hexdigest() == e['sha256'] and stamp(e['path']) == before, 'input hash drift: ' + e['path']
    expected_input=(220002,'a1ebd4884d59708be9726030be67b918cf449f50b9e652cfb73f75c7d96387a7') if p['case'] in ('processing-cancel','export-cancel') else (53,INPUT_HASH)
    assert (p['input']['bytes'],p['input']['sha256'])==expected_input, 'selected case input binding'
    if p['case'] in ('processing-cancel','export-cancel'):
        assert Path(p['input']['path'])==Path(r'C:\native105-cancel-renewed-r1\cancel.csv'), 'already debited cancellation input required'
    assert declared[p['input']['path']]['sha256'] == expected_input[1]
    if p['case']=='malformed-retry':
        malformed=p['malformed_input']
        assert malformed['path']==r'C:\desktop105-native-faults-r1\malformed.csv' and malformed['bytes']==63 and malformed['sha256']=='9161b910f538d8611ec4e6324f893af7cf35d199cac516c4fe59696e9f1da45e'
        assert malformed['path'] in custody['retainedInputPaths'] and declared[malformed['path']]['sha256']==malformed['sha256'], 'already debited malformed fixture required'
        from hosted_picker import suite as policy
        policy.verify_malformed_input(malformed)
    else:assert 'malformed_input' not in p, 'unused case input declaration'
    assert p['retained_evidence'] and all(row['path'] in declared and declared[row['path']]['sha256'] == row['sha256'] for row in p['retained_evidence']), 'all retained references must be inputs'
    # The common receipt binds the full configuration by SHA; retain it once.
    return dict(bindings=dict(product=p['product'], controller_root=p['controller_root'],
        channel=p['channel'], case=p['case'], source_selection=p['source_selection']),
        runtime_pending=['actual pickers/permission/public Run',
        'controlled failure and output/workspace cleanup', 'full cold controller guard',
        'EOF/reap/helper threads/owned Jobs/original descriptor release'])


def parse_uia(plan, budget, probe):
    scripts = path(plan['controller_root'])/'scripts'
    declared = {row['path']: row for row in plan['inputs']}
    sources = {}
    for name in ('parse-uia.ps1', 'uia.ps1'):
        source = scripts/'hosted_picker'/name
        before = stamp(source)
        raw = source.read_bytes()
        assert before == stamp(source) == declared[str(source)]['stat'], 'PowerShell source metadata drift'
        assert hashlib.sha256(raw).hexdigest() == declared[str(source)]['sha256'], 'PowerShell source hash drift'
        sources[name] = raw
    payload = base64.b64encode(sources['uia.ps1']).decode('ascii')
    command = "& {\n" + sources['parse-uia.ps1'].decode('utf-8') + "\n} -SourceBase64 '" + payload + "'"
    powershell = read(plan['documents']['uia-binding.json'])['powershell']['path']
    return probe([powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
                 budget, 'actual-picker-powershell', cwd=str(scripts.parent))


def inspect(plan, budget, *, probe):
    """Bounded preparation probes only; never start a browser or product Job."""
    assert os.name == 'nt', 'actual native Windows preparation required'
    assert Path(plan['python']['path']).resolve() == Path(sys.executable).resolve(), 'selected Python required'
    scripts=path(plan['controller_root'])/'scripts'
    checked = validate(plan,producer_root=plan['controller_root'])
    if 'execution_kind' in plan or 'frozen_batch' in plan:
        from scale_acceptance.hosted_qualification import batch_admission
        batch_admission(plan,'actual-picker',plan['channel'])
    from . import assets, integration, suite, uia
    from .control import native_volume, owned_roots, storage_size
    volume=native_volume()
    package = read(plan['documents']['package-binding.json'])
    custody = read(plan['documents']['custody.json'])
    checked['baseline_completed']=suite.baseline_completed(Path(plan['root']),expected_manifest=custody['baselineCompletedManifestSha256'])
    roots=owned_roots(Path(plan['root']),custody)
    owned_bytes=sum(storage_size(root) for root in roots)
    retained_inputs=suite.input_inventory(custody,roots,plan['input']['path'])
    assert custody['extraRetainedSourceFixtureBytes']>=1444 and custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes']>=1009704
    suite.input_gate(0,custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes'])
    assert owned_bytes>=custody['sampledOwnedBytes'] and owned_bytes-custody['sampledOwnedBytes']<plan['growth_bytes']
    assert custody['sampledOwnedBytes']+plan['growth_bytes']<storage_stop(plan) and owned_bytes<storage_stop(plan), 'original owned artifact/growth envelope cannot fit'
    integration.require_custody(custody, package['package'], {key: package[key] for key in
        ('source_commit', 'source_tree', 'runtime_build_commit')})
    assets.read_package(custody['selectedZIP']['path'], package)
    if plan['case'] in ('success','failure'):
        uia.layout_spec(read(plan['documents']['permission-layout.json']))
    uia.runtime(read(plan['documents']['uia-binding.json']))
    import importlib.util
    spec = importlib.util.spec_from_file_location('picker_windows', scripts / 'browser-small-windows.py')
    windows = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(windows)
    assert all(callable(getattr(windows,name,None)) for name in ('kernel','process_identity',
        'held_identity','query_job','duplicate_job','close','terminate','stop_descendants')), 'selected native helper API incomplete'
    assert isinstance(windows.IncompleteJobCensus,type) and issubclass(windows.IncompleteJobCensus,OSError)
    windows.kernel()  # Bind native symbols/signatures; create no Job or process.
    for source in scripts.joinpath('hosted_picker').rglob('*.py'):
        compile(source.read_bytes(), str(source), 'exec')
    cache=budget.directory/'powershell-cache';cache.mkdir()
    previous={key:os.environ.get(key) for key in ('TEMP','TMP','PSModuleAnalysisCachePath','PSModulePath')}
    os.environ.update(TEMP=str(cache),TMP=str(cache),PSModuleAnalysisCachePath=str(cache/'module-analysis.cache'),
                      PSModulePath=r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules')
    try:
        parse_uia(plan, budget, probe)
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
    output = probe([plan['node']['path'], str(scripts / 'hosted_picker/dependency-probe.cjs'),
                    plan['playwright_root']], budget, 'actual-picker-runtime', cwd=str(scripts.parent))
    observed = json.loads(budget.read(output))
    assert observed['status'] == 'passed' and observed['launch'] is False
    assert observed['node'] == plan['toolchains']['node_version']
    assert observed['playwright'] == plan['toolchains']['playwright_version']
    checked['retained_storage_sample_bytes']=owned_bytes
    checked['retained_input_inventory']=retained_inputs
    checked['volume']=volume
    return checked


def check(p):
    for entry in p['inputs']:
        assert stamp(entry['path']) == entry['stat'], 'input metadata changed during execution'
    for root, names in p['input_directories'].items():
        assert inventory(root) == names, 'input inventory changed during execution'


def prepare_namespace(plan, retained):
    """One cold, completed prewrite census; only the selected missing case root is created."""
    from hosted_picker import control
    assert Path(control.__file__).resolve()==(SCRIPTS/'hosted_picker/control.py').resolve(), 'selected namespace validator required'
    from scale_acceptance.guard import DiskObservation
    import time
    root=path(plan['root'])
    assert root.parent==Path('C:/') and root.name.startswith(('hosted105-','native105-smoke-'))
    assert not root.exists() and root not in [path(name) for name in retained], 'fresh case namespace required'
    controller=path(plan['controller_root'])
    assert not root.is_relative_to(controller) and not controller.is_relative_to(root), 'source/output overlap'
    assert all(not path(row['path']).is_relative_to(root) for row in plan['inputs']), 'input/output overlap'
    roots=[path(name) for name in retained]
    retained_floor=read(plan['documents']['custody.json'])['sampledOwnedBytes']
    assert type(retained_floor) is int and retained_floor>=0, 'retained accounting floor required'
    assert roots, 'complete retained ownership required'
    custody=dict(ownedRoots=[str(name) for name in roots[1:]])
    def observe():
        actual=control.owned_roots(roots[0],custody)
        identities=[(name.stat().st_dev,name.stat().st_ino) for name in actual]
        total=sum(control.storage_size(name) for name in actual)
        assert actual==control.owned_roots(roots[0],custody)
        assert identities==[(name.stat().st_dev,name.stat().st_ino) for name in actual], 'owned root changed during prewrite census'
        free=shutil.disk_usage('C:/').free
        assert max(total,retained_floor)+plan['growth_bytes']<storage_stop(plan), 'prewrite owned storage stop'
        assert free-plan['growth_bytes']>=128*1024**3, 'prewrite physical headroom'
        return dict(owned_bytes=total,retained_floor_bytes=retained_floor,admission_bytes=max(total,retained_floor),free_bytes=free,roots=len(actual),volume=control.native_volume())
    disk=DiskObservation(observe);marker=time.monotonic()
    try:
        disk.start();sample=disk.after(marker)
    finally:disk.stop()
    assert not disk.pending and not root.exists(), 'prewrite observation pending or namespace collision'
    root.mkdir() # Exclusive, after cold input validation and a joined fresh capacity observation.
    return sample


def observed_runtime(plan, expected, runtime_sha256=None):
    """Merge an actual read-only host receipt, never learn hashes during preparation."""
    binding=plan.get('runtime_observation')
    if binding is None:
        assert runtime_sha256 is None, 'unused runtime receipt hash'
        return []
    if runtime_sha256 is not None:
        assert binding['sha256'] is None and len(runtime_sha256)==64 and all(c in '0123456789abcdef' for c in runtime_sha256)
        binding['sha256']=runtime_sha256
    assert isinstance(binding['sha256'],str) and len(binding['sha256'])==64 and all(c in '0123456789abcdef' for c in binding['sha256']), 'bound actual runtime receipt required'
    observed=read(binding['path'],expected_sha256=binding['sha256'])
    assert binding['sha256'] and observed['schema']=='chopper-hosted-host-v1' and observed['status']=='passed'
    assert observed['host']['os']=='Windows' and observed['channel']==plan['channel']
    assert all(observed[key] is False for key in ('workload_started','original_acquired','controller_started'))
    for role in ('python','node','browser'):
        assert all(observed['tools'][role][key]==plan[role][key] for key in ('path','sha256')), 'selected runtime tool drift'
    # Git-only preparation dependencies remain in the pinned cold receipt, not live guards.
    for row in [*observed['inputs'],*observed['preparation_code'],binding]:
        assert expected.setdefault(row['path'],row['sha256'])==row['sha256'], 'conflicting observed runtime pin'
    plan['runtime_roots']=list(dict.fromkeys([*plan.get('runtime_roots',[]),*observed['input_directories']]))
    return list(observed['input_directories'])


def prepare(definition, output, *, runtime_sha256=None):
    """Fill native metadata/names from an explicitly hash-bound definition.

    This creates the configuration and, when missing, its declared case namespace
    after cold validation and a joined prewrite census; never fixtures, profiles,
    attempts, locks or a browser. Preflight remains a separate bounded Root operation.
    """
    definition, output = path(definition), path(output)
    assert not output.exists(), 'fresh configuration required'
    definition_stamp = stamp(definition)
    p = read(definition)
    if 'new_namespace' in p:
        assert p['new_namespace'] is True and not path(p['root']).exists(), 'fresh namespace required; no retry'
    selected = read(p['source_selection']['path'])
    expected = {}
    for entry in [*selected['inputs'], *p['inputs']]:
        previous = expected.setdefault(entry['path'], entry['sha256'])
        assert previous == entry['sha256'], 'conflicting selected input pin'
    runtime_directories=observed_runtime(p,expected,runtime_sha256)
    if p.get('execution_kind') == 'batch':
        from scale_acceptance.hosted_qualification import batch_inputs
        for entry in batch_inputs(p['frozen_batch']):
            assert expected.setdefault(entry['path'],entry['sha256']) == entry['sha256'], 'conflicting batch proof pin'
    # Derive every required receipt from the pinned authoritative ledger, as we
    # already derive selected-source inputs. Never learn their hashes from disk.
    ledger_path=p['documents']['accounting.json']
    assert ledger_path in expected, 'accounting authority pin required'
    ledger=read(ledger_path,expected_sha256=expected[ledger_path])
    for row in ledger['prior_attempts']:
        previous=expected.setdefault(row['native_path'],row['sha256'])
        assert previous==row['sha256'], 'conflicting historical receipt pin'
    expected[str(definition)] = hashlib.sha256(definition.read_bytes()).hexdigest()
    assert stamp(definition) == definition_stamp, 'definition changed during preparation'
    directories = list(dict.fromkeys([*selected['input_directories'], *p['input_directories'], *runtime_directories,
                                     str(SCRIPTS / 'hosted_picker')]))
    p['input_directories'] = {name: inventory(name) for name in directories}
    assert all(name in expected for names in p['input_directories'].values() for name in names), 'definition must pin every actual input; no learned hashes'
    p['inputs'] = [dict(path=name, sha256=digest, stat=stamp(name)) for name,digest in sorted(expected.items())]
    if p.get('case')=='malformed-retry':
        binding=p['malformed_input'];row=next(row for row in p['inputs'] if row['path']==binding['path'])
        assert row['sha256']==binding['sha256'], 'malformed input authority pin required'
        p['malformed_input']=dict(binding,nativeStat=dict(zip(('dev','ino','bytes','mtime_ns'),row['stat'][:4])))
    p['definition'] = dict(path=str(definition),sha256=expected[str(definition)])
    missing='root' in p and not path(p['root']).exists()
    if missing:validate(p,preparing=True)
    else:validate(p)
    assert stamp(definition) == definition_stamp, 'definition changed during preparation'
    physical_capacity(p)
    if missing:
        assert output.parent==path(p['root']), 'candidate must be inside its new case root'
        p['preparation_root_observation']=prepare_namespace(p,read(p['documents']['custody.json'])['ownedRoots'])
    with output.open('x',encoding='utf-8') as stream:
        json.dump(p,stream,sort_keys=True,separators=(',',':'));stream.write('\n')
    return dict(path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                input_files=len(p['inputs']),workload_started=False,scale_slot_consumed=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('definition')
    parser.add_argument('output')
    parser.add_argument('--runtime-sha256')
    args = parser.parse_args()
    print(json.dumps(prepare(args.definition,args.output,runtime_sha256=args.runtime_sha256)))
