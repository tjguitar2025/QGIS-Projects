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

Write-Host "=== 2/2 Rendering app frames ===" -ForegroundColor Cyan
# clear the previous run's frames so the app timeline matches this forecast
Remove-Item "$Base\app\frames\*" -Recurse -Force -ErrorAction SilentlyContinue
# one process per variable keeps ecCodes/cfgrib memory bounded on big GRIBs
foreach ($var in "2t", "msl", "tcwv", "wind") {
    & $Conda run -n weather python $Frames $Grib --var $var
    if ($LASTEXITCODE -ne 0) { throw "frame rendering of $var failed" }
}
& $Conda run -n weather python $Frames $Grib --timeline
if ($LASTEXITCODE -ne 0) { throw "timeline generation failed" }

Write-Host "Done. Start the app with .\start_app.ps1 (http://localhost:8050)" -ForegroundColor Green
