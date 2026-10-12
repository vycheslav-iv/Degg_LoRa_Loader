# SPECIFICATION — Degg_LoRa_Loader (Degg LoRa Loader)

Нода применяет список LoRA (JSON) к цепочкам MODEL/CLIP. Список редактируется в
UI-списке прямо на ноде: превью с CivitAI, единая карточка LoRA (детали + выбор
превью), общий тумблер, добавление из каталога, локализация RU/EN.

## Состав

| Файл | Роль |
|---|---|
| `degg_lora_loader.py` | нода + 4 HTTP-роута + кэши CivitAI и превью |
| `__init__.py` | `NODE_CLASS_MAPPINGS` + `WEB_DIRECTORY = "web"` |
| `web/js/degg_lora_loader.js` | LiteGraph/Nodes 2.0 расширение: DOM-список, модалки, локализация |
| `locales/{en,ru}/nodeDefs.json` | переводы (RU показывается только при ru-локали) |
| `tests/` | Python-песочница + JS-смоук + статический аудит (без ComfyUI) |
| `check.json` | три проверки для `_process/check.py` |

## Нода (Python)

- `INPUT_TYPES`: required `loras_data` (STRING, default `"[]"`); optional `model` (MODEL), `clip` (CLIP).
- `RETURN_TYPES = ("MODEL", "CLIP")`, `RETURN_NAMES = ("model", "clip")`, `FUNCTION = "load_loras"`,
  `CATEGORY = "My_custom_nodes/LoRA"`. `OUTPUT_NODE` не установлен — нода не output.
- Тяжёлые импорты (`folder_paths`, `nodes.LoraLoader`) — лениво, внутри функций:
  импорт модуля живёт без запущенного ComfyUI (иначе падает Python-тест и смоук).
- `apply_loras` вызывает `loader.load_lora(model, clip, name, strength, strength_clip)` —
  **имя файла, а не путь** (иначе ломается кэширование/резолв ComfyUI).
- `model`/`clip` опциональны: если не подключены — соответствующая цепочка
  пропускается (pass-through), LoRA применяется к тому, что подключено.

## Формат данных `loras_data`

JSON-массив объектей `{on, lora, strength, strength_clip}` — та же схема в Python
(`parse_loras`) и в JS (`parseLoras`), зеркально:

- не-словари, записи без `lora`, пустое имя — отбрасываются; битый JSON → `[]`;
- чтение принимает и обёртку `{"loras": [...]}` (совместимость), запись всегда — массив;
- `strength`/`strength_clip`: NaN/пусто → 1, кламп ±100; `on` — строгий парсер bool.

**Персистентность (Option B, подтверждена по фронтенду `settingStore`):**
`serialiseWidgetValues` исключает только `widget.serialize === false`, поле `hidden`
не проверяется. Поэтому:

- `loras_data`: `hidden = true` + `options.hidden` + `options.hideInPanel` (скрыт в UI),
  сериализация **НЕ** отключается — иначе список пропадает из workflow/prompt;
- DOM-виджет `degg_lora_list`: `serialize: false` (в options — prompt) и
  `listW.serialize = false` (свойство — workflow); он в prompt не попадает.

Значение в `loras_data` пишется на **каждую** мутацию (add/remove/toggle/strength/
toggle-all) — JSON-массив. Загрузка: `onConfigure` читает
`widgets_values_named.loras_data`, иначе первый string в `widgets_values`,
начинающийся с `[`.

## HTTP-роуты (ровно 4, регистрируются в `register_routes()`)

| Роут | Что отдаёт |
|---|---|
| `GET /degg_lora_loader/loras` | каталог лор из models/loras: `[{name, image}]`, `image` — URL превью или `null` |
| `GET /degg_lora_loader/img?file=` | картинка-сосед лоры (`sibling_image_path`); traversal → 400, нет файла → 404 |
| `GET /degg_lora_loader/info?file=` | данные CivitAI: `ok, name, baseModel, trigger, description, images, permalink, localImage` |
| `GET /degg_lora_loader/thumb?file=&idx=` | превью для показа: соседний файл → дисковый кэш → скачивание из CivitAI (один раз) |

Роуты под try/except: без ComfyUI (`server`/`folder_paths` недоступны) нода
импортируется, просто без роутов. JS использует те же 4 роута буквально
(без `api.fetchApi`/`apiURL` — те добавили бы префикс `/api`).

### Кэш метаданных `/info` (диск — источник правды)

- дисковый кэш `user/default/degg_lora_cache/<sha256(имя)>.<CACHE_VERSION>.json`
  **доверенный**: тёплый кэш → **0 HTTP**, в том числе первый запрос после
  рестарта ComfyUI. Прежде первый запрос каждого процесса форсил `refresh=True`,
  то есть считал sha256 ВСЕГО файла лоры и ходил в CivitAI для каждой лоры на
  каждое открытие страницы (при 20 лорах — гигабайты чтения с диска);
- HTTP (sha256 файла → CivitAI `model-versions/by-hash/`) только при отсутствии
  кэша или `refresh=1`;
- **негативный кэш**: 404 от CivitAI запоминается (`ok: false`), чтобы локальная
  (не выложенная на CivitAI) лора не хэшировалась заново каждый раз;
  **сетевой сбой не кэшируется** — иначе кэш отравился бы навсегда;
- инвалидация по `stamp` ([размер, mtime_ns] файла лоры): переучил/подменил
  лору — данные обновятся. Записи старого формата без `stamp` считаются свежими,
  поэтому `CACHE_VERSION` не поднимался: новая семантика касается как раз тех
  лор, у которых файла кэша ещё нет.

Тесты: `10c` тёплый кэш → 0 HTTP; `10e` холодный → 1 HTTP и «после рестарта»
(роуты перерегистрированы) → 0 HTTP; `10f` повтор 404 → 0 HTTP, сетевой сбой →
снова HTTP, изменение файла → снова HTTP.

### Кэш превью `/thumb`

- порядок отдачи: соседний файл лоры (`sibling_image_path`) → дисковый кэш
  `degg_lora_cache/img/<sha256(имя)>.i<idx>.<ext>` → скачивание
  `images[idx].url` из CivitAI (один раз);
- `idx` — индекс картинки в `images[]` (0 — дефолтная, то есть `images[0]`);
- скачивание только `https` и только хост `*.civitai.com` (данные кэша — не
  разрешение на запрос к произвольному URL); расширение из URL, при отсутствии
  — из `Content-Type`;
- ответ — `FileResponse` + `ETag`/`Cache-Control: no-cache`: повтор отдаётся
  304 без байтов картинки, а после чистки кэша браузер не показывает старое;
- блокирующие операции (sha256, `urlopen`, stat) уходят в поток
  (`asyncio.to_thread`): sync-вызов внутри `async def` морозит ВЕСЬ сервер
  ComfyUI (очередь, прогресс, websocket). Тяжёлые операции ограничены семафором
  `HEAVY_LIMIT = 3`, иначе открытие страницы с 20+ лорами запускает десятки
  чтений файлов и запросов сразу.

## Сборка мусора (этап 2: без ручной чистки)

Два механизма, оба автоматические:

1. **sweep при загрузке каталога** (`/loras`, троттлинг `SWEEP_INTERVAL = 300` с):
   для каждой лоры с диска считается `sha256(имя)`; всё в кэше, чей хеш не
   совпал ни с одной живой лорой, удаляется — `*.json` метаданных,
   `img/<hash>.i<idx>.<ext>` и кастомные превью
   `input/degg_lora_preview_<hash>_*`. Переименовал/удалил лору — следы ушли.
   - **предохранитель:** битый или пустой листинг лор = «не знаем, что живо» →
     не удаляется НИЧЕГО (иначе недоступная сетевая папка уносит весь кэш);
   - удаляются только файлы СВОЕГО вида (строгие `_CACHE_RE`/`_THUMB_RE`/
     префикс превью): чужие `notes.txt`, `readme.md` и любые файлы в `input/`
     не трогаются. Файлы активных лор не трогаются тем же сравнением хешей.
2. **TTL** (`ttl_sweep`, троттлинг `TTL_INTERVAL = 3600` с): файлы кэша старше
   `TTL_SECONDS = 30` дней удаляются по mtime — страховка, если sweep давно не
   запускался. К чему обращались, продлевает жизнь: `/thumb` из дискового кэша
   трогает mtime (`touch_thumb`), но не чаще `TTL_TOUCH_SECONDS = 7` дней —
   mtime входит в ETag, а на каждый запрос трогать нельзя, иначе браузер
   перекачивал бы картинку на каждой странице.

Плюс `refresh=1` у `/info` (ручное обновление) сбрасывает и кэш превью этой
лоры (`drop_thumb_cache`) — следующий `/thumb` скачает картинку заново.

### Имя кастомного превью (связь с лорой)

`uploadPreview` грузит файл через родной `/upload/image` ComfyUI, но с именем
`degg_lora_preview_<sha256(имя лоры)>_<ts>.<ext>`: имя передаётся третьим
аргументом `FormData.append("image", file, name)` — ComfyUI берёт имя файла из
multipart-части (`server.py`: `filename = image.filename`), отдельного поля
`filename` он не читает. Хеш считается через `crypto.subtle.digest` (ComfyUI на
localhost — secure context); без него или без `TextEncoder` имя не подменяется
(деградация без ошибок) — такие файлы подчистит только TTL. Суффикс ` (1)`,
который ComfyUI дописывает при совпадении имён, sweep терпит (regex по префиксу).

### Ссылка на страницу LoRA (CivitAI)

`model-versions/by-hash/` поля `permalink` **не отдаёт** (проверено сырым
ответом: ключи `[… id, modelId …]`, `permalink` отсутствует), поэтому
`_normalize_civitai` строит ссылку сам через `civitai_page_url(modelId, id)`:
`https://civitai.com/models/{modelId}?modelVersionId={id}` (без `id` — только
`/models/{modelId}`; без `modelId` — `None`). `permalink` из ответа, если
когда-нибудь появится, имеет приоритет. Живая проверка: для реальной лоры ссылка
открывается 200 и ведёт на её страницу.

Файл кэша версионирован (`CACHE_VERSION = "v2"`, `<sha256 имени>.v2.json`):
старые записи без ссылки **не** переиспользуются — иначе у уже закэшированных
лор ссылка не появилась бы. Старые файлы можно удалить вручную из
`user/default/degg_lora_cache/`.

## Фронтенд (JS)

Константы: `HEAD_H=34`, `ROW_H=90`, `LIST_ROWS=3`, `CONTENT_MIN_H=304`,
`MARGIN=10`, `MIN_W=380`, `STRENGTH_STEP=0.05`, `SCRUB_PX_PER_STEP=10`,
`SCRUB_THRESHOLD=50`; `getMinHeight() = 324` — пол высоты
(без `getHeight`/`computeSize`).

- Импорт: `window.comfyAPI.app.app`; регистрация через
  `app.registerExtension({name: "Degg.LoraLoader", beforeRegisterNodeDef})`,
  чужие ноды отбрасываются по имени; унаследованные `onNodeCreated/onConfigure/
  onRemoved` вызываются, `computeSize`/`computeLayoutSize` не перезаписываются.
- Корень пола: inline `height:100%; min-height:304px; display:flex;
  flex-direction:column; overflow:hidden` + `.dl-list{flex:1; overflow-y:auto}`.
  **Без `margin` у корня**: фронтенд (`DomWidgets.vue`) сам позиционирует
  оверлей `.dom-widget` с инсетом `widget.margin=10` (pos = node.pos+margin,
  size − 2·margin); собственный `margin:10px` удваивал отступ, расталкивал
  корень до краёв ноды (`w-full` + margin → border-box reaches node edge) и
  футер-кнопка `.dl-add` перекрывала SE-угол — ресайз мышью в classic-режиме
  не работал. Внешняя L-полоска 10px угловой зоны 15×15 обязана оставаться
  канвасом (живая проба `tests/_probe_live_resize.py`).
  `hideOnZoom: false` (иначе превью исчезает при ds.scale < 0.6), `hideInPanel: true`.
- Строка: `[toggle aria-checked][thumb 82][grip][name][strength][✕]`.
  Тумблер и `toggleAll` меняют класс `dl-off`/счётчик на месте; остальные
  мутации перерисовывают список и пишут JSON в `loras_data`.
  Клик по `name` (`dl-ln`) НЕ открывает карточку — только клик по `thumb` (`dl-thumb`).
- **Toggle-all state**: `render()` ОБЯЗАН вызывать `updateAllSw()` в конце —
  иначе при загрузке workflow переключатель «Все вкл/выкл» остаётся в начальном
  состоянии (`aria-checked="true"`), хотя большинство лор выключены. Был баг:
  после reload ComfyUI toggle показывал «все активны» при одной активной лоре.
- **Перетаскивание за ручку (grip)**: `pointerdown/pointermove/pointerup/
  pointercancel` на `.dl-grip` (SVG-6 точек, `cursor:grab`, `touch-action:none`,
  ширина 22px, hover-подсветка). Ручка — третий ребёнок строки (между thumb и name).
  `setPointerCapture` на ручке; модульное состояние `DRAG = {node, from, to,
  grip}`. `dragMove` вычисляет слот по midpoint строк (`_rect`/`getBoundingClientRect`),
  ставит `.dl-drop-before`/`.dl-drop-after` (inset box-shadow); `dragEnd` вызывает
  `moveEntry(node, from, to)`, который меняет порядок в `s.entries` = JSON
  `loras_data` = порядок применения Python. Клик без движения — no-op; `pointercancel`
  отменяет. Слушатели только на ручке; `window/document` не трогаем.
  `toggleAt` находит `.dl-sw` через `findByClass(row, "dl-sw")`.
  `stopPropagation` на pointerdown предотвращает перехват LiteGraph'ом.
- **Поле силы** — копия нативного виджета Nodes 2.0
  (`ScrubableNumberInput.vue`): пилюля `.dl-num` (высота 24px, radius 6px) с
  кнопками `−`/`+` (`.dl-num-btn`, SVG-иконки lucide minus/plus через
  `createElementNS`) и полем `.dl-num-input` по центру; фон/текст — токены темы
  `--component-node-widget-background` / `--component-node-foreground` (+`-hovered`),
  чтобы виджет совпадал с остальными виджетами фронтенда. Кнопки шагают на
  `STRENGTH_STEP=0.05` (`stepStrength`), кламп ±100 и округление до 4 знаков —
  без float-мусора. Значение показывается как нативное: `Intl.NumberFormat`
  по текущему языку (в RU — «3,52»), а ввод принимает и запятую, и точку
  (`normalizeNumberText`); при смене языка `refreshLabels` переформатирует число.
- **Ручная тяга по значению (scrub)** — как у нативного поля силы: поле накрыто
  прозрачным слоем `.dl-num-scrub` (внутри `.dl-num-mid`) с курсором ←→
  (`cursor:ew-resize`, `touch-action:pan-y`). Зажатая ЛКМ тянет значение:
  `SCRUB_PX_PER_STEP=10` — один шаг силы на каждые 10px, **вправо — больше**
  (нативное `usePointerSwipe.distanceX = posStart.x − posEnd.x`, а значение
  считается как `value − delta·step`). Отпускание после пути ≥ `SCRUB_THRESHOLD=50px`
  — это тяга, ручной ввод не открывается; клик без движения, наоборот, прячет
  слой (класс `dl-scrub-edit` → `display:none`), ставит фокус в поле и выделяет
  текст под замену (`select()`), слой возвращается по `blur`; `pointercancel`
  (жест забрал браузер), как и у нативного поля, ручной ввод не открывает.
  Обработчики
  (`scrubBegin`/`scrubDrag`/`scrubEnd`) висят **только на своём слое** и берут
  `setPointerCapture`, поэтому тяга продолжается и за пределами пилюли;
  глобальные `window`/`document` слушатели по-прежнему запрещены. Тяга меняет
  значение тем же `stepStrength`, что и кнопки «−»/«+» (кламп и округление
  общие).
- Состояние — `node._dl` (+ `node._dlReady`); глобальных слушателей нет
  (window/document.addEventListener запрещены тестом), `setTimeout`/rAF не
  используются.
- **Карточка LoRA** (единая): клик по превью (`dl-thumb`) открывает модалку
  `openLoraCard` — клик по имени (`dl-ln`) НЕ открывает карточку. Вверху детали
  (`.dl-details`: имя-ссылка `a.dl-iname` — **единственная** ссылка на страницу
  LoRA, с `title`-подсказкой «Открыть на CivitAI» и подчёркиванием по hover,
  чтобы кликабельность была видна; отдельной строки-ссылки НЕТ (убиралась как
  дубль), и она появляется только при наличии `permalink` из `/info`; далее
  `baseModel`, триггеры, описание), ниже сетка кандидатов превью
  `.dl-pgrid > .dl-pcand` (локальное превью, своё, картинки CivitAI) +
  `Загрузить`/`Сбросить`. `openPreviewPicker` — алиас `openLoraCard`;
  `openInfo(node, name)` открывает ту же карточку по имени, а для лоры вне
  списка — детали без сетки (`index < 0`). Один `fetchInfo` на карточку: детали
  и кандидаты из CivitAI рендерятся вместе.
- Кандидаты CivitAI — **локальный** `/thumb?file=<лора>&idx=<n>`, а не ссылка
  на CDN: выбранное превью сохраняется в `loras_data` локальным URL и грузится
  с диска. Уже сохранённый в воркфлоу CDN-URL той же картинки **мигрирует** на
  `/thumb?idx` при открытии карточки (`migratePreview`) — иначе старые воркфлоу
  продолжали бы тянуть CDN. Своё превью (`/view?...`) не трогается.
- **Пикер каталога** (`openPicker`): модалка «Выбор LoRA» со списком всех лор.
  Поле поиска `.dl-search` (input, placeholder локализован) — фильтрует список
  по подстроке (case-insensitive) через `data-name` (lowercase) на каждом
  элементе `.dl-pitem`. При пустом каталоге поле скрыто.
- Модалки (каталог «+ LoRA» и карточка LoRA) — элементы на `document.body`,
  закрытие кнопкой/бэкдропом, без глобальных keydown/Escape.
- Локализация: словари `LOCALES.ru/.en` (одинаковые ключи; EN без кириллицы),
  `t(key)` — единственная точка перевода, язык из `Comfy.Locale`
  (`extensionManager.setting.get` → `getSettingValue`), `setLocaleOverride` —
  ручной переключатель (тесты). Подписи обновляет `refreshLabels`.
- превью строк и каталога идут через `/degg_lora_loader/thumb?file=` (не
  прямой ссылкой на CDN): картинка берётся с диска, а не качается заново на
  каждом открытии страницы; `/img` остался для карточки (соседний файл),
  `/info` — строкой (имя/baseModel) и карточкой (детали + кандидаты);
- если превью не загрузилось (`error` — лора удалена, кэш почищен), картинка
  заменяется глифом, а не остаётся пустой рамкой: «есть ли превью» JS заранее
  не опрашивает — это и был лишний `/info` в пути превью;
- ограничитель параллельности на клиенте для превью НЕ нужен: холодный путь
  `/thumb` (sha256 + скачивание) уже сериализован семафором на сервере
  (`HEAVY_LIMIT`), а тёплый путь — чтение файла с диска.

## Проверки

```bash
python _process/check.py Degg_LoRa_Loader
```

Три проверки из `check.json`: Python-песочница, JS-смоук (vm-заглушки DOM/fetch;
включая поведенческие проверки поля силы — шаг 0.05, формат числа, тяга по
значению и клик в ручной ввод), статический аудит (Python ↔ JS ↔ locales ↔
check.json + запрещённые приёмы AGENTS.md §4.1/§5). Каждый пункт задачи должен
иметь красную версию до правки (скил `comfyui-task-acceptance`); приёмка —
мутацией (скил `comfyui-mutation-testing`).

⚠️ **Три теста живут под НОВЫМ контрактом** (правились по §2.3 — правится тест,
а не задача; «вернуть старую формулировку» = регресс):

- python `10c`: раньше «первый запрос проходит через sha256 в CivitAI» — эта
  формулировка и была багом; теперь «дисковый кэш доверенный — шитьё + запрос
  без HTTP» (диск — источник правды, HTTP только при промахе/`refresh=1`);
- смоук: «есть ли превью» JS больше не опрашивает заранее через `/info` —
  битая картинка уступает место глифу по событию `error` (и это убирает лишний
  запрос `/info` на каждую лору в пути превью);
- аудит: запрет «sha256 НЕ вычисляется на клиенте» сужен, а не отменён —
  клиент не строит `by-hash` и не читает содержимое лоры, но хэш **имени**
  для имени файла превью законен (иначе сервер не свяжет файл с лорой).
  Плюс сверка «один префикс превью в JS и Python» — иначе sweep не найдёт файлы.
