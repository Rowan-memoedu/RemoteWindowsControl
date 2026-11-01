#Requires -Version 5.1

function Assert-InteractiveAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $sessionId = (Get-Process -Id $PID).SessionId
    if ($sessionId -eq 0) { throw '请在学生日常使用的 Windows 桌面中运行安装器。' }
    $shells = @(Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Where-Object { $_.SessionId -eq $sessionId })
    if (-not $shells.Count) { throw '未找到当前 Windows 桌面，请登录桌面后重试。' }
    foreach ($shell in $shells) {
        $owner = Invoke-CimMethod -InputObject $shell -MethodName GetOwnerSid
        if ($owner.ReturnValue -eq 0 -and $owner.Sid -eq $identity.User.Value) { return }
    }
    throw '安装器与桌面不是同一个 Windows 账户。请使用具有管理员权限的日常账户安装，不能用另一个管理员账户代为提升。'
}

function Get-AssistRoot([string]$HostName) {
    $legacy = Join-Path $env:LOCALAPPDATA ('RemoteWindowsAssist\' + $HostName)
    $preferred = 'D:\AppData\RemoteWindowsAssist\' + $HostName
    if (Test-Path -LiteralPath $preferred) { return $preferred }
    if (Test-Path -LiteralPath $legacy) { return $legacy }
    $drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='D:'" -ErrorAction SilentlyContinue
    if ($drive -and $drive.DriveType -eq 3 -and $drive.FreeSpace -gt 1GB) { return $preferred }
    return $legacy
}

function Protect-AssistRoot([string]$Root) {
    $item = Get-Item -LiteralPath $Root
    while ($item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '协助程序目录不能经过重解析点。' }
        $item = $item.Parent
    }
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    [IO.Directory]::SetAccessControl($Root,$acl)
}

function New-AssistTaskDefinition([string]$UserSid,[string]$ScriptPath,[string]$ConfigPath,[string]$WorkingDirectory,[string]$PythonwExe) {
    if (-not $PythonwExe -or -not (Test-Path -LiteralPath $PythonwExe)) { throw '缺少无控制台运行组件 pythonw.exe。' }
    $executable = $PythonwExe
    $arguments = '"{0}" "{1}"' -f $ScriptPath,$ConfigPath
    $action = New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $WorkingDirectory
    $principal = New-ScheduledTaskPrincipal -UserId $UserSid -LogonType Interactive -RunLevel Highest
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserSid
    $trigger.Delay = 'PT15S'
    # RestartOnFailure alone did not restart a failed on-demand instance in the
    # Windows 11 canary. A native repeating trigger also repairs a stopped task;
    # IgnoreNew leaves an already-running instance and its desktop session alone.
    $recovery = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    return New-ScheduledTask -Action $action -Principal $principal -Trigger @($trigger,$recovery) -Settings $settings -Description '学生远程协助：此账户登录 Windows 后自动上线。可从桌面“远程协助设置”停用。'
}

function Install-AssistPersistence([object]$Pairing,[string]$Root,[string]$TailscaleExe,[string]$SourceRoot) {
    $taskName = 'RemoteWindowsAssist-' + $Pairing.hostName
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $resident = Join-Path $Root 'Resident.ps1'
    $launcher = Join-Path $Root 'QuietLauncher.py'
    $configPath = Join-Path $Root 'resident.json'
    if ($existing) {
        if (@($existing.Actions).Count -ne 1 -or ($existing.Actions[0].Arguments -notlike ('*"' + $resident + '"*') -and $existing.Actions[0].Arguments -notlike ('*"' + $launcher + '"*'))) { throw '同名计划任务不属于此安装，已停止以免覆盖。' }
        Disable-ScheduledTask -InputObject $existing | Out-Null
        Stop-ScheduledTask -InputObject $existing
        for ($i=0; $i -lt 15; $i++) {
            if (-not (Get-NetTCPConnection -State Listen -LocalPort $Pairing.port -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Seconds 1
        }
    }
    if (Get-NetTCPConnection -State Listen -LocalPort $Pairing.port -ErrorAction SilentlyContinue) { throw '检测到原有协助窗口或其他程序仍占用端口。请关闭旧版协助窗口后，再双击此版本的 Start.cmd。' }
    Protect-AssistRoot $Root
    foreach ($name in @('Resident.ps1','SessionServer.py','QuietLauncher.py','QuietConsole.py','Manage-Assist.ps1')) {
        $source = Join-Path $SourceRoot $name
        $destination = Join-Path $Root $name
        if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($destination)) { Copy-Item -LiteralPath $source -Destination $destination -Force }
    }
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $configuration = [ordered]@{
        schema=1; hostName=$Pairing.hostName; teacherIP=$Pairing.teacherIP
        tailnetName=$Pairing.tailnetName; dnsSuffix=$Pairing.dnsSuffix; port=$Pairing.port
        mcpToken=$Pairing.mcpToken; tailscaleExe=$TailscaleExe; userSid=$userSid
        pythonExe=(Join-Path $Root 'runtime\python.exe'); taskName=$taskName
    }
    [IO.File]::WriteAllText($configPath,($configuration | ConvertTo-Json),[Text.UTF8Encoding]::new($true))
    $definition = New-AssistTaskDefinition $userSid $launcher $configPath $Root (Join-Path $Root 'runtime\pythonw.exe')
    Register-ScheduledTask -TaskName $taskName -InputObject $definition -Force | Out-Null
    $readback = Get-ScheduledTask -TaskName $taskName
    if ($readback.Principal.LogonType -ne 'Interactive' -or $readback.Principal.RunLevel -ne 'Highest') { throw '自动启动任务未保留交互桌面或管理员权限。' }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '远程协助设置.lnk'))
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -ConfigPath "{1}"' -f (Join-Path $Root 'Manage-Assist.ps1'),$configPath
    $shortcut.WorkingDirectory = $Root
    $shortcut.Description = '查看、停止或恢复自动远程协助'
    $shortcut.Save()
    Start-ScheduledTask -TaskName $taskName
    return $taskName
}
