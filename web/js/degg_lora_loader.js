const HEAD_H = 34;
// Шаг кнопок «−»/«+» силы LoRA (как у поля силы в нативной ноде).
const STRENGTH_STEP = 0.05;
// Ручная тяга по значению (scrub) — как у поля силы в нативной ноде:
// один шаг на каждые 10px движения и порог 50px, отделяющий тягу от клика.
const SCRUB_PX_PER_STEP = 10;
const SCRUB_THRESHOLD = 50;
// Состояние активной тяги: слой, строка и накопленный путь в пикселях.
const SCRUB = { el: null, node: null, index: -1, startX: 0, startY: 0, delta: 0, swiping: false };
const ROW_H = 90;
const LIST_ROWS = 3;
const MARGIN = 10;
const CONTENT_MIN_H = HEAD_H + ROW_H * LIST_ROWS;
const MIN_W = 360;

const CSS_TEXT = [
  ".dl-root{height:100%;min-height:304px;display:flex;flex-direction:column;overflow:hidden;margin:10px;font-size:13px;color:#ddd;}",
  ".dl-head{display:flex;align-items:center;gap:6px;height:34px;flex:0 0 auto;}",
  ".dl-add,.dl-all,.dl-x,.dl-del{font:inherit;cursor:pointer;}",
  ".dl-add{flex:0 0 auto;padding:4px 10px;border:1px solid #5a5a5a;border-radius:4px;background:#2a2a2a;color:#eee;}",
  ".dl-count{flex:1 1 auto;text-align:right;color:#9c9c9c;}",
  ".dl-allwrap{display:flex;align-items:center;gap:6px;flex:0 0 auto;}",
  ".dl-all{flex:0 0 auto;}",
  ".dl-alllabel{font-size:12px;color:#9c9c9c;}",
  ".dl-list{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;display:flex;flex-direction:column;gap:6px;padding:2px 0;}",
  ".dl-foot{flex:0 0 auto;display:flex;padding-top:6px;}",
  ".dl-foot .dl-add{flex:1 1 auto;font-weight:600;}",
  ".dl-empty{padding:16px 8px;text-align:center;color:#8a8a8a;}",
  ".dl-row{display:flex;align-items:center;gap:8px;height:82px;padding:4px 6px;border:1px solid #3a3a3a;border-radius:6px;background:#232323;}",
  ".dl-row.dl-off{opacity:.45;}",
  ".dl-sw{position:relative;flex:0 0 auto;width:40px;height:24px;padding:0;border:none;border-radius:12px;background:var(--interface-stroke,#4a4a4a);cursor:pointer;transition:background .15s;}",
  ".dl-sw[aria-checked=\"true\"]{background:var(--primary-background,#5b8def);}",
  ".dl-sw[aria-checked=\"true\"] .dl-knob{transform:translateX(16px);}",
  ".dl-knob{position:absolute;top:4px;left:4px;width:16px;height:16px;border-radius:50%;background:var(--base-background,#f0f0f0);box-shadow:0 1px 2px rgba(0,0,0,.35);pointer-events:none;transition:transform .15s;}",
  ".dl-thumb{flex:0 0 auto;width:82px;height:82px;border-radius:4px;overflow:hidden;background:#1a1a1a;display:flex;align-items:center;justify-content:center;cursor:pointer;}",
  ".dl-glyph{width:100%;height:100%;background:repeating-linear-gradient(45deg,#1f1f1f 0 6px,#242424 6px 12px);}",
  ".dl-img{width:82px;height:82px;object-fit:cover;display:block;}",
  ".dl-name{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:1px;overflow:hidden;}",
  ".dl-bm{font-size:10px;color:#8a8a8a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
  ".dl-ln{font-size:12px;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
  ".dl-num{flex:0 0 auto;width:92px;height:24px;display:flex;align-items:center;overflow:hidden;border-radius:6px;background:var(--component-node-widget-background,#2a2a2a);color:var(--component-node-foreground,#ddd);font-size:12px;}",
  ".dl-num-mid{position:relative;flex:1 1 auto;min-width:0;height:100%;display:flex;align-items:center;}",
  ".dl-num-scrub{position:absolute;top:0;right:0;bottom:0;left:0;z-index:1;cursor:ew-resize;touch-action:pan-y;}",
  ".dl-num-scrub.dl-scrub-edit{display:none;}",
  ".dl-num-btn{flex:0 0 auto;width:24px;height:100%;padding:0;border:0;border-radius:0;background:transparent;color:inherit;font:inherit;cursor:pointer;display:flex;align-items:center;justify-content:center;}",
  ".dl-num-btn:hover{background:var(--component-node-widget-background-hovered,rgba(255,255,255,.1));}",
  ".dl-num-btn svg{width:14px;height:14px;display:block;}",
  ".dl-num-input{flex:1 1 auto;min-width:0;height:100%;border:0;background:transparent;color:inherit;font:inherit;text-align:center;padding:0;outline:none;}",
  ".dl-del{flex:0 0 auto;width:28px;height:28px;color:#9c9c9c;background:transparent;border:none;outline:none;}",
  ".dl-modal{position:fixed;inset:0;z-index:1200;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;}",
  ".dl-picker,.dl-info{position:relative;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;background:#232323;border:1px solid #4a4a4a;border-radius:8px;padding:14px;}",
  ".dl-title{font-weight:bold;margin-bottom:8px;}",
  ".dl-x{position:absolute;top:8px;right:8px;width:26px;height:26px;border:1px solid #5a5a5a;border-radius:4px;background:#2a2a2a;color:#eee;}",
  ".dl-items{display:flex;flex-direction:column;gap:4px;}",
  ".dl-pitem{display:flex;align-items:center;gap:8px;padding:6px;border:1px solid #3a3a3a;border-radius:4px;cursor:pointer;background:#1f1f1f;}",
  ".dl-pitem.dl-used{opacity:.5;}",
  ".dl-pthumb{width:32px;height:32px;object-fit:cover;border-radius:3px;background:#151515;flex:0 0 auto;}",
  ".dl-pt{width:32px;height:32px;flex:0 0 auto;border-radius:3px;overflow:hidden;background:#151515;display:flex;align-items:center;justify-content:center;}",
  ".dl-plabel{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
  ".dl-iname{font-size:15px;font-weight:bold;margin-bottom:6px;}",
  ".dl-irow{display:flex;gap:6px;margin:3px 0;}",
  ".dl-ilabel{color:#9c9c9c;flex:0 0 auto;}",
  ".dl-ival{flex:1 1 auto;min-width:0;}",
  ".dl-idesc{margin:6px 0;white-space:pre-wrap;}",
  ".dl-imgs{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;}",
  ".dl-iimg,.dl-localimg{max-width:150px;max-height:150px;border-radius:4px;}",
  ".dl-ierr{color:#e08a8a;}",
  ".dl-ppick{max-width:640px;}",
  ".dl-pcard{display:flex;align-items:center;gap:8px;margin-bottom:8px;}",
  ".dl-path{flex:1 1 auto;min-width:0;font-size:12px;color:#ccc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
  ".dl-details{margin:2px 0 8px;}",
  "a.dl-iname{display:inline-block;margin-bottom:6px;color:#7fb4ff;text-decoration:none;cursor:pointer;}",
  "a.dl-iname:hover{text-decoration:underline;}",
  ".dl-pgrid{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;}",
  ".dl-pcand{width:140px;height:140px;border:2px solid #3a3a3a;border-radius:6px;overflow:hidden;cursor:pointer;background:#151515;display:flex;align-items:center;justify-content:center;}",
  ".dl-pcand.dl-pcur{border-color:var(--primary-background,#5b8def);}",
  ".dl-pcimg{max-width:140px;max-height:140px;display:block;}",
  ".dl-pbtns{display:flex;gap:8px;}",
  ".dl-pup,.dl-preset{font:inherit;cursor:pointer;padding:5px 10px;border:1px solid #5a5a5a;border-radius:4px;background:#2a2a2a;color:#eee;}",
  ".dl-pfile{display:none;}",
].join("\n");

let styleInjected = false;
function injectCss() {
  if (styleInjected) return;
  if (typeof document === "undefined" || !document.createElement) return;
  styleInjected = true;
  const el = document.createElement("style");
  el.textContent = CSS_TEXT;
  if (document.head) document.head.appendChild(el);
  else if (document.body) document.body.appendChild(el);
}

const LOCALES = {
  ru: {
    add: "+ Лора",
    all: "Все вкл/выкл",
    empty: "Нет LoRA — нажмите + Лора",
    pickTitle: "Выбор LoRA",
    emptyCatalog: "Список LoRA пуст",
    infoTitle: "Информация о LoRA",
    base: "Базовая модель",
    triggers: "Триггеры",
    description: "Описание",
    openCivitai: "Открыть на CivitAI",
    incStrength: "Увеличить силу",
    decStrength: "Уменьшить силу",
    remove: "Удалить",
    loadError: "Не удалось загрузить данные",
    uploadBtn: "Загрузить картинку…",
    resetBtn: "Сбросить",
  },
  en: {
    add: "+ LoRA",
    all: "Toggle all",
    empty: "No LoRAs — press + LoRA",
    pickTitle: "Pick a LoRA",
    emptyCatalog: "No LoRAs found",
    infoTitle: "LoRA details",
    base: "Base model",
    triggers: "Triggers",
    description: "Description",
    openCivitai: "Open on CivitAI",
    incStrength: "Increase strength",
    decStrength: "Decrease strength",
    remove: "Remove",
    loadError: "Failed to load data",
    uploadBtn: "Upload image…",
    resetBtn: "Reset",
  },
};

let LOCALE_OVERRIDE = null;
function readComfyLocale() {
  if (LOCALE_OVERRIDE) return LOCALE_OVERRIDE;
  try {
    if (APP && APP.extensionManager && APP.extensionManager.setting) {
      const value = APP.extensionManager.setting.get("Comfy.Locale");
      if (value) return value;
    }
  } catch (err) {}
  try {
    if (APP && APP.ui && APP.ui.settings && APP.ui.settings.getSettingValue) {
      const value2 = APP.ui.settings.getSettingValue("Comfy.Locale", "en");
      if (value2) return value2;
    }
  } catch (err) {}
  return "en";
}
function isRu() { return /^ru/i.test(readComfyLocale()); }
function setLocaleOverride(value) {
  LOCALE_OVERRIDE = typeof value === "string" && value ? value : null;
  return LOCALE_OVERRIDE;
}
function t(key) {
  const dict = isRu() ? LOCALES.ru : LOCALES.en;
  const val = dict[key];
  if (typeof val === "string" && val) return val;
  const fallback = LOCALES.en[key];
  return typeof fallback === "string" && fallback ? fallback : key;
}

const TRACKED = [];
let CATALOG = null;
let CATALOG_PROMISE = null;
let PICKER_NODE = null;

function mk(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  return el;
}
function findByClass(root, cls) {
  if (!root || !root.children) return null;
  for (let i = 0; i < root.children.length; i++) {
    const c = root.children[i];
    if (!c) continue;
    const cn = String(c.className || "");
    if (cn.split(/\s+/).indexOf(cls) >= 0) return c;
    const deep = findByClass(c, cls);
    if (deep) return deep;
  }
  return null;
}
function stripHtml(text) {
  if (typeof text !== "string" || !text) return "";
  return text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}
// Значение силы показывается как нативное поле Nodes 2.0: число форматируется
// через Intl.NumberFormat для текущего языка (в RU — «3,52»), а вводимый текст
// принимает и запятую, и точку (ScrubableNumberInput.vue делает то же самое).
function formatStrength(value) {
  const f = Number(value);
  if (!isFinite(f)) return String(value);
  try {
    if (typeof Intl === "object" && Intl && typeof Intl.NumberFormat === "function") {
      return new Intl.NumberFormat(readComfyLocale(), {
        useGrouping: false,
        maximumFractionDigits: 4,
      }).format(f);
    }
  } catch (err) {}
  return String(f);
}
function normalizeNumberText(raw) {
  if (typeof raw !== "string") return raw;
  return raw.replace(/\s/g, "").replace(",", ".");
}
function roundStrength(value) {
  const f = Number(value);
  if (!isFinite(f)) return 0;
  return Math.round(f * 10000) / 10000;
}
function numValue(value, def) {
  if (typeof value === "boolean" || value === null || value === undefined) return Number(def);
  let f;
  if (typeof value === "number") f = value;
  else if (typeof value === "string" && value.trim() !== "") f = Number(value);
  else return Number(def);
  if (Number.isNaN(f)) return Number(def);
  if (f > 100) f = 100;
  else if (f < -100) f = -100;
  return f;
}
function flagValue(value, def) {
  if (value === null || value === undefined) return def;
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const v = value.trim().toLowerCase();
    return v === "1" || v === "true" || v === "yes" || v === "on";
  }
  return Boolean(value);
}
function parseLoras(raw) {
  let data = raw;
  if (typeof raw === "string") {
    try {
      data = JSON.parse(raw);
    } catch (err) {
      return [];
    }
  }
  if (data && typeof data === "object" && !Array.isArray(data)) data = data.loras;
  if (!Array.isArray(data)) return [];
  const out = [];
  for (const item of data) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    let lora = item.lora;
    if (typeof lora !== "string") continue;
    lora = lora.trim();
    if (!lora) continue;
    const strength = numValue(item.strength, 1);
    let clip;
    if (item.strength_clip === undefined || item.strength_clip === null) clip = strength;
    else clip = numValue(item.strength_clip, strength);
    const row = { on: flagValue(item.on, true), lora: lora, strength: strength, strength_clip: clip };
    if (typeof item.preview === "string" && item.preview) row.preview = item.preview;
    out.push(row);
  }
  return out;
}
function thumbSrc(name) {
  if (!Array.isArray(CATALOG)) return "";
  for (const cat of CATALOG) {
    if (cat && cat.name === name) {
      if (!cat.image) return "";
      return "/degg_lora_loader/img?file=" + encodeURIComponent(name);
    }
  }
  return "";
}

const INFO_MEM = Object.create(null);
const INFO_PENDING = Object.create(null);
const INFO_QUEUE = [];
const THUMB_MEM = Object.create(null);
let INFO_ACTIVE = 0;
let LAZY_OBSERVER = null;

function fetchInfo(name) {
  const key = String(name || "");
  if (Object.prototype.hasOwnProperty.call(INFO_MEM, key)) return Promise.resolve(INFO_MEM[key]);
  if (INFO_PENDING[key]) return INFO_PENDING[key];
  const run = new Promise(function (resolve) {
    const start = function () {
      INFO_ACTIVE += 1;
      fetch("/degg_lora_loader/info?file=" + encodeURIComponent(key))
        .then(function (res) {
          return res && res.ok ? res.json() : null;
        })
        .then(function (info) {
          resolve(info && typeof info === "object" ? info : null);
        })
        .catch(function () {
          resolve(null);
        })
        .then(function () {
          INFO_ACTIVE -= 1;
          const next = INFO_QUEUE.shift();
          if (next) next();
        });
    };
    if (INFO_ACTIVE < 3) start();
    else INFO_QUEUE.push(start);
  });
  INFO_PENDING[key] = run;
  run.then(function (val) {
    INFO_MEM[key] = val;
    delete INFO_PENDING[key];
  });
  return run;
}

function siteThumb(info) {
  if (info && Array.isArray(info.images) && info.images.length) {
    const im0 = info.images[0];
    if (im0 && typeof im0.url === "string" && im0.url) return im0.url;
  }
  return "";
}

function paintThumb(host, src, cls) {
  host.replaceChildren();
  if (src) {
    const img = mk("img", cls);
    img.loading = "lazy";
    img.addEventListener("error", function () {
      img.style.display = "none";
    });
    img.src = src;
    host.appendChild(img);
  } else {
    host.appendChild(mk("div", "dl-glyph"));
  }
}

function attachThumb(host, name, entry, cls, lazy) {
  if (!host) return;
  const custom = entry && typeof entry.preview === "string" && entry.preview ? entry.preview : "";
  const local = thumbSrc(name);
  const direct = custom || local;
  if (direct) {
    paintThumb(host, direct, cls);
    return;
  }
  const key = String(name || "");
  if (Object.prototype.hasOwnProperty.call(THUMB_MEM, key)) {
    paintThumb(host, THUMB_MEM[key], cls);
    return;
  }
  if (lazy && LAZY_OBSERVER) {
    host.setAttribute("data-lora", key);
    host.setAttribute("data-cls", cls || "");
    LAZY_OBSERVER.observe(host);
    return;
  }
  fetchInfo(key).then(function (info) {
    const src = siteThumb(info);
    THUMB_MEM[key] = src;
    paintThumb(host, src, cls);
  });
}

// Иконки lucide (minus/plus) — как в нативном виджете силы.
function lucideIcon(name) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const horizontal = document.createElementNS(SVG_NS, "path");
  horizontal.setAttribute("d", "M5 12h14");
  svg.appendChild(horizontal);
  if (name === "plus") {
    const vertical = document.createElementNS(SVG_NS, "path");
    vertical.setAttribute("d", "M12 5v14");
    svg.appendChild(vertical);
  }
  return svg;
}

const APP = (window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app) || window.app || null;

function ensureState(node) {
  if (!node._dl) {
    node._dl = {
      entries: [],
      dataW: null,
      listW: null,
      root: null,
      head: null,
      addBtn: null,
      allWrap: null,
      allSw: null,
      allLabel: null,
      countEl: null,
      list: null,
    };
  }
  return node._dl;
}

function findDataW(node, name) {
  const ws = node.widgets || [];
  for (const w of ws) {
    if (w && w.name === name) return w;
  }
  return null;
}

function ensureMinWidth(node) {
  if (!node || !node.size) return;
  if (node.size[0] < MIN_W) {
    node.setSize([MIN_W, node.size[1]]);
    if (typeof node.setDirtyCanvas === "function") node.setDirtyCanvas();
  }
}

function syncData(node) {
  const s = ensureState(node);
  if (s.dataW) s.dataW.value = JSON.stringify(s.entries);
}

function updateCount(node) {
  const s = ensureState(node);
  if (!s.countEl) return;
  const total = s.entries.length;
  if (!total) {
    s.countEl.textContent = "";
    return;
  }
  let on = 0;
  for (const e of s.entries) {
    if (e.on) on += 1;
  }
  s.countEl.textContent = on + "/" + total;
}

function trashIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("fill", "#9c9c9c");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z");
  svg.appendChild(path);
  return svg;
}

function buildRow(node, index) {
  const s = ensureState(node);
  const entry = s.entries[index];
  const row = mk("div", entry.on ? "dl-row" : "dl-row dl-off");
  const sw = mk("button", "dl-sw");
  sw.setAttribute("role", "switch");
  sw.setAttribute("aria-checked", entry.on ? "true" : "false");
  sw.appendChild(mk("span", "dl-knob"));
  sw.addEventListener("click", function () {
    toggleAt(node, index);
  });
  const thumb = mk("div", "dl-thumb");
  attachThumb(thumb, entry.lora, entry, "dl-img");
  thumb.addEventListener("click", function () {
    openLoraCard(node, index);
  });
  const name = mk("div", "dl-name");
  const bm = mk("div", "dl-bm");
  const ln = mk("div", "dl-ln");
  ln.textContent = entry.lora;
  ln.addEventListener("click", function () {
    openLoraCard(node, index);
  });
  name.appendChild(bm);
  name.appendChild(ln);
  row.title = entry.lora;
  fetchInfo(entry.lora).then(function (info) {
    if (!info) return;
    if (typeof info.name === "string" && info.name) ln.textContent = info.name;
    if (typeof info.baseModel === "string" && info.baseModel) bm.textContent = info.baseModel;
  });
  // Пилюля силы — структура нативного ScrubableNumberInput.vue:
  // кнопка «−» / поле / кнопка «+».
  const num = mk("div", "dl-num");
  const numDec = mk("button", "dl-num-btn dl-num-dec");
  numDec.type = "button";
  numDec.setAttribute("aria-label", t("decStrength"));
  numDec.appendChild(lucideIcon("minus"));
  numDec.addEventListener("click", function () {
    stepStrength(node, index, -1);
  });
  const numInput = mk("input", "dl-num-input");
  numInput.type = "text";
  numInput.inputMode = "decimal";
  numInput.setAttribute("autocomplete", "off");
  numInput.value = formatStrength(entry.strength);
  numInput.addEventListener("change", function (ev) {
    setStrength(node, index, ev && ev.target ? ev.target.value : numInput.value);
  });
  numInput.addEventListener("blur", function () {
    setClassFlag(numScrub, "dl-scrub-edit", false);
  });
  // Прозрачный слой поверх поля: зажатой ЛКМ можно тянуть значение влево/
  // вправо (курсор ←→), как в нативном поле силы Nodes 2.0.
  const numMid = mk("div", "dl-num-mid");
  const numScrub = mk("div", "dl-num-scrub");
  numScrub.addEventListener("pointerdown", function (ev) {
    scrubBegin(numScrub, node, index, ev);
  });
  numScrub.addEventListener("pointermove", function (ev) {
    scrubDrag(ev);
  });
  numScrub.addEventListener("pointerup", function (ev) {
    scrubEnd(numScrub, numInput, ev);
  });
  numScrub.addEventListener("pointercancel", function (ev) {
    // Жест забрал браузер — как в нативном поле, в ручной ввод не уходим.
    scrubEnd(numScrub, numInput, ev, true);
  });
  numMid.append(numInput, numScrub);
  const numInc = mk("button", "dl-num-btn dl-num-inc");
  numInc.type = "button";
  numInc.setAttribute("aria-label", t("incStrength"));
  numInc.appendChild(lucideIcon("plus"));
  numInc.addEventListener("click", function () {
    stepStrength(node, index, 1);
  });
  num.append(numDec, numMid, numInc);
  const del = mk("button", "dl-del");
  del.setAttribute("title", t("remove"));
  del.appendChild(trashIcon());
  del.addEventListener("click", function () {
    removeAt(node, index);
  });
  row.append(sw, thumb, name, num, del);
  return row;
}

function render(node) {
  const s = ensureState(node);
  if (!s.list) return;
  s.list.replaceChildren();
  if (!s.entries.length) {
    const empty = mk("div", "dl-empty");
    empty.textContent = t("empty");
    s.list.appendChild(empty);
  } else {
    for (let i = 0; i < s.entries.length; i++) {
      s.list.appendChild(buildRow(node, i));
    }
  }
  updateCount(node);
}

function refreshLabels(node) {
  const s = node && node._dl;
  if (!s) return;
  if (s.addBtn) s.addBtn.textContent = t("add");
  if (s.allLabel) s.allLabel.textContent = t("all");
  if (s.list) {
    const empty = findByClass(s.list, "dl-empty");
    if (empty) empty.textContent = t("empty");
    const rows = s.list.children;
    for (let i = 0; i < rows.length; i++) {
      const del = findByClass(rows[i], "dl-del");
      if (del) del.setAttribute("title", t("remove"));
      const dec = findByClass(rows[i], "dl-num-dec");
      if (dec) dec.setAttribute("aria-label", t("decStrength"));
      const inc = findByClass(rows[i], "dl-num-inc");
      if (inc) inc.setAttribute("aria-label", t("incStrength"));
      // Число переформатируется под новый язык (в RU — запятая).
      const field = findByClass(rows[i], "dl-num-input");
      const entry = s.entries[i];
      if (field && entry) field.value = formatStrength(entry.strength);
    }
  }
}

function addLora(node, rawName) {
  const s = ensureState(node);
  const name = typeof rawName === "string" ? rawName.trim() : "";
  if (!name) return;
  for (const e of s.entries) {
    if (e.lora === name) return;
  }
  s.entries.push({ on: true, lora: name, strength: 1, strength_clip: 1 });
  syncData(node);
  render(node);
}

function removeAt(node, index) {
  const s = ensureState(node);
  if (index < 0 || index >= s.entries.length) return;
  s.entries.splice(index, 1);
  syncData(node);
  render(node);
}

function toggleAt(node, index) {
  const s = ensureState(node);
  const entry = s.entries[index];
  if (!entry) return;
  entry.on = !entry.on;
  const row = s.list && s.list.children[index];
  if (row) {
    row.className = entry.on ? "dl-row" : "dl-row dl-off";
    const sw = row.children[0];
    if (sw && sw.setAttribute) sw.setAttribute("aria-checked", entry.on ? "true" : "false");
  }
  syncData(node);
  updateCount(node);
  updateAllSw(node);
}

function updateAllSw(node) {
  const s = ensureState(node);
  if (!s.allSw) return;
  const allOn = s.entries.length > 0 && s.entries.every(function (e) { return e.on; });
  s.allSw.setAttribute("aria-checked", allOn ? "true" : "false");
}

function toggleAll(node) {
  const s = ensureState(node);
  if (!s.entries.length) return;
  let anyOn = false;
  for (const e of s.entries) {
    if (e.on) {
      anyOn = true;
      break;
    }
  }
  const target = !anyOn;
  for (const e of s.entries) {
    e.on = target;
  }
  syncData(node);
  render(node);
  updateAllSw(node);
}

function setStrength(node, index, rawValue) {
  const s = ensureState(node);
  const entry = s.entries[index];
  if (!entry) return;
  const f = roundStrength(numValue(normalizeNumberText(rawValue), 1));
  entry.strength = f;
  entry.strength_clip = f;
  syncData(node);
  const row = s.list && s.list.children[index];
  const field = row ? findByClass(row, "dl-num-input") : null;
  if (field) field.value = formatStrength(f);
}

// Клик по «−»/«+» — как кнопки нативного поля силы.
function stepStrength(node, index, direction) {
  const s = ensureState(node);
  const entry = s.entries[index];
  if (!entry) return;
  setStrength(node, index, entry.strength + direction * STRENGTH_STEP);
}

// ── Ручная тяга по значению (scrub) ──────────────────────────────────────
// Как у поля силы Nodes 2.0: прозрачный слой поверх цифр с курсором ←→,
// зажатая ЛКМ тянет значение — один шаг силы на каждые 10px (вправо —
// больше). Отпустил без движения — попадаем в ручной ввод с выделенным
// текстом, и слой на это время прячется (.dl-scrub-edit), чтобы не мешать
// правке. Слушатели — только на своём слое (+ захват указателя): window и
// document не трогаем (глобальных слушателей в ноде нет).
function setClassFlag(el, name, on) {
  if (!el) return;
  const parts = String(el.className || "").split(/\s+/).filter(Boolean);
  const at = parts.indexOf(name);
  if (on && at < 0) parts.push(name);
  else if (!on && at >= 0) parts.splice(at, 1);
  el.className = parts.join(" ");
}

function scrubBegin(el, node, index, ev) {
  if (!el) return;
  SCRUB.el = el;
  SCRUB.node = node;
  SCRUB.index = index;
  SCRUB.startX = Number(ev && ev.clientX) || 0;
  SCRUB.startY = Number(ev && ev.clientY) || 0;
  SCRUB.delta = 0;
  SCRUB.swiping = false;
  if (ev && ev.pointerId !== undefined && typeof el.setPointerCapture === "function") {
    try {
      el.setPointerCapture(ev.pointerId);
    } catch (err) {}
  }
  if (ev && typeof ev.preventDefault === "function") ev.preventDefault();
}

function scrubDrag(ev) {
  if (!SCRUB.el) return;
  const x = Number(ev && ev.clientX) || 0;
  const y = Number(ev && ev.clientY) || 0;
  const dx = SCRUB.startX - x;
  const dy = SCRUB.startY - y;
  if (!SCRUB.swiping && Math.max(Math.abs(dx), Math.abs(dy)) >= SCRUB_THRESHOLD) {
    SCRUB.swiping = true;
  }
  const step = Math.trunc((dx - SCRUB.delta) / SCRUB_PX_PER_STEP);
  if (!step) return;
  SCRUB.delta += step * SCRUB_PX_PER_STEP;
  // dx = старт − текущая, поэтому «потянул вправо» → шаг вверх.
  stepStrength(SCRUB.node, SCRUB.index, -step);
}

function scrubEnd(el, field, ev, cancelled) {
  if (!SCRUB.el) return;
  const swiping = SCRUB.swiping || cancelled;
  SCRUB.el = null;
  SCRUB.node = null;
  SCRUB.index = -1;
  SCRUB.delta = 0;
  SCRUB.swiping = false;
  if (el && ev && ev.pointerId !== undefined && typeof el.releasePointerCapture === "function") {
    try {
      el.releasePointerCapture(ev.pointerId);
    } catch (err) {}
  }
  if (swiping) return;
  // Клик без движения — ручной ввод: слой прячем, текст выделен под замену.
  setClassFlag(el, "dl-scrub-edit", true);
  if (!field) return;
  if (typeof field.focus === "function") {
    try {
      field.focus();
    } catch (err) {}
  }
  if (typeof field.select === "function") {
    try {
      field.select();
    } catch (err) {}
  }
}

function closeModal() {
  PICKER_NODE = null;
  if (LAZY_OBSERVER) {
    LAZY_OBSERVER.disconnect();
    LAZY_OBSERVER = null;
  }
  const body = document.body;
  if (!body || !body.children) return;
  for (let i = body.children.length - 1; i >= 0; i--) {
    const el = body.children[i];
    if (el && String(el.className || "").includes("dl-modal")) el.remove();
  }
}

function openPicker(node) {
  closeModal();
  PICKER_NODE = node;
  const modal = mk("div", "dl-modal");
  const box = mk("div", "dl-picker");
  const title = mk("div", "dl-title");
  title.textContent = t("pickTitle");
  const closeBtn = mk("button", "dl-x");
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", closeModal);
  box.appendChild(title);
  box.appendChild(closeBtn);
  const items = mk("div", "dl-items");
  if (Array.isArray(CATALOG) && CATALOG.length) {
    const s = ensureState(node);
    const io = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(function (recs) {
      for (const rec of recs || []) {
        if (!rec || !rec.isIntersecting) continue;
        const host = rec.target;
        io.unobserve(host);
        const nm = host.getAttribute("data-lora");
        const cls = host.getAttribute("data-cls") || "dl-pthumb";
        attachThumb(host, nm, null, cls, false);
      }
    }, { root: box, rootMargin: "200px" });
    LAZY_OBSERVER = io;
    for (const cat of CATALOG) {
      if (!cat || typeof cat.name !== "string") continue;
      const used = s.entries.some(function (e) {
        return e.lora === cat.name;
      });
      const item = mk("div", used ? "dl-pitem dl-used" : "dl-pitem");
      let entry = null;
      for (const e2 of s.entries) {
        if (e2.lora === cat.name) {
          entry = e2;
          break;
        }
      }
      const thumb = mk("div", "dl-pt");
      attachThumb(thumb, cat.name, entry, "dl-pthumb", true);
      const label = mk("div", "dl-plabel");
      label.textContent = cat.name;
      item.appendChild(thumb);
      item.appendChild(label);
      (function (nm) {
        item.addEventListener("click", function () {
          addLora(node, nm);
          closeModal();
        });
      })(cat.name);
      items.appendChild(item);
    }
  } else {
    loadCatalog();
    const empty = mk("div", "dl-empty");
    empty.textContent = t("emptyCatalog");
    items.appendChild(empty);
  }
  box.appendChild(items);
  modal.appendChild(box);
  modal.addEventListener("click", function (ev) {
    if (ev && ev.target === modal) closeModal();
  });
  document.body.appendChild(modal);
}

function buildDetails(box, loraName, info) {
  const title = info && typeof info.name === "string" && info.name
    ? info.name
    : String(loraName || "");
  const permalink = info && typeof info.permalink === "string" && info.permalink
    ? info.permalink
    : "";
  if (permalink) {
    const nameLink = mk("a", "dl-iname");
    nameLink.href = permalink;
    nameLink.target = "_blank";
    nameLink.rel = "noopener";
    nameLink.title = t("openCivitai");
    nameLink.textContent = title;
    box.appendChild(nameLink);
  } else {
    const nm = mk("div", "dl-iname");
    nm.textContent = title;
    box.appendChild(nm);
  }
  if (!info) {
    const err = mk("div", "dl-ierr");
    err.textContent = t("loadError");
    box.appendChild(err);
    return;
  }
  {
    if (info.baseModel) {
      const row = mk("div", "dl-irow");
      const lb = mk("span", "dl-ilabel");
      lb.textContent = t("base") + ":";
      const val = mk("span", "dl-ival");
      val.textContent = String(info.baseModel);
      row.appendChild(lb);
      row.appendChild(val);
      box.appendChild(row);
    }
    let trig = "";
    if (Array.isArray(info.trigger)) trig = info.trigger.join(", ");
    else if (typeof info.trigger === "string") trig = info.trigger;
    if (trig) {
      const row = mk("div", "dl-irow");
      const lb = mk("span", "dl-ilabel");
      lb.textContent = t("triggers") + ":";
      const val = mk("span", "dl-ival");
      val.textContent = trig;
      row.appendChild(lb);
      row.appendChild(val);
      box.appendChild(row);
    }
    const desc = stripHtml(typeof info.description === "string" ? info.description : "");
    if (desc) {
      const lb = mk("div", "dl-ilabel");
      lb.textContent = t("description") + ":";
      const d = mk("div", "dl-idesc");
      d.textContent = desc;
      box.appendChild(lb);
      box.appendChild(d);
    }
  }
}

function openInfo(node, name) {
  const s = ensureState(node);
  let at = -1;
  for (let i = 0; i < s.entries.length; i++) {
    if (s.entries[i].lora === name) {
      at = i;
      break;
    }
  }
  return openLoraCard(node, at, name);
}

function setPreview(node, index, url) {
  const s = ensureState(node);
  const entry = s.entries[index];
  if (!entry) return;
  if (url) entry.preview = url;
  else delete entry.preview;
  syncData(node);
  render(node);
  closeModal();
}

// Единая карточка LoRA: клик по превью И по имени открывают её же.
// Сверху — детали (имя-ссылка на CivitAI, baseModel, триггеры, описание,
// permalink), ниже — сетка кандидатов превью + upload/reset.
// `index` < 0 → детали без превью (openInfo для лоры вне списка).
function openLoraCard(node, index, fallbackName) {
  closeModal();
  const s = ensureState(node);
  const entry = (typeof index === "number" && index >= 0) ? (s.entries[index] || null) : null;
  const loraName = entry ? entry.lora : (typeof fallbackName === "string" ? fallbackName.trim() : "");
  if (!loraName) return Promise.resolve(null);
  const modal = mk("div", "dl-modal");
  const box = mk("div", "dl-picker dl-ppick");
  const title = mk("div", "dl-title");
  title.textContent = t("infoTitle");
  const closeBtn = mk("button", "dl-x");
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", closeModal);
  box.appendChild(title);
  box.appendChild(closeBtn);
  const card = mk("div", "dl-pcard");
  const path = mk("div", "dl-path");
  path.textContent = loraName;
  path.title = loraName;
  card.appendChild(path);
  box.appendChild(card);
  const details = mk("div", "dl-details");
  box.appendChild(details);
  const grid = mk("div", "dl-pgrid");
  const addCand = function (src, isCurrent) {
    if (!src) return;
    for (const existing of grid.children) {
      if (existing._dlSrc === src) return;
    }
    const cand = mk("div", isCurrent ? "dl-pcand dl-pcur" : "dl-pcand");
    cand._dlSrc = src;
    const im = mk("img", "dl-pcimg");
    im.loading = "lazy";
    im.src = src;
    cand.appendChild(im);
    cand.addEventListener("click", function () {
      setPreview(node, index, src);
    });
    grid.appendChild(cand);
  };
  if (entry) {
    box.appendChild(grid);
    addCand(thumbSrc(loraName), !entry.preview);
    addCand(entry.preview, !!entry.preview);
    const btns = mk("div", "dl-pbtns");
    const fileInput = mk("input", "dl-pfile");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.addEventListener("change", function () {
      const f = fileInput.files && fileInput.files.length ? fileInput.files[0] : null;
      if (f) uploadPreview(node, index, f);
    });
    const upBtn = mk("button", "dl-pup");
    upBtn.textContent = t("uploadBtn");
    upBtn.addEventListener("click", function () {
      if (fileInput.click) fileInput.click();
    });
    const resetBtn = mk("button", "dl-preset");
    resetBtn.textContent = t("resetBtn");
    resetBtn.addEventListener("click", function () {
      setPreview(node, index, "");
    });
    btns.appendChild(upBtn);
    btns.appendChild(resetBtn);
    box.appendChild(fileInput);
    box.appendChild(btns);
  }
  modal.appendChild(box);
  modal.addEventListener("click", function (ev) {
    if (ev && ev.target === modal) closeModal();
  });
  document.body.appendChild(modal);
  return fetchInfo(loraName).then(function (info) {
    buildDetails(details, loraName, info || null);
    if (entry && info && Array.isArray(info.images)) {
      for (const im of info.images) {
        if (!im || typeof im.url !== "string" || !im.url) continue;
        addCand(im.url, entry.preview === im.url);
      }
    }
    return info || null;
  });
}

function openPreviewPicker(node, index) {
  return openLoraCard(node, index);
}

function uploadPreview(node, index, file) {
  const s = ensureState(node);
  const entry = s.entries[index];
  if (!entry || !file) return Promise.resolve(null);
  const fd = new FormData();
  fd.append("image", file, file.name || "preview.png");
  return fetch("/upload/image", { method: "POST", body: fd })
    .then(function (res) {
      return res && res.ok ? res.json() : null;
    })
    .then(function (data) {
      if (!data || typeof data.name !== "string" || !data.name) return null;
      const url = "/view?filename=" + encodeURIComponent(data.name)
        + "&subfolder=" + encodeURIComponent(data.subfolder || "")
        + "&type=" + encodeURIComponent(data.type || "input");
      setPreview(node, index, url);
      return url;
    })
    .catch(function () {
      return null;
    });
}

function loadCatalog() {
  if (CATALOG_PROMISE) return CATALOG_PROMISE;
  CATALOG_PROMISE = fetch("/degg_lora_loader/loras")
    .then(function (res) {
      return res && res.ok ? res.json() : null;
    })
    .then(function (data) {
      CATALOG = data && Array.isArray(data.loras) ? data.loras : [];
      for (let i = TRACKED.length - 1; i >= 0; i--) {
        const nd = TRACKED[i];
        if (nd && nd._dlReady && nd._dl) render(nd);
      }
      if (PICKER_NODE) openPicker(PICKER_NODE);
      return CATALOG;
    })
    .catch(function () {
      CATALOG = [];
      return CATALOG;
    });
  return CATALOG_PROMISE;
}

const EXT_NAME = "Degg.LoraLoader";

if (APP && typeof APP.registerExtension === "function") {
  APP.registerExtension({
    name: EXT_NAME,
    beforeRegisterNodeDef: function (nodeType, nodeData) {
      if (!nodeData || nodeData.name !== "Degg_LoRa_Loader") return;
      const proto = nodeType.prototype;
      const inheritedCreated = proto.onNodeCreated;
      const inheritedConfigure = proto.onConfigure;
      const inheritedRemoved = proto.onRemoved;

      proto.onNodeCreated = function () {
        if (typeof inheritedCreated === "function") inheritedCreated.apply(this, arguments);
        injectCss();
        const node = this;
        const s = ensureState(node);
        const dataW = findDataW(node, "loras_data");
        if (dataW) {
          dataW.hidden = true;
          if (!dataW.options) dataW.options = {};
          dataW.options.hidden = true;
          dataW.options.hideInPanel = true;
          s.dataW = dataW;
        }
        const root = mk("div", "dl-root");
        root.style.height = "100%";
        root.style.minHeight = CONTENT_MIN_H + "px";
        root.style.display = "flex";
        root.style.flexDirection = "column";
        root.style.overflow = "hidden";
        const head = mk("div", "dl-head");
        const addBtn = mk("button", "dl-add");
        addBtn.textContent = t("add");
        addBtn.addEventListener("click", function () {
          openPicker(node);
        });
        const countEl = mk("div", "dl-count");
        const allWrap = mk("div", "dl-allwrap");
        const allSw = mk("button", "dl-all dl-sw");
        allSw.setAttribute("role", "switch");
        allSw.setAttribute("aria-checked", "true");
        allSw.appendChild(mk("span", "dl-knob"));
        allSw.addEventListener("click", function () {
          toggleAll(node);
        });
        const allLabel = mk("span", "dl-alllabel");
        allLabel.textContent = t("all");
        allWrap.appendChild(allSw);
        allWrap.appendChild(allLabel);
        head.appendChild(allWrap);
        head.appendChild(countEl);
        const list = mk("div", "dl-list");
        const foot = mk("div", "dl-foot");
        foot.appendChild(addBtn);
        root.appendChild(head);
        root.appendChild(list);
        root.appendChild(foot);
        s.root = root;
        s.head = head;
        s.addBtn = addBtn;
        s.countEl = countEl;
        s.allWrap = allWrap;
        s.allSw = allSw;
        s.allLabel = allLabel;
        s.list = list;
        const listW = node.addDOMWidget(
          "degg_lora_list",
          "degg_lora_list",
          root,
          {
            hideOnZoom: false,
            hideInPanel: true,
            serialize: false,
            getMinHeight: function () {
              return CONTENT_MIN_H + MARGIN * 2;
            },
          }
        );
        listW.serialize = false;
        s.listW = listW;
        node._dlReady = true;
        if (TRACKED.indexOf(node) < 0) TRACKED.push(node);
        render(node);
        refreshLabels(node);
        ensureMinWidth(node);
        loadCatalog();
      };

      proto.onConfigure = function (info) {
        if (typeof inheritedConfigure === "function") inheritedConfigure.apply(this, arguments);
        const node = this;
        const s = ensureState(node);
        let raw = null;
        if (
          info &&
          info.widgets_values_named &&
          typeof info.widgets_values_named.loras_data === "string"
        ) {
          raw = info.widgets_values_named.loras_data;
        } else if (info && Array.isArray(info.widgets_values)) {
          for (const v of info.widgets_values) {
            if (typeof v === "string" && v.trim().charAt(0) === "[") {
              raw = v;
              break;
            }
          }
        }
        if (raw !== null) {
          s.entries = parseLoras(raw);
          if (s.dataW) s.dataW.value = raw;
        }
        render(node);
        refreshLabels(node);
        ensureMinWidth(node);
      };

      proto.onRemoved = function () {
        if (typeof inheritedRemoved === "function") inheritedRemoved.apply(this, arguments);
        closeModal();
        const node = this;
        const at = TRACKED.indexOf(node);
        if (at >= 0) TRACKED.splice(at, 1);
        node._dl = null;
        node._dlReady = false;
      };
    },
  });
}

window.DeggLoraLoader = {
  CONTENT_MIN_H: CONTENT_MIN_H,
  MARGIN: MARGIN,
  MIN_W: MIN_W,
  parseLoras: parseLoras,
  addLora: addLora,
  removeAt: removeAt,
  toggleAt: toggleAt,
  toggleAll: toggleAll,
  setStrength: setStrength,
  stepStrength: stepStrength,
  openPicker: openPicker,
  closeModal: closeModal,
  openLoraCard: openLoraCard,
  openInfo: openInfo,
  openPreviewPicker: openPreviewPicker,
  setPreview: setPreview,
  uploadPreview: uploadPreview,
  refreshLabels: refreshLabels,
  setLocaleOverride: setLocaleOverride,
  isRu: isRu,
  readComfyLocale: readComfyLocale,
  LOCALES: LOCALES,
  t: t,
  loadCatalog: loadCatalog,
};
