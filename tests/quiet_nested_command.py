"""Verify console visibility through the real PowerShell executor's child routes."""
import json
from pathlib import Path
import sys

from windows_mcp.powershell import PowerShellExecutor

root=Path(sys.argv[1]).resolve()
root.mkdir(parents=True,exist_ok=True)
probe=Path(__file__).with_name('console_probe.py').resolve()

def quote(value):
    return "'"+str(value).replace("'","''")+"'"

report={}
for label in ('nested-cmd','hidden-start-process'):
    output=root/(label+'.json')
    if label=='nested-cmd':
        command='& $env:ComSpec /d /c '+ ' '.join(quote(x) for x in (sys.executable,probe,output))
    else:
        arguments='"'+str(probe)+'" "'+str(output)+'"'
        command='Start-Process -FilePath '+quote(sys.executable)+' -ArgumentList '+quote(arguments)+' -WindowStyle Hidden -Wait'
    text,status=PowerShellExecutor.execute_command(command,timeout=30)
    if status!=0:
        raise RuntimeError(label+' failed: '+text)
    result=json.loads(output.read_text(encoding='utf-8'))
    assert not result['consoleVisible'],label+' displayed a console window'
    report[label]={'status':'PASS','consoleHandle':result['consoleHandle'],'consoleVisible':result['consoleVisible']}
(root/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
