# Run the repository-local Graphify CLI without model backends.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $repoRoot '.tools/graphify/venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Graphify is not installed. See docs/graphify.md for setup.'
}
$previousBackend = $env:GRAPHIFY_BACKEND
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:GRAPHIFY_BACKEND = 'none'
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location $repoRoot
    try {
        & $python -m graphify @args
        $result = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:GRAPHIFY_BACKEND = $previousBackend
    $env:PYTHONIOENCODING = $previousEncoding
}
exit $result
