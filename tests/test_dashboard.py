"""Exercise the dashboard's online/offline boundary without operating a real desktop."""
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import device_dashboard as dashboard


class DashboardTests(unittest.TestCase):
    host = 'rwg-abcd1234-0123456789ab'
    other = 'rwg-abcd1234-987654321abc'

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        base = Path(r'D:\Artifacts\RemoteWindowsControl\validation\dashboard')
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=base)))
        self.app = dashboard.Dashboard(self.root, self.root/'ops')
        stack.callback(self.app.pool.shutdown)
        self.mode, self.calls, self.online = 'ready', [], True
        test = self

        class Remote(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                name = request['params']['name']
                test.calls.append((name,self.headers.get('Authorization')))
                if test.mode == 'denied':
                    self.send_error(401)
                    return
                if name == 'ControlStatus':
                    value = {'state':'user' if test.mode=='busy' else 'ready'}
                    result = {'structuredContent':value,'content':[{'type':'text','text':json.dumps(value)}]}
                else:
                    sample = {'ComputerName':'LAB-PC','OS':'Windows 11','TotalMemory':8589934592,
                              'Drives':[{'DeviceID':'C:','Size':1000,'FreeSpace':600}],
                              'Apps':[{'Name':'Teaching app','Version':'3','password':'must-not-escape'}],
                              'secret':'must-not-escape'}
                    payload = 'Response: '+json.dumps(sample)+'\nStatus Code: 0'
                    result = {'content':[{'type':'text','text':payload}]}
                wire = json.dumps({'id':1,'jsonrpc':'2.0','result':result})
                body = (': keepalive\n\nevent: message\ndata: '+wire+'\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1',0),Remote)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        self.port = server.server_port
        self.app.discover = self.discover

    def discover(self):
        rows = [{'hostName':host,'address':'127.0.0.1','online':self.online,'os':'windows',
                 'lastSeen':'2026-01-01T01:00:00+00:00'} for host in (self.host,self.other)]
        return rows,{p['hostName']:('127.0.0.1',self.port,'11'*32) for p in rows}

    def finished(self):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            doc = self.app.view(self.host)
            if doc['detail']['control'] != 'checking':
                return doc
            time.sleep(.02)
        self.fail('Collection did not finish')

    def test_selected_online_device_and_offline_cache_survive_restart(self):
        first = self.finished()
        self.assertEqual(first['detail']['control'],'ready')
        self.assertEqual(first['detail']['inventory']['ComputerName'],'LAB-PC')
        self.assertEqual(self.calls,[('ControlStatus','Bearer '+'11'*32),('PowerShell','Bearer '+'11'*32)])
        self.assertNotIn('must-not-escape',json.dumps(first))
        self.assertNotIn('11'*32,json.dumps(first))
        self.online = False
        second = self.app.view(self.host,manual=True)
        self.assertEqual(second['detail']['control'],'offline')
        self.assertEqual(second['detail']['capturedAt'],first['detail']['capturedAt'])
        self.assertGreater(second['devices'][0]['lastSeen'],'2026-01-01')
        self.assertEqual(len(self.calls),2)
        restart = dashboard.Dashboard(self.root,self.root/'ops')
        self.addCleanup(restart.pool.shutdown)
        with patch.object(restart,'discover',side_effect=OSError('local link down')):
            lost = restart.view(self.host)
        self.assertIsNone(lost['devices'][0]['online'])
        self.assertEqual(lost['detail']['control'],'unknown')
        self.assertEqual(lost['detail']['inventory']['ComputerName'],'LAB-PC')

    def test_busy_then_denied_never_runs_inventory(self):
        self.mode = 'busy'
        self.assertEqual(self.finished()['detail']['control'],'busy')
        self.mode = 'denied'
        self.app.view(self.host,manual=True)
        self.assertEqual(self.finished()['detail']['control'],'denied')
        self.assertEqual([c[0] for c in self.calls],['ControlStatus','ControlStatus'])

    def test_missing_time_and_tool_refusal(self):
        self.assertIsNone(dashboard.iso_time('0001-01-01T00:00:00Z'))
        with self.assertRaises(dashboard.Busy):
            dashboard.result_object({'result':{'isError':True,'content':[
                {'type':'text','text':'{"code":"PHYSICAL_INPUT_HELD"}'}]}})
        with self.assertRaises(ValueError):
            dashboard.result_object({'result':{'content':[{'type':'text','text':'Response: {}\nStatus Code: 1'}]}})


if __name__ == '__main__':
    unittest.main()
