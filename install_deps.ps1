# QuantFund - Install Dependencies Only
# Run with: powershell -ExecutionPolicy Bypass -File install_deps.ps1

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "QuantFund - Installing Dependencies" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check Node.js
try {
    $nodeVersion = node --version
    Write-Host "Node.js found: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "Node.js is not installed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Installing Node.js dependencies..." -ForegroundColor Yellow
Write-Host ""

# Install frontend dependencies
Set-Location dashboard
npm install

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Dependencies installed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "To run the dashboard:" -ForegroundColor Cyan
    Write-Host "  npm run tauri dev" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Installation failed!" -ForegroundColor Red
    exit 1
}
