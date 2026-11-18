"""Versioned, row-addressed synthetic entity lists; no private source records."""
import csv
import hashlib
import json
from pathlib import Path


VERSION = 'entity-list-v1'
HEADER = ['record_id', 'region', 'locality', 'segment', 'name', 'address', 'notes']


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def row_at(index, parameters):
    def draw(field):
        key = json.dumps([VERSION, parameters['seed'], index, field],
                         ensure_ascii=True, separators=(',', ':')).encode()
        return int.from_bytes(hashlib.sha256(key).digest()[:8], 'big')

    regions = parameters['regions']
    # Independent categorical region and payload-width draws: no reserved
    # correlated-width/skew or late-key performance holdouts are generated here.
    region = (0 if draw('hot') % 100 < parameters['hot_percent']
              else 1 + draw('region') % (regions - 1)) if regions > 1 else 0
    width = parameters['notes_min'] + draw('width') % (
        parameters['notes_max'] - parameters['notes_min'] + 1)
    prefix = 'note,\n"quoted" ' if index % 17 == 0 else 'contact '
    # ASCII notes give an exact configurable byte width. Other fields exercise
    # Unicode, empty fields, quotes and delimiters without inferring data types.
    text = hashlib.sha256(str(draw('payload')).encode()).hexdigest()
    notes = (prefix + text * ((width // len(text)) + 1))[:width]
    return [str(index), f'region-{region:03}', f'locality-{draw("locality") % 32:03}',
            f'segment-{draw("segment") % 4}',
            ['Alex Chen', 'José Rivera', 'Zoë Martin', 'Sam Patel'][draw('name') % 4],
            '' if index % 19 == 0 else f'{1 + draw("address") % 9999} "Market", Road', notes]


def generate(path, parameters):
    parameters = dict(parameters)
    for field in ('rows', 'regions', 'hot_percent', 'notes_min', 'notes_max'):
        if type(parameters.get(field)) is not int:
            raise ValueError(f'{field} must be an integer')
    if not 0 <= parameters['rows'] or not 1 <= parameters['regions'] <= 1000:
        raise ValueError('rows must be nonnegative; regions must be 1..1000')
    if not 0 <= parameters['hot_percent'] <= 100:
        raise ValueError('hot_percent must be 0..100')
    if not 0 <= parameters['notes_min'] <= parameters['notes_max'] <= 262144:
        raise ValueError('notes widths must be ordered and at most 262144 bytes')
    if not isinstance(parameters.get('seed'), str) or not parameters['seed']:
        raise ValueError('a nonempty generation seed is required')
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(HEADER)
        for index in range(parameters['rows']):
            writer.writerow(row_at(index, parameters))
    metadata = {'generator': VERSION, 'parameters': parameters, 'header': HEADER,
                'sha256': sha256(path), 'bytes': path.stat().st_size,
                'generator_source_sha256': sha256(Path(__file__)),
                'dialect': {'encoding': 'utf-8', 'headers': True, 'delimiter': ',',
                            'quote': '"', 'line_ending': 'lf', 'bom': False},
                'cohort': 'development'}
    return metadata
