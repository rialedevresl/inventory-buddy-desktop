"""SLInventoryCleanupBridge - the small program Firestorm starts for the installed app.

It talks to Firestorm over its standard input/output (that's how Firestorm's
LEAP plug-ins work), so it's built as a console program. If Windows gives it
a console window anyway, it lets go of it right away and the window closes.
"""
import sys


if __name__ == "__main__":
    from slip.bridge_plugin import main      # main() lets go of the console window first thing
    sys.exit(main())
