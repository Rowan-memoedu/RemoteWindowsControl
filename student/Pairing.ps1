#Requires -Version 5.1

function Get-StudentToken([string]$Secret, [string]$HostName) {
    if ($Secret -notmatch '^[a-f0-9]{64}$') { throw '通用包配对凭据无效。' }
    $key = New-Object byte[] 32
    for ($i=0; $i -lt 32; $i++) { $key[$i] = [Convert]::ToByte($Secret.Substring($i*2,2),16) }
    $hmac = [Security.Cryptography.HMACSHA256]::new()
    try {
        $hmac.Key = $key
        $bytes = [Text.Encoding]::UTF8.GetBytes('RemoteWindowsAssist/v1/' + $HostName)
        return [BitConverter]::ToString($hmac.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()
    } finally { $hmac.Dispose() }
}

function Resolve-StudentPairing([object]$Package, [string]$IdentityRoot) {
    if ($Package.schema -eq 1) {
        if ($Package.hostName -notmatch '^rwc-[a-f0-9]{12}$' -or $Package.mcpToken -notmatch '^[a-f0-9]{64}$') { throw '单机包配对配置无效。' }
        return $Package
    }
    if ($Package.schema -ne 2 -or $Package.mode -ne 'universal' -or $Package.fleetId -notmatch '^[a-f0-9]{8}$' -or $Package.mcpSecret -notmatch '^[a-f0-9]{64}$') { throw '通用包配对配置无效。' }
    New-Item -ItemType Directory -Path $IdentityRoot -Force | Out-Null
    $path = Join-Path $IdentityRoot ($Package.fleetId + '.json')
    $mutex = [Threading.Mutex]::new($false,('Local\RemoteWindowsAssist-Identity-' + $Package.fleetId))
    $locked = $false
    try {
        try { $locked = $mutex.WaitOne(30000) } catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw '另一协助窗口正在初始化，请稍后重试。' }
        if (Test-Path -LiteralPath $path) {
            $device = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($device.schema -ne 1 -or $device.fleetId -ne $Package.fleetId -or $device.deviceId -notmatch '^[a-f0-9]{12}$') { throw '本机设备身份文件无效，请联系老师。' }
        } else {
            $random = [Security.Cryptography.RandomNumberGenerator]::Create()
            try { $bytes = New-Object byte[] 6; $random.GetBytes($bytes) } finally { $random.Dispose() }
            $device = [pscustomobject]@{schema=1;fleetId=$Package.fleetId;deviceId=[BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()}
            $temporary = $path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
            try {
                [IO.File]::WriteAllText($temporary,($device | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
                [IO.File]::Move($temporary,$path)
            } finally { if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary } }
        }
    } finally { if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
    $hostName = 'rwg-' + $Package.fleetId + '-' + $device.deviceId
    return [pscustomobject]@{
        schema=2; mode='universal'; fleetId=$Package.fleetId; hostName=$hostName
        mcpToken=(Get-StudentToken $Package.mcpSecret $hostName)
        teacherIP=$Package.teacherIP; tailnetName=$Package.tailnetName; dnsSuffix=$Package.dnsSuffix
        port=$Package.port; authKey=$Package.authKey; enrollmentExpires=$Package.enrollmentExpires
    }
}
