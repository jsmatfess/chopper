# Local Context Mode setup

[Context Mode](https://github.com/mksglu/context-mode) is optional developer
tooling for executing analysis outside the model context and searching indexed
output. It complements [Graphify](../graphify.md) navigation and [RTK](../../RTK.md)
command-output compression. It is not a Chopper build dependency.

## Install and register on Windows

Requires Node.js 22.5 or newer and the Codex CLI. From PowerShell:

```powershell
npm install -g context-mode@1.0.169
$contextModeEntry = Join-Path (npm root -g) 'context-mode/cli.bundle.mjs'
codex mcp add context-mode --env CONTEXT_MODE_PLATFORM=codex -- node $contextModeEntry
codex mcp get context-mode
context-mode doctor
```

Registration writes the user-level Codex MCP configuration. Calling Node directly
avoids Windows `.cmd` launcher ambiguity. Restart the Codex/T3 provider session
after registration so it reloads its MCP tool catalog. Check for `ctx_execute`,
`ctx_index` and `ctx_search`; tool names may include an MCP prefix. Hosts that do
not load Codex's configuration need an equivalent stdio MCP registration using
the same Node command, entry-point argument and environment variable.

This setup uses explicit MCP calls and the repository's [agent instructions](../../AGENTS.md),
without Context Mode hooks or its default mandatory routing block. Existing RTK
hooks are retained. Doctor reports missing Context Mode hooks / hooks feature
flag in this mode; these are intentional, while server initialization and
FTS5/SQLite must pass. Automatic session capture, routing enforcement and
history restoration are not enabled. Do not assume an empty history search
means no earlier work occurred.

## Install and register on Linux / WSL

Use Node.js 22.5+ in the Linux environment. From the repository root:

```sh
npm install -g context-mode@1.0.169
codex mcp add context-mode --env CONTEXT_MODE_PLATFORM=codex -- \
  "$(node -p 'process.execPath')" "$(npm root -g)/context-mode/cli.bundle.mjs"
codex mcp get context-mode
context-mode doctor
```

This registers explicit MCP calls with the same hook-free policy described
above. The resolved Node executable and package entry point are absolute paths;
re-register after moving or replacing that Node installation. Restart the
assistant session to load the tools.

## Use and verify

Use JavaScript for portable analysis and absolute paths for input files. Set
child-process cwd explicitly when invoking project commands; execution directories
and shell selection can differ from the agent terminal. Inspect current MCP tool
schemas rather than assuming arguments from examples for another version.

After restarting, execute a small JavaScript calculation, index a short labelled
sample, and search for its unique phrase. `ctx_stats` reports actual tool usage;
installation alone does not save context. Prefer focused indexing of relevant
documents or logs over a repository-wide copy. Re-index changed sources and
verify important findings directly against current source and owning documents.

Local content/session storage defaults to `~/.codex/context-mode/` for this
platform. Treat indexes as disposable retrieval aids, not maintained project
documentation or benchmark evidence. Check `context-mode doctor` for resolved
storage paths. Upgrades are deliberate: install the chosen package version,
repeat server/SQLite and execute/index/search checks, and restart the provider.
Avoid `context-mode upgrade` for this setup because it also configures hooks.

To remove the integration, run `codex mcp remove context-mode` and
`npm uninstall -g context-mode`. These commands do not promise to erase existing
indexes; use the package's purge tool only when intentionally deleting stored data.
