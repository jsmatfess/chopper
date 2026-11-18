"""Recover native self-sample attribution when perf was built without libelf.

Usage: python3 scripts/symbolize-perf-offsets.py BINARY PERF_DATA
Only for perf's raw DSO file offsets (libelf OFF). Translate offsets through ELF
LOAD segments before addr2line; PIE virtual addresses need not equal file offsets.
Reports outermost inline functions, not runtime caller stacks. Other DSOs remain
unattributed rather than guessing symbols from stripped system libraries.
"""
from collections import Counter
import json
from pathlib import Path
import re
import struct
import subprocess
import sys


def summarize(binary, data):
    blob = Path(binary).read_bytes()
    if blob[:6] != b'\x7fELF\x02\x01':
        raise ValueError('requires little-endian ELF64')
    phoff = struct.unpack_from('<Q', blob, 32)[0]
    entsize, count = struct.unpack_from('<HH', blob, 54)
    segments = []
    for index in range(count):
        kind, flags, offset, address, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', blob, phoff + index * entsize)
        if kind == 1 and flags & 1:
            segments.append((offset, address, size))
    report = subprocess.check_output(['perf', 'report', '--stdio', '--no-children', '--call-graph', 'none',
        '--percent-limit', '0', '-n', '-s', 'dso,symbol', '-i', str(data)], text=True)
    totals = Counter()
    addresses = Counter()
    for line in report.splitlines():
        match = re.match(r'\s*[\d.]+%\s+(\d+)\s+(\S+)\s+\[.\]\s+(0x[0-9a-f]+)', line)
        if not match:
            continue
        samples, dso, offset = match.groups()
        symbol = f'{dso} (unattributed)'
        if dso == Path(binary).name:
            offset = int(offset, 16)
            for start, address, size in segments:
                if start <= offset < start + size:
                    addresses[address + offset - start] += int(samples)
                    symbol = None
                    break
        if symbol is not None:
            totals[symbol] += int(samples)
    if addresses:
        decoded = subprocess.run(['addr2line', '-a', '-i', '-f', '-C', '-e', str(binary)],
                                 input=''.join(hex(a) + '\n' for a in addresses),
                                 text=True, capture_output=True, check=True).stdout
        parts = re.split(r'(?m)^(0x[0-9a-f]+)\n', decoded)
        for index in range(1, len(parts), 2):
            frames = parts[index + 1].splitlines()
            symbol = frames[-2] if len(frames) >= 2 else 'chopper (unattributed)'
            totals[symbol] += addresses[int(parts[index], 16)]
    total = sum(totals.values())
    if not total:
        return {'samples': 0, 'functions': [],
                'attribution': 'no raw offset samples; increase fixture size or inspect the perf report'}
    return {'samples': total, 'attribution': 'self samples; outermost inline function; no runtime stacks',
            'functions': [{'function': k, 'samples': v, 'percent': round(v / total * 100, 2)}
                          for k, v in totals.most_common()]}


if __name__ == '__main__':
    print(json.dumps(summarize(sys.argv[1], sys.argv[2])))
