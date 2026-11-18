"""Read-only native windows after one output-path click; never resolves a prompt."""
import json,time
import diagnostics,selection

def observe(windows,job,root,node,session,guard,api,retain,layout,publish=lambda value:None,clock=None):
    clock=clock or time.monotonic
    deadline=clock()+10
    def bounded():
        guard()
        if clock()>=deadline:raise OSError('Post-click observation deadline')
    diagnostics.settle_job(windows,job,bounded,clock,time.sleep,deadline)
    forest=diagnostics.HeldForest(windows,job,root,node,session,bounded)
    retain(forest);forest.capture()
    visits=0
    def snapshot():
        result=[];seen=set();total=0
        def read(h,pid,fn):
            forest.check_chain(pid)
            if api.owner(h)!=pid:raise OSError('Post-click HWND owner changed')
            value=fn(h)
            forest.check_chain(pid)
            if api.owner(h)!=pid:raise OSError('Post-click HWND owner changed')
            return value
        def row(h,pid):
            cls=read(h,pid,api.class_name)
            if not isinstance(cls,str) or not 0<len(cls)<=127:raise OSError('Post-click class bound')
            visible=read(h,pid,api.visible);enabled=read(h,pid,api.enabled)
            return dict(hwnd=h,owner=pid,parent=read(h,pid,api.parent),id=read(h,pid,api.control_id),
                        visible=visible,enabled=enabled,ready=visible and enabled,**{'class':cls},caption=None)
        def visit(h):
            nonlocal visits,total
            bounded();visits+=1
            if visits>4096:raise OSError('Post-click top-level visit ceiling')
            pid=api.owner(h)
            if pid not in forest.chains:return True
            if h in seen or len(result)>=64:raise OSError('Post-click top-level duplicate/ceiling')
            seen.add(h);top=row(h,pid);top['nodes']=[];children={h}
            def child(c):
                nonlocal total
                bounded();total+=1
                if c in children or len(top['nodes'])>=255 or total>512:raise OSError('Post-click child duplicate/ceiling')
                owner=api.owner(c)
                if owner not in forest.chains:raise OSError('Post-click foreign child')
                value=row(c,owner)
                if value['parent'] not in children:raise OSError('Post-click child hierarchy changed')
                children.add(c);top['nodes'].append(value);return True
            api.children(h,child);forest.check();result.append(top);return True
        api.enumerate(visit);forest.check()
        return result
    first=snapshot();second=snapshot()
    if first!=second:raise OSError('Post-click window tree changed')
    folders=[v for v in first if v['class']=='#32770']
    result=dict(kind='exact-owned-post-output-click-windows',windows=first,processes=list(forest.identities.values()),
                root=root,node=node,session=session,visited=visits,captionsSuppressed=True,
                classicDialogCount=len(folders),chromeWidgetCount=sum(v['class'].startswith('Chrome_Widget') for v in first),
                folderState='absent' if not folders else 'unknown-native-dialog-layout',
                interpretation='Unclassified native metadata; no permission or navigation inferred',
                acceptance=False,selectionEnabled=False,runs=0,additionalClicks=0)
    if len(json.dumps(result).encode())>128*1024:raise OSError('Post-click byte ceiling')
    publish(result)
    if len(folders)==1:
        f=folders[0]
        # Only the already-reviewed folder Edit1152 may be read; never the address edit.
        snap=dict(hwnd=f['hwnd'],identity=dict(pid=f['owner']),rootClass=f['class'],rootReady=f['ready'],mode='observe-output',
                  nodes=[{k:v[k] for k in ('hwnd','parent','owner','id','ready','class','caption')} for v in f['nodes']])
        try:bound=selection.bind_output(snap,layout)
        except (AssertionError,KeyError):bound=None
        if bound is not None:
            selection.recheck(api,forest,snap)
            count,text=api.message(bound[0],0x000d,selection.OUTPUT)
            if not isinstance(count,int) or not isinstance(text,str) or count!=len(text) or count>len(selection.OUTPUT):
                raise OSError('Post-click folder read truncated/unavailable')
            selection.recheck(api,forest,snap)
            result.update(folderState='one-known-folder-layout',folderEdit=dict(id=1152,count=count,text=text,readOnly=True))
    bounded();forest.check()
    if len(json.dumps(result).encode())>128*1024:raise OSError('Post-click byte ceiling')
    return result
