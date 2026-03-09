# Check XAUUSD Data in PostgreSQL
# Run with: powershell -ExecutionPolicy Bypass -File check_data.ps1

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Checking XAUUSD Data in PostgreSQL" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if psql is available
try {
    $null = psql --version
} catch {
    Write-Host "PostgreSQL client (psql) not found!" -ForegroundColor Red
    Write-Host "Please install PostgreSQL or add it to PATH" -ForegroundColor Yellow
    exit 1
}

Write-Host "Connecting to PostgreSQL..." -ForegroundColor Yellow
Write-Host ""

# Query to check data
$query = @"
SELECT 
    symbol,
    timeframe,
    COUNT(*) as total_bars,
    MIN(datetime) as start_date,
    MAX(datetime) as end_date,
    MIN(low) as min_price,
    MAX(high) as max_price
FROM xauusd_ohlcv
WHERE symbol = 'XAUUSD' AND timeframe = 'M1'
GROUP BY symbol, timeframe;
"@

# Execute query
psql -U postgres -c $query

Write-Host ""
Write-Host "If you see data above, you're ready to go!" -ForegroundColor Green
Write-Host "If the table doesn't exist or is empty, you need to load data first." -ForegroundColor Yellow
Write-Host ""
