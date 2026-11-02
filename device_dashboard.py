"""Local, read-only student status page. The browser never receives pairing credentials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

from connect_students import find_students, student_token
from mcp_http import read_response


WEB = Path(__file__).with_name('dashboard')
DATA = Path(r'D:\AppData\RemoteWindowsControl')
OPERATIONS = Path(r'D:\Artifacts\RemoteWindowsControl\operations')
TAILSCALE = r'D:\AppData\Tailscale\App\tailscale.exe'
PORT = 8766
DEVICE_ID = re.compile(r'(?:rwg-[0-9a-f]{8}-|rwc-)[0-9a-f]{12}')
STATIC = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css'), '/tokens.css': ('tokens.css', 'text/css')}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def iso_time(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value)
        if date.year > 2000 and date.tzinfo:
            return date.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def file_time(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def cached_json(path):
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(dir=path.parent)
    temp = Path(filename)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False, allow_nan=False)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Busy(Exception):
    """The student's physical input currently has priority."""


def result_object(reply):
    result = reply.get('result', {})
    content = result.get('content', [])
    text = next((part['text'] for part in content if part.get('type') == 'text'), '')
    if text.lstrip().startswith('{'):
        obj = json.loads(text)
        if obj.get('code') in ('USER_CONTROL', 'TAKEOVER_PENDING', 'PHYSICAL_INPUT_HELD'):
            raise Busy
    if 'error' in reply or result.get('isError'):
        raise ValueError('MCP tool failed')
    structured = result.get('structuredContent')
    if isinstance(structured, dict) and 'state' in structured:
        return structured
    if text.startswith('Response:'):
        match = re.fullmatch(r'Response:\s*(.*?)\s*Status Code:\s*0\s*', text, re.S)
        if not match:
            raise ValueError('PowerShell did not finish successfully')
        text = match.group(1)
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError('Expected an object')
    return obj


def inventory_fields(obj):
    """Only the displayable inventory schema can enter the cache or the page."""
    if not obj.get('ComputerName') or not obj.get('OS'):
        raise ValueError('Incomplete inventory')
    scalars = ('ComputerName UserName Administrator SessionId OS OSVersion Architecture Manufacturer '
               'Model CPU CpuLoad Threads TotalMemory MemoryAvailable UptimeSeconds BootTime PowerLine '
               'Battery AiwenInstalled AiwenRunning').split()
    data = {k: obj[k] for k in scalars if isinstance(obj.get(k), (str, int, float, bool))}
    for key in ('Lid', 'Sleep', 'Hibernate'):
        pair = obj.get(key)
        if isinstance(pair, dict) and all(isinstance(pair.get(k), int) for k in ('ac', 'dc')):
            data[key] = {k: pair[k] for k in ('ac', 'dc')}
    groups = {'Drives': ('DeviceID','FileSystem','Size','FreeSpace'),
              'GPUs': ('Name','CurrentHorizontalResolution','CurrentVerticalResolution'),
              'NetworkAdapters': ('Name','LinkSpeed'), 'Apps': ('Name','Version'),
              'AssistTasks': ('Name','State')}
    for key, fields in groups.items():
        rows = obj.get(key)
        if isinstance(rows, list):
            data[key] = [{k: row[k] for k in fields if isinstance(row.get(k), (str,int,float))}
                         for row in rows if isinstance(row,dict)]
    return data


def read_history(operations):
    history = {}
    for record in sorted(operations.glob('*/operation-status.json')):
        op = cached_json(record)
        host = op.get('targetHost', '')
        if not DEVICE_ID.fullmatch(host) or op.get('targetConfirmedByUser') is not True:
            continue
        info = history.setdefault(host, {})
        if op.get('student'):
            info['name'] = op['student']
        path = record.with_name('inventory.json')
        try:
            when = file_time(path)
            if when > info.get('capturedAt', ''):
                info['inventory'] = inventory_fields(result_object(load_json(path)))
                info['capturedAt'] = when
        except (OSError, ValueError, Busy):
            pass
        install = op.get('installation', {})
        if op.get('software') == '爱问云' and install.get('state') == 'completed' and install.get('installerExitCode') == 0:
            receipt = record.with_name('installation.json')
            info['installedAt'] = file_time(receipt) if receipt.is_file() else file_time(record)
            state = (op.get('login') or {}).get('state')
            info['loginRecord'] = {'not_started':'unconfirmed','completed':'confirmed','verified':'confirmed'}.get(state)
    return history


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call_tool(target, name, arguments, timeout):
    address, port, token = target
    url = f'http://{address}:{port}/mcp'
    body = {'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
            'params':{'name':name, 'arguments':arguments}}
    request = urllib.request.Request(url, json.dumps(body).encode(), {
        'Authorization':'Bearer '+token, 'Content-Type':'application/json',
        'Accept':'application/json, text/event-stream'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    with opener.open(request, timeout=timeout) as response:
        return result_object(read_response(response, timeout=timeout))


def paired_devices(status, fleet, data_root):
    devices = find_students(status, fleet)
    if status.get('Self', {}).get('Online') is False:
        raise RuntimeError('Teacher offline')
    peers = {p.get('DNSName','').rstrip('.'):p for p in (status.get('Peer') or {}).values()}
    targets = {d['hostName']:(d['address'], int(fleet['port']), student_token(fleet['mcpSecret'], d['hostName']))
               for d in devices}
    for path in data_root.glob('rwc-*.json'):
        host = path.stem
        if not DEVICE_ID.fullmatch(host):
            continue
        pair = cached_json(path)
        if pair.get('hostName') != host or not all(pair.get(k) == fleet[k] for k in ('dnsSuffix','teacherIP','tailnetName')):
            continue
        peer = peers.get(host + '.' + fleet['dnsSuffix'])
        if not peer or not re.fullmatch('[a-f0-9]{64}', pair.get('mcpToken','')):
            continue
        ips = [a for a in peer.get('TailscaleIPs',[]) if ipaddress.ip_address(a) in ipaddress.ip_network('100.64.0.0/10')]
        if len(ips) == 1:
            devices.append({'hostName':host, 'address':ips[0], 'online':bool(peer.get('Online'))})
            targets[host] = (ips[0], int(pair['port']), pair['mcpToken'])
    for device in devices:
        peer = peers[device['hostName'] + '.' + fleet['dnsSuffix']]
        device['lastSeen'] = iso_time(peer.get('LastSeen'))
        device['os'] = peer.get('OS')
    return devices, targets


class Dashboard:
    def __init__(self, data_root=DATA, operations=OPERATIONS):
        self.root = data_root
        self.cache = data_root / 'dashboard'
        self.peers_path = self.cache / 'peers.json'
        self.history = read_history(operations)
        self.peers = cached_json(self.peers_path)
        self.targets = {}
        self.probes = {}
        self.samples = {}
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='inventory')
        self.lock = threading.RLock()
        self.checked = ''
        self.network_ok = False
        self.next_network = 0
        self.operations = operations
        self.next_history = time.monotonic() + 300

    def discover(self):
        raw = subprocess.check_output([TAILSCALE, 'status', '--json'], timeout=6,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return paired_devices(json.loads(raw), load_json(self.root / 'universal.json'), self.root)

    def refresh_network(self):
        self.checked = utc_now()
        try:
            devices, targets = self.discover()
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
            self.network_ok = False
            self.targets.clear()
            self.probes.clear()
            return
        new = {}
        for row in devices:
            host = row['hostName']
            previous = self.peers.get(host, {})
            seen = row.get('lastSeen') or previous.get('lastSeen')
            observed = previous.get('observed')
            if row['online']:
                observed = self.checked
            new[host] = {**row, 'lastSeen':seen, 'observed':observed}
            if not row['online'] or self.targets.get(host) != targets[host]:
                self.probes.pop(host, None)
        for gone in self.peers.keys() - new.keys():
            self.probes.pop(gone, None)
        self.network_ok = True
        self.targets = targets
        if self.peers != new:
            save_json(self.peers_path, new)
        self.peers = new

    def collect(self, host, target, ticket):
        state, sample = 'unreachable', None
        response_ms = None
        try:
            started = time.monotonic()
            control = call_tool(target, 'ControlStatus', {}, 5)
            response_ms = round((time.monotonic() - started) * 1000)
            owner = control.get('state')
            if owner in ('user', 'takeover_pending'):
                raise Busy
            if owner != 'ready':
                state = 'working' if owner == 'ai' else 'unavailable'
                return
            state = 'partial'
            command = (WEB / 'Read-Inventory.ps1').read_text(encoding='utf-8-sig')
            info = inventory_fields(call_tool(target, 'PowerShell', {'command':command,'timeout':30}, 38))
            sample = {'capturedAt':utc_now(), 'inventory':info}
            state = 'ready'
        except Busy:
            state = 'busy'
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403):
                state = 'denied'
            exc.close()
        except (OSError, ValueError, TimeoutError, RuntimeError):
            pass
        finally:
            with self.lock:
                if self.probes.get(host) is ticket:
                    if sample:
                        self.samples[host] = sample
                    ticket.update(state=state, checkedAt=utc_now(), running=False, responseMs=response_ms,
                                  retry=time.monotonic() + (90 if state == 'ready' else 20))
                    if sample:
                        save_json(self.cache / (host+'.json'), sample)

    def view(self, requested='', manual=False):
        with self.lock:
            now = time.monotonic()
            if manual or now >= self.next_history:
                self.history = read_history(self.operations)
                self.next_history = now + 300
            if now >= self.next_network or manual:
                self.refresh_network()
                self.next_network = time.monotonic() + 7
            rows = []
            for host, peer in self.peers.items():
                if host not in self.samples:
                    self.samples[host] = cached_json(self.cache / (host+'.json'))
                label = (self.history.get(host, {}).get('name')
                         or self.samples[host].get('inventory',{}).get('ComputerName')
                         or '学生电脑 ' + host[-6:].upper())
                rows.append({'id':host, 'name':label,
                    'online':peer['online'] if self.network_ok else None,
                    'address':peer['address'], 'os':peer.get('os'),
                    'lastSeen':max(peer.get('lastSeen') or '',peer.get('observed') or '') or None,
                    'approximate':(peer.get('observed') or '') > (peer.get('lastSeen') or '')})
            rows.sort(key=lambda d:(d['online'] is not True, d['name'],d['id']))
            ids = {d['id'] for d in rows}
            host = requested if requested in ids else (rows[0]['id'] if rows else None)
            detail = None
            if host:
                historical = self.history.get(host, {})
                sample = self.samples[host] or historical
                active = self.network_ok and self.peers[host]['online']
                ticket = self.probes.get(host, {})
                if active and not ticket.get('running') and (manual or now >= ticket.get('retry',0)):
                    ticket = {'state':'checking', 'checkedAt':None, 'running':True}
                    self.probes[host] = ticket
                    self.pool.submit(self.collect, host, self.targets[host], ticket)
                detail = {'id':host, 'capturedAt':sample.get('capturedAt'), 'inventory':sample.get('inventory',{}),
                          'installedAt':historical.get('installedAt'),
                          'loginRecord':historical.get('loginRecord'),
                          'responseMs':ticket.get('responseMs') if active else None,
                          'control':ticket.get('state','unchecked') if active else ('offline' if self.network_ok else 'unknown'),
                          'controlAt':ticket.get('checkedAt') if active else None}
            return {'checkedAt':self.checked,'networkOk':self.network_ok,'devices':rows,'detail':detail}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_body(self, status, mime, body):
        self.send_response(status)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return self.send_error(403)
        url = urlsplit(self.path)
        if url.path == '/health':
            return self.send_body(200,'application/json',b'{"service":"student-device-dashboard"}')
        if url.path == '/api/status':
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.send_error(403)
            query = parse_qs(url.query)
            try:
                result = self.server.dashboard.view(query.get('device',[''])[0], query.get('refresh') == ['1'])
                return self.send_body(200,'application/json',json.dumps(result,ensure_ascii=False).encode())
            except (OSError,ValueError,KeyError):
                return self.send_error(503, 'Status temporarily unavailable')
        if url.path in STATIC:
            filename, mime = STATIC[url.path]
            return self.send_body(200,mime,(WEB / filename).read_bytes())
        self.send_error(404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()
    with ThreadingHTTPServer(('127.0.0.1',args.port), Handler) as server:
        server.dashboard = Dashboard()
        server.serve_forever()


if __name__ == '__main__':
    main()
