#Requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath,[switch]$Elevated)
$ErrorActionPreference = 'Stop'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        if ($Elevated) { throw '未取得管理员权限。' }
        $arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -ConfigPath "{1}" -Elevated' -f $PSCommandPath,$ConfigPath
        Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -ArgumentList $arguments | Out-Null
        exit 0
    }
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $task = Get-ScheduledTask -TaskName $config.taskName
    Write-Host '学生远程协助'
    Write-Host ('自动连接：' + $(if($task.Settings.Enabled){'已启用'}else{'已停用'}))
    Write-Host ('设备：' + $config.hostName)
    Write-Host '启用后，每次登录此 Windows 账户会自动上线，老师可以查看屏幕、操作电脑、读写文件和安装软件。'
    Write-Host ''
    Write-Host '1  停止协助，并取消以后自动连接'
    Write-Host '2  恢复协助，并启用以后自动连接'
    Write-Host '0  退出'
    $choice = Read-Host '请输入数字'
    if ($choice -eq '1') {
        Disable-ScheduledTask -InputObject $task | Out-Null
        Stop-ScheduledTask -InputObject $task
        Get-NetFirewallRule -Name $config.taskName -ErrorAction SilentlyContinue | Disable-NetFirewallRule
        Write-Host '已停止，今后不会自动连接。需要时可在这里恢复。'
    } elseif ($choice -eq '2') {
        Get-NetFirewallRule -Name $config.taskName -ErrorAction Stop | Enable-NetFirewallRule
        Enable-ScheduledTask -InputObject $task | Out-Null
        Start-ScheduledTask -TaskName $config.taskName
        Write-Host '已启用，正在连接。'
    } else { exit 0 }
    Read-Host '按回车关闭' | Out-Null
} catch {
    Write-Host ('操作未完成：' + $_.Exception.Message) -ForegroundColor Red
    Read-Host '按回车关闭' | Out-Null
    exit 1
}
