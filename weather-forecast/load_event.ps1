# Load a historical weather event (ERA5 reanalysis) into the app.
#   .\load_event.ps1 -Start 2005-08-23 -End 2005-08-31
param(
    [Parameter(Mandatory)][string]$Start,
    [Parameter(Mandatory)][string]$End
)

$Base   = "$env:USERPROFILE\WeatherForecast"
$Conda  = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
$Frames = "$Base\scripts\grib_to_frames.py"
$Grib   = "$Base\data\events\era5_$($Start)_$($End).grib"

Write-Host "=== 1/2 Fetching ERA5 reanalysis $Start .. $End ===" -ForegroundColor Cyan
if (Test-Path $Grib) {
    Write-Host "cached: $Grib"
} else {
    & $Conda run -n weather python "$Base\scripts\fetch_era5_event.py" --start $Start --end $End --out $Grib
    if ($LASTEXITCODE -ne 0) { throw "ERA5 fetch failed" }
}

Write-Host "=== 2/2 Rendering event frames ===" -ForegroundColor Cyan
Remove-Item "$Base\app\frames_event\*" -Recurse -Force -ErrorAction SilentlyContinue
# one process per variable keeps ecCodes/cfgrib memory bounded on big GRIBs
foreach ($var in "2t", "msl", "tcwv", "wind") {
    & $Conda run -n weather python $Frames $Grib --var $var --analysis --outdir "$Base\app\frames_event"
    if ($LASTEXITCODE -ne 0) { throw "frame rendering of $var failed" }
}
& $Conda run -n weather python $Frames $Grib --timeline --analysis --outdir "$Base\app\frames_event"
if ($LASTEXITCODE -ne 0) { throw "timeline generation failed" }

Write-Host "Done. Event ready in the app's History panel." -ForegroundColor Green
