"""Stop MCP when its task/session supervisor exits; leave launched apps alone."""
import os
import sys
import threading
import psutil

parent = psutil.Process(int(sys.argv[1]))
def watch_launcher():
    try:
        parent.wait()
    finally:
        os._exit(0)

threading.Thread(target=watch_launcher,daemon=True).start()
from QuietConsole import configure_app_launch
configure_app_launch()
from windows_mcp.__main__ import main
main(args=sys.argv[2:],prog_name='windows-mcp')
