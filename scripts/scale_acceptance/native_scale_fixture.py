"""Independent source-only checkpoint. Never imports the generator or recipe."""
import hashlib
import json
import os
from pathlib import Path
from .verify import expected_header, inspect_row, read_json, require, validate_job


def validate_metadata(job, fixture, recipe, source=None):
    config, meta = read_json(job), read_json(fixture)
    validate_job(config, meta)
    require(meta['runtime'] == 'native', 'native fixture required')
    require(json.dumps({k: v for k, v in meta.items() if k != 'sha256'}, sort_keys=True) ==
            json.dumps({k: v for k, v in recipe.items() if k not in ('sha256', 'job')}, sort_keys=True),
            'approved recipe dimensions mismatch')
    expected_job = dict(recipe['job'], input=str(source if source is not None else Path(job).parent/'input.csv'),
                        output=str(Path(job).parent/'output'),
                        resources={**recipe['job']['resources'], 'temp_dir': str(Path(job).parent/'temp')})
    require(json.dumps(config, sort_keys=True) == json.dumps(expected_job, sort_keys=True),
            'approved Job/path commitment mismatch')
    return config, meta


def checkpoint_record(meta):
    return dict(sha256=meta['sha256'], rows=meta['rows'], bytes=meta['bytes'],
                shape=meta['shape'], runtime='native', independent_source_check=True)


def _file_stamp(value, time_field='st_ctime_ns'):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, getattr(value, time_field))


def checkpoint(job, fixture, recipe, progress=lambda rows: None):
    config, meta = validate_metadata(job, fixture, recipe)
    source = Path(config['input'])
    require(not source.is_symlink() and source.stat().st_size == meta['bytes'], 'fixture size')
    before = source.stat()
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        # Windows path stat aliases ctime to birth time, while fstat may return
        # change time. Compare birth time across APIs, then each API to itself.
        time_field = ('st_birthtime_ns' if os.name == 'nt' and
                      all(hasattr(value, 'st_birthtime_ns') for value in (before, opened)) else 'st_ctime_ns')
        require(_file_stamp(before, time_field) == _file_stamp(opened, time_field),
                'fixture changed before checkpoint open')
        header = stream.readline(meta['width'] + 1)
        require(header == expected_header(meta['width']), 'fixture header')
        digest.update(header)
        for index in range(meta['rows']):
            raw = stream.readline(meta['width'] + 1)
            require(inspect_row(raw, meta['width'], meta['rows']) == index, 'fixture ID order')
            digest.update(raw)
            if index % 10000 == 0:
                progress(index + 1)
        require(stream.read(1) == b'', 'extra fixture bytes')
        require(_file_stamp(opened) == _file_stamp(os.fstat(stream.fileno())),
                'fixture changed during checkpoint')
    after = source.stat()
    require(_file_stamp(before) == _file_stamp(after),
            'fixture changed during checkpoint')
    require(digest.hexdigest() == meta['sha256'], 'independent fixture SHA/metadata mismatch')
    require('sha256' not in recipe or digest.hexdigest() == recipe['sha256'],
            'optional expected recipe SHA mismatch')
    return checkpoint_record(meta)
