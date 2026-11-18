# WSL development and native Windows measurements

Use two independent checkouts. Keep everyday Linux development under
`~/git/chopper` on WSL's Linux filesystem, and native Windows builds and
measurements in a Windows drive checkout such as `C:\src\chopper` on NTFS.
The Windows checkout can also remain at its existing location. Microsoft
[recommends keeping files on the toolchain's filesystem](https://learn.microsoft.com/en-us/windows/wsl/filesystems).

The editor can run on Windows with its WSL integration; Git, Rust, Node and
Graphify for the development checkout run in Linux. Keep each checkout's
`target`, `.tools`, `ui/node_modules` and `ui/dist` independent. Do not use a Git
worktree whose Git metadata lives across the filesystem boundary, or share these
build/cache directories through symlinks. A native Windows process reading
`\\wsl.localhost\...` would introduce the filesystem bridge into its workload.

## Shared local server ports

Linux browser CI and native Windows browser acceptance can bind the same fixed
local origins through WSL localhost forwarding. Serialize the complete Linux
browser job, including its owned-server cleanup, with Windows browser acceptance;
source work and Linux checks that do not bind those origins can continue in
parallel. The selected SMALL origins come from `ORIGIN_PORTS` in
`scripts/browser-small-runner.py`. Before a new attempt after a bind rejection,
observe the complete selected port set and inspect ownership; a free port does
not identify its historical listener, and unrelated listeners must not be killed.

## Line endings

The repository's `.gitattributes` keeps ordinary text LF in the index and in both
Windows and Linux checkouts, regardless of `core.autocrlf`. Batch files use CRLF;
CSV fixtures, evidence and vendor/history paths marked `-text` retain their exact
bytes. Editors should save ordinary text as LF. Scope these rules to this repo;
other repositories can keep their own policies.

After this policy is merged, new clones use it immediately. For an existing
checkout, first commit or preserve local edits, then update to the merged revision.
If older CRLF working files remain, re-check out only clean files after confirming
there are no local edits to lose. Do not run a blanket reset or normalization over
a dirty checkout. `git ls-files --eol` shows index/worktree line endings and
`git check-attr text eol -- <path>` explains the selected rule.

## Set up Linux development after merging current work

Keep the existing Windows checkout and all local changes until they are safely
committed and merged. Do not reset, clean, or copy its virtual environments into
Linux. After the intended changes reach the remote, open a WSL terminal:

```sh
mkdir -p ~/git
git -c core.autocrlf=false clone https://github.com/jsmatfess/chopper.git ~/git/chopper
cd ~/git/chopper
git config --local core.autocrlf false
source "$HOME/.cargo/env"
rustc -Vv
cargo --version
node --version
python3 --version
cc --version
rustup component add rustfmt clippy
rustup target add wasm32-unknown-unknown wasm32-wasip1
npm --prefix ui ci
```

Install Linux Rust using [rustup](https://rust-lang.org/tools/install/) if absent;
Node must be 22.5+ for Context Mode, with Python 3.10+ and a C compiler for
Graphify and the native Zstandard build. This machine's user-level Rust and Node
installations survive a new checkout; repository-local `.tools` do not.
The [browser guide](browser.md#local-development) owns WASI SDK 33 and browser
prerequisites; a WASM target alone does not install that C toolchain or Chromium.

Recreate the local [Graphify environment and graph](graphify.md#install-on-linux--wsl)
in the new checkout, then re-register its MCP server with the new absolute paths.
User-level RTK, Context Mode and Matt Pocock's plugin remain installed in the same
WSL user. Run `rtk init --codex --show`, `codex mcp list` and
`context-mode doctor`; follow the [Context Mode policy](context-mode.md) for its
intentional missing-hook diagnostics. The repository's `.agents/skills` carries
the benchmark skill once that revision is checked out; avoid installing duplicate
copies if the client already discovers it. Restart the assistant in the new WSL
checkout to load project instructions, skills and MCP paths.

Use the ordinary checks from [CONTRIBUTING](../CONTRIBUTING.md). Linux tests and
timings establish Linux/WSL coverage; Windows-specific paths still need Windows
checks. When temporarily compiling Linux from a Windows-drive checkout, set
`CARGO_TARGET_DIR` to a Linux filesystem directory to avoid sharing Windows build
outputs. That transitional arrangement still pays source-file bridge overhead.

## Native Windows prerequisites

Install Windows Git, Python, stable MSVC Rust, Microsoft C++ Build Tools with the
Windows SDK, and Windows Node 22+. Rust uses `x86_64-pc-windows-msvc` on this x64
machine. Do not use Linux Cargo to produce the benchmark executable. Native
Windows [rustup prerequisites](https://rust-lang.org/tools/install/#windows-considerations)
include the Microsoft build tools; the Rust installer alone is insufficient.

For a new machine, these PowerShell commands install the C++ prerequisites and
Node (the Build Tools installer can require Windows elevation):

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget --accept-package-agreements --accept-source-agreements --override "--wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
winget install --id OpenJS.NodeJS.LTS --exact --source winget
```

Install Windows Rust using the official x64 rustup installer and select stable
MSVC. In a fresh Windows terminal, run `rustup component add rustfmt clippy` and
`rustup target add wasm32-unknown-unknown`. Use a real Windows Python interpreter,
not a Microsoft Store launcher alias, for recorded validation batches.

The launcher below discovers Windows PATH tools, the existing repository-local
Windows Rust layout, user-level `.cargo/bin`, and the portable Windows Node
22.23.4 installation under `%LOCALAPPDATA%\Chopper\tools`. It prefers the installed
Python 3.14 interpreter under `%LOCALAPPDATA%\Python\pythoncore-3.14-64`.
For another location, set `CHOPPER_WINDOWS_PYTHON` to its full Windows executable
path. Optional `CHOPPER_WINDOWS_CARGO`, `CHOPPER_WINDOWS_NODE`, and equivalent
tool-name overrides select other explicit executables. Overrides set in the WSL shell are explicitly forwarded as Windows paths;
no WSLENV registration is needed. Their directories precede defaults in the
child PATH. An explicit Cargo selection does not select checkout-local Rust homes;
explicit Windows CARGO_HOME/RUSTUP_HOME settings still apply. These selections
change only the child environment, without changing machine security settings. Use matching compiler/build flags for baseline and candidate.

## Dispatch native jobs from WSL

After these scripts exist in the Windows checkout, use its absolute mounted path:

```sh
python3 scripts/windows-native.py --checkout /mnt/c/src/chopper doctor
python3 scripts/windows-native.py --checkout /mnt/c/src/chopper \
  --expect-commit "$(git rev-parse HEAD)" cargo -- build --release --locked -p chopper --bin chopper
python3 scripts/windows-native.py --checkout /mnt/c/src/chopper \
  --expect-commit "$(git rev-parse HEAD)" cargo -- test --workspace --locked
python3 scripts/windows-native.py --checkout /mnt/c/src/chopper \
  --expect-commit "$(git rev-parse HEAD)" python -- scripts/local-ci.py check
```

From a native Windows terminal, the same Python entry point accepts
`--checkout C:\src\chopper` and executes directly without the WSL bridge.

Substitute the actual Windows checkout path. `doctor` reports native tool paths,
versions, revision, dirty-path count and C++ Build Tools discovery, returning
nonzero for missing prerequisites. It is a discovery check, not build acceptance;
compile and run a native executable to verify linker/SDK/application-policy access.
The launcher also accepts `python`, `node` and `npm`. All command arguments after
the tool name are passed to that tool. Use Windows paths or paths relative to the
Windows checkout in those arguments; `/mnt/c/...` is translated only for
`--checkout`. Spaces, quotes and shell metacharacters are transported as JSON data
and passed as a native argument array, without a command-shell evaluation step.
The PowerShell transport binds the encoded request once and reuses that value.
Before dispatch, the parent rejects a command exceeding the Windows
[32,767 UTF-16 unit limit, including its terminator](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw#parameters).

For the temporary [local CI gate](ci.md), install native Windows act in that
checkout or on its Windows PATH. `local-ci.py check` executes the workflow's
Windows profile directly on Windows, using Git Bash instead of system32's WSL
`bash.exe` launcher. It records the committed revision and base in a Windows
receipt. Configure `chopper.windowsCheckout` in the WSL delivery repository to
that checkout's mounted path; the merge gate reads the matching receipt without
sharing build directories or rewriting either checkout. Linux checks still run
in the WSL checkout. Dirty Windows inputs must be preserved; use a separate clean
validation clone when updating the existing checkout would overwrite local work.

The dispatcher launches Windows PowerShell commands and Windows Python, restores
Windows PATH/PATHEXT for that child, and uses the selected Windows checkout as
the native working directory. It does not change PowerShell execution policy.
It rejects WSL UNC checkout paths. Native child exit codes propagate back to WSL.
An ordinary nonzero child exit reports that status; it is not evidence of a
sandbox or interop failure. The transport also disables Git's optional index
refresh before invoking an older frozen dispatcher.
If an agent sandbox reports `UtilBindVsockAnyPort` or prevents Windows process
launch, run the same dispatcher with the host's approved interop access; do not
interpret an unstarted job as a test failure or passing Windows coverage.

Executions require a clean Windows checkout unless `--allow-dirty` is explicitly
provided. Revision and cleanliness checks disable Git's optional index refresh
to preserve the checkout's sealed index metadata. Dirty runs must retain the
complete relevant source identities;
`--expect-commit` alone cannot identify an uncommitted build. The launcher never
fetches, checks out branches, merges, or resets either checkout automatically.
For long unattended jobs, dispatch the existing
[validation runner](validation-runner.md) with declared deadlines, inputs,
toolchains and artifacts; its process containment and resume rules still apply.
The dispatcher is a synchronous launcher, not an unattended-job controller.

## Transfer revisions and measure

Commit a bounded change on the WSL development branch and push that branch to
GitHub when authorized. Fetch and check out the exact commit in a clean Windows
checkout using native Windows Git. A local `git bundle` can transfer committed
work without pushing. For commits ahead of `origin/main`, create the bundle in
WSL and copy it once to a Windows staging directory outside the timed job:

```sh
git bundle create /tmp/chopper-handoff.bundle origin/main..HEAD
git rev-parse HEAD
# Copy the bundle to a chosen Windows staging path, then use native Windows Git.
```

In the clean Windows checkout, verify the prerequisites and fetch the bundle:

```powershell
git fetch origin main
git bundle verify C:\staging\chopper-handoff.bundle
git fetch C:\staging\chopper-handoff.bundle HEAD
git switch --detach FETCH_HEAD
git rev-parse HEAD
```

Compare the full commit hashes before building. If the desired revision already
exists on the remote, fetching that revision is sufficient; no bundle is needed.
Do not share Git metadata or continuously synchronize working files. Keep both checkouts' line-ending rules governed by `.gitattributes`;
preserve benchmark evidence bytes and include both vendored codec directories in
fresh build provenance.

For frozen artifacts transferred to another machine, use an authenticated private
route and verify the exact received sizes and hashes before execution. Windows
[Taildrop](https://tailscale.com/docs/features/taildrop?tab=windows) automatically
saves received files in the user's Downloads directory; an empty CLI inbox does
not prove a transfer failed. Check the exact expected filename before resending,
preserve failed receipts, and account for retained copies at both locations.

Build and retain separate baseline/candidate Windows executables. Use an eligible
[Windows benchmark harness](../scripts/benchmark-windows.py) and the
[benchmark guide](benchmarks/README.md), declaring the smallest useful experiment
before launching it. For example, after preparing binaries and choosing a new
output path, dispatch the harness through Windows Python:

```sh
python3 scripts/windows-native.py --checkout /mnt/c/src/chopper \
  --expect-commit "$(git rev-parse HEAD)" python -- scripts/benchmark-windows.py \
  --baseline scratch/windows-calibration/baseline.exe \
  --candidate scratch/windows-calibration/candidate.exe \
  --work-dir scratch/windows-calibration \
  --output scratch/windows-calibration/new-pass.jsonl
```

This is an invocation example, not authorization to run its default matrix.
Keep fixture, temp, staging and output paths on the intended native NTFS volume;
never use WSL UNC paths for measured data. The Windows harness measures the
Windows child; WSL dispatch/startup and subsequent result copying are outside that
measurement boundary. Preserve raw logs, failures, binary/source/fixture hashes,
toolchains, actual resource settings, warm/cold-cache treatment and host context.
Compare alternating baseline/candidate jobs within Windows. Do not pool WSL and
Windows observations or infer physical SSD I/O from logical/process counters.

Pause other builds and heavy WSL work during timed runs. Shutting down WSL is
optional when a predeclared Windows-only run needs tighter isolation; it also
ends the WSL agent/launcher, so launch that run from Windows first and retrieve
results after restarting WSL. There is no automatic shutdown or cache eviction.
Windows application-control denials remain platform blockers under the
[README policy](../README.md#start); these helpers never change security settings.

Verify launcher changes with `python3 scripts/test-windows-native.py` and a native
`doctor`, argument/exit-code round trip and tiny compile/run on the Windows host.
No performance claim follows from those setup smoke checks.
