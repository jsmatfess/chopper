"""Concrete self-check and frozen native shape manifests; never starts execution."""
import platform
from pathlib import Path
import sys
from .generate import write_new
from .verify import require, sha256
from .guard import FrozenIdentity

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ['scripts/scale-acceptance.py', 'scripts/scale_acceptance/*.py', 'scripts/scale_acceptance/*.mjs',
           'scripts/scale_acceptance/README.md',
           'scripts/test-scale-acceptance.py', 'scripts/test-scale-acceptance-browser.mjs',
           'scripts/validation-runner.py']


def make(directory, shape=None, frozen=None):
    source_root = ROOT.resolve()
    raw = Path(directory).absolute()
    require('..' not in raw.parts, 'plan path must not contain parent traversal')
    scratch = source_root / 'scratch'
    require(not scratch.is_symlink(), 'scratch root must not be a symlink')
    directory = raw.resolve()
    require(directory != scratch and directory.is_relative_to(scratch),
            'plan must be under repository scratch/')
    for ancestor in [raw, *raw.parents]:
        if ancestor == source_root:
            break
        require(not ancestor.is_symlink(), 'plan ancestry must not contain symlinks')
    directory.mkdir(parents=True, exist_ok=False)
    relative = lambda path: str(Path(path).relative_to(source_root))
    policy_path = directory / 'policy.json'
    plan_path = directory / 'plan.json'
    policy = dict(version=1, owned_roots=[str(directory)], volumes=[str(directory)],
                  owned_bytes=64 * 1024**2, start_free_bytes=128 * 1024**2,
                  stop_free_bytes=64 * 1024**2, deadline_seconds=600,
                  no_progress_seconds=600, sample_seconds=1,
                  progress_paths=[str(directory / 'batch/1-stdout.log'), str(directory / 'batch/2-stdout.log')])
    inputs = SOURCES + [relative(policy_path)]
    python = str(Path(sys.executable).resolve())
    steps = [dict(id='oracle-controls', argv=[python, 'scripts/test-scale-acceptance.py',
                                             '--receipt', str(directory / 'python-check.json'), '--work-root', str(directory)],
                  timeout_seconds=480, inputs=inputs,
                  artifacts=[relative(directory / 'python-check.json')], depends=[]),
             dict(id='browser-extraction-controls', argv=['node', 'scripts/test-scale-acceptance-browser.mjs',
                                                          str(directory / 'browser-check.json'), str(directory)],
                  timeout_seconds=60, inputs=inputs,
                  artifacts=[relative(directory / 'browser-check.json')], depends=['oracle-controls'])]
    if shape:
        require(shape in ('D', 'G') and frozen is not None, 'frozen packet required for native scale plan')
        binding = dict(root=str(source_root), packet=str(Path(frozen).resolve()), sha256=sha256(frozen))
        identity = FrozenIdentity(binding)
        freeze, executable = identity.packet, identity.executable
        require(freeze['reservation']['sha256'] == sha256(freeze['reservation']['path']), 'host reservation mismatch')
        inputs += [relative(Path(frozen).resolve()), *freeze['inputs'], relative(executable)]
        policy.update(owned_bytes=160 * 1024**3, start_free_bytes=200 * 1024**3,
                      stop_free_bytes=20 * 1024**3, deadline_seconds=8 * 3600,
                      frozen=binding, reservation=freeze['reservation'], volumes=freeze['storage']['volumes'],
                      progress_paths=[str(directory / f'batch/{i}-stdout.log') for i in range(1, 4)] +
                                     [str(directory / f'batch/{i}-stderr.log') for i in range(1, 4)] +
                                     [str(directory / 'data/output/manifest.jsonl')])
        data = directory / 'data'
        base = [python, 'scripts/scale-acceptance.py']
        artifacts = [relative(data / name) for name in ('input.csv', 'fixture.json', 'job.json')]
        steps = [dict(id='generate-' + shape, argv=[*base, 'prepare', str(data), '--shape', shape, '--runtime', 'native'],
                      timeout_seconds=3600, inputs=inputs, artifacts=artifacts, depends=[]),
                 dict(id='run-' + shape, argv=[str(executable), 'run', '--config', str(data / 'job.json'), '--yes'],
                      timeout_seconds=7200, inputs=inputs + artifacts,
                      artifacts=[relative(data / 'output')], depends=['generate-' + shape]),
                 dict(id='verify-' + shape, argv=[*base, 'verify', str(data / 'job.json'), str(data / 'fixture.json'),
                                                 str(directory / 'verified.json'), '--bitmap-dir', str(directory)],
                      timeout_seconds=3600, inputs=inputs + artifacts + [relative(data / 'output')],
                      artifacts=[relative(directory / 'verified.json')], depends=['run-' + shape])]
    write_new(policy_path, policy)
    manifest = dict(root=str(source_root), batch_timeout_seconds=policy['deadline_seconds'],
                    estimated_seconds=6 * 3600 if shape else 300,
                    estimated_disk_bytes=policy['owned_bytes'],
                    toolchains=freeze['toolchains'] if shape else dict(python=sys.version, executable=python,
                                                                      platform=platform.platform(), node='resolved and hashed by runner'),
                    features=[], fixtures=[f'{shape} release-acceptance-v1 native'] if shape else ['tiny synthetic oracle controls'],
                    steps=steps)
    write_new(plan_path, manifest)
    return dict(plan=str(plan_path), policy=str(policy_path),
                command=[python, 'scripts/scale-acceptance.py', 'run', str(plan_path), str(directory / 'batch'), str(policy_path)])
