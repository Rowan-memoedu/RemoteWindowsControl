#Requires -Version 7.4
[CmdletBinding()]
param([string]$BuildRoot = 'D:\Artifacts\RemoteWindowsControl\build')
$ErrorActionPreference = 'Stop'
$uv = Join-Path $BuildRoot 'uv\uv.exe'
$env:UV_CACHE_DIR = 'D:\Caches\RemoteWindowsControl\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $BuildRoot 'managed-python'
$env:UV_NO_CONFIG = '1'
$env:ANONYMIZED_TELEMETRY = 'false'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:TEMP = Join-Path $BuildRoot 'temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $BuildRoot,$env:TEMP,$env:UV_CACHE_DIR -Force | Out-Null
if (-not (Test-Path -LiteralPath $uv)) { throw 'Run the verified uv bootstrap before building.' }
& $uv python install 3.14.10 --no-bin --no-registry
if ($LASTEXITCODE -ne 0) { throw 'Python download failed.' }
$runtime = Join-Path $env:UV_PYTHON_INSTALL_DIR 'cpython-3.14.10-windows-x86_64-none'
$python = Join-Path $runtime 'python.exe'
& $uv pip compile (Join-Path $PSScriptRoot 'requirements.in') --python $python --only-binary ':all:' --generate-hashes --output-file (Join-Path $PSScriptRoot 'requirements.lock') --quiet
if ($LASTEXITCODE -ne 0) { throw 'Dependency resolution failed.' }
& $uv pip install --python $python --target (Join-Path $runtime 'Lib\site-packages') --only-binary ':all:' --require-hashes --requirements (Join-Path $PSScriptRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -c "import importlib.metadata,win32api,comtypes,dxcam,fastmcp; print('windows-mcp=' + importlib.metadata.version('windows-mcp'))"
if ($LASTEXITCODE -ne 0) { throw 'Runtime import test failed.' }
& $python -m windows_mcp serve --help
if ($LASTEXITCODE -ne 0) { throw 'Windows-MCP CLI test failed.' }
$assets = Join-Path $BuildRoot 'assets'
New-Item -ItemType Directory -Path $assets -Force | Out-Null
Write-Host 'Packing portable runtime...'
Compress-Archive -Path (Join-Path $runtime '*') -DestinationPath (Join-Path $assets 'runtime.zip') -Force
Copy-Item -LiteralPath 'D:\Artifacts\Installers\Tailscale\tailscale-setup-1.104.4-amd64.msi' -Destination (Join-Path $assets 'tailscale.msi')
$manifest = [ordered]@{
    architecture = 'AMD64'; pythonVersion = '3.14.10'; windowsMcpVersion = '0.8.8'; tailscaleVersion = '1.104.4'
    runtimeSha256 = (Get-FileHash -LiteralPath (Join-Path $assets 'runtime.zip')).Hash
    tailscaleSha256 = (Get-FileHash -LiteralPath (Join-Path $assets 'tailscale.msi')).Hash
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $assets 'assets.json') -Encoding utf8
Write-Host ('Runtime assets ready: ' + $assets)
Get-ChildItem -LiteralPath $assets | Select-Object Name,Length
