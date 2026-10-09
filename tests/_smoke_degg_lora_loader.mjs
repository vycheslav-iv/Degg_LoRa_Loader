// JS-смоук Degg_LoRa_Loader: исполняет web/js/degg_lora_loader.js в vm-контексте
// с заглушками window/comfyAPI/document/fetch и проверяет контракт фронтенда:
//   • расширение зарегистрировано, beforeRegisterNodeDef фильтрует по имени;
//   • скрытый виджет loras_data: hidden/hidden-в-options/hideInPanel,
//     при этом ОСТАЁТСЯ в widgets_values (serialize не тронут) — иначе пропадает
//     персистентность;
//   • DOM-виджет degg_lora_list: addDOMWidget, hideOnZoom:false, hideInPanel,
//     getMinHeight (пол), БЕЗ getHeight/computeSize, serialize:false в ОБОИХ
//     местах (prompt читает options.serialize, workflow — widget.serialize);
//   • корень пола: height:100%, min-height, display:flex, flex-direction:column,
//     overflow:hidden (скил comfyui-dom-widget-sizing);
//   • DOM-структура: head (toggle-all слева / счётчик) + список строк
//     [toggle][thumb 82][name][strength][✕] + foot «+ LoRA» внизу;
//   • переключатели: dl-knob (только Nodes 2.0, legacy-режимы удалены);
//   • MIN_W: нода расширена до MIN_W при создании и при onConfigure;
//   • персистентность: onConfigure читает widgets_values_named → positional
//     фолбэк; любая правка пишет JSON в loras_data;
//   • клик по имени открывает инфо, клик по превью — пикер превью,
//     клик «+ LoRA» — модалку выбора;
//   • локализация RU/EN по setLocaleOverride; глобальных слушателей нет.
// Запуск: cd Degg_LoRa_Loader && node tests/_smoke_degg_lora_loader.mjs

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const FILE = path.join(ROOT, "web", "js", "degg_lora_loader.js");

const errors = [];
const oks = [];
const check = (label, cond, extra = "") => {
  (cond ? oks : errors).push(label);
  if (!cond) console.log(`  ASSERT FAIL  ${label}${extra ? "  [" + extra + "]" : ""}`);
  else console.log(`  ok  ${label}`);
};

let capturedExt = null;
let rafQueue = [];
let windowAdds = 0;
let documentAdds = 0;
const FETCH_LOG = [];
const IO_INSTANCES = [];
const IO_OBSERVED = [];
// фикстура каталога: 3 лоры (у a — локальное превью, у остальных нет) — превью
// из каталога, глиф без картинки и ≥2 пунктов в picker зависят от этого списка;
// /info: у b сайт-картинка, у sub/c картинок нет, у a имя Civitai
const infoResp = (o) => ({ ok: true, json: async () => ({ ok: true, ...o }) });
let FETCH_RESULT = (raw) => {
  const u = String(raw);
  if (u.includes("/degg_lora_loader/loras")) {
    return {
      ok: true,
      json: async () => ({
    loras: [
      { name: "a.safetensors", image: "/degg_lora_loader/img?file=a.safetensors" },
      { name: "b.safetensors", image: null },
      { name: "sub/c.safetensors", image: null },
      { name: "d.safetensors", image: null },
        ],
      }),
    };
  }
  if (u.includes("/upload/image")) {
    return { ok: true, json: async () => ({ name: "up.png", subfolder: "", type: "input" }) };
  }
  if (u.includes("/degg_lora_loader/info")) {
    if (u.includes("d.safetensors")) {
      return infoResp({ name: "Site D", baseModel: "SDXL 1.0", images: [{ url: "https://img/site-d.png" }], permalink: "https://civitai.com/models/4" });
    }
    if (u.includes("b.safetensors")) {
      return infoResp({ name: "Site B", baseModel: "SDXL 1.0", images: [{ url: "https://img/site-b.png" }], permalink: "https://civitai.com/models/2" });
    }
    if (u.includes("sub%2Fc.safetensors")) return infoResp({ name: "Plain C", images: [] });
    if (u.includes("a.safetensors")) {
      return infoResp({ name: "054 - Fused Glass", baseModel: "Krea 2", images: [{ url: "https://img/a.png" }], permalink: "https://civitai.com/models/1" });
    }
    return infoResp({ name: "Plain", images: [] });
  }
  return { ok: true, json: async () => ({ loras: [] }) };
};

// ── заглушка DOM ──────────────────────────────────────────────────────────
class FakeEl {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.childNodes = this.children;
    this.parentNode = null;
    this.style = {};
    this.className = "";
    this.id = "";
    this.textContent = "";
    this.value = "";
    this.type = "";
    this.title = "";
    this.alt = "";
    this.step = "";
    this.min = "";
    this.max = "";
    this.disabled = false;
    this.clientWidth = 0;
    this.clientHeight = 0;
    this._listeners = Object.create(null);
  }
  get firstChild() {
    return this.children[0] || null;
  }
  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  append(...nodes) {
    nodes.forEach((n) => this.appendChild(n));
  }
  removeChild(child) {
    const at = this.children.indexOf(child);
    if (at >= 0) this.children.splice(at, 1);
    child.parentNode = null;
    return child;
  }
  replaceChildren(...nodes) {
    while (this.firstChild) this.removeChild(this.firstChild);
    nodes.forEach((n) => this.appendChild(n));
  }
  contains(el) {
    if (el === this) return true;
    return this.children.some((c) => c.contains && c.contains(el));
  }
  setAttribute(k, v) {
    this[k] = v;
  }
  getAttribute(k) {
    return this[k] === undefined ? null : this[k];
  }
  addEventListener(type, fn) {
    (this._listeners[type] = this._listeners[type] || []).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this._listeners[type] || [];
    const at = list.indexOf(fn);
    if (at >= 0) list.splice(at, 1);
  }
  listeners(type) {
    return this._listeners[type] || [];
  }
  dispatch(type, ev = {}) {
    const e = Object.assign(
      { type, button: 0, preventDefault() {}, stopPropagation() {}, target: this },
      ev
    );
    for (const fn of this.listeners(type)) fn(e);
    return e;
  }
  focus() {}
  blur() {}
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
}

class FakeImg extends FakeEl {
  constructor() {
    super("img");
    this._src = "";
  }
  set src(v) {
    this._src = String(v || "");
    if (/missing/.test(this._src)) {
      for (const fn of this.listeners("error")) fn({ type: "error" });
    }
  }
  get src() {
    return this._src;
  }
}

class FakeIO {
  constructor(cb, opts) {
    this.cb = cb;
    this.opts = opts || {};
    this.targets = [];
    IO_INSTANCES.push(this);
  }
  observe(el) {
    this.targets.push(el);
    IO_OBSERVED.push({ margin: this.opts.rootMargin, isBox: !!this.opts.root });
    if (this.cb) this.cb([{ target: el, isIntersecting: true }], this);
  }
  unobserve(el) {
    const at = this.targets.indexOf(el);
    if (at >= 0) this.targets.splice(at, 1);
  }
  disconnect() {
    this.targets = [];
  }
}

const documentStub = {
  createElement: (tag) => {
    const t = String(tag).toLowerCase();
    if (t === "img") return new FakeImg();
    return new FakeEl(tag);
  },
  createElementNS: (ns, tag) => new FakeEl(tag),
  head: new FakeEl("head"),
  body: new FakeEl("body"),
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  addEventListener: () => {
    documentAdds += 1;
  },
  removeEventListener: () => {},
};

const appInstance = {
  registerExtension: (e) => {
    capturedExt = e;
  },
  extensionManager: {
    setting: { get: (k) => (k === "Comfy.Locale" ? "en" : null) },
  },
};

const sandbox = {
  console,
  document: documentStub,
  Image: FakeImg,
  IntersectionObserver: FakeIO,
  FormData: class FakeFormData {
    constructor() {
      this.parts = [];
    }
    append(k, v, f) {
      this.parts.push([k, v, f]);
    }
  },
  comfyAPI: {
    app: { app: appInstance, registerExtension: appInstance.registerExtension },
    api: {
      api: {
        apiURL: (p) => `http://127.0.0.1:8188${p}`,
        fetchApi: () => Promise.resolve({ json: () => Promise.resolve({ ok: true }) }),
      },
    },
  },
  app: appInstance,
  setTimeout: (fn) => {
    rafQueue.push(fn);
    return rafQueue.length;
  },
  clearTimeout: () => {},
  requestAnimationFrame: (fn) => {
    rafQueue.push(fn);
    return rafQueue.length;
  },
  fetch: (url, opts) => {
    const u = String(url);
    FETCH_LOG.push(opts && opts.method ? opts.method + " " + u : u);
    return Promise.resolve(FETCH_RESULT(u));
  },
  addEventListener: () => {
    windowAdds += 1;
  },
  removeEventListener: () => {},
};
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(FILE, "utf8"), sandbox, { filename: "degg_lora_loader.js" });

const DL = sandbox.window.DeggLoraLoader;
check("расширение захвачено", !!capturedExt);
check("EXT_NAME верный", capturedExt && capturedExt.name === "Degg.LoraLoader");
check("window.DeggLoraLoader экспортирован", !!DL);
if (!DL) {
  console.log("\nSMOKE FAILED (нет экспорта)");
  process.exit(1);
}
if (typeof DL.CONTENT_MIN_H !== "number") {
  check("CONTENT_MIN_H экспортирован", false, String(DL.CONTENT_MIN_H));
  console.log("\nSMOKE FAILED");
  process.exit(1);
}
const { CONTENT_MIN_H, MARGIN } = DL;

const flush = async () => {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
};

// ── заглушка ноды (как её создаёт фронтенд по INPUT_TYPES) ────────────────
function makeNode() {
  const node = {
    size: [340, 300],
    inputs: [
      { name: "model", type: "MODEL", link: null },
      { name: "clip", type: "CLIP", link: null },
    ],
    widgets: [],
    properties: {},
    addDOMWidget(name, type, element, options) {
      const w = {
        type: type || "dom",
        name,
        element,
        options: { hideOnZoom: true, ...(options || {}) },
        serialize: true,
        y: 0,
        computedHeight: undefined,
        margin: 10,
      };
      this.widgets.push(w);
      return w;
    },
    addCustomWidget(w) {
      this.widgets.push(w);
      return w;
    },
    setSize(s) {
      this.size = s;
    },
    setDirtyCanvas() {},
    computeSize() {
      return [this.size[0], this.size[1] + 304];
    },
  };
  // виджет loras_data фронтенд создаёт из INPUT_TYPES ДО onNodeCreated
  node.widgets.push({
    name: "loras_data",
    type: "text",
    value: "[]",
    options: {},
    last_y: 26,
    computeSize: () => [0, 24],
    serialize: true,
  });
  return node;
}

/** Обход DOM-заглушки. */
function findEl(root, pred) {
  if (!root || !root.children) return null;
  for (const c of root.children) {
    if (pred(c)) return c;
    const deep = findEl(c, pred);
    if (deep) return deep;
  }
  return null;
}
const byClass = (root, cls) => findEl(root, (e) => String(e.className || "").split(/\s+/).includes(cls));
function findAll(root, pred, out = []) {
  if (!root || !root.children) return out;
  for (const c of root.children) {
    if (pred(c)) out.push(c);
    findAll(c, pred, out);
  }
  return out;
}
const json = (w) => {
  try {
    return JSON.parse(w.value);
  } catch (e) {
    return null;
  }
};

// ── beforeRegisterNodeDef: чужую ноду не трогаем ──────────────────────────
const protoHolder = {};
function NodeType() {}
NodeType.prototype = protoHolder;
capturedExt.beforeRegisterNodeDef(NodeType, { name: "NotDegg" });
check("чужая нода не получила перехват onNodeCreated", typeof protoHolder.onNodeCreated !== "function");

capturedExt.beforeRegisterNodeDef(NodeType, { name: "Degg_LoRa_Loader" });
check("наша нода получила onNodeCreated", typeof protoHolder.onNodeCreated === "function");
check("наша нода получила onConfigure", typeof protoHolder.onConfigure === "function");
check("наша нода получила onRemoved", typeof protoHolder.onRemoved === "function");
check("proto.computeSize НЕ перезаписан", protoHolder.computeSize === undefined);
check("proto.computeLayoutSize НЕ перезаписан", protoHolder.computeLayoutSize === undefined);

// ── создание ноды ─────────────────────────────────────────────────────────
const node = makeNode();
protoHolder.onNodeCreated.call(node);

const names = node.widgets.map((w) => w.name);
check(
  "порядок виджетов: loras_data → degg_lora_list",
  JSON.stringify(names) === JSON.stringify(["loras_data", "degg_lora_list"]),
  JSON.stringify(names)
);
check("id готовности выставлен", node._dlReady === true);
check("нода не вешает слушателей на window/document", windowAdds === 0 && documentAdds === 0,
  `window=${windowAdds} document=${documentAdds}`);

// ── скрытый виджет данных ─────────────────────────────────────────────────
const dataW = node.widgets.find((w) => w.name === "loras_data");
check("loras_data найден", !!dataW);
check("loras_data: w.hidden = true", dataW && dataW.hidden === true, String(dataW && dataW.hidden));
check("loras_data: options.hidden = true", !!(dataW && dataW.options && dataW.options.hidden === true));
check("loras_data: options.hideInPanel = true", !!(dataW && dataW.options && dataW.options.hideInPanel === true));
check("loras_data: сериализация НЕ отключена (иначе пропадёт персистентность)",
  !!dataW && dataW.serialize !== false && (!dataW.options || dataW.options.serialize !== false));
check("loras_data: значение по умолчанию []", dataW && dataW.value === "[]", String(dataW && dataW.value));

// ── DOM-виджет списка ─────────────────────────────────────────────────────
const listW = node.widgets.find((w) => w.name === "degg_lora_list");
check("degg_lora_list найден (addDOMWidget)", !!listW && listW.type === "degg_lora_list",
  JSON.stringify(node.widgets.map((w) => w.name)));
check("DOM-виджет: hideOnZoom = false (иначе превью исчезает при отдалении)",
  !!(listW && listW.options && listW.options.hideOnZoom === false),
  String(listW && listW.options && listW.options.hideOnZoom));
check("DOM-виджет: hideInPanel = true", !!(listW && listW.options && listW.options.hideInPanel === true));
check("DOM-виджет: getMinHeight есть", !!(listW && typeof listW.options.getMinHeight === "function"));
check("DOM-виджет: getMinHeight = CONTENT_MIN_H + MARGIN*2",
  !!(listW && listW.options.getMinHeight() === CONTENT_MIN_H + MARGIN * 2),
  listW ? String(listW.options.getMinHeight()) : "нет виджета");
check("DOM-виджет: НЕТ getHeight (иначе высота пинится)",
  !!(listW && listW.options && listW.options.getHeight === undefined));
check("DOM-виджет: НЕТ computeSize", !listW || listW.computeSize === undefined);
check("DOM-виджет: widget.serialize = false", !!(listW && listW.serialize === false));
check("DOM-виджет: options.serialize = false (prompt не должен его видеть)",
  !!(listW && listW.options && listW.options.serialize === false));

// ── корень пола ───────────────────────────────────────────────────────────
const root = listW && listW.element;
check("корень: height 100%", !!(root && root.style.height === "100%"), String(root && root.style.height));
check("корень: min-height = CONTENT_MIN_H",
  !!(root && root.style.minHeight === CONTENT_MIN_H + "px"), String(root && root.style.minHeight));
check("корень: display flex", !!(root && root.style.display === "flex"));
check("корень: flex-direction column", !!(root && root.style.flexDirection === "column"));
check("корень: overflow hidden", !!(root && root.style.overflow === "hidden"));

// ── legacy-режимы удалены (только Nodes 2.0) ──────────────────────────────
check("root: без legacy-режимных классов dl-mode-*",
  !!(root && !String(root.className).includes("dl-mode-")),
  root ? String(root.className) : "нет root");
check("root: без legacy-слушателей pointerenter",
  !!(root && root.listeners("pointerenter").length === 0),
  root ? String(root.listeners("pointerenter").length) : "нет root");
check("root: без legacy-слушателей pointerdown",
  !!(root && root.listeners("pointerdown").length === 0),
  root ? String(root.listeners("pointerdown").length) : "нет root");
check("applySwitchMode: удалён (только Nodes 2.0)", typeof DL.applySwitchMode === "undefined",
  String(typeof DL.applySwitchMode));
check("MIN_W экспортирован", typeof DL.MIN_W === "number", String(DL.MIN_W));
check("MIN_W: нода расширена до MIN_W при создании",
  typeof DL.MIN_W === "number" && node.size[0] >= DL.MIN_W, String(node.size[0]));

// ── header ────────────────────────────────────────────────────────────────
const head = byClass(root, "dl-head");
const addBtn = byClass(root, "dl-add");
const countEl = byClass(root, "dl-count");
const allWrap = byClass(root, "dl-allwrap");
const allSw = byClass(root, "dl-all");
const allLabel = byClass(root, "dl-alllabel");
const listEl = byClass(root, "dl-list");
check("header есть", !!head);
check("кнопка «+ LoRA» есть", !!addBtn);
check("счётчик есть", !!countEl);
check("обёртка toggle-all есть", !!allWrap);
check("переключатель toggle-all есть", !!allSw);
check("подпись toggle-all есть", !!allLabel);
check("toggle-all — это switch (role=switch)", !!(allSw && allSw.getAttribute("role") === "switch"));
check("toggle-all — синий при всех включённых", !!(allSw && allSw.getAttribute("aria-checked") === "true"));
check("список есть", !!listEl);
check("head: toggle-all первый ребёнок шапки",
  !!(head && head.children[0] && String(head.children[0].className).split(/\s+/).includes("dl-allwrap")),
  head ? JSON.stringify(head.children.map((e) => e.className)) : "нет head");
check("head: счётчик после toggle-all",
  !!(head && head.children[1] && String(head.children[1].className).split(/\s+/).includes("dl-count")),
  head ? JSON.stringify(head.children.map((e) => e.className)) : "нет head");
check("head: «+ LoRA» убран из шапки", !!head && !byClass(head, "dl-add"));
const foot = byClass(root, "dl-foot");
check("foot: футер под списком есть",
  !!(foot && root.children.indexOf(foot) > root.children.indexOf(listEl)),
  JSON.stringify(root.children.map((e) => e.className)));
check("foot: «+ LoRA» во футере", !!(foot && byClass(foot, "dl-add")));
check("EN: кнопка = «+ LoRA»", !!addBtn && addBtn.textContent === "+ LoRA",
  addBtn ? addBtn.textContent : "нет кнопки");
check("пустой список: подсказка", !!listEl && listEl.children.length === 1
  && byClass(listEl, "dl-empty") !== null, String(listEl && listEl.children.length));

// ── каталог лор: fetch /degg_lora_loader/loras ────────────────────────────
await flush();
check("каталог запрошен по /degg_lora_loader/loras",
  FETCH_LOG.some((u) => u.includes("/degg_lora_loader/loras")), JSON.stringify(FETCH_LOG));
check("каталог не дёргает /info (sha256 дорогой)",
  !FETCH_LOG.some((u) => u.includes("/degg_lora_loader/info")), JSON.stringify(FETCH_LOG));

// ── parseLoras (зеркалит Python parse_loras) ──────────────────────────────
check("parseLoras: валидный JSON", DL.parseLoras('[{"on":true,"lora":"a.safetensors"}]').length === 1);
check("parseLoras: битый JSON → []", DL.parseLoras("{oops").length === 0);
check("parseLoras: null → []", DL.parseLoras(null).length === 0);
check("parseLoras: без lora отбрасывается", DL.parseLoras('[{"on":true}]').length === 0);
check("parseLoras: объект-обёртка", DL.parseLoras('{"loras":[{"lora":"a"}]}').length === 1);
check("parseLoras: не-словарь отбрасывается", DL.parseLoras('["junk"]').length === 0);
check("parseLoras: поле preview сохраняется", (() => {
  const list = DL.parseLoras('[{"lora":"x.safetensors","preview":"https://p/1.png"}]');
  return list.length === 1 && list[0].preview === "https://p/1.png";
})(), (() => {
  const list = DL.parseLoras('[{"lora":"x.safetensors","preview":"https://p/1.png"}]');
  return JSON.stringify(list);
})());

// ── onConfigure: widgets_values_named ─────────────────────────────────────
const jsonStr = JSON.stringify([
  { on: true, lora: "a.safetensors", strength: 0.7, strength_clip: 0.7 },
  { on: false, lora: "sub/c.safetensors", strength: 0.4, strength_clip: 0.4 },
]);
protoHolder.onConfigure.call(node, { widgets_values_named: { loras_data: jsonStr } });
check("onConfigure: строки из widgets_values_named", listEl.children.length === 2,
  String(listEl.children.length));
check("onConfigure: loras_data.value совпадает", dataW.value === jsonStr, String(dataW.value));

const rows = listEl.children;
const row0 = rows[0];
check("строка: className dl-row", !!row0 && String(row0.className).includes("dl-row"));
check("строка: toggle есть", !!byClass(row0, "dl-sw"));
check("строка: превью есть", !!byClass(row0, "dl-thumb"));
check("строка: имя файла в dl-ln (sync fallback)", !!byClass(row0, "dl-ln") && byClass(row0, "dl-ln").textContent === "a.safetensors",
  (() => { const ln = byClass(row0, "dl-ln"); return ln ? JSON.stringify(ln.textContent) : "нет dl-ln"; })());
check("строка: strength = 0.7", !!byClass(row0, "dl-num") && byClass(row0, "dl-num").value === "0.7",
  String(byClass(row0, "dl-num") && byClass(row0, "dl-num").value));
check("строка: кнопка удаления есть", !!byClass(row0, "dl-del"));
check("строка: корзина — SVG-иконка", (() => {
  const del = byClass(row0, "dl-del");
  return !!del && del.children.some((c) => c.tagName === "SVG");
})());
check("строка: корзина без текста ✕", (() => {
  const del = byClass(row0, "dl-del");
  return !!del && del.textContent === "";
})());
check("строка: порядок детей toggle → thumb → name → num → del", (() => {
  const c = row0.children.map((e) => e.className);
  const idx = (sub) => c.findIndex((x) => String(x).includes(sub));
  return idx("dl-sw") < idx("dl-thumb") && idx("dl-thumb") < idx("dl-name")
    && idx("dl-name") < idx("dl-num") && idx("dl-num") < idx("dl-del");
})(), JSON.stringify(row0.children.map((e) => e.className)));
check("выключенная строка помечена dl-off", String(rows[1].className).includes("dl-off"));
check("включённая строка не dl-off", !String(rows[0].className).includes("dl-off"));
check("счётчик: 1/2", countEl.textContent === "1/2", countEl.textContent);

// превью: единый резолвер attachThumb (T1)
await flush();
const thumbImg = byClass(row0, "dl-img");
check("превью: локальная картинка из каталога", !!thumbImg && thumbImg.src.includes("/degg_lora_loader/img"),
  thumbImg ? thumbImg.src : "нет img");
const row1Thumb = byClass(rows[1], "dl-thumb");
check("превью: без картинок → глиф, не img с пустым src", !!row1Thumb && !!byClass(row1Thumb, "dl-glyph")
  && !byClass(row1Thumb, "dl-img"),
  row1Thumb ? JSON.stringify(row1Thumb.children.map((e) => e.className)) : "нет thumb");
check("превью: у строк нет img с пустым src",
  findAll(root, (e) => e.tagName === "IMG" && !e.src).length === 0,
  JSON.stringify(findAll(root, (e) => e.tagName === "IMG").map((e) => e.src)));
check("превью: ленивая загрузка (loading=lazy)",
  findAll(root, (e) => e.tagName === "IMG").every((e) => e.loading === "lazy"),
  JSON.stringify(findAll(root, (e) => e.tagName === "IMG").map((e) => e.loading)));
const sw0 = byClass(row0, "dl-sw");
check("toggle: dl-knob внутри переключателя", !!(sw0 && byClass(sw0, "dl-knob")));
check("toggle: переключатель остаётся первым ребёнком строки", row0.children[0] === sw0,
  JSON.stringify(row0.children.map((e) => e.className)));
check("img: error-обработчик прячет битую картинку", (() => {
  thumbImg.dispatch("error");
  return thumbImg.style.display === "none";
})(), String(thumbImg.style.display));

// ── имя строки: серый dl-bm + белый dl-ln из /info (T7) ──────────────────
check("строка: имя разложено на dl-bm + dl-ln", (() => {
  const nb = byClass(row0, "dl-name");
  return !!nb && !!byClass(nb, "dl-bm") && !!byClass(nb, "dl-ln");
})(), JSON.stringify(byClass(row0, "dl-name") && byClass(row0, "dl-name").children.map((e) => e.className)));
check("строка: белое имя = имя Civitai (info.name)", (() => {
  const ln = byClass(row0, "dl-ln");
  return !!ln && ln.textContent === "054 - Fused Glass";
})(), (() => { const ln = byClass(row0, "dl-ln"); return ln ? ln.textContent : "нет dl-ln"; })());
check("строка: серый baseModel без префикса", (() => {
  const bm = byClass(row0, "dl-bm");
  return !!bm && bm.textContent === "Krea 2" && !/^(base|модель)/i.test(bm.textContent);
})(), (() => { const bm = byClass(row0, "dl-bm"); return bm ? JSON.stringify(bm.textContent) : "нет dl-bm"; })());
check("строка: title = полный путь lora", row0.title === "a.safetensors", String(row0.title));
check("строка: sub/c — имя из info (Plain C), пустой baseModel", (() => {
  const nb1 = byClass(rows[1], "dl-name");
  const ln1 = nb1 && byClass(nb1, "dl-ln");
  const bm1 = nb1 && byClass(nb1, "dl-bm");
  return !!ln1 && ln1.textContent === "Plain C" && !!bm1 && bm1.textContent === "";
})(), (() => {
  const nb1 = byClass(rows[1], "dl-name");
  return nb1 ? JSON.stringify(nb1.children.map((e) => [e.className, e.textContent])) : "нет";
})());

// ── T2: имя → инфо, превью → пикер превью, upload/reset ──────────────────
check("T2: экспорты openPreviewPicker/uploadPreview есть",
  typeof DL.openPreviewPicker === "function" && typeof DL.uploadPreview === "function",
  JSON.stringify([typeof DL.openPreviewPicker, typeof DL.uploadPreview]));
byClass(row0, "dl-ln").dispatch("click");
await flush();
check("T2: клик по имени открывает инфо", (() => {
  const m = documentStub.body.children[documentStub.body.children.length - 1];
  return documentStub.body.children.length > 0 && !!m && !!byClass(m, "dl-info");
})(), String(documentStub.body.children.length));
check("T2: инфо по имени показывает имя из /info",
  !!findEl(documentStub.body, (e) => e.textContent === "054 - Fused Glass"));
DL.closeModal();
byClass(row0, "dl-thumb").dispatch("click");
await flush();
const ppModal = documentStub.body.children[documentStub.body.children.length - 1];
check("T2: клик по превью открывает пикер, а не инфо",
  !!ppModal && !!byClass(ppModal, "dl-ppick") && !byClass(ppModal, "dl-info"),
  ppModal ? String(ppModal.children.map((e) => e.className)) : "нет модалки");
check("T2: карточка пикера — полный путь в шапке", (() => {
  const p = ppModal && byClass(ppModal, "dl-path");
  return !!p && p.textContent === "a.safetensors" && p.title === "a.safetensors";
})());
await flush();
check("T2: карточка пикера — ссылка CivitAI (permalink)", (() => {
  const link = ppModal && findEl(ppModal, (e) => e.tagName === "A" && String(e.className).includes("dl-link"));
  return !!link && link.href === "https://civitai.com/models/1";
})(), (() => { const link = ppModal && findEl(ppModal, (e) => e.tagName === "A"); return link ? String(link.href) : "нет ссылки"; })());
check("T2: локальный кандидат превью", !!ppModal
  && findAll(ppModal, (e) => e.tagName === "IMG" && String(e.src).includes("/degg_lora_loader/img?file=a.safetensors")).length === 1,
  JSON.stringify(findAll(ppModal, (e) => e.tagName === "IMG").map((e) => e.src)));
check("T2: сайт-кандидат из images[0]", !!ppModal
  && findAll(ppModal, (e) => e.tagName === "IMG" && e.src === "https://img/a.png").length === 1,
  JSON.stringify(findAll(ppModal, (e) => e.tagName === "IMG").map((e) => e.src)));
check("T2: кнопка загрузки своего превью", !!ppModal && !!findEl(ppModal, (e) => String(e.className).includes("dl-pup")));
check("T2: кнопка сброса превью", !!ppModal && !!findEl(ppModal, (e) => String(e.className).includes("dl-preset")));
const siteCand = ppModal && findAll(ppModal, (e) => String(e.className).includes("dl-pcand")).find((c) =>
  findAll(c, (im) => im.tagName === "IMG" && im.src === "https://img/a.png").length === 1);
check("T2: обёртка сайта-кандидата .dl-pcand", !!siteCand);
if (siteCand) {
  siteCand.dispatch("click");
  await flush();
}
check("T2: выбор кандидата → preview в loras_data", (() => {
  const d = json(dataW);
  return !!d && d[0].preview === "https://img/a.png";
})(), String(dataW.value));
check("T2: выбор кандидата → превью строки обновилось", (() => {
  const im = byClass(listEl.children[0], "dl-img");
  return !!im && im.src === "https://img/a.png";
})(), (() => { const im = byClass(listEl.children[0], "dl-img"); return im ? im.src : "нет img"; })());
check("T2: выбор кандидата → модалка закрыта", documentStub.body.children.length === 0,
  String(documentStub.body.children.length));

byClass(listEl.children[0], "dl-thumb").dispatch("click");
await flush();
if (typeof DL.uploadPreview === "function") {
  await DL.uploadPreview(node, 0, { name: "custom.png" });
}
check("T2: upload шлёт POST /upload/image",
  FETCH_LOG.some((u) => String(u).includes("POST") && String(u).includes("/upload/image")),
  JSON.stringify(FETCH_LOG.filter((u) => String(u).includes("upload"))));
check("T2: upload → preview = /view-URL", (() => {
  const d = json(dataW);
  return !!d && d[0].preview === "/view?filename=up.png&subfolder=&type=input";
})(), String(dataW.value));
check("T2: upload → превью строки обновилось", (() => {
  const im = byClass(listEl.children[0], "dl-img");
  return !!im && im.src === "/view?filename=up.png&subfolder=&type=input";
})(), (() => { const im = byClass(listEl.children[0], "dl-img"); return im ? im.src : "нет img"; })());
DL.closeModal();

byClass(listEl.children[0], "dl-thumb").dispatch("click");
await flush();
const presetBtn = findEl(documentStub.body, (e) => String(e.className).includes("dl-preset"));
check("T2: кнопка сброса найдена в открытом пикере", !!presetBtn);
if (presetBtn) {
  presetBtn.dispatch("click");
  await flush();
}
check("T2: сброс очищает preview", (() => {
  const d = json(dataW);
  return !!d && !d[0].preview;
})(), String(dataW.value));
check("T2: сброс → превью снова локальное", (() => {
  const im = byClass(listEl.children[0], "dl-img");
  return !!im && String(im.src).includes("/degg_lora_loader/img?file=a.safetensors");
})(), (() => { const im = byClass(listEl.children[0], "dl-img"); return im ? im.src : "нет img"; })());
check("T2: сброс закрывает модалку", documentStub.body.children.length === 0,
  String(documentStub.body.children.length));

// ── onConfigure: позиционный фолбэк ───────────────────────────────────────
const node2 = makeNode();
protoHolder.onNodeCreated.call(node2);
node2.size = [200, 300];
protoHolder.onConfigure.call(node2, { widgets_values: ['[{"on":true,"lora":"b.safetensors","strength":0.5}]'] });
check("onConfigure: узкая сохранённая нода расширена до MIN_W",
  typeof DL.MIN_W === "number" && node2.size[0] >= DL.MIN_W, String(node2.size[0]));
const list2 = byClass(node2.widgets.find((w) => w.name === "degg_lora_list").element, "dl-list");
check("onConfigure: позиционный widgets_values читается", list2.children.length === 1,
  String(list2.children.length));
check("onConfigure: значение записано в loras_data", (() => {
  const d = node2.widgets.find((w) => w.name === "loras_data");
  return json(d) && json(d).length === 1 && json(d)[0].lora === "b.safetensors";
})(), String(node2.widgets.find((w) => w.name === "loras_data").value));

// ── add / toggle / strength / remove ──────────────────────────────────────
DL.addLora(node, "b.safetensors");
check("addLora: 3 строки", listEl.children.length === 3, String(listEl.children.length));
check("addLora: записан в loras_data", json(dataW).length === 3, String(dataW.value));
check("addLora: по умолчанию on=true", json(dataW)[2].on === true);
check("addLora: дубликат не добавляется", (() => {
  DL.addLora(node, "b.safetensors");
  const ok = json(dataW).length === 3;
  DL.removeAt(node, 2);
  return ok;
})(), String(dataW.value));

const before = json(dataW)[0].on;
DL.toggleAt(node, 0);
check("toggleAt: on переключился", json(dataW)[0].on === !before);
check("toggleAt: строка получила dl-off", String(listEl.children[0].className).includes("dl-off"));
check("toggleAt: счётчик 0/2", countEl.textContent === "0/2", countEl.textContent);
check("toggleAt: aria-checked", listEl.children[0].children[0]["aria-checked"] === "false");
check("toggleAt: мастер-переключатель выключен (не все вкл)",
  allSw.getAttribute("aria-checked") === "false", allSw.getAttribute("aria-checked"));
DL.toggleAt(node, 0);
check("toggleAt: вернулся", json(dataW)[0].on === before && countEl.textContent === "1/2",
  countEl.textContent);
DL.toggleAt(node, 1);
check("toggleAt: мастер-переключатель включён (все вкл)",
  allSw.getAttribute("aria-checked") === "true", allSw.getAttribute("aria-checked"));

DL.setStrength(node, 1, "0.25");
check("setStrength: значение в loras_data", json(dataW)[1].strength === 0.25, String(json(dataW)[1].strength));
check("setStrength: input.value обновлён", byClass(listEl.children[1], "dl-num").value === "0.25");
DL.setStrength(node, 1, "abc");
check("setStrength: нечисловое → 1.0", json(dataW)[1].strength === 1);
DL.setStrength(node, 1, "250");
check("setStrength: кламп в 100", json(dataW)[1].strength === 100);
DL.setStrength(node, 1, "-250");
check("setStrength: кламп в -100", json(dataW)[1].strength === -100);

DL.toggleAll(node);
check("toggleAll: все выключились", json(dataW).every((l) => l.on === false)
  && countEl.textContent === "0/2", countEl.textContent);
check("toggleAll: переключатель выключен", allSw.getAttribute("aria-checked") === "false",
  allSw.getAttribute("aria-checked"));
check("toggleAll: строки помечены dl-off", rows.every((r) => String(r.className).includes("dl-off")));
DL.toggleAll(node);
check("toggleAll: включились обратно", json(dataW).every((l) => l.on === true)
  && countEl.textContent === "2/2", countEl.textContent);
check("toggleAll: переключатель включён", allSw.getAttribute("aria-checked") === "true",
  allSw.getAttribute("aria-checked"));
allSw.dispatch("click");
check("клик по мастер-переключателю: все выключились", json(dataW).every((l) => l.on === false));
check("клик по мастер-переключателю: переключатель выключен",
  allSw.getAttribute("aria-checked") === "false", allSw.getAttribute("aria-checked"));
allSw.dispatch("click");
check("клик по мастер-переключателю: все включились", json(dataW).every((l) => l.on === true));
check("клик по мастер-переключателю: переключатель включён",
  allSw.getAttribute("aria-checked") === "true", allSw.getAttribute("aria-checked"));

DL.removeAt(node, 1);
check("removeAt: строк удалена", listEl.children.length === 1, String(listEl.children.length));
check("removeAt: loras_data усечён", json(dataW).length === 1, String(dataW.value));
DL.removeAt(node, 0);
check("removeAt: пустой список → подсказка", listEl.children.length === 1
  && byClass(listEl, "dl-empty") !== null, String(listEl.children.length));
check("removeAt: пустой счётчик", countEl.textContent === "", countEl.textContent);

// toggle-all при пустом списке не роняет ноду
let taOk = true;
try {
  DL.toggleAll(node);
} catch (e) {
  taOk = false;
}
check("toggleAll на пустом списке не бросает", taOk);

// ── локализация (здесь список ещё пуст — по подсказке проверяется RU/EN) ───
DL.setLocaleOverride("ru");
DL.refreshLabels(node);
check("RU: кнопка = «+ Лора»", addBtn.textContent === "+ Лора", addBtn.textContent);
check("RU: пустой список по-русски", byClass(listEl, "dl-empty").textContent.includes("Нет"),
  byClass(listEl, "dl-empty").textContent);
DL.setLocaleOverride("en");
DL.refreshLabels(node);
check("EN: кнопка = «+ LoRA»", addBtn.textContent === "+ LoRA", addBtn.textContent);
check("EN: пустой список по-английски", byClass(listEl, "dl-empty").textContent === "No LoRAs — press + LoRA",
  byClass(listEl, "dl-empty").textContent);
check("locale: сброс override → EN", DL.setLocaleOverride(null) === null && DL.isRu() === false);
check("локализация: EN-словарь без кириллицы", Object.values(DL.LOCALES.en)
  .every((v) => !/[\u0400-\u04FF]/.test(v)));
check("локализация: RU-словарь с кириллицей", Object.values(DL.LOCALES.ru)
  .every((v) => /[\u0400-\u04FF]/.test(v)));
check("локализация: ключи RU и EN совпадают",
  JSON.stringify(Object.keys(DL.LOCALES.ru).sort()) === JSON.stringify(Object.keys(DL.LOCALES.en).sort()));
check("локализация: нет комбо-входов → values не подменяются", DL.comboValues === undefined);

// ── негативный кэш /info (T1) ─────────────────────────────────────────────
const subFetchCount = () => FETCH_LOG.filter((u) => String(u).includes("sub%2Fc.safetensors")).length;
DL.addLora(node, "sub/c.safetensors");
await flush();
check("негативный кэш: /info для лоры без картинок запрошен 1 раз", subFetchCount() === 1,
  `fetches=${subFetchCount()} log=${JSON.stringify(FETCH_LOG.filter((u) => String(u).includes("sub")))}`);
const subRow = listEl.children[0];
check("негативный кэш: строка получила глиф", !!(subRow && byClass(subRow, "dl-glyph")),
  subRow ? JSON.stringify(subRow.children.map((e) => e.className)) : "нет строки");
DL.removeAt(node, 0);
await flush();
DL.addLora(node, "sub/c.safetensors");
await flush();
check("негативный кэш: повторный рендер без повторного /info", subFetchCount() === 1,
  `fetches=${subFetchCount()}`);
DL.removeAt(node, 0);
await flush();

// ── модалка выбора лоры ───────────────────────────────────────────────────
DL.addLora(node, "a.safetensors");
DL.addLora(node, "b.safetensors");
await flush();
const bRow = listEl.children[1];
const bImg = bRow ? byClass(bRow, "dl-img") : null;
check("превью: без локалки → сайт-картинка из /info (images[0])",
  !!bImg && bImg.src === "https://img/site-b.png", bImg ? bImg.src : "нет img");
DL.openPicker(node);
const modal = documentStub.body.children[documentStub.body.children.length - 1];
check("openPicker: модалка в document.body", !!modal && String(modal.className).includes("dl-modal"));
check("openPicker: есть список лор из каталога", findAll(modal, (e) => String(e.className).includes("dl-pitem")).length >= 2,
  String(findAll(modal, (e) => String(e.className).includes("dl-pitem")).length));
check("openPicker: уже добавленная помечена", (() => {
  const items = findAll(modal, (e) => String(e.className).includes("dl-pitem"));
  const a = items.find((e) => String(e.className).includes("dl-used"));
  return !!a;
})());
check("openPicker: глобальных слушателей нет", windowAdds === 0 && documentAdds === 0,
  `window=${windowAdds} document=${documentAdds}`);
await flush();
const itemsNow = findAll(modal, (e) => String(e.className).includes("dl-pitem"));
check("picker: хост превью — контейнер .dl-pt", !!itemsNow.find((e) => !!byClass(e, "dl-pt")),
  JSON.stringify(itemsNow.map((e) => e.children.map((c) => c.className))));
const itemB = itemsNow.find((e) => {
  const lb = byClass(e, "dl-plabel");
  return lb && lb.textContent === "b.safetensors";
});
const bPImg = itemB ? byClass(itemB, "dl-pthumb") : null;
check("picker: сайт-картинка b из /info (images[0])", !!bPImg && bPImg.src === "https://img/site-b.png",
  bPImg ? bPImg.src : "нет img");
check("picker: нет img с пустым src", findAll(modal, (e) => e.tagName === "IMG" && !e.src).length === 0,
  JSON.stringify(findAll(modal, (e) => e.tagName === "IMG").map((e) => e.src)));
check("picker: ленивая загрузка (loading=lazy)",
  findAll(modal, (e) => e.tagName === "IMG").every((e) => e.loading === "lazy"));
check("picker: глиф для lora без картинок", (() => {
  const itemC = itemsNow.find((e) => {
    const lb = byClass(e, "dl-plabel");
    return lb && lb.textContent === "sub/c.safetensors";
  });
  return !!itemC && !!byClass(itemC, "dl-glyph");
})());
check("picker: IntersectionObserver создан над скролл-боксом",
  IO_INSTANCES.length >= 1
  && IO_INSTANCES[0].opts.rootMargin === "200px"
  && !!IO_INSTANCES[0].opts.root
  && String(IO_INSTANCES[0].opts.root.className).includes("dl-picker"),
  JSON.stringify(IO_INSTANCES.map((i) => ({ margin: i.opts.rootMargin, root: i.opts.root && i.opts.root.className }))));
check("picker: видимый элемент подписан в observer (rootMargin 200px)",
  IO_OBSERVED.some((o) => o.margin === "200px" && o.isBox),
  JSON.stringify(IO_OBSERVED));
const itemD = itemsNow.find((e) => {
  const lb = byClass(e, "dl-plabel");
  return lb && lb.textContent === "d.safetensors";
});
const dPImg = itemD ? byClass(itemD, "dl-pthumb") : null;
check("picker: некэшированная lora получила сайт-картинку после наблюдения",
  !!dPImg && dPImg.src === "https://img/site-d.png", dPImg ? dPImg.src : "нет img");
DL.closeModal();
check("closeModal: модалка убрана", documentStub.body.children.length === 0,
  String(documentStub.body.children.length));

// ── preview-приоритет: entry.preview выше локальной/сайтовой (T1) ─────────
const node3 = makeNode();
protoHolder.onNodeCreated.call(node3);
protoHolder.onConfigure.call(node3, {
  widgets_values: [JSON.stringify([{ on: true, lora: "pv.safetensors", strength: 1, strength_clip: 1, preview: "https://custom/p1.png" }])],
});
await flush();
const list3 = byClass(node3.widgets.find((w) => w.name === "degg_lora_list").element, "dl-list");
const img3 = list3 && list3.children[0] ? byClass(list3.children[0], "dl-img") : null;
check("preview: собственное превью побеждает (src = preview)", !!img3 && img3.src === "https://custom/p1.png",
  img3 ? img3.src : "нет img");
check("preview: /info для строки pv — один запрос (превью не через /info)",
  FETCH_LOG.filter((u) => String(u).includes("pv.safetensors")).length === 1,
  JSON.stringify(FETCH_LOG.filter((u) => String(u).includes("pv"))));
protoHolder.onRemoved.call(node3);

// ── модалка информации (клик по превью) ───────────────────────────────────
FETCH_RESULT = (u) => (u.includes("/degg_lora_loader/info")
  ? {
      ok: true,
      json: async () => ({
        ok: true,
        name: "Cool LoRA",
        baseModel: "SDXL 1.0",
        trigger: ["cool", "style"],
        description: "<p>Hello <b>world</b></p>",
        images: [{ url: "https://img/1.png" }],
        permalink: "https://civitai.com/models/1",
        localImage: null,
      }),
    }
  : { ok: true, json: async () => ({ loras: [] }) });

await DL.openInfo(node, "openme.safetensors");
const infoModal = documentStub.body.children[documentStub.body.children.length - 1];
check("openInfo: модалка открылась", !!infoModal && String(infoModal.className).includes("dl-modal"));
check("openInfo: имя модели показано", !!findEl(infoModal, (e) => e.textContent === "Cool LoRA"));
check("openInfo: описание без HTML-тегов", !!findEl(infoModal, (e) => e.textContent === "Hello world"));
check("openInfo: базовая модель", !!findEl(infoModal, (e) => e.textContent === "SDXL 1.0"));
check("openInfo: триггеры показаны", !!findEl(infoModal, (e) => String(e.textContent).includes("cool")));
check("openInfo: ссылка на CivitAI", (() => {
  const a = findEl(infoModal, (e) => e.tagName === "A");
  return !!a && a.href === "https://civitai.com/models/1";
})());
check("openInfo: GET /degg_lora_loader/info?file=...", FETCH_LOG.some((u) => u.includes("/degg_lora_loader/info?file=") && u.includes("openme.safetensors")),
  JSON.stringify(FETCH_LOG.filter((u) => String(u).includes("/info"))));
check("openInfo: закрытие по кнопке", (() => {
  const btn = findEl(infoModal, (e) => String(e.className).includes("dl-x"));
  if (!btn) return false;
  btn.dispatch("click");
  return documentStub.body.children.length === 0;
})());

// ── onRemoved ─────────────────────────────────────────────────────────────
DL.openPicker(node);
protoHolder.onRemoved.call(node);
check("onRemoved: модалка закрыта", documentStub.body.children.length === 0,
  String(documentStub.body.children.length));
check("onRemoved: состояние убрано", node._dl === undefined || node._dl === null,
  JSON.stringify(node._dl && Object.keys(node._dl)));

rafQueue = [];
await flush();
rafQueue = [];
check("rAF отработал (нет зависших колбэков)", rafQueue.length === 0, String(rafQueue.length));
check("глобальных слушателей нет (финал)", windowAdds === 0 && documentAdds === 0,
  `window=${windowAdds} document=${documentAdds}`);

console.log("");
console.log(`ok: ${oks.length}   FAIL: ${errors.length}`);
if (errors.length) {
  errors.forEach((e) => console.log("  - " + e));
  console.log("SMOKE FAILED");
  process.exit(1);
}
console.log("SMOKE OK");
