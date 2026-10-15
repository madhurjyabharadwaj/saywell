"""Entry point for the packaged Saywell.exe (PyInstaller can't start a package's __main__ directly)."""
from saywell.__main__ import main

main()
