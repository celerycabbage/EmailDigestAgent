param(
    [string]$TaskName = "EmailDigestAgent",
    [string]$PythonPath = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonConsole = $PythonPath
if (-not $PythonConsole) {
    $PythonConsole = (Get-Command python.exe -ErrorAction Stop).Source
}
$PythonWindowless = Join-Path (Split-Path -Parent $PythonConsole) "pythonw.exe"
$Python = if (Test-Path -LiteralPath $PythonWindowless) { $PythonWindowless } else { $PythonConsole }
$Script = Join-Path $ProjectRoot "run_scheduled_digest.py"
$Action = New-ScheduledTaskAction -Execute $Python -Argument ('"{0}"' -f $Script) -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Description "Generate and email the configured mail digest" -Force
Write-Host "Task created: $TaskName. It checks every 5 minutes and sends the digest at the configured time."
