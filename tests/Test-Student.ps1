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
$fixture=Join-Path $env:TEMP ('rwc-acl-'+[Guid]::NewGuid().ToString('N')+'.tmp')
try {
    [IO.File]::WriteAllText($fixture,'synthetic-credential-fixture')
    $access=[Security.AccessControl.FileSecurity]::new()
    $access.SetAccessRuleProtection($true,$false)
    $access.SetAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User,'FullControl','Allow'))
    [IO.File]::SetAccessControl($fixture,$access)
    if([IO.File]::ReadAllText($fixture) -ne 'synthetic-credential-fixture') { throw 'Protected fixture unreadable' }
    $readback=Get-Acl -LiteralPath $fixture
    if(-not $readback.AreAccessRulesProtected -or @($readback.Access).Count -ne 1) { throw 'Unexpected private credential access rules' }
    Write-Output 'PASS: student enrollment credential file can be restricted without extra security privileges'
} finally { if(Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture } }
