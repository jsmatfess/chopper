"""Explicit hash-bound preparation for the existing final-package Native UI smoke."""
import hashlib,json,os,stat,sys
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:sys.path.insert(0,str(SCRIPTS))
from hosted_picker.config import path,stamp,inventory,read

SOURCE='639d1fe97d985b1544df0932321c6a93cca2567b'
TREE='b3bde79d552ee29760cb283d07938f9248cee0bb'
BUILD='feb9e099e5e0f22c4da8d0f5ba7269e221c91e9d'
EXE_SHA='42772aa8bb8a76e27fe9d7a0e479b445250e164bdcb4da25fdae88a83536c5d2'
RECEIPT_SHA='1720f28a01cbbd7a30cbb8c8614b9efc2da01e57c765c625f51e8a5e3455c30d'
ZIP_SHA='bba46786609777f2722c6fec0563f6ce5ae32fb2dd630032889f56f3ab27be01'

def digest(file):
    before=stamp(file);h=hashlib.sha256()
    with path(file).open('rb') as stream:
        assert (os.fstat(stream.fileno()).st_dev,os.fstat(stream.fileno()).st_ino)==tuple(before[:2])
        for part in iter(lambda:stream.read(1024**2),b''):h.update(part)
    assert stamp(file)==before,'input changed while reading: '+str(file)
    return h.hexdigest()

def package(p):
    binding=p['package'];receipt=read(binding['receipt']['path'],expected_sha256=RECEIPT_SHA)
    assert binding['receipt']['sha256']==RECEIPT_SHA
    assert receipt['release_source_commit']==SOURCE and receipt['release_source_tree']==TREE
    name='chopper-0.2.0-windows-x86_64.zip';expected=receipt['packages'][name]
    assert expected==dict(bytes=1804401,sha256=ZIP_SHA) and binding['zip']['sha256']==ZIP_SHA
    file=path(binding['zip']['path']);before=stamp(file)
    assert before[2]==expected['bytes'] and digest(file)==ZIP_SHA
    members=receipt['package_members'][name]
    assert len(members)==8 and members['chopper.exe']['sha256']==EXE_SHA
    from scale_acceptance.native_scale_host import module
    module('package-release').inspect_zip(file,'windows_x86_64',members)
    assert stamp(file)==before
    assert all(path(item).stat().st_nlink==1 for item in (file,binding['receipt']['path'],p['exe']['path']))
    assert digest(p['exe']['path'])==EXE_SHA and p['exe']['sha256']==EXE_SHA
    return dict(receiptSha256=RECEIPT_SHA,zipSha256=ZIP_SHA,exeSha256=EXE_SHA,members=8)

def check(p):
    for item in p['inputs']:assert stamp(item['path'])==item['stat'],'input metadata changed: '+item['path']
    for root,names in p['input_directories'].items():assert inventory(root)==names,'input membership changed: '+root

def runtime_inventory(p,declared):
    # Entry-point hashes alone do not cover the DLL/module trees loaded by these tools.
    roots={str(path(p[name]['path']).parent) for name in ('python','node')}
    roots.update((str(path(p['browser']['path']).parent/p['browser_version']),p['playwright_root']))
    assert roots.issubset(set(p['runtime_roots'])), 'complete selected runtime roots required'
    for root in p['runtime_roots']:
        assert root in p['input_directories'], 'runtime root omitted from membership inventory'
        members=inventory(root)
        assert p['input_directories'][root]==members and all(name in declared for name in members), 'runtime membership incomplete'
    selection=p['source_selection']
    assert selection['path'] in declared and declared[selection['path']]['sha256']==selection['sha256']
    selected=read(selection['path'],expected_sha256=selection['sha256'])
    assert selected['source_commit']==SOURCE and selected['source_tree']==TREE
    assert all(row['path'] in declared and declared[row['path']]['sha256']==row['sha256'] for row in selected['inputs']), 'complete selected source/runtime pins required'
    for root in selected['input_directories']:
        members=sorted(row['path'] for row in selected['inputs'] if path(row['path']).is_relative_to(path(root)))
        assert p['input_directories'].get(root)==inventory(root)==members, 'selected inventory cannot be shortened'

def validate(p,*,fresh=True,preparing=False):
    assert not sys.flags.optimize and p['schema']=='chopper-native-ui-smoke-v1'
    assert p['product']==dict(commit=SOURCE,tree=TREE,runtime_build=BUILD)
    assert p['case'] in ('processing-cancel','export-cancel') and p['channel']=='chrome'
    root=path(p['root']);assert root.parent==Path('C:/') and root.name.startswith('native105-smoke-') and (root.is_dir() or (preparing and not root.exists()))
    assert not fresh or not (root/'attempt1').exists(),'no retry/overwrite of a Native UI attempt'
    assert p['seconds']==180 and p['input_cap_bytes']==1024**2
    assert p['owned_cap_bytes']==32*1024**3 and p['growth_bytes']==4*1024**3
    assert Path(p['controller_root']).resolve()==SCRIPTS.parent.resolve()
    assert Path(p['python']['path']).resolve()==Path(sys.executable).resolve() and p['toolchains']['python_version']==sys.version
    assert p['browser']['path'].casefold()==r'C:\Program Files\Google\Chrome\Application\chrome.exe'.casefold()
    assert set(p['documents'])=={'decision.json','job.json','custody.json','accounting.json'}
    custody=read(p['documents']['custody.json']);assert custody['chromeVersion']==p['browser_version']
    declared={row['path']:row for row in p['inputs']};assert len(declared)==len(p['inputs'])
    required=[str(file) for file in SCRIPTS.joinpath('native_smoke').rglob('*') if file.is_file()]
    required += [str(SCRIPTS/name) for name in ('browser-small-windows.py','validation-runner.py','hosted_picker/config.py','hosted_picker/suite.py','hosted_picker/reservation.py','scale_acceptance/guard.py','scale_acceptance/verify.py','scale_acceptance/hosted_qualification.py','scale_acceptance/native_scale_host.py','package-release.py','hosted_picker/dependency-probe.cjs')]
    from scale_acceptance.native_scale_host import module
    required += [str(file) for file in module('acceptance-preflight').checker_sources()]
    required += [row['path'] for row in (p['python'],p['node'],p['browser'],p['exe'],p['package']['zip'],p['package']['receipt'])]
    required += [*p['documents'].values(),*custody['retainedInputPaths']]
    ledger=read(p['documents']['accounting.json'])
    required += [row['native_path'] for row in ledger['prior_attempts']]
    assert all(name in declared for name in required),'undeclared Native smoke dependency/evidence'
    for name in ('python','node','browser','exe'):
        assert declared[p[name]['path']]['sha256']==p[name]['sha256']
    runtime_inventory(p,declared)
    assert str(SCRIPTS/'native_smoke') in p['input_directories']
    for directory,names in p['input_directories'].items():
        assert inventory(directory)==names and all(name in declared for name in names),'complete declared directory required'
    for row in p['inputs']:
        assert stamp(row['path'])==row['stat'] and digest(row['path'])==row['sha256'],'immutable input drift: '+row['path']
    lock=p['original_lock'];assert path(lock['path'])==Path.home()/'.chopper/local-ci.lock'
    locked=Path(lock['path']).stat();assert stat.S_ISREG(locked.st_mode) and [locked.st_dev,locked.st_ino]==lock['identity']
    assert p['owned_roots'] and len(set(p['owned_roots']))==len(p['owned_roots'])
    assert str(root) in p['owned_roots']
    assert all(path(name).parent==Path('C:/') and (path(name).is_dir() or (preparing and path(name)==root and not root.exists())) for name in p['owned_roots'])
    assert set(custody['extraOwnedRoots'])==set(p['owned_roots'])-{str(root),*(str(Path('C:/')/name) for name in p['historical_native_roots'])}
    assert custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes']>=1048480
    assert custody['retainedFixtureBytes']+custody['extraRetainedSourceFixtureBytes']<=1024**2
    return dict(bindings=dict(product=p['product'],case=p['case'],channel='chrome'),package=package(p),runtime_pending=['actual public Native UI Cancel in selected phase','atomic output/temp cleanup','EOF/reap/Jobs/Original release'])

def prepare(definition,output,*,runtime_sha256=None):
    definition,output=path(definition),path(output);assert not output.exists()
    before=stamp(definition);p=read(definition);expected={}
    if 'new_namespace' in p:
        assert p['new_namespace'] is True and not path(p['root']).exists(), 'fresh namespace required; no retry'
    selected=read(p['source_selection']['path'],expected_sha256=p['source_selection']['sha256'])
    for item in [*selected['inputs'],*p['inputs']]:
        previous=expected.setdefault(item['path'],item['sha256']);assert previous==item['sha256']
    from hosted_picker.config import observed_runtime
    runtime_directories=observed_runtime(p,expected,runtime_sha256)
    ledger_path=p['documents']['accounting.json'];ledger=read(ledger_path,expected_sha256=expected[ledger_path])
    for row in ledger['prior_attempts']:
        previous=expected.setdefault(row['native_path'],row['sha256']);assert previous==row['sha256']
    expected[str(definition)]=digest(definition)
    p['input_directories']={name:inventory(name) for name in dict.fromkeys([*p['input_directories'],*selected['input_directories'],*runtime_directories])}
    assert all(name in expected for names in p['input_directories'].values() for name in names),'definition must pin complete membership; no hash learning'
    p['inputs']=[dict(path=name,sha256=value,stat=stamp(name)) for name,value in sorted(expected.items())]
    p['definition']=dict(path=str(definition),sha256=expected[str(definition)])
    missing=not path(p['root']).exists()
    if missing:validate(p,preparing=True)
    else:validate(p)
    assert stamp(definition)==before
    if missing:
        from hosted_picker.config import prepare_namespace
        assert output.parent==path(p['root']), 'candidate must be inside its new case root'
        p['preparation_root_observation']=prepare_namespace(p,[name for name in p['owned_roots'] if path(name)!=path(p['root'])])
    with output.open('x',encoding='utf-8') as stream:json.dump(p,stream,sort_keys=True,separators=(',',':'));stream.write('\n')
    return dict(path=str(output),sha256=digest(output),workload_started=False)

def inspect(plan,budget,*,probe):
    assert os.name=='nt','native Windows preparation required'
    result=validate(plan)
    from . import control
    control.bindings_for_inspection(plan)
    result['baseline_completed']=control.load('suite').baseline_completed(control.ROOT)
    assert set(map(str,control.owned_roots()))==set(plan['owned_roots']),'declared and observed owned-root closures differ'
    result['volume']=control.native_volume()
    result['owned_bytes']=control.owned_size()
    assert result['owned_bytes']+plan['growth_bytes']<24*1024**3
    import shutil
    assert shutil.disk_usage('C:/').free-plan['growth_bytes']>=128*1024**3
    result['node_runtime']=json.loads(budget.read(probe([plan['node']['path'],str(SCRIPTS/'hosted_picker/dependency-probe.cjs'),plan['playwright_root']],budget,'native-ui-runtime',cwd=str(SCRIPTS.parent))))
    assert result['node_runtime']['node']==plan['toolchains']['node_version'] and result['node_runtime']['playwright']==plan['toolchains']['playwright_version']
    assert result['node_runtime']['launch'] is False
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('definition');parser.add_argument('output')
    parser.add_argument('--runtime-sha256')
    args=parser.parse_args();print(json.dumps(prepare(args.definition,args.output,runtime_sha256=args.runtime_sha256)))
