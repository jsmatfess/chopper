"""Bounded independent codecs for the small hosted graph acceptance fixtures."""
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

else:
    raise SystemExit("unknown graph codec fixture mode")
