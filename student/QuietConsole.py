"""Keep command-line App launches windowless while preserving ordinary GUI apps."""
import subprocess


class ConsoleSafeSubprocess:
    def __getattr__(self, name):
        return getattr(subprocess, name)

    @staticmethod
    def Popen(*args, **kwargs):
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(*args, **kwargs)


def configure_app_launch():
    # PowerShellExecutor already uses CREATE_NO_WINDOW upstream. Keep this
    # proxy local to the App module; do not replace subprocess globally.
    # Windows ignores CREATE_NO_WINDOW for non-console (GUI) executables.
    from windows_mcp.tools import app as app_tools
    app_tools.subprocess = ConsoleSafeSubprocess()
