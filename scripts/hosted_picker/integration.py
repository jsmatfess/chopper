"""Pure guards and parent-owned finite static server; no server starts on import."""
import hashlib,json,os,re,stat,threading
from pathlib import Path,PureWindowsPath
from http.server import HTTPServer


def ordinary(path):
    path=Path(path)
    for p in (path,*path.parents):
        s=p.lstat()
        assert not p.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400, 'reparse/alias custody'
    s=path.stat()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1, 'ordinary single-link ZIP required'
    return s


def file_binding(path,package,candidate):
    before=ordinary(path)
    with Path(path).open('rb') as stream:
        stamp=os.fstat(stream.fileno())
        assert os.path.samestat(before,stamp)
        raw=stream.read(package['bytes']+1)
        assert len(raw)==package['bytes'] and hashlib.sha256(raw).hexdigest()==package['sha256'], 'selected ZIP bytes changed'
        assert os.path.samestat(stamp,os.fstat(stream.fileno()))
    after=ordinary(path)
    assert (stamp.st_dev,stamp.st_ino,stamp.st_size,stamp.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
    return dict(path=str(path),dev=stamp.st_dev,ino=stamp.st_ino,bytes=stamp.st_size,mtime_ns=stamp.st_mtime_ns,
                sha256=package['sha256'],candidate=candidate)


def require_custody(custody,package,candidate,binder=file_binding):
    row=custody.get('selectedZIP')
    assert isinstance(row,dict), 'Windows selected ZIP custody absent'
    p=PureWindowsPath(row['path'])
    assert p.is_absolute() and p.drive.upper()=='C:' and p.suffix.lower()=='.zip' and '..' not in p.parts
    assert type(row['ino']) is int and row['ino']>0 and type(row['dev']) is int and row['dev']>0, 'NTFS file ID absent'
    assert binder(row['path'],package,candidate)==row, 'selected ZIP custody unmatched'
    return row


def retained_ports(roots):
    ports=set()
    pattern=rb'https?://127\.0\.0\.1:([0-9]{1,5})(?=[/\s"\x27:#]|$)'
    for root in roots:
        assert root.is_dir() and not root.is_symlink(), 'retained origin root missing'
        # Audit the entire retained record namespace, including failed stdout captures.
        for path in root.rglob('*'):
            s=path.lstat()
            assert not path.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400
            if path.is_file() and path.suffix.lower() in ('.json','.jsonl','.log','.txt'):
                assert s.st_size<=8*1024**2, 'origin record too large to audit'
                data=path.read_bytes()
                ports.update(int(x) for x in re.findall(pattern,data))
    return ports


def fresh_origin(address,ports):
    host,port=address
    assert host=='127.0.0.1' and type(port) is int and 0<port<65536
    assert port not in ports, 'retained #105 server origin/port reused'
    return 'http://127.0.0.1:'+str(port)


class FiniteHTTPServer(HTTPServer):
    allow_reuse_address=False
    def get_request(self):
        sock,address=super().get_request()
        sock.settimeout(1)
        return sock,address


class OwnedServer:
    def __init__(self,assets,ports,handler,server_factory=FiniteHTTPServer):
        self.server=server_factory(('127.0.0.1',0),handler(assets))
        try:
            self.url=fresh_origin(self.server.server_address,ports)
        except BaseException:
            self.server.server_close();raise
        self.failure=None
        self.ready=threading.Event()
        def serve():
            self.ready.set()
            try:self.server.serve_forever(poll_interval=.05)
            except BaseException as error:self.failure=str(error)
        self.thread=threading.Thread(target=serve,name='owned-static',daemon=True)
        self.started=False
    def start(self):
        assert not self.started
        self.thread.start();self.started=True
        assert self.ready.wait(1) and self.thread.is_alive() and self.failure is None
        return dict(url=self.url,host=self.server.server_address[0],port=self.server.server_address[1],
                    owner=os.getpid(),http='HTTP/1.0',socketTimeoutSeconds=1)
    def stop(self):
        # A bounded helper avoids blocking the owner if serve_forever fails unexpectedly.
        shutdown=threading.Thread(target=self.server.shutdown,daemon=True)
        if self.started and self.thread.is_alive():shutdown.start();shutdown.join(2)
        self.thread.join(2) if self.started else None
        self.server.server_close()
        assert not shutdown.is_alive() and not self.thread.is_alive(), 'server shutdown/join incomplete'
        assert self.failure is None, 'server failed: '+str(self.failure)
        return True
