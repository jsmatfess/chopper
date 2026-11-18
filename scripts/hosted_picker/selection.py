"""One exact reviewed structural input binding; no output actions or fallback."""
import ctypes,time
from ctypes import wintypes as W
PATH=r'C:\desktop105-native-export-control-r5\tiny.csv'
OUTPUT=r'C:\hosted105-tiny-export-r31\attempt1\output'

def structural(snapshot):
    nodes=snapshot['nodes'];index={snapshot['hwnd']:-1}
    index.update({n['hwnd']:i for i,n in enumerate(nodes)})
    return [dict(parentIndex=index[n['parent']],**{'class':n['class']},id=n['id']) for n in nodes]

def bind(snapshot,layout):
    assert snapshot['rootClass']=='#32770' and snapshot['rootReady'] is True
    assert structural(snapshot)==layout['nodes'],'unexpected complete input layout'
    root=snapshot['hwnd'];nodes=snapshot['nodes'];pid=snapshot['identity']['pid']
    assert 1<=len(nodes)<=255 and len(nodes)==len(layout['nodes']) and len({n['hwnd'] for n in nodes})==len(nodes)
    assert all(n['owner']==pid for n in nodes)
    def unique(cls,id):
        rows=[n for n in nodes if n['class']==cls and n['id']==id]
        assert len(rows)==1 and rows[0]['ready'] is True,'unique ready control required'
        return rows[0]
    extended=unique('ComboBoxEx32',1148);combo=unique('ComboBox',1148);edit=unique('Edit',1148)
    button=unique('Button',1);cancel=unique('Button',2)
    assert extended['parent']==root and combo['parent']==extended['hwnd'] and edit['parent']==combo['hwnd']
    assert button['parent']==cancel['parent']==root
    return edit['hwnd'],button['hwnd']

def bind_output(snapshot,layout):
    assert snapshot['mode']=='observe-output' and snapshot['rootClass']=='#32770' and snapshot['rootReady'] is True
    assert structural(snapshot)==layout['nodes'],'unexpected complete output layout'
    nodes=snapshot['nodes'];root=snapshot['hwnd'];pid=snapshot['identity']['pid']
    assert 1<=len(nodes)<=255 and len(nodes)==len(layout['nodes']) and len({n['hwnd'] for n in nodes})==len(nodes)
    assert all(n['owner']==pid for n in nodes)
    def direct(cls,id):
        rows=[n for n in nodes if n['class']==cls and n['id']==id]
        assert len(rows)==1 and rows[0]['parent']==root and rows[0]['ready'] is True,'unique direct ready folder control'
        return rows[0]['hwnd']
    edit=direct('Edit',1152);button=direct('Button',1);direct('Button',2)
    return edit,button


def recheck(api,forest,snapshot):
    pid=snapshot['identity']['pid'];root=snapshot['hwnd']
    def owned(h):
        forest.check_chain(pid)
        assert api.owner(h)==pid,'window owner changed'
    owned(root)
    assert api.class_name(root)=='#32770' and api.visible(root) and api.enabled(root)
    candidates=[]
    def top(h):
        forest.check()
        owner=api.owner(h)
        if owner in forest.chains and api.visible(h) and api.class_name(h)=='#32770':candidates.append((h,owner))
        return True
    api.enumerate(top);assert candidates==[(root,pid)],'dialog uniqueness changed'
    rows=[]
    def child(h):
        assert len(rows)<255
        def read(fn):
            owned(h);v=fn(h);owned(h);return v
        rows.append(dict(hwnd=h,parent=read(api.parent),owner=pid,id=read(api.control_id),
                         ready=read(api.visible) and read(api.enabled),**{'class':read(api.class_name)},caption=None))
        return True
    api.children(root,child)
    assert rows==snapshot['nodes'],'live HWND/layout/readiness changed'
    owned(root);assert api.visible(root) and api.enabled(root)
    forest.check()

def _choose(api,forest,snapshot,layout,verify_path,guard,path,binder,clock=None):
    clock=clock or time.monotonic
    deadline=clock()+15
    def bounded():
        guard()
        if clock()>=deadline:raise OSError('Native selection deadline')
    # Observation's five-second budget ends with its result; selection has its own bounded scope.
    forest.guard=bounded
    bounded()
    bound=binder(snapshot,layout)
    def check():
        verify_path();recheck(api,forest,snapshot)
        assert binder(snapshot,layout)==bound
    check()
    assert api.message(bound[0],0x000c,path)!=0,'WM_SETTEXT refused'
    check()
    count,text=api.message(bound[0],0x000d,path)
    assert count==len(path) and text==path,'bounded exact WM_GETTEXT mismatch'
    check()
    api.message(bound[1],0x00f5,path) # BM_CLICK result is not an OS selection receipt.
    return dict(kind='native-path-click-issued',readbackExact=True,clicks=1,acceptance=False,byteConsumptionProven=False)

def choose(api,forest,snapshot,layout,verify_input,guard,clock=None,*,path=None):
    return _choose(api,forest,snapshot,layout,verify_input,guard,PATH if path is None else path,bind,clock)

def choose_output(api,forest,snapshot,layout,verify_output,guard,clock=None):
    return _choose(api,forest,snapshot,layout,verify_output,guard,OUTPUT,bind_output,clock)


class NativeMessages:
    def __init__(self,user,*,path=None):
        self.paths=(PATH,OUTPUT) if path is None else (path,)
        self.send=user.SendMessageTimeoutW
        self.send.argtypes=[W.HWND,W.UINT,ctypes.c_size_t,ctypes.c_void_p,W.UINT,W.UINT,ctypes.POINTER(ctypes.c_size_t)]
        self.send.restype=ctypes.c_ssize_t
    def message(self,h,msg,path):
        assert path in self.paths,'unbound native picker path'
        assert msg in (0x000c,0x000d,0x00f5),'unsupported native picker message'
        out=ctypes.c_size_t();capacity=len(path)+2
        text=ctypes.create_unicode_buffer(path) if msg==0x000c else ctypes.create_unicode_buffer(capacity) if msg==0x000d else None
        pointer=ctypes.cast(text,ctypes.c_void_p) if text is not None else None
        if not self.send(h,msg,capacity if msg==0x000d else 0,pointer,0x23,1000,ctypes.byref(out)):
            raise OSError('SendMessageTimeoutW failed/timed out; no retry')
        return (out.value,text.value) if msg==0x000d else out.value
