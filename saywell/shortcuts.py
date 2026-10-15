"""Create Desktop and Start menu shortcuts so Saywell opens like any other app.

From a source checkout the shortcut runs `pythonw -m saywell` (no console window);
from the packaged build it points at Saywell.exe.
"""
import os
import subprocess
import sys

from .config import APP_NAME, asset, source_root

_PS = r"""
$ErrorActionPreference = 'Stop'
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $sh.CreateShortcut((Join-Path $dir "$env:SW_NAME.lnk"))
    $lnk.TargetPath = $env:SW_TARGET
    $lnk.Arguments = $env:SW_ARGS
    $lnk.WorkingDirectory = $env:SW_CWD
    $lnk.IconLocation = "$env:SW_ICON,0"
    $lnk.Description = 'Hold a hotkey, speak, and your words appear where you type'
    $lnk.Save()
    Write-Output $lnk.FullName
}
"""


def launch_command() -> tuple[str, str, str]:
    """(target, arguments, working dir) that start Saywell without a console."""
    if getattr(sys, "frozen", False):
        return sys.executable, "", os.path.dirname(sys.executable)
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    return exe, "-m saywell", source_root() or os.getcwd()


def create_shortcuts() -> list[str]:
    target, args, cwd = launch_command()
    icon = target if getattr(sys, "frozen", False) else asset("saywell.ico")
    env = dict(os.environ, SW_NAME=APP_NAME, SW_TARGET=target, SW_ARGS=args, SW_CWD=cwd, SW_ICON=icon)
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], env=env,
                         capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "PowerShell failed")
    return [line for line in out.stdout.splitlines() if line.strip()]
