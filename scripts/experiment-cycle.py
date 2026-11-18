"""Run declared experiment steps without model calls; emit a compact handoff packet."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


RUNNER_PATH = Path(__file__).with_name('validation-runner.py')
spec = importlib.util.spec_from_file_location('validation_runner', RUNNER_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

# Recommendations, not hidden model calls or automatic changes to T3 settings.
POLICY = {
    'design': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'high'},
    'implement': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'high'},
    'routine_harness_change': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'medium'},
    'execute': {'executor': 'code'},
    'summarize': {'executor': 'code'},
    'diagnose': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'medium'},
    'interpret': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'high'},
    'escalate': {'executor': 'gpt-6.1-sol', 'reasoningEffort': 'xhigh'},
}


def load_plan(path):
    plan = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    experiment = plan.get('experiment', {})
    if not isinstance(experiment, dict):
        raise ValueError('experiment must be an object')
    for field in ('question', 'hypothesis', 'decision_rule', 'stop_rule'):
        value = experiment.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError(f'experiment.{field} must be nonempty text of at most 2000 characters')
    if experiment.get('cohort') not in ('development', 'held-out'):
        raise ValueError('experiment.cohort must be development or held-out')
    if experiment['cohort'] == 'held-out':
        for field in ('frozen_rules', 'predictions'):
            if not isinstance(experiment.get(field), str) or not experiment[field].strip():
                raise ValueError(f'held-out experiment requires {field} before execution')
    phases = {step.get('phase') for step in plan['steps']}
    if not phases <= {'prepare', 'measure', 'verify', 'summarize'}:
        raise ValueError('every step needs phase prepare, measure, verify or summarize')
    if not {'measure', 'verify'} <= phases:
        raise ValueError('experiment requires measurement and verification steps')
    return plan


def driver_identity():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), RUNNER_PATH)}


def packet(directory, limit=12):
    """Read metadata only. Never inject raw logs or infer benchmark statistics."""
    plan_path = directory / 'manifest.json'
    plan = load_plan(plan_path)
    state = json.loads((directory / 'status.json').read_text(encoding='utf-8'))
    latest = {attempt['id']: attempt for attempt in state['attempts']}
    complete = (state['summary']['incomplete'] == 0
                and all(latest.get(step['id'], {}).get('status') == 'passed'
                        for step in plan['steps']))
    failed = [step for step in plan['steps']
              if latest.get(step['id'], {}).get('status', 'pending') != 'passed']
    ordered = failed + [step for step in plan['steps'] if step not in failed]
    steps = []
    for step in ordered[:limit]:
        attempt = latest.get(step['id'], {})
        number = attempt.get('attempt')
        steps.append({
            'id': step['id'], 'phase': step['phase'],
            'status': attempt.get('status', 'pending'),
            'attempt': number, 'exit_code': attempt.get('exit_code'),
            'command_duration_seconds': attempt.get('duration_seconds'),
            'error': attempt.get('error', '')[:500] or None,
            'logs': ([str(directory / f'{number}-stdout.log'),
                      str(directory / f'{number}-stderr.log')] if number else []),
        })
    stage = 'interpret' if complete else 'diagnose'
    return {
        'schema_version': 1,
        'experiment': {key: value[:2000] if isinstance(value, str) else value
                       for key, value in plan['experiment'].items()
                       if key in ('question', 'hypothesis', 'decision_rule', 'stop_rule',
                                  'cohort', 'frozen_rules', 'predictions')},
        'outcome': 'ready_for_interpretation' if complete else 'incomplete',
        'next_stage': stage, 'recommended_reasoning': POLICY[stage],
        'summary': state['summary'], 'attempts_retained': len(state['attempts']),
        'steps': steps, 'steps_omitted': max(0, len(ordered) - limit),
        'manifest': str(plan_path),
        'manifest_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        'status': str(directory / 'status.json'),
        'notice': ('Command durations are orchestration timings, not complete-job benchmark '
                   'measurements. Read declared harness artifacts for metrics. This packet '
                   'does not choose a winner or revalidate source/artifact freshness.'),
    }


def run(path, directory, guard=None):
    plan = load_plan(path)
    # Freeze the wrapper/runner versions into the existing immutable manifest.
    # A changed driver requires a new batch rather than silently reusing passes.
    plan['experiment_driver'] = driver_identity()
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Keep driver input outside the owned batch: runner itself owns its lock.
    with tempfile.TemporaryDirectory(prefix='chopper-experiment-') as temporary:
        prepared = Path(temporary) / 'plan.json'
        prepared.write_text(json.dumps(plan), encoding='utf-8')
        code = runner.run(prepared, directory, guard=guard)
    result = packet(directory)
    runner.write_json(directory / 'decision-packet.json', result)
    print(json.dumps(result, indent=2))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('policy', help='show recommended reasoning routing; no model calls')
    execute = commands.add_parser('run', help='execute or safely resume a declared plan')
    execute.add_argument('plan', type=Path)
    execute.add_argument('directory', type=Path)
    report = commands.add_parser('packet', help='summarize a saved batch without running it')
    report.add_argument('directory', type=Path)
    report.add_argument('--limit', type=int, default=12)
    args = parser.parse_args()
    try:
        if args.command == 'policy':
            print(json.dumps(POLICY, indent=2))
            return 0
        if args.command == 'run':
            return run(args.plan.resolve(), args.directory.resolve())
        if not 1 <= args.limit <= 100:
            raise ValueError('packet limit must be between 1 and 100')
        print(json.dumps(packet(args.directory.resolve(), args.limit), indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'experiment-cycle: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
