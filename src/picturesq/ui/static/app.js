// picturesq UI: one page, no build step. Talks to the JSON API in picturesq/ui/app.py.
"use strict";

const $ = (id) => document.getElementById(id);
const ADJUSTMENTS = [
  { key: "exposure", label: "Exposure", min: -3, max: 3, step: 0.05, unit: " EV" },
  { key: "warmth", label: "Warmth", min: -50, max: 50, step: 1, unit: "" },
  { key: "tint", label: "Tint", min: -30, max: 30, step: 1, unit: "" },
  { key: "contrast", label: "Contrast", min: -0.5, max: 0.5, step: 0.01, unit: "" },
  { key: "saturation", label: "Saturation", min: -1, max: 1, step: 0.01, unit: "" },
  { key: "vibrance", label: "Vibrance", min: -1, max: 1, step: 0.01, unit: "" },
];
const CATEGORY_LABELS = { all: "All", bw: "B/W", cold: "Cold", warm: "Warm", cinematic: "Cinematic" };

const ui = {
  state: null,
  active: null,
  selected: new Set(),
  anchor: null,
  scope: "photos",
  category: "all",
  clipboard: null,
  flaggedFirst: false,
};

// --- API ------------------------------------------------------------------------------

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error((body && body.error) || response.statusText);
  return body;
}

async function load() {
  try {
    ui.state = await api("/api/state");
    notice(null);
  } catch (error) {
    notice(error.message, true);
    return;
  }
  const names = ui.state.photos.map((p) => p.name);
  if (!names.includes(ui.active)) ui.active = names[0] || null;
  ui.selected = new Set([...ui.selected].filter((n) => names.includes(n)));
  if (ui.active && ui.selected.size === 0) ui.selected.add(ui.active);
  render();
}

async function commit(change) {
  const target = ui.scope === "project" ? "project" : [...ui.selected];
  try {
    ui.state = await api("/api/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, ...change }),
    });
    notice(null);
  } catch (error) {
    notice(error.message, true);
  }
  render();
}

function notice(message, isError = false) {
  const el = $("notice");
  el.hidden = !message;
  el.textContent = message || "";
  el.classList.toggle("error", isError);
}

function previewUrl(name, size, variant = "current", draft = null) {
  const query = new URLSearchParams({ size, variant, rev: ui.state.revision });
  if (draft) query.set("draft", JSON.stringify(draft));
  return `/api/preview/${encodeURIComponent(name)}?${query}`;
}

// --- small images: a queue, so they never take every connection the browser allows
// (6 per host) and the large preview always gets one ------------------------------------

const thumbs = { urgent: [], normal: [], running: 0, limit: 3 };

function loadThumb(img, url, urgent = false) {
  if (img.dataset.want === url) return;
  img.dataset.want = url;
  (urgent ? thumbs.urgent : thumbs.normal).push({ img, url });
  setTimeout(pumpThumbs, 0); // after the caller has put the image in the page
}

function pumpThumbs() {
  while (thumbs.running < thumbs.limit && (thumbs.urgent.length || thumbs.normal.length)) {
    const { img, url } = (thumbs.urgent.length ? thumbs.urgent : thumbs.normal).shift();
    // Skip images replaced since (a newer URL) or no longer shown (another photo's tiles).
    if (img.dataset.want !== url || !img.isConnected) continue;
    thumbs.running += 1;
    const loader = new Image();
    loader.onload = loader.onerror = () => {
      thumbs.running -= 1;
      if (img.dataset.want === url) img.src = url;
      pumpThumbs();
    };
    loader.src = url;
  }
}

// --- the large preview: only the latest request matters --------------------------------

const large = { busy: false, next: null, shown: null };

function showLarge(url) {
  if (url === large.shown && !large.busy) return;
  if (large.busy) {
    large.next = url;
    return;
  }
  large.busy = true;
  $("busy").hidden = false;
  const image = new Image();
  const done = () => {
    large.busy = false;
    const next = large.next;
    large.next = null;
    if (next && next !== url) showLarge(next);
    else $("busy").hidden = true;
  };
  image.onload = () => {
    $("large").src = url;
    large.shown = url;
    done();
  };
  image.onerror = () => {
    notice("could not render this photo", true);
    done();
  };
  image.src = url;
}

// --- what is being edited ---------------------------------------------------------------

function photo(name) {
  return ui.state.photos.find((p) => p.name === name);
}

function editedLook() {
  if (ui.scope === "project") return ui.state.look;
  const p = photo(ui.active);
  return p ? p.look : null;
}

function editedAdjustments() {
  if (ui.scope === "project") return ui.state.adjustments;
  const p = photo(ui.active);
  return p ? p.adjustments : {};
}

function lookInfo(key) {
  return ui.state.looks.find((l) => l.key === key);
}

// --- rendering ------------------------------------------------------------------------

function render() {
  if (!ui.state) return;
  $("project").textContent = ui.state.project;
  renderStrip();
  renderViewer();
  renderPanel();
  renderExportOutputs();
  fetch("/api/config").then((r) => r.text()).then((text) => ($("yaml").textContent = text));
}

function orderedPhotos() {
  const photos = [...ui.state.photos];
  if (ui.flaggedFirst) {
    photos.sort((a, b) => (b.flags.length > 0) - (a.flags.length > 0));
  }
  return photos;
}

function renderStrip() {
  const list = $("photos");
  const existing = new Map([...list.children].map((li) => [li.dataset.name, li]));
  const fragment = document.createDocumentFragment();
  for (const p of orderedPhotos()) {
    let li = existing.get(p.name);
    if (!li) {
      li = document.createElement("li");
      li.dataset.name = p.name;
      li.innerHTML = '<img alt=""><div class="caption"></div>';
      li.addEventListener("click", (event) => pick(p.name, event));
    }
    loadThumb(li.querySelector("img"), previewUrl(p.name, "thumb"));
    const own = p.look_override || Object.keys(p.adjustment_overrides).length || Object.keys(p.normalise).length;
    const look = p.look ? `${p.look.name} ${Math.round(p.look.intensity * 100)}%` : "no look";
    li.querySelector(".caption").innerHTML =
      `<span class="${own ? "own" : ""}">${own ? "● " : ""}</span>${escapeHtml(look)}`;
    li.title = p.name + (p.error ? `\n${p.error}` : "");
    let badge = li.querySelector(".badge");
    if (p.flags.length || p.error) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "badge";
        li.appendChild(badge);
      }
      badge.textContent = p.error ? "failed" : p.flags.map((f) => f.flag).join(", ");
    } else if (badge) {
      badge.remove();
    }
    li.classList.toggle("active", p.name === ui.active);
    li.classList.toggle("selected", ui.selected.has(p.name));
    fragment.appendChild(li);
  }
  list.replaceChildren(fragment);
}

function renderViewer() {
  const p = photo(ui.active);
  $("photo-name").textContent = p ? p.name : "no photos";
  $("photo-flags").textContent = p ? p.flags.map((f) => f.message).join(" · ") : "";
  if (p) showLarge(previewUrl(p.name, "large"));
}

function renderPanel() {
  const photosScope = ui.scope === "photos";
  $("scope-photos").setAttribute("aria-checked", photosScope);
  $("scope-project").setAttribute("aria-checked", !photosScope);
  $("scope-photos").textContent = `Selected photos (${ui.selected.size})`;
  $("scope-note").textContent = photosScope
    ? "Changes are saved as overrides on the selected photos."
    : "Changes set the project default; photos with their own override keep it.";
  $("normalise-section").hidden = !photosScope;
  $("paste").disabled = !ui.clipboard || !photosScope;
  $("reset").disabled = !photosScope;
  renderCategories();
  renderLooks();
  renderLookControls();
  renderAdjustments();
  if (photosScope) renderNormalise();
}

function renderCategories() {
  const categories = ["all", ...new Set(ui.state.looks.map((l) => l.category))];
  $("categories").replaceChildren(
    ...categories.map((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = CATEGORY_LABELS[c] || c;
      b.setAttribute("aria-checked", c === ui.category);
      b.onclick = () => {
        ui.category = c;
        renderPanel();
      };
      return b;
    }),
  );
}

function renderLooks() {
  const current = editedLook();
  const name = ui.active;
  const tiles = [{ key: null, label: "No look", variant: "none" }];
  for (const look of ui.state.looks) {
    if (ui.category === "all" || look.category === ui.category) {
      tiles.push({ key: look.key, label: look.key, variant: `look:${look.key}`, description: look.description });
    }
  }
  $("looks").replaceChildren(
    ...tiles.map((tile) => {
      const div = document.createElement("div");
      div.className = "look";
      const chosen = tile.key === null ? !current : current && current.name === tile.key;
      div.classList.toggle("chosen", Boolean(chosen));
      div.title = tile.description || "Neutral render plus adjustments";
      div.innerHTML = `<img alt=""><span>${escapeHtml(tile.label)}</span>`;
      if (name) loadThumb(div.querySelector("img"), previewUrl(name, "thumb", tile.variant), true);
      div.onclick = () => chooseLook(tile.key);
      return div;
    }),
  );
}

function chooseLook(key) {
  const current = editedLook();
  if (key === null) return commit({ look: { name: null } });
  if (current && current.name === key) return;
  const intensity = current ? current.intensity : 1;
  commit({ look: { name: key, intensity, parameters: {} } });
}

function renderLookControls() {
  const box = $("look-controls");
  const current = editedLook();
  box.replaceChildren();
  if (!current) return;
  const info = lookInfo(current.name);
  const draftLook = (patch) => ({ look: { ...current, ...patch, parameters: { ...current.parameters, ...(patch.parameters || {}) } } });
  box.appendChild(
    slider({
      label: "Intensity",
      value: current.intensity * 100,
      min: 0, max: 150, step: 1, unit: " %",
      set: true,
      onInput: (v) => draft(draftLook({ intensity: v / 100 })),
      onChange: (v) => commit(draftLook({ intensity: v / 100 })),
    }),
  );
  if (info) {
    for (const [key, parameter] of Object.entries(info.parameters)) {
      const value = key in current.parameters ? current.parameters[key] : parameter.default;
      const step = (parameter.max - parameter.min) / 100;
      box.appendChild(
        slider({
          label: parameter.label,
          value, min: parameter.min, max: parameter.max, step,
          set: key in current.parameters,
          onInput: (v) => draft(draftLook({ parameters: { [key]: v } })),
          onChange: (v) => commit(draftLook({ parameters: { [key]: v } })),
          onReset: () => {
            const parameters = { ...current.parameters };
            delete parameters[key];
            commit({ look: { ...current, parameters } });
          },
        }),
      );
    }
  }
  const p = photo(ui.active);
  if (ui.scope === "photos" && p && p.look_override) {
    const follow = document.createElement("button");
    follow.type = "button";
    follow.textContent = "Follow project look";
    follow.title = "Remove this photo's look override";
    follow.onclick = () => commit({ look: null });
    box.appendChild(follow);
  }
}

function renderAdjustments() {
  const values = editedAdjustments();
  const p = photo(ui.active);
  const overrides = ui.scope === "photos" && p ? p.adjustment_overrides : null;
  $("adjustments").replaceChildren(
    ...ADJUSTMENTS.map((a) =>
      slider({
        label: a.label,
        value: values[a.key] || 0,
        min: a.min, max: a.max, step: a.step, unit: a.unit,
        set: overrides ? a.key in overrides : values[a.key] !== 0,
        onInput: (v) => draft({ adjustments: { ...values, [a.key]: v } }),
        onChange: (v) => commit({ adjustments: { [a.key]: v } }),
        onReset: () => commit({ adjustments: { [a.key]: null } }),
      }),
    ),
  );
}

function renderNormalise() {
  const p = photo(ui.active);
  const box = $("normalise");
  box.replaceChildren();
  if (!p) return;
  const set = p.normalise;
  const exposure = "exposure_ev" in set ? set.exposure_ev : p.exposure_ev ?? ui.state.exposure_offset_ev;
  box.appendChild(
    slider({
      label: "Exposure",
      value: exposure, min: -2, max: 6, step: 0.05, unit: " EV",
      set: "exposure_ev" in set,
      onChange: (v) => commit({ normalise: { exposure_ev: v } }),
      onReset: () => commit({ normalise: { exposure_ev: null } }),
    }),
  );
  if (p.as_shot) {
    box.appendChild(
      slider({
        label: "White balance",
        value: "wb_kelvin" in set ? set.wb_kelvin : p.as_shot.kelvin,
        min: 2000, max: 12000, step: 50, unit: " K",
        set: "wb_kelvin" in set,
        onChange: (v) => commit({ normalise: { wb_kelvin: v } }),
        onReset: () => commit({ normalise: { wb_kelvin: null } }),
      }),
      slider({
        label: "WB tint",
        value: "tint" in set ? set.tint : p.as_shot.tint,
        min: -50, max: 50, step: 1, unit: "",
        set: "tint" in set,
        onChange: (v) => commit({ normalise: { tint: v } }),
        onReset: () => commit({ normalise: { tint: null } }),
      }),
    );
  }
  const hint = document.createElement("p");
  hint.className = "muted small";
  hint.textContent = "Double-click a label to reset it. Exposure and white balance re-normalise the photo.";
  box.appendChild(hint);
}

function slider({ label, value, min, max, step, unit = "", set = false, onInput, onChange, onReset }) {
  const row = document.createElement("div");
  row.className = "slider";
  row.classList.toggle("set", Boolean(set));
  const id = `s-${label.replace(/\W+/g, "-")}-${Math.random().toString(36).slice(2, 7)}`;
  row.innerHTML = `<label for="${id}"></label><input id="${id}" type="range"><output></output>`;
  const [labelEl, input, output] = row.children;
  labelEl.textContent = label;
  labelEl.title = onReset ? `${label} (double-click to reset)` : label;
  Object.assign(input, { min, max, step, value });
  const decimals = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
  const show = (v) => (output.textContent = `${Number(v).toFixed(decimals)}${unit}`);
  show(value);
  input.addEventListener("input", () => {
    show(input.value);
    if (onInput) onInput(Number(input.value));
  });
  input.addEventListener("change", () => onChange(Number(input.value)));
  if (onReset) labelEl.addEventListener("dblclick", onReset);
  return row;
}

function draft(values) {
  if (!ui.active) return;
  showLarge(previewUrl(ui.active, "medium", "current", values));
}

// --- selection ------------------------------------------------------------------------

function pick(name, event) {
  const order = orderedPhotos().map((p) => p.name);
  if (event && event.shiftKey && ui.anchor) {
    const [a, b] = [order.indexOf(ui.anchor), order.indexOf(name)].sort((x, y) => x - y);
    ui.selected = new Set(order.slice(a, b + 1));
  } else if (event && (event.ctrlKey || event.metaKey)) {
    if (ui.selected.has(name) && ui.selected.size > 1) ui.selected.delete(name);
    else ui.selected.add(name);
    ui.anchor = name;
  } else {
    ui.selected = new Set([name]);
    ui.anchor = name;
  }
  ui.active = name;
  if (!ui.selected.has(name)) ui.selected.add(name);
  render();
}

function step(delta) {
  const order = orderedPhotos().map((p) => p.name);
  const index = order.indexOf(ui.active);
  const next = order[Math.min(order.length - 1, Math.max(0, index + delta))];
  if (next && next !== ui.active) {
    pick(next, null);
    const li = [...$("photos").children].find((el) => el.dataset.name === next);
    if (li) li.scrollIntoView({ block: "nearest" });
  }
}

// --- export ---------------------------------------------------------------------------

function renderExportOutputs() {
  const box = $("export-outputs");
  if (box.childElementCount) return;
  for (const [name, output] of Object.entries(ui.state.outputs)) {
    const label = document.createElement("label");
    const size = output.long_edge ? `${output.long_edge}px` : "full size";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(name)}" checked> ${escapeHtml(name)} <span class="muted">${size}</span>`;
    box.appendChild(label);
  }
}

async function startExport() {
  const outputs = [...$("export-outputs").querySelectorAll("input:checked")].map((i) => i.value);
  if (!outputs.length) return notice("choose at least one output", true);
  try {
    await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outputs }),
    });
  } catch (error) {
    return notice(error.message, true);
  }
  pollExport();
}

async function pollExport() {
  const job = await api("/api/export").catch(() => null);
  const status = $("export-status");
  $("export-button").disabled = Boolean(job && job.running);
  if (!job) return;
  const failed = job.failed.length ? `, ${job.failed.length} failed` : "";
  if (job.running) {
    status.textContent = `exporting ${job.done}/${job.total}${failed} · ${job.seconds}s`;
    setTimeout(pollExport, 1000);
  } else {
    status.textContent = job.exit_code === 0
      ? `exported ${job.done} photo(s) in ${job.seconds}s → exports/`
      : `export finished with errors${failed}: ${job.last || ""}`;
  }
}

// --- wiring ---------------------------------------------------------------------------

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function holdBefore(on) {
  if (!ui.active) return;
  if (on) $("large").src = previewUrl(ui.active, "large", "neutral");
  else if (large.shown) $("large").src = large.shown;
}

$("scope-photos").onclick = () => { ui.scope = "photos"; renderPanel(); };
$("scope-project").onclick = () => { ui.scope = "project"; renderPanel(); };
$("select-all").onclick = () => { ui.selected = new Set(ui.state.photos.map((p) => p.name)); render(); };
$("flagged-first").onchange = (e) => { ui.flaggedFirst = e.target.checked; renderStrip(); };
$("export-button").onclick = startExport;
$("copy").onclick = () => {
  const p = photo(ui.active);
  if (!p) return;
  ui.clipboard = { look: p.look || { name: null }, adjustments: { ...p.adjustments } };
  notice(`copied the grade of ${p.name}`);
  renderPanel();
};
$("paste").onclick = () => ui.clipboard && commit({ look: ui.clipboard.look, adjustments: ui.clipboard.adjustments });
$("reset").onclick = () => commit({ reset: true });
const before = $("before");
before.addEventListener("mousedown", () => holdBefore(true));
before.addEventListener("mouseup", () => holdBefore(false));
before.addEventListener("mouseleave", () => holdBefore(false));

document.addEventListener("keydown", (event) => {
  if (event.target.tagName === "INPUT" && event.target.type !== "checkbox") return;
  if (event.key === "ArrowDown" || event.key === "ArrowRight" || event.key === "j") { step(1); event.preventDefault(); }
  else if (event.key === "ArrowUp" || event.key === "ArrowLeft" || event.key === "k") { step(-1); event.preventDefault(); }
  else if (event.key === "\\" && !event.repeat) holdBefore(true);
  else if (event.key === "c" && !event.ctrlKey && !event.metaKey) $("copy").click();
  else if (event.key === "v" && !event.ctrlKey && !event.metaKey) $("paste").click();
  else if (event.key === "a" && !event.ctrlKey && !event.metaKey) $("select-all").click();
});
document.addEventListener("keyup", (event) => { if (event.key === "\\") holdBefore(false); });

// An agent (or another tab) editing picturesq.yaml: reload when the revision moves.
const events = new EventSource("/api/events");
events.onmessage = (message) => {
  const data = JSON.parse(message.data);
  if (data.error) notice(`picturesq.yaml: ${data.error}`, true);
  else if (ui.state && data.revision !== ui.state.revision) load();
};

load().then(pollExport);
