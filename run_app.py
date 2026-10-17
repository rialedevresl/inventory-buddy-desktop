"""Inventory Buddy Desktop - start the app.

    py run_app.py

Opens the app in your web browser. Everything runs on this computer; the
page is only reachable from this computer. Close this window to quit.
This version only reads your inventory - it never changes anything.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slip.server import AppState, serve  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--cache-dir", type=Path, action="append", default=[],
                    help="Extra folder to look for Firestorm's inventory cache in")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--offline", action="store_true", help="Testing: use the saved inventory, no Firestorm")
    args = ap.parse_args()

    state = AppState(args.cache_dir, offline=args.offline)
    httpd = serve(state, args.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print("Inventory Buddy Desktop is running at", url)
    print("Close this window (or press Ctrl+C) to quit.")
    sys.stdout.flush()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
