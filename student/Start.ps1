#Requires -Version 5.1
[CmdletBinding()]
param([switch]$Elevated)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONNOUSERSITE = '1'
$env:ANONYMIZED_TELEMETRY = 'false'
$env:WINDOWS_MCP_WATCHDOG = 'off'
$env:WINDOWS_MCP_TOOLS = $null
$env:WINDOWS_MCP_EXCLUDE_TOOLS = $null
. (Join-Path $PSScriptRoot 'Pairing.ps1')

function Get-TailscaleExe {
    $command = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($path in @((Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'), 'D:\AppData\Tailscale\App\tailscale.exe')) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    return $null
}
function Get-TailscaleStatus([string]$Exe) {
    $result = & $Exe status --json 2>$null
    if (-not $result) { throw '无法读取 Tailscale 状态。' }
    return (($result -join "`n") | ConvertFrom-Json)
}
function Assert-TailIP([string]$Value) {
    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Value,[ref]$parsed)) { throw '配对文件中的教师地址无效。' }
    $bytes = $parsed.GetAddressBytes()
    if ($bytes.Length -ne 4 -or $bytes[0] -ne 100 -or $bytes[1] -lt 64 -or $bytes[1] -gt 127) { throw '配对地址必须是 Tailscale IPv4 地址。' }
}

try {
    $configPath = Join-Path $PSScriptRoot 'pairing.json'
    if (-not (Test-Path -LiteralPath $configPath)) { throw '安装包缺少教师配对配置，请联系老师重新生成。' }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schema -notin @(1,2) -or $config.port -ne 8765) { throw '配对配置格式无效。' }
    Assert-TailIP $config.teacherIP
    if (-not $config.tailnetName -or -not $config.dnsSuffix) { throw '配对配置尚未完成。' }
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or $env:PROCESSOR_ARCHITEW6432) { throw '此安装包仅支持 64 位 Intel/AMD Windows，请联系老师。' }
    if ([Environment]::OSVersion.Version.Major -lt 10) { throw '需要 Windows 10 或 Windows 11。' }

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $admin = ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) {
        if ($Elevated) { throw '尚未取得管理员权限。' }
        Write-Host '即将申请管理员权限，用于安装组件和开启本次远程协助。'
        $arg = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "{0}" -Elevated' -f $PSCommandPath
        Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs -ArgumentList $arg | Out-Null
        # Close the initial launcher so the student has just one assistance window.
        exit 0
    }
    $Host.UI.RawUI.WindowTitle = '远程协助 — 关闭此窗口结束控制'
    Write-Host '运行期间，老师可查看屏幕、操作电脑、读写文件和执行安装命令。' -ForegroundColor Yellow
    Write-Host '关闭本窗口即可结束本次协助。请保持电脑不锁屏、不休眠。'
    $config = Resolve-StudentPairing $config (Join-Path $env:LOCALAPPDATA 'RemoteWindowsAssist\identities')

    $assets = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'assets\assets.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $runtimeZip = Join-Path $PSScriptRoot 'assets\runtime.zip'
    $msi = Join-Path $PSScriptRoot 'assets\tailscale.msi'
    if ((Get-FileHash -LiteralPath $runtimeZip).Hash -ne $assets.runtimeSha256 -or (Get-FileHash -LiteralPath $msi).Hash -ne $assets.tailscaleSha256) { throw '安装包校验失败，请重新解压或联系老师。' }
    $signature = Get-AuthenticodeSignature -LiteralPath $msi
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Tailscale') { throw 'Tailscale 官方签名校验失败。' }

    $root = Join-Path $env:LOCALAPPDATA ('RemoteWindowsAssist\' + $config.hostName)
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $runtime = Join-Path $root 'runtime'
    $marker = Join-Path $root 'runtime.sha256'
    $python = Join-Path $runtime 'python.exe'
    if (Test-Path -LiteralPath $runtime) {
        if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $assets.runtimeSha256 -or -not (Test-Path -LiteralPath $python)) { throw ('发现未完成或不同版本的组件，请联系老师处理：' + $root) }
    } else {
        Write-Host '正在解压运行组件，首次需要一些时间……'
        Expand-Archive -LiteralPath $runtimeZip -DestinationPath $runtime
        Set-Content -LiteralPath $marker -Value $assets.runtimeSha256 -Encoding ASCII
    }
    $tailscale = Get-TailscaleExe
    if (-not $tailscale) {
        Write-Host '正在安装 Tailscale……'
        $installArguments = '/i "{0}" /qn /norestart TS_NOLAUNCH=1 /L*v "{1}"' -f $msi,(Join-Path $root 'tailscale-install.log')
        $install = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList $installArguments -Wait -PassThru
        if ($install.ExitCode -notin @(0,3010)) { throw ('Tailscale 安装失败，错误码：' + $install.ExitCode) }
        $tailscale = Get-TailscaleExe
        if (-not $tailscale) { throw '安装完成但未找到 Tailscale。' }
        if ($install.ExitCode -eq 3010) { Write-Host '系统提示需要重启；脚本不会自动重启，若接入失败请联系老师。' }
    }
    $service = Get-Service Tailscale
    if ($service.Status -ne 'Running') { Start-Service Tailscale }
    $status = Get-TailscaleStatus $tailscale
    if ($status.CurrentTailnet -and $status.CurrentTailnet.Name -ne $config.tailnetName) { throw '此电脑已加入其他 Tailscale 网络，脚本不会替换现有连接，请联系老师。' }
    if ($status.CurrentTailnet -and $status.Self.HostName -ne $config.hostName) { throw '此电脑已有其他 Tailscale 身份，脚本不会改名或覆盖，请联系老师。' }
    if (-not $status.CurrentTailnet) {
        if ((Get-Date).ToUniversalTime() -ge [DateTime]::Parse($config.enrollmentExpires).ToUniversalTime()) { throw '接入码已过期，请向老师索取更新后的安装包。' }
        if ($config.authKey -notmatch '^tskey-auth-[A-Za-z0-9-]+$') { throw '接入码缺失或无效。' }
        Write-Host '正在自动接入，无需注册或登录账号……'
        $keyFile = Join-Path $root 'enrollment.key'
        try {
            [IO.File]::WriteAllText($keyFile,$config.authKey,[Text.UTF8Encoding]::new($false))
            $acl = [Security.AccessControl.FileSecurity]::new()
            $acl.SetAccessRuleProtection($true,$false)
            $acl.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity.User,'FullControl','Allow'))
            [IO.File]::SetAccessControl($keyFile,$acl)
            & $tailscale up ('--auth-key=file:' + $keyFile) ('--hostname=' + $config.hostName) --accept-routes=false --accept-dns=false --unattended=true --timeout=60s
            if ($LASTEXITCODE -ne 0) { throw '自动接入失败；请确认能上网，若重复失败请联系老师。' }
        } finally {
            if (Test-Path -LiteralPath $keyFile) { Remove-Item -LiteralPath $keyFile -Force }
        }
    } elseif ($status.BackendState -eq 'Stopped') {
        & $tailscale up --timeout=30s
        if ($LASTEXITCODE -ne 0) { throw 'Tailscale 启动失败。' }
    }
    $status = Get-TailscaleStatus $tailscale
    if ($status.BackendState -ne 'Running' -or $status.CurrentTailnet.Name -ne $config.tailnetName) { throw '设备尚未成功接入教师网络，请联系老师。' }
    $ip = @($status.TailscaleIPs | Where-Object { $_ -match '^100\.' }) | Select-Object -First 1
    Assert-TailIP $ip
    $expectedDNS = $config.hostName + '.' + $config.dnsSuffix
    if ($status.Self.DNSName.TrimEnd('.') -ne $expectedDNS) { throw '设备名称与教师配置不一致，请联系老师。' }
    if (Get-NetTCPConnection -State Listen -LocalPort $config.port -ErrorAction SilentlyContinue) { throw '协助端口已被使用；请关闭之前的协助窗口后重试。' }

    $ruleName = 'RemoteWindowsAssist-' + $config.hostName
    $rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($rule) {
        $rule | Set-NetFirewallRule -Enabled True -Direction Inbound -Action Allow -Profile Any
        $rule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $ip -RemoteAddress $config.teacherIP
        $rule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol Any -LocalPort Any -RemotePort Any
        $rule | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program Any
    } else {
        New-NetFirewallRule -Name $ruleName -DisplayName '教师远程协助（仅配对教师）' -Direction Inbound -Action Allow -Enabled True -Profile Any -LocalAddress $ip -RemoteAddress $config.teacherIP -Protocol Any -Program Any | Out-Null
    }
    $env:WINDOWS_MCP_AUTH_KEY = $config.mcpToken
    $env:WINDOWS_MCP_IP_ALLOWLIST = $config.teacherIP + '/32'
    $tempPath = Join-Path $root 'temp'
    New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
    $env:TEMP = $tempPath; $env:TMP = $tempPath
    $configFile = Join-Path $root 'windows-mcp.toml'
    [IO.File]::WriteAllText($configFile,"[tools]`nexclude = []`n",[Text.UTF8Encoding]::new($false))
    $arguments = '"{0}" {1} serve --config "{2}" --transport streamable-http --stateless-http --host {3} --port {4}' -f (Join-Path $PSScriptRoot 'SessionServer.py'),$PID,$configFile,$ip,$config.port
    $server = Start-Process -FilePath $python -ArgumentList $arguments -NoNewWindow -PassThru
    $ready = $false
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        if ($server.HasExited) { throw ('协助程序启动失败，退出码：' + $server.ExitCode) }
        $listener = Get-NetTCPConnection -State Listen -LocalAddress $ip -LocalPort $config.port -ErrorAction SilentlyContinue
        if ($listener -and $listener.OwningProcess -eq $server.Id) { $ready=$true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw '协助程序未能在一分钟内开始监听，请联系老师。' }
    Write-Host ''
    Write-Host '已启动，等待老师连接。结束协助时关闭本窗口。' -ForegroundColor Green
    Write-Host ('设备：' + $config.hostName)
    $server.WaitForExit()
    if ($server.ExitCode -ne 0) { throw ('协助程序已退出，错误码：' + $server.ExitCode) }
} catch {
    if (Get-Variable server -ErrorAction SilentlyContinue) {
        if ($server -and -not $server.HasExited) { $server.Kill() }
    }
    Write-Host ''
    Write-Host ('配置失败：' + $_.Exception.Message) -ForegroundColor Red
    if ($Elevated) { Read-Host '按回车关闭窗口' | Out-Null }
    exit 1
} finally {
    if (Get-Variable server -ErrorAction SilentlyContinue) {
        if ($server -and -not $server.HasExited) { $server.Kill() }
    }
    if (Get-Variable ruleName -ErrorAction SilentlyContinue) {
        Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Disable-NetFirewallRule -ErrorAction SilentlyContinue
    }
    $env:WINDOWS_MCP_AUTH_KEY = $null
}
