"""Read-only exact selected639 ZIP verification and production-only static handler."""
import hashlib,io,zipfile
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from pathlib import Path

def read_package(path,binding):
    raw=Path(path).read_bytes()
    assert len(raw)==binding['package']['bytes'] and hashlib.sha256(raw).hexdigest()==binding['package']['sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist(); expected=binding['assets']
        assert len(names)==7 and len(set(names))==7 and set(names)==set(expected)
        result={}
        for name,identity in expected.items():
            value=z.read(name)
            assert len(value)==identity['bytes'] and hashlib.sha256(value).hexdigest()==identity['sha256']
            result['/'+name]=value
        assert b'Cross-Origin-Opener-Policy: same-origin' in result['/_headers']
        assert b'Cross-Origin-Embedder-Policy: require-corp' in result['/_headers']
        return result

def handler(assets):
    types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
           '.css':'text/css; charset=utf-8','.wasm':'application/wasm', '':'text/plain; charset=utf-8'}
    class Static(BaseHTTPRequestHandler):
        protocol_version="HTTP/1.0"
        timeout=1
        def do_GET(self):
            self.close_connection=True
            key=urlsplit(self.path).path
            if key=='/':key='/index.html'
            if key not in assets:
                self.send_error(404);return
            data=assets[key]
            self.send_response(200)
            self.send_header('Content-Type',types[Path(key).suffix])
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close')
            self.send_header('Cross-Origin-Opener-Policy','same-origin')
            self.send_header('Cross-Origin-Embedder-Policy','require-corp')
            self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    return Static

# No standalone server: the parent owns startup, listen-ready receipt and stop/reap.
