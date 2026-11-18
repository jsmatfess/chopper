$CargoArgs = $args
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (Test-Path (Join-Path $root '.tools/cargo/bin/cargo.exe')) {
    $env:RUSTUP_HOME = Join-Path $root '.tools/rustup'
    $env:CARGO_HOME = Join-Path $root '.tools/cargo'
    $env:PATH = "$(Join-Path $root '.tools/cargo/bin');$(Join-Path $root '.tools/mingw64/bin');$env:PATH"
}
& cargo @CargoArgs
exit $LASTEXITCODE
