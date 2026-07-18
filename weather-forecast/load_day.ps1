# Load a single historical day (hourly ERA5 reanalysis) into the app.
#   .\load_day.ps1 -Date 2025-07-30
# Renders temperature + precipitation + wind + pressure/isobars at hourly resolution into
# app\frames_event (shares the event playback machinery in the frontend).
# Rendered frames are kept in data\day_cache\<date>; revisiting a day is a
# file copy instead of a CDS download + render.
param(
    [Parameter(Mandatory)][string]$Date
)

$Base   = "$env:USERPROFILE\WeatherForecast"
$Conda  = "$env:USERPROFILE\miniconda3\Scripts\conda.exe"
$Frames = "$Base\scripts\grib_to_frames.py"
$Grib   = "$Base\data\events\era5_day_$Date.grib"
$Cache  = "$Base\data\day_cache\$Date"
$Out    = "$Base\app\frames_event"

function Clear-FramesDir {
    # remove the whole dir with retries: a plain wildcard delete can stop silently
    # if the server is mid-serving a frame, leaving stale frames behind
    foreach ($try in 1..5) {
        Remove-Item $Out -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $Out)) { break }
        Start-Sleep -Seconds 2
    }
    New-Item -ItemType Directory -Force $Out | Out-Null
}

if (Test-Path "$Cache\timeline.json") {
    Write-Host "=== Cached day found - restoring frames for $Date ===" -ForegroundColor Cyan
    Clear-FramesDir
    Copy-Item "$Cache\*" $Out -Recurse -Force
    Write-Host "Done (from cache). Day ready in the app's History panel." -ForegroundColor Green
    exit 0
}

Write-Host "=== 1/2 Fetching hourly ERA5 reanalysis for $Date ===" -ForegroundColor Cyan
if (Test-Path $Grib) {
    Write-Host "cached: $Grib"
} else {
    & $Conda run -n weather python "$Base\scripts\fetch_era5_event.py" `
        --start $Date --end $Date --hourly --vars 2t,tp,wind,msl --out $Grib
    if ($LASTEXITCODE -ne 0) { throw "ERA5 fetch failed" }
}

Write-Host "=== 2/2 Rendering day frames (5 layers in parallel) ===" -ForegroundColor Cyan
Clear-FramesDir
# one process per variable keeps ecCodes/cfgrib memory bounded on big GRIBs;
# the processes run concurrently (msl + isobars share a field - the shared
# .idx race is benign, cfgrib rebuilds it)
$procs = @()
foreach ($var in "2t", "tp", "wind", "msl", "isobars") {
    $procs += Start-Process -FilePath $Conda -PassThru -NoNewWindow `
        -ArgumentList "run", "-n", "weather", "python", $Frames, $Grib,
                      "--var", $var, "--analysis", "--outdir", $Out
}
# cache each handle or .ExitCode reads back null after the process exits
foreach ($p in $procs) { $null = $p.Handle }
foreach ($p in $procs) { $p.WaitForExit() }
foreach ($p in $procs) {
    if ($p.ExitCode -ne 0) { throw "frame rendering failed (exit $($p.ExitCode))" }
}
& $Conda run -n weather python $Frames $Grib --timeline --analysis --vars 2t,tp,msl --outdir $Out
if ($LASTEXITCODE -ne 0) { throw "timeline generation failed" }

# cache the rendered day for instant reloads later
Remove-Item $Cache -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Cache | Out-Null
Copy-Item "$Out\*" $Cache -Recurse -Force

# the frames cache supersedes the raw GRIB (~190 MB/day) - drop it and its .idx
Remove-Item "$Grib*" -Force -ErrorAction SilentlyContinue

Write-Host "Done. Day ready in the app's History panel." -ForegroundColor Green
