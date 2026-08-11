# SpaceWeather — start the local server and open the app
$Base  = $PSScriptRoot
$Conda = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"

Write-Host "Starting SpaceWeather on http://localhost:8060 ..." -ForegroundColor Cyan
Start-Process "http://localhost:8060"
Set-Location $Base
& $Conda run --no-capture-output -n weather python -m uvicorn server:app --port 8060
