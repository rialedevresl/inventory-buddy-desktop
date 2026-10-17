<p align="center"><img src="docs/icon.png" width="128" alt="Inventory Buddy Desktop"></p>

# Inventory Buddy Desktop — v1.0.0

**An inventory organizer for Second Life®**, made by
[Ria Ledevre](https://www.instagram.com/ledeverse/), the creator of Inventory Buddy.

It reads your inventory, helps you sort it, and - only when you press Run - makes the
changes in Firestorm for you, with every step checked and an undo. It never sees your
password. Free to use, and the code is public so you can see exactly what it does.

## Start it (Windows)

The simplest way, which works on every PC: get Python once from python.org,
download **Inventory-Buddy-Desktop-<version>.zip**, extract it, and double-click
**Start Inventory Buddy Desktop**. The app opens in its own window, with no
console. `HOW TO START.txt` in the zip walks through it.

## Install it with the Setup file (experimental)

A little honesty about the installer: Windows fully trusts apps from companies that pay
for a code-signing certificate every year. I'm one person making a free tool, so the
installer isn't signed (yet!). Windows may show a blue **"Windows protected your PC"**
box. That's Windows being careful with anything it doesn't recognize, not a sign that
anything is wrong. On some newer PCs, **Smart App Control** blocks unsigned apps
completely, and there's no way around it. If that happens, the zip works everywhere.

1. Download **Inventory-Buddy-Desktop-Setup-<version>.exe** from the [Releases page](https://github.com/rialedevresl/inventory-buddy-desktop/releases).
2. Run it. Windows may say "Windows protected your PC" because the app isn't
   signed yet: press **More info**, then **Run anyway**.
3. Open **Inventory Buddy Desktop** from the Start menu (or the desktop shortcut).

It opens in its own window. Close the window when you're done; the app
quits by itself shortly after (it stays running while Firestorm is connected
or a run is going, and opening it again brings the window back).

Your categories, choices and run history live in
`%APPDATA%\SL Inventory Cleanup` (the app's earlier name), so they carry over between versions and
stay if you uninstall.

## Run it from the source code (for development)

    py desktop.py      # the app in its own window, like the installed version
    py run_app.py      # the app in your browser, with a console window

The installer is built by GitHub on every push (see
`.github/workflows/build-windows.yml`); tag a version (`v1.0.0`) to publish
it on the Releases page.

When it opens you'll see one screen: **Let's get your inventory**.

1. Quit Firestorm if it's open, then press **Start Firestorm**.
2. Log in as usual (the app never sees your password).
3. The app reads your inventory fresh from Firestorm, then the rest of the
   app appears. If you close Firestorm, the app locks again until you
   reconnect - your sorting choices are kept.

## What's in this version

- **Overview**: your real numbers (items, repeated items split into real
  items vs. store packaging, product folders, Trash, empty folders) and a
  map of your inventory by item type.
- **Sort**: the app suggests a category for every product folder and loose
  item, using keyword rules plus what it learns from your existing category
  folders. Check one category at a time: pictures first, then the rest.
  Drag things onto another category (or use **Move…**), select several at
  once, and press **Looks good** to check a category and go to the next.
  Things it can't place confidently go to **Not sure yet**, with its best
  guesses as one-click buttons. "Copy already here" marks leftover originals
  of things you already sorted. Your choices are saved; nothing changes in
  Second Life yet. When Run arrives, it will only move things you moved
  yourself or that sit in a category you checked — never unchecked
  suggestions.
- **Folders**: browse your inventory like Firestorm, plus search. Product
  folders (one product's pieces: e.g. a hairstyle's mesh, tattoo layers,
  alpha and HUD) are marked **Product** and will be sorted as one unit.
  Clothing and body parts show their real type (Tattoo layer, Alpha,
  Skin, Shape…).
- **Categories**: the sorting categories: the Inventory Buddy decor
  categories (now with short names, e.g. Decor › Mirrors) plus clothing,
  shoes, jewelry, accessories, hair, head & face, body, held accessories,
  animations and pets. Your existing folders are recognised by their old
  names too (e.g. "Decor - Mirrors", "Legacy Clothing › Tops"). Add, rename or remove top categories and subcategories.
  Changes save automatically to
  `%APPDATA%\SL Inventory Cleanup\categories.json`.

- **Thumbnails**: items and folders that have a Second Life thumbnail show
  it. Images come from Second Life's picture service (only the thumbnail's
  texture ID is sent) and are kept in
  `%APPDATA%\SL Inventory Cleanup\thumbs` so each is fetched once. Use the
  Thumbnails switch at the top to turn them off.

- Second Life's built-in **Library** (its own Clothing, Objects, Accessories
  folders and so on) is skipped: it's read-only and kept separate from
  your inventory.

- **Order**: on Folders and Sort, show things by name, newest first or
  oldest first (by when they arrived in your inventory). Each item shows
  the month you got it.

- **Plan & Run**: review everything that will change (moves by category,
  new folders, renames to the short names, and anything marked for Trash),
  then press **Start Firestorm with Inventory Cleanup**, log in, and **Run**.
  Only things you moved yourself or that sit in a category you checked are
  in the plan. Don't click in Firestorm while it runs. Pause, stop, and
  **Undo this run** are on the same screen. Trash is Firestorm's Trash and
  is never emptied.
- New folders are made by copying an empty folder. If you have none, make
  one called "Inventory Cleanup Template" in Firestorm.

## Privacy

Everything runs on your computer. The app's page is only reachable from
this computer. The only thing sent out is thumbnail texture IDs to Second
Life's picture service, when thumbnails are switched on.

## Credits

Made by Ria Ledevre for the Second Life community. Built with help from Claude (Anthropic).

## Help me make it better ♡

The sorting learns from how you organize, but it can only get better if I hear what it
gets wrong. If something lands in the wrong category, or anything feels confusing, please
tell me! Item names and where they should have gone help the most.

- **Instagram:** [@ledeverse](https://www.instagram.com/ledeverse/)
- **In-world:** **Ria Ledevre**

## License

Free for your own personal use. The code is here so you can see what it does, but it isn't open for
copying, changing, sharing or selling. See [LICENSE](LICENSE). Want to share it? Link people here.

---

<sub>Second Life® is a trademark of Linden Research, Inc. Inventory Buddy Desktop is not affiliated with or endorsed by Linden Lab.</sub>
