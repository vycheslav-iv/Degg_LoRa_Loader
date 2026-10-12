// Статический аудит Degg_LoRa_Loader — без ComfyUI и браузера.
// Проверяет согласованность Python ↔ JS ↔ locales ↔ check.json и запрещённые
// приёмы из AGENTS.md (§4.1 «Совместимость с Nodes 2.0», §5 «Типичные проблемы»).
//
// Запуск:  cd Degg_LoRa_Loader && node tests/_audit_degg_lora_loader.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));

const errors = [];
const oks = [];
const check = (label, cond, extra = "") => {
  (cond ? oks : errors).push(label);
  console.log(`  ${cond ? "ok  " : "FAIL"} ${label}${!cond && extra ? "  [" + extra + "]" : ""}`);
};
const has = (s, re, label) => check(label, re.test(s), String(re));
const read = (rel) => {
  const p = path.join(ROOT, rel);
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
};
// Запрещённые приёмы ищем ТОЛЬКО в коде: комментарии упоминают их как
// запрещённые, поиск по сырому тексту давал бы ложный FAIL.
const stripComments = (s) =>
  s
    .split("\n")
    .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
    .join("\n");

// ── 1. Состав проекта ─────────────────────────────────────────────────────
const PY = read("degg_lora_loader.py");
const JS = read("web/js/degg_lora_loader.js");
const INIT = read("__init__.py");
const SPEC = read("SPECIFICATION.md");
const CHECKJ = read("check.json");

const REQUIRED_TESTS = [
  "tests/_test_degg_lora_loader.py",
  "tests/_smoke_degg_lora_loader.mjs",
  "tests/_audit_degg_lora_loader.mjs",
];

check("degg_lora_loader.py существует", !!PY);
check("web/js/degg_lora_loader.js существует", !!JS);
check("__init__.py существует", !!INIT);
check("SPECIFICATION.md существует", !!SPEC);
check("check.json существует", !!CHECKJ);
for (const t of REQUIRED_TESTS) check(`${t} существует`, !!read(t));
for (const l of ["locales/en/nodeDefs.json", "locales/ru/nodeDefs.json"]) {
  check(`${l} существует`, !!read(l));
}

if (INIT) {
  has(INIT, /WEB_DIRECTORY\s*=\s*"web"/, "__init__: WEB_DIRECTORY = 'web'");
  has(INIT, /from \.degg_lora_loader import (NODE_CLASS_MAPPINGS|NODE_DISPLAY_NAME_MAPPINGS)/,
    "__init__: импорт маппингов из degg_lora_loader");
  check("__init__: нет лишнего кода",
    INIT.trim().split("\n").filter((l) => l.trim() && !l.startsWith("#")).length <= 8);
}

// ── 2. Python ─────────────────────────────────────────────────────────────
let pyInputs = [];
let pyOptional = [];
if (PY) {
  has(PY, /^class DeggLoraLoader:/m, "python: class DeggLoraLoader");
  has(PY, /RETURN_TYPES\s*=\s*\("MODEL",\s*"CLIP"\)/, "python: RETURN_TYPES = (MODEL, CLIP)");
  has(PY, /RETURN_NAMES\s*=\s*\("model",\s*"clip"\)/, "python: RETURN_NAMES = (model, clip)");
  has(PY, /FUNCTION\s*=\s*"load_loras"/, "python: FUNCTION = load_loras");
  has(PY, /CATEGORY\s*=\s*"My_custom_nodes\/LoRA"/, "python: CATEGORY = My_custom_nodes/LoRA");
  check("python: OUTPUT_NODE не установлен (noda — не output)", !/OUTPUT_NODE\s*=\s*True/.test(PY));

  check("python: маппинги через NODE_KEY", /NODE_CLASS_MAPPINGS\s*=\s*\{\s*NODE_KEY\s*:/.test(PY));
  has(PY, /NODE_KEY\s*=\s*"Degg_LoRa_Loader"/, "python: NODE_KEY = Degg_LoRa_Loader");
  has(PY, /NODE_DISPLAY_NAME_MAPPINGS[\s\S]{0,80}?"Degg LoRa Loader"/,
    "python: отображаемое имя «Degg LoRa Loader»");

  const topHeavy = PY.match(/^(?:import|from)\s+(folder_paths|server|aiohttp|nodes|comfy)\b/gm) || [];
  check("python: нет тяжёлых импортов на уровне модуля", topHeavy.length === 0, JSON.stringify(topHeavy));
  has(PY, /^\s+import folder_paths$/m, "python: folder_paths импортируется лениво");
  has(PY, /^\s+from nodes import LoraLoader$/m, "python: nodes.LoraLoader импортируется лениво");
  has(PY, /def register_routes\(\)/, "python: register_routes() есть");
  has(PY, /^\s+from aiohttp import web$/m, "python: aiohttp импортируется внутри register_routes");
  has(PY, /^register_routes\(\)$/m, "python: register_routes() вызывается при импорте");
  check("python: роуты защищены try/except (импорт жив без ComfyUI)",
    /def register_routes\(\):[\s\S]{0,400}?try:/.test(PY));

  // Обязательные функции
  for (const fn of ["parse_loras", "safe_lora_name", "apply_loras", "sibling_image_path",
    "get_lora_info", "_normalize_civitai", "_http_get_json", "_sha256"]) {
    has(PY, new RegExp(`def ${fn}\\(`), `python: def ${fn}()`);
  }

  // Сборка мусора (этап 2)
  for (const fn of ["sweep_cache", "ttl_sweep", "sweep_input_previews", "drop_thumb_cache"]) {
    has(PY, new RegExp(`def ${fn}\\(`), `python: def ${fn}()`);
  }
  check("python: предохранитель sweep — пустой листинг лор не чистит",
    /if not active_names:\s*\n\s*return 0/.test(PY));
  (() => {
    const pyPrefix = (PY.match(/PREVIEW_NAME_PREFIX = "([^"]+)"/) || [])[1];
    const jsPrefix = (JS ? JS.match(/PREVIEW_NAME_PREFIX = "([^"]+)"/) : []) || [];
    check("js и python: один префикс кастомного превью (иначе sweep не найдёт файлы)",
      !!pyPrefix && pyPrefix === jsPrefix[1], `js=${jsPrefix[1]} py=${pyPrefix}`);
  })();

  // Кэш CivitAI
  has(PY, /degg_lora_cache/, "python: кэш-папка degg_lora_cache");
  has(PY, /civitai\.com\/api\/v1\/model-versions\/by-hash\//, "python: CivitAI by-hash endpoint");
  has(PY, /get_user_directory\(\)/, "python: кэш в user/default (get_user_directory)");
  check("python: кэш пишется ДО вычисления sha256 (иначе chicken-and-egg)",
    /def get_lora_info\([\s\S]*?cache_key[\s\S]*?_sha256/s.test(PY));

  // INPUT_TYPES
  const block = (PY.match(/def INPUT_TYPES[\s\S]*?RETURN_TYPES/) || [])[0] || "";
  const reqPart = (block.match(/"required":\s*\{([\s\S]*?)\n\s*\},?\n\s*(?:"optional"|"hidden")/) || [])[1] || "";
  const optPart = (block.match(/"optional":\s*\{([\s\S]*?)\n\s*\},?\n\s*(?:"hidden"|\})/) || [])[1] || "";
  pyInputs = [...reqPart.matchAll(/"(\w+)":\s*\(/g)].map((m) => m[1]);
  pyOptional = [...optPart.matchAll(/"(\w+)":\s*\(/g)].map((m) => m[1]);

  check("python: loras_data обязателен и STRING", /"loras_data":\s*\("STRING"/.test(PY));
  has(PY, /"default":\s*"\[\]"/, "python: loras_data default = '[]'");
  check("python: model/clip опциональные сокеты",
    pyOptional.includes("model") && pyOptional.includes("clip"), JSON.stringify(pyOptional));
  check("python: порядок model → clip → loras_data",
    JSON.stringify([...pyOptional, ...pyInputs]) === JSON.stringify(["model", "clip", "loras_data"]),
    JSON.stringify([...pyOptional, ...pyInputs]));
  check("python: нет combo-входов (значения протокольны)", !/\(\s*\[[^\]]+","/.test(block));

  // Ровно 4 роута
  const pyRoutes = [...new Set([...PY.matchAll(/@routes\.(?:get|post)\("([^"]+)"\)/g)].map((m) => m[1]))].sort();
  check("python: ровно 4 роута", pyRoutes.length === 4, JSON.stringify(pyRoutes));
  check("python: роуты = img/info/loras/thumb",
    JSON.stringify(pyRoutes) === JSON.stringify([
      "/degg_lora_loader/img", "/degg_lora_loader/info",
      "/degg_lora_loader/loras", "/degg_lora_loader/thumb",
    ]), JSON.stringify(pyRoutes));
  check("python: блокирующая работа уходит в поток (asyncio.to_thread)",
    (PY.match(/asyncio\.to_thread\(/g) || []).length >= 4,
    String((PY.match(/asyncio\.to_thread\(/g) || []).length));
  check("python: роуты без параметра декоратора",
    !/@routes\.(?:get|post)\([^"]*\{/.test(PY));
}

// ── 3. JS ─────────────────────────────────────────────────────────────────
const JSC = JS ? stripComments(JS) : "";
if (JS) {
  has(JSC, /window\.comfyAPI\.app\.app/, "js: Nodes 2.0 — window.comfyAPI.app.app (не scripts/app.js)");
  check("js: нет импорта scripts/app.js", !/scripts\/app\.js/.test(JSC));
  has(JSC, /fetch\(/, "js: свои роуты через обычный fetch");
  check("js: не использует api.fetchApi (добавил бы префикс /api к нашим роутам)",
    !/api\.fetchApi/.test(JSC));
  check("js: не использует apiURL (ловушка NS / лишний префикс)", !/apiURL\(/.test(JSC));

  has(JSC, /function readComfyLocale\(/, "js: readComfyLocale() есть");
  has(JSC, /function isRu\(\)\s*\{\s*return\s+\/\^ru\/i\.test\(readComfyLocale\(\)\)/,
    "js: isRu() реально читает readComfyLocale");
  has(JSC, /function setLocaleOverride\(/, "js: setLocaleOverride() для тестов");
  has(JSC, /extensionManager[\s\S]{0,200}?setting[\s\S]{0,80}?\?\.get\(|extensionManager[\s\S]{0,200}?setting[\s\S]{0,80}?\.get\(/,
    "js: язык через app.extensionManager.setting.get('Comfy.Locale')");
  has(JSC, /getSettingValue\([\s\S]{0,60}?Comfy\.Locale/, "js: фолбэк app.ui.settings.getSettingValue");

  // Домен: DOM-виджет по правилам comfyui-dom-widget-sizing
  has(JSC, /addDOMWidget\(/, "js: используется addDOMWidget");
  has(JSC, /hideOnZoom:\s*false/, "js: hideOnZoom:false (иначе превью исчезает при отдалении)");
  has(JSC, /getMinHeight\s*:/, "js: getMinHeight (пол высоты)");
  check("js: НЕТ options.getHeight (высота пинится)", !/getHeight\s*:/.test(JSC));
  check("js: НЕТ перезаписи computeSize", !/computeSize\s*=/.test(JSC));
  check("js: НЕТ scrollHeight (feedback loop)", !/scrollHeight/.test(JSC));
  check("js: НЕТ offsetHeight (нестабильный layout)", !/offsetHeight/.test(JSC));
  check("js: НЕТ setInterval", !/setInterval/.test(JSC));
  check("js: НЕТ MutationObserver", !/MutationObserver/.test(JSC));
  check("js: НЕТ canvasOnly", !/canvasOnly/.test(JSC));
  check("js: НЕТ innerHTML", !/innerHTML/.test(JSC));
  check("js: НЕТ слушателей на window", !/window\.addEventListener/.test(JSC));
  check("js: НЕТ слушателей на document", !/document\.addEventListener/.test(JSC));

  // Персистентность
  has(JSC, /loras_data/, "js: имя виджета данных = loras_data");
  has(JSC, /options\.hidden\s*=\s*true/, "js: options.hidden = true (скрыть из панели/рендера)");
  has(JSC, /options\.hideInPanel\s*=\s*true/, "js: options.hideInPanel = true");
  has(JSC, /\.hidden\s*=\s*true/, "js: widget.hidden = true (isWidgetVisible)");
  check("js: сериализация loras_data НЕ отключена",
    /dataW\.serialize\s*=\s*false/.test(JSC) === false
    && !/loras_data[\s\S]{0,400}?options\.serialize\s*=\s*false/.test(JSC));
  check("js: DOM-виджет гасит serialize в ОБОИХ полях (prompt/workflow)",
    /serialize:\s*false/.test(JSC) && /\.serialize\s*=\s*false/.test(JSC));
  check("js: НЕТ подмены options.values (combo-протокол)", !/options\.values\s*=/.test(JSC));

  // Персистентность через JSON в loras_data
  has(JSC, /widgets_values_named/, "js: onConfigure читает widgets_values_named");
  has(JSC, /widgets_values/, "js: onConfigure читает позиционный widgets_values");

  // Дизайн по образцу Nodes 2.0 / legacy
  has(JSC, /MIN_W\s*=/, "js: MIN_W объявлен (защита имён от горизонтального скролла)");
  has(JSC, /setSize\(/, "js: node.setSize применяет MIN_W");
  has(JSC, /\.dl-foot/, "js: футер «+ LoRA» под списком");
  has(JSC, /dl-knob/, "js: knob переключателя (Switch.vue-style)");
  check("js: applySwitchMode удалён (только Nodes 2.0)", !/applySwitchMode/.test(JSC));
  check("js: без legacy-перепривязки (pointerenter на предке)", !/pointerenter/.test(JSC));
  // Запрет сужен: pointerdown законен ТОЛЬКО как scrub-слой пилюли силы
  // и как grip-слой перетаскивания строки. Проверяем получателя, а не
  // само имя события: слушатели обязаны висеть на своём слое, не на
  // window/document (те запрещены отдельными проверками).
  (() => {
    const hits = [...JSC.matchAll(/([\w$.]+)\.addEventListener\("pointer(\w+)"/g)];
    return check("js: события указателя — только на scrub/grip-слое",
      hits.length >= 3 && hits.every((m) => /scrub|grip/i.test(m[1])),
      JSON.stringify(hits.map((m) => m[1] + "." + m[2])));
  })();
  has(JSC, /\.dl-num-scrub\{[^}]*cursor:ew-resize/, "js: курсор scrub-слоя ←→ (cursor:ew-resize)");
  has(JSC, /\.dl-num-scrub\{[^}]*position:absolute/, "js: scrub-слой лежит поверх поля (position:absolute)");
  has(JSC, /\.dl-num-scrub\{[^}]*touch-action:pan-y/, "js: touch-action:pan-y у scrub-слоя (как native)");
  has(JSC, /\.dl-num-scrub\.dl-scrub-edit\{[^}]*display:none/,
    "js: css — .dl-scrub-edit реально прячет scrub-слой (display:none)");
  check("js: класс .dl-scrub-edit и ставится, и снимается",
    /setClassFlag\([^)]*"dl-scrub-edit",\s*true\)/.test(JSC)
    && /setClassFlag\([^)]*"dl-scrub-edit",\s*false\)/.test(JSC));
  check("js: ручная тяга — 10px на шаг (как native)",
    /SCRUB_PX_PER_STEP\s*=\s*10/.test(JSC));
  check("js: порог «тяга или клик» = 50px (как native isSwiping)",
    /SCRUB_THRESHOLD\s*=\s*50/.test(JSC));
  check("js: тяга меняет значение через stepStrength (один путь для кнопок и мыши)",
    /stepStrength\(\s*SCRUB\.node\s*,\s*SCRUB\.index\s*,/.test(JSC));
  check("js: без классов dl-mode-v2/dl-mode-legacy", !/dl-mode-(v2|legacy)/.test(JSC));
  has(JSC, /\.dl-grip\{/, "js: css — .dl-grip существует");
  has(JSC, /\.dl-row\.dl-dragging\{/, "js: css — .dl-row.dl-dragging (перетаскиваемая строка полупрозрачна)");
  has(JSC, /\.dl-row\.dl-drop-before\{/, "js: css — .dl-row.dl-drop-before (индикатор перед строкой)");
  has(JSC, /\.dl-row\.dl-drop-after\{/, "js: css — .dl-row.dl-drop-after (индикатор после строки)");
  check("js: moveEntry экспортирован в window.DeggLoraLoader", /moveEntry: moveEntry/.test(JSC));
  check("js: MIN_W = 380 (запас на грип 14px + gap 8px)", /MIN_W\s*=\s*380/.test(JSC));
  check("js: ключ reorder в обоих языках", /reorder: "Перетащить для изменения порядка"/.test(JSC) && /reorder: "Drag to reorder"/.test(JSC));
  check("js: toggleAt ищет .dl-sw через findByClass (grip — первый ребёнок строки)",
    /findByClass\(row,\s*"dl-sw"\)/.test(JSC));
  check("js: глобальных слушателей document/window нет (DnD тоже)",
    !/document\.addEventListener\(/.test(JSC) && !/window\.addEventListener\(/.test(JSC));
  has(JSC, /overflow-x:\s*hidden/, "js: overflow-x:hidden у списка");
  check("js: «+ LoRA» не в шапке (head.appendChild(addBtn) запрещён)",
    !/head\.appendChild\(addBtn\)/.test(JSC));
  check("js: toggle-all идут в шапке первыми (all → count, без addBtn)",
    /head\.appendChild\(allWrap\);\s*head\.appendChild\(countEl\);/.test(JSC));
  has(JSC, /dl-allwrap/, "js: обёртка мастер-переключателя .dl-allwrap");
  has(JSC, /dl-alllabel/, "js: подпись мастер-переключателя .dl-alllabel");
  has(JSC, /dl-all.*dl-sw|dl-sw.*dl-all/, "js: мастер-переключатель использует стили .dl-sw");
  has(JSC, /\.dl-img\{[^}]*object-fit:\s*cover/, "js: превью .dl-img обрезается по центру (object-fit:cover)");
  // Поле силы — как нативный виджет Nodes 2.0 (ScrubableNumberInput.vue):
  // пилюля на токенах темы, кнопки «−»/«+» с SVG-иконками, локальный формат числа.
  has(JSC, /--component-node-widget-background/, "js: поле силы на токенах темы Nodes 2.0");
  has(JSC, /dl-num-btn/, "js: поле силы — пилюля с кнопками «−»/«+» (dl-num-btn)");
  has(JSC, /lucideIcon\(/, "js: иконки степпера — SVG lucide minus/plus");
  check("js: сила форматируется через Intl.NumberFormat (как нативное поле)",
    /Intl\.NumberFormat/.test(JSC));
  check("js: шаг степпера силы = 0.05 (STRENGTH_STEP)",
    /STRENGTH_STEP\s*=\s*0\.05/.test(JSC));
  check("js: корзина без hover-правил", !/dl-row:hover\s+\.dl-del/.test(JSC));
  check("js: корзина всегда видна (без opacity:0)", !/\.dl-del\{[^}]*opacity:\s*0/.test(JSC));
  has(JSC, /createElementNS/, "js: иконка корзины через createElementNS (SVG)");
  check("js: у корзины нет серой обводки", !/\.dl-del\{[^}]*border:\s*(solid|1px|2px)/.test(JSC));
  check("js: корзина не красная", !/\.dl-del\{[^}]*color:\s*#e08a8a/.test(JSC));
  check("js: у корзины прозрачный фон", /\.dl-del\{[^}]*background:transparent/.test(JSC));
  check("js: у корзины border:none", /\.dl-del\{[^}]*border:none/.test(JSC));

  // Безопасность и сети
  has(JSC, /encodeURIComponent\(/, "js: query-параметры кодируются");
  // Раньше клиенту запрещалось считать sha256 ВООБЩЕ (хеш содержимого лоры для
  // CivitAI — дело сервера). Теперь клиент хеширует только ИМЯ лоры: кастомное
  // превью получает имя degg_lora_preview_<sha256(имя)>_<ts>, по которому сервер
  // убирает превью удалённых лор. Хеш содержимого/by-hash — по-прежнему сервер.
  check("js: клиент не строит by-hash и не читает содержимое лоры",
    !/by-hash|arrayBuffer|FileReader/.test(JSC));
  has(JSC, /crypto\.subtle/, "js: crypto.subtle — только для имени файла превью");
  has(JSC, /replace\(/, "js: описание CivitAI очищается от разметки");

  // Единый резолвер превью (T1)
  has(JSC, /attachThumb\(/, "js: единый резолвер attachThumb");
  has(JSC, /INFO_MEM/, "js: кэш /info INFO_MEM (включая негативный)");
  has(JSC, /thumbUrl\(/, "js: превью строки берётся через свой роут /thumb, не с CDN");
  has(JSC, /info\.images/, "js: карточка берёт кандидатов из images[] /info");
  has(JSC, /loading\s*=\s*"lazy"/, "js: loading=lazy (рыночные картинки полноразмерные)");

  // Ленивые сайт-превью в пикере (T6)
  has(JSC, /IntersectionObserver/, "js: пикер грузит сайт-картинки через IntersectionObserver");
  has(JSC, /rootMargin/, "js: rootMargin у IntersectionObserver (подгрузка на подходе)");
  has(JSC, /\.dl-pt\{/, "js: контейнер превью пикера .dl-pt");

  // Поиск в пикере
  has(JSC, /dl-search/, "js: поле поиска .dl-search в пикере");
  has(JSC, /searchPlaceholder/, "js: локализованный placeholder поиска");
  has(JSC, /data-name/, "js: data-name для фильтрации поиска");

  // Имя строки: серый baseModel + белое имя Civitai (T7)
  has(JSC, /dl-bm/, "js: серый baseModel строки .dl-bm");
  has(JSC, /dl-ln/, "js: белое имя Civitai строки .dl-ln");
  has(JSC, /\.title\s*=/, "js: полный путь в title строки");

  // Пикер превью: upload/view, permalink в карточке (T2)
  has(JSC, /openPreviewPicker/, "js: пикер превью openPreviewPicker");
  has(JSC, /\/upload\/image/, "js: загрузка своего превью через /upload/image");
  has(JSC, /\/view\?/, "js: показ загруженного через /view");
  has(JSC, /new FormData\(/, "js: FormData для аплоада");
  has(JSC, /dl-path/, "js: полный путь в шапке карточки пикера");
  has(JSC, /mk\("a", "dl-iname"\)/, "js: имя LoRA — ссылка на CivitAI (a.dl-iname)");
  check("js: НЕТ отдельной строки-ссылки dl-link (ссылка — само имя)", !/dl-link/.test(JSC));
  (() => {
    const m = JSC.match(/\.dl-pcand\{[^}]*width:(\d+)px/);
    return check("js: кандидаты превью не меньше 120px (.dl-pcand width)", !!m && Number(m[1]) >= 120, m ? m[1] + "px" : "не найдено");
  })();

  // Согласованность роутов Python ↔ JS
  const jsRoutes = [...new Set(JS.match(/\/degg_lora_loader\/[a-z_]+/g))].sort();
  const pyRoutes2 = PY ? [...new Set([...PY.matchAll(/@routes\.(?:get|post)\("([^"]+)"\)/g)].map((m) => m[1]))].sort() : [];
  check("js и python: одни и те же роуты",
    jsRoutes.length === 4 && JSON.stringify(jsRoutes) === JSON.stringify(pyRoutes2),
    `js=${JSON.stringify(jsRoutes)} py=${JSON.stringify(pyRoutes2)}`);
  check("js: превью идёт через свой роут /thumb, а не напрямую на CDN",
    /\/degg_lora_loader\/thumb\?file=/.test(JS), "нет /thumb в JS");

  // Согласованность имён виджетов
  if (PY) {
    for (const name of ["loras_data"]) {
      check(`js/python: имя виджета «${name}» совпадает`,
        PY.includes(`"${name}"`) && new RegExp(`["'\`]${name}["'\`]`).test(JS));
    }
  }

  // Состояние: каждая st.<поле> должна быть определена
  const stateFields = [...new Set([...JSC.matchAll(/\bst\.([A-Za-z_$][\w$]*)/g)].map((m) => m[1]))];
  const defined = new Set([
    ...[...JSC.matchAll(/\bst\.([A-Za-z_$][\w$]*)\s*=/g)].map((m) => m[1]),
    ...[...JSC.matchAll(/\b([A-Za-z_$][\w$]*)\s*:\s*(?:null|false|true|\[\]|\{\}|0|""|undefined)/g)].map((m) => m[1]),
  ]);
  const missingState = stateFields.filter((f) => !defined.has(f));
  check("js: каждое поле st.<x> определено в ensureState/присваиванием",
    missingState.length === 0, JSON.stringify(missingState));

  // Локализация UI-строк
  check("js: словари LOCALES есть", /LOCALES\s*=\s*\{/.test(JSC));
  check("js: RU-словарь есть", /ru:\s*\{/.test(JSC));
  check("js: EN-словарь есть", /en:\s*\{/.test(JSC));
  check("js: t(key) — единственная точка перевода", /function t\(/.test(JSC));
  check("js: есть перерисовка подписей при смене языка", /refreshLabels/.test(JSC));

  // Никаких модальных окон на document с глобальными слушателями
  check("js: модалка закрывается кнопкой/бэкдропом элемента",
    /closeModal\(/.test(JSC));
}

// ── 4. Локализация locales/{en,ru}/nodeDefs.json ──────────────────────────
const localeDefs = { en: null, ru: null };
for (const lang of ["en", "ru"]) {
  const rel = `locales/${lang}/nodeDefs.json`;
  const raw = read(rel);
  if (!raw) continue;
  const buf = fs.readFileSync(path.join(ROOT, rel));
  check(`${rel}: нет UTF-8 BOM`, !(buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf));
  let def = null;
  try {
    def = JSON.parse(raw);
  } catch (e) {
    check(`${rel}: валидный JSON`, false, String(e));
    continue;
  }
  check(`${rel}: ключ ноды Degg_LoRa_Loader`, !!def.Degg_LoRa_Loader);
  const d = def.Degg_LoRa_Loader;
  if (!d) continue;
  localeDefs[lang] = d;
  check(`${rel}: display_name заполнен`, typeof d.display_name === "string" && d.display_name.trim().length > 0);
  check(`${rel}: description заполнен`, typeof d.description === "string" && d.description.trim().length > 0);
  for (const slot of [...pyInputs, ...pyOptional]) {
    const s = d.inputs && d.inputs[slot];
    check(`${rel}: inputs.${slot}.name`, !!(s && s.name));
    check(`${rel}: inputs.${slot}.tooltip`, !!(s && s.tooltip));
  }
  check(`${rel}: outputs.0.name`, !!(d.outputs && d.outputs["0"] && d.outputs["0"].name));
}
if (localeDefs.en && localeDefs.ru) {
  check("локализация: RU реально переведён (display_name != EN)",
    localeDefs.ru.display_name !== localeDefs.en.display_name,
    `${localeDefs.en.display_name} / ${localeDefs.ru.display_name}`);
  check("локализация: RU-подписи входов содержат кириллицу",
    [...pyInputs, ...pyOptional].every((s) =>
      !!localeDefs.ru.inputs[s] && /[\u0400-\u04FF]/.test(localeDefs.ru.inputs[s].name)));
}

// Python — EN-источник (русские тултипы показывались бы немцу).
if (PY) {
  const tooltips = [...PY.matchAll(/tooltip":\s*"([^"]*)"/g)].map((m) => m[1]);
  check("python: тултипы без кириллицы (EN — источник, RU живёт в locales/ru)",
    tooltips.length > 0 && tooltips.every((t) => !/[\u0400-\u04FF]/.test(t)),
    JSON.stringify(tooltips));
  const descBlock = (PY.match(/DESCRIPTION\s*=\s*\(([\s\S]*?)\n\s*\)/) || [])[1] || "";
  check("python: DESCRIPTION без кириллицы (EN — источник)",
    descBlock.length > 0 && !/[\u0400-\u04FF]/.test(descBlock), descBlock.slice(0, 60));
}

// ── 5. check.json ─────────────────────────────────────────────────────────
if (CHECKJ) {
  let cj = null;
  try {
    cj = JSON.parse(CHECKJ);
  } catch (e) {
    check("check.json: валидный JSON", false, String(e));
  }
  if (cj) {
    const checks = cj.checks || [];
    check("check.json: 3 проверки", checks.length === 3, String(checks.length));
    const cmds = checks.map((c) => c.cmd);
    check("check.json: python-тест", cmds.includes("python tests/_test_degg_lora_loader.py"),
      JSON.stringify(cmds));
    check("check.json: smoke", cmds.includes("node tests/_smoke_degg_lora_loader.mjs"),
      JSON.stringify(cmds));
    check("check.json: audit", cmds.includes("node tests/_audit_degg_lora_loader.mjs"),
      JSON.stringify(cmds));
    const allExpect = checks.flatMap((c) => c.expect || []);
    check("check.json: expect — маркеры из вывода",
      ["FAIL: 0", "ТЕСТ ПРОЙДЕН", "SMOKE OK", "аудит чист"].every((m) => allExpect.includes(m)),
      JSON.stringify(allExpect));
    check("check.json: у каждой проверки есть expect",
      checks.every((c) => Array.isArray(c.expect) && c.expect.length > 0));
    check("check.json: у каждой проверки есть description",
      checks.every((c) => typeof c.description === "string" && c.description.length > 20));
  }
}

// ── 6. README: карта папок и таблица нод ──────────────────────────────────
const README = (() => {
  const p = path.join(ROOT, "..", "README.md");
  return fs.existsSync(p) ? fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n") : null;
})();
if (README) {
  check("README: строка проекта Degg_LoRa_Loader есть", /Degg_LoRa_Loader/.test(README));
  check("README: узел «Degg LoRa Loader» назван в таблице нод", /Degg LoRa Loader/.test(README));
}

console.log("");
console.log(`ok: ${oks.length}   FAIL: ${errors.length}`);
if (errors.length) {
  errors.forEach((e) => console.log("  - " + e));
  console.log("АУДИТ ПРОВАЛЕН");
  process.exit(1);
}
console.log("аудит чист");
