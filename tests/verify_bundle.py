"""Inspect the distributable ZIP without printing enrollment or MCP credentials."""
import io
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import sys
import zipfile

archive=Path(sys.argv[1]).resolve()
output=Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    names=bundle.namelist()
    for name in names:
        path=PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts
    roots={PurePosixPath(name).parts[0] for name in names}
    assert len(roots)==1
    root=next(iter(roots))
    read=lambda name: bundle.read(root+'/'+name)
    required={'Start.cmd','Start.ps1','SessionServer.py','QuietLauncher.py','QuietConsole.py','Persistence.ps1','Resident.ps1','Manage-Assist.ps1','说明.txt','pairing.json','assets/assets.json','assets/runtime.zip','assets/tailscale.msi'}
    actual={name[len(root)+1:] for name in names if not name.endswith('/')}
    pairing=json.loads(read('pairing.json').decode('utf-8-sig'))
    if pairing['schema']==2:
        required.add('Pairing.ps1')
        assert pairing['mode']=='universal'
        assert re.fullmatch(r'[a-f0-9]{8}',pairing['fleetId'])
        assert re.fullmatch(r'[a-f0-9]{64}',pairing['mcpSecret'])
        assert 'hostName' not in pairing and 'mcpToken' not in pairing
    else:
        assert pairing['schema']==1
        assert pairing['hostName']==root
        assert len(pairing['mcpToken'])==64
        if 'Pairing.ps1' in actual:
            required.add('Pairing.ps1')
    assert actual==required,actual
    assert pairing['authKey'].startswith('tskey-auth-')
    assert pairing['teacherIP'].startswith('100.')
    for name in [n for n in actual if n.endswith(('.ps1','.txt'))]+['pairing.json']:
        assert read(name).startswith(b'\xef\xbb\xbf'),f'Windows encoding: {name}'
    for name in actual-{'assets/runtime.zip','assets/tailscale.msi'}:
        assert b'tskey-api-' not in read(name),f'Unexpected API credential in {name}'
    assets=json.loads(read('assets/assets.json'))
    runtime=read('assets/runtime.zip')
    assert hashlib.sha256(runtime).hexdigest().upper()==assets['runtimeSha256']
    assert hashlib.sha256(read('assets/tailscale.msi')).hexdigest().upper()==assets['tailscaleSha256']
    with zipfile.ZipFile(io.BytesIO(runtime)) as inner:
        assert inner.testzip() is None
        assert 'python.exe' in inner.namelist()
        assert 'pythonw.exe' in inner.namelist()
        assert 'Lib/site-packages/windows_mcp/__main__.py' in inner.namelist()
        assert all('..' not in PurePosixPath(p).parts for p in inner.namelist())
report={'status':'PASS','archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'packageMode':pairing.get('mode','single-device'),'connectionMode':'automatic-at-logon','packageIdentity':pairing.get('fleetId',root),'enrollmentExpires':pairing['enrollmentExpires'],'checks':['ZIP integrity','complete persistent-runner manifest','Windows PowerShell UTF-8 BOM','pinned binary hashes','no teacher API credential','portable runtime included'],'remote_end_to_end':'persistent upgrade pending student execution; original interactive connection already verified separately'}
output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key not in {'archive','sha256'}},ensure_ascii=False))
