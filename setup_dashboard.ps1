# QuantFund Dashboard Setup Script for Windows
# Run with: powershell -ExecutionPolicy Bypass -File setup_dashboard.ps1

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "QuantFund XAUUSD Dashboard Setup" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow
Write-Host ""

# Check Rust
try {
    $rustVersion = cargo --version
    Write-Host "Rust found: $rustVersion" -ForegroundColor Green
} catch {
    Write-Host "Rust is not installed. Please install from https://rustup.rs/" -ForegroundColor Red
    exit 1
}

# Check Node.js
try {
    $nodeVersion = node --version
    Write-Host "Node.js found: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "Node.js is not installed. Please install from https://nodejs.org/" -ForegroundColor Red
    exit 1
}

# Check PostgreSQL
try {
    $pgVersion = psql --version
    Write-Host "PostgreSQL found: $pgVersion" -ForegroundColor Green
} catch {
    Write-Host "PostgreSQL client not found. Make sure PostgreSQL is installed and running." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Yellow
Write-Host ""

# Install frontend dependencies
Set-Location dashboard
Write-Host "Installing Node.js dependencies..." -ForegroundColor Cyan
npm install

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Ensure PostgreSQL is running with XAUUSD data loaded" -ForegroundColor White
    Write-Host "2. Run: cd dashboard; npm run tauri dev" -ForegroundColor White
    Write-Host ""
    Write-Host "For production build: npm run tauri build" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Setup failed. Please check the errors above." -ForegroundColor Red
    exit 1
}
