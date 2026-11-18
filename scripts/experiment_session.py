"""Session policy only; subprocesses and provenance remain in validation-runner."""
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import time
from experiment_decisions import provide, validate as decision
import experiment_codex

spec = importlib.util.spec_from_file_location('cycle', Path(__file__).with_name('experiment-cycle.py'))
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)
write = cycle.runner.write_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('invalid object fields: ' + ', '.join(required))


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'integer required in [{minimum}, {maximum}]')


def text(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
        raise ValueError('bounded nonempty text required')


def owned(root, path):
    path = Path(path).resolve()
    if path == root or root not in path.parents:
        raise ValueError('output outside owned session: ' + str(path))
    return path


def relative(value):
    if not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts or any(c in value for c in '*?[]'):
        raise ValueError('explicit relative paths required; no globs or traversal')
    return value


def storage(root):
    total = 0
    def fail(error):
        raise error
    for folder, dirs, files in os.walk(root, onerror=fail):
        for name in dirs + files:
            path = Path(folder) / name
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('session links unsupported')
            if path.is_file():
                total += path.stat().st_size
    return total


@contextlib.contextmanager
def ownership(directory):
    # OS lock releases on crash; the persistent file is not a stale PID lock.
    with (directory / 'controller.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def freeze(config, directory):
    fields(config, ('schema_version', 'root', 'provider', 'batches', 'first'),
           ('seconds', 'storage_bytes', 'max_batches', 'max_runs', 'max_decisions', 'decisions', 'codex'))
    if type(config['schema_version']) is not int or config['schema_version'] != 1 or config['provider'] not in ('predeclared', 'file', 'codex'):
        raise ValueError('unsupported schema/provider')
    if config['provider'] == 'codex':
        fields(config.get('codex'), ('executable', 'model', 'reasoning_effort', 'timeout_seconds'), ('escalation_reason',))
        settings = config['codex']
        if not Path(settings['executable']).is_absolute() or not Path(settings['executable']).is_file():
            raise ValueError('explicit installed Codex executable required')
        text(settings['model'])
        if settings['reasoning_effort'] not in ('medium', 'high', 'xhigh'):
            raise ValueError('explicit medium/high/xhigh effort required')
        if settings['reasoning_effort'] == 'xhigh':
            text(settings.get('escalation_reason'))
        integer(settings['timeout_seconds'], 1, 120)
    elif 'codex' in config:
        raise ValueError('Codex settings require the explicit codex provider')
    root = Path(config['root']).resolve()
    owned(root, directory)
    for name, default, maximum in (('seconds', 7200, 7200), ('storage_bytes', 20 * 1024**3, 20 * 1024**3),
                                   ('max_batches', 8, 12), ('max_runs', 32, 48), ('max_decisions', 8, 12)):
        integer(config.get(name, default), 1, maximum)
    if not isinstance(config['batches'], list) or not 1 <= len(config['batches']) <= 12:
        raise ValueError('one to twelve approved batches required')
    ids, sources, outputs, frozen = set(), {}, [], []
    for batch in config['batches']:
        fields(batch, ('id', 'kind', 'parent', 'plan', 'outputs', 'metrics', 'storage_reserve_bytes'))
        name = batch['id']
        text(name)
        if len(name) > 80 or not name.replace('-', '').isalnum() or name in ids:
            raise ValueError('unique simple batch IDs required')
        if batch['kind'] not in ('initial', 'repeat', 'refine', 'challenger') or batch['parent'] not in ids | {None}:
            raise ValueError('invalid approved transition')
        ids.add(name)
        path = Path(batch['plan']).resolve()
        plan = cycle.load_plan(path)
        if Path(plan['root']).resolve() != root or plan['experiment']['cohort'] != 'development':
            raise ValueError('native development plans in one root only')
        if not 1 <= len(plan['steps']) <= 32 or not 0 < plan['batch_timeout_seconds'] <= 120:
            raise ValueError('batch must fit two-minute control bound and 32 steps')
        measures = [s for s in plan['steps'] if s['phase'] == 'measure']
        if not 1 <= len(measures) <= 6:
            raise ValueError('one to six measured runs per batch required')
        ancestors = {}
        verified = set()
        for step in plan['steps']:
            deps = step.get('depends', [])
            if step['id'] in ancestors or any(dep not in ancestors for dep in deps):
                raise ValueError('unique steps with preceding dependencies required')
            ancestors[step['id']] = set(deps).union(*(ancestors[d] for d in deps))
            if step['phase'] == 'verify':
                verified.update(ancestors[step['id']])
        if any(step['id'] not in verified for step in measures):
            raise ValueError('every measurement needs a dependent verifier')
        for key in ('fixtures', 'toolchains', 'estimated_seconds', 'estimated_disk_bytes'):
            if not plan.get(key):
                raise ValueError('explicit fixtures, resources and costs required')
        integer(batch['storage_reserve_bytes'], 1, 20 * 1024**3)
        if not isinstance(batch['outputs'], list) or not batch['outputs']:
            raise ValueError('explicit output roots required')
        roots = [owned(directory, root / relative(p)) for p in batch['outputs']]
        for output in roots:
            if any(output == old or output in old.parents or old in output.parents for old in outputs):
                raise ValueError('batch outputs must be disjoint')
            outputs.append(output)
        for step in plan['steps']:
            if not 0 < step['timeout_seconds'] <= 120 or not step['inputs']:
                raise ValueError('bounded steps with declared inputs required')
            for pattern in step.get('artifacts', []):
                artifact = owned(directory, root / relative(pattern))
                if not any(artifact == p or p in artifact.parents for p in roots):
                    raise ValueError('artifact does not match batch output roots')
            for pattern in step['inputs']:
                relative(pattern)
                candidate = (root / pattern).resolve()
                if not any(candidate == p or p in candidate.parents for p in outputs):
                    ident = cycle.runner.identity(root, [pattern])
                    if cycle.runner.incomplete_identity(ident):
                        raise ValueError('missing source input: ' + pattern)
                    sources.update(ident)
            argv = step['argv']
            if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
                raise ValueError('explicit string command arrays required')
            if any('browser' in str(arg).lower() for arg in argv[:2]):
                raise ValueError('browser controller adaptation is deferred')
            if 'run-native' in argv:
                if argv.index('run-native') + 2 >= len(argv) or '--record' not in argv or argv.index('--record') + 1 >= len(argv):
                    raise ValueError('native command requires executable, Job and record')
                job_path = Path(argv[argv.index('run-native') + 2])
                job = read(job_path)
                for destination in (job['output'], job['resources']['temp_dir'], argv[argv.index('--record') + 1]):
                    destination = owned(directory, root / destination)
                    if not any(destination == p or p in destination.parents for p in roots):
                        raise ValueError('native Job output/temp/record path mismatch')
                if (job.get('operations') != [
                        {'type': 'partition', 'columns': ['region']},
                        {'type': 'assign_probabilistic', 'groups': [
                            {'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}], 'strata': []},
                        {'type': 'shuffle', 'strategy': 'uniform'}]
                        or job.get('full_shuffle_policy') != 'seeded_v1'
                        or job['resources'].get('grouping') not in ('auto', 'sort')):
                    raise ValueError('only current seeded auto/sort complete campaign jobs supported')
                for source in (job_path, Path(job['input']), Path(argv[argv.index('run-native') + 1])):
                    pattern = str(source.resolve().relative_to(root))
                    ident = cycle.runner.identity(root, [pattern])
                    if cycle.runner.incomplete_identity(ident):
                        raise ValueError('missing native input')
                    sources.update(ident)
        sources.update(cycle.runner.identity(root, [str(path.relative_to(root))]))
        if not isinstance(batch['metrics'], list) or not 1 <= len(batch['metrics']) <= 6:
            raise ValueError('one to six harness metric descriptors required')
        seen_metrics = set()
        for metric in batch['metrics']:
            fields(metric, ('path', 'pointer', 'unit', 'scope', 'cell'))
            for value in metric.values():
                text(value)
            observation = (metric['path'], metric['pointer'])
            if observation in seen_metrics:
                raise ValueError('duplicate metric observation')
            seen_metrics.add(observation)
            metric_path = owned(directory, root / relative(metric['path']))
            if not any(metric_path == p or p in metric_path.parents for p in roots):
                raise ValueError('metric outside declared outputs')
            artifacts = [root / p for step in plan['steps'] for p in step.get('artifacts', [])]
            if not any(metric_path == p or p in metric_path.parents for p in artifacts):
                raise ValueError('metric must be a retained runner artifact')
            if not metric['pointer'].startswith('/'):
                raise ValueError('JSON pointer required')
        frozen.append({'batch': batch, 'plan': plan, 'runs': len(measures)})
    if config['first'] not in ids:
        raise ValueError('unknown first batch')
    first = next(b['batch'] for b in frozen if b['batch']['id'] == config['first'])
    if first['kind'] != 'initial' or first['parent'] is not None:
        raise ValueError('first batch must be initial without parent')
    for entry in frozen:
        repeats, node = 0, entry['batch']
        while node['parent'] is not None:
            repeats += node['kind'] == 'repeat'
            node = next(b['batch'] for b in frozen if b['batch']['id'] == node['parent'])
        if repeats > 2:
            raise ValueError('at most three batches in a repeat lineage')
    choices = config.get('decisions', [])
    if not isinstance(choices, list) or len(choices) > config.get('max_decisions', 8):
        raise ValueError('too many predeclared decisions')
    for item in choices:
        decision(item)
    drivers = {**cycle.driver_identity(), **{p.name: cycle.runner.digest(p) for p in
                        (Path(__file__), Path(__file__).with_name('experiment-controller.py'),
                         Path(__file__).with_name('experiment_decisions.py'),
                         Path(__file__).with_name('experiment_codex.py'),
                         Path(__file__).with_name('experiment-decision.schema.json'),
                         Path(__file__).with_name('experiment-packet.schema.json'))}}
    if config['provider'] == 'codex':
        drivers['codex_executable'] = cycle.runner.digest(Path(config['codex']['executable']))
    return {'config': config, 'batches': frozen, 'sources': sources, 'drivers': drivers}


def metrics(batch, root):
    groups, pointers = {}, []
    for descriptor in batch['metrics']:
        path = root / descriptor['path']
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('metric document exceeds 1 MiB')
        value = read(path)
        for part in descriptor['pointer'].split('/')[1:]:
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('metric must be finite nonnegative number')
        key = (descriptor['cell'], descriptor['unit'], descriptor['scope'])
        groups.setdefault(key, []).append(value)
        pointers.append({**descriptor, 'sha256': cycle.runner.digest(path), 'value': value})
    return {'samples': pointers, 'summaries': [
        {'cell': k[0], 'unit': k[1], 'scope': k[2], 'n': len(v), 'median': statistics.median(v),
         'min': min(v), 'max': max(v)} for k, v in groups.items()]}


def classify(batch_dir, plan):
    state = read(batch_dir / 'status.json')
    latest = {a['id']: a for a in state['attempts']}
    for step in plan['steps']:
        attempt = latest.get(step['id'])
        if attempt and attempt['status'] == 'invalidated':
            return 'source-or-artifact-invalidated'
        if attempt and attempt['status'] != 'passed':
            return ('correctness-failure' if step['phase'] == 'verify' and attempt.get('exit_code') is not None
                    and attempt['status'] == 'failed' and not attempt.get('error') else 'infrastructure-failure')
    return 'verified' if state['summary']['incomplete'] == 0 else 'infrastructure-failure'


def execute(config_path, directory, decision_path=None):
    directory.mkdir(parents=True, exist_ok=True)
    with ownership(directory):
        manifest_path = directory / 'session.json'
        status_path = directory / 'controller-status.json'
        config = read(config_path) if config_path else read(manifest_path)['config']
        # Charge initial freezing, setup failures and any subsequent downtime too.
        # Persist this before expensive identity work or creating the manifest.
        if not status_path.exists():
            write(status_path, {
                'schema_version': 1, 'started_unix': time.time(), 'status': 'running', 'next': config.get('first'),
                'events': [], 'launched': [], 'runs': 0, 'decisions': [], 'artifacts': {}, 'inconclusive': 0})
        try:
            current = freeze(config, directory)
        except (ValueError, OSError, KeyError, TypeError):
            if status_path.exists():
                state = read(status_path)
                state['status'] = 'source-or-artifact-invalidated'
                state['events'].append({'kind': 'manifest-revalidation-failed', 'unix': time.time()})
                write(status_path, state)
            raise
        if manifest_path.exists():
            if read(manifest_path) != current:
                if status_path.exists():
                    state = read(status_path)
                    state['status'] = 'source-or-artifact-invalidated'
                    state['events'].append({'kind': 'source-invalidation', 'unix': time.time()})
                    write(status_path, state)
                raise ValueError('frozen configuration/source/driver invalidated')
        else:
            if any((Path(config['root']) / p).exists() for b in config['batches'] for p in b['outputs']):
                raise ValueError('fresh output roots required; preserve existing evidence')
            if any(directory.glob('batch-*')) or any(directory.glob('packet-*.json')):
                raise ValueError('existing controller evidence requires original session manifest')
            write(manifest_path, current)
        state = read(status_path)
        root = Path(config['root']).resolve()

        def save(kind, **data):
            state['events'].append({'kind': kind, 'unix': time.time(), **data})
            state['elapsed_seconds'] = time.time() - state['started_unix']
            state['stored_bytes'] = storage(directory)
            state['peak_observed_bytes'] = max(state.get('peak_observed_bytes', 0), state['stored_bytes'])
            write(status_path, state)

        def guard():
            elapsed = time.time() - state['started_unix']
            used = storage(directory)
            state['storage_checks'] = state.get('storage_checks', 0) + 1
            state['peak_observed_bytes'] = max(state.get('peak_observed_bytes', 0), used)
            reason = None
            if elapsed < state.get('elapsed_seconds', 0) or elapsed >= config.get('seconds', 7200):
                reason = 'time-budget'
            elif (directory / 'STOP').exists():
                reason = 'stop-request'
            elif used >= config.get('storage_bytes', 20 * 1024**3):
                reason = 'storage-budget'
            if reason:
                state['status'] = reason
                raise OSError(reason)

        if (state['status'] in ('running', 'decision-needed') and state['events']
                and state['events'][-1]['kind'] in ('launch', 'provider-request')):
            state['status'] = 'interrupted-review-required'
            save('crash-recovery', note='No relaunch; inspect retained runner status and owned processes.')
        if state['artifacts'] and cycle.runner.identity(root, list(state['artifacts'])) != state['artifacts']:
            state['status'] = 'source-or-artifact-invalidated'
            save('artifact-invalidation')
        try:
            guard()
            if decision_path is not None and config['provider'] != 'file':
                raise ValueError('decision files require a session frozen with provider file')
            while state['status'] in ('running', 'decision-needed'):
                guard()
                if state['status'] == 'decision-needed':
                    packet_path = directory / state['packet']
                    digest = cycle.runner.digest(packet_path)
                    if digest != state['packet_sha256']:
                        raise ValueError('decision packet invalidated')
                    index = len(state['decisions'])
                    if index >= config.get('max_decisions', 8):
                        state['status'] = 'decision-budget'
                        break
                    provider_metadata = None
                    if config['provider'] == 'codex' and decision_path is None:
                        if config['codex']['timeout_seconds'] > config.get('seconds', 7200) - (time.time() - state['started_unix']):
                            state['status'] = 'time-admission'
                            break
                        request = directory / f'provider-{index+1:02}'
                        save('provider-request', directory=str(request), supplied_settings=config['codex'])
                        choice, provider_metadata = experiment_codex.run(config['codex'], packet_path, request, cycle.runner, guard)
                        guard()
                        state['artifacts'].update(cycle.runner.identity(root, [str(request.relative_to(root))]))
                    else:
                        choice = provide(config, index, digest, decision_path)
                    decision_path = None
                    if choice is None:
                        break
                    signature = {k: choice[k] for k in ('action', 'target', 'assessment')}
                    if signature in [d['signature'] for d in state['decisions']]:
                        raise ValueError('repeated identical decision')
                    target = next((b for b in current['batches'] if b['batch']['id'] == choice['target']), None)
                    if choice['action'] != 'stop' and (target is None or target['batch']['kind'] != choice['action']
                            or target['batch']['parent'] != state['launched'][-1] or choice['target'] in state['launched']):
                        raise ValueError('out-of-scope decision')
                    state['decisions'].append({'signature': signature, 'decision': choice, 'packet_sha256': digest,
                                               'provider': config['provider'], 'model_settings': provider_metadata,
                                               'usage': provider_metadata.get('usage') if provider_metadata else None})
                    state['inconclusive'] = state['inconclusive'] + 1 if choice['assessment'] == 'inconclusive' else 0
                    state['status'] = ('stopped' if choice['action'] == 'stop' else
                                       'scientific-rejection' if choice['assessment'] == 'rejected' else
                                       'diminishing-value' if state['inconclusive'] >= 2 else 'running')
                    state['next'] = choice['target']
                    save('decision')
                    if state['status'] != 'running':
                        break
                selected = next(b for b in current['batches'] if b['batch']['id'] == state['next'])
                batch, plan = selected['batch'], selected['plan']
                if (len(state['launched']) >= config.get('max_batches', 8)
                        or state['runs'] + selected['runs'] > config.get('max_runs', 32)):
                    state['status'] = 'run-or-batch-budget'
                    break
                if plan['batch_timeout_seconds'] > config.get('seconds', 7200) - (time.time() - state['started_unix']):
                    state['status'] = 'time-admission'
                    break
                reserve = batch['storage_reserve_bytes']
                if (storage(directory) + reserve > config.get('storage_bytes', 20 * 1024**3)
                        or shutil.disk_usage(directory).free < reserve):
                    state['status'] = 'storage-admission'
                    break
                if freeze(config, directory) != current:
                    raise ValueError('source invalidated before batch')
                guard()
                if plan['batch_timeout_seconds'] > config.get('seconds', 7200) - (time.time() - state['started_unix']):
                    state['status'] = 'time-admission'
                    break
                state['launched'].append(batch['id'])
                state['runs'] += selected['runs']
                save('launch', batch=batch['id'], storage_reserve_bytes=reserve)
                batch_dir = directory / ('batch-' + batch['id'])
                cycle.run(Path(batch['plan']).resolve(), batch_dir, guard=guard)
                guard()
                outcome = classify(batch_dir, plan)
                if state['status'] != 'running':
                    save('guard-stopped', outcome=outcome)
                    break
                if outcome != 'verified':
                    state['status'] = outcome
                    save(outcome, failure_packet=str(batch_dir / 'decision-packet.json'))
                    break
                measurements = metrics(batch, root)
                patterns = [p for step in plan['steps'] for p in step.get('artifacts', [])]
                state['artifacts'].update(cycle.runner.identity(root, patterns))
                packet_name = f'packet-{len(state["launched"]):02}.json'
                packet = {'schema_version': 1, 'batch': batch['id'], 'experiment': {
                              k: plan['experiment'][k] for k in ('question', 'hypothesis', 'decision_rule', 'stop_rule', 'cohort')},
                          'outcome': 'verified', 'metrics': measurements, 'failures': [],
                          'resources': {'elapsed_session_seconds': time.time() - state['started_unix'],
                                        'stored_bytes': storage(directory), 'rss_bytes': None,
                                        'peak_observed_bytes': state['peak_observed_bytes'],
                                        'storage_scope': 'owned tree sampled; not physical I/O or RSS'},
                          'evidence': {'manifest': str(batch_dir / 'manifest.json'),
                                       'manifest_sha256': cycle.runner.digest(batch_dir / 'manifest.json'),
                                       'status': str(batch_dir / 'status.json'),
                                       'status_sha256': cycle.runner.digest(batch_dir / 'status.json')},
                          'allowed_targets': [{'target': b['id'], 'action': b['kind']} for b in config['batches'] if b['parent'] == batch['id']],
                          'decision_needed': 'stop, repeat, refine or approved challenger; no engine/default changes',
                          'resume_command': f'"{sys.executable}" "{Path(__file__).with_name("experiment-controller.py").resolve()}" run "{directory}" --decision DECISION.json',
                          'model_settings': None, 'usage': None}
                for value in (*packet['evidence'].values(), packet['resume_command']):
                    text(value)
                if len((json.dumps(packet, indent=2) + '\n').encode('utf-8')) > 32768:
                    raise ValueError('decision packet exceeds 32 KiB; narrow descriptors')
                write(directory / packet_name, packet)
                state['packet'] = packet_name
                state['packet_sha256'] = cycle.runner.digest(directory / packet_name)
                state['status'] = 'decision-needed'
                save('verified', packet=packet_name)
        except (ValueError, KeyError, TypeError) as error:
            state['status'] = 'invalid-decision-or-manifest'
            save('rejected', error=str(error)[:500])
        except OSError as error:
            if state['status'] in ('running', 'decision-needed'):
                state['status'] = 'infrastructure-failure'
            save('stopped', error=str(error)[:500])
        save('checkpoint')
        print(json.dumps({k: state[k] for k in ('status', 'elapsed_seconds', 'stored_bytes', 'runs')}, indent=2))
        return 0 if state['status'] in ('stopped', 'decision-needed') else 1
