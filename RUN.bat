@echo off
echo ==========================================
echo QuantFund XAUUSD Dashboard
echo ==========================================
echo.

echo Checking data...
powershell -ExecutionPolicy Bypass -File check_data.ps1

echo.
echo Installing dependencies...
powershell -ExecutionPolicy Bypass -File install_deps.ps1

echo.
echo Starting dashboard...
cd dashboard
npm run tauri dev
