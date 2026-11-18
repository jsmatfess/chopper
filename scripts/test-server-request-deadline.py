#!/usr/bin/env python3
"""Tiny external native server socket controls; no build or platform emulation.

Retain stdout/stderr using --logs. --old-control expects the historical failure.
On Windows launch from an attached console so CTRL_BREAK_EVENT can be delivered.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import threading
import time


def record(case, **fields):
    print(json.dumps(dict(case=case, **fields)), flush=True)


class Server:
    def __init__(self, binary, logs):
        self.logs = logs
        logs.mkdir(parents=True, exist_ok=False)
        self.stderr = (logs / 'stderr.log').open('wb')
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        self.process = subprocess.Popen([str(binary), 'serve', '--port', '0'],
                                        stdout=subprocess.PIPE, stderr=self.stderr,
                                        creationflags=flags)
        self.line = None
        self.ready = threading.Event()

        def capture():
            with (logs / 'stdout.log').open('wb') as output:
                for line in self.process.stdout:
                    output.write(line)
                    output.flush()
                    if b'Chopper local UI:' in line:
                        self.line = line.decode()
                        self.ready.set()
        self.capture = threading.Thread(target=capture, daemon=True)
        self.capture.start()
        assert self.ready.wait(10), 'server startup exceeded 10s (see stderr.log)'
        match = re.search(r'http://(127\.0\.0\.1):(\d+)/#token=(\w+)', self.line)
        assert match, self.line
        self.host, self.port, self.token = match[1], int(match[2]), match[3]
        self.address = f'{self.host}:{self.port}'

    def request(self, path, data=None, token=True, headers=None, method=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        try:
            auth = {'X-Chopper-Token': self.token} if token else {}
            auth.update(headers or {})
            connection.request(method or ('GET' if data is None else 'POST'), path,
                               None if data is None else json.dumps(data), auth)
            response = connection.getresponse()
            payload = response.read()
            return response.status, json.loads(payload)
        finally:
            connection.close()

    def hold(self, path='/api/analyze', chunked=False, small=False, token=True,
             expect_continue=False):
        stream = socket.create_connection((self.host, self.port), timeout=2)
        stream.settimeout(7)
        framing = 'Transfer-Encoding: chunked' if chunked else f'Content-Length: {100 if small else 100000}'
        auth = f'X-Chopper-Token: {self.token}\r\n' if token else ''
        if expect_continue:
            auth += 'Expect: 100-continue\r\n'
        stream.sendall((f'POST {path} HTTP/1.1\r\nHost: {self.address}\r\n{auth}{framing}\r\n\r\n').encode()
                       + (b'1\r\n{\r\n' if chunked else b'{'))
        return stream

    def state(self):
        code, value = self.request('/api/state')
        assert code == 200, value
        return value

    def wait(self, expected):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.state()
            if state['status'] in expected:
                return state
            assert state['status'] not in ('failed', 'cancelled'), state
            time.sleep(.02)
        raise AssertionError(f'job did not reach {expected}')

    def stop(self):
        start = time.monotonic()
        self.process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
        code = self.process.wait(timeout=3)
        assert code == 0, code
        record('signal_shutdown', elapsed=time.monotonic() - start, exit=code)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        self.capture.join(timeout=2)
        self.stderr.close()


def expired(stream):
    try:
        response = stream.recv(8192)
        assert not response or b' 400 ' in response or b' 408 ' in response, response
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--logs', type=Path, required=True, help='new owned directory')
    parser.add_argument('--old-control', action='store_true')
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    record('identity', binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
           platform=os.name, old_control=args.old_control)
    server = Server(binary, args.logs.resolve())
    sockets = []
    try:
        if args.old_control:
            held = server.hold()
            sockets.append(held)
            try:
                server.state()
            except (TimeoutError, OSError):
                record('old_status_blocked', expected=True)
            else:
                raise AssertionError('old failure was not reproduced')
            server.process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
            try:
                server.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                record('old_shutdown_blocked', expected=True)
            else:
                raise AssertionError('old shutdown failure was not reproduced')
            return

        # Isolate the actual Windows reader timeout before any saturation/queueing.
        held = server.hold()
        sockets.append(held)
        start = time.monotonic()
        expired(held)
        elapsed = time.monotonic() - start
        assert elapsed < 7, elapsed
        record('absolute_expiry', chunked=False, small=False, trickle=False, elapsed=elapsed)
        held.close()
        sockets.remove(held)

        # Four body handlers, then bounded denial without waiting for unread body.
        for path in ['/api/analyze', '/api/profile', '/api/columns', '/api/pick-path']:
            sockets.append(server.hold(path))
            # Separate requests establish dispatcher progress before the next hold.
            assert server.state()['status'] == 'idle'
        extra = server.hold('/api/run-direct')
        sockets.append(extra)
        start = time.monotonic()
        assert b' 503 ' in extra.recv(8192)
        assert time.monotonic() - start < 2
        for path in ['/api/state', '/api/cancel', '/api/run']:
            start = time.monotonic()
            code, _ = server.request(path, None if path == '/api/state' else {})
            assert code == (400 if path == '/api/run' else 200)
            assert time.monotonic() - start < 2
        record('saturation_control_routes', handlers=4, excess=503, bound_seconds=2)
        for stream in sockets:
            stream.close()
        sockets.clear()
        # A complete defaults GET ensures transport progress; handlers reap on next POST.
        defaults = server.request('/api/defaults')[1]
        deadline = time.monotonic() + 2
        while server.request('/api/sniff', {})[0] == 503:
            assert time.monotonic() < deadline, 'handlers did not release after disconnect'
            time.sleep(.02)
        for chunked, small, trickle in [(False, True, False),
                                        (True, False, False), (False, False, True),
                                        (True, False, True)]:
            held = server.hold(chunked=chunked, small=small)
            sockets.append(held)
            start = time.monotonic()
            if trickle:
                for _ in range(12):
                    time.sleep(.5)
                    try:
                        held.sendall(b'1\r\n \r\n' if chunked else b' ')
                    except OSError:
                        break
            expired(held)
            elapsed = time.monotonic() - start
            assert elapsed < 7, elapsed
            assert server.state()['status'] == 'idle'
            deadline = time.monotonic() + 2
            probes = []
            try:
                for _ in range(4):
                    probe = server.hold(expect_continue=True)
                    probes.append(probe)
                    # as_reader sends this only after body-handler admission.
                    response = bytearray()
                    while not response.endswith(b'\r\n\r\n'):
                        remaining = deadline - time.monotonic()
                        assert remaining > 0, 'expired handler did not release'
                        probe.settimeout(remaining)
                        byte = probe.recv(1)
                        assert byte and len(response) < 512, response
                        response.extend(byte)
                    assert response.split(b'\r\n', 1)[0] == b'HTTP/1.1 100 Continue', response
                assert server.request('/api/sniff', {})[0] == 503
                assert time.monotonic() < deadline, 'expired handler did not release'
            finally:
                for probe in probes:
                    probe.close()
            deadline = time.monotonic() + 2
            while server.request('/api/sniff', {})[0] == 503:
                assert time.monotonic() < deadline, 'release probes did not retire'
                time.sleep(.02)
            record('absolute_expiry', chunked=chunked, small=small, trickle=trickle, elapsed=elapsed)
            held.close()
            sockets.remove(held)

        assert server.request('/api/analyze', {}, token=False)[0] == 403
        assert server.request('/api/state', headers={'Host': 'untrusted'})[0] == 403
        assert server.request('/api/state', headers={'Origin': 'http://untrusted'})[0] == 403
        root = (server.logs / 'fixture').resolve()
        root.mkdir()
        source = root / 'input.csv'
        source.write_bytes(b'id,value\r\n1,a\r\n2,b\r\n3,c\r\n')
        job = dict(defaults, input=str(source), output=str(root / 'prepared'))
        job['resources']['temp_dir'] = str(root)
        assert server.request('/api/profile', job)[0] == 200
        assert server.wait({'profiled'})['profile'] is not None
        connection = http.client.HTTPConnection(server.host, server.port, timeout=2)
        try:
            payload = json.dumps(job).encode()
            connection.request('POST', '/api/profile', iter([payload[:1], payload[1:]]),
                               {'X-Chopper-Token': server.token}, encode_chunked=True)
            response = connection.getresponse()
            assert response.status == 200, response.read()
            response.read()
        finally:
            connection.close()
        server.wait({'profiled'})
        assert server.request('/api/analyze', job)[0] == 200
        server.wait({'ready'})
        # Invalid replacement preserves the prepared snapshot.
        assert server.request('/api/analyze', {})[0] == 400
        assert server.state()['status'] == 'ready'
        assert server.request('/api/run', {})[0] == 200
        server.wait({'complete'})
        expected = b'id,value\n1,a\n2,b\n3,c\n'
        prepared = list((root / 'prepared').glob('*.csv'))
        assert len(prepared) == 1
        assert prepared[0].read_bytes().replace(b'\r\n', b'\n') == expected
        job['output'] = str(root / 'direct')
        assert server.request('/api/run-direct', job)[0] == 200
        server.wait({'complete'})
        direct = list((root / 'direct').glob('*.csv'))
        assert len(direct) == 1 and direct[0].read_bytes() == prepared[0].read_bytes()
        record('complete_profile_prepare_confirm_run', csv_bytes_equal=True)
        # Ready snapshot owns temporary data; shutdown must dispose it despite held body.
        job['output'] = str(root / 'unpublished')
        assert server.request('/api/analyze', job)[0] == 200
        server.wait({'ready'})
        sockets.append(server.hold(chunked=True))
        server.state()
        server.stop()
        assert not (root / 'unpublished').exists()
        assert sorted(p.name for p in root.iterdir()) == ['direct', 'input.csv', 'prepared']
        record('owned_preparation_cleanup', incomplete_output=False)
    finally:
        for stream in sockets:
            stream.close()
        server.close()


if __name__ == '__main__':
    main()
