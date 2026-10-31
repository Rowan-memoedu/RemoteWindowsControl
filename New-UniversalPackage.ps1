#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EnrollmentFile,
    [string]$OutputRoot = 'D:\Artifacts\RemoteWindowsControl\universal',
    [string]$AssetsPath = 'D:\Artifacts\RemoteWindowsControl\build\assets',
    [string]$StateRoot = 'D:\AppData\RemoteWindowsControl'
)
$ErrorActionPreference='Stop'
$status=& 'D:\AppData\Tailscale\App\tailscale.exe' status --json | ConvertFrom-Json
if($LASTEXITCODE -ne 0 -or $status.BackendState -ne 'Running'){throw '教师本机尚未接入 Tailscale。'}
$teacherIP=@($status.TailscaleIPs | Where-Object {$_ -match '^100\.'})[0]
$enrollment=Get-Content -LiteralPath $EnrollmentFile -Raw | ConvertFrom-Json
$capability=$enrollment.capabilities.devices.create
if($capability.reusable -ne $true -or $capability.ephemeral -ne $false -or $capability.preauthorized -ne $true -or @($capability.tags).Count -ne 1 -or $capability.tags[0] -ne 'tag:codex-student'){throw '通用包需要可重复使用、非临时、预批准且仅含学生标签的接入码。'}
if($enrollment.key -notmatch '^tskey-auth-[A-Za-z0-9-]+$' -or [DateTime]::Parse($enrollment.expires).ToUniversalTime() -le [DateTime]::UtcNow.AddHours(1)){throw '接入码无效或即将过期。'}
if(-not $teacherIP -or -not $status.CurrentTailnet.MagicDNSEnabled -or -not $status.MagicDNSSuffix){throw '教师网络尚未准备好。'}
New-Item -ItemType Directory -Path $StateRoot,$OutputRoot -Force | Out-Null
foreach($folderPath in @($StateRoot,$OutputRoot)) {
    $acl=[Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
        $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($folderPath),$acl)
}
$fleetPath=Join-Path $StateRoot 'universal.json'
if(Test-Path -LiteralPath $fleetPath) {
    $fleet=Get-Content -LiteralPath $fleetPath -Raw | ConvertFrom-Json
    if($fleet.schema -ne 2 -or $fleet.fleetId -notmatch '^[a-f0-9]{8}$' -or $fleet.mcpSecret -notmatch '^[a-f0-9]{64}$' -or $fleet.teacherIP -ne $teacherIP -or $fleet.tailnetName -ne $status.CurrentTailnet.Name -or $fleet.dnsSuffix -ne $status.MagicDNSSuffix){throw '已有通用包的教师或网络身份发生变化，请先核验。'}
    $fleetId=$fleet.fleetId; $secret=$fleet.mcpSecret
} else {
    $fleetId=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(4)).ToLowerInvariant()
    $secret=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
}
$pairing=[ordered]@{schema=2;mode='universal';fleetId=$fleetId;teacherIP=$teacherIP;tailnetName=$status.CurrentTailnet.Name;dnsSuffix=$status.MagicDNSSuffix;port=8765;authKey=$enrollment.key;enrollmentExpires=$enrollment.expires;mcpSecret=$secret}
$folder=Join-Path $OutputRoot 'RemoteWindowsAssist'
if(Test-Path -LiteralPath $folder) {
    if((Get-Item -LiteralPath $folder).Attributes -band [IO.FileAttributes]::ReparsePoint){throw '交付目录不能是重解析点。'}
    $existing=Get-Content -LiteralPath (Join-Path $folder 'pairing.json') -Raw | ConvertFrom-Json
    if($existing.fleetId -ne $fleetId){throw '交付目录中已有其他安装包。'}
}
New-Item -ItemType Directory -Path $folder -Force | Out-Null
foreach($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'student') -File) {
    $dest=Join-Path $folder $file.Name
    if($file.Extension -in @('.ps1','.txt')){[IO.File]::WriteAllText($dest,[IO.File]::ReadAllText($file.FullName),[Text.UTF8Encoding]::new($true))}
    else {Copy-Item -LiteralPath $file.FullName -Destination $dest -Force}
}
New-Item -ItemType Directory -Path (Join-Path $folder 'assets') -Force | Out-Null
Get-ChildItem -LiteralPath $AssetsPath -File | Copy-Item -Destination (Join-Path $folder 'assets') -Force
$pairing | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $folder 'pairing.json') -Encoding utf8BOM
$pairing.Remove('authKey')
$pairing | ConvertTo-Json | Set-Content -LiteralPath $fleetPath -Encoding utf8
$zip=Join-Path $OutputRoot '学生远程协助-通用版.zip'
Compress-Archive -Path $folder -DestinationPath $zip -Force
Write-Output ('通用安装包：'+$zip)
Write-Output ('新电脑首次接入截止：'+$enrollment.expires)
Write-Output '已接入的电脑不受接入码到期影响。同一 ZIP 可发给多位学生。'
Write-Output ('教师扫描入口：'+(Join-Path $PSScriptRoot 'Connect-Students.cmd'))
