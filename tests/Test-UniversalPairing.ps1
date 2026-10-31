#Requires -Version 5.1
param([Parameter(Mandatory)][string]$FixtureRoot,[Parameter(Mandatory)][string]$OutputPath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
. (Join-Path (Split-Path $PSScriptRoot -Parent) 'student\Pairing.ps1')
$package=[pscustomobject]@{schema=2;mode='universal';fleetId='1234abcd';mcpSecret=('11'*32);teacherIP='100.97.233.94';tailnetName='fixture.example';dnsSuffix='fixture.ts.net';port=8765;authKey='synthetic-unused';enrollmentExpires='2030-01-01T00:00:00Z'}
$first=Resolve-StudentPairing $package (Join-Path $FixtureRoot 'computer-a')
$second=Resolve-StudentPairing $package (Join-Path $FixtureRoot 'computer-b')
$repeat=Resolve-StudentPairing $package (Join-Path $FixtureRoot 'computer-a')
if($first.hostName -eq $second.hostName -or $first.mcpToken -eq $second.mcpToken){throw 'Different computers shared an identity or credential.'}
if($first.hostName -ne $repeat.hostName -or $first.mcpToken -ne $repeat.mcpToken){throw 'Restart changed the computer identity.'}
$package.authKey='synthetic-renewed'
$renewed=Resolve-StudentPairing $package (Join-Path $FixtureRoot 'computer-a')
if($renewed.hostName -ne $first.hostName -or $renewed.mcpToken -ne $first.mcpToken){throw 'Renewing enrollment changed an existing device.'}
$legacy=[pscustomobject]@{schema=1;hostName='rwc-123456789abc';mcpToken=('22'*32)}
$legacyResolved=Resolve-StudentPairing $legacy (Join-Path $FixtureRoot 'legacy')
if($legacyResolved.hostName -ne $legacy.hostName -or $legacyResolved.mcpToken -ne $legacy.mcpToken){throw 'Legacy package changed.'}
$identityPath=Join-Path $FixtureRoot 'computer-a\1234abcd.json'
[IO.File]::WriteAllText($identityPath,'{"schema":1,"fleetId":"1234abcd","deviceId":"bad"}')
$rejected=$false
try {$null=Resolve-StudentPairing $package (Join-Path $FixtureRoot 'computer-a')} catch {$rejected=$true}
if(-not $rejected){throw 'Invalid persisted identity silently replaced.'}
@{status='PASS';first=$first;second=$second;checks=@('separate computers','stable restart','enrollment renewal','legacy compatibility','invalid state rejected')} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output 'PASS: distinct device identities, stable restarts, renewal, legacy compatibility and invalid-state handling'
