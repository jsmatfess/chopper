"""Tiny production integration plan only; no scale option or implicit launch."""
from pathlib import Path
import sys
from .browser_identity import BrowserIdentity
from .generate import write_new
from .plan import ROOT
from .recipe import dimensions
from .verify import require, sha256


def make_browser(directory, frozen, rows=127):
    require(type(rows) is int and 1 <= rows <= 2000, 'tiny browser rows must be 1..2000')
    require(sum(dimensions(shape, 'browser', rows)[2] for shape in ('D', 'G')) < 3 * 1024**2,
            'combined tiny fixture limit')
    root = ROOT.resolve()
    raw = Path(directory).absolute()
    require('..' not in raw.parts, 'browser plan parent traversal')
    require(all(not p.is_symlink() for p in [raw, *raw.parents]), 'browser plan symlink ancestry')
    destination = raw.resolve()
    require(destination.is_relative_to(root / 'scratch') and destination != root / 'scratch', 'browser plan must stay under scratch')
    binding = dict(root=str(root), packet=str(Path(frozen).absolute()), sha256=sha256(frozen))
    identity = BrowserIdentity(binding)
    p = identity.packet
    require(Path(p['python']['path']).resolve() == Path(sys.executable).resolve(), 'use frozen Python to prepare/run plan')
    destination.mkdir(parents=True, exist_ok=False)
    rel = lambda path: Path(path).relative_to(root).as_posix()
    policy_path = destination / 'policy.json'
    policy = dict(version=1, owned_roots=[str(destination)], volumes=[str(destination)],
                  owned_bytes=64 * 1024**2, start_free_bytes=128 * 1024**2,
                  stop_free_bytes=64 * 1024**2, deadline_seconds=600,
                  no_progress_seconds=60, sample_seconds=1, browser_frozen=binding,
                  reservation=p['reservation'], progress_paths=[str(destination / 'work/progress.json')])
    inputs = [*p['inputs'], rel(binding['packet']), rel(policy_path)]
    base = [p['python']['path'], 'scripts/scale-acceptance.py']
    steps = []
    fixture_inputs = []
    for shape in ('D', 'G'):
        data = destination / shape
        artifacts = [rel(data / name) for name in ('input.csv', 'fixture.json', 'job.json')]
        steps.append(dict(id='generate-' + shape, argv=[*base, 'prepare', str(data), '--shape', shape,
                     '--runtime', 'browser', '--rows', str(rows)], timeout_seconds=30,
                     inputs=inputs, artifacts=artifacts, depends=[steps[-1]['id']] if steps else []))
        fixture_inputs.extend(artifacts)
    work = destination / 'work'
    steps.append(dict(id='tiny-production-browser', argv=[p['node']['path'],
                 'scripts/scale_acceptance/browser-driver.mjs', binding['packet'], str(destination)],
                 timeout_seconds=480, inputs=inputs + fixture_inputs,
                 artifacts=[rel(work / 'browser-receipt.json'), rel(work / 'D'), rel(work / 'G')], depends=['generate-G']))
    for shape in ('D', 'G'):
        data = destination / shape
        steps.append(dict(id='verify-' + shape, argv=[*base, 'verify', str(data / 'job.json'),
                     str(data / 'fixture.json'), str(destination / (shape + '-verified.json')),
                     '--output', str(work / shape), '--bitmap-dir', str(destination)],
                     timeout_seconds=30, inputs=inputs + fixture_inputs + [rel(work / shape)],
                     artifacts=[rel(destination / (shape + '-verified.json'))], depends=[steps[-1]['id']]))
    write_new(policy_path, policy)
    manifest = dict(root=str(root), batch_timeout_seconds=600, estimated_seconds=300,
                    estimated_disk_bytes=64 * 1024**2, toolchains=p['toolchains'], features=[],
                    fixtures=[f'tiny browser D/G {rows} rows each; injected File/OPFS; {p["channel"]}'], steps=steps)
    write_new(destination / 'plan.json', manifest)
    return dict(plan=str(destination / 'plan.json'), policy=str(policy_path), command=[*base, 'run',
                str(destination / 'plan.json'), str(destination / 'batch'), str(policy_path)])
