"""Small ZIP metadata-selection/allocation diagnostic; no throughput claim.

Uses a pinned allocation-profile example and its original build record. Retains
successful censuses and rejected attempts. All archive fixtures fit below 10 MiB;
the child profile contains the same one CSV row. No output job is published.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import zipfile


CSV = b'id,payload\n1,hello\n'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(entries=1, name='sample.csv'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as writer:
        writer.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), CSV)
        for index in range(entries - 1):
            writer.writestr(zipfile.ZipInfo(f'entry-{index:05}.bin', (2026, 1, 1, 0, 0, 0)), b'')
    return stream.getvalue()


def end(data):
    position = data.rfind(b'PK\x05\x06')
    assert position >= 0 and position + 22 == len(data)
    count, length, offset = struct.unpack_from('<HII', data, position + 10)
    return position, count, length, offset


def fixtures():
    many = archive(8193)
    _, count, length, _ = end(many)
    # Its final EOCD has no central header at offset zero. zip 2.4.2 can
    # discard that candidate and decode the original earlier directory.
    fallback = many + struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, 1, 1, 0, 0, 0)
    long_name = bytearray(archive(name='界' * 20000 + '.csv'))
    position, _, long_length, _ = end(long_name)
    struct.pack_into('<I', long_name, position + 12, 0)
    normal = archive()
    position, _, normal_length, normal_offset = end(normal)
    extension_bytes = 8 * 1024 * 1024
    zip64_end = struct.pack('<4sQHHIIQQQQ', b'PK\x06\x06', 44 + extension_bytes,
                           45, 45, 0, 0, 1, 1, normal_length, normal_offset)
    locator = struct.pack('<4sIQI', b'PK\x06\x07', 0, position, 1)
    sentinel = struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, 65535, 65535,
                           0xffffffff, 0xffffffff, 0)
    zip64 = normal[:position] + zip64_end + bytes(extension_bytes) + locator + sentinel
    return [
        ('plain_control', CSV, {'entries': 0, 'zip64_extension_bytes': 0}),
        ('many_entries_control', many, {'entries': count, 'actual_directory_bytes': length,
                                      'selected_preflight_count': count, 'selected_preflight_directory_bytes': length}),
        ('earlier_directory_fallback', fallback, {'entries': count, 'actual_directory_bytes': length,
                                                'selected_preflight_count': 1, 'selected_preflight_directory_bytes': 0}),
        ('underreported_directory_length', bytes(long_name), {'entries': 1, 'actual_directory_bytes': long_length,
                                                            'selected_preflight_count': 1, 'selected_preflight_directory_bytes': 0}),
        ('zip64_extension', zip64, {'entries': 1, 'actual_directory_bytes': normal_length,
                                  'selected_preflight_count': 1, 'selected_preflight_directory_bytes': normal_length,
                                  'zip64_extension_bytes': extension_bytes}),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allocator', type=Path, required=True)
    parser.add_argument('--build-record', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    builds = json.loads(args.build_record.read_text(encoding='utf-8'))
    build = builds['builds']['baseline']
    if build['features'] or build['returncode'] != 0 or sha(args.allocator) != build['allocator']['sha256']:
        parser.error('allocator does not match a successful no-feature baseline build')
    if not builds.get('source_identity_unchanged') or not builds.get('source_sha256'):
        parser.error('build record lacks matched source identity')
    binary = args.allocator.resolve()
    sys.stdout = args.output.open('x', encoding='utf-8', buffering=1)
    def emit(value):
        print(json.dumps(value), flush=True)
    emit({'type': 'environment', 'scope': 'allocation/parser-selection diagnostic; not timing or an RSS cap',
          'platform': platform.platform(), 'python': platform.python_version(),
          'allocator_sha256': sha(binary), 'build_record': str(args.build_record),
          'build_record_sha256': sha(args.build_record), 'build_source_sha256': builds['source_sha256'],
          'harness_sha256': sha(Path(__file__)), 'work_dir': str(args.work_dir.resolve()),
          'memory_mb': 32, 'workers': 1, 'metadata_eligibility_budget_bytes': 4 * 1024 * 1024,
          'aggregate_limits_mb': [1, 128], 'samples_per_fixture_limit': 1,
          'cache': 'uncontrolled; fixture generation touches cache; fresh child for each census',
          'stop_criterion': 'five fixed sub-10-MiB fixtures at two fixed shared ceilings; retain every rejection; stop on invalid successful profile or cleanup mismatch'})
    cases = fixtures()
    allowed_names = {'job.json', *(f'{name}.data' for name, _, _ in cases)}
    with tempfile.TemporaryDirectory(prefix='zip-metadata-probe-', dir=args.work_dir) as directory:
        root = Path(directory)
        for name, data, description in cases:
            assert len(data) < 10 * 1024 * 1024
            source = root / f'{name}.data'
            source.write_bytes(data)
            emit({'type': 'fixture', 'name': name, 'bytes': len(data), 'sha256': sha(source), **description})
            for limit in (1, 128):
                job = {'input': str(source), 'output': str(root / 'output'), 'seed': 'zip-metadata-probe-v1',
                       'resources': {'memory_mb': 32, 'workers': 1, 'max_record_bytes': 1048576, 'temp_dir': str(root)}}
                config = root / 'job.json'
                config.write_text(json.dumps(job), encoding='utf-8')
                environment = {**os.environ, 'CHOPPER_MEMORY_LIMIT_MB': str(limit)}
                try:
                    result = subprocess.run([str(binary), str(config), 'profile'], env=environment,
                                            capture_output=True, text=True, encoding='utf-8', timeout=90)
                except BaseException as error:
                    emit({'type': 'failure', 'fixture': name, 'aggregate_limit_mb': limit, 'error': repr(error)})
                    raise
                observation = {'type': 'allocation' if result.returncode == 0 else 'rejection',
                               'fixture': name, 'aggregate_limit_mb': limit, 'config': job,
                               'exit_code': result.returncode, 'stderr': result.stderr}
                if result.returncode == 0:
                    census = json.loads(result.stdout)
                    assert census['profile']['rows'] == 1 and census['profile']['columns'] == 2
                    assert census['profile']['header'] == ['id', 'payload']
                    observation['census'] = census
                else:
                    observation['stdout'] = result.stdout
                emit(observation)
                assert not (root / 'output').exists(), 'profile published output'
                assert set(p.name for p in root.iterdir()) <= allowed_names, 'profile leaked workspace'
    assert not root.exists(), 'diagnostic fixture directory survived cleanup'
    emit({'type': 'complete', 'fixtures': 5, 'observations': 10,
          'output_absent': True, 'workspace_cleanup_verified': True, 'fixture_directory_removed': True,
          'scope': 'diagnostic observations; ownership proof and broader compatibility require separate contracts'})


if __name__ == '__main__':
    main()
