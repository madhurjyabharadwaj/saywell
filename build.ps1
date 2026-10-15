# Builds dist\Saywell\Saywell.exe and dist\Saywell-windows.zip (the file to share).
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -q --disable-pip-version-check -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
# Pre-generate the UI Automation bindings so they get bundled instead of generated on first run.
& $py -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"
& $py -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build packaging\saywell.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Compress-Archive -Path dist\Saywell -DestinationPath dist\Saywell-windows.zip -Force
Write-Host "Built dist\Saywell\Saywell.exe and dist\Saywell-windows.zip"
