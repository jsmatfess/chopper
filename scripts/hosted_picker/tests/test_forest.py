"""Pure fake coverage for the new diagnostic scope; run offline with fakes only."""
import copy,ctypes,unittest
from types import SimpleNamespace
import diagnostics
CHROME=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
def identity(pid,parent,image=CHROME,birth=None):
    return dict(pid=pid,parent=parent,image=image,created=birth or pid,session=1)
class Backend:
    def __init__(self):
        self.ids={10:identity(10,1,'node'),20:identity(20,10),30:identity(30,20),40:identity(40,1,'worker')}
        self.pids=list(self.ids);self.opened=[];self.closed=[];self.fail_open=None;self.changed=None;self.member=True;self.nonmembers=set();self.dead=set()
    def query_job(self,job,max_pids=64):return dict(kill_on_close=True,pids=self.pids[:])
    def kernel(self):return self
    def OpenProcess(self,rights,inherit,pid):
        if pid==self.fail_open:raise OSError('open race')
        self.opened.append(pid);return pid
    def held_identity(self,h,pid):
        if pid in self.dead:raise OSError('Held process not current')
        return dict(self.ids[pid])
    def IsProcessInJob(self,h,j,out):out._obj.value=self.member and h not in self.nonmembers;return True
    def checked(self,v):
        if not v:raise OSError('API failure')
        return v
    def close(self,h):self.closed.append(h)
class Windows:
    def __init__(self):self.rows={1:[30,True,'#32770'],2:[999,True,'SECRET'],3:[20,False,'HIDDEN'],4:[40,True,'OWNED_NON_CHROME_SECRET']};self.reads=[];self.flip=None
    def enumerate(self,visit):
        for h in self.rows:visit(h)
    def owner(self,h):return self.rows[h][0]
    def visible(self,h):
        assert self.rows[h][0] in (20,30),'foreign visibility'
        return self.rows[h][1]
    def class_name(self,h):
        assert self.rows[h][0] in (20,30),'foreign class'
        self.reads.append(h)
        if self.flip:self.rows[h][0]=999
        return self.rows[h][2]
class Forest(unittest.TestCase):
    def make(self,b):return diagnostics.HeldForest(b,7,{k:v for k,v in b.ids[20].items() if k!='session'},{k:v for k,v in b.ids[10].items() if k!='session'},1,lambda:None)
    def test_typed_changed_census_preserves_unknown_and_retired_facts(self):
        b=Backend();f=self.make(b)
        try:
            f.capture();b.ids[50]=identity(50,20);b.pids.append(50)
            with self.assertRaises(diagnostics.JobMembershipChanged) as caught:f.check()
            self.assertEqual(caught.exception.expected,[10,20,30,40])
            self.assertEqual(caught.exception.actual,[10,20,30,40,50])
            evidence=f.evidence()
            self.assertIn(50,evidence['last']['pids'])
            self.assertNotIn(50,[row['pid'] for row in evidence['identities']])
            f.refresh(30)
            self.assertIn(40,[row['pid'] for row in f.evidence()['retiredIdentities']])
        finally:f.close()
        self.assertIn(50,[row['pid'] for row in f.evidence()['identities']])
        self.assertCountEqual(b.opened,b.closed)
    def test_exact_child_identity_chain_no_foreign_or_hidden_class(self):
        b=Backend();f=self.make(b)
        try:
            f.capture();a=Windows();v=diagnostics.forest_classes(a,f)
            self.assertEqual(a.reads,[1]);self.assertEqual(v['dialogCount'],1)
            self.assertIn(40,[r['pid'] for r in v['unknown']])
            self.assertEqual([i['pid'] for i in v['windows'][0]['parentChain']],[30,20,10])
            self.assertFalse(v['acceptance']);self.assertFalse(v['selectionEnabled'])
            self.assertTrue(v['layoutReviewRequired']);self.assertEqual(b.closed,[])
        finally:f.close()
        self.assertCountEqual(b.closed,b.opened)
    def test_foreign_replaced_cyclic_unbound_and_unknown_image(self):
        for fault in ('foreign-job','replaced-parent','cycle','unbound','unknown-image','session'):
            b=Backend();f=self.make(b)
            if fault=='foreign-job':b.member=False
            if fault=='replaced-parent':b.ids[20]['created']=31
            if fault=='cycle':b.ids[30]['parent']=30
            if fault=='unbound':b.ids[30]['parent']=999
            if fault=='unknown-image':b.ids[30]['image']=''
            if fault=='session':b.ids[30]['session']=2
            try:
                with self.subTest(fault=fault),self.assertRaises(OSError):f.capture()
            finally:f.close()
            self.assertCountEqual(b.closed,b.opened)
    def test_process_disappears_or_changes_birth_after_capture(self):
        for fault in ('census','birth','image','parent'):
            b=Backend();f=self.make(b)
            try:
                f.capture()
                if fault=='census':b.pids.remove(30)
                elif fault=='birth':b.ids[30]['created']+=1
                elif fault=='image':b.ids[30]['image']='replacement'
                else:b.ids[30]['parent']=40
                a=Windows()
                with self.assertRaises(OSError):diagnostics.forest_classes(a,f)
                self.assertEqual(a.reads,[])
            finally:f.close()
    def test_partial_open_and_identity_failure_close_every_acquired_handle(self):
        for failure in ('open','identity'):
            b=Backend();f=self.make(b)
            if failure=='open':b.fail_open=30
            else:
                original=b.held_identity
                def query(h,pid):
                    if pid==30:raise OSError('birth query race')
                    return original(h,pid)
                b.held_identity=query
            try:
                with self.assertRaises(OSError):f.capture()
            finally:f.close()
            self.assertCountEqual(b.closed,b.opened)
    def test_cleanup_continues_after_close_error_and_retains_unknown_handle(self):
        b=Backend();f=self.make(b);f.capture();original=b.close
        def close(h):
            if h==20:raise OSError('close failed')
            original(h)
        b.close=close
        with self.assertRaises(OSError):f.close()
        self.assertEqual(list(f.handles),[20]);self.assertCountEqual(b.closed,[10,30,40])
        b.close=original;f.close();self.assertEqual(f.handles,{})
    def test_window_owner_change_fails_closed(self):
        b=Backend();f=self.make(b)
        try:
            f.capture();a=Windows();a.flip=True
            with self.assertRaisesRegex(OSError,'changed'):diagnostics.forest_classes(a,f)
        finally:f.close()
    def test_window_owner_changes_before_class_so_no_class_read(self):
        b=Backend();f=self.make(b)
        try:
            f.capture();a=Windows();original=a.visible
            def visible(h):
                result=original(h);a.rows[h][0]=999;return result
            a.visible=visible
            with self.assertRaisesRegex(OSError,'changed'):diagnostics.forest_classes(a,f)
            self.assertEqual(a.reads,[])
        finally:f.close()
    def test_process_window_visit_and_byte_bounds(self):
        b=Backend();b.pids=list(range(1,66));f=self.make(b)
        with self.assertRaisesRegex(OSError,'ceiling'):f.capture()
        b=Backend();f=self.make(b)
        try:
            f.capture()
            for count,owner in ((257,30),(4097,999)):
                a=Windows();a.rows={h:[owner,True,'C'] for h in range(1,count+1)}
                with self.assertRaisesRegex(OSError,'ceiling'):diagnostics.forest_classes(a,f)
            # Maximum ancestry expansion must reject before retaining >1MiB of records.
            f.chains[30]=[dict(f.identities[30],image='x'*1024)]*64
            a=Windows();a.rows={h:[30,True,'C'] for h in range(1,30)}
            with self.assertRaisesRegex(OSError,'byte ceiling'):diagnostics.forest_classes(a,f)
        finally:f.close()
if __name__=='__main__':unittest.main()
