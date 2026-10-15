# PyInstaller recipe for Saywell.exe. Build with:  .\build.ps1
import os

ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "saywell", "assets"), os.path.join("saywell", "assets"))],
    hiddenimports=["comtypes.stream"],
    excludes=["tkinter", "unittest", "pytest", "pydoc"],
)
# Qt's software OpenGL fallback (20 MB) and translations aren't used by Saywell's widgets.
a.binaries = [b for b in a.binaries if "opengl32sw" not in b[0].lower()]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/").lower()]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Saywell",
    icon=os.path.join(ROOT, "saywell", "assets", "saywell.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Saywell", upx=False)
