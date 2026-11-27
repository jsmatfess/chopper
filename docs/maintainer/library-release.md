# Qualify the native libraries and CLI together

Use the same local candidate tag from clean, independent checkouts on native
Windows and Linux x86-64. Keep the intended release version in Cargo and the
Python extension. A local tag such as `v0.7.0-rc.1` can identify that source while
the wheel and application versions remain `0.7.0`.

The [qualification command](../../scripts/qualify-library-release.py) checks the
tag against HEAD, builds the locked CLI and wheel, and invokes the existing
[validation runner](../validation-runner.md#local-batch-execution). Give each
attempt a fresh output directory outside the checkout or under ignored `scratch/`.

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
  composed Job, CLI replay and concurrent cancellation.
- `cargo-packages/receipt.json` records the packaged crate set, the downstream
  lockfile and native host, and the ZIP resource checks. It covers the public
  crate, portable core, and the bundled ZIP, Deflate and JSON dependencies.
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
