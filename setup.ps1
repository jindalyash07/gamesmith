# One-time setup for GameSmith on Windows. Run from the repo root:  .\setup.ps1
# If scripts are blocked:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
$ErrorActionPreference = "Stop"

Write-Host "Checking prerequisites..."
node -v
python --version

Write-Host "`nCreating virtual environment..."
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet

Write-Host "`nInstalling and building the verifier..."
npm install --prefix verifier --silent
npm run build --prefix verifier
npm test --prefix verifier

Write-Host "`nRunning harness tests..."
& .\.venv\Scripts\python.exe -m pytest -q

Write-Host "`nSandbox mode:"
& .\.venv\Scripts\python.exe -c "from harness.gates import permission_mode; m = permission_mode(); print(m, '(Node permission model active)' if m != 'off' else '(WARNING: upgrade to Node 22+ for the permission model)')"

Write-Host "`nDone. Activate with:  .venv\Scripts\Activate.ps1"
