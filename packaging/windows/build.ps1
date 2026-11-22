# Builds the Windows installer. Run from the repo root in PowerShell (CI does exactly this).
# Needs: Python 3.11 (with tkinter) on PATH, Node 20+, Inno Setup (iscc) on PATH.
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root
$version = (Get-Content VERSION).Trim()

Write-Host "== frontends"
foreach ($app in @("apps\buildings\frontend", "apps\terrain\frontend")) {
  Push-Location $app
  npm ci
  npm run build
  Pop-Location
}

Write-Host "== update package"
python packaging\make_release.py
if ($LASTEXITCODE -ne 0) { throw "make_release failed" }

Write-Host "== stage installer files"
$stage = "build\stage"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force "$stage\launcher", "$stage\app" | Out-Null
# 1) the runtime: a full CPython 3.11 (venv, pip, tkinter) copied from the machine that builds
$pyHome = python -c "import sys; print(sys.base_prefix)"
Copy-Item -Recurse $pyHome "$stage\runtime"
# 2) launcher + the code that ships with this version (an update zip unpacked)
Copy-Item launcher\launcher.py "$stage\launcher\"
Expand-Archive "dist\world-studio-app-$version.zip" "$stage\app"

Write-Host "== installer"
iscc /DAppVersion=$version packaging\windows\installer.iss
Write-Host "Done: dist\WorldStudio-Setup-$version.exe  and  dist\world-studio-app-$version.zip(.sha256)"
