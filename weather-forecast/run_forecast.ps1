# One-command local weather forecast pipeline.
#   .\run_forecast.ps1              -> latest available ERA5 (6 days ago), 144h forecast
#   .\run_forecast.ps1 -Date 20260704 -LeadTime 240
param(
    [string]$Date = (Get-Date).ToUniversalTime().AddDays(-6).ToString("yyyyMMdd"),
    [int]$LeadTime = 144,
    [switch]$SkipGif
)

$Base   = "$env:USERPROFILE\WeatherForecast"
$Conda  = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
$QgisPy = "C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat"
$Grib   = "$Base\data\forecasts\fcnv2_$Date.grib"

Write-Host "=== 1/4 FourCastNetv2 forecast: init $Date 00z, +$LeadTime h ===" -ForegroundColor Cyan
& $Conda run -n weather ai-models --input cds --date $Date --time 0000 --lead-time $LeadTime `
    --assets "$Base\assets" --path $Grib fourcastnetv2-small
if ($LASTEXITCODE -ne 0) { throw "ai-models failed" }

Write-Host "=== 2/4 Converting variables to GeoTIFFs ===" -ForegroundColor Cyan
# clear previous run's tiffs so QGIS layers match this forecast
Remove-Item "$Base\data\geotiffs\*.tif" -ErrorAction SilentlyContinue
foreach ($var in "2t", "wind", "msl") {
    & $Conda run -n weather python "$Base\scripts\grib_to_geotiff.py" $Grib --var $var
    if ($LASTEXITCODE -ne 0) { throw "conversion of $var failed" }
}

Write-Host "=== 3/4 Rebuilding QGIS project ===" -ForegroundColor Cyan
& $QgisPy "$Base\scripts\build_qgis_project.py"
& $QgisPy "$Base\scripts\add_forecast_layers.py"

if (-not $SkipGif) {
    Write-Host "=== 4/4 Exporting GIF animation ===" -ForegroundColor Cyan
    & $QgisPy "$Base\scripts\export_animation.py" --var 2t
}

Write-Host "Done. Open $Base\qgis\weather_forecast.qgz" -ForegroundColor Green
