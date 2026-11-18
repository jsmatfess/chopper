"""Opt-in Codex CLI decision adapter; all subprocess lifecycle is owned by runner."""
import json
from pathlib import Path

from experiment_decisions import validate


def command(settings):
    return [settings['executable'], '--no-daemon', '-a', 'never', 'exec', '--ephemeral', '--ignore-user-config',
            '--ignore-rules', '--skip-git-repo-check', '--sandbox', 'read-only', '--json',
            '--disable', 'shell_tool', '-c', 'project_doc_max_bytes=0', '-c', 'web_search="disabled"',
            '-c', 'model_reasoning_effort=' + json.dumps(settings['reasoning_effort']),
            '--model', settings['model'], '--output-schema', 'decision.schema.json',
            '--output-last-message', 'response.json', '-']


def run(settings, packet_path, directory, runner, guard):
    """No fallback/retry and no API dependency. Saved CLI authentication is reused.

    The packet is the only experiment data in stdin. Repository instructions and
    shell/search are disabled; no persistent rollout is requested. Supplied model
    settings are explicit, never inferred from the parent agent's runtime.
    """
    directory.mkdir(exist_ok=False)
    packet_hash = runner.digest(packet_path)
    packet_bytes = packet_path.read_bytes()
    if len(packet_bytes) > 32768:
        raise ValueError('provider packet exceeds 32 KiB')
    (directory / 'packet.json').write_bytes(packet_bytes)
    schema = Path(__file__).with_name('experiment-decision.schema.json')
    (directory / 'decision.schema.json').write_bytes(schema.read_bytes())
    prompt = ('You are the decision provider for a bounded experiment controller. Use only the JSON packet below. '
              'Do not use tools, read files, run experiments, or implement code. '
              'Return exactly one JSON object conforming to the supplied schema. '
              'Choose stop if there is no useful next approved question, correctness failed, or the packet is inconclusive '
              'and another approved batch cannot resolve a concrete uncertainty. '
              'Otherwise use exactly one action/target transition from allowed_targets. '
              'Never promote a default or invent missing measurements. A harness acceptance control is not a performance finding. '
              'For stop target must be null; otherwise it must be a listed transition target. '
              'Set packet_sha256 to ' + packet_hash + '.\nPACKET:\n' + packet_bytes.decode('utf-8'))
    (directory / 'prompt.txt').write_text(prompt, encoding='utf-8')
    plan = {'root': str(directory), 'batch_timeout_seconds': settings['timeout_seconds'],
            'estimated_seconds': settings['timeout_seconds'], 'estimated_disk_bytes': 1024**2,
            'toolchains': {'codex_executable': settings['executable'], 'model': settings['model'],
                           'reasoning_effort': settings['reasoning_effort']},
            'features': ['ephemeral', 'read-only', 'shell-disabled', 'web-search-disabled'],
            'fixtures': ['bounded decision packet only'], 'steps': [{
                'id': 'decision', 'argv': command(settings), 'stdin_file': 'prompt.txt',
                'timeout_seconds': settings['timeout_seconds'],
                'inputs': ['packet.json', 'decision.schema.json', 'prompt.txt'],
                'artifacts': ['response.json'], 'depends': []}]}
    path = directory / 'plan.json'
    runner.write_json(path, plan)
    code = runner.run(path, directory / 'runner', guard=guard)
    metadata = {'supplied_settings': settings, 'returned_model': None, 'usage': None,
                'status': str(directory / 'runner/status.json'), 'packet_sha256': packet_hash,
                'status_sha256': runner.digest(directory / 'runner/status.json'),
                'authentication': 'existing CLI authentication; credentials are not copied'}
    log = directory / 'runner/1-stdout.log'
    if log.exists() and log.stat().st_size <= 8 * 1024**2:
        with log.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
                    metadata['usage'] = event['usage']
                if isinstance(event.get('model'), str):
                    metadata['returned_model'] = event['model']
    runner.write_json(directory / 'provider-record.json', metadata)
    if code:
        raise OSError('Codex decision invocation failed; see ' + str(directory / 'runner'))
    response = directory / 'response.json'
    if response.stat().st_size > 16384:
        raise ValueError('provider response exceeds 16 KiB')
    metadata['response_sha256'] = runner.digest(response)
    metadata['events_sha256'] = runner.digest(log)
    runner.write_json(directory / 'provider-record.json', metadata)
    return validate(json.loads(response.read_text(encoding='utf-8')), packet_hash), metadata
