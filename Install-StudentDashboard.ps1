#Requires -Version 7
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskName = 'RemoteWindowsControl-StudentDashboard'
$page = 'http://127.0.0.1:8766/'
$server = Join-Path $PSScriptRoot 'device_dashboard.py'
$python = (& python -c 'import sys; print(sys.executable)').Trim()
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw 'Windowless teacher Python not found.' }
$arguments = '-B "{0}"' -f $server
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Arguments -ne $arguments -or $existing.Actions[0].Execute -ne $pythonw)) {
    throw 'A different scheduled task already owns this name.'
}
function Test-Page {
    try { return (Invoke-RestMethod -Uri ($page+'health') -NoProxy -TimeoutSec 2).service -eq 'student-device-dashboard' }
    catch { return $false }
}
$listener = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
if ($listener -and (-not $existing -or -not (Test-Page))) { throw 'TCP port 8766 is already in use.' }

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '教师本机学生电脑状态页' -Force | Out-Null
if (-not (Test-Page)) { Start-ScheduledTask -TaskName $taskName }
for ($i=0; $i -lt 20; $i++) {
    if (Test-Page) { break }
    Start-Sleep -Milliseconds 400
}
if (-not (Test-Page)) { throw 'Local status page did not start.' }
$shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) '学生电脑状态.url'
if (Test-Path -LiteralPath $shortcut) {
    if ((Get-Content -LiteralPath $shortcut) -notcontains ('URL='+$page)) { throw 'An unrelated desktop shortcut already has this name.' }
} else {
    [IO.File]::WriteAllLines($shortcut, @('[InternetShortcut]',('URL='+$page)), [Text.Encoding]::ASCII)
}
[pscustomobject]@{Page=$page; DesktopShortcut=$shortcut; Task=$taskName; State=[string](Get-ScheduledTask -TaskName $taskName).State} | ConvertTo-Json
