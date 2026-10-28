param(
    [switch]$SkipNotebook
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Compose is required. Install Docker Desktop and retry."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ is required. Install Python and make it available as 'python'."
}
if (-not (Test-Path -LiteralPath "data/curated/case_level.csv")) {
    throw "Stage-one curated output is missing. Run the existing stage-one producer first."
}
if (-not (Test-Path -LiteralPath ".env")) {
    throw "Copy .env.example to .env and set a local PostgreSQL password first."
}

docker compose up -d --wait postgres
$envValues = @{}
Get-Content -LiteralPath ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)\s*$') { $envValues[$matches[1]] = $matches[2] }
}
$dbName = $envValues["POSTGRES_DB"]
$dbUser = [System.Uri]::EscapeDataString($envValues["POSTGRES_USER"])
$dbPassword = [System.Uri]::EscapeDataString($envValues["POSTGRES_PASSWORD"])
$dbPort = if ($envValues["POSTGRES_PORT"]) { $envValues["POSTGRES_PORT"] } else { "5432" }
$env:DATABASE_URL = "postgresql+psycopg://${dbUser}:${dbPassword}@localhost:${dbPort}/${dbName}"

python -m pip install -e ".[test]"
python -m nyc311_factory db-load
python -m pytest -q
if (-not $SkipNotebook) {
    New-Item -ItemType Directory -Force -Path "reports" | Out-Null
    python -m jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 `
        --output "dba_benchmark.executed.ipynb" --output-dir "reports" "notebooks/dba_benchmark.ipynb"
}
