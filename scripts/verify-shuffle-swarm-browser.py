#!/usr/bin/env python3
"""JSON stdin bridge to the read-only native recipe generator/verifier/provenance."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('swarm_native', ROOT / 'scripts/bench-shuffle-swarm.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
v = native.verify
CSV = dict(encoding='utf-8', headers=True, delimiter=',', quote='"', escape=None,
           line_ending='lf', bom=False, skip_empty_lines=False)


def config(recipe):
    job = native.make_job(recipe, Path('input.csv'), Path('results'))
    job['resources'].update(temp_dir=None, temp_bytes=None, max_files=100000, grouping='auto')
    job['limits'] = dict(dict(rows=None, bytes=None, compressed_bytes=None), **job['limits'])
    # Default RNG/algorithm fields are omitted by canonical Job serialization.
    job.update(input_csv=CSV, output_csv=CSV, compression='none', zip_member=None)
    return job


def verify(request):
    recipe = v.recipes()[request['recipe']]
    result = request['result']
    submitted = result['submitted']
    wanted = config(recipe)
    v.require(v.matches_config(submitted, wanted), 'submitted recipe/seed/settings/resources/caps mismatch')
    directory = Path(request['directory'])
    records = [json.loads(line) for line in (directory / 'manifest.jsonl').read_text().splitlines()]
    canonical = records[0]['config']
    # Assert submitted semantics independently BEFORE accepting canonical WASI paths.
    meaningful = copy.deepcopy(submitted)
    for key in ('input', 'output'):
        meaningful.pop(key)
    meaningful['resources'].pop('temp_dir')
    v.require(v.matches_config(canonical, meaningful), 'canonical/submitted semantics mismatch')
    v.require(canonical['input'] == '/input.csv' and canonical['output'] == '/results'
              and canonical['resources']['temp_dir'] == '/tmp', 'unexpected WASI path mapping')
    analysis = copy.deepcopy(result['analysis'])
    v.require(analysis['seed'] == wanted['seed'], 'Analysis seed mismatch')
    warning = ('Browser export is not atomic. A valid CHOPPER-COMPLETE.json record marks '
               'successful completion. Keep this tab open until saving finishes.')
    v.require(analysis['warnings'][-1:] == [warning], 'missing browser-only warning')
    analysis['warnings'].pop()  # UI adds this after receiving the immutable engine Analysis.
    marker_path = directory.parent / 'CHOPPER-COMPLETE.json'
    marker = json.loads(marker_path.read_text())
    v.require(marker == dict(complete=True, files=len(records), engine='chopper-browser', version=1),
              'invalid completion marker')
    receipt = v.verify(directory, recipe, canonical, analysis)
    actual = sum(p.stat().st_size for p in directory.iterdir()) + marker_path.stat().st_size
    storage = result['diagnostics']['storage']
    v.require(actual == result['export_bytes'] == storage['profiled_destination_bytes'], 'export byte mismatch')
    v.require(storage['workspace_bytes_after_cleanup'] == 0 and storage['peak_open_handles'] <= 64,
              'storage cleanup/handle limits mismatch')
    receipt.update(marker_sha256=v.sha(marker_path), marker_bytes=marker_path.stat().st_size,
                   actual_export_bytes=actual, submitted_semantics_verified=True,
                   browser_verifier_sha256=v.sha(__file__))
    return receipt


def self_test():
    import tempfile
    test_spec = importlib.util.spec_from_file_location('swarm_controls', ROOT / 'scripts/test-shuffle-swarm.py')
    controls = importlib.util.module_from_spec(test_spec)
    test_spec.loader.exec_module(controls)
    with tempfile.TemporaryDirectory(prefix='chopper-browser-adapter-selfcheck-') as temporary:
        parent = Path(temporary)
        directory = parent / 'verification-output'
        directory.mkdir()
        recipe, _, analysis, records = controls.Controls().sample(directory)
        submitted = config(recipe)
        canonical = copy.deepcopy(submitted)
        canonical.update(input='/input.csv', output='/results')
        canonical['resources']['temp_dir'] = '/tmp'
        analysis['warnings'] = []
        analysis['seed'] = submitted['seed']
        records[0].update(config=canonical, analysis=copy.deepcopy(analysis))
        (directory / 'manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
        marker = parent / 'CHOPPER-COMPLETE.json'
        marker.write_text(json.dumps(dict(complete=True, files=len(records), engine='chopper-browser', version=1)))
        total = sum(p.stat().st_size for p in directory.iterdir()) + marker.stat().st_size
        analysis['warnings'].append('Browser export is not atomic. A valid CHOPPER-COMPLETE.json record marks successful completion. Keep this tab open until saving finishes.')
        result = dict(submitted=submitted, analysis=analysis, export_bytes=total,
                      diagnostics=dict(storage=dict(profiled_destination_bytes=total,
                                       workspace_bytes_after_cleanup=0, peak_open_handles=2)))
        original = v.recipes
        v.recipes = lambda: {recipe['name']: recipe}
        request = dict(recipe=recipe['name'], result=result, directory=str(directory))
        try:
            v.require(verify(request)['verified'], 'valid synthetic browser export rejected')
            for mutate in ('seed', 'accounting', 'cleanup', 'marker', 'csv'):
                bad = copy.deepcopy(request)
                if mutate == 'seed':
                    bad['result']['submitted']['seed'] = 'wrong'
                elif mutate == 'accounting':
                    bad['result']['export_bytes'] += 1
                elif mutate == 'cleanup':
                    bad['result']['diagnostics']['storage']['workspace_bytes_after_cleanup'] = 1
                elif mutate == 'marker':
                    marker.write_text('{}')
                else:
                    csv = directory / records[1]['path']
                    csv.write_text(csv.read_text().replace('0,0,', '9,9,', 1))
                try:
                    verify(bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError('tampered ' + mutate + ' accepted')
                if mutate == 'marker':
                    marker.write_text(json.dumps(dict(complete=True, files=len(records), engine='chopper-browser', version=1)))
        finally:
            v.recipes = original
    print('browser bridge synthetic controls passed: valid quoted/multiline fields, seed, accounting, cleanup, marker, CSV rejection')


def main():
    request = json.load(sys.stdin)
    action = request['action']
    if action == 'recipes':
        result = v.recipes()
    elif action == 'fixture':
        recipe = v.recipes()[request['recipe']]
        path = Path(request['path'])
        v.fixture(path, recipe)
        result = dict(recipe=recipe, config=config(recipe), sha256=v.sha(path), bytes=path.stat().st_size)
    elif action == 'provenance':
        result = native.provenance(Path(request['wasm']).resolve(strict=True),
                                  Path(request['manifest']), Path(request['target']), request['candidate'])
    elif action == 'verify':
        result = verify(request)
    else:
        raise ValueError('unknown action')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        self_test()
    else:
        main()
