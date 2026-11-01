"""Check real Win32 visibility and offline shutdown without desktop input."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import psutil
import win32api
import win32con
import win32security

source=Path(__file__).parents[1]
sys.path.insert(0,str(source/'student'))
from QuietConsole import configure_app_launch
from windows_mcp.tools import app as app_tools

out=Path(sys.argv[1]).resolve()
out.mkdir(parents=True,exist_ok=True)
runtime=Path(sys.executable).parent
report={}
configure_app_launch()
for executable,label,extra in [('python.exe','cli',[]),('pythonw.exe','gui',['--gui'])]:
    output=out/(label+'-'+secrets.token_hex(4)+'.json')
    app_tools._launch_executable(str(runtime/executable),[str(source/'tests/console_probe.py'),str(output),*extra],None)
    for _ in range(50):
        if output.exists():break
        time.sleep(.1)
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['consoleHandle']==0 and not result['consoleVisible'],label+' allocated a console'
    if label=='gui':assert result['guiVisible'],'Normal GUI visibility was suppressed'
    report[label]=result

fixture=out/'offline'
fixture.mkdir(exist_ok=True)
for name in ('Resident.ps1','QuietLauncher.py','SessionServer.py','QuietConsole.py'):
    (fixture/name).write_text((source/'student'/name).read_text(encoding='utf-8-sig'),encoding='utf-8-sig' if name.endswith('.ps1') else 'utf-8')
token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
try:
    sid=win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
finally:
    token.Close()
config={'schema':1,'hostName':'offline-fixture','tailnetName':'fixture.invalid','dnsSuffix':'fixture.invalid','teacherIP':'127.0.0.1','port':8765,
    'userSid':sid,'mcpToken':secrets.token_hex(32),'tailscaleExe':r'D:\AppData\Tailscale\App\tailscale.exe','pythonExe':sys.executable,'taskName':'isolated-offline-fixture'}
(fixture/'resident.json').write_text(json.dumps(config),encoding='utf-8-sig')
parent=None
resident=None
try:
    parent=subprocess.Popen([str(runtime/'pythonw.exe'),str(fixture/'QuietLauncher.py'),str(fixture/'resident.json')],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(100):
        if parent.poll() is not None:raise AssertionError('Windowless parent exited early')
        children=psutil.Process(parent.pid).children()
        candidates=[p for p in children if p.name().lower()=='powershell.exe']
        if candidates and (fixture/'resident.log').exists():
            resident=candidates[0]
            break
        time.sleep(.1)
    if not resident:raise AssertionError('Offline resident did not start')
    print('Waiting for the offline child to exit after its windowless parent stops...',flush=True)
    parent.terminate()
    parent.wait(timeout=5)
    resident.wait(timeout=15)
    assert 'Windowless supervisor has stopped.' in (fixture/'resident.log').read_text(encoding='utf-8-sig')
    report['offlineStop']='PASS: waiting PowerShell child exited after its task parent stopped'
finally:
    if parent and parent.poll() is None:
        parent.terminate();parent.wait(timeout=5)
    if resident and resident.is_running():
        resident.terminate();resident.wait(timeout=5)
report['status']='PASS'
(out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
