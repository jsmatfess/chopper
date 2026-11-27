import json
import sys
from pathlib import Path

config, receipts, report=map(Path,sys.argv[1:])
config=json.loads(config.read_text())
rows=[json.loads(line) for line in receipts.read_text().splitlines()]
assert {row['kind'] for row in rows} <= {'fixture','environment','fault','measurement'}
assert {row['name'] for row in rows if row['kind']=='fixture'} == {case['name'] for case in config['cases']}
summary={}
for case in config['cases']:
    expected=case.get('failure',{})
    actual=[row for row in rows if row.get('cell')==case['name']]
    assert [row['variant'] for row in actual] == list(case.get('variants',config['engines']))
    for row in actual:
        status=expected.get(row['variant'],'complete')
        assert row['storage']['workspace_bytes_after_cleanup']==0
        if status=='complete':
            assert row['kind']=='measurement' and row['checks']['rows']==case['rows']
        else:
            assert row['kind']=='fault' and row['status']==status and not row['entries']
            assert row['error']
        summary.setdefault(case['name'],{})[row['variant']]=status
with report.open('x') as out:
    json.dump(summary,out,indent=2)
    out.write('\n')
print(json.dumps(summary))
