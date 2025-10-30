param(
  [int]$Port = 8000,
  [string]$BindAddress = "0.0.0.0",
  [switch]$Reload
)

# Activate venv if present
if (Test-Path ".venv") {
  $activate = Join-Path ".venv" "Scripts\Activate.ps1"
  . $activate
}

$reloadArg = if ($Reload) { "--reload" } else { "" }

# Run uvicorn via module to avoid PATH issues
python -m uvicorn --app-dir src app.main:app --host $BindAddress --port $Port $reloadArg
