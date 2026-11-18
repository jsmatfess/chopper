#!/bin/sh
# Run the repository-local Linux/WSL Graphify CLI without model backends.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python="$repo_root/.tools/graphify/venv-linux/bin/python"
if [ ! -x "$python" ]; then
    echo 'Graphify is not installed. See docs/graphify.md for setup.' >&2
    exit 1
fi
cd "$repo_root"
export GRAPHIFY_BACKEND=none PYTHONIOENCODING=utf-8
exec "$python" -m graphify "$@"
