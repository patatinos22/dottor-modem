$ErrorActionPreference = "Stop"
Write-Host "Creazione DottorModem.exe..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --onefile --windowed --uac-admin `
  --name "DottorModem" `
  --add-data "ui;ui" --add-data "core;core" `
  --hidden-import customtkinter --hidden-import speedtest --hidden-import psutil `
  main_optimizer.py
if ($LASTEXITCODE -eq 0) {
    Write-Host "`nEXE creato: dist\DottorModem.exe" -ForegroundColor Green
    Write-Host "  Dimensione: $([math]::Round((Get-Item dist\DottorModem.exe).Length/1MB,1)) MB" -ForegroundColor Gray
}
