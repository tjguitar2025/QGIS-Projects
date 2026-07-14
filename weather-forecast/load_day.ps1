# Load a single historical day (hourly ERA5 reanalysis) into the app.
#   .\load_day.ps1 -Date 2025-07-30
# Renders temperature + precipitation + wind at hourly resolution into
# app\frames_event (shares the event playback machinery in the frontend).
param(
    [Parameter(Mandatory)][string]$Date
)

$Base   = "$env:USERPROFILE\WeatherForecast"
$Conda  = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
$Frames = "$Base\scripts\grib_to_frames.py"
$Grib   = "$Base\data\events\era5_day_$Date.grib"

Write-Host "=== 1/2 Fetching hourly ERA5 reanalysis for $Date ===" -ForegroundColor Cyan
if (Test-Path $Grib) {
    Write-Host "cached: $Grib"
} else {
    & $Conda run -n weather python "$Base\scripts\fetch_era5_event.py" `
        --start $Date --end $Date --hourly --vars 2t,tp,wind --out $Grib
    if ($LASTEXITCODE -ne 0) { throw "ERA5 fetch failed" }
}

Write-Host "=== 2/2 Rendering day frames ===" -ForegroundColor Cyan
# remove the whole dir with retries: a plain wildcard delete can stop silently
# if the server is mid-serving a frame, leaving stale frames behind
foreach ($try in 1..5) {
    Remove-Item "$Base\app\frames_event" -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path "$Base\app\frames_event")) { break }
    Start-Sleep -Seconds 2
}
New-Item -ItemType Directory -Force "$Base\app\frames_event" | Out-Null
# one process per variable keeps ecCodes/cfgrib memory bounded on big GRIBs
foreach ($var in "2t", "tp", "wind") {
    & $Conda run -n weather python $Frames $Grib --var $var --analysis --outdir "$Base\app\frames_event"
    if ($LASTEXITCODE -ne 0) { throw "frame rendering of $var failed" }
}
& $Conda run -n weather python $Frames $Grib --timeline --analysis --vars 2t,tp --outdir "$Base\app\frames_event"
if ($LASTEXITCODE -ne 0) { throw "timeline generation failed" }

Write-Host "Done. Day ready in the app's History panel." -ForegroundColor Green
