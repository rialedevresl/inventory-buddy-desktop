/* Inventory Buddy Desktop - UI. Plain JS, no libraries. All names from the
   inventory are inserted as text (never as HTML). */
"use strict";

const TOKEN = document.querySelector('meta[name="app-token"]').content;
// v0.8/v0.9 additions (kept here so app.css doesn't need replacing).
document.head.append(Object.assign(document.createElement("style"), { textContent: `
  .act { margin-top: 6px; display: flex; flex-direction: column; gap: 6px; }
  .act-btn { align-self: flex-start; font-size: 0.85em; padding: 2px 10px; }
  .actions { display: flex; flex-direction: column; gap: 6px; }
  .actions .sfoot { flex-wrap: wrap; gap: 6px; }
  .fwrap { display: flex; flex-direction: column; }
  .stree .manual { margin-top: 14px; }
  .stree .manual summary { cursor: pointer; }
  a.sug { text-decoration: none; }
  .items-h { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .items-h .section-t { margin-right: auto; }
  .tile.pickable { cursor: pointer; }
  .tile.pickable:hover { border-color: var(--accent); }
  .tile.sel { outline: 3px solid var(--accent); outline-offset: -1px; background: #F7F3FD; }
  .tile .pick { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .tile .pick input { width: 18px; height: 18px; accent-color: var(--accent); }
  .chip.mark-trash { background: #FBE3DA; color: #9A2E12; }
  .chip.mark-move { background: var(--accent-soft); color: var(--accent-dark); }
  .itembar { position: sticky; top: 70px; z-index: 5; }
` }));
const view = document.getElementById("view");
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const clean = (list) => list.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false);

// ------------------------------------------------------------------ helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const ICONS = {
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  kit: "M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5",
  object: "M12 3l8 4.5v9L12 21l-8-4.5v-9z",
  clothing: "M8 4l4 2 4-2 4 3-2 4h-2v9H8v-9H6L4 7z",
  bodypart: "M12 4a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM6 21v-4a6 6 0 0 1 12 0v4",
  texture: "M4 5h16v14H4zM4 15l5-5 4 4 3-3 4 4",
  notecard: "M6 3h9l4 4v14H6zM9 12h7M9 16h7M9 8h3",
  landmark: "M12 21s-6-6-6-11a6 6 0 0 1 12 0c0 5-6 11-6 11zM12 8v4",
  animatn: "M7 5l12 7-12 7z",
  callcard: "M4 6h16v12H4zM8 10h4M8 14h8",
  lsltext: "M8 8l-4 4 4 4M16 8l4 4-4 4M13 6l-2 12",
  sound: "M5 10v4h3l4 4V6L8 10zM16 9a4 4 0 0 1 0 6",
  gesture: "M8 13V6a1.5 1.5 0 0 1 3 0v6M11 11V5a1.5 1.5 0 0 1 3 0v6M14 11V7a1.5 1.5 0 0 1 3 0v7a6 6 0 0 1-6 6h-1a5 5 0 0 1-4-2l-2-3",
  material: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3",
  link: "M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  x: "M6 6l12 12M18 6L6 18",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
};
function icon(name, size = 22) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", size); svg.setAttribute("height", size); svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round"); svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path"); p.setAttribute("d", ICONS[name] || ICONS.object);
  svg.append(p);
  return svg;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: { "X-App-Token": TOKEN, ...(opts.body ? { "Content-Type": "application/json" } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: "The app didn't answer properly." }));
  if (res.status === 409 && data.locked) { setLocked(true); setTimeout(tick, 0); }
  if (!res.ok || data.error) throw new Error(data.error || `Error ${res.status}`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

function show(...nodes) {
  view.replaceChildren(...clean(nodes));
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
function showError(err) {
  show(h("div", { class: "panel" }, h("h2", {}, "Couldn't load that"), h("p", { class: "muted" }, err.message || String(err))));
}

let THUMBS_ON = true;
try { THUMBS_ON = localStorage.getItem("thumbs") !== "off"; } catch (e) { /* storage blocked */ }
function thumbBox(cls, tid, iconName, size) {
  const box = h("div", { class: cls }, icon(iconName, size));
  if (THUMBS_ON && tid) {
    // The image sits invisibly in the box (so lazy loading works) and replaces the icon once it arrives.
    const img = h("img", { alt: "", loading: "lazy", decoding: "async", class: "pending",
      src: `/thumb/${tid}.jpg?t=${encodeURIComponent(TOKEN)}` });
    img.addEventListener("load", () => { img.classList.remove("pending"); box.classList.add("has-img"); });
    img.addEventListener("error", () => img.remove());
    box.append(img);
  }
  return box;
}

// ---- ordering by name or by when things arrived in the inventory
let ORDER = "name";
try { ORDER = localStorage.getItem("order") || "name"; } catch (e) { /* storage blocked */ }
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function gotDate(t) {
  if (!t || t < 1041379200) return "";   // before 2003: not a real date (Second Life didn't exist yet)
  const d = new Date(t * 1000);
  return `Got ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}
function ordered(list, nameKey = "name") {
  const out = [...list];
  if (ORDER === "newest") out.sort((a, b) => (b.created || 0) - (a.created || 0));
  else if (ORDER === "oldest") out.sort((a, b) => (a.created || Infinity) - (b.created || Infinity));
  else out.sort((a, b) => String(a[nameKey]).localeCompare(String(b[nameKey]), undefined, { sensitivity: "base" }));
  return out;
}
function orderPicker() {
  const sel = h("select", { class: "order-sel", "aria-label": "Order" },
    [["name", "Name (A–Z)"], ["newest", "Newest first"], ["oldest", "Oldest first"]].map(([v, l]) =>
      h("option", { value: v, selected: ORDER === v ? true : null }, l)));
  sel.addEventListener("change", () => {
    ORDER = sel.value;
    try { localStorage.setItem("order", ORDER); } catch (e) { /* ignore */ }
    route();
  });
  return h("label", { class: "order" }, h("span", { class: "muted small" }, "Order"), sel);
}

const plural = (n, word, many) => `${fmt(n)} ${n === 1 ? word : (many || word + "s")}`;
const PERMS = (p) => !p ? "" : [p.copy ? "Copy" : "No copy", p.mod ? "Mod" : "No mod", p.trans ? "Trans" : "No trans"].join(" · ");
const KIND_ICON = (t) => ICONS[t] ? t : "object";
const PACK = new Set(["notecard", "landmark", "callcard"]);

// ------------------------------------------------------------------ inventory picker
async function loadPicker() {
  const sel = document.getElementById("inv-pick");
  const { inventories, current } = await api("/api/inventories");
  sel.replaceChildren(...inventories.map((inv, i) =>
    h("option", { value: inv.path, selected: inv.path === current ? true : null },
      `Inventory ${i + 1} · saved ${inv.saved}`)));
  if (!inventories.length) sel.append(h("option", {}, "No inventory found"));
}
document.getElementById("inv-pick").addEventListener("change", async (e) => {
  try { await api("/api/open", { method: "POST", body: { path: e.target.value } }); toast("Switched inventory"); route(); }
  catch (err) { showError(err); }
});
document.getElementById("rescan").addEventListener("click", async () => {
  if (!OFFLINE) {
    try { await api("/api/scan", { method: "POST", body: {} }); toast("Reading your inventory again…"); lastScan = "scanning"; tick(); }
    catch (err) { toast(err.message); }
    return;
  }
  const sel = document.getElementById("inv-pick");
  try { await api("/api/open", { method: "POST", body: { path: sel.value || null } }); await loadPicker(); toast("Rescanned"); route(); }
  catch (err) { showError(err); }
});

// ------------------------------------------------------------------ overview
function typeMap(types) {
  let list = types.filter((t) => !["link", "link_f"].includes(t.type) && t.count > 0);
  const total = list.reduce((a, t) => a + t.count, 0) || 1;
  // Boxes under ~2.5% of the inventory are too small to read: group them into one "Other" box.
  const small = list.filter((t) => t.count / total < 0.025);
  list = list.filter((t) => t.count / total >= 0.025);
  if (small.length === 1) { list.push(small[0]); small.length = 0; }
  if (small.length) list.push({ type: "other", label: `Other (${small.length} types)`, count: small.reduce((a, t) => a + t.count, 0), other: true });
  const blk = (t, big) => h("div", {
    class: "blk" + (big ? " big" : "") + (t.packaging ? " pack" : "") + (t.other ? " other" : ""),
    role: "img", style: { flex: `${t.count} 1 0` },
    "aria-label": `${t.label}: ${fmt(t.count)} items${t.packaging ? ", often packaging" : ""}`,
  }, h("b", {}, fmt(t.count)), h("span", {}, t.label));
  const [first, ...rest] = list;
  if (!first) return h("p", { class: "muted" }, "No items.");
  const restTotal = rest.reduce((a, t) => a + t.count, 0);
  const rows = [[], [], []]; const weights = [0, 0, 0];
  let r = 0;
  for (const t of rest) {
    if (weights[r] >= restTotal / 3 && r < 2) r++;
    rows[r].push(t); weights[r] += t.count;
  }
  const right = h("div", { class: "col", style: { flex: `${restTotal} 1 0` } },
    rows.filter((x) => x.length).map((row, i) =>
      h("div", { class: "row", style: { flex: `${Math.max(weights[i], restTotal * 0.22)} 1 0` } }, row.map((t) => blk(t, false)))));
  const map = h("div", { class: "map" }, h("div", { class: "col", style: { flex: `${first.count} 1 0` } },
    h("div", { class: "row", style: { flex: "1 1 0" } }, blk(first, true))), rest.length ? right : null);
  const others = small.length ? h("p", { class: "others" }, h("b", {}, "Other: "),
    small.map((t, i) => [i ? " · " : "", h("span", { class: t.packaging ? "opack" : "" }, `${t.label} ${fmt(t.count)}`)])) : null;
  return [map, others];
}

async function overview() {
  const o = await api("/api/overview");
  const dupTotal = o.dup_extra + o.dup_packaging || 1;
  show(
    h("section", { class: "head" },
      h("div", {}, h("p", { class: "muted small" }, `${o.live ? "Read live from Firestorm" : "Saved by Firestorm"} ${o.saved} · ${plural(o.folders, "folder")} · ${plural(o.creators, "creator")}`),
        h("h1", {}, `${fmt(o.items)} items. Here’s where to start.`))),
    h("section", { class: "cards", "aria-label": "Cleanup opportunities" },
      h("a", { class: "card hero", href: "#/duplicates", "aria-label": `Repeated items: ${fmt(o.dup_extra + o.dup_packaging)} extra copies. Open Duplicates` },
        h("span", { class: "t" }, "Repeated items"),
        h("span", { class: "n" }, fmt(o.dup_extra + o.dup_packaging), " ", h("small", {}, "extra copies")),
        h("div", { class: "split", role: "img", "aria-label": `${fmt(o.dup_extra)} duplicate items, ${fmt(o.dup_packaging)} packaging` },
          h("div", { style: { width: `${(100 * o.dup_extra) / dupTotal}%` } })),
        h("div", { class: "legend" },
          h("span", {}, h("i", { style: { background: "#7B52C9" } }), h("b", {}, fmt(o.dup_extra)), " duplicate items to sort out on the Duplicates page"),
          h("span", {}, h("i", { style: { background: "#F6D9BF" } }), h("b", {}, fmt(o.dup_packaging)), " store packaging repeated in product folders (“Clean out packaging” on Sort)"))),
      h("a", { class: "card", href: "#/folders" }, h("span", { class: "t" }, "Product folders"),
        h("span", { class: "n" }, fmt(o.kits)),
        h("span", { class: "d" }, "Folders that hold one product. They move as a whole — you can split one up if you want.")),
      h("div", { class: "card" }, h("span", { class: "t" }, "Landmarks, notecards & calling cards"),
        h("span", { class: "n" }, fmt(o.packaging)), h("span", { class: "d" }, "Mostly come in product boxes. “Clean out packaging” on the Sort screen marks them for Trash.")),
      h("div", { class: "card" }, h("span", { class: "t" }, "Items with thumbnails"), h("span", { class: "n" }, fmt(o.thumbs)),
        h("span", { class: "d" }, o.folder_thumbs ? `Plus ${plural(o.folder_thumbs, "folder")}. The rest show a type icon.` : "The rest show a type icon.")),
      h("div", { class: "card" }, h("span", { class: "t" }, "Quick tidy-up"),
        h("div", { class: "pair" },
          h("span", {}, h("span", { class: "n" }, fmt(o.empty_folders)), h("span", { class: "d" }, "empty folders")),
          h("span", {}, h("span", { class: "n" }, fmt(o.trash)), h("span", { class: "d" }, "in Trash"))),
        h("span", { class: "d" }, "Not counting system folders. Trash still counts until it’s emptied."))),
    h("section", { class: "panel", "aria-labelledby": "map-h" },
      h("div", { class: "head" }, h("h2", { id: "map-h" }, "What your inventory is made of"),
        h("div", { class: "legend" },
          h("span", {}, h("i", { style: { background: "#E6DEF6" } }), "Item type"),
          h("span", {}, h("i", { style: { background: "#F6D9BF" } }), "Often packaging"),
          h("span", {}, "Box size = number of items"))),
      typeMap(o.types)),
  );
}

// ------------------------------------------------------------------ duplicates
let DUP_SHOW = 60;
async function keepCopy(id, undo) {
  try {
    const r = await api("/api/duplicates/keep", { method: "POST", body: { keep: id, undo: !!undo } });
    TREE = r.tree; setPlanBadge(r.tree);
    toast(undo ? "Undone. All copies stay where they are." : `Keeping this one. ${plural(r.count, "other copy", "other copies")} marked for Trash.`);
    route({ keepScroll: true });
  } catch (err) { toast(err.message); }
}

function dupGroup(g) {
  const isProduct = g.kind === "product";
  return h("section", { class: "panel dup" + (g.decided ? " done" : "") },
    h("div", { class: "dup-head" },
      thumbBox("dup-th", g.thumb, isProduct ? "kit" : KIND_ICON(g.type), 24),
      h("div", { class: "dup-title" },
        h("b", {}, g.name || "(no name)"),
        h("span", { class: "muted small" }, `${g.count} copies · ${g.label}`)),
      g.decided ? h("button", { type: "button", class: "btn", onclick: () => keepCopy(g.copies[0].id, true) }, "Undo") : null,
      !g.hidden && !g.all_gone ? h("button", { type: "button", class: "btn danger", title: "You don’t want this at all: mark every copy for Trash",
        onclick: () => trashAll(g) }, "Trash all copies") : null,
      h("button", { type: "button", class: "btn", title: g.hidden ? "Put this set back on the list" : "Take this set off the list. It stays hidden on later scans.",
        onclick: () => hideDup(g, !g.hidden) }, g.hidden ? "Show again" : "Not duplicates")),
    h("ul", { class: "dup-list" }, g.copies.map((c) => h("li", { class: "dup-row " + c.state },
      h("div", { class: "dup-where" },
        h("a", { href: `#/folders/${c.folder}` }, c.where),
        h("span", { class: "chips" },
          c.sorted ? h("span", { class: "chip kit" }, `Already in ${c.sorted}`) : null,
          c.created && gotDate(c.created) ? h("span", { class: "chip" }, gotDate(c.created)) : null,
          c.nocopy ? h("span", { class: "chip warn" }, "No copy") : null,
          c.package ? h("span", { class: "chip info" }, "Stays: part of what’s in this folder") : null,
          c.state === "trash" ? h("span", { class: "chip mark-trash" }, "Marked for Trash") : null,
          c.state === "keep" && g.decided ? h("span", { class: "chip mark-move" }, "Keeping") : null,
          c.suggested ? h("span", { class: "chip info" }, c.why ? `Suggested keep: ${c.why}` : "Suggested keep") : null)),
      (c.state === "keep" && g.decided) || g.hidden ? null
        : h("button", { type: "button", class: "btn" + (c.suggested ? " primary" : ""), onclick: () => keepCopy(c.id) }, "Keep this one")))));
}

async function trashAll(g) {
  try {
    const r = await api("/api/duplicates/trash-all", { method: "POST", body: { id: g.copies[0].id } });
    TREE = r.tree; setPlanBadge(r.tree);
    toast(`${plural(r.count, "copy", "copies")} marked for Trash. Nothing is deleted until you run the plan.` +
      (r.kept ? ` ${plural(r.kept, "copy", "copies")} inside other folders stayed; trash ${r.kept === 1 ? "it" : "them"} from there if you want.` : ""));
    route({ keepScroll: true });
  } catch (err) { toast(err.message); }
}

async function hideDup(g, hide) {
  try {
    if (hide && g.decided) await api("/api/duplicates/keep", { method: "POST", body: { keep: g.copies[0].id, undo: true } });
    await api("/api/duplicates/hide", { method: "POST", body: { key: g.key, hide } });
    toast(hide ? "Taken off the list. “Show hidden” at the bottom brings it back." : "Back on the list.");
    route({ keepScroll: true });
  } catch (err) { toast(err.message); }
}

let DUP_HIDDEN = false;
async function duplicatesPage() {
  const d = await api("/api/duplicates" + (DUP_HIDDEN ? "?hidden=1" : ""));
  const open = d.groups.filter((g) => !g.decided), done = d.groups.filter((g) => g.decided);
  const list = [...open, ...done];
  show(
    h("section", { class: "head" },
      h("div", {},
        h("h1", {}, "Duplicates"),
        h("p", { class: "muted" }, d.groups.length
          ? `${plural(d.groups.length, "thing")} you have more than one exact copy of (${plural(d.extra, "extra copy", "extra copies")}). ` +
            "Pick the copy to keep and the others are marked for Trash. Nothing changes until you run the plan on Plan & Run."
          : DUP_HIDDEN ? "Nothing hidden." : "No duplicates left to sort out. Products only count as copies when the folder name and everything inside match. Repeated store packaging (notecards, landmarks) is handled by “Clean out packaging” on the Sort page."),
        DUP_HIDDEN ? null : h("p", { class: "muted small" }, "Things that came inside different packages (each head’s own alpha, say) aren’t counted. " +
          "If a set still isn’t really duplicates, press “Not duplicates” to take it off the list."))),
    DUP_HIDDEN ? h("div", { class: "banner" }, h("div", {}, h("b", {}, "Hidden sets. "), "Press “Show again” to put one back on the list."),
      h("button", { type: "button", class: "btn", onclick: () => { DUP_HIDDEN = false; route(); } }, "Back to duplicates")) : null,
    !DUP_HIDDEN && open.length ? h("div", { class: "banner" },
      h("div", {}, h("b", {}, `${plural(open.length, "set")} still to decide. `),
        "“Keep one of each” keeps the suggested copy in every set: one already sorted into a category, then one in your own folders, otherwise the newest. " +
        "Sets where every copy is no-copy are skipped, since that’s how you rez more than one."),
      h("button", { type: "button", class: "btn primary", onclick: async () => {
        try {
          const r = await api("/api/duplicates/keep-all", { method: "POST", body: {} });
          TREE = r.tree; setPlanBadge(r.tree); toast(`${plural(r.count, "copy", "copies")} marked for Trash`); route({ keepScroll: true });
        } catch (err) { toast(err.message); } } }, `Keep one of each (${fmt(open.length)})`)) : null,
    h("div", { class: "dups" }, list.slice(0, DUP_SHOW).map(dupGroup)),
    list.length > DUP_SHOW ? h("button", { type: "button", class: "btn", onclick: () => { DUP_SHOW += 60; route({ keepScroll: true }); } },
      `Show more (${fmt(list.length - DUP_SHOW)} left)`) : null,
    !DUP_HIDDEN && d.hidden ? h("p", {}, h("button", { type: "button", class: "btn", onclick: () => { DUP_HIDDEN = true; route(); } },
      `Show hidden (${fmt(d.hidden)})`)) : null,
  );
}

// ------------------------------------------------------------------ acting on things from My Inventory & Search
let TREE = null;   // category list for the "Move to…" menus; refreshed after every change
async function getTree(fresh) {
  if (!TREE || fresh) TREE = await api("/api/sort/tree");
  return TREE;
}

async function keepTogether(folder, on) {
  const r = await api("/api/sort/keep", { method: "POST", body: { folder, on } });
  TREE = r.tree; setPlanBadge(r.tree);
  toast(on ? "Kept together — it now moves as one product" : "Back to the app’s own judgement");
  route();
}

async function splitUnit(unit, name) {
  const r = await api("/api/sort/split", { method: "POST", body: { unit } });
  TREE = r.tree; setPlanBadge(r.tree);
  toast(`Split “${name}” — its pieces are now sorted one by one`);
  route();
}

async function undoChoice(units, msg) {
  const r = await api("/api/sort/unassign", { method: "POST", body: { units } });
  TREE = r.tree; setPlanBadge(r.tree);
  toast(msg || "Your choice was undone");
  route();
}

const labelOf = (sel) => sel.value === "unsure" ? "Not sure yet" : sel.value === "trash" ? "Trash"
  : sel.selectedOptions[0].textContent.replace(" ✓ (headed here)", "");

// What moves when you act on this item or folder, where it's headed, and the buttons to change that.
async function actionPanel(kind, id) {
  const box = h("div", { class: "actions" }, h("span", { class: "muted small" }, "Checking…"));
  const fill = (...kids) => box.replaceChildren(...clean(kids));
  try {
    const [info, tree] = await Promise.all([api(`/api/sort/locate?kind=${kind}&id=${encodeURIComponent(id)}`), getTree()]);
    if (!info.movable) {
      fill(
        h("span", { class: "muted small" }, info.reason),
        info.skipped ? h("button", { type: "button", class: "btn ghost", onclick: () => skipFolder(info.skip_root, false, info.skip_name) },
          info.skip_root === id ? "Sort this folder again" : `Sort “${info.skip_name}” again`) : null,
        info.can_join ? h("button", { type: "button", class: "btn ghost", onclick: () => keepTogether(id, true).catch((e) => toast(e.message)) },
          "Treat as one product") : null,
        kind === "folder" && !info.skipped && !info.manual && info.reason !== "This is your whole inventory." &&
          info.reason !== "System folders can't be moved." ? skipButton(id) : null);
      return box;
    }
    const piece = info.kind === "piece";
    const mine = info.how === "you";
    // Hide the option it already has; a piece with no choice of its own can go anywhere.
    const move = categoryOptions(tree, mine ? info.dest : piece ? "unsure" : info.dest);
    move.addEventListener("change", () => {
      if (!move.value) return;
      moveUnits([info.unit], move.value, labelOf(move)).catch((err) => toast(err.message));
    });
    let destLine;
    if (mine && info.dest === "trash") destLine = "Marked for Trash — you’ll review it on Plan & Run before anything happens";
    else if (mine) destLine = `You’re sending it to ${info.dest_name}`;
    else if (info.how === "with_product") destLine = info.dest === "unsure" ? "Stays with its product (the product isn’t sorted yet)"
      : info.here ? `Stays with its product, already in ${info.dest_name}`
      : `Stays with its product, headed to ${info.dest_name}`;
    else if (info.how === "stays") destLine = "Stays where it is unless you move or trash it";
    else if (info.dest === "unsure") destLine = "Not sure yet — pick a category";
    else if (info.here) destLine = `Already in ${info.dest_name}`;
    else destLine = `Headed to ${info.dest_name}${info.how === "suggested" ? " (the app’s guess — not in the plan until you check that category)" : ""}`;
    const linkable = mine || !["with_product", "stays"].includes(info.how);
    fill(
      h("div", { class: "small" },
        piece && info.inside ? h("div", {}, "Inside the product “", h("b", {}, info.inside),
          "”. These buttons act on this one item only — the rest of the product stays together.") : null,
        !piece && info.inside ? h("div", {}, "Part of the product “", h("b", {}, info.inside), "” — it moves with the whole folder.") : null,
        h("div", {}, linkable ? h("a", { href: `#/sort/${info.dest}` }, destLine) : destLine)),
      mine && info.dest === "trash" && info.nocopy ? h("span", { class: "chips" }, h("span", { class: "chip warn" }, "No copy — this is your only one")) : null,
      h("div", { class: "sfoot" }, move,
        !(mine && info.dest === "trash") ? h("button", { type: "button", class: "icon-btn trash-btn",
          title: piece ? "Mark just this item for Trash (you'll review it before anything happens)" : "Mark for Trash (you'll review it before anything happens)",
          "aria-label": "Mark for Trash", onclick: () => moveUnits([info.unit], "trash", "To Trash (marked — review before running)").catch((e) => toast(e.message)) },
          icon("trash", 18)) : null,
        mine ? h("button", { type: "button", class: "btn ghost", onclick: () =>
          undoChoice([info.unit], mine && info.dest === "trash" ? "Kept — not going to Trash" : "Your choice was undone").catch((e) => toast(e.message)) },
          info.dest === "trash" ? "Don’t trash" : "Undo my choice") : null,
        info.kind === "product" ? h("button", { type: "button", class: "btn ghost", onclick: () => splitUnit(info.unit, info.name).catch((e) => toast(e.message)) },
          "Split into pieces") : null,
        info.joined ? h("button", { type: "button", class: "btn ghost", onclick: () => keepTogether(info.unit.slice(2), false).catch((e) => toast(e.message)) },
          "Stop keeping together") : null,
        kind === "folder" ? skipButton(id) : null));
  } catch (err) {
    fill(h("span", { class: "err small" }, err.message));
  }
  return box;
}

// Skipping a folder: the sorter leaves it (and everything in it) alone.
function skipButton(id) {
  return h("button", { type: "button", class: "btn ghost",
    title: "Leave this folder alone: nothing in it is sorted, moved, renamed or trashed. Good for folders you've already organized.",
    onclick: () => skipFolder(id, true) }, "Skip this folder");
}
async function skipFolder(id, on, name) {
  try {
    const r = await api("/api/sort/skip", { method: "POST", body: { folder: id, on } });
    TREE = r.tree; setPlanBadge(r.tree);
    toast(on ? "Skipped. Nothing in this folder will be sorted, moved or trashed." : `${name ? `“${name}”` : "This folder"} will be sorted again.`);
    route({ keepScroll: true });
  } catch (err) { toast(err.message); }
}

// A small "Actions" button that opens the panel only when asked (so big folders stay quick).
function actionsToggle(kind, id) {
  const slot = h("div", { class: "act-slot" });
  const btn = h("button", { type: "button", class: "btn ghost act-btn", "aria-expanded": "false",
    onclick: async (e) => {
      e.preventDefault(); e.stopPropagation();
      if (slot.firstChild) { slot.replaceChildren(); btn.setAttribute("aria-expanded", "false"); btn.textContent = "Move / Trash…"; return; }
      btn.setAttribute("aria-expanded", "true"); btn.textContent = "Close";
      slot.replaceChildren(await actionPanel(kind, id));
    } }, "Move / Trash…");
  return h("div", { class: "act" }, btn, slot);
}

// ------------------------------------------------------------------ folders
function kindChips(summary, max = 4) {
  const kinds = summary.kinds.slice(0, max).map(([k, n]) => h("span", { class: "chip" }, `${n} ${k}${n > 1 && !/s$/.test(k) ? "s" : ""}`));
  if (summary.kinds.length > max) kinds.push(h("span", { class: "chip" }, `+${summary.kinds.length - max} more`));
  return kinds;
}

function folderCard(f, extraLine) {
  return h("a", { class: "fcard" + (f.kit ? " kit" : ""), href: `#/folders/${f.id}` },
    thumbBox("ic", f.thumb, f.kit ? "kit" : "folder", 22),
    h("span", { class: "body" },
      h("span", { class: "name" }, f.name || "(no name)"),
      extraLine ? h("span", { class: "muted small" }, extraLine) : null,
      h("span", { class: "chips" },
        f.kit ? h("span", { class: "chip kit" }, f.joined ? "Product (you kept it together)" : "Product") : null,
        f.split ? h("span", { class: "chip" }, "Split") : null,
        f.skipped ? h("span", { class: "chip sys" }, "Skipped") : null,
        f.manual ? h("span", { class: "chip sys" }, "Left for you to sort") : f.system ? h("span", { class: "chip sys" }, "System folder") : null,
        f.kit ? kindChips(f.summary, 3) :
          h("span", { class: "chip" }, `${fmt(f.items)} item${f.items === 1 ? "" : "s"}${f.folders ? ` · ${fmt(f.folders)} folder${f.folders === 1 ? "" : "s"}` : ""}`))));
}

const canAct = (it) => !it.manual && !["link", "link_f"].includes(it.type);

function markChip(mark) {
  if (!mark) return null;
  if (mark.cat === "trash") return h("span", { class: "chip mark-trash" }, "Marked for Trash");
  if (mark.cat === "unsure") return h("span", { class: "chip" }, "You set: Not sure yet");
  return h("span", { class: "chip mark-move" }, `Moving to ${mark.name}`);
}

// Item selection on a folder page (tick several pieces, then trash or move them together).
let itemSelMode = false;
let itemSel = new Set();
let itemSelFolder = null;

function itemTile(it, extraLine, withActions = true, pickable = false) {
  const picking = pickable && itemSelMode && canAct(it);
  const tile = h("div", { class: "tile" + (picking ? " pickable" : "") + (picking && itemSel.has(it.id) ? " sel" : "") },
    thumbBox("th" + (PACK.has(it.type) ? " pack" : ""), it.thumb, KIND_ICON(it.type), 30),
    h("span", { class: "nm" }, it.name || "(no name)"),
    h("span", { class: "kd" }, it.kind, it.perms ? ` · ${PERMS(it.perms)}` : ""),
    it.created ? h("span", { class: "kd" }, gotDate(it.created)) : null,
    extraLine ? h("span", { class: "kd" }, extraLine) : null,
    (it.perms && !it.perms.copy) || it.mark ? h("span", { class: "chips" },
      it.perms && !it.perms.copy ? h("span", { class: "chip warn" }, "No copy") : null, markChip(it.mark)) : null,
    picking ? h("label", { class: "pick" }, h("input", { type: "checkbox", checked: itemSel.has(it.id) ? true : null,
      tabindex: "-1", "aria-hidden": "true" }), itemSel.has(it.id) ? "Selected" : "Select") : null,
    withActions && !picking && canAct(it) ? actionsToggle("item", it.id) : null);
  if (picking) {
    tile.setAttribute("role", "checkbox");
    tile.setAttribute("aria-checked", itemSel.has(it.id) ? "true" : "false");
    tile.tabIndex = 0;
    const toggle = (e) => {
      e.preventDefault();
      itemSel.has(it.id) ? itemSel.delete(it.id) : itemSel.add(it.id);
      route({ keepScroll: true });
    };
    tile.addEventListener("click", toggle);
    tile.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") toggle(e); });
  }
  return tile;
}

async function actOnSelected(cat, label) {
  const ids = [...itemSel];
  if (!ids.length) return toast("Select some items first.");
  const r = await api("/api/sort/move", { method: "POST", body: { units: ids.map((i) => "item:" + i), category: cat } });
  TREE = r.tree; setPlanBadge(r.tree);
  const skipped = ids.length - r.count;
  toast(`${cat === "trash" ? "Marked" : "Moved"} ${plural(r.count, "item")} ${cat === "trash" ? "for Trash" : "to " + label}` +
    (skipped ? ` · ${fmt(skipped)} can’t be moved on their own` : ""));
  itemSel.clear(); itemSelMode = false;
  route({ keepScroll: true });
}

function searchBar(value) {
  const input = h("input", { type: "search", id: "fsearch", placeholder: "Search folders and items by name", value: value || "",
    "aria-label": "Search folders and items" });
  const form = h("form", { class: "toolbar", role: "search", onsubmit: (e) => {
    e.preventDefault(); location.hash = `#/folders?q=${encodeURIComponent(input.value.trim())}`;
  } }, input, h("button", { class: "btn primary", type: "submit" }, "Search"));
  return form;
}

async function folders(id) {
  const f = await api(`/api/folder${id ? `?id=${encodeURIComponent(id)}` : ""}`);
  if (itemSelFolder !== f.id) { itemSelFolder = f.id; itemSelMode = false; itemSel.clear(); }
  const isRoot = f.crumbs.length === 1;
  const crumbs = h("nav", { class: "crumbs", "aria-label": "Folder path" },
    f.crumbs.map((c, i) => [i ? h("span", { class: "sep", "aria-hidden": "true" }, "›") : null,
      i === f.crumbs.length - 1 ? h("span", { "aria-current": "page" }, c.name) : h("a", { href: `#/folders/${c.id}` }, c.name)]));
  const kitBanner = f.kit ? h("div", { class: "banner" }, icon("kit", 28),
    h("div", {}, h("b", {}, "This is one product."),
      h("div", {}, `${fmt(f.summary.pieces)} pieces — they move together, as one folder. To trash or move just some of them, use `,
        h("b", {}, "Select items"), " below or the Move / Trash… button on one item.")),
    h("div", { class: "chips" }, kindChips(f.summary, 8))) : null;
  const skipBanner = f.skipped ? h("div", { class: "banner" },
    h("div", {}, h("b", {}, f.skipped.self ? "You skipped this folder." : `This is inside “${f.skipped.name}”, a folder you skipped.`),
      h("div", { class: "small" }, "Nothing in it is sorted, moved, renamed or trashed. Its category folders can still receive new things, and the app still learns from how you sorted them.")),
    h("button", { type: "button", class: "btn", onclick: () => skipFolder(f.skipped.id, false, f.skipped.name) },
      f.skipped.self ? "Sort it again" : `Sort “${f.skipped.name}” again`)) : null;
  const manualBanner = f.manual ? h("div", { class: "banner" },
    h("div", {}, h("b", {}, "Left for you to sort by hand."),
      h("div", { class: "small" }, "This is a system folder (or inside one). The app never moves anything in it."))) : null;
  const folderActions = !isRoot && !f.manual && !f.system ? h("section", { class: "panel" },
    h("h2", { class: "section-t" }, "This folder"), await actionPanel("folder", f.id)) : null;

  const actable = f.items.filter(canAct);
  let itemBar = null;
  if (itemSelMode) {
    const tree = await getTree();
    const bulk = categoryOptions(tree, "unsure");
    bulk.addEventListener("change", () => {
      if (!bulk.value) return;
      actOnSelected(bulk.value, labelOf(bulk)).catch((e) => toast(e.message));
    });
    itemBar = h("div", { class: "selbar itembar" },
      h("span", {}, itemSel.size ? `${plural(itemSel.size, "item")} selected` : "Click items to select them."),
      bulk,
      h("button", { type: "button", class: "btn", disabled: itemSel.size ? null : true,
        onclick: () => actOnSelected("trash", "Trash").catch((e) => toast(e.message)) }, icon("trash", 16), " Mark for Trash"),
      h("button", { type: "button", class: "btn ghost", onclick: () => { actable.forEach((it) => itemSel.add(it.id)); route({ keepScroll: true }); } }, "Select all"),
      itemSel.size ? h("button", { type: "button", class: "btn ghost", onclick: () => { itemSel.clear(); route({ keepScroll: true }); } }, "Clear") : null,
      itemSel.size && [...itemSel].some((i) => (f.items.find((x) => x.id === i) || {}).mark) ? h("button", { type: "button", class: "btn ghost",
        onclick: () => { const ids = [...itemSel].map((i) => "item:" + i); itemSel.clear(); itemSelMode = false;
          undoChoice(ids, "Your choices for those items were undone").catch((e) => toast(e.message)); } }, "Undo my choices") : null);
  }
  const selectBtn = actable.length ? h("button", { type: "button", class: "btn", "aria-pressed": itemSelMode ? "true" : "false",
    onclick: () => { itemSelMode = !itemSelMode; if (!itemSelMode) itemSel.clear(); route({ keepScroll: true }); } },
    itemSelMode ? "Done selecting" : "Select items") : null;

  show(
    backBar(),
    h("section", { class: "head" }, h("div", {}, crumbs, h("h1", {}, f.name))),
    h("div", { class: "toolbar" }, searchBar(""), orderPicker()),
    skipBanner, kitBanner, manualBanner, folderActions,
    f.folders.length ? h("h2", { class: "section-t" }, `Folders (${fmt(f.folders.length)})`) : null,
    f.folders.length ? h("div", { class: "grid" }, (ORDER === "name" ? f.folders : ordered(f.folders)).map((c) => folderCard(c, c.created && ORDER !== "name" ? gotDate(c.created) : null))) : null,
    f.item_total ? h("div", { class: "items-h" }, h("h2", { class: "section-t" }, `Items (${fmt(f.item_total)})`), selectBtn) : null,
    itemBar,
    f.item_total ? h("div", { class: "items" }, ordered(f.items).map((it) => itemTile(it, null, true, true))) : null,
    f.item_total > f.items.length ? h("p", { class: "muted small" }, `Showing the first ${fmt(f.items.length)}.`) : null,
    !f.folders.length && !f.item_total ? h("div", { class: "panel empty" }, "This folder is empty.") : null,
  );
}

// Search results can be picked in bulk ("everything from this brand is poses").
const folderSel = new Set();

function pickableFolder(f) {
  const on = folderSel.has(f.id);
  const box = h("div", { class: "fpick" + (on ? " sel" : ""), role: "checkbox", tabindex: "0", "aria-checked": on ? "true" : "false" },
    h("label", { class: "pick" }, h("input", { type: "checkbox", checked: on ? true : null, tabindex: "-1", "aria-hidden": "true" }), on ? "Selected" : "Select"),
    folderCard(f, `in ${f.path}`));
  const toggle = (e) => { e.preventDefault(); on ? folderSel.delete(f.id) : folderSel.add(f.id); route({ keepScroll: true }); };
  box.addEventListener("click", toggle);
  box.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") toggle(e); });
  return box;
}

async function actOnSearchSel(cat, label) {
  const units = [...[...folderSel].map((f) => "folder:" + f), ...[...itemSel].map((i) => "item:" + i)];
  if (!units.length) return toast("Select some folders or items first.");
  const r = await api("/api/sort/move", { method: "POST", body: { units, category: cat } });
  TREE = r.tree; setPlanBadge(r.tree);
  const skipped = units.length - r.count;
  toast(`${cat === "trash" ? "Marked" : "Moved"} ${plural(r.count, "thing")} ${cat === "trash" ? "for Trash" : "to " + label}` +
    (skipped ? ` · ${fmt(skipped)} skipped (folders you organized yourself, system folders, or skipped folders don’t move as one)` : ""));
  folderSel.clear(); itemSel.clear(); itemSelMode = false;
  route({ keepScroll: true });
}

async function search(q) {
  if (!q) return folders(null);
  if (itemSelFolder !== "search:" + q) { itemSelFolder = "search:" + q; itemSelMode = false; itemSel.clear(); folderSel.clear(); }
  const r = await api(`/api/search?q=${encodeURIComponent(q)}`);
  const pickFolders = r.folders.filter((f) => !f.manual && !f.system);
  const pickItems = r.items.filter(canAct);
  const n = folderSel.size + itemSel.size;
  let bar = null;
  if (itemSelMode) {
    const tree = await getTree();
    const bulk = categoryOptions(tree, "unsure");
    bulk.addEventListener("change", () => { if (bulk.value) actOnSearchSel(bulk.value, labelOf(bulk)).catch((e) => toast(e.message)); });
    bar = h("div", { class: "selbar itembar" },
      h("span", {}, n ? `${plural(n, "thing")} selected` : "Click folders and items to select them."),
      bulk,
      h("button", { type: "button", class: "btn", disabled: n ? null : true,
        onclick: () => actOnSearchSel("trash", "Trash").catch((e) => toast(e.message)) }, icon("trash", 16), " Mark for Trash"),
      h("button", { type: "button", class: "btn ghost", onclick: () => {
        pickFolders.forEach((f) => folderSel.add(f.id)); pickItems.forEach((it) => itemSel.add(it.id)); route({ keepScroll: true }); } },
        "Select all"),
      n ? h("button", { type: "button", class: "btn ghost", onclick: () => { folderSel.clear(); itemSel.clear(); route({ keepScroll: true }); } }, "Clear") : null);
  }
  const selectBtn = pickFolders.length || pickItems.length ? h("button", { type: "button", class: "btn", "aria-pressed": itemSelMode ? "true" : "false",
    onclick: () => { itemSelMode = !itemSelMode; if (!itemSelMode) { itemSel.clear(); folderSel.clear(); } route({ keepScroll: true }); } },
    itemSelMode ? "Done selecting" : "Select") : null;
  show(
    backBar(),
    h("section", { class: "head" }, h("div", {}, h("p", { class: "muted small" }, "Search"), h("h1", {}, `“${q}”`)),
      h("div", { class: "toolbar" }, selectBtn)),
    searchBar(q),
    bar,
    h("h2", { class: "section-t" }, `Folders (${fmt(r.folders.length)})`),
    r.folders.length ? h("div", { class: "grid" }, r.folders.map((f) => itemSelMode && !f.manual && !f.system ? pickableFolder(f)
      : h("div", { class: "fwrap" }, folderCard(f, `in ${f.path}`), !f.manual && !f.system ? actionsToggle("folder", f.id) : null)))
      : h("p", { class: "muted" }, "No folders match."),
    h("h2", { class: "section-t" }, `Items (${fmt(r.items.length)})`),
    r.items.length ? h("div", { class: "items" }, r.items.map((it) =>
      h("div", {}, itemTile(it, `in ${it.path}`, true, true), itemSelMode ? null : h("a", { class: "small", href: `#/folders/${it.folder}` }, "Open its folder"))))
      : h("p", { class: "muted" }, "No items match."),
    r.folders.length >= 150 || r.items.length >= 150 ? h("p", { class: "muted small" }, "Showing the first 150 of each. Search for something more specific to see the rest.") : null,
  );
}

// ------------------------------------------------------------------ categories
let cats = null;
async function saveCats() {
  try { const missing = cats.missing; cats = await api("/api/categories", { method: "PUT", body: cats }); cats.missing = missing; toast("Saved"); }
  catch (err) { toast(err.message); cats = await api("/api/categories"); }
  TREE = null;
  renderCats();
}
const nid = () => Math.random().toString(36).slice(2, 12);

function inlineEdit(current, onDone) {
  const input = h("input", { class: "edit-in", value: current, maxlength: "63", "aria-label": "New name" });
  const finish = (ok) => onDone(ok ? input.value.trim() : null);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
  const wrap = h("span", { class: "addrow" }, input,
    h("button", { class: "btn primary", type: "button", onclick: () => finish(true) }, "Save"),
    h("button", { class: "btn", type: "button", onclick: () => finish(false) }, "Cancel"));
  setTimeout(() => { input.focus(); input.select(); }, 0);
  return wrap;
}

let editing = null;      // {top, sub} being renamed
let confirming = null;   // {top, sub} awaiting delete confirmation

function renderCats() {
  const tops = cats.categories.map((top, ti) => {
    const isEditTop = editing && editing.top === top.id && !editing.sub;
    const header = isEditTop
      ? inlineEdit(top.name, (v) => { editing = null; if (v) { top.name = v; saveCats(); } else renderCats(); })
      : h("div", { class: "cat-h" },
          h("h2", {}, top.name), h("span", { class: "count" }, `${top.children.length} subcategories`),
          h("button", { class: "icon-btn", type: "button", "aria-label": `Rename ${top.name}`, onclick: () => { editing = { top: top.id }; renderCats(); } }, icon("edit", 18)),
          h("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${top.name}`, onclick: () => { confirming = { top: top.id }; renderCats(); } }, icon("x", 18)));
    const confirmTop = confirming && confirming.top === top.id && !confirming.sub
      ? h("div", { class: "confirm" }, `Remove “${top.name}” and its ${top.children.length} subcategories?`,
          h("button", { class: "btn danger", type: "button", onclick: () => { confirming = null; cats.categories.splice(ti, 1); saveCats(); } }, "Remove"),
          h("button", { class: "btn", type: "button", onclick: () => { confirming = null; renderCats(); } }, "Keep"))
      : null;
    const subs = h("div", { class: "subs" }, top.children.map((sub, si) => {
      if (editing && editing.sub === sub.id) {
        return inlineEdit(sub.name, (v) => { editing = null; if (v) { sub.name = v; saveCats(); } else renderCats(); });
      }
      if (confirming && confirming.sub === sub.id) {
        return h("span", { class: "confirm" }, `Remove “${sub.name}”?`,
          h("button", { class: "btn danger", type: "button", onclick: () => { confirming = null; top.children.splice(si, 1); saveCats(); } }, "Remove"),
          h("button", { class: "btn", type: "button", onclick: () => { confirming = null; renderCats(); } }, "Keep"));
      }
      return h("span", { class: "sub" }, h("span", {}, sub.name),
        h("button", { class: "icon-btn", type: "button", "aria-label": `Rename ${sub.name}`, onclick: () => { editing = { top: top.id, sub: sub.id }; renderCats(); } }, icon("edit", 15)),
        h("button", { class: "icon-btn", type: "button", "aria-label": `Remove ${sub.name}`, onclick: () => { confirming = { top: top.id, sub: sub.id }; renderCats(); } }, icon("x", 15)));
    }));
    const addIn = h("input", { placeholder: `Add a subcategory to ${top.name}`, maxlength: "63", "aria-label": `New subcategory in ${top.name}` });
    const add = h("form", { class: "addrow", onsubmit: (e) => {
      e.preventDefault(); const v = addIn.value.trim(); if (!v) return;
      top.children.push({ id: nid(), name: v }); saveCats();
    } }, addIn, h("button", { class: "btn", type: "submit" }, "Add"));
    return h("section", { class: "cat" }, header, confirmTop, subs, add);
  });
  const newTop = h("input", { placeholder: "New top-level category (e.g. Hair, Skins, Poses)", maxlength: "63", "aria-label": "New top-level category" });
  const resetBox = confirming && confirming.reset
    ? h("div", { class: "confirm" }, "Replace your categories with the starter list? Your changes will be lost.",
        h("button", { class: "btn danger", type: "button", onclick: async () => { confirming = null; cats = await api("/api/categories/reset", { method: "POST", body: {} }); TREE = null; toast("Reset to defaults"); renderCats(); } }, "Reset"),
        h("button", { class: "btn", type: "button", onclick: () => { confirming = null; renderCats(); } }, "Cancel"))
    : h("button", { class: "btn", type: "button", onclick: () => { confirming = { reset: true }; renderCats(); } }, "Reset to starter list");
  const pf = cats.parent_folder || { on: false, name: "Sorted" };
  const pfName = h("input", { value: pf.name, maxlength: "63", "aria-label": "Parent folder name", disabled: pf.on ? null : true });
  pfName.addEventListener("change", () => {
    const v = pfName.value.trim();
    if (!v || v === pf.name) { pfName.value = pf.name; return; }
    cats.parent_folder = { on: pf.on, name: v }; saveCats();
  });
  const pfOn = h("input", { type: "checkbox", checked: pf.on ? true : null });
  pfOn.addEventListener("change", () => { cats.parent_folder = { on: pfOn.checked, name: pfName.value.trim() || pf.name }; saveCats(); });
  const parentPanel = h("section", { class: "panel" },
    h("label", { class: "toggle" }, pfOn, h("b", {}, "Keep all category folders inside one folder")),
    h("div", { class: "addrow" }, h("span", { class: "muted small" }, "Folder name"), pfName),
    h("p", { class: "muted small" }, pf.on
      ? `New category folders are made inside “${pf.name}”, and the ones you already have in My Inventory are moved into it when a run uses them. You’ll see every one of these moves on Plan & Run before anything happens.`
      : "Off: category folders sit directly in My Inventory."));
  const wfOn = h("input", { type: "checkbox", checked: cats.whole_folders !== false ? true : null });
  wfOn.addEventListener("change", () => { cats.whole_folders = wfOn.checked; saveCats(); });
  const thOn = h("input", { type: "checkbox", checked: THUMBS_ON ? true : null });
  thOn.addEventListener("change", () => {
    THUMBS_ON = thOn.checked;
    try { localStorage.setItem("thumbs", THUMBS_ON ? "on" : "off"); } catch (e) { /* ignore */ }
    renderCats();
  });
  const thumbPanel = h("section", { class: "panel" },
    h("label", { class: "toggle" }, thOn, h("b", {}, "Show pictures")),
    h("p", { class: "muted small" }, THUMBS_ON
      ? "Thumbnails show on Sort, Folders and Duplicates. Turn this off for a faster, more compact list."
      : "Off: things show a small type icon instead of a picture."));
  const fpOn = h("input", { type: "checkbox", checked: cats.folder_pictures !== false ? true : null });
  fpOn.addEventListener("change", () => { cats.folder_pictures = fpOn.checked; saveCats(); });
  const picPanel = h("section", { class: "panel" },
    h("label", { class: "toggle" }, fpOn, h("b", {}, "Use a texture inside a product as its picture")),
    h("p", { class: "muted small" }, cats.folder_pictures !== false
      ? "For products without a thumbnail, the app uses the texture that looks most like an ad picture (or the only one there), skipping normal maps, masks and HUD art. It’s remembered, so the picture stays after you clean out the packaging. Only full-permission textures can be shown."
      : "Off: products without a thumbnail show an icon."));
  const wholePanel = h("section", { class: "panel" },
    h("label", { class: "toggle" }, wfOn, h("b", {}, "Move a whole folder when everything in it goes to the same category")),
    h("p", { class: "muted small" }, cats.whole_folders !== false
      ? "Faster: a folder of 15 hair items moves in one step instead of 15, and lands inside Hair as a folder. Folders with subfolders, or with anything going elsewhere, are still moved item by item."
      : "Off: things are always moved out of their folders one by one, so they sit loose in the category folder."));
  const scrollY = window.scrollY;
  view.replaceChildren(...clean([
    h("section", { class: "head" },
      h("div", {}, h("p", { class: "muted small" }, `Started from: ${cats.source}`),
        h("h1", {}, "Sorting categories")),
      resetBox),
    h("p", { class: "muted" }, "These become the folders your items get sorted into: each category is a folder, each subcategory a folder inside it. Rename, remove or add your own — changes save automatically."),
    parentPanel,
    wholePanel,
    thumbPanel,
    picPanel,
    cats.missing && cats.missing.length ? h("div", { class: "banner" },
      h("div", {}, h("b", {}, `${cats.missing.length} starter categories you don’t have yet`),
        h("div", { class: "small" }, cats.missing.join(" · "))),
      h("button", { type: "button", class: "btn primary", onclick: async () => {
        cats = await api("/api/categories/add-missing", { method: "POST", body: {} }); cats.missing = []; TREE = null; toast("Added"); renderCats(); } },
        "Add them")) : null,
    h("form", { class: "panel addrow", onsubmit: (e) => {
      e.preventDefault(); const v = newTop.value.trim(); if (!v) return;
      cats.categories.push({ id: nid(), name: v, children: [] }); saveCats();
    } }, newTop, h("button", { class: "btn primary", type: "submit" }, "Add category")),
    ...tops]));
  window.scrollTo(0, scrollY);
}

async function categories() {
  cats = await api("/api/categories");
  editing = confirming = null;
  window.scrollTo(0, 0);
  renderCats();
}


// ------------------------------------------------------------------ sort
let sortSel = new Set();
let sortSelectMode = false;
let openTops = new Set();
let lastTop = null;      // the category you were last in: moving to another one closes it
let dragIds = null;

function setPlanBadge(tree) {
  const b = document.getElementById("plan-badge");
  if (!b) return;
  b.hidden = !tree.plan;
  b.textContent = fmt(tree.plan);
  b.title = `${fmt(tree.plan)} moves planned`;
}

async function moveUnits(ids, cat, label, learn) {
  const r = await api("/api/sort/move", { method: "POST", body: { units: ids, category: cat, learn: !!learn } });
  sortSel.clear();
  TREE = r.tree;
  toast(`Moved ${ids.length === 1 ? "1 thing" : fmt(ids.length) + " things"} to ${label}`);
  setPlanBadge(r.tree);
  route({ keepScroll: true });
}

async function cleanPackaging(body, msg) {
  const r = await api("/api/sort/clean", { method: "POST", body });
  TREE = r.tree; setPlanBadge(r.tree);
  toast(msg(r.count));
  route({ keepScroll: true });
}

function dropTarget(el, cat, label) {
  el.addEventListener("dragover", (e) => { if (dragIds) { e.preventDefault(); el.classList.add("drop-on"); } });
  el.addEventListener("dragleave", () => el.classList.remove("drop-on"));
  el.addEventListener("drop", (e) => {
    e.preventDefault(); el.classList.remove("drop-on");
    if (dragIds && dragIds.length) moveUnits(dragIds, cat, label).catch((err) => toast(err.message));
    dragIds = null;
  });
  return el;
}

function categoryOptions(tree, current) {
  const sel = h("select", { class: "move-sel", "aria-label": "Move to category" },
    h("option", { value: "" }, "Move to…"),
    current !== "unsure" ? h("option", { value: "unsure" }, "Not sure yet") : null,
    current !== "trash" ? h("option", { value: "trash" }, "Send to Trash") : null,
    (tree.homes || []).filter((c) => c.id !== current).map((c) => h("option", { value: c.id }, `${c.name} folder`)),
    // Every category is listed. The one it's already headed to is marked; picking it confirms the guess
    // (so it's in the plan even if you haven't checked that category yet).
    tree.tops.map((t) => h("optgroup", { label: t.name },
      t.children.map((c) => h("option", { value: c.id }, c.id === current ? `${c.name} ✓ (headed here)` : c.name)))));
  return sel;
}

function sortCard(u, tree, current) {
  const pic = !!(u.thumb && THUMBS_ON);
  const selected = sortSel.has(u.id);
  const card = h("article", {
    class: "scard" + (pic ? " pic" : " short") + (u.unsure && current !== "unsure" ? " unsure" : "") + (selected ? " sel" : ""),
    draggable: "true", "data-id": u.id, "aria-label": u.name,
    onclick: (e) => {
      if (!sortSelectMode || e.target.closest("button, select, a")) return;
      sortSel.has(u.id) ? sortSel.delete(u.id) : sortSel.add(u.id);
      card.classList.toggle("sel"); updateSelBar();
    },
  });
  card.addEventListener("dragstart", (e) => {
    dragIds = sortSel.has(u.id) ? [...sortSel] : [u.id];
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragIds.join(","));
  });
  card.addEventListener("dragend", () => { setTimeout(() => { dragIds = null; }, 0); });
  const icon_ = u.kind === "product" ? "kit" : "object";
  if (pic) card.append(thumbBox("sthumb", u.thumb, icon_, 30));
  const move = categoryOptions(tree, current);
  move.addEventListener("change", () => {
    if (!move.value) return;
    moveUnits([u.id], move.value, labelOf(move)).catch((err) => toast(err.message));
  });
  const leftPack = u.packaging - u.cleaned;
  const productTools = u.kind === "product" && current !== "trash" ? h("div", { class: "sugs" },
    leftPack ? h("button", { type: "button", class: "sug", title: "Marks the notecards, landmarks and scripts inside for Trash. Textures are always kept. The product itself still moves here.",
      onclick: () => cleanPackaging({ units: [u.id] }, (n) => `Marked ${plural(n, "piece")} of packaging for Trash`).catch((e) => toast(e.message)) },
      `Clean out packaging (${fmt(leftPack)})`) : null,
    u.cleaned ? h("button", { type: "button", class: "sug",
      onclick: () => cleanPackaging({ units: [u.id], undo: true }, () => "Packaging kept").catch((e) => toast(e.message)) },
      `Keep packaging (${fmt(u.cleaned)} marked)`) : null,
    h("button", { type: "button", class: "sug", title: "Sort what's inside this folder one by one instead",
      onclick: () => splitUnit(u.id, u.name).catch((e) => toast(e.message)) }, "Split into pieces"),
    u.folder ? h("a", { class: "sug", href: `#/folders/${u.folder}` }, "Look inside") : null) : null;
  const parts = [
    h("div", { class: "srow" },
      pic ? null : h("span", { class: "sicon" + (u.kind === "product" ? " kit" : "") }, icon(icon_, 20)),
      h("div", { class: "stext" },
        h("span", { class: "sname", title: u.name }, u.name),
        h("span", { class: "slabel" }, u.label),
        h("span", { class: u.here ? "swhere here" : "swhere" }, u.where),
        u.created ? h("span", { class: "slabel" }, gotDate(u.created)) : null)),
    u.new ? h("span", { class: "chips" }, h("span", { class: "chip new", title: "Wasn’t here when you checked this category." }, "New since you checked")) : null,
    u.by_type ? h("span", { class: "chips" }, h("span", { class: "chip info", title: "Its Second Life item type settles where it goes." }, "Placed by item type")) : null,
    u.copy_here ? h("span", { class: "chips" }, h("span", { class: "chip info", title: "A thing with the same name and creator is already in this category — this may be a leftover original." }, "Copy already here")) : null,
    u.nocopy ? h("span", { class: "chips" }, h("span", { class: "chip warn" }, "No copy — moved, never copied")) : null,
    u.unsure && u.suggestions.length ? h("div", { class: "sugs" },
      current === "unsure" ? null : h("span", { class: "chip warn" }, "Not sure"),
      u.suggestions.map((sg) => h("button", { type: "button", class: "sug",
        onclick: () => moveUnits([u.id], sg.id, sg.name).catch((err) => toast(err.message)) }, sg.name))) : null,
    current === "trash" ? h("div", { class: "sugs" },
      u.nocopy ? h("span", { class: "chip warn" }, "No copy — this is your only one") : null,
      h("button", { type: "button", class: "sug", onclick: () =>
        undoChoice([u.id], "Kept — not going to Trash").catch((e) => toast(e.message)) }, "Don’t trash"),
      u.kind === "piece" && u.folder ? h("a", { class: "sug", href: `#/folders/${u.folder}` }, "Open its folder") : null) : null,
    u.unsure && !u.suggestions.length ? h("span", { class: "muted small" },
      u.appearance ? "Clothing or body part with no clear name — use Move… or drag it." : "No good guess — use Move… or drag it.") : null,
    productTools,
    h("div", { class: "sfoot" }, move,
      current !== "trash" ? h("button", { type: "button", class: "icon-btn trash-btn", title: "Mark for Trash (you'll review it before anything happens)",
        "aria-label": `Mark ${u.name} for Trash`,
        onclick: () => moveUnits([u.id], "trash", "To Trash (marked — review before running)").catch((err) => toast(err.message)) },
        icon("trash", 18)) : null)];
  card.append(...clean(parts));
  return card;
}

function updateSelBar() {
  const bar = document.getElementById("selbar");
  if (!bar) return;
  bar.hidden = !sortSelectMode;
  const n = document.getElementById("seln");
  if (n) n.textContent = sortSel.size ? `${fmt(sortSel.size)} selected` : "Click things to select them.";
}

// Not sure yet and To Trash are long lists, shown as collapsible groups. Which groups are open is remembered.
const openGroups = new Set();
let groupsSeeded = { unsure: false, trash: false };

function groupSection(key, title, count, open, actions, cards, cls) {
  const d = h("details", { class: "sgroup" + (cls ? " " + cls : ""), open: open ? true : null },
    h("summary", {}, h("span", { class: "gtitle" }, title), h("span", { class: "tbadge" }, fmt(count))),
    actions ? h("div", { class: "gactions" }, actions) : null,
    h("div", { class: "sgrid" }, cards));
  d.addEventListener("toggle", () => { d.open ? openGroups.add(key) : openGroups.delete(key); });
  return d;
}

function unsureGroups(units, tree, current) {
  const by = new Map();
  for (const u of units) {
    const g = u.suggestions && u.suggestions[0];
    const key = g ? g.id : "_none";
    if (!by.has(key)) by.set(key, { id: g ? g.id : null, name: g ? g.name : null, units: [] });
    by.get(key).units.push(u);
  }
  const groups = [...by.values()].sort((a, b) => (a.id ? 0 : 1) - (b.id ? 0 : 1) || b.units.length - a.units.length);
  if (!groupsSeeded.unsure) { groups.slice(0, 2).forEach((g) => openGroups.add("u:" + (g.id || "_none"))); groupsSeeded.unsure = true; }
  return h("section", { class: "sgroups", "aria-label": "Not sure yet, grouped by the app’s best guess" },
    h("p", { class: "muted small" }, "Grouped by the app’s best guess. Open a group, drag out anything that doesn’t belong, then move the rest in one go. " +
      "The app learns from each group you confirm, so similar things get sorted by themselves next time."),
    groups.map((g) => {
      const key = "u:" + (g.id || "_none");
      const ids = g.units.map((u) => u.id);
      return groupSection(key, g.id ? `Probably ${g.name}` : "No guess", g.units.length, openGroups.has(key),
        g.id ? h("button", { type: "button", class: "btn primary", onclick: () =>
          moveUnits(ids, g.id, g.name, true).catch((e) => toast(e.message)) },
          `Move ${ids.length === 1 ? "it" : `these ${fmt(ids.length)}`} to ${g.name}`) : null,
        g.units.map((u) => sortCard(u, tree, current)));
    }));
}

const TRASH_ORDER = ["Product", "Object", "Clothing & body parts", "Notecard", "Landmark", "Texture", "Script",
  "Animation", "Gesture", "Calling card", "Sound", "Material"];
// Landmarks: one row per store or place. The newest landmark is kept (and pulled into Landmarks);
// older and repeated copies can go to Trash.
function landmarkPlaces(cat) {
  const act = async (place, undo) => {
    const r = await api("/api/sort/landmark-copies", { method: "POST", body: { place, undo } });
    TREE = r.tree; setPlanBadge(r.tree);
    toast(undo ? `Kept ${plural(r.count, "landmark")}` : `Marked ${plural(r.count, "older copy", "older copies")} for Trash`);
    route({ keepScroll: true });
  };
  const top = cat.extra ? h("div", { class: "banner" },
    h("div", {}, h("b", {}, `${plural(cat.extra, "older or repeated landmark")}`),
      h("div", { class: "small" }, "Copies of a landmark you already have a newer one for. Marking them sends them to Trash when you run; Trash isn’t emptied.")),
    h("button", { type: "button", class: "btn", onclick: () => act(null, false).catch((e) => toast(e.message)) }, `Trash all ${fmt(cat.extra)}`))
    : cat.marked ? h("p", { class: "muted small" }, `${plural(cat.marked, "older copy", "older copies")} marked for Trash. `,
      h("button", { type: "button", class: "linkbtn small", onclick: () => act(null, true).catch((e) => toast(e.message)) }, "Keep them all")) : null;
  return h("section", { class: "lmplaces", "aria-label": "Landmarks, one per store or place" }, top,
    cat.places.map((p) => {
      const k = p.keep;
      const marked = p.copies.filter((c) => c.trash).length;
      return h("article", { class: "lmplace" },
        h("div", { class: "lmmain" },
          h("span", { class: "lmicon", "aria-hidden": "true" }, icon("landmark", 18)),
          h("div", { class: "lmtext" },
            h("b", {}, k.name),
            h("span", { class: "small " + (p.moving ? "lmmove" : "muted") },
              p.moving ? `Newest · moving to Landmarks from ${k.where}` : "Newest · in your Landmarks folder",
              k.created ? ` · ${gotDate(k.created)}` : "")),
          p.copies.length ? (p.left
            ? h("button", { type: "button", class: "btn small-btn", onclick: () => act(p.key, false).catch((e) => toast(e.message)) },
                `Trash ${plural(p.left, "older copy", "older copies")}`)
            : h("button", { type: "button", class: "linkbtn small", onclick: () => act(p.key, true).catch((e) => toast(e.message)) },
                `Keep the ${fmt(marked)} older`)) : null),
        p.copies.length ? h("details", { class: "lmcopies" },
          h("summary", { class: "muted small" }, `${plural(p.copies.length, "older or repeated copy", "older or repeated copies")}` +
            (marked ? ` · ${fmt(marked)} marked for Trash` : "")),
          h("ul", {}, p.copies.map((c) => h("li", { class: c.trash ? "gone" : "" },
            c.name, h("span", { class: "muted small" }, ` · ${c.where}${c.created ? " · " + gotDate(c.created) : ""}${c.trash ? " · to Trash" : ""}`))))) : null);
    }));
}

function trashGroups(units, tree, current) {
  const nocopy = units.filter((u) => u.nocopy);
  const by = new Map();
  for (const u of units.filter((x) => !x.nocopy)) {
    const k = u.ktype || "Other";
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(u);
  }
  const order = (k) => { const i = TRASH_ORDER.indexOf(k); return i < 0 ? 99 : i; };
  const kinds = [...by.keys()].sort((a, b) => order(a) - order(b) || a.localeCompare(b));
  if (!groupsSeeded.trash) { openGroups.add("t:nocopy"); groupsSeeded.trash = true; }
  const PLURAL = { "Clothing & body parts": "Clothing & body parts", "Other": "Other" };
  return h("section", { class: "sgroups", "aria-label": "To Trash, grouped by type" },
    h("p", { class: "muted small" }, "Grouped by type so you can double-check by name before anything goes. " +
      "Use Move… on a card (or drag it onto a category) to keep it."),
    nocopy.length ? groupSection("t:nocopy", "No copy — you can’t get these back by copying", nocopy.length,
      openGroups.has("t:nocopy"), null, nocopy.map((u) => sortCard(u, tree, current)), "warn") : null,
    kinds.map((k) => groupSection("t:" + k, PLURAL[k] || (k.endsWith("s") ? k : k + "s"), by.get(k).length,
      openGroups.has("t:" + k), null, by.get(k).map((u) => sortCard(u, tree, current)))));
}

// "Which folders should the sorter go through?" Asked the first time you open Sort; "Choose folders" brings it back.
async function chooseFoldersPage() {
  const d = await api("/api/sort/folders");
  const first = !d.chosen;
  const pick = d.folders.filter((f) => !f.fixed);
  const fixed = d.folders.filter((f) => f.fixed);
  const on = new Set(pick.filter((f) => (first ? !f.organized : !f.skipped)).map((f) => f.id));
  const count = h("span", { class: "muted" });
  const recount = () => {
    const n = pick.filter((f) => on.has(f.id)).reduce((a, f) => a + f.count, 0);
    count.textContent = `${plural(on.size, "folder")} · ${fmt(n)} items to sort`;
  };
  const rows = pick.map((f) => {
    const box = h("input", { type: "checkbox", checked: on.has(f.id) ? true : null });
    box.addEventListener("change", () => { box.checked ? on.add(f.id) : on.delete(f.id); recount(); });
    return h("label", { class: "frow" + (f.organized ? " org" : "") }, box,
      h("span", { class: "fname" }, f.name),
      f.organized ? h("span", { class: "chip info" }, `Looks organized · ${Math.round(f.sorted_share * 100)}% already in category folders`) : null,
      h("span", { class: "muted small" }, plural(f.count, "item")));
  });
  const setAll = (val, which) => { pick.forEach((f) => { if (!which || which(f)) val ? on.add(f.id) : on.delete(f.id); }); route({ keepScroll: true }); };
  recount();
  show(
    h("section", { class: "head" }, h("div", {},
      h("h1", {}, "Which folders should the sorter go through?"),
      h("p", { class: "muted" }, "Unticked folders are left exactly as they are: nothing in them is suggested, moved, renamed or trashed. " +
        "Folders you’ve already organized can still receive new things, and the app still learns from how you sorted them."))),
    h("div", { class: "toolbar" }, count,
      h("button", { type: "button", class: "btn ghost", onclick: () => { pick.forEach((f) => on.add(f.id)); rows.forEach((r) => { r.querySelector("input").checked = true; }); recount(); } }, "Tick all"),
      h("button", { type: "button", class: "btn ghost", onclick: () => { pick.forEach((f) => { if (f.organized) on.delete(f.id); });
        rows.forEach((r, i) => { r.querySelector("input").checked = on.has(pick[i].id); }); recount(); } }, "Untick the organized ones")),
    h("section", { class: "panel flist" }, rows.length ? rows : h("p", { class: "muted" }, "No folders to choose from.")),
    fixed.length ? h("details", { class: "panel" }, h("summary", { class: "muted" }, `Always left alone (${fmt(fixed.length)})`),
      h("p", { class: "muted small" }, "System folders like Clothing, Textures and Calling Cards (Objects, Lost And Found and Received Items are sorted), plus #Firestorm and #RLV."),
      h("ul", { class: "plist" }, fixed.map((f) => h("li", {}, f.name, h("span", { class: "muted small" }, ` · ${plural(f.count, "item")}`))))) : null,
    h("p", {}, h("button", { type: "button", class: "btn primary", onclick: async () => {
      try {
        const skip = pick.filter((f) => !on.has(f.id)).map((f) => f.id);
        const r = await api("/api/sort/choose-folders", { method: "POST", body: { skip } });
        TREE = r.tree; setPlanBadge(r.tree);
        toast(skip.length ? `${plural(skip.length, "folder")} will be left alone` : "Sorting everything");
        location.hash = "#/sort";
        if (location.hash === "#/sort") route();
      } catch (err) { toast(err.message); } } }, first ? "Start sorting" : "Save"),
      first ? null : h("a", { class: "btn ghost", href: "#/sort", style: { marginLeft: "8px" } }, "Cancel")),
  );
}

async function sortPage(cid) {
  if (cid === "folders") return chooseFoldersPage();
  if (!TREE || TREE.chosen === undefined) TREE = await api("/api/sort/tree");
  if (!TREE.chosen) return chooseFoldersPage();
  if (!view.querySelector(".swrap")) {
    show(h("div", { class: "panel" }, h("h2", {}, "Working out where everything goes…"),
      h("p", { class: "muted" }, "The first time can take a little while for a big inventory.")));
  }
  const [tree, cat] = await Promise.all([api("/api/sort/tree"),
    api(`/api/sort/category${cid ? `?id=${encodeURIComponent(cid)}` : ""}`)]);
  TREE = tree;
  setPlanBadge(tree);
  if (!cid && cat.id) { history.replaceState(null, "", `#/sort/${cat.id}`); }
  const current = cat.id;
  const curTop = tree.tops.find((t) => t.children.some((c) => c.id === current));
  if (curTop && curTop.id !== lastTop) { openTops = new Set([curTop.id]); lastTop = curTop.id; }

  const manual = tree.manual && tree.manual.length ? h("details", { class: "manual" },
    h("summary", { class: "muted small" }, `Left for you to sort by hand (${fmt(tree.manual.length)})`),
    h("p", { class: "muted small" }, "System folders the app never moves things out of. Objects, Lost And Found and Received Items are sorted."),
    h("ul", { class: "plist" }, tree.manual.map((m) => h("li", {},
      h("a", { href: `#/folders/${m.id}` }, m.name), h("span", { class: "muted small" }, ` · ${plural(m.count, "item")}`))))) : null;

  const skippedList = tree.skipped && tree.skipped.length ? h("details", { class: "manual", open: true },
    h("summary", { class: "muted small" }, `Skipped by you (${fmt(tree.skipped.length)})`),
    h("p", { class: "muted small" }, "Left exactly as they are. Skip more from any folder’s page."),
    h("ul", { class: "plist" }, tree.skipped.map((m) => h("li", {},
      h("a", { href: `#/folders/${m.id}`, title: m.path }, m.name), h("span", { class: "muted small" }, ` · ${plural(m.count, "item")} · `),
      h("button", { type: "button", class: "linkbtn small", onclick: () => skipFolder(m.id, false, m.name) }, "Sort again"))))) : null;
  const side = h("aside", { class: "stree", "aria-label": "Categories" },
    h("div", { class: "sprog" },
      h("span", { class: "muted small" }, `${fmt(tree.checked)} of ${fmt(tree.categories)} categories checked · ${fmt(tree.plan)} moves planned`),
      h("div", { class: "bar" }, h("div", { style: { width: `${tree.categories ? (100 * tree.checked) / tree.categories : 0}%` } })),
      h("a", { class: "linkbtn small", href: "#/sort/folders" }, "Choose which folders to sort")),
    tree.tops.map((t) => {
      const open = openTops.has(t.id);
      return [
        h("button", { type: "button", class: "ttop", "aria-expanded": open ? "true" : "false",
          onclick: () => { openTops = open ? new Set([...openTops].filter((x) => x !== t.id)) : new Set([t.id]); route({ keepScroll: true }); } },
          h("span", { class: "tname" }, t.name), h("span", { class: "tbadge" }, t.checked === t.children.length && t.children.length ? "✓" : fmt(t.count))),
        open ? t.children.map((c) => dropTarget(h("a", { href: `#/sort/${c.id}`, class: "tsub" + (c.id === current ? " on" : "") },
          h("span", { class: "tname" }, c.name),
          h("span", { class: "tbadge" + (c.approved ? " ok" : c.new ? " new" : ""), title: c.new ? `${fmt(c.new)} new since you checked it` : null },
            c.approved ? "✓" : c.new ? `${fmt(c.new)} new` : fmt(c.count))), c.id, c.name)) : null,
      ];
    }),
    dropTarget(h("a", { href: "#/sort/unsure", class: "ttop unsure" + (current === "unsure" ? " on" : "") },
      h("span", { class: "tname" }, "Not sure yet"), h("span", { class: "tbadge" }, fmt(tree.unsure))), "unsure", "Not sure yet"),
    dropTarget(h("a", { href: "#/sort/trash", class: "ttop trashrow" + (current === "trash" ? " on" : "") },
      h("span", { class: "tname" }, "To Trash"), h("span", { class: "tbadge" }, fmt(tree.trash))), "trash", "Trash"),
    h("p", { class: "shome-t muted small" }, "System folders"),
    (tree.homes || []).map((c) => dropTarget(h("a", { href: `#/sort/${c.id}`, class: "ttop" + (current === c.id ? " on" : "") },
      h("span", { class: "tname" }, c.name),
      h("span", { class: "tbadge" + (c.approved ? " ok" : c.new ? " new" : "") }, c.approved ? "✓" : c.new ? `${fmt(c.new)} new` : fmt(c.incoming))),
      c.id, c.name)),
    skippedList, manual);

  const coming = cat.total - cat.here;
  const summary = cat.id === "trash"
    ? `${fmt(cat.total)} things you marked for Trash. Trash isn’t emptied, so you can still get them back in Firestorm.`
    : cat.id === "unsure"
    ? `${fmt(cat.total)} things the app couldn’t place.`
    : cat.id === "settings"
    ? `Windlights and other environment settings go to your Settings folder, as they are. ${fmt(cat.here)} already there · ${fmt(coming)} coming from elsewhere (including ones pulled out of products).`
    : cat.landmarks
    ? `${fmt(cat.total)} stores and places. The newest landmark to each one goes to your Landmarks folder (${fmt(cat.pulling)} pulled out of products and other folders); older and repeated copies are listed under it.`
    : `${fmt(cat.total)} things headed here · ${fmt(cat.here)} already in this folder · ${fmt(coming)} coming from elsewhere` +
      (cat.copies ? ` · ${fmt(cat.copies)} look like leftover originals of things already here` : "");
  const approveBtn = cat.id === "unsure" || cat.id === "trash" ? null : cat.approved
    ? h("button", { type: "button", class: "btn", onclick: async () => {
        await api("/api/sort/approve", { method: "POST", body: { category: cat.id, approved: false } }); route(); } }, "Checked ✓ — uncheck")
    : h("button", { type: "button", class: "btn primary", onclick: async () => {
        const r = await api("/api/sort/approve", { method: "POST", body: { category: cat.id, approved: true } });
        toast(`Checked ${cat.name}`); sortSel.clear();
        location.hash = r.next ? `#/sort/${r.next}` : "#/sort/unsure"; } }, "Looks good — next category");
  const selectBtn = h("button", { type: "button", class: "btn", "aria-pressed": sortSelectMode ? "true" : "false",
    onclick: () => { sortSelectMode = !sortSelectMode; if (!sortSelectMode) sortSel.clear(); route({ keepScroll: true }); } },
    sortSelectMode ? "Done selecting" : "Select");
  const bulkMove = categoryOptions(tree, current);
  bulkMove.addEventListener("change", () => {
    if (!bulkMove.value || !sortSel.size) return;
    moveUnits([...sortSel], bulkMove.value, labelOf(bulkMove)).catch((err) => toast(err.message));
  });

  const withPic = cat.units.filter((u) => u.thumb && THUMBS_ON);
  const noPic = cat.units.filter((u) => !(u.thumb && THUMBS_ON));
  const inOrder = ORDER === "name" && cat.id !== "unsure" ? [...withPic, ...noPic]
    : cat.id === "unsure" && ORDER === "name" ? cat.units : [...ordered(withPic), ...ordered(noPic)];
  if (cat.new) inOrder.sort((a, b) => (b.new ? 1 : 0) - (a.new ? 1 : 0));   // new since you checked: first
  const grid = cat.landmarks ? landmarkPlaces(cat) : cat.id === "unsure" ? unsureGroups(inOrder, tree, current)
    : cat.id === "trash" ? trashGroups(inOrder, tree, current)
    : h("section", { class: "sgrid", "aria-label": `Things headed to ${cat.name}` },
        inOrder.map((u) => sortCard(u, tree, current)));
  const mainCol = h("div", { class: "smain" },
    cat.top ? h("p", { class: "muted small" }, `${cat.top} › ${cat.name}`) : null,
    h("section", { class: "head" }, h("div", {}, h("h1", {}, cat.name), h("p", { class: "muted" }, summary)),
      h("div", { class: "toolbar" }, cat.landmarks ? null : orderPicker(), cat.landmarks ? null : selectBtn, approveBtn)),
    h("div", { class: "selbar", id: "selbar", hidden: !sortSelectMode },
      h("span", { id: "seln" }), bulkMove,
      current !== "trash" ? h("button", { type: "button", class: "btn", onclick: () => {
        if (sortSel.size) moveUnits([...sortSel], "trash", "Trash").catch((err) => toast(err.message)); } }, icon("trash", 16), " Mark for Trash") : null,
      h("button", { type: "button", class: "btn ghost", onclick: () => { cat.units.forEach((u) => sortSel.add(u.id)); route({ keepScroll: true }); } }, "Select all"),
      h("button", { type: "button", class: "btn ghost", onclick: () => { sortSel.clear(); route({ keepScroll: true }); } }, "Clear")),
    cat.new ? h("div", { class: "banner" },
      h("div", {}, h("b", {}, `${plural(cat.new, "new thing")} since you checked ${cat.name}`),
        h("div", { class: "small" }, "They’re shown first, marked “New since you checked”. Things the app guessed go into the plan only after you check this category again."))) : null,
    cat.id === "unsure" || cat.landmarks ? null : h("p", { class: "muted small" }, "Folders move as a whole. Drag anything onto a category on the left, or use Move to…. Nothing changes in Second Life until you run the plan."),
    cat.copies ? h("div", { class: "banner warnbanner" },
      h("div", {}, h("b", {}, `${fmt(cat.copies)} leftover originals`),
        h("div", { class: "small" }, "Same name and creator as something already in this category — usually the original left behind after sorting.")),
      h("button", { type: "button", class: "btn", onclick: async () => {
        const r = await api("/api/sort/trash-copies", { method: "POST", body: { category: cat.id } });
        TREE = r.tree; setPlanBadge(r.tree); toast(`Marked ${fmt(r.count)} for Trash`); route({ keepScroll: true }); } }, `Mark the ${fmt(cat.copies)} for Trash`)) : null,
    cat.packaging && cat.id !== "trash" ? h("div", { class: "banner" },
      h("div", {}, h("b", {}, `${plural(cat.packaging, "piece")} of packaging inside these products`),
        h("div", { class: "small" }, "Notecards, landmarks and scripts (textures are always kept). Cleaning them out marks them for Trash — you’ll see them in To Trash and can keep any of them.")),
      h("button", { type: "button", class: "btn", onclick: () =>
        cleanPackaging({ category: cat.id }, (n) => `Marked ${plural(n, "piece")} of packaging for Trash`).catch((e) => toast(e.message)) },
        "Clean out packaging in all of them")) : null,
    cat.total ? grid : h("div", { class: "panel empty" }, "Nothing is headed here yet."),
    cat.total > cat.units.length ? h("p", { class: "muted small" }, `Showing ${fmt(cat.units.length)} of ${fmt(cat.total)}.`) : null);
  show(h("div", { class: "swrap" }, side, mainCol));
  updateSelBar();
}


// ------------------------------------------------------------------ plan & run
let runTimer = null;
function stopRunTimer() { if (runTimer) { clearInterval(runTimer); runTimer = null; } }

function fsPill(st) {
  const pill = document.getElementById("fs-pill");
  if (!pill || !st) return;
  const b = st.bridge;
  let text = "Firestorm not connected", cls = "pill";
  if (b.ready && st.inventory_root && b.root !== st.inventory_root) { text = "Firestorm: different avatar"; cls = "pill bad"; }
  else if (b.ready) { text = "Firestorm connected"; cls = "pill ok"; }
  else if (b.connected) { text = "Firestorm: waiting for login"; cls = "pill"; }
  else if (b.launched) { text = "Firestorm starting…"; cls = "pill"; }
  pill.textContent = text; pill.className = cls;
}

function runPanel(st) {
  const r = st.run;
  if (!r) return null;
  const pct = r.total ? Math.round((100 * r.done) / r.total) : 0;
  const active = ["running", "paused", "stopping"].includes(r.state);
  const cheer = r.state === "done" && !r.undo && r.done ? h("div", { class: "cheer" },
    h("img", { src: "done.jpg", alt: "Ria cheering, with a checked-off list" }),
    h("div", {}, h("h2", {}, "All done!"),
      h("p", {}, `${plural(r.done, "step")} finished and checked against your live inventory.`),
      h("p", { class: "muted small" }, "Changed your mind about something? “Undo this run” puts it all back."))) : null;
  return h("section", { class: "panel runpanel", "aria-live": "polite" }, cheer,
    h("div", { class: "head" },
      h("div", {}, h("p", { class: "muted small" }, r.undo ? "Undoing a run" : "Running the plan"),
        h("h2", {}, active ? (r.state === "paused" ? "Paused" : r.state === "stopping" ? "Stopping after this step…" : r.current || "Starting…") : r.message || r.state)),
      h("span", { class: "bignum" }, `${pct}%`)),
    h("div", { class: "bar big", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(r.total), "aria-valuenow": String(r.done) },
      h("div", { style: { width: `${pct}%` } })),
    h("p", { class: "muted small" }, `${fmt(r.done)} of ${fmt(r.total)} steps · each one checked against your live inventory`),
    active ? h("div", { class: "toolbar" },
      h("button", { type: "button", class: "btn primary", onclick: () => api("/api/run/pause", { method: "POST", body: {} }).then(() => planPage()) }, r.state === "paused" ? "Resume" : "Pause"),
      h("button", { type: "button", class: "btn", onclick: () => api("/api/run/stop", { method: "POST", body: {} }).then(() => planPage()) }, r.state === "paused" ? "Stop" : "Stop after this step"),
      r.state === "paused" ? h("p", { class: "muted small" },
        "Resume carries on with the plan as it was when you pressed Run. To change where things go, press Stop, fix them on the Sort page, then run again — moves already made stay done, and Undo can put them back.") : null)
      : (!r.undo && r.done ? h("div", { class: "toolbar" },
          h("button", { type: "button", class: "btn", onclick: async () => {
            try { await api("/api/run/undo", { method: "POST", body: { log: r.log } }); planPage(); } catch (err) { toast(err.message); } } }, "Undo this run")) : null),
    r.recent.length ? h("ol", { class: "runlog" }, r.recent.slice().reverse().map((l) => h("li", {}, "✓ ", l))) : null,
    r.problems.length ? h("div", { class: "confirm" }, h("b", {}, `${r.problems.length} step(s) didn't happen:`),
      h("ul", {}, r.problems.slice(-10).map((p) => h("li", {}, `${p.label} — ${p.note}`)))) : null);
}

async function planPage() {
  stopRunTimer();
  const [st, pv] = await Promise.all([api("/api/run/status"), api("/api/run/preview")]);
  fsPill(st);
  const b = st.bridge;
  const mismatch = b.ready && b.root !== st.inventory_root;
  const running = st.run && ["running", "paused", "stopping"].includes(st.run.state);
  const connect = b.ready
    ? h("p", { class: mismatch ? "err" : "muted" }, mismatch
        ? "Firestorm is logged in as a different avatar than the inventory you sorted. Log in as the right avatar, or pick that inventory at the top."
        : "Firestorm is connected and logged in.")
    : h("div", { class: "toolbar" },
        h("button", { type: "button", class: "btn primary", disabled: b.launched || b.connected ? true : null, onclick: async () => {
          try { await api("/api/run/connect", { method: "POST", body: {} }); toast("Starting Firestorm — log in as usual"); planPage(); }
          catch (err) { toast(err.message); } } }, b.connected ? "Waiting for you to log in…" : b.launched ? "Firestorm is starting…" : "Start Firestorm with Inventory Buddy"),
        h("span", { class: "muted small" }, "Quit Firestorm first if it’s open. You log in yourself — the app never sees your password."));
  const trashRow = (t) => h("li", {},
    h("span", {}, t.name), t.where ? h("span", { class: "muted small" }, ` · from ${t.where}`) : null,
    t.nocopy ? h("span", { class: "chip warn" }, "No copy — your only one") : null,
    h("button", { type: "button", class: "btn ghost", onclick: async () => {
      await api("/api/sort/unassign", { method: "POST", body: { units: [t.unit] } }); toast("Kept"); planPage(); } }, "Don’t trash"));
  let trashList = null;
  if (pv.trash.length) {
    const nocopy = pv.trash.filter((t) => t.nocopy);
    const byType = new Map();
    for (const t of pv.trash.filter((x) => !x.nocopy)) {
      const k = t.ktype || "Other";
      if (!byType.has(k)) byType.set(k, []);
      byType.get(k).push(t);
    }
    const order = (k) => { const i = TRASH_ORDER.indexOf(k); return i < 0 ? 99 : i; };
    const kinds = [...byType.keys()].sort((a, b) => order(a) - order(b) || a.localeCompare(b));
    const section = (key, title, list, cls) => groupSection(key, title, list.length, openGroups.has(key), null,
      [h("ul", { class: "plist" }, list.slice(0, 500).map(trashRow))], ((cls || "") + " listgroup").trim());
    if (!openGroups.has("p:seeded")) { openGroups.add("p:seeded"); openGroups.add("p:nocopy"); }
    trashList = h("section", { class: "panel" },
      h("h2", {}, `To Trash (${fmt(pv.trash.length)})`),
      h("p", { class: "muted small" }, "Grouped by type so you can check by name before anything goes. Firestorm’s Trash isn’t emptied, so these can still be dragged back."),
      h("div", { class: "sgroups" },
        nocopy.length ? section("p:nocopy", "No copy — you can’t get these back by copying", nocopy, "warn") : null,
        kinds.map((k) => section("p:" + k, k === "Clothing & body parts" || k === "Other" || k.endsWith("s") ? k : k + "s", byType.get(k)))));
  }
  show(
    h("section", { class: "head" }, h("div", {},
      h("h1", {}, "Plan & Run"),
      h("p", { class: "muted" }, pv.total ? `${plural(pv.total, "step")}: ${plural(pv.moves + (pv.tucks || []).length, "move")}${pv.folders ? ` (${plural(pv.folders, "whole folder")})` : ""}, ${plural(pv.creates.length, "new folder")}, ${plural(pv.renames.length, "rename")}, ${fmt(pv.trash.length)} to Trash.`
        : "Nothing planned yet. Things go in the plan when you move them yourself or check a category on the Sort screen."))),
    runPanel(st),
    h("section", { class: "panel" }, h("h2", {}, "1 · Connect Firestorm"), connect),
    pv.total ? h("section", { class: "panel" }, h("h2", {}, "2 · Review"),
      pv.renames.length ? h("details", {}, h("summary", {}, `Rename ${plural(pv.renames.length, "existing folder")} to the short category names`),
        h("ul", { class: "plist" }, pv.renames.map((r) => h("li", {}, `“${r.old}” → “${r.new}”`)))) : null,
      pv.creates.length ? h("details", {}, h("summary", {}, `Create ${plural(pv.creates.length, "new folder")}`),
        h("ul", { class: "plist" }, pv.creates.map((c) => h("li", {}, c)))) : null,
      pv.tucks && pv.tucks.length ? h("details", {}, h("summary", {}, `Move ${plural(pv.tucks.length, "category folder")} into “${pv.parent}”`),
        h("ul", { class: "plist" }, pv.tucks.map((c) => h("li", {}, c)))) : null,
      pv.groups.map((g) => h("details", {}, h("summary", {}, h("b", {}, `${g.top} › ${g.name}`), ` — ${fmt(g.items.length)} moving in`),
        h("ul", { class: "plist" }, g.items.slice(0, 300).map((n) => h("li", {}, n)),
          g.items.length > 300 ? h("li", { class: "muted" }, `…and ${fmt(g.items.length - 300)} more`) : null)))) : null,
    trashList,
    pv.total ? h("section", { class: "panel" }, h("h2", {}, "3 · Run"),
      h("p", { class: "muted" }, "Don’t click or type in Firestorm while it runs — the app is using its Inventory window. Take off anything you want moved first: Firestorm won’t move things you’re wearing. You can pause or stop between steps, and undo the whole run afterwards."),
      h("button", { type: "button", class: "btn primary big", disabled: !b.ready || mismatch || running ? true : null, onclick: async () => {
        try { await api("/api/run/start", { method: "POST", body: {} }); planPage(); } catch (err) { toast(err.message); } } },
        running ? "Running…" : !b.ready ? "Connect Firestorm first" : `Run ${plural(pv.total, "step")}`)) : null,
    st.runs.length && !running ? h("details", { class: "panel" }, h("summary", {}, "Earlier runs"),
      h("ul", { class: "plist" }, st.runs.map((name) => h("li", {}, name.replace("run-", "").replace(".json", ""),
        h("button", { type: "button", class: "btn ghost", onclick: async () => {
          try { await api("/api/run/undo", { method: "POST", body: { log: name } }); planPage(); } catch (err) { toast(err.message); } } }, "Undo"))))) : null,
  );
  if (running || (!b.ready && (b.launched || b.connected))) {
    runTimer = setInterval(async () => {
      if (!location.hash.startsWith("#/plan")) return stopRunTimer();
      try {
        const s2 = await api("/api/run/status");
        fsPill(s2);
        const stillRunning = s2.run && ["running", "paused", "stopping"].includes(s2.run.state);
        if (!stillRunning || s2.bridge.ready !== b.ready) { planPage(); }
        else {
          const old = view.querySelector(".runpanel"); const fresh = runPanel(s2);
          if (old && fresh) old.replaceWith(fresh);
        }
      } catch (e) { /* ignore */ }
    }, 1500);
  }
}


// ------------------------------------------------------------------ connect first (nothing else until a fresh scan)
let LOCKED = true, OFFLINE = false, sessTimer = null;

function setLocked(locked) {
  LOCKED = locked;
  document.body.classList.toggle("locked", locked && !OFFLINE);
}

async function refreshSession() {
  const sess = await api("/api/session");
  OFFLINE = sess.offline;
  document.body.classList.toggle("live", !OFFLINE);
  const wasLocked = LOCKED;
  setLocked(sess.locked);
  fsPill({ bridge: sess.bridge, inventory_root: sess.locked ? null : sess.bridge.root });
  return { sess, changed: wasLocked !== sess.locked };
}

function step(n, title, state, body) {
  return h("li", { class: "cstep " + state },
    h("span", { class: "cnum", "aria-hidden": "true" }, state === "done" ? "✓" : String(n)),
    h("div", {}, h("b", {}, title), body ? h("div", { class: "muted small" }, body) : null));
}

const PROFILE = "https://www.instagram.com/ledeverse/";
const FEEDBACK = "https://forms.gle/3xLb9AMczW2dhWW59";
const REPO = "https://github.com/rialedevresl/inventory-buddy-desktop";
const SIGNATURE = "signature.png";
async function aboutPage() {
  let version = "";
  try { version = (await (await fetch("/health")).json()).version || ""; } catch (e) { /* offline */ }
  const ext = (href, text) => h("a", { href, target: "_blank", rel: "noopener" }, text);
  const promise = (t) => h("li", {}, h("span", { class: "lheart", "aria-hidden": "true" }, "♡"), h("span", {}, t));
  const back = LOCKED && !OFFLINE ? h("p", { class: "backbar" }, h("button", { type: "button", class: "btn",
    onclick: () => { location.hash = "#/overview"; } }, "← Back to getting started")) : null;
  show(back, h("section", { class: "about letter" },
    h("img", { class: "lart", src: "ria.jpg", alt: "Ria Ledevre's avatar, holding a checklist among boxes" }),
    h("p", { class: "lhi" }, "Hi lovely,"),
    h("p", {}, "If your inventory looks anything like mine did, with thousands of boxes, folders inside folders, landmarks everywhere and that one outfit you know you own but can never find, this is for you."),
    h("p", {}, "I made Inventory Buddy to sort things in-world, but I wanted something that could take on a whole inventory at once, so I built this. It’s free, and it always will be."),
    h("p", {}, "I know letting an app near your inventory can feel scary, so here’s my promise to you:"),
    h("ul", { class: "lpromise" },
      promise("You log in to Firestorm yourself, just like usual. Your password stays yours, and the app never sees it."),
      promise("Nothing changes until you press Run, and you’ll see every step first."),
      promise("Every run can be undone, and Trash is never emptied."),
      promise("No-copy items are only ever moved, never copied or lost."),
      promise("Folders you skip, and system folders like Clothing and Favorites, are left exactly as they are.")),
    h("p", {}, "I hope it gives you back a little time, and a little peace, so you can get back to the fun part of Second Life."),
    h("p", { class: "lsign" }, "With love,"),
    h("img", { class: "lsig", src: SIGNATURE, alt: "Ria Ledevre" }),
    h("div", { class: "lfoot" },
      h("p", {}, h("b", {}, "Inventory Buddy Desktop"), version ? ` · version ${version}` : "",
        " · An inventory organizer for Second Life®"),
      h("p", {}, h("b", {}, "Something sorted wrong, or an idea?"), " I’d love to hear it. Fill in the ", ext(FEEDBACK, "feedback form"), ", message me on ", ext(PROFILE, "Instagram"),
        ", or IM Ria Ledevre in-world. Item names and where they should have gone help me improve the sorting."),
      h("p", {}, "Updates, and the code so you can see exactly what it does, are on ", ext(REPO, "GitHub"), "."),
      h("p", { class: "fine" }, "Second Life® is a trademark of Linden Research, Inc. Inventory Buddy Desktop is not affiliated with or endorsed by Linden Lab."))));
}

// Reassurances shown one at a time under the bar while you get connected.
const START_TIPS = [
  "The app never sees your password: you log in to Firestorm yourself, as usual.",
  "Nothing changes in Second Life until you press Run on Plan & Run, and you see every step first.",
  "Every run can be undone from Plan & Run, and Trash is never emptied.",
  "Your inventory is read fresh from Firestorm each time, so the app always works on it as it is right now.",
  "Folders you skip, and system folders like Clothing and Favorites, are left exactly as they are.",
];
let lastTip = -1;

async function connectPage(sess) {
  const b = sess.bridge, sc = sess.scan;
  const pct = sc.total ? Math.round((100 * sc.done) / sc.total) : 0;
  // One bar for the whole way in: start Firestorm, log in, read the inventory.
  const stage = sc.state === "scanning" ? 2 : b.ready ? 2 : b.connected ? 1 : b.launched && !b.lost ? 0 : -1;
  const fill = sc.state === "scanning" ? 50 + pct / 2 : b.ready ? 50 : b.connected ? 33 : b.launched && !b.lost ? 12 : 0;
  const status = b.lost ? "The link to Firestorm dropped. Quit Firestorm, then press Start Firestorm again."
    : sc.state === "error" ? sc.message
    : sc.state === "scanning" ? (sc.message || "Reading your inventory…")
    : b.ready ? "Logged in. Reading your inventory starts by itself…"
    : b.connected ? "Firestorm is open. Log in as usual: the app never sees your password."
    : b.launched ? "Firestorm is starting…"
    : "Press Start Firestorm in the picture to begin.";
  const start = async () => {
    try { await api("/api/run/connect", { method: "POST", body: {} }); toast("Starting Firestorm…"); tick(); }
    catch (err) { toast(err.message); }
  };
  const busy = b.launched && !b.lost;
  // The painted button in the picture is the real button: a see-through button sits exactly on top of it.
  const hero = h("div", { class: "start-hero" + (busy ? " busy" : "") },
    h("img", { src: "start.jpg", alt: "Ria at her desk, pointing to a Start Firestorm button" }),
    busy ? h("span", { class: "start-hit label", role: "status" },
      b.connected ? (b.ready ? "Reading…" : "Log in…") : "Starting…")
      : h("button", { type: "button", class: "start-hit", "aria-label": "Start Firestorm", onclick: start }));
  const labels = ["Start Firestorm", "Log in", "Read your inventory"];
  const tipN = Math.floor(Date.now() / 7000) % START_TIPS.length;      // a new one every 7 seconds
  const tip = h("p", { class: "ctip" + (tipN !== lastTip && lastTip !== -1 ? " fade" : ""), "aria-live": "polite" },
    h("span", { class: "ctip-mark", "aria-hidden": "true" }, "♡"), START_TIPS[tipN]);
  lastTip = tipN;
  show(h("section", { class: "connect" },
    h("h1", {}, "Let’s get your inventory"),
    !b.launched || b.lost ? h("div", { class: "cwarn", role: "note" },
      h("b", {}, "Is Firestorm already open?"), " If yes, please close it. The app can only connect when Firestorm is initially opening.") : null,
    hero,
    h("div", { class: "cprog" },
      h("div", { class: "bar big", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(fill)) },
        h("div", { style: { width: `${Math.max(fill, 2)}%` } })),
      h("ol", { class: "cstages" }, labels.map((l, i) => h("li", { class: i < stage || (i === 2 && !sess.locked) ? "done" : i === stage ? "now" : "" }, l))),
      h("p", { class: "cstatus" + (b.lost || sc.state === "error" ? " err" : "") }, status,
        sc.state === "error" ? h("button", { type: "button", class: "btn", onclick: async () => {
          try { await api("/api/scan", { method: "POST", body: {} }); tick(); } catch (err) { toast(err.message); } } }, "Try again") : null,
        b.lost ? h("button", { type: "button", class: "btn primary", onclick: start }, "Start Firestorm") : null),
      tip),
  ));
}

// A rescan reads the inventory in the background; the page is redrawn once, when it's finished.
let lastScan = null;
function rescanButton(sc) {
  const b = document.getElementById("rescan");
  const busy = sc && sc.state === "scanning";
  b.disabled = busy ? true : null;
  b.textContent = busy ? `Reading… ${sc.total ? Math.round((100 * sc.done) / sc.total) : 0}%` : "Rescan";
}
async function tick() {
  try {
    const { sess, changed } = await refreshSession();
    const scan = sess.scan ? sess.scan.state : null;
    const finished = lastScan === "scanning" && scan !== "scanning";
    lastScan = scan;
    rescanButton(sess.scan);
    if (sess.locked && !OFFLINE) { if (!location.hash.startsWith("#/about")) await connectPage(sess); }
    else if (changed || finished) {
      TREE = null; await loadPicker().catch(() => {});
      if (finished && !changed) toast(scan === "error" ? "Couldn’t read your inventory again. Try Rescan once more." : "Inventory updated");
      route({ keepScroll: true });
    }
  } catch (e) { /* app restarting */ }
}
function startSessionTimer() {
  if (sessTimer) clearInterval(sessTimer);
  sessTimer = setInterval(() => { if (LOCKED || !OFFLINE) tick(); }, 2000);
}

// ------------------------------------------------------------------ router
// keepScroll: re-draw the same page after a change without jumping back to the top.
async function route(opts) {
  const keep = opts && opts.keepScroll ? window.scrollY : null;
  if (!location.hash.startsWith("#/plan")) stopRunTimer();
  if (LOCKED && !OFFLINE && !location.hash.startsWith("#/about")) {
    try { const { sess } = await refreshSession(); if (sess.locked) return connectPage(sess); } catch (e) { return; }
  }
  const hash = location.hash || "#/overview";
  const [path, query] = hash.slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  const page = parts[0] || "overview";
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === page));
  const q = new URLSearchParams(query || "").get("q");
  try {
    if (page === "folders") await (q !== null && q !== "" ? search(q) : folders(parts[1] || null));
    else if (page === "categories") await categories();
    else if (page === "sort") await sortPage(parts[1] || null);
    else if (page === "plan") await planPage();
    else if (page === "duplicates") await duplicatesPage();
    else if (page === "about") await aboutPage();
    else await overview();
  } catch (err) { showError(err); }
  if (keep !== null) window.scrollTo(0, keep);
  if (pendingScroll !== null) { const y = pendingScroll; pendingScroll = null; requestAnimationFrame(() => window.scrollTo(0, y)); }
}
// "Back to …" after "Look inside" on the Sort page or opening a search result: back to the same place and scroll spot.
const scrollAt = {};
let RETURN = null, pendingScroll = null;
window.addEventListener("scroll", () => { scrollAt[location.hash || "#/overview"] = window.scrollY; }, { passive: true });
const PAGE_NAMES = { sort: "Sort", duplicates: "Duplicates", plan: "Plan & Run", overview: "Overview", categories: "Categories" };
function returnLabel(hash) {
  const page = (hash.slice(2).split(/[/?]/)[0]) || "overview";
  if (page === "sort") {
    const cid = hash.split("/")[2];
    if (cid === "unsure") return "Not sure yet";
    if (cid === "trash") return "To Trash";
    const sub = TREE && TREE.tops.flatMap((t) => t.children).find((c) => c.id === cid);
    return sub ? sub.name : "Sort";
  }
  if (page === "folders" && hash.includes("?q=")) return "Search";
  return PAGE_NAMES[page] || "where you were";
}
function backBar() {
  if (!RETURN) return null;
  return h("p", { class: "backbar" }, h("button", { type: "button", class: "btn", onclick: () => {
    pendingScroll = RETURN.y; const to = RETURN.hash; RETURN = null; location.hash = to; } },
    "← Back to ", returnLabel(RETURN.hash)));
}
window.addEventListener("hashchange", (e) => {
  const oldHash = new URL(e.oldURL).hash || "#/overview";
  const isFolder = (hsh) => hsh.startsWith("#/folders") && !hsh.includes("?q=");
  const fromSearch = oldHash.startsWith("#/folders") && oldHash.includes("?q=");
  if (isFolder(location.hash) && (oldHash.startsWith("#/sort") || fromSearch)) RETURN = { hash: oldHash, y: scrollAt[oldHash] || 0 };
  else if (!isFolder(location.hash)) RETURN = null;
  route();
});
// Tell the desktop app this window is closing, so it can quit soon after the last one closes.
window.addEventListener("pagehide", () => {
  try { navigator.sendBeacon(`/api/window-closed?t=${encodeURIComponent(TOKEN)}`); } catch (e) { /* not supported */ }
});
refreshSession().catch(() => {}).finally(() => {
  if (OFFLINE) loadPicker().catch(() => {});
  route(); startSessionTimer();
});
