import json
import runpy
import sys
from pathlib import Path

config, receipts, output = map(Path, sys.argv[1:])
cases = {case['name']: case for case in json.loads(config.read_text())['cases']}
for line in receipts.read_text().splitlines():
    row = json.loads(line)
    if row['kind'] == 'fixture':
        # Each plain three-field CSV row adds seven u64s of framing and
        # removes three delimiter/terminator bytes. The header never enters the spool.
        packed = row['bytes'] - len('id,key,payload\n') + 53 * row['rows']
        assert (packed >= 256*1024**2) == bool(cases[row['name']].get('fewer_scans')), (row['name'], packed)
    if row['kind'] != 'measurement':
        continue
    fused = row['variant'] == 'nested' and cases[row['cell']].get('fewer_scans')
    ranges = [step for step in row['physical'] if step['kind'] == 'shared_ranges']
    traversals = [step for step in row['physical'] if step['kind'] == 'balanced_traversal']
    assert len(ranges) == (0 if fused else 1), (row['cell'], row['variant'], ranges)
    step, = traversals
    assert step['operations'] == ([1,2] if fused else [2]), step
    assert step['status'] == 'completed' and step['rows'] == row['checks']['rows'], step
    assert step['groups'] == row['checks']['groups'] and step['sources'], step
runpy.run_path(str(Path(__file__).with_name('verify-results.py')), run_name='__main__')
