#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EnrollmentFile,
    [Parameter(Mandatory)][string]$PolicyApiKeyFile,
    [string]$OutputRoot = 'D:\Artifacts\RemoteWindowsControl\students',
    [string]$AssetsPath = 'D:\Artifacts\RemoteWindowsControl\build\assets',
    [string]$StateRoot = 'D:\AppData\RemoteWindowsControl'
)
$ErrorActionPreference = 'Stop'
$tailscale = 'D:\AppData\Tailscale\App\tailscale.exe'
$status = (& $tailscale status --json | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $status.BackendState -ne 'Running') { throw '教师本机尚未登录 Tailscale。' }
$key = Get-Content -LiteralPath $EnrollmentFile -Raw | ConvertFrom-Json
$capability = $key.capabilities.devices.create
if ($capability.reusable -ne $false -or $capability.ephemeral -ne $false -or $capability.preauthorized -ne $true -or @($capability.tags).Count -ne 1 -or $capability.tags[0] -ne 'tag:codex-student') { throw '需要只授予 tag:codex-student 的一次性预授权接入码。' }
if ($key.key -notmatch '^tskey-auth-[A-Za-z0-9-]+$' -or [DateTime]::Parse($key.expires).ToUniversalTime() -le [DateTime]::UtcNow.AddHours(1)) { throw '接入码无效或即将过期。' }
if (-not $status.CurrentTailnet.MagicDNSEnabled -or -not $status.MagicDNSSuffix) { throw '教师网络尚未启用 MagicDNS。' }
$teacherIP = @($status.TailscaleIPs | Where-Object { $_ -match '^100\.' })[0]
if (-not $teacherIP) { throw '未获得教师 Tailscale IPv4。' }
# Read the live network policy. Do not issue a student package into an allow-all tailnet.
$apiSecret = Import-Clixml -LiteralPath $PolicyApiKeyFile
if ($apiSecret -isnot [Security.SecureString]) { throw 'API 凭据必须使用当前 Windows 用户的 DPAPI 加密保存。' }
$apiToken = [Net.NetworkCredential]::new('', $apiSecret).Password
try {
    $policy = Invoke-RestMethod -Uri 'https://api.tailscale.com/api/v2/tailnet/-/acl' -Headers @{Authorization=('Bearer ' + $apiToken); Accept='application/json'} -TimeoutSec 30
    if ($policy -is [string]) { $policy = $policy | ConvertFrom-Json }
} finally { $apiToken = $null }
$grants = @($policy.grants)
if (@($policy.acls).Count -ne 0 -or $grants.Count -ne 1 -or @($grants[0].src).Count -ne 1 -or $grants[0].src[0] -ne $teacherIP -or @($grants[0].dst).Count -ne 1 -or $grants[0].dst[0] -ne 'tag:codex-student' -or @($grants[0].ip).Count -ne 1 -or $grants[0].ip[0] -ne '*') { throw '网络策略不符合教师访问学生全部端口和协议的配置，已停止打包。请先核验现有网络，脚本不会覆盖策略。' }
New-Item -ItemType Directory -Path $StateRoot,$OutputRoot -Force | Out-Null
foreach ($privateFolder in @($StateRoot,$OutputRoot)) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    foreach($sid in @([Security.Principal.WindowsIdentity]::GetCurrent().User,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
        $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($privateFolder),$acl)
}
# Enrollment keys are single use; prevent accidentally preparing two devices with one key.
$keyDigest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($key.key))).ToLowerInvariant()
$usedKeyMarker = Join-Path $StateRoot ('enrollment-' + $keyDigest + '.used')
if (Test-Path -LiteralPath $usedKeyMarker) { throw '此接入码已经用于一个安装包，请为另一台电脑生成新的接入码。' }
$id = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(6)).ToLowerInvariant()
$hostName = 'rwc-' + $id
$token = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
$pairing = [ordered]@{ schema=1; hostName=$hostName; teacherIP=$teacherIP; tailnetName=$status.CurrentTailnet.Name; dnsSuffix=$status.MagicDNSSuffix; port=8765; authKey=$key.key; enrollmentExpires=$key.expires; mcpToken=$token }
$folder = Join-Path $OutputRoot $hostName
if (Test-Path -LiteralPath $folder) { throw '安装包目标已存在。' }
New-Item -ItemType Directory -Path $folder -Force | Out-Null
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'student') -File) {
    $dest = Join-Path $folder $file.Name
    if ($file.Extension -in @('.ps1','.txt')) {
        [IO.File]::WriteAllText($dest,[IO.File]::ReadAllText($file.FullName),[Text.UTF8Encoding]::new($true))
    } else { Copy-Item -LiteralPath $file.FullName -Destination $dest }
}
Copy-Item -LiteralPath $AssetsPath -Destination (Join-Path $folder 'assets') -Recurse
$pairingPath = Join-Path $folder 'pairing.json'
$pairing | ConvertTo-Json | Set-Content -LiteralPath $pairingPath -Encoding utf8BOM
$teacherPairing = Join-Path $StateRoot ($hostName + '.json')
$pairing.Remove('authKey')
$pairing | ConvertTo-Json | Set-Content -LiteralPath $teacherPairing -Encoding utf8
$python = (Get-Command python.exe -ErrorAction Stop).Source
& $python (Join-Path $PSScriptRoot 'configure_codex.py') $teacherPairing
if ($LASTEXITCODE -ne 0) { throw '教师 Codex MCP 配置失败。' }
$zip = Join-Path $OutputRoot ($hostName + '-学生远程协助.zip')
Compress-Archive -Path $folder -DestinationPath $zip
Set-Content -LiteralPath $usedKeyMarker -Value $hostName -Encoding ascii
Write-Host ('学生安装包：' + $zip)
Write-Host ('首次接入截止：' + $key.expires)
Write-Host ('学生启动后，教师执行：python configure_codex.py "' + $teacherPairing + '" --connect')
Write-Host '安装包仅供对应的一台学生电脑使用，请勿公开发布。'
