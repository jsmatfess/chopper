#!/usr/bin/env python3
"""Tiny #153 qualification fixtures; no Chopper/browser processes are started."""
import argparse
import csv
import io
import json
from pathlib import Path
import tempfile

# Literal bytes checked with Python codecs, independently of the Rust engine.
FIXTURES = {
    'cp1252': ('cp1252', 'id,text\n1,café €\n', '69642c746578740a312c636166e920800a'),
    'sjis': ('shift_jis', 'id,text\n1,日本\n', '69642c746578740a312c93fa967b0a'),
}


def fixture(label):
    codec, text, hex_bytes = FIXTURES[label]
    encoded = bytes.fromhex(hex_bytes)
    assert text.encode(codec) == encoded
    assert encoded.decode(codec) == text
    assert encoded != text.encode('utf-8')
    return codec, text, encoded


def verify(label, output):
    codec, text, expected = fixture(label)
    files = sorted(output.glob('*.csv'))
    assert len(files) == 1, f'Expected one CSV, found {files}'
    actual = files[0].read_bytes()
    assert actual == expected, f'{label}: expected {expected.hex()}, got {actual.hex()}'
    assert list(csv.reader(io.StringIO(actual.decode(codec)))) == list(csv.reader(io.StringIO(text)))


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    for label in FIXTURES:
        _, _, encoded = fixture(label)
        source = root / f'{label}.csv'
        source.write_bytes(encoded)
        settings = dict(encoding=label, headers=True, delimiter=',', quote='"', escape=None,
                        line_ending='lf', bom=False, skip_empty_lines=False)
        job = dict(version=1, input=str(source.resolve()), output=str((root / f'{label}-results').resolve()),
                   input_csv=settings, output_csv=settings, compression='none', operations=[],
                   limits=dict(rows=2, bytes=32), resources=dict(memory_mb=32, workers=1, max_record_bytes=1048576), seed='encoding-153')
        (root / f'{label}.json').write_text(json.dumps(job, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def self_test():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        prepare(root / 'inputs')
        for label in FIXTURES:
            job = json.loads((root / 'inputs' / f'{label}.json').read_text(encoding='utf-8'))
            resources = job['resources']
            assert resources['max_record_bytes'] == 1048576
            assert resources['max_record_bytes'] <= resources['memory_mb'] * 1024**2 // 16
            assert job['input_csv']['encoding'] == job['output_csv']['encoding'] == label
            _, text, encoded = fixture(label)
            output = root / label
            output.mkdir()
            target = output / 'part-00000001.csv'
            target.write_bytes(encoded)
            verify(label, output)
            target.write_bytes(text.encode('utf-8'))
            try:
                verify(label, output)
            except AssertionError:
                pass
            else:
                raise AssertionError('Verifier accepted silent UTF-8 substitution')
    print('Fixture/control checks passed; no engine execution claimed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('self-test')
    commands.add_parser('prepare').add_argument('directory', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('label', choices=FIXTURES)
    check.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.command == 'self-test':
        self_test()
    elif args.command == 'prepare':
        prepare(args.directory)
    else:
        verify(args.label, args.output)
        print(f'{args.label}: exact non-ASCII encoded CSV bytes verified')
