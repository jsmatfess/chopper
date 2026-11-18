"""Reviewable one-shape plan. Planning never launches or supplies approval."""
from pathlib import Path
import sys
from .browser_scale_identity import ScaleIdentity, real_path
from .generate import write_new
from .plan import ROOT
from .recipe import job
from .verify import require, sha256

GiB = 1024**3
LIMITS = dict(owned_bytes=24 * GiB, start_free_bytes=40 * GiB, stop_free_bytes=8 * GiB,
              deadline_seconds=6 * 3600, no_progress_seconds=600, sample_seconds=1)


def destination_path(directory):
    raw = Path(directory).absolute()
    require('..' not in raw.parts, 'scale plan parent traversal')
    real_path(str(raw))
    require(raw.is_relative_to(ROOT.resolve() / 'scratch') and raw != ROOT.resolve() / 'scratch', 'scale attempt must stay under scratch')
    return raw


def documents(destination, binding, p, *, harness_root=None):
    root = ROOT.resolve() if harness_root is None else Path(harness_root).resolve()
    rel = lambda path: Path(path).relative_to(root).as_posix()
    shape = p['shape']
    qualifying = p['mode'] == 'qualify'
    contract = 'browser-scale-tiny-v1' if qualifying else 'browser-scale-v1'
    policy_path = destination / 'policy.json'
    data, work = destination / shape, destination / 'work'
    require(Path(p['harness']['root']).resolve() == root, 'selected harness root mismatch')
    require(Path(p['profile']) == work / 'profile', 'explicit fresh profile binding required')
    policy = dict(version=1, contract=contract, **LIMITS, owned_roots=[str(destination)],
                  volumes=[str(destination)], scale_frozen=binding, reservation=p['reservation'],
                  progress_paths=[str(work / 'progress.jsonl'), *[str(destination / 'batch' / f'{i}-stdout.log') for i in (1, 3)]])
    base = [p['python']['path'], '-B', 'scripts/scale-acceptance.py']
    inputs = [*p['harness']['inputs'], rel(binding['packet']), rel(policy_path)]
    borrowed = p.get('borrowed_input')
    source = Path(borrowed['path']) if borrowed else data/'input.csv'
    fixtures = [rel(data / name) for name in (('fixture.json', 'job.json') if borrowed else ('input.csv', 'fixture.json', 'job.json'))]
    # ScaleIdentity pins any absolute borrowed input outside the runner root.
    steps = [dict(id='generate', argv=[*base, 'prepare', str(data), '--shape', shape, '--runtime', 'browser'],
                  timeout_seconds=1800, inputs=inputs, artifacts=fixtures, depends=[]),
             dict(id='browser-scale', argv=[p['node']['path'], 'scripts/scale_acceptance/browser-scale-driver.mjs',
                  binding['packet'], str(destination)], timeout_seconds=5400, inputs=inputs + fixtures,
                  artifacts=[rel(work / 'browser-receipt.json'), rel(work / shape)], depends=['generate'])]
    if qualifying:
        steps[0]['argv'] += ['--rows', str(p['fixture']['rows'])]
    if borrowed:
        steps[0]['argv'] += ['--borrowed-packet', binding['packet'], '--borrowed-packet-sha256', binding['sha256']]
    verify = [*base, 'verify', str(data / 'job.json'), str(data / 'fixture.json'), str(destination / 'verified.json'),
              '--output', str(work / shape), '--bitmap-dir', str(destination)]
    if p.get('peer'):
        verify += ['--peer', p['peer']['path']]
    steps.append(dict(id='verify', argv=verify, timeout_seconds=1800, inputs=inputs + fixtures + [rel(work / shape)],
                      artifacts=[rel(destination / 'verified.json')], depends=['browser-scale']))
    manifest = dict(root=str(root), contract=contract, plan_id=p['plan_id'], shape=shape,
                    channel=p['channel'], job=job(shape, 'browser', source, data / 'output', data / 'temp'), batch_timeout_seconds=21600, estimated_seconds=9000,
                    estimated_disk_bytes=24 * GiB, toolchains=p['toolchains'], features=[],
                    fixtures=[p['fixture']], steps=steps)
    return manifest, policy


def make_scale(directory, frozen):
    destination = destination_path(directory)
    binding = dict(packet=str(real_path(str(Path(frozen).absolute()))), sha256=sha256(frozen))
    require(Path(binding['packet']).is_relative_to(ROOT.resolve()), 'packet must stay under harness root')
    identity = ScaleIdentity(binding)
    require(Path(identity.packet['python']['path']).resolve() == Path(sys.executable).resolve(), 'use frozen Python')
    manifest, policy = documents(destination, binding, identity.packet)
    destination.mkdir(parents=True, exist_ok=False)
    write_new(destination / 'plan.json', manifest)
    write_new(destination / 'policy.json', policy)
    return dict(status='planned; parent approval still required', plan=str(destination / 'plan.json'),
                plan_sha256=sha256(destination / 'plan.json'), policy_sha256=sha256(destination / 'policy.json'),
                packet_sha256=binding['sha256'], execution='browser-scale-run requires a separate parent-approved record')
