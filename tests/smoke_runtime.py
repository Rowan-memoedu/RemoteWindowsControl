"""Check portable MCP startup, authentication, allowlist and real command round trip."""
import json
import base64
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
token = secrets.token_hex(32)
environment = os.environ | {
    'WINDOWS_MCP_AUTH_KEY': token, 'WINDOWS_MCP_IP_ALLOWLIST': '127.0.0.1/32',
    'ANONYMIZED_TELEMETRY': 'false', 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
    'PYTHONNOUSERSITE': '1', 'TEMP': str(out), 'TMP': str(out),
}
report = {}

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def call(port, method, params=None, auth=token):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    if auth is not None:
        headers['Authorization'] = 'Bearer ' + auth
    payload = json.dumps({'jsonrpc':'2.0', 'id':1, 'method':method, 'params':params or {}}).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}/mcp', payload, headers)
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            raw = response.read().decode()
            if raw.startswith('event:') or raw.startswith('data:'):
                raw = next(line[6:] for line in raw.splitlines() if line.startswith('data: '))
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        return exc.code, {}

def start(port, allowlist, logfile):
    env = environment | {'WINDOWS_MCP_IP_ALLOWLIST':allowlist}
    config = out / 'empty.toml'
    config.write_text('# Isolated canary configuration\n', encoding='utf-8')
    process = subprocess.Popen([str(root/'python.exe'), '-m','windows_mcp','serve',
        '--config',str(config),'--transport','streamable-http','--stateless-http',
        '--host','127.0.0.1','--port',str(port)], env=env,
        stdout=logfile, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError(f'MCP exited during startup: {process.returncode}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3):
                return process
        except OSError:
            time.sleep(.5)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError('MCP startup timed out')

process = None
try:
    port = free_port()
    with (out/'server.log').open('w',encoding='utf-8') as log:
        process = start(port, '127.0.0.1/32', log)
        init = {'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'read-only-canary','version':'1'}}
        assert call(port, 'initialize', init, auth=None)[0] == 401
        assert call(port, 'initialize', init, auth='invalid-token')[0] == 401
        report['authentication'] = 'PASS: absent and incorrect bearer tokens rejected'
        status, initialized = call(port, 'initialize', init)
        assert status == 200 and 'result' in initialized, initialized
        status, listed = call(port, 'tools/list')
        assert status == 200 and 'result' in listed, listed
        names = [tool['name'] for tool in listed['result']['tools']]
        assert {'PowerShell','FileSystem','Screenshot','Click','Snapshot'}.issubset(names), names
        report['tools'] = names
        # A read-only PowerShell command verifies that this is more than a GUI transport.
        for _ in range(12):
            status, result = call(port, 'tools/call', {'name':'PowerShell','arguments':{'command':"Write-Output 'REMOTE_MCP_CANARY_OK'",'timeout':15}})
            text = json.dumps(result)
            if 'REMOTE_MCP_CANARY_OK' in text and not result.get('result',{}).get('isError',False):
                break
            if 'USER_CONTROL' not in text and 'TAKEOVER_PENDING' not in text:
                raise AssertionError(result)
            time.sleep(2)
        else:
            raise AssertionError('Desktop remained under user control; command test was not completed')
        report['powershell'] = 'PASS: authenticated command returned expected output'
        for method, arguments in [('Screenshot',{}),('Snapshot',{'use_vision':False,'use_dom':False,'use_ui_tree':True})]:
            for _ in range(12):
                status,result=call(port,'tools/call',{'name':method,'arguments':arguments})
                result_text=json.dumps(result)
                if 'USER_CONTROL' in result_text or 'TAKEOVER_PENDING' in result_text:
                    time.sleep(2); continue
                assert status==200 and not result.get('result',{}).get('isError',False),method+' failed'
                content=result.get('result',{}).get('content',[])
                if method=='Screenshot':
                    images=[part for part in content if part.get('type')=='image']
                    assert images and len(base64.b64decode(images[0]['data']))>1000,'Screenshot missing'
                    report['screenshot']='PASS: read-only screenshot returned image data; no screenshot saved'
                else:
                    blocks=[part.get('text','') for part in content if part.get('type')=='text']
                    assert blocks and not any('Error capturing' in text for text in blocks),'Snapshot failed'
                    report['snapshot']='PASS: read-only desktop snapshot returned; private UI content not logged'
                break
            else:
                raise AssertionError(method+' not completed because the user retained control')
        process.terminate(); process.wait(timeout=15); process=None
    with (out/'denied.log').open('w',encoding='utf-8') as log:
        port=free_port()
        process=start(port,'100.64.0.1/32',log)
        assert call(port,'initialize',init)[0] == 403
        report['ip_allowlist']='PASS: unauthorized source IP rejected even with a valid bearer token'
        process.terminate(); process.wait(timeout=15); process=None
    report['status']='PASS'
finally:
    if process and process.poll() is None:
        process.terminate(); process.wait(timeout=15)
    (out/'smoke.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
