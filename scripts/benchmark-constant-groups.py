"""Small-parent constant-key control using the complete-job benchmark machinery.

Run with --shapes columns and at least 320 rows. c0 has 64 values; selecting all
31 keys has 320 observed tuples. Other fields and all verification stay unchanged.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

path = Path(__file__).with_name('benchmark-external-shuffle.py')
spec = importlib.util.spec_from_file_location('external', path)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
original_fields = benchmark.fields


def fields(row, shape):
    assert shape == 'columns', 'small-parent control requires --shapes columns'
    values = original_fields(row, shape)
    values[2] = str(row % 64)
    return values


def output_count(case, shape, groups):
    assert case in benchmark.CONSTANT_CASES
    return 320 if case == 'constant_partial' else 64 * (4 if case == 'constant_downstream' else 1)


if __name__ == '__main__':
    benchmark.fields = fields
    benchmark.output_count = output_count
    print(json.dumps({'type': 'fixture', 'description': __doc__,
                      'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'harness_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}), flush=True)
    benchmark.main()
