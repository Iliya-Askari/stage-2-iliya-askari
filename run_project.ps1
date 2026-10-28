param(
    [string]$Config = "config/default.json",
    [switch]$SkipBenchmark
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ is required and must be available as 'python'."
}
if (-not $env:DATABASE_URL) {
    throw "Set DATABASE_URL to a running local PostgreSQL database before starting."
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}
$pythonExe = (Resolve-Path -LiteralPath ".venv\Scripts\python.exe").Path
& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed." }
& $pythonExe -m pip install -e ".[test]"
if ($LASTEXITCODE -ne 0) { throw "Project installation failed." }

# Run stage one, load both datasets and schema, then execute the complete test suite.
& $pythonExe -m nyc311_factory --config $Config -v run
if ($LASTEXITCODE -ne 0) { throw "Stage-one data pipeline failed." }
& $pythonExe -m nyc311_factory --config $Config db-load
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL schema/data load failed." }
& $pythonExe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "The test suite failed." }

if (-not $SkipBenchmark) {
    New-Item -ItemType Directory -Force -Path "reports" | Out-Null
    & $pythonExe -m jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 `
        --output "dba_benchmark.executed.ipynb" --output-dir "reports" "notebooks/dba_benchmark.ipynb"
    if ($LASTEXITCODE -ne 0) { throw "The database benchmark notebook failed." }
}

Write-Host "Project pipeline, database load, and tests completed successfully."
