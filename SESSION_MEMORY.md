# Память сессии — Degg_LoRa_Loader (2026-10-12)

> Покажи этот файл агенту, чтобы продолжить работу.
> Всегда сверяйся с `AGENTS.md` и `SPECIFICATION.md`.

---

## 1. Что делали в этой сессии (кратко)
- Три этапа про производительность и чистоту превью: серверный кэш `/thumb` +
  неблокирующие роуты (этап 1), автосборка мусора sweep + TTL (этап 2),
  локальные кандидаты карточки и миграция старых CDN-URL (этап 3).
- Обновлён `SPECIFICATION.md`, всё закоммичено (`1d736d9`) и запушено.
- На уровне бандла: создан скил `comfyui-async-route-blocking`, дополнен
  `comfyui-civitai-model-info`, починен двойной счётчик провалов в
  `_process/check.py` (печатал 6 при 3 реальных).

## 2. Итоговое состояние кода
- `degg_lora_loader.py:734` `register_routes()` — **4 роута** (`:766 /loras`,
  `:771 /img`, `:782 /thumb`, `:816 /info`). Всё блокирующее — через
  `asyncio.to_thread`; семафор `HEAVY_LIMIT = 3` (`:33`), создаётся лениво
  (`:51`, иначе привязывается не к тому loop в тестах).
- `degg_lora_loader.py:637` `get_lora_info()` — **диск = источник правды**
  (0 HTTP при тёплом кэше, в т.ч. после рестарта), негативный кэш 404,
  инвалидация по `stamp` (`_file_stamp:80`, `_cache_is_fresh:111`);
  `CACHE_VERSION = "v2"` (`:26`) поднимать не нужно — семантика менялась
  как раз для записей, которых ещё нет.
- `degg_lora_loader.py:475` `_download_image()` — только `https` и хост
  `*.civitai.com` (`_allowed_image_url:456`), запись атомарная (`_write_json:97`).
- GC: `sweep_cache:183`, `sweep_input_previews:163`, `ttl_sweep:219`
  (30 суток, `TTL_INTERVAL=3600`), `touch_thumb:244` (не чаще 7 дней —
  иначе ломается ETag), `run_gc:273` из `/loras` с троттлингом `SWEEP_INTERVAL=300`.
- `web/js/degg_lora_loader.js:330` `thumbUrl` / `:334` `thumbUrlAt` — все
  превью через свой `/thumb`, не с CDN; `:1070` `migratePreview` переводит
  старые CDN-URL из воркфлоу на `/thumb?idx` при открытии карточки;
  `:1215` `uploadPreview` именует файл `degg_lora_preview_<sha256(имени)>_<ts>`
  (префикс `:1178`, имя — **третий** аргумент `FormData.append`).
- Битая картинка → глиф по событию `error` (вместо раннего `/info` — это и
  убрало лишний запрос на каждую лору).

## 3. Проблемы, которые встречались (и как решали)
- Превью тянулись с CDN на каждом открытии → свой `/thumb`: соседний файл →
  дисковый кэш → скачивание один раз, `ETag`/304.
- Первый запрос после рестарта форсил `refresh=True` → sha256 КАЖДОЙ лоры на
  каждое открытие страницы → убрано, диск доверенный.
- `async def`-роуты держали event loop (sha256/`urlopen` синхронно) →
  `asyncio.to_thread` + семафор; проверка тикером `ticks=25` (sync) против
  `103659` (поток).
- Мусор в кэше копился → sweep + TTL + предохранитель на пустой листинг.
- Три теста жили под старым контрактом и были правятся (§2.3): см. §4.

## 4. Что важно не сломать при продолжении работы
- **Sweep:** пустой/битый листинг лор → не удалять НИЧЕГО; удаляются только
  свои файлы по `_CACHE_RE:44`/`_THUMB_RE:45`/префиксу `degg_lora_preview_`.
  Чужие файлы в `input/` и соседние файлы моделей не трогать.
- **`touch_thumb`** — не чаще `TTL_TOUCH` (7 дней): mtime входит в ETag,
  «трогать на каждый запрос» = перекачка картинки на каждой странице.
- **Три теста живут под НОВЫМ контрактом** (старые формулировки вернуть = регресс):
  `10c` «дисковый кэш доверенный», а не «первый запрос в CivitAI»; глиф в
  смоуке по `error`, а не по заранее запрошенному `/info`; в аудите запрет
  «sha256 на клиенте» сужен — клиент не строит `by-hash` и не читает
  содержимое лоры, но хэш **имени** для имени превью законен.
- `render()` ОБЯЗАН вызывать `updateAllSw()` в конце (`web/js/…:600`,
  `updateAllSw:666`) — иначе toggle-all врёт после загрузки workflow.
- Клик по `dl-ln` НЕ открывает карточку (только `dl-thumb`); порядок
  `s.entries` = JSON `loras_data` = порядок применения Python.
- В `async def`-роутах не звать sync-сеть/хэш/чтение больших файлов
  (скил `comfyui-async-route-blocking`).

## 5. Следующие шаги (идеи, не сделано)
- Живая проверка в браузере: перезапуск ComfyUI + Hard Reload, в Network
  должны отсутствовать запросы к `civitai.com` при открытии страницы.
- В `F:\Python\Python314` нет `pytest` → 3 проекта красные в
  `_process/check.py` (`Custom_node_Konst_Girl`, `…_EN-RU`, `Degg_Res_Set`);
  Degg_LoRa_Loader — зелёный.
- Поставить git-предохранитель (warn «предохранитель git» есть у всех проектов).

## 6. Связанные файлы
- `degg_lora_loader.py` — нода + кэши CivitAI/превью + GC (424 → 842 строки)
- `web/js/degg_lora_loader.js` — DOM-список, карточка, превью (1426 строк)
- `tests/_test_degg_lora_loader.py` — 163 проверки (`10c/10e/10f`, тикер)
- `tests/_smoke_degg_lora_loader.mjs` — 246 проверок
- `tests/_audit_degg_lora_loader.mjs` — 203 проверки
- `SPECIFICATION.md` — обновлён (4 роута, кэш/GC, контракты тестов)
- бандл: `.agents|/.kilo|/.opencode/skills/comfyui-async-route-blocking/SKILL.md`,
  `…/comfyui-civitai-model-info/SKILL.md`, строка в `AGENTS.md`, фикс
  счётчика в `_process/check.py`

## 7. Git
- `1d736d9` — feat: local preview pipeline — /thumb cache, async routes, cache GC
- `9740f99` — Fix: toggle-all state after workflow load
