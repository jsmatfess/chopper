"""Adversarial checks for the standalone text-block experiment, not production spills."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile

spec = importlib.util.spec_from_file_location('formats', Path(__file__).with_name('benchmark-input-formats.py'))
formats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formats)
results = []
with tempfile.TemporaryDirectory(prefix='chopper-block-controls-') as directory:
    path = Path(directory) / 'block'
    expected = [['id', 'text', 'tail'], ['001', '', 'NULL'], ['2', 'quote,"\n\0', '界']]
    for compact in [False, True]:
        kind = 'compact' if compact else 'u64'
        formats.write_blocks(path, iter(expected), compact)
        valid = path.read_bytes()
        assert list(formats.read_blocks(path, compact)) == expected
        results.append({'format': kind, 'case': 'text_roundtrip', 'verified': True})
        cases = {'version': b'BADBLOCK' + valid[8:],
                 'truncated_header': valid[:10],
                 'truncated_payload': valid[:-1],
                 'utf8': valid[:-1] + b'\xff',
                 'trailing_header_byte': valid + b'\0'}
        data = bytearray(valid)
        struct.pack_into('<I', data, 8, formats.BLOCK_ROWS + 1)
        cases['row_limit'] = bytes(data)
        data = bytearray(valid)
        struct.pack_into('<I', data, 16, formats.MAX_BLOCK + 1)
        cases['payload_limit'] = bytes(data)
        data = bytearray(valid)
        offset = 20 if compact else 28
        struct.pack_into('<I' if compact else '<Q', data, offset, 0xffffffff)
        cases['field_exceeds_block'] = bytes(data)
        if not compact:
            data = bytearray(valid)
            struct.pack_into('<Q', data, 20, 4)
            cases['field_count_mismatch'] = bytes(data)
        data = bytearray(valid)
        size = struct.unpack_from('<I', data, 16)[0]
        struct.pack_into('<I', data, 16, size + 1)
        data.append(0)
        cases['trailing_payload_byte'] = bytes(data)
        for name, data in cases.items():
            path.write_bytes(data)
            try:
                list(formats.read_blocks(path, compact))
            except (ValueError, UnicodeDecodeError):
                pass
            else:
                raise AssertionError((kind, name, 'corruption accepted'))
            results.append({'format': kind, 'case': name, 'verified': True})
print(json.dumps({'scope': 'standalone text blocks only; not production spill/cancellation/memory validation',
                  'checks': results, 'verified': True}, indent=2))
