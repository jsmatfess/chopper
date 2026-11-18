"""Pure ownership and receipt gates. No native calls, no action fallback."""

CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
IMAGES = {'chrome': CHROME, 'msedge': EDGE}

def browser_owner(identity, expected, job_pids, channel, node_pid):
    assert channel in ('chrome','msedge')
    assert identity == expected, 'process birth/image/parent changed'
    assert identity['pid'] in job_pids and identity['parent'] == node_pid, 'not owned browser root'
    assert identity['image'].casefold() == (CHROME if channel == 'chrome' else EDGE).casefold()
    assert type(identity['created']) is int and identity['created'] > 0
    return identity

def observation(snapshot, expected, job_pids, session):
    assert snapshot['identity'] == expected
    assert expected['pid'] in job_pids and snapshot['session'] == session
    assert snapshot['mode'] in ('observe-input','observe-output')
    assert snapshot['rootClass'] == '#32770' and snapshot['rootReady'] is True
    root=snapshot['hwnd']; nodes=snapshot['nodes']
    assert type(root) is int and root>0 and 0<len(nodes)<=256
    assert len({n['hwnd'] for n in nodes})==len(nodes)
    by_id={n['hwnd']:n for n in nodes}
    for n in nodes:
        assert n['owner']==expected['pid'] and n['hwnd']!=root
        assert type(n['id']) is int and type(n['ready']) is bool
        assert type(n['class']) is str and len(n['class'])<=127
        assert n['caption'] is None or (n['class'] in ('Static','Button') and len(n['caption'])<=510)
        seen=set(); current=n['hwnd']
        while current!=root:
            assert current not in seen and current in by_id, 'unknown/cyclic ancestry'
            seen.add(current);current=by_id[current]['parent']
    return snapshot
