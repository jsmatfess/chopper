"""Streaming fixed-width generator; existing destinations are never overwritten."""
import hashlib
import json
from pathlib import Path
from .recipe import VERSION, dimensions, job


def header(width):
    return b'id,region,' + b'p' * (width - 11) + b'\n'


def row(index, width):
    digest = hashlib.sha256(f'{VERSION}:{index}'.encode('ascii')).hexdigest()
    payload = (digest * ((width - 17 + 63) // 64))[:width - 17]
    value = f'{index:012d},r{index % 8},{payload}\n'.encode('ascii')
    assert len(value) == width
    return value


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def fixture_identity(shape, runtime, rows=None):
    """Hash the selected stream without allocating or writing a fixture.

    This is cold preparation, not a generation debit or proof of a stored input.
    Actual generation and pre-Run readers still verify the complete body.
    """
    width, count, size = dimensions(shape, runtime, rows)
    digest = hashlib.sha256(header(width))
    for index in range(count):
        digest.update(row(index, width))
    return dict(width=width, rows=count, bytes=size, sha256=digest.hexdigest())


def prepare(directory, shape, runtime, rows=None, *, borrowed=None):
    width, count, size = dimensions(shape, runtime, rows)
    directory = Path(directory).absolute()
    if borrowed is not None:
        from .hosted_qualification import check_borrowed_input
        if runtime != 'browser' or shape != 'D' or rows != 127:
            raise ValueError('borrowed input is only the bounded browser D fixture')
        check_borrowed_input(borrowed)
        from .browser_scale_identity import tiny_fixture
        expected = tiny_fixture(shape, rows)
        if borrowed['sha256'] != expected['sha256'] or borrowed['bytes'] != expected['bytes']:
            raise ValueError('borrowed deterministic fixture mismatch')
        directory.mkdir(parents=True, exist_ok=False)
        source = Path(borrowed['path'])
        metadata = dict(generator=VERSION, shape=shape, runtime=runtime, tiny=True, **expected)
        write_new(directory / 'fixture.json', metadata)
        write_new(directory / 'job.json', job(shape, runtime, source, directory/'output', directory/'temp'))
        check_borrowed_input(borrowed)
        return metadata
    directory.mkdir(parents=True, exist_ok=False)
    source = directory / 'input.csv'
    sha = hashlib.sha256()
    with source.open('xb') as stream:
        first = header(width)
        assert len(first) == width
        stream.write(first)
        sha.update(first)
        for index in range(count):
            data = row(index, width)
            stream.write(data)
            sha.update(data)
            if index % 10000 == 0:
                print(json.dumps(dict(phase='generate', rows=index + 1)), flush=True)
    assert source.stat().st_size == size
    metadata = dict(generator=VERSION, shape=shape, runtime=runtime, width=width,
                    rows=count, bytes=size, sha256=sha.hexdigest(), tiny=rows is not None)
    write_new(directory / 'fixture.json', metadata)
    (directory / 'temp').mkdir()
    write_new(directory / 'job.json', job(shape, runtime, source, directory / 'output', directory / 'temp'))
    return metadata
