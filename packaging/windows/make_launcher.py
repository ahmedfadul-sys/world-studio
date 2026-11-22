r"""Creates the way to start World Studio on THIS computer, without building an .exe (antivirus programs often break those):
  dist\WorldStudio.vbs  - sets up the conda DLL paths, then starts the launcher with no console window
  a 'World Studio' shortcut on the Desktop pointing at it
Run it with the python of the environment you installed into (installing.bat does it for you):  python packaging\\windows\\make_launcher.py"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
prefix = Path(sys.prefix)
pyw = prefix / "pythonw.exe"
launcher = root / "launcher" / "launcher.py"
for p in (pyw, launcher):
    if not p.exists():
        sys.exit(f"ERROR: {p} not found")

dist = root / "dist"
dist.mkdir(exist_ok=True)
for old in ("WorldStudio.exe", "WorldStudio.json"):          # leftovers of the old .exe approach
    try:
        (dist / old).unlink()
    except OSError:
        pass

extra = [prefix, prefix / "Library" / "mingw-w64" / "bin", prefix / "Library" / "usr" / "bin", prefix / "Library" / "bin", prefix / "Scripts"]
vbs = dist / "WorldStudio.vbs"
vbs.write_text("\r\n".join([
    'Set sh = CreateObject("WScript.Shell")',
    'Set env = sh.Environment("Process")',
    'env("PATH") = "' + ";".join(str(p) for p in extra) + ';" + env("PATH")',
    f'env("CONDA_PREFIX") = "{prefix}"',
    f'sh.CurrentDirectory = "{root}"',
    'sh.Run """' + str(pyw) + '"" ""' + str(launcher) + '""", 0, False',
]) + "\r\n", encoding="utf-8")
print("created", vbs)

if sys.platform == "win32":
    ps = ("$d=[Environment]::GetFolderPath('Desktop');$s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\\World Studio.lnk');"
          f"$s.TargetPath=\"$env:WINDIR\\System32\\wscript.exe\";$s.Arguments='\"{vbs}\"';$s.WorkingDirectory='{root}';"
          f"$s.IconLocation='{pyw},0';$s.Save();Write-Host ('shortcut: '+$d+'\\World Studio.lnk')")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
