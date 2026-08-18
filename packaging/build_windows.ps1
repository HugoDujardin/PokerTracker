<#
    Construit l'executable Windows 11 de PokerTracker.

    Utilisation (PowerShell, depuis la racine du depot):
        .\packaging\build_windows.ps1

    Resultat: dist\PokerTracker\PokerTracker.exe (dossier autonome, a copier
    tel quel sur une machine sans Python).
#>
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Environnement virtuel ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1

Write-Host "== Dependances ==" -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

Write-Host "== Tests ==" -ForegroundColor Cyan
python -m pytest

Write-Host "== Construction ==" -ForegroundColor Cyan
pyinstaller --noconfirm --clean packaging\pokertracker.spec

Write-Host "Termine: dist\PokerTracker\PokerTracker.exe" -ForegroundColor Green
