"""Compute the unchanged diagnostic null once; no candidate output is observed."""
import argparse
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import platform


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    spec=importlib.util.spec_from_file_location('diagnostics',Path(__file__).with_name('diagnose-shuffle.py'))
    d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    source=''.join(inspect.getsource(getattr(d,name)) for name in ['fixture','metrics','discrepancy','combined','null_distribution'])
    contract={'version':'shuffle-diagnostic-null-v1','python':platform.python_version(),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'seeds':d.SEEDS,'patterns':d.PATTERNS,'metrics':d.METRICS,'pilot':d.PILOT,'corpora':d.NULL_CORPORA}
    result={'contract':contract,'patterns':{}}
    for pattern in d.PATTERNS:
        records=[]
        center,corpora=d.null_distribution(pattern,d.fixture(pattern),records.append)
        result['patterns'][pattern]={'record':records[0],'center':center,'corpora':corpora}
        print(json.dumps({'pattern':pattern,'computed':True}),flush=True)
    args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')


if __name__=='__main__':main()
