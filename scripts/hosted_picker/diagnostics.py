"""Read-only held-owner diagnostics; r11 scopes control reads to the held owner chain."""
import ctypes
from ctypes import wintypes as W


def owner_classes(api, target, check):
    check()
    rows=[];seen=set();visited=0
    def visit(hwnd):
        nonlocal visited
        visited+=1
        if visited>4096:raise OSError('top-level enumeration ceiling')
        check()
        if api.owner(hwnd)!=target:return True
        if not api.visible(hwnd):return True
        if hwnd in seen or len(rows)>=64:raise OSError('owned window ambiguity/ceiling')
        seen.add(hwnd)
        cls=api.class_name(hwnd)
        if not isinstance(cls,str) or not 0<len(cls)<=127:raise OSError('owned class inaccessible/truncated')
        # Recheck ownership after the read to reject a disappearing/reused HWND.
        check()
        if api.owner(hwnd)!=target or not api.visible(hwnd):raise OSError('owned window changed')
        rows.append(dict(hwnd=hwnd,owner=target,**{'class':cls}))
        return True
    api.enumerate(visit)
    check()
    return dict(kind='exact-owner-visible-top-level-classes',owner=target,windows=rows,
                dialogCount=sum(r['class']=='#32770' for r in rows),acceptance=False,selectionEnabled=False)


class NativeWindows:
    def __init__(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        self.user.EnumWindows.argtypes=[self.callback,W.LPARAM];self.user.EnumWindows.restype=W.BOOL
        self.user.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        self.user.GetWindowThreadProcessId.restype=W.DWORD
        self.user.IsWindowVisible.argtypes=[W.HWND];self.user.IsWindowVisible.restype=W.BOOL
        self.user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int];self.user.GetClassNameW.restype=ctypes.c_int
        self.user.EnumChildWindows.argtypes=[W.HWND,self.callback,W.LPARAM];self.user.EnumChildWindows.restype=W.BOOL
        self.user.GetParent.argtypes=[W.HWND];self.user.GetParent.restype=W.HWND
        self.user.GetDlgCtrlID.argtypes=[W.HWND];self.user.GetDlgCtrlID.restype=ctypes.c_int
        self.user.IsWindowEnabled.argtypes=[W.HWND];self.user.IsWindowEnabled.restype=W.BOOL
    def children(self,root,visit):
        errors=[]
        def callback(hwnd,unused):
            try:return visit(hwnd)
            except BaseException as error:errors.append(error);return False
        cb=self.callback(callback)
        # EnumChildWindows has no meaningful return value, as in WinControls.
        self.user.EnumChildWindows(root,cb,0)
        if errors:raise errors[0]
    def parent(self,h):return int(self.user.GetParent(h) or 0)
    def control_id(self,h):return int(self.user.GetDlgCtrlID(h))
    def enabled(self,h):return bool(self.user.IsWindowEnabled(h))
    def owner(self,hwnd):
        pid=W.DWORD()
        if not self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid)):raise OSError('window owner inaccessible')
        return pid.value
    def visible(self,hwnd):return bool(self.user.IsWindowVisible(hwnd))
    def class_name(self,hwnd):
        text=ctypes.create_unicode_buffer(129)
        n=self.user.GetClassNameW(hwnd,text,len(text))
        if not 0<n<128:raise OSError('owned class inaccessible/truncated')
        return text.value
    def enumerate(self,visit):
        errors=[]
        def callback(hwnd,unused):
            try:return visit(hwnd)
            except BaseException as error:errors.append(error);return False
        cb=self.callback(callback)
        ok=self.user.EnumWindows(cb,0)
        if errors:raise errors[0]
        if not ok:raise OSError('EnumWindows failed')


def complete_census(windows, job, bounded):
    # Discard incomplete lists; never inspect their process/window metadata.
    for attempt in range(3):
        bounded()
        try:
            census=windows.query_job(job,max_pids=64)
        except getattr(windows,'IncompleteJobCensus',()) as error:
            bounded()
            if attempt==2:raise
            continue
        bounded()
        return census


class JobMembershipChanged(OSError):
    def __init__(self,expected,actual):
        self.expected=list(expected);self.actual=list(actual)
        super().__init__('Diagnostic process census changed: expected='+str(self.expected)+' actual='+str(self.actual))


class HeldForest:
    """Exact Job census only; all acquired handles survive until worker cleanup."""
    def __init__(self, windows, job, root, node, session, check):
        self.w=windows; self.job=job; self.root=root; self.node=node
        self.session=session; self.guard=check; self.handles={}; self.identities={}
        self.chains={}; self.unknown=[]; self.pids=[]; self.retired={}; self.refreshed=False
        self.last_census=None;self.retired_identities={};self.membership_change=None

    def capture(self):
        self.guard()
        census=complete_census(self.w,self.job,self.guard)
        self.last_census=census
        if not census['kill_on_close']:raise OSError('Diagnostic Job containment unknown')
        self.pids=sorted(census['pids'])
        self.chains={}; self.unknown=[]
        if not self.pids or len(set(self.pids))!=len(self.pids) or len(self.pids)>64:raise OSError('Diagnostic process ceiling')
        for pid in self.pids:
            self.guard()
            if pid in self.handles:continue
            h=self.w.checked(self.w.kernel().OpenProcess(0x100000|0x1000,False,pid))
            self.handles[pid]=h # Record before any fallible identity/member query.
            identity=self.w.held_identity(h,pid)
            if not isinstance(identity['image'],str) or not 0<len(identity['image'])<=1024:
                raise OSError('Diagnostic unknown/oversized process image')
            self.identities[pid]=identity
        self.check()
        for expected in (self.root,self.node):
            actual=self.identities.get(expected['pid'])
            if actual is None or any(actual.get(k)!=v for k,v in expected.items()):
                raise OSError('Diagnostic held root/Node identity mismatch')
        if self.root['parent']!=self.node['pid'] or self.node['created']>self.root['created']:raise OSError('Diagnostic root not direct Node child')
        chrome=self.root['image'].casefold()
        for pid,identity in self.identities.items():
            if identity['image'].casefold()!=chrome:
                self.unknown.append(dict(pid=pid,status='not-Chrome; no window inspection'))
                continue
            chain=[];seen=set();current=pid
            while True:
                if current in seen or current not in self.identities:
                    raise OSError('Diagnostic cyclic/unbound parent ancestry')
                seen.add(current);item=self.identities[current];chain.append(dict(item))
                if item['session']!=self.session or item['image'].casefold()!=chrome:
                    raise OSError('Diagnostic unknown image/session in Chrome ancestry')
                if current==self.root['pid']:
                    chain.append(dict(self.identities[self.node['pid']]))
                    break
                parent=self.identities.get(item['parent'])
                if parent is None or parent['created']>item['created']:
                    raise OSError('Diagnostic missing/replaced parent')
                current=item['parent']
            self.chains[pid]=chain
        self.check()
        return self

    def check(self):
        self.guard()
        census=complete_census(self.w,self.job,self.guard)
        self.last_census=census
        actual=sorted(census['pids'])
        if not census['kill_on_close']:raise OSError('Diagnostic Job containment changed')
        if not actual or len(actual)>64 or len(set(actual))!=len(actual):raise OSError('Diagnostic process ceiling')
        if actual!=self.pids:
            self.membership_change=dict(expected=dict(pids=list(self.pids)),actual=dict(pids=actual))
            if any(row['pid'] not in actual for row in (self.root,self.node)):
                raise OSError('Diagnostic held root/Node left Job')
            self.check_members(pid for pid in self.handles if pid in actual)
            raise JobMembershipChanged(self.pids,actual)
        self.check_members(self.handles)

    def evidence(self):
        return dict(captured=dict(pids=list(self.pids)),last=self.last_census,membershipChange=self.membership_change,
                    identities=[dict(v) for v in self.identities.values()],
                    retiredIdentities=[dict(v) for v in self.retired_identities.values()])

    def check_members(self, pids):
        for pid in pids:
            self.guard()
            h=self.handles[pid]; member=W.BOOL()
            self.w.checked(self.w.kernel().IsProcessInJob(h,self.job,ctypes.byref(member)))
            # held_identity checks handle liveness before and after birth/image/parent/session.
            if not member.value or self.w.held_identity(h,pid)!=self.identities[pid]:
                raise OSError('Diagnostic held process identity/Job changed')
            if self.identities[pid]['session']!=self.session:
                raise OSError('Diagnostic Job session unknown')

    def check_chain(self, pid):
        self.guard()
        census=complete_census(self.w,self.job,self.guard)
        pids=census['pids']; chain=self.chains[pid]
        if (not census['kill_on_close'] or not 0<len(pids)<=64 or
            len(set(pids))!=len(pids) or any(i['pid'] not in pids for i in chain)):
            raise OSError('Input held ancestry Job census changed')
        self.check_members(i['pid'] for i in chain)

    def refresh(self, pid):
        # Keep the target handles; rebind every other process before final uniqueness.
        self.check_chain(pid)
        if self.refreshed:raise OSError('Input census refresh ceiling')
        self.refreshed=True
        chain=self.chains[pid]; pinned={i['pid'] for i in chain}
        for other,h in list(self.handles.items()):
            if other in pinned:continue
            self.retired[other]=h # Original handles remain held through worker cleanup.
            self.retired_identities[other]=self.identities[other]
            del self.handles[other]; del self.identities[other]
        self.capture()
        if self.chains.get(pid)!=chain:raise OSError('Input held ancestry changed')
        self.check_chain(pid)

    def close(self):
        errors=[]
        for handles in (self.handles,self.retired):
            for pid,h in list(handles.items()):
                try:self.w.close(h)
                except BaseException as error:errors.append(str(error))
                else:del handles[pid]
        if errors:
            self.cleanup_failed=True
            raise OSError('Diagnostic handle cleanup unknown: '+ '; '.join(errors))


def forest_classes(api, forest):
    import json
    forest.check();rows=[];seen=set();visited=0;encoded_bytes=0
    def visit(hwnd):
        nonlocal visited,encoded_bytes
        visited+=1
        if visited>4096:raise OSError('top-level enumeration ceiling')
        forest.guard()
        owner=api.owner(hwnd)
        if owner not in forest.chains:return True
        # Recheck immediately before every visibility/class read; never inspect foreign text/class.
        if api.owner(hwnd)!=owner:raise OSError('owned window owner changed')
        if not api.visible(hwnd):return True
        if hwnd in seen or len(rows)>=256:raise OSError('owned window ambiguity/ceiling')
        seen.add(hwnd);forest.check()
        if api.owner(hwnd)!=owner:raise OSError('owned window owner changed')
        cls=api.class_name(hwnd)
        if not isinstance(cls,str) or not 0<len(cls)<=127:raise OSError('owned class inaccessible/truncated')
        forest.check()
        if api.owner(hwnd)!=owner or not api.visible(hwnd):raise OSError('owned window changed')
        row=dict(hwnd=hwnd,owner=owner,identity=forest.identities[owner],
                 parentChain=forest.chains[owner],**{'class':cls})
        encoded_bytes+=len(json.dumps(row,ensure_ascii=True).encode('utf-8'))+2
        if encoded_bytes>900*1024:raise OSError('Diagnostic byte ceiling')
        rows.append(row)
        return True
    api.enumerate(visit);forest.check()
    value=dict(kind='exact-held-job-Chrome-forest-visible-top-level-classes',
        root=forest.root,node=forest.node,processes=list(forest.identities.values()),
        unknown=forest.unknown,windows=rows,visited=visited,
        dialogCount=sum(r['class']=='#32770' for r in rows),
        acceptance=False,selectionEnabled=False,layoutReviewRequired=True)
    if len(json.dumps(value,ensure_ascii=True).encode('utf-8'))>1024**2:
        raise OSError('Diagnostic byte ceiling')
    return value

def settle_job(windows,job,bounded,clock,pause,stop):
    # Browser startup may still create/retire children before any snapshot is bound.
    previous=None;stable=0
    for _ in range(8):
        bounded()
        census=complete_census(windows,job,bounded)
        if not census['kill_on_close'] or not census['pids']:raise OSError('Input readiness Job unknown')
        current=sorted(census['pids'])
        if current==previous:stable+=1
        else:stable=0
        if stable>=3:return
        previous=current
        pause(min(.2,max(0,stop-clock())))
    raise OSError('Input readiness process census did not settle')


# r9 scope: exact live held Chrome child Input tree. Captions deliberately suppressed.
def input_tree(windows, job, root, node, session, guard, api, validate, retain,
               clock=None, pause=None, *, rebind_membership=False):
    import time
    import json
    clock=clock or time.monotonic; pause=pause or time.sleep
    stop=clock()+5; visits=0
    def bounded():
        guard()
        if clock()>=stop:raise OSError('Input tree readiness deadline')
    settle_job(windows,job,bounded,clock,pause,stop)
    for attempt in range(8):
        bounded()
        forest=HeldForest(windows,job,root,node,session,bounded)
        retain(forest)
        candidates=[]
        def visit(hwnd):
            nonlocal visits
            bounded();visits+=1
            if visits>4096:raise OSError('Input total top-level visit ceiling')
            pid=api.owner(hwnd)
            if pid not in forest.chains:return True
            forest.check()
            if api.owner(hwnd)!=pid:raise OSError('Input owner changed')
            visible=api.visible(hwnd)
            forest.check()
            if api.owner(hwnd)!=pid:raise OSError('Input owner changed')
            if not visible:return True
            cls=api.class_name(hwnd)
            forest.check()
            if api.owner(hwnd)!=pid or not api.visible(hwnd):raise OSError('Input window changed')
            if not isinstance(cls,str) or not 0<len(cls)<=127:raise OSError('Input class bound')
            if cls=='#32770':
                if any(h==hwnd for h,p in candidates):raise OSError('Input duplicate candidate')
                candidates.append((hwnd,pid))
                if len(candidates)>1:raise OSError('Input ambiguous candidate')
            return True
        try:
            forest.capture()
            api.enumerate(visit);forest.check()
        except JobMembershipChanged:
            if not rebind_membership:raise
            # Discard only an unfinished read-only snapshot, never an action.
            forest.close();retain(None)
            if attempt<7:pause(min(.05,max(0,stop-clock())))
            continue
        if candidates:
            hwnd,pid=candidates[0]
            if pid==root['pid']:raise OSError('Input candidate must be verified Chrome child')
            def bound():
                forest.check_chain(pid)
                if api.owner(hwnd)!=pid:raise OSError('Input root owner changed')
                cls=api.class_name(hwnd)
                forest.check_chain(pid)
                if api.owner(hwnd)!=pid or cls!='#32770' or not api.visible(hwnd):
                    raise OSError('Input root changed')
                forest.check_chain(pid)
                if api.owner(hwnd)!=pid:raise OSError('Input root owner changed')
                ready=api.enabled(hwnd)
                forest.check_chain(pid)
                if api.owner(hwnd)!=pid:raise OSError('Input root changed')
                return ready
            if bound():
                rows=[];seen=set()
                def collect(h):
                    bound()
                    if h==hwnd or h in seen or len(rows)>=255:raise OSError('Input node ceiling/duplicate')
                    seen.add(h)
                    def read(fn):
                        forest.check_chain(pid)
                        if api.owner(h)!=pid:raise OSError('Input foreign descendant')
                        value=fn(h)
                        forest.check_chain(pid)
                        if api.owner(h)!=pid:raise OSError('Input descendant owner changed')
                        return value
                    cls=read(api.class_name)
                    if not isinstance(cls,str) or not 0<len(cls)<=127:raise OSError('Input class bound')
                    parent=read(api.parent);control_id=read(api.control_id)
                    ready=read(api.visible) and read(api.enabled)
                    rows.append(dict(hwnd=h,parent=parent,owner=pid,id=control_id,ready=ready,
                                     **{'class':cls},caption=None))
                    return True
                api.children(hwnd,collect)
                if not bound():raise OSError('Input readiness changed')
                expected=forest.identities[pid]
                value=dict(kind='exact-held-child-input-tree',mode='observe-input',channel='chrome',session=session,
                    identity=expected,root=root,node=node,parentChain=forest.chains[pid],
                    processes=list(forest.identities.values()),hwnd=hwnd,rootClass='#32770',rootReady=True,
                    nodes=rows,captionsSuppressed=True,visited=visits,snapshots=attempt+1,
                    acceptance=False,selectionEnabled=False,layoutReviewRequired=True)
                validate(value,expected,forest.pids,session)
                # Re-enumerate and compare every metadata field to fail closed on tree races.
                original=rows[:];rows.clear();seen.clear();api.children(hwnd,collect)
                if rows!=original or not bound():raise OSError('Input control tree changed')
                forest.refresh(pid)
                prior=candidates[:];candidates.clear();api.enumerate(visit);forest.check()
                if candidates!=prior:raise OSError('Input candidate changed')
                value['processes']=list(forest.identities.values())
                value['visited']=visits
                if not bound():raise OSError('Input final readiness changed')
                validate(value,expected,forest.pids,session);forest.check()
                if len(json.dumps(value,ensure_ascii=True).encode())>1024**2:raise OSError('Input byte ceiling')
                return value
        # Never overlap metadata handles from separate readiness snapshots.
        forest.close();retain(None)
        if attempt<7:pause(min(.05,max(0,stop-clock())))
    raise OSError('Input readiness snapshots exhausted')
