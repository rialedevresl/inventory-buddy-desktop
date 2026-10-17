"""Double-click this file to start Inventory Buddy Desktop.

It opens the app in its own window, with no console. Needs Python 3.10 or
newer from python.org (Python is signed, so Windows' Smart App Control
allows it). For a desktop shortcut: right-click this file > Show more options
> Send to > Desktop (create shortcut).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def tell(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Inventory Buddy Desktop", 0x10)
    except Exception:  # noqa: BLE001 - not Windows: print instead
        print(text)


if sys.version_info < (3, 10):
    tell("Inventory Buddy Desktop needs Python 3.10 or newer.\n\n"
         f"This computer opened it with Python {sys.version.split()[0]}. "
         "Install the latest Python from python.org, then try again.")
    sys.exit(1)

sys.path.insert(0, str(HERE))

# With no console there's nowhere for messages to go, so they go to a log in the settings folder.
try:
    from slip.categories import data_dir
    log = open(data_dir() / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
except Exception:  # noqa: BLE001
    pass

try:
    import desktop
    sys.exit(desktop.main())
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    tell(f"Inventory Buddy Desktop couldn't start:\n\n{exc}")
    sys.exit(1)
