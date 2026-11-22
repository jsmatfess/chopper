#!/usr/bin/env python3
"""Small corruption controls for the cross-tool CSV verifier; no benchmarks."""
import csv
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location('comparison', Path(__file__).with_name('benchmark-tool-comparison.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

with tempfile.TemporaryDirectory() as directory:
    out = Path(directory)
    def fixture(ids):
        for i in range(8):
            with (out / f'{i:02}.csv').open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(m.HEADER)
                writer.writerows([f'{ordinal:010d}', '00001', '', m.PAYLOAD] for ordinal in ids[i * 2:i * 2 + 2])
    def reject(ids, job):
        fixture(ids)
        try:
            m.verify(out, 16, job, 'duckdb')
        except AssertionError:
            return
        raise AssertionError('corruption accepted')
    fixture(list(range(16)))
    assert m.verify(out, 16, 'balanced', 'duckdb')['counts'] == [2] * 8
    fixture(list(reversed(range(16))))
    assert m.verify(out, 16, 'shuffle', 'duckdb')['rows'] == 16
    reject([0] * 16, 'shuffle')
    reject(list(reversed(range(16))), 'balanced')
    reject(list(range(16)), 'shuffle')
    reject([*range(15), 16], 'shuffle')
    fixture(list(range(16)))
    p = out / '00.csv'
    p.write_text(p.read_text().replace('00001', '1'))
    try:
        m.verify(out, 16, 'balanced', 'duckdb')
    except AssertionError:
        pass
    else:
        raise AssertionError('text coercion accepted')
print('Verifier accepts valid order/permutation and rejects duplicates, missing/out-of-range IDs, wrong order, identity shuffle and leading-zero loss.')
