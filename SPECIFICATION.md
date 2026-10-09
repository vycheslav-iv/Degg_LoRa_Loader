# SPECIFICATION — Degg_LoRa_Loader (Degg LoRa Loader)

Нода применяет список LoRA (JSON) к цепочкам MODEL/CLIP. Список редактируется в
UI-списке прямо на ноде: превью с CivitAI, диалог информации о LoRA, общий
тумблер, добавление из каталога, локализация RU/EN.

## Состав

| Файл | Роль |
|---|---|
| `degg_lora_loader.py` | нода + 3 HTTP-роута + кэш CivitAI |
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

## HTTP-роуты (ровно 3, регистрируются в `register_routes()`)

| Роут | Что отдаёт |
|---|---|
| `GET /degg_lora_loader/loras` | каталог лор из models/loras: `[{name, image}]`, `image` — URL превью или `null` |
| `GET /degg_lora_loader/img?file=` | картинка-сосед лоры (`sibling_image_path`); traversal → 400, нет файла → 404 |
| `GET /degg_lora_loader/info?file=` | данные CivitAI: `ok, name, baseModel, trigger, description, images, permalink, localImage` |

Роуты под try/except: без ComfyUI (`server`/`folder_paths` недоступны) нода
импортируется, просто без роутов. JS использует те же 3 префикса буквально
(без `api.fetchApi`/`apiURL` — те добавили бы префикс `/api`).

### Кэш `/info` (роут-локальный seen-set)

- `refresh=1` → всегда HTTP (форс);
- `safe_name` уже в `seen` → дисковый кэш, **0 HTTP**;
- иначе — HTTP-запрос (sha256 файла, CivitAI `model-versions/by-hash/`),
  результат в `user/default/degg_lora_cache/`, затем `seen.add`.
- Порядок: запись кэша **до** вычисления sha256 (иначе chicken-and-egg: ключ кэша
  — артефакт того, что уже положили в кэш).

Тесты: `10c.1` первый запрос → HTTP=1; `10c.2` повтор → HTTP=0;
`10c.3` `refresh=1` → HTTP=1. TTL отклонён как флейки — seen-set живёт
только внутри одного вызова роута.

## Фронтенд (JS)

Константы: `HEAD_H=34`, `ROW_H=90`, `LIST_ROWS=3`, `CONTENT_MIN_H=304`,
`MARGIN=10`; `getMinHeight() = 324` — пол высоты (без `getHeight`/`computeSize`).

- Импорт: `window.comfyAPI.app.app`; регистрация через
  `app.registerExtension({name: "Degg.LoraLoader", beforeRegisterNodeDef})`,
  чужие ноды отбрасываются по имени; унаследованные `onNodeCreated/onConfigure/
  onRemoved` вызываются, `computeSize`/`computeLayoutSize` не перезаписываются.
- Корень пола: inline `height:100%; min-height:304px; display:flex;
  flex-direction:column; overflow:hidden` + `.dl-list{flex:1; overflow-y:auto}`.
  `hideOnZoom: false` (иначе превью исчезает при ds.scale < 0.6), `hideInPanel: true`.
- Строка: `[toggle aria-checked][thumb 82][name][num input][✕]`.
  Тумблер и `toggleAll` меняют класс `dl-off`/счётчик на месте; остальные
  мутации перерисовывают список и пишут JSON в `loras_data`.
- Состояние — `node._dl` (+ `node._dlReady`); глобальных слушателей нет
  (window/document.addEventListener запрещены тестом), `setTimeout`/rAF не
  используются.
- Модалки (picker/info) — элементы на `document.body`, закрытие кнопкой/бэкдропом,
  без глобальных keydown/Escape.
- Локализация: словари `LOCALES.ru/.en` (одинаковые ключи; EN без кириллицы),
  `t(key)` — единственная точка перевода, язык из `Comfy.Locale`
  (`extensionManager.setting.get` → `getSettingValue`), `setLocaleOverride` —
  ручной переключатель (тесты). Подписи обновляет `refreshLabels`.
- `/degg_lora_loader/img` используется и в строках, и в picker; `/info` — только
  по клику на превью (sha256 дорогой, каталог его не дёргает).

## Проверки

```bash
python _process/check.py Degg_LoRa_Loader
```

Три проверки из `check.json`: Python-песочница, JS-смоук (vm-заглушки DOM/fetch),
статический аудит (Python ↔ JS ↔ locales ↔ check.json + запрещённые приёмы
AGENTS.md §4.1/§5). Каждый пункт задачи должен иметь красную версию до правки
(скил `comfyui-task-acceptance`); приёмка — мутацией (скил `comfyui-mutation-testing`).
