"""Packs the ready-to-share zip for the Python version: dist/Inventory-Buddy-Desktop-<version>.zip"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from slip import __version__  # noqa: E402

TOP = "Inventory Buddy Desktop"
FILES = ["Start Inventory Buddy Desktop.pyw", "desktop.py", "run_app.py", "README.md", "LICENSE"]
EXTRA = {"packaging/HOW TO START.txt": "HOW TO START.txt", "packaging/app.ico": "app.ico"}


def main():
    out = ROOT / "dist" / f"Inventory-Buddy-Desktop-{__version__}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            z.write(ROOT / name, f"{TOP}/{name}")
        for src, name in EXTRA.items():
            z.write(ROOT / src, f"{TOP}/{name}")
        for folder in ("slip", "web"):
            for p in sorted((ROOT / folder).rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                    z.write(p, f"{TOP}/{p.relative_to(ROOT).as_posix()}")
    print(out, f"{out.stat().st_size // 1024} KB")
    return out


if __name__ == "__main__":
    main()
