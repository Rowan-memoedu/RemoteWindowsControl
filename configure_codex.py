"""Register one paired remote HTTP MCP without changing unrelated Codex configuration."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib
import urllib.request
from mcp_http import read_response

def update_config(path: Path, pairing: dict, url: str, enabled: bool):
    host = pairing['hostName']
    if not re.fullmatch(r'rwc-[a-f0-9]{12}', host):
        raise ValueError('Invalid assistance hostname')
    token = pairing['mcpToken']
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ValueError('Invalid MCP credential')
    name = host.replace('-', '_')
    before = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    parsed = tomllib.loads(before)
    begin = f'# RemoteWindowsAssist begin {host}'
    end = f'# RemoteWindowsAssist end {host}'
    block = '\n'.join([begin, f'[mcp_servers.{name}]', f'url = {json.dumps(url)}',
        f'enabled = {str(enabled).lower()}', 'startup_timeout_sec = 60', 'tool_timeout_sec = 3600',
        'http_headers = { Authorization = ' + json.dumps('Bearer ' + token) + ' }', end])
    if begin in before:
        if before.count(begin) != 1 or before.count(end) != 1:
            raise ValueError('Ambiguous managed MCP block')
        start = before.index(begin); stop = before.index(end, start) + len(end)
        old = tomllib.loads(before[start:stop]).get('mcp_servers', {})
        if set(old) != {name} or parsed.get('mcp_servers',{}).get(name) != old[name]:
            raise ValueError('Existing MCP block contains unexpected user changes')
        after = before[:start] + block + before[stop:]
    else:
        if name in parsed.get('mcp_servers', {}):
            raise ValueError('Existing MCP name is not managed by this package')
        after = before.rstrip() + '\n\n' + block + '\n'
    updated = tomllib.loads(after)
    previous_other = dict(parsed.get('mcp_servers', {})); previous_other.pop(name, None)
    new_other = dict(updated.get('mcp_servers', {})); new_other.pop(name, None)
    assert previous_other == new_other
    parsed.pop('mcp_servers', None); without_mcp = dict(updated); without_mcp.pop('mcp_servers', None)
    assert parsed == without_mcp
    if after == before:
        return name
    # Atomic replacement prevents a crash from truncating the user's configuration.
    fd, temporary = tempfile.mkstemp(prefix='.remoteassist-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
            output.write(after); output.flush(); os.fsync(output.fileno())
        if path.exists():
            if path.read_text(encoding='utf-8-sig') != before:
                raise RuntimeError('Codex configuration changed concurrently; retry after inspecting it')
            # ReplaceFile merges the original file ACL into the replacement on Windows.
            replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
            replace.argtypes = [ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p]
            replace.restype = ctypes.c_int
            if not replace(str(path),temporary,None,0,None,None):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    assert tomllib.loads(path.read_text(encoding='utf-8')) == updated
    return name

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pairing', type=Path)
    parser.add_argument('--codex-config', type=Path, default=Path(os.environ['USERPROFILE'])/'.codex'/'config.toml')
    parser.add_argument('--connect', action='store_true')
    parser.add_argument('--tailscale', default=r'D:\AppData\Tailscale\App\tailscale.exe')
    args = parser.parse_args()
    pairing = json.loads(args.pairing.read_text(encoding='utf-8-sig'))
    url = f"http://{pairing['hostName']}.{pairing['dnsSuffix']}:{pairing['port']}/mcp"
    if args.connect:
        status = json.loads(subprocess.check_output([args.tailscale, 'status', '--json'], text=True, timeout=15))
        peers = [p for p in (status.get('Peer') or {}).values() if p.get('DNSName','').rstrip('.') == pairing['hostName']+'.'+pairing['dnsSuffix']]
        if len(peers) != 1 or not peers[0].get('Online'):
            raise RuntimeError('Student device is not online; ask the student to open Start.cmd first')
        address = next(ip for ip in peers[0]['TailscaleIPs'] if ip.startswith('100.'))
        url = f"http://{address}:{pairing['port']}/mcp"
        payload = json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'teacher-connection-check','version':'1'}}}).encode()
        request = urllib.request.Request(url,payload,{'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+pairing['mcpToken']})
        with urllib.request.urlopen(request,timeout=30) as response:
            if 'result' not in read_response(response):
                raise RuntimeError('MCP initialize handshake failed')
    name = update_config(args.codex_config, pairing, url, args.connect)
    print(json.dumps({'server':name,'enabled':args.connect,'verified_connection':args.connect}, ensure_ascii=False))

if __name__ == '__main__':
    main()
