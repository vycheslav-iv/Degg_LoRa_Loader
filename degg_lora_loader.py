"""Degg LoRa Loader — apply a JSON list of LoRAs with on/off and strengths.

Python side of the node: parsing the persisted loras_data JSON, applying
LoRAs through nodes.LoraLoader, sibling preview lookup, CivitAI info cache,
the on-disk preview cache and the four HTTP routes used by the DOM frontend.
"""

import asyncio
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

NODE_KEY = "Degg_LoRa_Loader"

CIVITAI_BY_HASH = "https://civitai.com/api/v1/model-versions/by-hash/"
CACHE_DIR_NAME = "degg_lora_cache"
IMAGE_CACHE_DIR_NAME = "img"
# Версия формата кэша: `model-versions/by-hash` не отдаёт permalink, ссылка на
# страницу лоры строится из modelId/id; старый кэш (без ссылки) не переиспользуем.
CACHE_VERSION = "v2"
HTTP_TIMEOUT = 10
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
CONTENT_TYPE_EXTS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
USER_AGENT = "DeggLoRaLoader/1.0"
# Сколько тяжёлых операций (sha256/сеть) идёт одновременно: иначе открытие
# страницы с 20+ лорами запускает десятки чтений файлов и запросов сразу.
HEAVY_LIMIT = 3
HEAVY_SEMAPHORE = None

# Сборка мусора (этап 2): кэш удалённых лор + TTL как страховка. Ручная чистка
# не нужна — но и удалять что-то лишнее нельзя: чистятся только ФАЙЛЫ СВОЕГО
# ВИДА (см. _CACHE_RE/_THUMB_RE/_TMP_RE и префикс кастомного превью).
SWEEP_INTERVAL = 300           # не чаще раза в 5 минут
TTL_INTERVAL = 3600            # TTL-проход — не чаще раза в час
TTL_SECONDS = 30 * 86400       # старше 30 дней — мусор
TTL_TOUCH_SECONDS = 7 * 86400  # к чему обращались — не чаще раза в неделю
PREVIEW_NAME_PREFIX = "degg_lora_preview_"
_CACHE_RE = re.compile(r"^([0-9a-f]{64})(?:\.[0-9A-Za-z_]+)?\.json$")
_THUMB_RE = re.compile(r"^([0-9a-f]{64})\.i\d+(?:\.[0-9A-Za-z]+)?$")
_TMP_RE = re.compile(r"^([0-9a-f]{64})(?:\.[0-9A-Za-z]+)*\.tmp$")
_PREVIEW_RE = re.compile(r"^" + PREVIEW_NAME_PREFIX + r"([0-9a-f]{64})_\d+")
_LAST_SWEEP = 0.0
_LAST_TTL = 0.0

def _heavy_semaphore():
    global HEAVY_SEMAPHORE
    if HEAVY_SEMAPHORE is None:
        HEAVY_SEMAPHORE = asyncio.Semaphore(HEAVY_LIMIT)
    return HEAVY_SEMAPHORE


def cache_root():
    """Каталог дискового кэша ноды (user/default/degg_lora_cache) или None."""
    try:
        import folder_paths
        return os.path.join(
            folder_paths.get_user_directory(), "default", CACHE_DIR_NAME)
    except Exception:
        return None


def _cache_key(name):
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _lora_full_path(name):
    try:
        import folder_paths
        return folder_paths.get_full_path("loras", name)
    except Exception:
        return None


def _file_stamp(path):
    """Слепок файла [размер, mtime_ns] — им кэш узнаёт о подмене/переучивании лоры."""
    try:
        stat = os.stat(path)
    except Exception:
        return None
    return [int(stat.st_size), int(stat.st_mtime_ns)]


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write_json(path, payload):
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except Exception:
        return False


def _cache_is_fresh(record, full_path):
    if not isinstance(record, dict):
        return False
    stamp = record.get("stamp")
    if stamp is None:
        return True
    return stamp == _file_stamp(full_path)


def _listdir(directory):
    try:
        return os.listdir(directory)
    except Exception:
        return []


def _remove(path):
    try:
        os.remove(path)
        return 1
    except Exception:
        return 0


def _cache_stem(entry):
    match = _CACHE_RE.match(entry)
    return match.group(1) if match else None


def _thumb_stem(entry):
    match = _THUMB_RE.match(entry)
    return match.group(1) if match else None


def _input_directory():
    try:
        import folder_paths
        return folder_paths.get_input_directory()
    except Exception:
        return None


def active_hashes(names):
    """Хеши имён существующих лор — по ним отличается живой кэш от мусора."""
    active = set()
    for name in names or []:
        safe = safe_lora_name(name)
        if safe:
            active.add(_cache_key(safe))
    return active


def sweep_input_previews(active):
    """Удаляет кастомные превью лор, которых больше нет на диске.

    Только свои файлы (префикс `degg_lora_preview_` + хеш имени лоры); суффикс
    ` (1)`, который дописывает ComfyUI при совпадении имён, тоже подходит.
    """
    directory = _input_directory()
    if not directory:
        return 0
    removed = 0
    for entry in _listdir(directory):
        if not entry.startswith(PREVIEW_NAME_PREFIX):
            continue
        match = _PREVIEW_RE.match(entry)
        if not match or match.group(1) in active:
            continue
        removed += _remove(os.path.join(directory, entry))
    return removed


def sweep_cache(active_names=None, force=False):
    """Кэш лор, которых нет на диске, — в мусор.

    Предохранитель: битый/пустой листинг лор означает «не знаем, что живо» и
    НЕ чистит ничего — иначе одна сетевая папка вне доступа уносит весь кэш.
    """
    global _LAST_SWEEP
    now = time.time()
    if not force and now - _LAST_SWEEP < SWEEP_INTERVAL:
        return 0
    if active_names is None:
        try:
            import folder_paths
            active_names = folder_paths.get_filename_list("loras")
        except Exception:
            return 0
    if not active_names:
        return 0
    _LAST_SWEEP = now
    active = active_hashes(active_names)
    removed = 0
    root = cache_root()
    if root:
        for entry in _listdir(root):
            stem = _cache_stem(entry)
            if stem and stem not in active:
                removed += _remove(os.path.join(root, entry))
        image_dir = os.path.join(root, IMAGE_CACHE_DIR_NAME)
        for entry in _listdir(image_dir):
            stem = _thumb_stem(entry)
            if stem and stem not in active:
                removed += _remove(os.path.join(image_dir, entry))
    removed += sweep_input_previews(active)
    return removed


def ttl_sweep(force=False):
    """Страховка на крайний случай: к чему не обращались 30 дней — мусор."""
    global _LAST_TTL
    now = time.time()
    if not force and now - _LAST_TTL < TTL_INTERVAL:
        return 0
    _LAST_TTL = now
    root = cache_root()
    if not root:
        return 0
    cutoff = now - TTL_SECONDS
    removed = 0
    for directory in (root, os.path.join(root, IMAGE_CACHE_DIR_NAME)):
        for entry in _listdir(directory):
            if not (_cache_stem(entry) or _thumb_stem(entry) or _TMP_RE.match(entry)):
                continue
            path = os.path.join(directory, entry)
            try:
                if os.path.getmtime(path) < cutoff:
                    removed += _remove(path)
            except Exception:
                continue
    return removed


def touch_thumb(path):
    """Продлевает жизнь активно используемого кэша превью (не чаще раза в неделю).

    mtime входит в ETag, поэтому трогаем редко: иначе браузер перекачивал бы
    картинку на каждой странице.
    """
    try:
        if time.time() - os.path.getmtime(path) < TTL_TOUCH_SECONDS:
            return False
        os.utime(path, None)
        return True
    except Exception:
        return False


def drop_thumb_cache(safe_name):
    """Сброс кэша превью лоры: следующий /thumb скачает картинку заново."""
    root = cache_root()
    if not root:
        return 0
    image_dir = os.path.join(root, IMAGE_CACHE_DIR_NAME)
    prefix = _cache_key(safe_name) + "."
    removed = 0
    for entry in _listdir(image_dir):
        if entry.startswith(prefix) and _thumb_stem(entry):
            removed += _remove(os.path.join(image_dir, entry))
    return removed


def run_gc(active_names=None):
    return sweep_cache(active_names) + ttl_sweep()


def _num(value, default=1.0):
    if isinstance(value, bool) or value is None:
        return float(default)
    try:
        f = float(value)
    except Exception:
        return float(default)
    if f != f:
        return float(default)
    if f > 100.0:
        f = 100.0
    elif f < -100.0:
        f = -100.0
    return f


def _flag(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def safe_lora_name(name):
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name:
        return None
    if "\x00" in name or ":" in name:
        return None
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return None
    for part in norm.split("/"):
        if part in ("", ".", ".."):
            return None
    return name


def parse_loras(raw):
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return []
    else:
        data = raw
    if isinstance(data, dict):
        data = data.get("loras")
    if not isinstance(data, (list, tuple)):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        lora = item.get("lora")
        if not isinstance(lora, str):
            continue
        lora = lora.strip()
        if not lora:
            continue
        strength = _num(item.get("strength"), 1.0)
        clip_value = item.get("strength_clip")
        if clip_value is None:
            strength_clip = strength
        else:
            strength_clip = _num(clip_value, strength)
        row = {
            "on": _flag(item.get("on"), True),
            "lora": lora,
            "strength": strength,
            "strength_clip": strength_clip,
        }
        preview = item.get("preview")
        if isinstance(preview, str) and preview.strip():
            row["preview"] = preview
        out.append(row)
    return out


def apply_loras(model, clip, loras_data):
    if model is None:
        return (model, clip)
    entries = parse_loras(loras_data)
    if not entries:
        return (model, clip)
    import folder_paths
    from nodes import LoraLoader
    loader = LoraLoader()
    for entry in entries:
        if not entry["on"]:
            continue
        strength = entry["strength"]
        strength_clip = entry["strength_clip"]
        if strength == 0 and strength_clip == 0:
            continue
        name = safe_lora_name(entry["lora"])
        if not name:
            continue
        try:
            path = folder_paths.get_full_path("loras", name)
        except Exception:
            path = None
        if not path or not os.path.isfile(path):
            continue
        result = loader.load_lora(model, clip, name, strength, strength_clip)
        if result:
            model, clip = result
    return (model, clip)


def sibling_image_path(lora_name):
    safe = safe_lora_name(lora_name)
    if not safe:
        return None
    try:
        import folder_paths
        full = folder_paths.get_full_path("loras", safe)
    except Exception:
        full = None
    if not full:
        return None
    base = os.path.splitext(full)[0]
    for ext in IMAGE_EXTS:
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    return None


def _strip_html(text):
    if not isinstance(text, str) or not text:
        return ""
    out = re.sub(r"<[^>]*>", " ", text)
    out = html.unescape(out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _http_get_json(url, timeout=HTTP_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _fetch_civitai_info(digest):
    """Запрос by-hash: ('ok', data) | ('not-found', None) | ('error', None).

    «not-found» можно кэшировать негативно (такой лоры нет на CivitAI), а
    сетевой сбой — нельзя: иначе кэш отравится и данные не появятся никогда.
    """
    url = CIVITAI_BY_HASH + digest
    try:
        data = _http_get_json(url, timeout=HTTP_TIMEOUT)
    except urllib.error.HTTPError as err:
        if getattr(err, "code", None) == 404:
            return ("not-found", None)
        return ("error", None)
    except Exception:
        return ("error", None)
    if not isinstance(data, dict):
        return ("error", None)
    return ("ok", data)


def _image_ext_from_url(url):
    try:
        path = urllib.parse.urlsplit(str(url)).path
    except Exception:
        return ""
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in IMAGE_EXTS else ""


def _allowed_image_url(url):
    """Только https-картинки CivitAI: кэш метаданных — не разрешение на SSRF."""
    if not isinstance(url, str):
        return None
    value = url.strip()
    if not value:
        return None
    try:
        parts = urllib.parse.urlsplit(value)
    except Exception:
        return None
    if parts.scheme != "https":
        return None
    host = (parts.hostname or "").lower()
    if host == "civitai.com" or host.endswith(".civitai.com"):
        return value
    return None


def _download_image(url, dest_base):
    """Скачать картинку CivitAI в dest_base + <ext> (атомарно). Путь или None."""
    safe_url = _allowed_image_url(url)
    if not safe_url or not dest_base:
        return None
    ext = _image_ext_from_url(safe_url)
    raw = b""
    try:
        request = urllib.request.Request(
            safe_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read()
            if not ext:
                content_type = ""
                headers = getattr(response, "headers", None)
                if headers is not None:
                    try:
                        content_type = headers.get_content_type()
                    except Exception:
                        content_type = ""
                ext = CONTENT_TYPE_EXTS.get(content_type, "")
    except Exception:
        return None
    if not raw or not ext:
        return None
    path = dest_base + ext
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as handle:
            handle.write(raw)
        os.replace(tmp_path, path)
    except Exception:
        return None
    return path


def thumb_index(raw):
    try:
        idx = int(str(raw).strip())
    except Exception:
        return 0
    return idx if idx > 0 else 0


def thumb_cache_base(safe_name, idx=0):
    """Базовый путь файла кэша превью (без расширения) или None."""
    root = cache_root()
    if not root:
        return None
    return os.path.join(root, IMAGE_CACHE_DIR_NAME,
                        _cache_key(safe_name) + ".i%d" % idx)


def cached_thumb_path(safe_name, idx=0):
    base = thumb_cache_base(safe_name, idx)
    if not base:
        return None
    for ext in IMAGE_EXTS:
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    return None


def thumb_url(info, idx=0):
    """URL картинки с индексом idx из данных /info (только разрешённый хост)."""
    if not isinstance(info, dict):
        return None
    images = info.get("images")
    if not isinstance(images, list) or idx < 0 or idx >= len(images):
        return None
    entry = images[idx]
    if not isinstance(entry, dict):
        return None
    return _allowed_image_url(entry.get("url"))


def _sha256(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except Exception:
        return None
    return digest.hexdigest()


def civitai_page_url(model_id, version_id=None):
    """Ссылка на страницу модели CivitAI: modelId (и версия, если есть).

    Живой /model-versions/by-hash поля permalink не содержит, зато отдаёт
    modelId и id версии — из них и собирается кликабельная ссылка.
    """
    if isinstance(model_id, bool) or model_id is None:
        return None
    try:
        model = int(model_id)
    except Exception:
        return None
    if model <= 0:
        return None
    url = "https://civitai.com/models/%d" % model
    if isinstance(version_id, bool) or version_id is None:
        return url
    try:
        version = int(version_id)
    except Exception:
        return url
    if version > 0:
        url += "?modelVersionId=%d" % version
    return url


def _normalize_civitai(data, filename):
    if not isinstance(data, dict):
        return None
    model = data.get("model")
    if not isinstance(model, dict):
        model = {}
    name = model.get("name")
    if not isinstance(name, str) or not name.strip():
        name = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    base_model = data.get("baseModel")
    if not isinstance(base_model, str):
        base_model = ""
    trained = data.get("trainedWords")
    if isinstance(trained, list):
        trigger = [str(w) for w in trained]
    else:
        trigger = []
    description = _strip_html(data.get("description"))
    files = data.get("files")
    file_url = None
    if isinstance(files, list) and files and isinstance(files[0], dict):
        candidate = files[0].get("downloadUrl")
        if isinstance(candidate, str):
            file_url = candidate
    permalink = data.get("permalink")
    if not isinstance(permalink, str) or not permalink:
        permalink = civitai_page_url(data.get("modelId"), data.get("id"))
    images = []
    raw_images = data.get("images")
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, dict) and isinstance(img.get("url"), str):
                images.append(dict(img))
    return {
        "ok": True,
        "name": name,
        "baseModel": base_model,
        "trigger": trigger,
        "description": description,
        "fileUrl": file_url,
        "permalink": permalink,
        "images": images,
    }


def get_lora_info(lora_name, refresh=False):
    """Данные CivitAI для лоры: дисковый кэш доверенный, HTTP — только по нужде.

    Никакого «первого принудительного refresh после рестарта»: он считал sha256
    ВСЕГО файла лоры + ходил в CivitAI для каждой лоры при каждом открытии
    страницы, хотя на диске уже лежал валидный кэш.
    """
    safe = safe_lora_name(lora_name)
    if not safe:
        return None
    full = _lora_full_path(safe)
    if not full or not os.path.isfile(full):
        return None
    root = cache_root()
    if not root:
        return None
    cache_path = os.path.join(
        root, _cache_key(safe) + "." + CACHE_VERSION + ".json")
    if not refresh:
        cached = _read_json(cache_path)
        if isinstance(cached, dict) and _cache_is_fresh(cached, full):
            return cached if cached.get("ok") else None
    digest = _sha256(full)
    if not digest:
        return None
    state, data = _fetch_civitai_info(digest)
    if state == "ok":
        info = _normalize_civitai(data, safe)
        if info is not None:
            info["stamp"] = _file_stamp(full)
            _write_json(cache_path, info)
            return info
        state = "error"
    if state == "not-found":
        _write_json(cache_path, {
            "ok": False,
            "reason": "not-found",
            "stamp": _file_stamp(full),
        })
    return None


class DeggLoraLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "loras_data": ("STRING", {
                    "default": "[]",
                    "tooltip": "JSON list of LoRAs with on/off and strengths",
                }),
            },
            "optional": {
                "model": ("MODEL", {"tooltip": "Model chain to apply LoRAs to"}),
                "clip": ("CLIP", {"tooltip": "Clip chain to apply LoRAs to"}),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP")
    RETURN_NAMES = ("model", "clip")
    FUNCTION = "load_loras"
    CATEGORY = "My_custom_nodes/LoRA"
    DESCRIPTION = (
        "Apply a list of LoRAs from JSON with on/off and strengths, "
        "with folder previews and CivitAI details."
    )

    def load_loras(self, model=None, clip=None, loras_data="[]"):
        return apply_loras(model, clip, loras_data)


NODE_CLASS_MAPPINGS = {NODE_KEY: DeggLoraLoader}
NODE_DISPLAY_NAME_MAPPINGS = {NODE_KEY: "Degg LoRa Loader"}
WEB_DIRECTORY = "web"

_ROUTES_DONE = False


def catalog_items():
    """Список лор из models/loras + URL картинки-соседа (или None)."""
    try:
        import folder_paths
        names = folder_paths.get_filename_list("loras")
    except Exception:
        names = []
    items = []
    for name in names:
        preview = sibling_image_path(name)
        if preview:
            image = "/degg_lora_loader/img?file=" + urllib.parse.quote(
                name, safe="")
        else:
            image = None
        items.append({"name": name, "image": image})
    return items


def register_routes():
    global _ROUTES_DONE
    if _ROUTES_DONE:
        return
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return
    instance = getattr(PromptServer, "instance", None)
    routes = getattr(instance, "routes", None)
    if routes is None:
        return

    def thumb_response(request, path):
        """Файл превью с ETag: браузер перевалидирует (304), а не качает снова."""
        headers = {"Cache-Control": "no-cache"}
        stamp = _file_stamp(path)
        etag = '"%x-%x"' % (stamp[0], stamp[1]) if stamp else None
        if etag:
            headers["ETag"] = etag
        inm = None
        try:
            inm = request.headers.get("If-None-Match")
        except Exception:
            inm = None
        if etag and isinstance(inm, str) and inm.strip() == etag:
            return web.Response(status=304, headers=headers)
        return web.FileResponse(path, headers=headers)

    @routes.get("/degg_lora_loader/loras")
    async def handle_loras(request):
        items = await asyncio.to_thread(catalog_items)
        names = [item["name"] for item in items]
        await asyncio.to_thread(run_gc, names)
        return web.json_response({"loras": items}, status=200)

    @routes.get("/degg_lora_loader/img")
    async def handle_img(request):
        raw_name = request.query.get("file") or ""
        safe = safe_lora_name(raw_name)
        if not safe:
            return web.json_response({"error": "bad name"}, status=400)
        preview = sibling_image_path(safe)
        if preview is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.FileResponse(preview)

    @routes.get("/degg_lora_loader/thumb")
    async def handle_thumb(request):
        """Превью лоры: соседний файл → дисковый кэш → скачать из CivitAI.

        Один раз скачали — дальше браузер получает картинку с диска (и 304 по
        ETag), а не тянет CDN при каждом открытии страницы.
        """
        raw_name = request.query.get("file") or ""
        safe = safe_lora_name(raw_name)
        if not safe:
            return web.json_response({"error": "bad name"}, status=400)
        idx = thumb_index(request.query.get("idx"))
        refresh = _flag(request.query.get("refresh"), False)
        if idx == 0:
            preview = await asyncio.to_thread(sibling_image_path, safe)
            if preview:
                return thumb_response(request, preview)
        if not refresh:
            cached = await asyncio.to_thread(cached_thumb_path, safe, idx)
            if cached:
                await asyncio.to_thread(touch_thumb, cached)
                await asyncio.to_thread(ttl_sweep)
                return thumb_response(request, cached)
        async with _heavy_semaphore():
            info = await asyncio.to_thread(get_lora_info, safe)
            url = thumb_url(info, idx)
            if url:
                base = await asyncio.to_thread(thumb_cache_base, safe, idx)
                if base:
                    path = await asyncio.to_thread(_download_image, url, base)
                    if path:
                        return thumb_response(request, path)
        return web.json_response({"error": "not found"}, status=404)

    @routes.get("/degg_lora_loader/info")
    async def handle_info(request):
        raw_name = request.query.get("file") or ""
        safe = safe_lora_name(raw_name)
        if not safe:
            return web.json_response({"error": "not found"}, status=404)
        refresh = _flag(request.query.get("refresh"), False)
        async with _heavy_semaphore():
            info = await asyncio.to_thread(get_lora_info, safe, refresh)
        if refresh:
            # Ручное обновление — сбрасываем и картинку, иначе превью останется старым.
            await asyncio.to_thread(drop_thumb_cache, safe)
        if info is None:
            return web.json_response({"error": "not found"}, status=404)
        payload = dict(info)
        preview = await asyncio.to_thread(sibling_image_path, safe)
        if preview:
            payload["localImage"] = "/degg_lora_loader/img?file=" + \
                urllib.parse.quote(safe, safe="")
        else:
            payload["localImage"] = None
        return web.json_response(payload, status=200)

    _ROUTES_DONE = True


register_routes()
