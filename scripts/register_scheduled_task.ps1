param(
    [string]$TaskName = "EmailDigestAgent",
    [string]$PythonPath = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = $PythonPath
if (-not $Python) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
$Script = Join-Path $ProjectRoot "run_scheduled_digest.py"
$Action = New-ScheduledTaskAction -Execute $Python -Argument ('"{0}"' -f $Script) -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1)
$Trigger.Repetition.Interval = (New-TimeSpan -Minutes 5)
$Trigger.Repetition.Duration = (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Description "Generate and email the configured mail digest" -Force
Write-Host "任务已创建：$TaskName。它每 5 分钟检查一次，并在 Web 页面设定的时间发送日报。"
