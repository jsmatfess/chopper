#!/usr/bin/env python3
"""Tiny actual-binary guide controls. Linux PTY is real; Windows PTY is pending.

Run under the host validation lock, after building a default binary. Optional
--fault-binary names a resource-contract-tests binary for deterministic barriers.
All evidence goes into a new --artifacts directory. No benchmarks or sleeps.
"""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


def verify_output(source, output, rows_cap=2, bytes_cap=64):
    with open(source, newline='', encoding='utf-8') as stream:
        expected = list(csv.reader(stream))
    actual = []
    paths = sorted(Path(output).glob('*.csv'))
    assert paths
    for path in paths:
        raw = path.read_bytes()
        records = list(csv.reader(io.StringIO(raw.decode('utf-8'), newline='')))
        assert records[0] == expected[0]
        assert len(records) - 1 <= rows_cap
        assert len(raw) <= bytes_cap
        actual.extend(records[1:])
    assert actual == expected[1:], (actual, expected)
    manifest = [json.loads(line) for line in (Path(output) / 'manifest.jsonl').read_text().splitlines()]
    jobs = [record for record in manifest if record['type'] == 'job']
    outputs = [record for record in manifest if record['type'] == 'output']
    assert len(jobs) == 1 and len(outputs) == len(paths)
    assert jobs[0]['analysis']['rows'] == len(actual)
    assert jobs[0]['analysis']['output_files'] == len(paths)
    assert jobs[0]['analysis']['output_csv_bytes'] == sum(p.stat().st_size for p in paths)
    for record, path in zip(outputs, paths):
        with path.open(newline='', encoding='utf-8') as stream:
            count = len(list(csv.reader(stream))) - 1
        assert record['path'] == path.name and record['rows'] == count
        assert record['csv_bytes'] == record['stored_bytes'] == path.stat().st_size
    return paths


class Pty:
    active = set()
    def __init__(self, binary, root, name, config=None, env=None, stdout=None):
        import pty
        import termios
        self.master, slave = pty.openpty()
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        self.root = root
        self.log = open(root / f'{name}.tty.log', 'wb')
        self.stdout = open(root / f'{name}.stdout.json', 'wb') if stdout is None else stdout
        self.buffer = b''
        self.process = subprocess.Popen([str(binary), 'guide'] + (['--config', str(config)] if config else []),
                                        stdin=slave, stderr=slave, stdout=self.stdout,
                                        cwd=root, env=env, start_new_session=True)
        os.close(slave)
        self.active.add(self)

    def expect(self, text):
        wanted = text.encode()
        deadline = time.monotonic() + 20
        while wanted not in self.buffer:
            remaining = deadline - time.monotonic()
            assert remaining > 0, (text, self.buffer[-3000:])
            readable, _, _ = select.select([self.master], [], [], remaining)
            assert readable, (text, self.buffer[-3000:])
            try:
                data = os.read(self.master, 65536)
            except OSError:
                data = b''
            assert data, (text, self.buffer[-3000:], self.process.poll())
            self.log.write(data)
            self.log.flush()
            self.buffer += data
        index = self.buffer.index(wanted) + len(wanted)
        self.buffer = self.buffer[index:]

    def send(self, text):
        data = (text + '\n').encode()
        while data:
            data = data[os.write(self.master, data):]

    def nav(self, action):
        self.expect('98 Run (review)')
        self.send(action)

    def finish(self, code=0):
        try:
            actual = self.process.wait(timeout=20)
            # Drain all remaining PTY bytes into the raw artifact.
            while select.select([self.master], [], [], 0)[0]:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.log.write(data)
            assert actual == code, (actual, code)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            os.close(self.master)
            self.log.close()
            self.stdout.close()
            self.active.discard(self)


def config_file(root, name, source, **updates):
    job = dict(version=1, input=str(source), output=str(root / name), limits=dict(rows=2, bytes=64))
    job.update(updates)
    path = root / (name + '.json')
    path.write_text(json.dumps(job), encoding='utf-8')
    return path


def review(p):
    p.nav('91')
    p.expect('6 Review')
    p.send('6')


def run_tests(binary, fault_binary, root):
    source = root / 'source 雪.csv'
    source.write_text('id,text\n1,"a,b"\n2,"a\nline"\n3,"say ""yes"""\n', encoding='utf-8')
    non_tty = subprocess.run([str(binary), 'guide', '--config', 'missing.json'], input=b'', capture_output=True, timeout=10)
    (root / 'non-tty.stderr').write_bytes(non_tty.stderr)
    assert non_tty.returncode == 1 and b'requires terminal stdin and stderr' in non_tty.stderr
    assert b'No such file' not in non_tty.stderr and not non_tty.stdout
    if sys.platform != 'linux':
        # No fake is_terminal seam is counted as Windows terminal coverage.
        return ['native non-TTY gate'], ['native Windows actual-PTY journeys and cancellation pending']
    saved = root / "saved job's 雪.json"
    p = Pty(binary, root, 'journey')
    p.nav('1'); p.expect('Input path'); p.send(str(source)); p.expect('Accept path?'); p.send('yes')
    p.nav('2'); p.nav('1'); p.expect('Start full scan?'); p.send('yes'); p.expect('3 exact rows')
    p.nav('90'); p.nav('2'); p.nav('2')
    p.nav('1'); p.expect('Output directory'); p.send(str(root / 'guided output 雪')); p.expect('Accept path?'); p.send('y')
    p.nav('2'); p.nav('1'); p.expect('Caps:'); p.send('1'); p.expect('Value ('); p.send('2')
    p.nav('1'); p.expect('Caps:'); p.send('2'); p.expect('Value ('); p.send('64')
    p.nav('92'); p.expect('configuration path'); p.send(str(saved)); p.expect('POSIX shell: ')
    p.expect('Relative paths use the process working directory.')
    # Clean reload and decline the first Run (default No).
    p.nav('93'); p.expect('Reload configuration path'); p.send(str(saved)); p.expect('Loaded intact')
    review(p); p.nav('98'); p.expect('[y/N]'); p.send('')
    p.nav('98'); p.expect('[y/N]'); p.send('yes'); p.finish()
    analysis = json.loads((root / 'journey.stdout.json').read_text())
    job = json.loads(saved.read_text())
    assert analysis['seed'] == job['seed'] and analysis['rows'] == 3
    verify_output(source, root / 'guided output 雪')
    rerun = dict(job, output=str(root / 'scripted output 雪'))
    rerun_path = root / "rerun's 雪.json"; rerun_path.write_text(json.dumps(rerun), encoding='utf-8')
    # Execute the same POSIX argument quoting emitted by the guide, including an apostrophe.
    quoted = "'" + str(rerun_path).replace("'", "'\"'\"'") + "'"
    executable = "'" + str(binary).replace("'", "'\"'\"'") + "'"
    result = subprocess.run(['/bin/sh', '-c', f'{executable} run --config {quoted} --yes --reproducible'], capture_output=True, timeout=20)
    (root / 'scripted.stdout.json').write_bytes(result.stdout); (root / 'scripted.stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['seed'] == job['seed']
    paths = verify_output(source, root / 'scripted output 雪')
    for path in paths:
        assert path.read_bytes() == (root / 'guided output 雪' / path.name).read_bytes()
    # The byte cap itself binds chunk boundaries (including quotes/newlines/header).
    config = config_file(root, 'byte-boundary', source, limits=dict(rows=2, bytes=24))
    p = Pty(binary, root, 'byte-boundary', config); review(p); p.nav('98'); p.expect('[y/N]'); p.send('yes'); p.finish()
    assert len(verify_output(source, root / 'byte-boundary', bytes_cap=24)) == 3
    # Skip inspection; save-only emits no Analysis and creates no output.
    config = config_file(root, 'skip-output', source)
    p = Pty(binary, root, 'save-only', config)
    p.nav('96'); p.expect('configuration path'); p.send(str(root / 'skip-saved.json')); p.finish()
    assert not (root / 'save-only.stdout.json').read_bytes() and not (root / 'skip-output').exists()
    # Idle interrupt is handled without requiring a newline.
    p = Pty(binary, root, 'idle-interrupt', config); p.expect('98 Run (review)'); p.process.send_signal(signal.SIGINT); p.finish(1)
    # EOF at navigation, value, path confirmation, save and Run/overwrite confirmation.
    for name, actions in [('navigation', []), ('value', [('nav', '1')]),
                          ('path-confirm', [('nav', '1'), ('Input path', str(source))]),
                          ('save', [('nav', '92')]), ('overwrite', [('nav', '92'), ('configuration path', str(saved))]),
                          ('run-confirm', [('nav', '91'), ('6 Review', '6'), ('nav', '98')])]:
        p = Pty(binary, root, 'eof-' + name, config)
        for prompt, value in actions:
            if prompt == 'nav': p.nav(value)
            else: p.expect(prompt); p.send(value)
        target = {'navigation':'98 Run (review)', 'value':'Input path', 'path-confirm':'Accept path?', 'save':'configuration path', 'overwrite':'Overwrite existing', 'run-confirm':'[y/N]'}[name]
        p.expect(target); os.write(p.master, b'\x04'); p.finish(1)
        assert not (root / ('eof-' + name + '.stdout.json')).read_bytes()
    # Strict caps, invalid resources, malformed late CSV and nonempty output are recoverable.
    bad_source = root / 'late.csv'; bad_source.write_text('id,text\n1,ok\n2,"bad\n')
    nonempty = root / 'nonempty'; nonempty.mkdir(); (nonempty / 'unrelated').write_text('keep')
    failures = [dict(name='header-cap', limits=dict(bytes=1)), dict(name='row-cap', limits=dict(bytes=12)),
                dict(name='memory', resources=dict(memory_mb=32)), dict(name='workers', resources=dict(workers=65)),
                dict(name='late-malformed', input=str(bad_source)), dict(name='nonempty', output=str(nonempty))]
    for fields in failures:
        name = fields.pop('name'); config = config_file(root, name, source, **fields)
        p = Pty(binary, root, name, config); review(p); p.nav('98')
        if name in ('header-cap', 'row-cap', 'late-malformed'):
            p.expect('[y/N]'); p.send('yes'); p.expect('Run failed after owners stopped')
        else:
            p.expect('Error:')
        p.nav('95')
        # Run review generates a retained seed and thus a dirty draft.
        if name in ('header-cap', 'row-cap', 'late-malformed'):
            p.expect('Save dirty draft'); p.send('')
        p.finish()
        if name != 'nonempty': assert not (root / name).exists()
    assert (nonempty / 'unrelated').read_text() == 'keep'
    # Save replacement failure is recoverable, preserves unrelated files and seed.
    config = config_file(root, 'save-failure-output', source, seed='retained-seed')
    blocked = root / 'blocked-config'; blocked.mkdir(); (blocked / 'unrelated').write_text('keep')
    p = Pty(binary, root, 'save-failure', config)
    p.nav('92'); p.expect('configuration path'); p.send(str(blocked)); p.expect('Overwrite existing'); p.send('yes'); p.expect('atomic configuration save failed')
    p.nav('96'); p.expect('configuration path'); p.send(str(root / 'after-failure.json')); p.finish()
    assert json.loads((root / 'after-failure.json').read_text())['seed'] == 'retained-seed'
    assert (blocked / 'unrelated').read_text() == 'keep'
    assert not (root / 'save-failure-output').exists()
    # Oversized real terminal response: raw mode avoids the kernel's canonical
    # line-length limit; it is still an actual PTY, never a fake is_terminal flag.
    import termios
    p = Pty(binary, root, 'line-bound', config)
    p.nav('1'); p.expect('Input path')
    attrs = termios.tcgetattr(p.master); attrs[3] &= ~termios.ICANON; termios.tcsetattr(p.master, termios.TCSANOW, attrs)
    p.send('x' * (65536 + 1)); p.finish(1)
    assert b'64 KiB' in (root / 'line-bound.tty.log').read_bytes()
    # Job length/schema/version failures occur after the terminal gate.
    for name, data in [('job-bound', b' ' * (1024 * 1024 + 1)), ('job-version', b'{"version":2}'), ('job-schema', b'{"removed":true}'), ('job-control', b'{"\\u001b":true}')]:
        path = root / (name + '.json'); path.write_bytes(data)
        p = Pty(binary, root, name, path)
        p.finish(1)
        assert not (root / (name + '.stdout.json')).read_bytes()
        assert b'\x1b' not in (root / (name + '.tty.log')).read_bytes()
    # Control text is escaped/truncated only for presentation; imported text and
    # config paths remain intact, and optional inspection never modifies them.
    control_source = root / 'control-\x1b.csv'
    control_source.write_text('h' * 270 + ',value\n1,escape-\x1b-end\n', encoding='utf-8')
    config = config_file(root, 'control-output', control_source)
    p = Pty(binary, root, 'control-display', config)
    p.nav('2'); p.nav('1'); p.expect('Start full scan?'); p.send('yes'); p.expect('1 exact rows'); p.nav('95'); p.finish()
    raw = (root / 'control-display.tty.log').read_bytes()
    assert b'\x1b' not in raw and b'[truncated]' in raw and b'\\u{1b}' in raw
    # Once commit succeeds, stdout failure must preserve the complete output.
    config = config_file(root, 'postcommit', source)
    p = Pty(binary, root, 'postcommit', config, stdout=open('/dev/full', 'wb'))
    review(p); p.nav('98'); p.expect('[y/N]'); p.send('yes'); p.finish(1)
    verify_output(source, root / 'postcommit')
    if fault_binary:
        for phase in ['profile-row', 'direct-row']:
            name = 'cancel-' + phase
            release = root / (name + '.fifo'); os.mkfifo(release)
            config = config_file(root, name, source)
            env = dict(os.environ, CHOPPER_GUIDE_TEST_PHASE=phase, CHOPPER_GUIDE_TEST_RELEASE=str(release))
            p = Pty(fault_binary, root, name, config, env)
            if phase == 'profile-row': p.nav('2'); p.nav('1'); p.expect('Start full scan?'); p.send('yes')
            else: review(p); p.nav('98'); p.expect('[y/N]'); p.send('yes')
            p.expect('guide test barrier: ' + phase); p.process.send_signal(signal.SIGINT); p.expect('guide test interrupt received')
            with open(release, 'wb', buffering=0) as pipe: pipe.write(b'x')
            p.finish(1); assert not (root / name).exists()
        # Destination introduced after review and after the first parsed row.
        release = root / 'late-create.fifo'; os.mkfifo(release)
        config = config_file(root, 'late-create', source)
        env = dict(os.environ, CHOPPER_GUIDE_TEST_PHASE='direct-row', CHOPPER_GUIDE_TEST_RELEASE=str(release))
        p = Pty(fault_binary, root, 'late-create', config, env); review(p); p.nav('98'); p.expect('[y/N]'); p.send('yes')
        p.expect('guide test barrier: direct-row'); destination = root / 'late-create'; destination.mkdir(); (destination / 'unrelated').write_text('keep')
        with open(release, 'wb', buffering=0) as pipe: pipe.write(b'x')
        p.expect('Run failed after owners stopped'); p.nav('95'); p.expect('Save dirty draft'); p.send(''); p.finish()
        assert (destination / 'unrelated').read_text() == 'keep' and list(destination.iterdir()) == [destination / 'unrelated']
    assert not list(root.glob('.chopper-*')), list(root.glob('.chopper-*'))
    return ['Linux actual-binary PTY journey, save/reload/default-No/confirm, inspection and skip, seeded shell rerun, stdout separation, EOF, idle SIGINT, caps/resources/late malformed/destination errors, postcommit stdout failure',
            'resource-contract binary profile/direct-row SIGINT and late-destination barriers' if fault_binary else 'fault binary not supplied'], ['native Windows actual-PTY journeys, PowerShell quoting and platform gates pending']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--verify-source', type=Path)
    parser.add_argument('--verify-output', type=Path)
    parser.add_argument('--fault-binary', type=Path)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    if args.verify_source and args.verify_output:
        verify_output(args.verify_source, args.verify_output)
        print('CSV field/order/row-cap/serialized-byte verification passed')
        return
    if not args.binary or not args.artifacts: parser.error('--binary and --artifacts are required for binary controls')
    root = args.artifacts.resolve(); root.mkdir(parents=True, exist_ok=False)
    try:
        coverage, pending = run_tests(args.binary.resolve(), args.fault_binary.resolve() if args.fault_binary else None, root)
        (root / 'result.json').write_text(json.dumps(dict(coverage=coverage, pending=pending), indent=2))
        print(json.dumps(dict(coverage=coverage, pending=pending)))
    except BaseException:
        (root / 'FAILED').write_text('Preserve raw transcripts; this attempt failed.\n')
        raise
    finally:
        # An assertion at a test-only barrier must not orphan a blocked owner.
        for child in list(Pty.active):
            if child.process.poll() is None:
                child.process.kill()
                child.process.wait(timeout=10)
            os.close(child.master)
            child.log.close()
            child.stdout.close()
            Pty.active.discard(child)


if __name__ == '__main__':
    main()
