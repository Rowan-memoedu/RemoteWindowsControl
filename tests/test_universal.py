import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from connect_students import find_students,student_token
from configure_codex import update_config


class UniversalTests(unittest.TestCase):
    def test_powershell_python_identity_compatibility(self):
        base=Path(r'D:\Artifacts\RemoteWindowsControl\validation\universal')
        base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='identity-',dir=base) as directory:
            root=Path(directory).resolve()
            self.assertEqual(root.parent,base.resolve())
            report=root/'fixture.json'
            ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            subprocess.run([str(ps),'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(SOURCE/'tests/Test-UniversalPairing.ps1'),'-FixtureRoot',str(root),'-OutputPath',str(report)],check=True,timeout=45,capture_output=True)
            fixture=json.loads(report.read_text(encoding='utf-8-sig'))
            for device in (fixture['first'],fixture['second']):
                self.assertEqual(device['mcpToken'],student_token('11'*32,device['hostName']))
            config=root/'config.toml'
            config.write_text('model="preserved"\n[mcp_servers.existing]\ncommand="keep"\n',encoding='utf-8')
            for device in (fixture['first'],fixture['second']):
                update_config(config,device,'http://100.100.1.2:8765/mcp',True)
            import tomllib
            parsed=tomllib.loads(config.read_text())
            self.assertEqual(len(parsed['mcp_servers']),3)
            self.assertEqual(parsed['mcp_servers']['existing']['command'],'keep')
            self.assertEqual(parsed['model'],'preserved')

    def test_discovery_distinguishes_fleet_suffix_and_online_state(self):
        fleet={'fleetId':'1234abcd','tailnetName':'fixture.example','dnsSuffix':'fixture.ts.net','teacherIP':'100.97.233.94'}
        peer=lambda dns,online: {'DNSName':dns,'Online':online,'TailscaleIPs':['fd7a:115c:a1e0::1','100.100.1.2']}
        status={'BackendState':'Running','CurrentTailnet':{'Name':'fixture.example'},'TailscaleIPs':['100.97.233.94'],'Peer':{
            'a':peer('rwg-1234abcd-111111111111.fixture.ts.net.',True),
            'b':peer('rwg-1234abcd-222222222222.fixture.ts.net.',False),
            'other':peer('rwg-abcd1234-111111111111.fixture.ts.net.',True),
            'wrong_network':peer('rwg-1234abcd-111111111111.other.ts.net.',True),
            'legacy':peer('rwc-123456789abc.fixture.ts.net.',True)}}
        devices=find_students(status,fleet)
        self.assertEqual([d['hostName'] for d in devices],['rwg-1234abcd-111111111111','rwg-1234abcd-222222222222'])
        self.assertEqual([d['online'] for d in devices],[True,False])
        status['CurrentTailnet']['Name']='different-network'
        with self.assertRaises(RuntimeError):find_students(status,fleet)


if __name__=='__main__':unittest.main()
