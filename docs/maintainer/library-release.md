# Qualify the native libraries and CLI together

Use the same local candidate tag from clean, independent checkouts on native
Windows and Linux x86-64. Keep the intended release version in Cargo and the
Python extension. A local tag such as `v0.7.0-rc.1` can identify that source while
the wheel and application versions remain `0.7.0`.

The [qualification command](../../scripts/qualify-library-release.py) checks the
tag against HEAD, builds the locked CLI and wheel, and invokes the existing
[validation runner](../validation-runner.md#local-batch-execution). Give each
attempt a fresh output directory outside the checkout or under ignored `scratch/`.
Retry a failed qualification from the entry point with a fresh directory so
the previous package staging tree, installed environment and logs are retained.

## Windows x86-64

Use native MSVC Rust, the Microsoft C++ Build Tools and a 64-bit, GIL-enabled
CPython 3.11 or newer. Select an independent NTFS checkout using the
[Windows and WSL workflow](../windows-wsl-workflow.md).

```powershell
python -m venv C:\chopper-tools\wheel-builder
$env:PATH = "C:\chopper-tools\wheel-builder\Scripts;$env:PATH"
python -m pip install "maturin==1.16.0"
python scripts/qualify-library-release.py v0.7.0-rc.1 C:\chopper-evidence\library-070-windows
```

The downstream Cargo smoke runs in a default-stack MSVC executable. The wheel
smoke runs inside the installed Windows Python process. Run both with the
checked-out native CLI binary the qualifier built from the candidate.

## Linux x86-64 and glibc 2.28

Run inside the official [manylinux_2_28 x86-64 image](https://github.com/pypa/manylinux/tree/main#manylinux_2_28-almalinux-8-based)
using its CPython 3.11 and a pinned stable `x86_64-unknown-linux-gnu` Rust
toolchain. Keep the image repository digest with the candidate record. The
qualifier measures the running glibc and requires 2.28. It requests Maturin's
`manylinux_2_28` compatibility tag and `--auditwheel check`, then installs and
tests the generated wheel on that baseline.

```sh
source_checkout=/absolute/clean/candidate-clone
rust_toolchain=/absolute/pinned/rust-toolchain
record_directory=/absolute/library-candidate-evidence
image=quay.io/pypa/manylinux_2_28_x86_64@sha256:FULL_IMAGE_DIGEST
mkdir -p "$record_directory"
docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env CARGO_HOME=/tmp/cargo \
  --mount "type=bind,src=$source_checkout,dst=/source,readonly" \
  --mount "type=bind,src=$rust_toolchain,dst=/rust,readonly" \
  --mount "type=bind,src=$record_directory,dst=/evidence" \
  --workdir /source "$image" bash -ec '
    export PATH=/rust/bin:/opt/python/cp311-cp311/bin:$PATH
    git config --global --add safe.directory /source
    python -m venv /tmp/wheel-builder
    /tmp/wheel-builder/bin/python -m pip install "maturin==1.16.0"
    export PATH=/tmp/wheel-builder/bin:$PATH
    /opt/python/cp311-cp311/bin/python scripts/qualify-library-release.py "$1" /evidence/linux
  ' bash v0.7.0-rc.1
```

Point `source_checkout` to a clone with its own Git metadata and the candidate
tag. A linked Git worktree requires Git metadata outside the mounted checkout.
Use the installed Rust toolchain directory containing `bin` and `lib`, and keep
the same compiler release selected for the candidate's other builds.

## Review the receipts

- `qualification.json` records the candidate tag, commit and tree, platform,
  tool versions, test inputs and commands. `status.json` records each attempt,
  each declared artifact's SHA-256 and size, and the final count of passed steps.
  Keep the numbered stdout and stderr logs with the artifacts.
- `wheels/` contains the exact wheel installed into the fresh `installed/`
  environment. Qualification checks the version, `cp311-abi3` platform tag and
  byte-for-byte license and notice payloads. The installed tests cover the
  composed Job, CLI replay, concurrent cancellation, calculated columns, input
  probes, and manifest streaming for plain, gzip and ZIP output.
- `cargo-packages/receipt.json` records the packaged crate set, the downstream
  lockfile and native host, and the ZIP resource checks. The downstream caller
  exercises input probes and reads the published manifest. Qualification covers
  the public crate, portable core, and the bundled ZIP, Deflate and JSON dependencies.
- The native CLI's version, generated reference, quickstart and other recipes,
  output manifests, and prior-release Jobs are checked against that candidate
  executable. The package and wheel tests also check row conservation, group
  membership, actual CSV byte caps and the manifests.

Review both platform receipts together and require matching candidate commits,
trees and distribution versions. Check the `chopper-csv` name and version on
crates.io and PyPI and the supporting crate names and versions on crates.io.
Review upstream licenses, [installation instructions](../user/libraries.md),
the [local delivery gate](../ci.md) and [release archive evidence](../release-packaging.md)
before approving publication. Record qualification and publication in the
[release record](https://github.com/jsmatfess/chopper/releases) and
[#122](https://github.com/jsmatfess/chopper/issues/122).

## Preview and publish the native library distributions

From the clean checkout at the qualified candidate, supply the retained Linux
and Windows qualification directories. The paths can point to a container bind
mount on Linux and a native Windows drive mounted in WSL.

```sh
python3 scripts/publish-library-release.py v0.7.0-rc.3 \
  --linux /absolute/qualification/linux \
  --windows /mnt/c/chopper-evidence/library-070-windows
```

The default preview checks both platform receipts and the runner's latest
successful attempts. It checks the SHA-256 of each wheel against the build
and installed-wheel records and requires the five qualified Cargo archives
to match across platforms. The JSON result reports which versions and wheel
files are pending or already present with the same bytes.

Land the candidate through the [local delivery gate](../ci.md). Put the final
`v<version>` tag on the approved qualified commit locally and on GitHub. For publication,
use a Python 3.11+ environment with Twine installed. Supply the corresponding
release credentials through `CARGO_REGISTRY_TOKEN` and `TWINE_USERNAME=__token__`
with `TWINE_PASSWORD` in the publishing environment for pending uploads. The
tokens need permission to create the projects on the first release.

Run the same command with `--publish` and retain its JSON result with the
qualification records. The publisher checks the final tag and reachability
from GitHub main and runs Twine's offline metadata check on pending wheels
before uploading. It sends the verified Cargo tarballs in
dependency order and waits for their checksums to appear in the registry index.
It then passes the exact verified wheels to Twine. [Cargo registry publish API](https://doc.rust-lang.org/cargo/reference/registry-web-api.html#publish) · [Twine upload](https://twine.readthedocs.io/en/stable/index.html#twine-upload)

After a partial release, repeat preview and then `--publish` with the same
qualified artifacts. Existing artifacts with identical checksums are reused.
If an upload response is lost, the publisher checks the index before asking
for a retry.
An unexpected PyPI file, yanked version or different checksum stops the release.
The tooling CI job runs offline publication simulations. Live publication runs
as an explicit local command after final tag approval.
