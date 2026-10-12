"use strict";
/* The explorer's behaviour. build_map.py puts this file, plus the project data, into one HTML page. */
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (s, el = document) => el.querySelector(s);
const byPath = Object.fromEntries(D.files.map(f => [f.path, f]));
const layerOf = Object.fromEntries(D.layers.map(l => [l.id, l]));
let tab = "tours", selected = null, tourIx = 0, query = "";

/* Text is always set with textContent / text nodes, never as HTML. */
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(k ?? ""));
  return e;
}
function rich(text) { // `code` spans only
  const out = document.createDocumentFragment();
  String(text).split(/(`[^`]+`)/).forEach(part =>
    out.append(part.startsWith("`") ? el("code", {}, part.slice(1, -1)) : document.createTextNode(part)));
  return out;
}
const base = p => p.split("/").pop();
const gh = (p, line) => `${D.repo}/blob/main/${p}${line ? "#L" + line : ""}`;

/* ---------- header ---------- */
$("#gh").href = D.repo;
const root = document.documentElement;
try { const t = localStorage.getItem("wl-theme"); if (t) root.dataset.theme = t; } catch (e) { /* private mode */ }
$("#theme").addEventListener("click", () => {
  const dark = (root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  root.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("wl-theme", root.dataset.theme); } catch (e) { /* ignore */ }
});
$("#stats").append(
  el("span", {class: "chip"}, `${D.totals.files} files`),
  el("span", {class: "chip"}, `${D.totals.app_lines.toLocaleString()} lines of app code`),
  el("span", {class: "chip"}, `${D.totals.test_lines.toLocaleString()} lines of tests`),
  el("span", {class: "chip"}, `${D.commands.filter(c => c.menu).length} menu commands`),
  el("span", {class: "chip"}, `${D.tables.length} database tables`),
);

/* ---------- tabs ---------- */
const TABS = [["tours", "Guided tours"], ["map", "Map"], ["commands", "Commands"], ["data", "Data & encryption"], ["files", "All files"]];
function drawTabs() {
  const box = $("#tabs"); box.replaceChildren();
  for (const [id, label] of TABS) {
    box.append(el("button", {class: "tab", role: "tab", type: "button", "aria-selected": String(tab === id && !query),
      on: {click: () => { tab = id; $("#q").value = ""; query = ""; render(); }}}, label));
  }
}

/* ---------- views ---------- */
function fileButton(f, state) {
  return el("button", {class: "file " + (state || ""), type: "button", title: f.path, on: {click: () => select(f.path)}},
    base(f.path), el("small", {}, f.note.replace(/`/g, "").slice(0, 60)));
}
function mapView() {
  const sel = selected && byPath[selected];
  const uses = new Set(sel ? sel.uses : []), usedBy = new Set(sel ? sel.used_by : []);
  const wrap = el("div");
  wrap.append(el("p", {class: "legend"}, el("span", {class: "l-sel"}, "selected"), el("span", {class: "l-uses"}, "it uses"),
    el("span", {class: "l-usedby"}, "uses it"), el("span", {}, "Click any file.")));
  const grid = el("div", {class: "layers"});
  for (const l of D.layers) {
    const card = el("section", {class: "layer"}, el("h3", {}, l.title), el("p", {}, l.about));
    for (const f of D.files.filter(f => f.layer === l.id)) {
      const st = f.path === selected ? "sel" : uses.has(f.path) ? "uses" : usedBy.has(f.path) ? "usedby" : sel ? "dim" : "";
      card.append(fileButton(f, st));
    }
    grid.append(card);
  }
  wrap.append(grid);
  return wrap;
}
function toursView() {
  const wrap = el("div");
  wrap.append(el("p", {class: "note"}, "Pick a story. Each one follows a real request through the code, one file at a time. Click a step to open that file."));
  const cards = el("div", {class: "cards"});
  D.tours.forEach((t, i) => cards.append(el("button", {class: "card" + (i === tourIx ? " on" : ""), type: "button",
    on: {click: () => { tourIx = i; render(); }}}, el("b", {}, t.title), el("span", {}, t.ask))));
  wrap.append(cards);
  const t = D.tours[tourIx];
  const list = el("ol", {class: "steps"});
  t.steps.forEach((s, i) => list.append(el("li", {}, el("span", {class: "n"}, String(i + 1)),
    el("button", {type: "button", on: {click: () => select(s.path)}}, el("small", {}, s.path), rich(s.text)))));
  wrap.append(el("h2", {style: "margin:22px 0 0;font-size:19px"}, t.title), list);
  return wrap;
}
function commandsView() {
  const wrap = el("div"), t = el("table");
  t.append(el("tr", {}, ...["Command", "What it does", "Handled in"].map(h => el("th", {}, h))));
  for (const c of D.commands) {
    t.append(el("tr", {}, el("td", {}, el("code", {}, c.command), c.menu ? "" : el("span", {class: "pill", style: "margin-left:6px"}, "hidden")),
      el("td", {}, c.what),
      el("td", {}, el("button", {class: "pill", type: "button", on: {click: () => select(c.file)}}, base(c.file)))));
  }
  wrap.append(el("p", {class: "note"}, "Type / in Telegram to see the menu. Anything that is not a command is read by the rules, then (if needed) the AI."), t);
  return wrap;
}
function dataView() {
  const wrap = el("div"), t = el("table");
  t.append(el("tr", {}, ...["Table", "Holds", "Encrypted columns"].map(h => el("th", {}, h))));
  for (const x of D.tables) {
    t.append(el("tr", {}, el("td", {}, el("code", {}, x.name)), el("td", {}, rich(x.about)),
      el("td", {}, x.encrypted.length
        ? x.encrypted.map(c => el("span", {class: "pill lock", style: "margin-right:4px"}, "🔒 " + c))
        : el("span", {class: "pill"}, "none"))));
  }
  wrap.append(
    el("p", {class: "note"}, rich("Free text people type (notes, chat history) and AI keys are encrypted in the file with `SECRET_KEY` (AES via Fernet, a different key per purpose, a fresh random value every time). Amounts, dates, balances and category/merchant names stay readable so the database can add them up.")),
    el("p", {class: "note"}, "Can the operator read it? Yes: the server holds SECRET_KEY because it must read your data to answer you. The encryption protects a copied database file or backup, not a person running the server."),
    t,
    el("p", {}, el("button", {class: "pill", type: "button", on: {click: () => select("app/crypto.py")}}, "app/crypto.py"), " ",
      el("button", {class: "pill", type: "button", on: {click: () => select("app/models.py")}}, "app/models.py"), " ",
      el("a", {class: "pill", href: gh("docs/SECURITY.md"), target: "_blank", rel: "noopener"}, "docs/SECURITY.md")));
  return wrap;
}
function listView(files) {
  if (!files.length) return el("p", {class: "empty"}, "Nothing matches.");
  const t = el("table");
  t.append(el("tr", {}, ...["File", "Layer", "What it is"].map(h => el("th", {}, h))));
  for (const f of files) {
    t.append(el("tr", {}, el("td", {}, el("button", {class: "pill", type: "button", on: {click: () => select(f.path)}}, f.path)),
      el("td", {}, el("span", {class: "badge"}, layerOf[f.layer].title)), el("td", {}, rich(f.note))));
  }
  return t;
}
function searchResults() {
  const q = query.toLowerCase();
  const hits = D.files.filter(f => f.path.toLowerCase().includes(q) || f.note.toLowerCase().includes(q) ||
    f.symbols.some(s => s.name.toLowerCase().includes(q) || s.doc.toLowerCase().includes(q)));
  const wrap = el("div", {}, el("p", {class: "note"}, `${hits.length} file${hits.length === 1 ? "" : "s"} match “${query}”`));
  const syms = hits.flatMap(f => f.symbols.filter(s => s.name.toLowerCase().includes(q)).map(s => ({f, s}))).slice(0, 12);
  if (syms.length) {
    wrap.append(el("div", {class: "sec"}, "Functions and classes"));
    for (const {f, s} of syms) {
      wrap.append(el("div", {class: "sym"}, el("a", {href: gh(f.path, s.line), target: "_blank", rel: "noopener"}, s.name),
        el("span", {}, `${base(f.path)} · line ${s.line}${s.doc ? " · " + s.doc : ""}`)));
    }
  }
  wrap.append(el("div", {class: "sec"}, "Files"), listView(hits));
  return wrap;
}

/* ---------- detail panel ---------- */
function chips(paths) {
  return paths.length
    ? el("div", {class: "pills"}, paths.map(p => el("button", {class: "pill", type: "button", on: {click: () => select(p)}}, base(p))))
    : el("span", {class: "pill"}, "nothing");
}
function drawDetail() {
  const box = $("#detail"), f = selected && byPath[selected];
  $("#layout").classList.toggle("has-detail", !!f);
  box.hidden = !f;
  if (!f) return;
  box.replaceChildren(
    el("button", {class: "close", type: "button", "aria-label": "Close", on: {click: () => { selected = null; render(); }}}, "×"),
    el("h2", {}, f.path),
    el("p", {style: "margin:6px 0"}, el("span", {class: "badge"}, layerOf[f.layer].title), " ", el("span", {class: "pill"}, f.lines + " lines")),
    el("p", {style: "margin:8px 0"}, rich(f.note)),
    el("a", {href: gh(f.path), target: "_blank", rel: "noopener"}, "Open on GitHub ↗"),
    el("div", {class: "sec"}, "Uses"), chips(f.uses),
    el("div", {class: "sec"}, "Used by"), chips(f.used_by),
  );
  if (f.symbols.length) {
    box.append(el("div", {class: "sec"}, "Main functions and classes"));
    for (const s of f.symbols.slice(0, 40)) {
      box.append(el("div", {class: "sym"}, el("a", {href: gh(f.path, s.line), target: "_blank", rel: "noopener"},
        (s.kind === "class" ? "class " : "") + s.name), el("span", {}, s.doc)));
    }
    if (f.symbols.length > 40) box.append(el("p", {class: "empty"}, `…and ${f.symbols.length - 40} more`));
  }
}

function select(path) {
  selected = path;
  render();
  if (matchMedia("(min-width: 980px)").matches) $("#detail").scrollTop = 0;
}
function render() {
  drawTabs();
  const v = $("#view"); v.replaceChildren();
  if (query) v.append(searchResults());
  else if (tab === "tours") v.append(toursView());
  else if (tab === "map") v.append(mapView());
  else if (tab === "commands") v.append(commandsView());
  else if (tab === "data") v.append(dataView());
  else v.append(listView(D.files));
  drawDetail();
  try { history.replaceState(null, "", "#" + (selected ? "f=" + encodeURIComponent(selected) : tab)); } catch (e) { /* ignore */ }
}
$("#q").addEventListener("input", e => { query = e.target.value.trim(); render(); });
addEventListener("keydown", e => {
  if (e.key === "Escape" && selected) { selected = null; render(); }
  if (e.key === "/" && document.activeElement !== $("#q")) { e.preventDefault(); $("#q").focus(); }
});

/* open straight to a file or tab from the link: #f=app/bot/nlu.py or #map */
const h = decodeURIComponent(location.hash.slice(1));
if (h.startsWith("f=") && byPath[h.slice(2)]) { selected = h.slice(2); tab = "map"; }
else if (TABS.some(t => t[0] === h)) tab = h;
render();
