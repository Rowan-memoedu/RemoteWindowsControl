#Requires -Version 5.1
$ErrorActionPreference='Stop'
$source=Split-Path $PSScriptRoot -Parent
$errorsFound=@()
foreach($file in Get-ChildItem -LiteralPath (Join-Path $source 'student') -Filter '*.ps1') {
    $tokens=$null; $parseErrors=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput([IO.File]::ReadAllText($file.FullName),[ref]$tokens,[ref]$parseErrors)
    $errorsFound+=@($parseErrors)
    if($file.Name -eq 'Start.ps1') { $startAst=$ast }
}
if($errorsFound.Count) { throw ($errorsFound | Out-String) }
Write-Output 'PASS: student scripts parse in Windows PowerShell 5.1'
$fn=$startAst.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-TailIP'},$true)
Invoke-Expression $fn.Extent.Text
foreach($ip in @('100.64.0.1','100.127.255.254')) { Assert-TailIP $ip }
foreach($ip in @('127.0.0.1','192.168.1.1','100.63.1.1','100.128.0.1','::1','invalid')) {
    $rejected=$false
    try { Assert-TailIP $ip } catch { $rejected=$true }
    if(-not $rejected) { throw ('Invalid IP accepted: '+$ip) }
}
Write-Output 'PASS: only Tailscale IPv4 teacher addresses accepted'
