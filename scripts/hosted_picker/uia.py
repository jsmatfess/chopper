"""One exact reviewed owned browser folder permission; no Run or export."""
import hashlib,json,os,stat,time
from pathlib import Path

ROLES=('UIAutomationClient','UIAutomationTypes','System.Management.Automation','mscorlib')

def binding(value):
    assert value['enabled'] is True and value['rootReviewed'] is True,'UIA runtime binding disabled'
    assert value['helperSeconds']==8 and value['treeBytes']==60000
    assert value['nodes']==256 and value['depth']==16 and value['names']==256
    assert isinstance(value['windowsVersion'],list) and len(value['windowsVersion'])==5
    assert isinstance(value['powershellVersion'],str) and 0<len(value['powershellVersion'])<64
    assert value['powershell']['path'].casefold()==r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'.casefold()
    assert isinstance(value['dotnetVersion'],str) and 0<len(value['dotnetVersion'])<64
    rows=[value['powershell'],*[value['assemblies'][k] for k in ROLES],*[value['nativeImages'][k] for k in ('clr','UIAutomationCore')]]
    assert len({r['path'].casefold() for r in rows})==len(rows)
    for r in rows:
        assert r['path'].startswith('C:\\') and isinstance(r['sha256'],str) and len(r['sha256'])==64
        assert set(r['nativeStat'])=={'dev','ino','bytes','mtime_ns'} and r['nativeStat']['ino']>0
        assert 0<r['nativeStat']['bytes']<=32*1024**2
    return rows

def runtime(value):
    rows=binding(value);assert list(__import__('sys').getwindowsversion())==value['windowsVersion']
    total=0
    for r in rows:
        p=Path(r['path'])
        for q in (p,*p.parents):assert not q.is_symlink() and not getattr(q.lstat(),'st_file_attributes',0)&0x400
        before=p.lstat();assert stat.S_ISREG(before.st_mode)
        stamp=lambda s:dict(dev=s.st_dev,ino=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns)
        assert stamp(before)==r['nativeStat'];total+=before.st_size;assert total<=64*1024**2
        with p.open('rb') as f:
            assert stamp(os.fstat(f.fileno()))==r['nativeStat']
            raw=f.read(32*1024**2+1)
            assert stamp(os.fstat(f.fileno()))==r['nativeStat']
        assert len(raw)==before.st_size and hashlib.sha256(raw).hexdigest()==r['sha256'] and stamp(p.lstat())==r['nativeStat']
    return True

def target(observation,root):
    values=[v for v in observation['windows'] if v['visible'] and v['enabled'] and v['class']=='Chrome_WidgetWin_1' and v['owner']==root['pid']]
    assert len(values)==1,'UIA needs one exact visible held Chrome root'
    return values[0]['hwnd']

def result(value,expected,allowed):
    assert value['kind'] in ('owned-uia-tree','owned-uia-unavailable') and value['acceptance'] is False and value['actions']==0
    if value['kind']=='owned-uia-unavailable':
        assert isinstance(value['error'],str) and len(value['error'])<=2048;return value
    assert value['hwnd']==expected and len(value['nodes'])<=256 and type(value['truncated']) is bool
    for i,r in enumerate(value['nodes']):
        assert r['index']==i and -1<=r['parent']<i and 0<=r['depth']<=16
        assert r['depth']==(0 if r['parent']==-1 else value['nodes'][r['parent']]['depth']+1), 'UIA depth/ancestry mismatch'
        assert r['processId'] in allowed and type(r['enabled']) is bool and type(r['offscreen']) is bool
        assert type(r['nativeHandle']) is int
        for k,limit in [('name',256),('automationId',256),('class',127),('controlType',127)]:assert isinstance(r[k],str) and len(r[k])<=limit
    assert len(json.dumps(value,ensure_ascii=False).encode())<=60000
    assert len(json.dumps(value).encode())<=128*1024
    return value

def layout_spec(layout):
    nodes=layout['nodes'];assert 1<=len(nodes)<=256
    keys={'index','parent','controlType','class','name','automationId','enabled','offscreen'}
    assert layout['channel'] in ('chrome','msedge')
    if 'rootNames' in layout:
        names=layout['rootNames']
        assert layout['channel']=='msedge' and type(names) is list and 1<=len(names)<=2
        assert all(type(name) is str and 0<len(name)<=256 and '{origin}' not in name for name in names)
        assert len(set(names))==len(names) and nodes[0]['name'] in names
    for index,node in enumerate(nodes):
        assert set(node)==keys and type(node['index']) is int and node['index']==index
        assert type(node['parent']) is int and (-1 if index==0 else 0)<=node['parent']<index
        for key,limit in [('name',256),('automationId',256),('class',127),('controlType',127)]:
            assert type(node[key]) is str and len(node[key])<=limit
        assert type(node['enabled']) is bool and type(node['offscreen']) is bool
    providers=layout['providerIndices']
    assert type(providers) is list and len(providers)<=4 and len(set(providers))==len(providers)
    assert all(type(i) is int and 0<i<len(nodes) and nodes[i]['class']=='Intermediate D3D Window' for i in providers)
    allow,deny,dialog,destination=[layout[k] for k in ('allowIndex','denyIndex','dialogIndex','destinationIndex')]
    assert all(type(i) is int and 0<i<len(nodes) for i in (allow,deny,dialog,destination))
    assert len({allow,deny,dialog,destination})==4
    assert nodes[allow]['name']=='Allow' and nodes[deny]['name']=="Don't Allow"
    assert nodes[allow]['parent']==nodes[deny]['parent'] and nodes[allow]['controlType']==nodes[deny]['controlType']=='ControlType.Button'
    assert nodes[allow]['enabled'] is True and nodes[allow]['offscreen'] is False
    assert nodes[dialog]['name']=='Allow this site to edit files?' and nodes[dialog]['class']=='RootView'
    assert nodes[destination]['name']=='{origin} will be able to edit files in output'


def permission_tree(value,expected,allowed,owner,origin,layout):
    from urllib.parse import urlsplit
    url=urlsplit(origin)
    assert url.scheme=='http' and url.hostname=='127.0.0.1' and url.port and url.netloc=='127.0.0.1:'+str(url.port) and not url.path and not url.query and not url.fragment
    layout_spec(layout)
    result(value,expected,allowed)
    assert value['kind']=='owned-uia-tree' and value['truncated'] is False and value['foreignSkipped']==0
    assert 1<=len(value['nodes'])==len(layout['nodes'])<=256
    providers=layout['providerIndices']
    for actual,template in zip(value['nodes'],layout['nodes']):
        wanted=dict(template);wanted['name']=wanted['name'].replace('{origin}',origin)
        assert all(actual[k] in layout['rootNames'] if actual['index']==0 and k=='name' and 'rootNames' in layout
                   else actual[k]==v for k,v in wanted.items()),'Selected browser permission layout changed'
        if actual['index'] not in providers:assert actual['processId']==owner['pid'],'permission control not held browser root'
        if actual['index']==0:assert actual['nativeHandle']==expected
        elif actual['index'] not in providers:assert actual['nativeHandle']==0
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def run(value,observation,forest,root,session,guard,spawn,send,events,windows,session_of,job,cache,script,permission,clock=time.monotonic):
    binding(value);hwnd=target(observation,root);deadline=clock()+8
    def check():
        guard();assert clock()<deadline,'UIA helper deadline'
        forest.check_chain(root['pid'])
    # The previous observer scope has ended; this phase owns a fresh bounded guard.
    forest.guard=guard
    allowed={p:i for p,i in forest.identities.items() if i['image'].casefold()==root['image'].casefold()}
    assert root['pid'] in allowed
    env=dict(os.environ,TMP=str(cache),TEMP=str(cache),PSModuleAnalysisCachePath=str(cache/'module-analysis.cache'),
             PSModulePath=r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules')
    check();forest.check()
    source=script.read_bytes()
    assert hashlib.sha256(source).hexdigest()==permission['scriptSha256'], 'UIA helper source changed before dispatch'
    p,identity=spawn([value['powershell']['path'],'-NoLogo','-NoProfile','-NonInteractive','-STA','-Command',source.decode('utf-8')],'uia',env)
    assert identity['image'].casefold()==value['powershell']['path'].casefold() and identity['parent']==os.getpid()
    assert session_of(p.pid)==session
    def helper_check():
        check()
        if p.poll() is None:assert p.pid in windows.query_job(job)['pids'],'UIA helper left inherited Job'
        if p.poll() is None:
            try:assert windows.process_identity(p.pid)==identity and session_of(p.pid)==session
            except OSError:
                if p.poll() is None:raise
    helper_check()
    observing=permission.get('observeOnly',False)
    send(p,dict(kind='owned-uia-binding',hwnd=hwnd,owner=root,allowed=list(allowed.values()),runtime=value,permission=not observing,layout=permission['layout'],channel=permission['layout']['channel']))
    report=None;candidate=None;invocation_sent=False
    try:
        while report is None or p.poll() is None:
            helper_check()
            try:name,line=events.get(timeout=.025)
            except __import__('queue').Empty:continue
            assert name=='uia','unexpected event while browser waits at UIA gate'
            value=json.loads(line)
            if observing:
                assert report is None, 'duplicate UIA observation'
                result(value,hwnd,allowed)
                assert value['kind']=='owned-uia-tree' and value['truncated'] is False and value['foreignSkipped']==0
                candidate=value;report=dict(kind='owned-uia-observed',actions=0,acceptance=False)
                continue
            if candidate is None:
                permission['verifyOutput']()
                digest=permission_tree(value,hwnd,allowed,root,permission['origin'],permission['layout'])
                candidate=value
                fresh=permission['freshForest'](check)
                providers={row['processId'] for row in value['nodes']}
                assert all(fresh.identities.get(pid)==allowed[pid] for pid in providers),'permission provider replaced during phase capture'
                assert fresh.identities.get(root['pid'])==forest.identities[root['pid']],'permission root identity changed'
                assert fresh.identities.get(p.pid)==dict(identity,session=session),'permission helper identity changed'
                helper_check();permission['verifyOutput']();helper_check();fresh.check()
                invocation_sent=True
                send(p,dict(kind='invoke-exact-folder-permission',sha256=digest,origin=permission['origin'],outputName='output',allowIndex=permission['layout']['allowIndex']))
            else:
                assert report is None and invocation_sent and value==dict(kind='owned-uia-permission-invoked',hwnd=hwnd,actions=1,acceptance=False,sha256=digest),'unexpected permission result'
                report=value
        assert p.wait(timeout=1)==0,'UIA helper failed'
        report['helperLaunched']=True;report['candidate']=candidate
        return report
    except BaseException as error:
        if p.poll() is None:p.kill()
        p.wait(timeout=2)
        # Once sent, a failed acknowledgement cannot prove that no action occurred.
        raise AssertionError('permission step failed; invocationSent='+str(invocation_sent)+': '+str(error)) from error

def retain_cache(path,identity,report):
    assert report['privateCleanup']['complete'] and all(v==dict(stdout=True,stderr=True) for v in report['privateCleanup']['eof'].values())
    assert report['privateCleanup']['jobPids']==[report['privateCleanup']['owner']]
    root=Path(path);s=root.lstat();assert stat.S_ISDIR(s.st_mode) and not root.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400
    assert dict(dev=s.st_dev,ino=s.st_ino)==identity
    rows=[];total=0;start=time.monotonic()
    for base,dirs,files in os.walk(root):
        for n in dirs+files:
            parent=Path(base)
            while True:
                d=parent.lstat();assert stat.S_ISDIR(d.st_mode) and not parent.is_symlink() and not getattr(d,'st_file_attributes',0)&0x400
                if parent==root:break
                assert parent.is_relative_to(root);parent=parent.parent
            p=Path(base)/n;s=p.lstat();assert time.monotonic()-start<1 and len(rows)<64
            assert len(p.relative_to(root).parts)<=8 and not p.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400
            if stat.S_ISREG(s.st_mode):assert s.st_nlink==1;total+=s.st_size;assert total<=512*1024
            else:assert stat.S_ISDIR(s.st_mode)
            rows.append(dict(path=str(p.relative_to(root)),bytes=s.st_size if stat.S_ISREG(s.st_mode) else 0,directory=stat.S_ISDIR(s.st_mode)))
    after=root.lstat();assert stat.S_ISDIR(after.st_mode) and not getattr(after,'st_file_attributes',0)&0x400
    assert dict(dev=after.st_dev,ino=after.st_ino)==identity
    return dict(complete=True,retained=True,empty=not rows,deletedFiles=0,bytes=total,entries=rows,note='Fresh helper cache retained after actual stop/reap/EOF; no empty-directory or deletion credit.')
