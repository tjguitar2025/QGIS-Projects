# Start the local weather app and open it in the browser.
$Base  = "$env:USERPROFILE\WeatherForecast"
$Conda = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"

# already running? just open the browser
try {
    Invoke-WebRequest "http://localhost:8050/api/run-status" -UseBasicParsing -TimeoutSec 2 | Out-Null
    Start-Process "http://localhost:8050"
    Write-Host "Local Weather already running at http://localhost:8050" -ForegroundColor Green
    return
} catch { }

$server = Start-Process -FilePath $Conda `
    -ArgumentList "run", "-n", "weather", "python", "$Base\server.py" `
    -WindowStyle Hidden -PassThru

# wait for the server to come up (max ~15s)
$up = $false
foreach ($i in 1..30) {
    try {
        Invoke-WebRequest "http://localhost:8050/api/run-status" -UseBasicParsing -TimeoutSec 1 | Out-Null
        $up = $true; break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $up) { Write-Warning "Server did not respond on port 8050 (PID $($server.Id))" }

Start-Process "http://localhost:8050"
Write-Host "Local Weather running at http://localhost:8050  (server PID $($server.Id))" -ForegroundColor Green
Write-Host "Stop it with:  Stop-Process -Id $($server.Id)"
