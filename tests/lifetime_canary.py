"""Verify closing the assistance parent terminates its child, not unrelated processes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil

source=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='rwc-lifetime-') as directory:
    pidfile=Path(directory)/'child.txt'
    script=Path(directory)/'parent.ps1'
    lifetime=str(source/'student'/'ProcessLifetime.ps1').replace("'","''")
    marker=str(pidfile).replace("'","''")
    script.write_text(f". '{lifetime}'\nSet-SessionProcessLifetime\n$p=Start-Process -FilePath \"$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" -ArgumentList '-NoProfile -Command Start-Sleep -Seconds 120' -WindowStyle Hidden -PassThru\n$p.Id | Set-Content -LiteralPath '{marker}'\nStart-Sleep -Seconds 120\n",encoding='utf-8-sig')
    parent=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],creationflags=subprocess.CREATE_NO_WINDOW)
    child_pid=None
    try:
        for _ in range(50):
            if pidfile.exists(): break
            if parent.poll() is not None: raise RuntimeError('Lifetime canary failed during setup')
            time.sleep(.2)
        child_pid=int(pidfile.read_text().strip())
        assert psutil.pid_exists(child_pid)
        parent.terminate(); parent.wait(timeout=10)
        for _ in range(50):
            if not psutil.pid_exists(child_pid): break
            time.sleep(.1)
        assert not psutil.pid_exists(child_pid), 'Orphaned assistance child after parent exit'
        assert psutil.pid_exists(os.getpid())
        print('PASS: closing the assistance parent terminates its own child process')
    finally:
        if parent.poll() is None: parent.terminate(); parent.wait(timeout=10)
        if child_pid and psutil.pid_exists(child_pid): psutil.Process(child_pid).terminate()
