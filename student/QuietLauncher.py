"""Windowless scheduled-task entry point; retain the normal resident lifecycle."""
import os
from pathlib import Path
import subprocess
import sys
import traceback


def main():
    config = Path(sys.argv[1]).resolve()
    root = config.parent
    log_path = root / 'launcher.log'
    if log_path.exists() and log_path.stat().st_size > 1024 * 1024:
        log_path.replace(root / 'launcher.previous.log')
    with log_path.open('a', encoding='utf-8') as log:
        try:
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            environment = os.environ | {'REMOTE_ASSIST_SUPERVISOR_PID': str(os.getpid())}
            process = subprocess.Popen(
                [str(shell), '-NoLogo', '-NoProfile', '-NonInteractive',
                 '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
                 '-File', str(root / 'Resident.ps1'), '-ConfigPath', str(config)],
                cwd=root, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return process.wait()
        except Exception:
            traceback.print_exc(file=log)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
