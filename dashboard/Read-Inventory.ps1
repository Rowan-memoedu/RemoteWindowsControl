# Fixed, read-only inventory command for the teacher's local device page.
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$system = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue)
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)

function Read-PowerPair($group, $setting) {
    $lines = @(& powercfg.exe /qh SCHEME_CURRENT $group $setting 2>$null)
    if ($LASTEXITCODE -ne 0) { return }
    $indices = @(foreach ($line in $lines) {
        if ($line -match '(?i):\s*0x([0-9a-f]+)\s*$') {
            [Convert]::ToUInt32($Matches[1], 16)
        }
    })
    if ($indices.Count -ge 2) { return @{ac=$indices[-2]; dc=$indices[-1]} }
}

$sources = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$apps = @(Get-ItemProperty -Path $sources -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -and $_.SystemComponent -ne 1 -and -not $_.ParentKeyName } |
    Select-Object @{n='Name';e={$_.DisplayName}},@{n='Version';e={$_.DisplayVersion}} |
    Sort-Object Name,Version -Unique)
$task = @(Get-ScheduledTask -TaskName 'RemoteWindowsAssist-*' -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -match '^RemoteWindowsAssist-(rwg-[0-9a-f]{8}-|rwc-)[0-9a-f]{12}$' } |
    Select-Object @{n='Name';e={$_.TaskName}},@{n='State';e={[string]$_.State}})
$volumes = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' |
    Select-Object DeviceID,FileSystem,Size,FreeSpace)
$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
    Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution)
$links = @(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' |
    Select-Object Name,LinkSpeed)
$powerLine = $null
try {
    Add-Type -AssemblyName System.Windows.Forms
    $powerLine = [string][System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus
} catch {}
$now = Get-Date
[ordered]@{
    ComputerName=$env:COMPUTERNAME; UserName=$env:USERNAME
    Administrator=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    SessionId=(Get-Process -Id $PID).SessionId; OS=$os.Caption; OSVersion=$os.Version
    Architecture=$os.OSArchitecture; Manufacturer=$system.Manufacturer; Model=$system.Model
    CPU=($cpu.Name -join ' / '); CpuLoad=($cpu | Measure-Object LoadPercentage -Average).Average
    Threads=$system.NumberOfLogicalProcessors; TotalMemory=$system.TotalPhysicalMemory
    MemoryAvailable=([long]$os.FreePhysicalMemory * 1KB)
    UptimeSeconds=[math]::Floor(($now - $os.LastBootUpTime).TotalSeconds)
    BootTime=$os.LastBootUpTime.ToUniversalTime().ToString('o'); GPUs=$gpus
    Drives=$volumes; NetworkAdapters=$links; PowerLine=$powerLine; Battery=$battery.EstimatedChargeRemaining
    Lid=(Read-PowerPair SUB_BUTTONS LIDACTION); Sleep=(Read-PowerPair SUB_SLEEP STANDBYIDLE)
    Hibernate=(Read-PowerPair SUB_SLEEP HIBERNATEIDLE); AssistTasks=$task
    Apps=$apps; AiwenInstalled=([bool]($apps.Name -contains '爱问云') -or
        (Test-Path -LiteralPath 'D:\AppData\Aiwenyun\App\ai-yxt.exe'))
    AiwenRunning=[bool](Get-Process -Name 'ai-yxt' -ErrorAction SilentlyContinue)
} | ConvertTo-Json -Compress -Depth 5
