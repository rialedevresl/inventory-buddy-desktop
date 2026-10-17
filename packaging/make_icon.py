"""Builds the app icon (packaging/app.ico) and the window icon (web/icon.png) from packaging/icon-source.png."""
from pathlib import Path
from PIL import Image

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

if __name__ == "__main__":
    here = Path(__file__).parent
    src = Image.open(here / "icon-source.png").convert("RGBA")
    big = src.resize((256, 256), Image.LANCZOS)
    big.save(here / "app.ico", sizes=SIZES)
    big.save(here.parent / "web" / "icon.png", optimize=True)
    print("wrote", here / "app.ico")
