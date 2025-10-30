# Create virtual environment if missing
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

# Activate venv for current session
$activate = Join-Path ".venv" "Scripts\Activate.ps1"
. $activate

# Upgrade pip and install requirements
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
