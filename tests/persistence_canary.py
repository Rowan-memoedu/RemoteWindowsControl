"""Exercise the real scheduled-task runner without logging out or rebooting the host.

The production definition is checked at Highest; the test runs Limited when the
current host process is not elevated. It never registers the production task.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

SOURCE = Path(__file__).parents[1]
sys.path.insert(0, str(SOURCE))
from mcp_http import read_response

out = Path(sys.argv[1]).resolve()
runtime = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
task_name = 'RemoteWindowsAssist-Canary-' + secrets.token_hex(4)
token = secrets.token_hex(32)
registered = False
report = {'taskName': task_name, 'status': 'RUNNING'}

class UserControlBusy(RuntimeError):
    pass

def quote(value):
    return "'" + str(value).replace("'", "''") + "'"

def ps(code):
    result = subprocess.run([powershell, '-NoLogo', '-NoProfile', '-NonInteractive',
        '-ExecutionPolicy', 'Bypass', '-Command', "$ErrorActionPreference='Stop'; " + code],
        capture_output=True, encoding='utf-8', errors='replace', timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()

def task_action(command):
    return ps(command + ' -TaskName ' + quote(task_name) + ' | Out-Null')

def state():
    try:
        return json.loads((out/'resident-state.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}

def connected():
    try:
        with socket.create_connection((ip, port), timeout=.8):
            return True
    except OSError:
        return False

def wait_ready(previous_pid=None, deadline=100):
    end = time.monotonic() + deadline
    next_progress = 0
    while time.monotonic() < end:
        current = state()
        if current.get('serverPID') and current['serverPID'] != previous_pid and connected():
            return current
        if time.monotonic() >= next_progress:
            print('Waiting for scheduled Windows-MCP startup/recovery...', flush=True)
            next_progress = time.monotonic() + 15
        time.sleep(1)
    raise TimeoutError('Scheduled Windows-MCP did not become ready.')

def call(method, params=None, auth=token):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    if auth is not None:
        headers['Authorization'] = 'Bearer ' + auth
    payload = json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode()
    request = urllib.request.Request(f'http://{ip}:{port}/mcp', payload, headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, read_response(response, timeout=60, progress=lambda: print('MCP keepalive',flush=True))
    except urllib.error.HTTPError as error:
        return error.code, {}

def guarded(tool, arguments):
    for attempt in range(35):
        status, result = call('tools/call', {'name':tool,'arguments':arguments})
        if any(word in json.dumps(result) for word in ('USER_CONTROL','TAKEOVER_PENDING')):
            if attempt % 5 == 0:
                print('Waiting for local user idle before the read-only check...',flush=True)
            time.sleep(2)
            continue
        assert status == 200 and not result.get('result',{}).get('isError'), tool + ' failed'
        return result
    raise UserControlBusy('The user retained desktop control; read-only check not completed.')

try:
    context = json.loads(ps("$s=& 'D:\\AppData\\Tailscale\\App\\tailscale.exe' status --json | ConvertFrom-Json; "
        "$i=[Security.Principal.WindowsIdentity]::GetCurrent(); "
        "[ordered]@{sid=$i.User.Value;admin=([Security.Principal.WindowsPrincipal]::new($i)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);"
        "session=(Get-Process -Id $PID).SessionId;hostName=$s.Self.HostName;tailnet=$s.CurrentTailnet.Name;dns=$s.MagicDNSSuffix;ip=@($s.TailscaleIPs | Where-Object {$_ -match '^100\\.'})[0]} | ConvertTo-Json -Compress"))
    ip = context['ip']
    with socket.socket() as probe:
        probe.bind((ip, 0))
        port = probe.getsockname()[1]
    for name in ('Resident.ps1','Persistence.ps1','SessionServer.py','QuietLauncher.py','QuietConsole.py'):
        text = (SOURCE/'student'/name).read_text(encoding='utf-8-sig')
        (out/name).write_text(text,encoding='utf-8-sig' if name.endswith('.ps1') else 'utf-8')
    config = {'schema':1,'hostName':context['hostName'],'teacherIP':ip,
        'tailnetName':context['tailnet'],'dnsSuffix':context['dns'],'port':port,
        'mcpToken':token,'tailscaleExe':r'D:\AppData\Tailscale\App\tailscale.exe',
        'userSid':context['sid'],'pythonExe':str(runtime/'python.exe'),'taskName':task_name}
    (out/'resident.json').write_text(json.dumps(config),encoding='utf-8-sig')
    register = '. ' + quote(out/'Persistence.ps1') + '; '
    register += '$definition=New-AssistTaskDefinition ' + ' '.join(quote(p) for p in (context['sid'],out/'QuietLauncher.py',out/'resident.json',out,runtime/'pythonw.exe')) + '; '
    register += "if([IO.Path]::GetFileName($definition.Actions[0].Execute) -ne 'pythonw.exe'){throw 'Scheduled entry point is not windowless'}; "
    register += "if($definition.Principal.RunLevel -ne 'Highest' -or $definition.Principal.LogonType -ne 'Interactive'){throw 'Production principal mismatch'}; "
    register += "if($definition.Settings.ExecutionTimeLimit -ne 'PT0S' -or $definition.Settings.RestartCount -ne 999 -or $definition.Triggers[0].Delay -ne 'PT15S' -or $definition.Triggers[1].Repetition.Interval -ne 'PT1M'){throw 'Task recovery/logon settings mismatch'}; "
    if not context['admin']:
        register += '$definition.Principal=New-ScheduledTaskPrincipal -UserId ' + quote(context['sid']) + ' -LogonType Interactive -RunLevel Limited; '
    register += 'Register-ScheduledTask -TaskName ' + quote(task_name) + ' -InputObject $definition | Out-Null'
    ps(register)
    registered = True
    report['productionDefinition'] = 'windowless pythonw + Highest + InteractiveToken + logon trigger + unlimited execution + native 1-minute repeating recovery trigger'
    report['actualCanaryRunLevel'] = 'Highest' if context['admin'] else 'Limited'
    report['fullRebootTest'] = 'Not performed; actual logon trigger remains for student acceptance'
    task_action('Start-ScheduledTask')
    first = wait_ready()
    assert first['sessionId'] == context['session'] and first['sessionId'] != 0
    report['interactiveSession'] = 'PASS'
    assert call('tools/list', auth=None)[0] == 401
    code, result = call('tools/list')
    assert code == 200 and len(result['result']['tools']) >= 21
    report['tools'] = len(result['result']['tools'])
    print('Authenticated MCP is running in the desktop session. Testing automatic crash recovery.',flush=True)
    ps('$p=Get-Process -Id '+str(first['serverPID'])+'; if($p.Path -ne '+quote(runtime/'python.exe')+"){throw 'Unexpected process'}; Stop-Process -InputObject $p -Force")
    recovered = wait_ready(previous_pid=first['serverPID'],deadline=115)
    assert call('tools/list')[0] == 200
    report['automaticCrashRecovery'] = 'PASS: Task Scheduler restarted the real MCP server'
    task_action('Disable-ScheduledTask')
    task_action('Stop-ScheduledTask')
    for _ in range(20):
        if not connected():
            break
        time.sleep(1)
    else:
        raise AssertionError('Stopping the task left the control server reachable')
    report['stop'] = 'PASS: control port closed'
    task_action('Enable-ScheduledTask')
    task_action('Start-ScheduledTask')
    wait_ready(previous_pid=recovered['serverPID'])
    assert call('tools/list')[0] == 200
    report['resume'] = 'PASS'
    report['status'] = 'PASS'
    try:
        command = "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class QuietConsoleProbe { [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'; "
        command += "Write-Output ('QUIET_CONSOLE=' + [QuietConsoleProbe]::GetConsoleWindow().ToInt64()); & $env:ComSpec /d /c echo PERSISTENT_COMMAND_OK"
        result = guarded('PowerShell', {'command':command,'timeout':25})
        assert 'PERSISTENT_COMMAND_OK' in json.dumps(result) and 'Status Code: 0' in json.dumps(result)
        assert 'QUIET_CONSOLE=0' in json.dumps(result), 'PowerShell allocated a console window'
        report['powershell'] = 'PASS'
        report['quietPowerShellAndCmd'] = 'PASS: console handle is zero; nested CMD returned output'
        probe = SOURCE/'tests'/'console_probe.py'
        for executable, label, extra in [('python.exe','console',[]),('pythonw.exe','gui',['--gui'])]:
            output = out/(task_name+'-'+label+'.json')
            guarded('App', {'mode':'launch_executable','executable':str(runtime/executable),'args':[str(probe),str(output),*extra]})
            for _ in range(50):
                if output.exists():
                    observation=json.loads(output.read_text(encoding='utf-8'))
                    break
                time.sleep(.1)
            else:
                raise AssertionError('App launch probe did not return its observation')
            assert observation['consoleHandle'] == 0 and not observation['consoleVisible'], 'App launch allocated a console window'
            if label == 'gui':
                assert observation['guiVisible'], 'App launch suppressed a normal GUI window'
        report['quietAppLaunch'] = 'PASS: CLI executable has no console; GUI window visibility preserved'
        result = guarded('Screenshot', {})
        images = [x for x in result['result']['content'] if x.get('type') == 'image']
        assert images and len(base64.b64decode(images[0]['data'])) > 1000
        report['screenshot'] = 'PASS; image not retained'
    except UserControlBusy:
        report['status'] = 'LIFECYCLE_PASS_UI_BLOCKED'
        report['desktopCheck'] = 'Not completed because the local user retained control; control coordination was preserved'
finally:
    if registered:
        ps('Disable-ScheduledTask -TaskName '+quote(task_name)+' | Out-Null; Stop-ScheduledTask -TaskName '+quote(task_name)+'; Unregister-ScheduledTask -TaskName '+quote(task_name)+' -Confirm:$false')
        report['temporaryTaskRemoved'] = True
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
