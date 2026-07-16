# Create a "Local Weather" desktop shortcut that starts the app in one double-click.
$Base = "$env:USERPROFILE\WeatherForecast"
$desktop = [Environment]::GetFolderPath('Desktop')

$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$desktop\Local Weather.lnk")
$lnk.TargetPath       = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$lnk.Arguments        = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Base\start_app.ps1`""
$lnk.WorkingDirectory = $Base
$lnk.IconLocation     = "$Base\app\weather.ico,0"
$lnk.Description      = "Local Weather - open the forecast app"
$lnk.WindowStyle      = 7   # minimized
$lnk.Save()

Write-Host "Created $desktop\Local Weather.lnk" -ForegroundColor Green
