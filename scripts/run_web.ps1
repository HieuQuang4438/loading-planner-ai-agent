# Load .env into this process (variables already set win), seed the admin if absent, then start the web app.
#   .\scripts\run_web.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Parsed by python-dotenv, as the app does (quotes, escapes, inline comments).
if (Test-Path (Join-Path $root ".env")) {
    $values = python -c "import json; from dotenv import dotenv_values; print(json.dumps(dotenv_values('.env')))" | ConvertFrom-Json
    foreach ($p in $values.PSObject.Properties) {
        if ($null -ne $p.Value -and -not [Environment]::GetEnvironmentVariable($p.Name, "Process")) {
            [Environment]::SetEnvironmentVariable($p.Name, $p.Value, "Process")
        }
    }
}

python -m src.web.users seed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m src.web
