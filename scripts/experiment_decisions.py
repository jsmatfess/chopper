"""Offline decision-provider boundary. No network, subprocess or model adapter."""
import json
import re


def validate(value, packet_hash=None):
    required = {'action', 'target', 'assessment', 'reason'}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - {'packet_sha256'}:
        raise ValueError('invalid decision fields')
    if value['action'] not in ('stop', 'repeat', 'refine', 'challenger'):
        raise ValueError('unsupported decision action')
    if value['assessment'] not in ('useful', 'rejected', 'inconclusive'):
        raise ValueError('unsupported assessment')
    if not isinstance(value['reason'], str) or not 1 <= len(value['reason'].strip()) <= 2000:
        raise ValueError('bounded nonempty reason required')
    if value['action'] == 'stop':
        if value['target'] is not None:
            raise ValueError('stop target must be null')
    elif not isinstance(value['target'], str) or not 1 <= len(value['target']) <= 80:
        raise ValueError('bounded target required')
    if packet_hash is not None and value.get('packet_sha256') != packet_hash:
        raise ValueError('decision packet hash mismatch')
    if 'packet_sha256' in value and (not isinstance(value['packet_sha256'], str)
                                   or not re.fullmatch('[0-9a-f]{64}', value['packet_sha256'])):
        raise ValueError('invalid packet hash')
    return value


def provide(config, index, packet_hash, path=None):
    """Return one validated response, or None for durable decision-needed mode.

    File providers require an exact packet hash. Predeclared responses are frozen
    before any execution, so the controller binds their hash when journaling.
    A future real adapter must implement this boundary separately and disclose
    its actual settings/usage; these offline providers have neither.
    """
    if path is not None:
        if path.stat().st_size > 16384:
            raise ValueError('decision exceeds 16 KiB')
        return validate(json.loads(path.read_text(encoding='utf-8')), packet_hash)
    if config['provider'] == 'predeclared' and index < len(config.get('decisions', [])):
        return validate(config['decisions'][index])
    return None
