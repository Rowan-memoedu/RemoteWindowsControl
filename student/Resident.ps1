#Requires -Version 5.1
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$root = Split-Path -Parent $ConfigPath
$log = Join-Path $root 'resident.log'
$server = $null
function Write-AssistLog([string]$Message) {
    if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 1MB) {
        Move-Item -LiteralPath $log -Destination ($log + '.1') -Force
    }
    Add-Content -LiteralPath $log -Value ((Get-Date -Format o) + ' ' + $Message) -Encoding UTF8
}
try {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schema -ne 1 -or $config.mcpToken -notmatch '^[a-f0-9]{64}$') { throw 'Invalid resident configuration.' }
    if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne $config.userSid -or (Get-Process -Id $PID).SessionId -eq 0) { throw 'Wrong interactive Windows session.' }
    Write-AssistLog 'Waiting for the paired Tailscale profile.'
    $ip = $null
    while (-not $ip) {
        try {
            $raw = & $config.tailscaleExe status --json 2>$null
            if ($LASTEXITCODE -eq 0 -and $raw) {
                $status = ($raw -join "`n") | ConvertFrom-Json
                if ($status.BackendState -eq 'Running' -and $status.CurrentTailnet.Name -eq $config.tailnetName -and $status.Self.HostName -eq $config.hostName -and $status.Self.DNSName.TrimEnd('.') -eq ($config.hostName + '.' + $config.dnsSuffix)) {
                    $ip = @($status.TailscaleIPs | Where-Object { $_ -match '^100\.' }) | Select-Object -First 1
                }
            }
        } catch { $ip = $null }
        if (-not $ip) { Start-Sleep -Seconds 10 }
    }
    $env:PYTHONUTF8 = '1'; $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONNOUSERSITE = '1'
    $env:ANONYMIZED_TELEMETRY = 'false'; $env:WINDOWS_MCP_WATCHDOG = 'off'
    $env:WINDOWS_MCP_TOOLS = $null; $env:WINDOWS_MCP_EXCLUDE_TOOLS = $null
    $env:WINDOWS_MCP_AUTH_KEY = $config.mcpToken
    $env:WINDOWS_MCP_IP_ALLOWLIST = $config.teacherIP + '/32'
    $temp = Join-Path $root 'temp'
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    $env:TEMP = $temp; $env:TMP = $temp
    $mcpConfig = Join-Path $root 'windows-mcp.toml'
    [IO.File]::WriteAllText($mcpConfig,"[tools]`nexclude = []`n",[Text.UTF8Encoding]::new($false))
    $arguments = '"{0}" {1} serve --config "{2}" --transport streamable-http --stateless-http --host {3} --port {4}' -f (Join-Path $root 'SessionServer.py'),$PID,$mcpConfig,$ip,$config.port
    $server = Start-Process -FilePath $config.pythonExe -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root 'mcp.stdout.log') -RedirectStandardError (Join-Path $root 'mcp.stderr.log')
    Write-AssistLog ('Started Windows-MCP process ' + $server.Id + ' in session ' + (Get-Process -Id $PID).SessionId)
    [ordered]@{state='starting';launcherPID=$PID;serverPID=$server.Id;sessionId=(Get-Process -Id $PID).SessionId;ip=$ip;port=$config.port;started=(Get-Date -Format o)} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'resident-state.json') -Encoding UTF8
    $server.WaitForExit()
    throw ('Windows-MCP exited with code ' + $server.ExitCode)
} catch {
    Write-AssistLog $_.Exception.Message
    exit 1
} finally {
    if ($server -and -not $server.HasExited) { $server.Kill() }
    $env:WINDOWS_MCP_AUTH_KEY = $null
}
