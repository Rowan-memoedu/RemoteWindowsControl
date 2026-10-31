"""Stopping the launcher ends MCP while a separately launched background task survives."""
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import psutil
sys.path.insert(0,str(Path(__file__).parents[1]))
from mcp_http import read_response

source=Path(sys.argv[1]).resolve()
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
token=secrets.token_hex(32)
with tempfile.TemporaryDirectory(prefix='rwc-lifetime-') as directory:
    temp=Path(directory)
    pidfile=temp/'server.pid'
    config=temp/'empty.toml'; config.write_text('[tools]\nexclude=[]\n',encoding='utf-8')
    parent_script=temp/'parent.py'
    arguments=[sys.executable,str(source/'student'/'SessionServer.py'),'PARENT_PID','serve','--config',str(config),'--transport','streamable-http','--stateless-http','--host','127.0.0.1','--port',str(port)]
    parent_script.write_text('import os, subprocess, time\nfrom pathlib import Path\nargs='+repr(arguments)+'\nargs[2]=str(os.getpid())\nwith open('+repr(str(temp/'server.log'))+',"w") as log:\n p=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)\n Path('+repr(str(pidfile))+').write_text(str(p.pid))\n time.sleep(150)\n',encoding='utf-8')
    env=os.environ|{'WINDOWS_MCP_AUTH_KEY':token,'WINDOWS_MCP_IP_ALLOWLIST':'127.0.0.1/32','ANONYMIZED_TELEMETRY':'false','PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
    parent=subprocess.Popen([sys.executable,str(parent_script)],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    tracked=[]
    def rpc(method,params):
        payload=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode()
        request=urllib.request.Request(f'http://127.0.0.1:{port}/mcp',payload,{'Authorization':'Bearer '+token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'})
        with urllib.request.urlopen(request,timeout=40) as response:
            return read_response(response,timeout=60,progress=lambda:print('MCP keepalive: '+method,flush=True))
    try:
        for _ in range(100):
            if pidfile.exists():
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2): break
                except OSError: pass
            if parent.poll() is not None: raise RuntimeError('Launcher setup failed')
            time.sleep(.2)
        server=psutil.Process(int(pidfile.read_text())); tracked.append(server)
        print('Session server listening; checking authenticated initialize',flush=True)
        rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'lifetime-canary','version':'1'}})
        print('Starting independent background task via PowerShell',flush=True)
        background_marker=temp/'background.pid'
        background_code='import subprocess,pathlib; p=subprocess.Popen(["powershell.exe","-NoProfile","-Command","Start-Sleep -Seconds 120"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW); pathlib.Path('+repr(str(background_marker))+').write_text(str(p.pid)); print("RWC_BACKGROUND_PID="+str(p.pid),flush=True)'
        command="& '"+sys.executable.replace("'","''")+"' -c '"+background_code.replace("'","''")+"'"
        match=None
        for _ in range(12):
            result=rpc('tools/call',{'name':'PowerShell','arguments':{'command':command,'timeout':20}})
            text=json.dumps(result)
            match=re.search(r'RWC_BACKGROUND_PID=(\d+)',text)
            if match: break
            if 'USER_CONTROL' not in text and 'TAKEOVER_PENDING' not in text: raise RuntimeError('Background launch failed')
            time.sleep(2)
        assert match,'Background task not launched'
        background=psutil.Process(int(match.group(1))); tracked.append(background)
        print('Background task started; closing launcher',flush=True)
        parent.terminate(); parent.wait(timeout=10)
        for _ in range(50):
            if not server.is_running(): break
            time.sleep(.1)
        assert not server.is_running(),'MCP server survived launcher closure'
        assert background.is_running(),'Independent background task was incorrectly stopped'
        print('PASS: launcher closure stops MCP; independent background task remains running')
    finally:
        if parent.poll() is None: parent.terminate(); parent.wait(timeout=10)
        if 'background_marker' in locals() and background_marker.exists():
            try:
                fixture_process=psutil.Process(int(background_marker.read_text()))
                if all(item.pid!=fixture_process.pid for item in tracked): tracked.append(fixture_process)
            except psutil.NoSuchProcess: pass
        for process in tracked:
            if process.is_running():
                process.terminate(); process.wait(timeout=10)
