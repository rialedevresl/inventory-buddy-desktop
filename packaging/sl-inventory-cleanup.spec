# PyInstaller recipe: one folder holding two programs that share the same files.
#   SLInventoryCleanup.exe        - the app (no console window)
#   SLInventoryCleanupBridge.exe  - started by Firestorm; talks to it over stdin/stdout
# Build from the repository root:  pyinstaller packaging/sl-inventory-cleanup.spec
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "app.ico")
datas = [(os.path.join(ROOT, "web"), "web")]

app = Analysis([os.path.join(ROOT, "desktop.py")], pathex=[ROOT], datas=datas,
               hiddenimports=["slip.server", "slip.bridge_plugin"], excludes=["tkinter"])
bridge = Analysis([os.path.join(ROOT, "bridge_main.py")], pathex=[ROOT],
                  hiddenimports=["slip.bridge_plugin", "slip.leap", "slip.llsd"], excludes=["tkinter"])

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="SLInventoryCleanup",
              icon=ICON, console=False, upx=False)
bridge_exe = EXE(PYZ(bridge.pure), bridge.scripts, [], exclude_binaries=True, name="SLInventoryCleanupBridge",
                 icon=ICON, console=True, upx=False)

COLLECT(app_exe, app.binaries, app.datas, bridge_exe, bridge.binaries, bridge.datas,
        name="SLInventoryCleanup", upx=False)
