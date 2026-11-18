"""Bounded independent codecs for the small hosted graph acceptance fixtures."""
import ctypes
import ctypes.util
import io
import json
import sys
import zipfile

payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
if len(payload) > 8 * 1024 * 1024:
    raise SystemExit("graph codec fixture exceeds 8 MiB")
mode = sys.argv[1]
if mode in ("zip-input", "zip-selected-input"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("selected.csv", payload)
        archive.writestr("other.csv" if mode == "zip-selected-input" else "ignored.txt", "not CSV")
    sys.stdout.buffer.write(output.getvalue())
elif mode == "zip-output":
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(member.file_size for member in archive.infolist()) > 64 * 1024 * 1024:
            raise SystemExit("graph archive fixture exceeds decoded envelope")
        result = {member.filename: {"text": archive.read(member).decode("utf-8"), "stored_bytes": member.compress_size} for member in archive.infolist()}
    json.dump(result, sys.stdout)
elif mode in ("zstd-input", "zstd-output"):
    library = sys.argv[2] if len(sys.argv) == 3 else ctypes.util.find_library("zstd")
    if not library:
        raise SystemExit("hosted graph codec fixtures require Python 3 and libzstd")
    codec = ctypes.CDLL(library)
    codec.ZSTD_isError.argtypes = [ctypes.c_size_t]
    codec.ZSTD_isError.restype = ctypes.c_uint
    source = ctypes.create_string_buffer(payload)
    if mode == "zstd-input":
        codec.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        codec.ZSTD_compressBound.restype = ctypes.c_size_t
        capacity = codec.ZSTD_compressBound(len(payload))
        output = ctypes.create_string_buffer(capacity)
        codec.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        codec.ZSTD_compress.restype = ctypes.c_size_t
        size = codec.ZSTD_compress(output, capacity, source, len(payload), 3)
    else:
        capacity = 1024 * 1024  # Per-CSV fixture bound, independent of claimed frame size.
        output = ctypes.create_string_buffer(capacity)
        codec.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        codec.ZSTD_decompress.restype = ctypes.c_size_t
        size = codec.ZSTD_decompress(output, capacity, source, len(payload))
    if codec.ZSTD_isError(size):
        raise SystemExit("independent Zstandard fixture codec failed")
    sys.stdout.buffer.write(output.raw[:size])
else:
    raise SystemExit("unknown graph codec fixture mode")
