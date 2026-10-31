"""Discover a universal package's Tailscale peers and register ready MCP servers."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

from configure_codex import update_config
from mcp_http import read_response


def student_token(secret, hostname):
    if not re.fullmatch(r'[a-f0-9]{64}', secret):
        raise ValueError('Invalid fleet pairing secret')
    return hmac.new(bytes.fromhex(secret), ('RemoteWindowsAssist/v1/'+hostname).encode(), hashlib.sha256).hexdigest()


def find_students(status, fleet):
    if status.get('BackendState') != 'Running' or status.get('CurrentTailnet',{}).get('Name') != fleet['tailnetName']:
        raise RuntimeError('Teacher is not connected to the configured Tailscale network')
    if fleet['teacherIP'] not in status.get('TailscaleIPs',[]):
        raise RuntimeError('Teacher address changed; inspect the network policy before connecting')
    if not re.fullmatch(r'[a-f0-9]{8}',fleet['fleetId']):
        raise ValueError('Invalid universal package identity')
    prefix='rwg-'+fleet['fleetId']+'-'
    result=[]
    for peer in (status.get('Peer') or {}).values():
        dns=peer.get('DNSName','').rstrip('.')
        suffix='.'+fleet['dnsSuffix']
        if not dns.endswith(suffix):
            continue
        hostname=dns[:-len(suffix)]
        if not re.fullmatch(re.escape(prefix)+r'[a-f0-9]{12}',hostname):
            continue
        addresses=[a for a in peer.get('TailscaleIPs',[]) if ipaddress.ip_address(a) in ipaddress.ip_network('100.64.0.0/10')]
        if len(addresses)!=1:
            raise ValueError('Student did not have exactly one Tailscale IPv4 address')
        result.append({'hostName':hostname,'address':addresses[0],'online':bool(peer.get('Online'))})
    return sorted(result,key=lambda item:item['hostName'])


def verify_mcp(url, token):
    payload=json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'teacher-fleet-connection','version':'1'}}}).encode()
    request=urllib.request.Request(url,payload,{'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+token})
    with urllib.request.urlopen(request,timeout=15) as response:
        reply=read_response(response,timeout=20)
    if 'result' not in reply or 'serverInfo' not in reply['result']:
        raise RuntimeError('Authenticated MCP handshake failed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fleet',type=Path,default=Path(r'D:\AppData\RemoteWindowsControl\universal.json'))
    parser.add_argument('--codex-config',type=Path,default=Path(os.environ['USERPROFILE'])/'.codex'/'config.toml')
    parser.add_argument('--tailscale',default=r'D:\AppData\Tailscale\App\tailscale.exe')
    parser.add_argument('--list',action='store_true',help='Only list matching devices')
    parser.add_argument('--host',help='Connect only this device hostname')
    args=parser.parse_args()
    fleet=json.loads(args.fleet.read_text(encoding='utf-8-sig'))
    status=json.loads(subprocess.check_output([args.tailscale,'status','--json'],text=True,timeout=20))
    students=find_students(status,fleet)
    if args.host:
        students=[item for item in students if item['hostName']==args.host]
    if args.list:
        print(json.dumps({'devices':students},ensure_ascii=False)); return
    connected=[]; waiting=[]
    for student in students:
        host=student['hostName']
        if not student['online']:
            waiting.append({'hostName':host,'reason':'Tailscale offline'}); continue
        token=student_token(fleet['mcpSecret'],host)
        url=f"http://{student['address']}:{fleet['port']}/mcp"
        try:
            verify_mcp(url,token)
        except (urllib.error.URLError,TimeoutError,OSError,ValueError,RuntimeError) as error:
            waiting.append({'hostName':host,'reason':'MCP not ready: '+type(error).__name__}); continue
        name=update_config(args.codex_config,{'hostName':host,'mcpToken':token},url,True)
        connected.append({'hostName':host,'server':name,'address':student['address']})
    print(json.dumps({'connected':connected,'waiting':waiting,'discovered':len(students)},ensure_ascii=False))
    if not students:
        print('尚未发现已接入的学生电脑。学生打开通用包中的 Start.cmd 后再次运行即可。')


if __name__=='__main__':
    main()
