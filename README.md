<p align="center"><img src="docs/icon.png" width="128" alt="Inventory Buddy Desktop"></p>

# Inventory Buddy Desktop

**An inventory organizer for Second Life®**, made by
[Ria Ledevre](https://www.instagram.com/ledeverse/), the creator of Inventory Buddy.

It reads your inventory, suggests where everything belongs, and lets you check its
suggestions. When you press Run, it moves things in Firestorm for you, and every run can
be undone. It never sees your password. It's free, and the code is public so you can
see exactly what it does.

Works with Firestorm on Windows. Current version: **1.0.0**.

## Get started

**The zip (recommended, works on every PC)**

1. Install Python once. It's free from [python.org](https://www.python.org/downloads/).
   The default choices are fine.
2. Download **Inventory-Buddy-Desktop-1.0.0.zip** from the
   [Releases page](https://github.com/rialedevresl/inventory-buddy-desktop/releases).
3. Right-click the zip, choose **Extract All…**, and keep the folder somewhere like Documents.
4. Double-click **Start Inventory Buddy Desktop** in that folder.

The first time, the app adds a shortcut to your desktop so you can start it from there
next time. `HOW TO START.txt` in the zip has the same steps.

**The Setup file (experimental)**

A little honesty about the installer: Windows fully trusts apps from companies that pay
for a code-signing certificate every year. I'm one person making a free tool, so the
installer isn't signed (yet!).

1. Download **Inventory-Buddy-Desktop-Setup-1.0.0.exe** from the
   [Releases page](https://github.com/rialedevresl/inventory-buddy-desktop/releases).
2. Run it. If Windows shows a blue **"Windows protected your PC"** box, press
   **More info**, then **Run anyway**. That's Windows being careful with anything it
   doesn't recognize, not a sign that something is wrong.
3. Open **Inventory Buddy Desktop** from the Start menu or the desktop shortcut.

On some newer PCs, **Smart App Control** blocks unsigned apps completely, with no way
around it. If that happens, use the zip instead.

## How to use it

1. **Quit Firestorm** if it's open. The app can only connect when it starts Firestorm itself.
2. Press the start button in the app. Firestorm opens, and you log in like usual.
3. The app reads your inventory, then the rest of the app opens up.

Then:

- **Overview** shows what's in your inventory: items, repeats, store packaging, empty folders and more.
- **Sort** is where most of the work happens. The app suggests a category for every product
  folder and loose item. Go through one category at a time, drag or use **Move…** to fix
  anything that's wrong, and press **Looks good** when a category is right. Things it can't
  place go to **Not sure yet**, with its best guesses as buttons. Landmarks and windlight
  settings can be sorted here too.
- **Duplicates** finds things you have more than one of, so you can choose what to keep.
- **Plan & Run** shows every change before it happens. Press Run, and don't click in Firestorm
  while it works. You can pause or stop anytime, and **Undo this run** puts everything back.
- **Folders** lets you browse and search your inventory, like in Firestorm.
- **Categories** lets you add, rename or remove categories, and turn folder pictures on or off.

Good to know:

- Nothing changes in Second Life until you press Run. Only things you moved yourself, or that
  sit in a category you checked, are part of a run.
- Anything sent to Trash goes to Firestorm's Trash. The app never empties it.
- If you close Firestorm, the app locks until you start it again. Your choices are kept.
- Close the app's window when you're done. It quits by itself shortly after.
- Your categories, choices and run history are saved in `%APPDATA%\SL Inventory Cleanup`
  (the app's earlier name). They carry over when you update, and stay if you uninstall.

## Privacy

Everything stays on your computer. Your inventory, your sorting choices and
your run history are never sent anywhere, not to me and not to anyone else.
The app opens in its own window, and no other computer can reach it.

The one exception is pictures. If you turn on **Show pictures** (on the
Categories page), the app asks Second Life's own picture service for your
folder images, the same way Firestorm loads them. Only the picture IDs are
sent, nothing about you or your account.

## Help me make it better ♡

The sorting learns from how you organize, but it can only get better if I hear what it
gets wrong. If something lands in the wrong category, or anything feels confusing, please
tell me! Item names and where they should have gone help the most.

- **Instagram:** [@ledeverse](https://www.instagram.com/ledeverse/)
- **In-world:** **Ria Ledevre**

## Credits

Made by Ria Ledevre for the Second Life community. Built with help from Claude (Anthropic).

## License

Free for your own personal use. The code is here so you can see what it does, but it isn't
open for copying, changing, sharing or selling. See [LICENSE](LICENSE). Want to share it?
Link people here.

## For developers

Run it from the source code:

    py desktop.py      # the app in its own window
    py run_app.py      # the app in your browser, with a console window

GitHub builds the zip and installer on every push (`.github/workflows/build-windows.yml`).
Publishing a release with a version tag such as `v1.0.1` attaches them to the Releases page.

---

<sub>Second Life® is a trademark of Linden Research, Inc. Inventory Buddy Desktop is not affiliated with or endorsed by Linden Lab.</sub>
