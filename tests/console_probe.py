"""Record a launched process's console allocation without showing test UI."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
user = ctypes.WinDLL('user32', use_last_error=True)
kernel.GetConsoleWindow.restype = wintypes.HWND
user.IsWindowVisible.argtypes = [wintypes.HWND]
user.IsWindowVisible.restype = wintypes.BOOL
console = kernel.GetConsoleWindow()
result = {'pid':os.getpid(),'consoleHandle':int(console or 0),'consoleVisible':bool(console and user.IsWindowVisible(console))}
if '--gui' in sys.argv[2:]:
    # A zero-size, non-activating native GUI window verifies that the console
    # creation flag leaves ordinary GUI visibility intact, without flashing UI.
    user.CreateWindowExW.argtypes = [wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
        ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,wintypes.HINSTANCE,wintypes.LPVOID]
    user.CreateWindowExW.restype = wintypes.HWND
    user.DestroyWindow.argtypes = [wintypes.HWND]
    hwnd = user.CreateWindowExW(0x08000000,'STATIC','Remote assistance isolated test',0x90000000,0,0,0,0,None,None,None,None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result['guiVisible'] = bool(user.IsWindowVisible(hwnd))
    finally:
        user.DestroyWindow(hwnd)
Path(sys.argv[1]).write_text(json.dumps(result),encoding='utf-8')
