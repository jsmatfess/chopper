# Local code graph

Chopper uses the local [Graphify CLI](https://github.com/Graphify-Labs/graphify),
not Graphify Cloud. The PowerShell wrapper disables model backends with
`GRAPHIFY_BACKEND=none`; extraction uses `--code-only` so documentation and media
are not sent for semantic extraction. No API key or hosted account is required.

## Install on Windows

From the repository root, with Python 3.10+ available (validated with 3.13):

```powershell
python -m venv .tools/graphify/venv
.\.tools\graphify\venv\Scripts\python.exe -m pip install "graphifyy[mcp]==0.9.95"
```

The environment and generated graph are ignored by Git. The installed package
is named `graphifyy`; its CLI/module is named `graphify`.

## Install on Linux / WSL

Keep a separate Linux environment so the Windows interpreter remains usable.
With Python 3.10+ and pip available, run from the repository root:

```sh
python3 -m venv .tools/graphify/venv-linux
.tools/graphify/venv-linux/bin/python -m pip install "graphifyy[mcp]==0.9.95"
```

If using uv, the equivalent is `uv venv --python 3.13 .tools/graphify/venv-linux`
followed by `uv pip install --python .tools/graphify/venv-linux/bin/python 'graphifyy[mcp]==0.9.95'`.
The Linux/WSL wrapper sets the same backend and encoding controls as PowerShell:

```sh
sh scripts/graphify.sh extract . --code-only --cargo --max-workers 4
sh scripts/graphify.sh cluster-only . --no-label
sh scripts/graphify.sh query "PreparedJob" --budget 1200
sh scripts/graphify.sh explain "PreparedJob"
```

## Build and query

```powershell
# Build or refresh the graph, including Cargo workspace dependency edges.
powershell -NoProfile -File scripts/graphify.ps1 extract . --code-only --cargo --max-workers 4
# Generate the report and interactive HTML without model-generated labels.
powershell -NoProfile -File scripts/graphify.ps1 cluster-only . --no-label
# Ask a scoped question; increase the budget if results are truncated.
powershell -NoProfile -File scripts/graphify.ps1 query "PreparedJob" --budget 1200
powershell -NoProfile -File scripts/graphify.ps1 explain "PreparedJob"
```

Open `graphify-out/graph.html` for the interactive graph. Refresh after source
changes; no watcher or Git hooks are installed. `.graphifyignore` excludes
vendored sources, historical evidence, generated UI output and build directories.
The map covers maintained code, tests and scripts, not the complete dependency
implementation. Read vendor contracts directly when working on codecs or ZIP.
AST edges are navigation aids; verify behavior in source and the specifications.

## Optional local MCP client connection

The CLI works immediately without MCP. To expose the same graph to an MCP client,
configure a stdio server with the following fields, replacing `<repo>` with the
absolute checkout path:

```json
{
  "command": "<repo>/.tools/graphify/venv/Scripts/python.exe",
  "args": ["-m", "graphify.serve", "<repo>/graphify-out/graph.json"],
  "env": {"GRAPHIFY_BACKEND": "none", "PYTHONIOENCODING": "utf-8"}
}
```

This starts a local process; it does not connect to Graphify Cloud. Installing the
CLI does not register an MCP server with an assistant. The repository's primary
query paths are the platform wrappers above.

For Linux / WSL Codex, register the same local stdio server from the repository
root after building the graph:

```sh
codex mcp add graphify --env GRAPHIFY_BACKEND=none --env PYTHONIOENCODING=utf-8 -- \
  "$PWD/.tools/graphify/venv-linux/bin/python" -m graphify.serve \
  "$PWD/graphify-out/graph.json"
codex mcp get graphify
```

Restart the assistant session to load newly registered MCP tools. Registration
contains this checkout's absolute paths; update it if the checkout moves.
