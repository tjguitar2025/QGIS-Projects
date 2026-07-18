# One-command local weather forecast pipeline.
#   .\run_forecast.ps1                          -> init today 00z (ECMWF open data), 144h forecast
#   .\run_forecast.ps1 -LeadTime 240
#   .\run_forecast.ps1 -Source cds -Date 20260704   -> ERA5 reanalysis init (lags ~6 days)
param(
    [string]$Date = "",
    [int]$LeadTime = 144,
    [ValidateSet("opendata", "cds")][string]$Source = "opendata"
)

if (-not $Date) {
    # ERA5 (cds) lags ~6 days behind real time; open data is same-day
    $Days = if ($Source -eq "cds") { -6 } else { 0 }
    $Date = (Get-Date).ToUniversalTime().AddDays($Days).ToString("yyyyMMdd")
}

$Base   = "$env:USERPROFILE\WeatherForecast"
$Conda  = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
$Grib   = "$Base\data\forecasts\fcnv2_$Date.grib"
$Frames = "$Base\scripts\grib_to_frames.py"

Write-Host "=== 1/2 FourCastNetv2 forecast: init $Date 00z ($Source), +$LeadTime h ===" -ForegroundColor Cyan
& $Conda run -n weather ai-models --input $Source --date $Date --time 0000 --lead-time $LeadTime `
    --assets "$Base\assets" --path $Grib fourcastnetv2-small
if ($LASTEXITCODE -ne 0) { throw "ai-models failed" }

Write-Host "=== 2/3 Fetching IFS precipitation (ECMWF open data) ===" -ForegroundColor Cyan
# FourCastNetv2 has no precip output; the precip layer uses the IFS forecast
# of the same cycle. Non-fatal: everything else works without it.
$TpGrib = "$Base\data\forecasts\tp_$Date.grib"
$HasTp = $false
if ($Source -eq "opendata") {
    & $Conda run -n weather python "$Base\scripts\fetch_opendata_tp.py" --date $Date --lead-time $LeadTime --out $TpGrib
    if ($LASTEXITCODE -eq 0) { $HasTp = $true }
    else { Write-Warning "IFS tp fetch failed - skipping the precipitation layer" }
}

Write-Host "=== 3/3 Rendering app frames ===" -ForegroundColor Cyan
# clear the previous run's frames so the app timeline matches this forecast
foreach ($try in 1..5) {
    Remove-Item "$Base\app\frames" -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path "$Base\app\frames")) { break }
    Start-Sleep -Seconds 2
}
New-Item -ItemType Directory -Force "$Base\app\frames" | Out-Null
# one process per variable keeps ecCodes/cfgrib memory bounded on big GRIBs
foreach ($var in "2t", "msl", "tcwv", "wind", "isobars") {
    & $Conda run -n weather python $Frames $Grib --var $var
    if ($LASTEXITCODE -ne 0) { throw "frame rendering of $var failed" }
}
$TimelineVars = "2t,msl,tcwv"
if ($HasTp) {
    & $Conda run -n weather python $Frames $TpGrib --var tp
    if ($LASTEXITCODE -ne 0) { throw "frame rendering of tp failed" }
    $TimelineVars = "2t,msl,tcwv,tp"
}
& $Conda run -n weather python $Frames $Grib --timeline --vars $TimelineVars
if ($LASTEXITCODE -ne 0) { throw "timeline generation failed" }

Write-Host "Done. Start the app with .\start_app.ps1 (http://localhost:8050)" -ForegroundColor Green
