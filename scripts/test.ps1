# Activate venv if present
if (Test-Path ".venv") {
  $activate = Join-Path ".venv" "Scripts\Activate.ps1"
  . $activate
}

python -m pytest -q