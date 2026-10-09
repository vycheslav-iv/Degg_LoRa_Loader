"""Degg LoRa Loader — apply a JSON list of LoRAs with on/off and strengths.

Python side of the node: parsing the persisted loras_data JSON, applying
LoRAs through nodes.LoraLoader, sibling preview lookup, CivitAI info cache
and the three HTTP routes used by the DOM frontend.
"""

import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request

NODE_KEY = "Degg_LoRa_Loader"

CIVITAI_BY_HASH = "https://civitai.com/api/v1/model-versions/by-hash/"
CACHE_DIR_NAME = "degg_lora_cache"
HTTP_TIMEOUT = 10
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


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
    request = urllib.request.Request(
        url, headers={"User-Agent": "DeggLoRaLoader/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _sha256(path):
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except Exception:
        return None
    return digest.hexdigest()


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
    if not isinstance(permalink, str):
        permalink = None
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
    safe = safe_lora_name(lora_name)
    if not safe:
        return None
    try:
        import folder_paths
        full = folder_paths.get_full_path("loras", safe)
    except Exception:
        full = None
    if not full or not os.path.isfile(full):
        return None
    cache_key = hashlib.sha256(safe.encode("utf-8")).hexdigest()
    try:
        cache_dir = os.path.join(
            folder_paths.get_user_directory(), "default", CACHE_DIR_NAME)
    except Exception:
        return None
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return None
    cache_path = os.path.join(cache_dir, cache_key + ".json")
    if not refresh and os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if isinstance(cached, dict) and cached.get("ok"):
                return cached
        except Exception:
            pass
    digest = _sha256(full)
    if not digest:
        return None
    url = CIVITAI_BY_HASH + digest
    try:
        raw = _http_get_json(url, timeout=HTTP_TIMEOUT)
    except Exception:
        return None
    info = _normalize_civitai(raw, safe)
    if info is None:
        return None
    try:
        tmp_path = cache_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(info, handle, ensure_ascii=False)
        os.replace(tmp_path, cache_path)
    except Exception:
        pass
    return info


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
    seen = set()

    @routes.get("/degg_lora_loader/loras")
    async def handle_loras(request):
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

    @routes.get("/degg_lora_loader/info")
    async def handle_info(request):
        raw_name = request.query.get("file") or ""
        safe = safe_lora_name(raw_name)
        if not safe:
            return web.json_response({"error": "not found"}, status=404)
        refresh_raw = str(request.query.get("refresh") or "").strip().lower()
        refresh = refresh_raw in ("1", "true", "yes", "on")
        if refresh:
            info = get_lora_info(safe, refresh=True)
        elif safe in seen:
            info = get_lora_info(safe)
        else:
            info = get_lora_info(safe, refresh=True)
        if info is None and not refresh:
            info = get_lora_info(safe)
        if info is None:
            return web.json_response({"error": "not found"}, status=404)
        seen.add(safe)
        payload = dict(info)
        preview = sibling_image_path(safe)
        if preview:
            payload["localImage"] = "/degg_lora_loader/img?file=" + \
                urllib.parse.quote(safe, safe="")
        else:
            payload["localImage"] = None
        return web.json_response(payload, status=200)

    _ROUTES_DONE = True


register_routes()
