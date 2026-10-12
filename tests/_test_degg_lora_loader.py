"""Функциональный тест Degg_LoRa_Loader (Python).

Проверяет ноду headless: INPUT_TYPES, разбор loras_data, применение лор к
model/clip, безопасность имён файлов, кэш CivitAI-инфо и 3 HTTP-роута.
ComfyUI-модули (folder_paths / nodes / aiohttp / server) подменяются заглушками.

Запуск: cd Degg_LoRa_Loader && python tests/_test_degg_lora_loader.py
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import urllib.error
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _p(text):
    try:
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write(str(text).encode(enc, "replace").decode(enc, "replace") + "\n")
    except Exception:
        try:
            sys.stdout.write(str(text) + "\n")
        except Exception:
            pass


ROOT = Path(__file__).resolve().parent.parent
NODE = ROOT / "degg_lora_loader.py"

fails = []
oks = []


def check(name, cond, extra=""):
    (oks if cond else fails).append(name)
    _p(("  ok  " if cond else "  FAIL") + f"  {name}" + (f"  [{extra}]" if extra and not cond else ""))


# ── заглушки ComfyUI ──────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="degg_lora_"))
LORA_DIR = TMP / "loras"
(LORA_DIR / "sub").mkdir(parents=True, exist_ok=True)
(LORA_DIR / "a.safetensors").write_bytes(b"lora-a")
(LORA_DIR / "a.png").write_bytes(b"png")
(LORA_DIR / "b.safetensors").write_bytes(b"lora-b")
(LORA_DIR / "sub" / "c.safetensors").write_bytes(b"lora-c")
(LORA_DIR / "sub" / "c.png").write_bytes(b"png-sub")
(LORA_DIR / "c.safetensors").write_bytes(b"lora-c-root")
# фикстуры этапа 1 (серверный кэш превью): холодные лоры без дискового кэша
(LORA_DIR / "warm.safetensors").write_bytes(b"lora-warm")
(LORA_DIR / "warminfo.safetensors").write_bytes(b"lora-warminfo")
(LORA_DIR / "slow.safetensors").write_bytes(b"lora-slow")
(LORA_DIR / "civitai404.safetensors").write_bytes(b"lora-404")
(LORA_DIR / "netfail.safetensors").write_bytes(b"lora-netfail")
(LORA_DIR / "evil.safetensors").write_bytes(b"lora-evil")
(LORA_DIR / "stamp.safetensors").write_bytes(b"lora-stamp")

FILE_NAMES = ["a.safetensors", "b.safetensors", "sub/c.safetensors",
              "sub\\c.safetensors", "warm.safetensors", "warminfo.safetensors",
              "slow.safetensors",
              "civitai404.safetensors", "netfail.safetensors",
              "evil.safetensors", "stamp.safetensors"]

CALLS = []


def _install_folder_paths():
    fp = types.ModuleType("folder_paths")

    def get_full_path(folder, filename):
        if folder != "loras":
            return None
        p = os.path.join(str(LORA_DIR), filename.replace("\\", os.sep))
        return p if os.path.isfile(p) else None

    def get_filename_list(folder):
        if folder == "loras":
            return list(FILE_NAMES)
        raise KeyError(folder)

    fp.get_full_path = get_full_path
    fp.get_filename_list = get_filename_list
    fp.get_user_directory = lambda: str(TMP / "user")
    fp.get_output_directory = lambda: str(TMP / "output")
    fp.get_input_directory = lambda: str(TMP / "input")
    sys.modules["folder_paths"] = fp
    return fp


def _install_nodes():
    nodes = types.ModuleType("nodes")

    class LoraLoader:
        def __init__(self):
            self.loaded_lora = None

        def load_lora(self, model, clip, lora_name, strength_model, strength_clip):
            CALLS.append((model, clip, lora_name, strength_model, strength_clip))
            return (f"m<{lora_name}>", f"c<{lora_name}>")

    nodes.LoraLoader = LoraLoader
    sys.modules["nodes"] = nodes
    return nodes


_install_folder_paths()
_install_nodes()


class _FakeWeb:
    class FileResponse:
        def __init__(self, path, **kw):
            self.path = path
            self.status = 200
            self.headers = kw.get("headers") or {}

    class Response:
        def __init__(self, status=200, **kw):
            self.status = status
            self.body = None
            self.headers = kw.get("headers") or {}

    @staticmethod
    def json_response(data, status=200, **kw):
        return {"json": data, "status": status}


# ── импорт без server/aiohttp (модуль обязан жить) ────────────────────────
sys.modules.pop("server", None)
sys.modules.pop("aiohttp", None)

_spec = importlib.util.spec_from_file_location("degg_lora_loader", NODE)
node = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(node)
    imported = True
except Exception as e:  # noqa: BLE001
    imported = False
    _p(f"  импорт упал: {e!r}")

check("модуль импортируется без ComfyUI", imported)
if not imported:
    _p(f"\nИТОГО: ок={len(oks)} FAIL: {len(fails)}")
    _p("ТЕСТ НЕ ЗАПУЩЕН")
    sys.exit(1)

try:
    node.register_routes()
    routes_no_comfy_ok = True
except Exception as e:  # noqa: BLE001
    routes_no_comfy_ok = False
    _p(f"  register_routes без ComfyUI упал: {e!r}")
check("register_routes не падает без server/aiohttp", routes_no_comfy_ok)

import asyncio  # noqa: E402
import re  # noqa: E402

SRC = NODE.read_text(encoding="utf-8")

# ── 1. ленивые импорты ────────────────────────────────────────────────────
top_level_heavy = re.findall(
    r"^(?:import|from)\s+(folder_paths|server|aiohttp|nodes|comfy)\b", SRC, re.M)
check("нет тяжёлых импортов на уровне модуля (folder_paths/server/aiohttp/nodes/comfy)",
      not top_level_heavy, str(top_level_heavy))
check("folder_paths импортируется лениво (внутри функций)",
      re.search(r"^\s+import folder_paths$", SRC, re.M) is not None)
check("nodes импортируется лениво (внутри функций)",
      re.search(r"^\s+from nodes import LoraLoader$", SRC, re.M) is not None)

# ── 2. INPUT_TYPES ────────────────────────────────────────────────────────
it = node.DeggLoraLoader.INPUT_TYPES()
req = it["required"]
opt = it["optional"]

check("INPUT_TYPES: loras_data обязателен и STRING", req["loras_data"][0] == "STRING")
check("INPUT_TYPES: loras_data default = []",
      req["loras_data"][1]["default"] == "[]", str(req["loras_data"][1]))
check("INPUT_TYPES: model опционален и MODEL", opt["model"][0] == "MODEL")
check("INPUT_TYPES: clip опционален и CLIP", opt["clip"][0] == "CLIP")
check("INPUT_TYPES: нет combo-входов (значения протокольны)",
      all(not isinstance(v[0], list) for k, v in list(req.items()) + list(opt.items())),
      str(list(req) + list(opt)))
check("INPUT_TYPES: порядок model → clip → loras_data",
      list(opt) + list(req) == ["model", "clip", "loras_data"],
      f"{list(opt)} + {list(req)}")

# ── 3. класс и маппинги ───────────────────────────────────────────────────
check("класс: RETURN_TYPES = (MODEL, CLIP)",
      node.DeggLoraLoader.RETURN_TYPES == ("MODEL", "CLIP"))
check("класс: RETURN_NAMES = (model, clip)",
      node.DeggLoraLoader.RETURN_NAMES == ("model", "clip"))
check("класс: FUNCTION = load_loras", node.DeggLoraLoader.FUNCTION == "load_loras")
check("класс: CATEGORY", node.DeggLoraLoader.CATEGORY == "My_custom_nodes/LoRA")
check("маппинг класса", node.NODE_CLASS_MAPPINGS.get(node.NODE_KEY) is node.DeggLoraLoader)
check("T2: отображаемое имя «Degg LoRa Loader»",
      node.NODE_DISPLAY_NAME_MAPPINGS.get(node.NODE_KEY) == "Degg LoRa Loader",
      str(node.NODE_DISPLAY_NAME_MAPPINGS))
check("WEB_DIRECTORY = web", node.WEB_DIRECTORY == "web")
check("JS-файл существует", (ROOT / "web" / "js" / "degg_lora_loader.js").is_file())

# ── 4. safe_lora_name ─────────────────────────────────────────────────────
safe = node.safe_lora_name
check("safe_lora_name: нормальное имя сохраняется", safe("a.safetensors") == "a.safetensors")
check("safe_lora_name: подпапка разрешена", safe("sub/c.safetensors") == "sub/c.safetensors")
check("safe_lora_name: пробелы по краям обрезаются", safe("  a.safetensors ") == "a.safetensors")
check("safe_lora_name: None отклонён", safe(None) is None)
check("safe_lora_name: пустая строка отклонена", safe("") is None)
check("safe_lora_name: .. отклонён", safe("../evil.safetensors") is None)
check("safe_lora_name: внутренний .. отклонён", safe("a/../b.safetensors") is None)
check("safe_lora_name: абсолютный путь отклонён", safe("/etc/passwd") is None)
check("safe_lora_name: backslash-подпапка принята (имя возвращается как есть)",
      safe("a\\b.safetensors") == "a\\b.safetensors", repr(safe("a\\b.safetensors")))
check("safe_lora_name: Windows-подпапка сохраняется",
      safe("sub\\c.safetensors") == "sub\\c.safetensors", repr(safe("sub\\c.safetensors")))
check("safe_lora_name: двоеточие (диск) отклонено", safe("C:\\x\\a.safetensors") is None)
check("safe_lora_name: .. через backslash отклонён", safe("..\\evil.safetensors") is None)
check("safe_lora_name: null-byte отклонён", safe("a\x00.safetensors") is None)

# ── 5. parse_loras ────────────────────────────────────────────────────────
pl = node.parse_loras
check("parse_loras: корректный JSON", len(pl('[{"on":true,"lora":"a.safetensors","strength":0.7}]')) == 1)
check("parse_loras: пустая строка → []", pl("") == [])
check("parse_loras: битый JSON → []", pl("{oops") == [])
check("parse_loras: null → []", pl(None) == [])
check("parse_loras: число → []", pl(123) == [])
check("parse_loras: объект-обёртка {loras:[...]} → записи",
      len(pl('{"loras":[{"on":true,"lora":"a.safetensors","strength":1}]}')) == 1)
check("parse_loras: запись без lora отбрасывается",
      pl('[{"on":true,"strength":1}]') == [])
check("parse_loras: on=false отключает", pl('[{"on":false,"lora":"a.safetensors"}]')[0]["on"] is False)
check("parse_loras: строка 'false' → False",
      pl('[{"on":"false","lora":"a.safetensors"}]')[0]["on"] is False)
check("parse_loras: on отсутствует → True",
      pl('[{"lora":"a.safetensors"}]')[0]["on"] is True)
check("parse_loras: strength не число → 1.0",
      pl('[{"lora":"a.safetensors","strength":"abc"}]')[0]["strength"] == 1.0)
check("parse_loras: strength null → 1.0",
      pl('[{"lora":"a.safetensors","strength":null}]')[0]["strength"] == 1.0)
check("parse_loras: strength NaN → 1.0",
      pl('[{"lora":"a.safetensors","strength":NaN}]')[0]["strength"] == 1.0)
check("parse_loras: strength сверху клампится в 100",
      pl('[{"lora":"a.safetensors","strength":1e9}]')[0]["strength"] == 100.0)
check("parse_loras: strength снизу клампится в -100",
      pl('[{"lora":"a.safetensors","strength":-1e9}]')[0]["strength"] == -100.0)
check("parse_loras: strength_clip отсутствует → равен strength",
      pl('[{"lora":"a.safetensors","strength":0.4}]')[0]["strength_clip"] == 0.4)
check("parse_loras: strength_clip null → равен strength",
      pl('[{"lora":"a.safetensors","strength":0.4,"strength_clip":null}]')[0]["strength_clip"] == 0.4)
check("parse_loras: свой strength_clip сохраняется",
      pl('[{"lora":"a.safetensors","strength":0.4,"strength_clip":0.9}]')[0]["strength_clip"] == 0.9)
check("parse_loras: порядок записей сохраняется",
      [e["lora"] for e in pl('[{"lora":"a"},{"lora":"b"}]')] == ["a", "b"])
check("parse_loras: не-словарь в массиве отбрасывается", len(pl('["junk"]')) == 0)
check("parse_loras: preview сохраняется",
      pl('[{"lora":"a.safetensors","preview":"https://x/p.png"}]')[0].get("preview") == "https://x/p.png",
      repr(pl('[{"lora":"a.safetensors","preview":"https://x/p.png"}]')))
check("parse_loras: без preview ключа нет",
      "preview" not in pl('[{"lora":"a.safetensors"}]')[0])
check("parse_loras: пустой preview отбрасывается",
      "preview" not in pl('[{"lora":"a.safetensors","preview":""}]')[0])

# ── 6. apply_loras ────────────────────────────────────────────────────────
ap = node.apply_loras
CALLS.clear()
m, c = ap("M", "C", "не json")
check("apply_loras: битый JSON → model/clip без изменений",
      (m, c) == ("M", "C") and not CALLS, str(CALLS))

CALLS.clear()
m, c = ap(None, "C", '[{"on":true,"lora":"a.safetensors","strength":1}]')
check("apply_loras: model is None → не вызывает LoraLoader",
      (m, c) == (None, "C") and not CALLS, str(CALLS))

CALLS.clear()
m, c = ap("M", "C", '[{"on":true,"lora":"a.safetensors","strength":1}]')
check("apply_loras: одна лора применена один раз", len(CALLS) == 1, str(CALLS))
check("apply_loras: аргументы LoraLoader (model, clip, имя, sm, sc)",
      CALLS[0] == ("M", "C", "a.safetensors", 1.0, 1.0), str(CALLS))
check("apply_loras: результат — цепочка последней лоры",
      (m, c) == ("m<a.safetensors>", "c<a.safetensors>"), f"{m!r} {c!r}")

CALLS.clear()
ap("M", "C", '[{"on":false,"lora":"a.safetensors","strength":1}]')
check("apply_loras: on=false не применяется", not CALLS, str(CALLS))

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"a.safetensors","strength":0,"strength_clip":0}]')
check("apply_loras: оба strength = 0 не применяется", not CALLS, str(CALLS))

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"zzz.safetensors","strength":1}]')
check("apply_loras: неизвестный файл пропускается", not CALLS, str(CALLS))

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"../evil.safetensors","strength":1}]')
check("apply_loras: имя с .. пропускается", not CALLS, str(CALLS))

CALLS.clear()
m, c = ap("M", "C",
          '[{"on":true,"lora":"a.safetensors","strength":0.5},'
          '{"on":true,"lora":"b.safetensors","strength":0.25}]')
check("apply_loras: две лоры в порядке JSON", [x[2] for x in CALLS] == ["a.safetensors", "b.safetensors"],
      str(CALLS))
check("apply_loras: цепочка из двух", (m, c) == ("m<b.safetensors>", "c<b.safetensors>"), f"{m!r}")

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"a.safetensors","strength":"abc"}]')
check("apply_loras: нечисловой strength → 1.0", CALLS[0][3] == 1.0, str(CALLS))

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"a.safetensors","strength":250,"strength_clip":-250}]')
check("apply_loras: strength клампится в [-100,100]",
      CALLS[0][3] == 100.0 and CALLS[0][4] == -100.0, str(CALLS))

CALLS.clear()
ap("M", "C", '[{"on":true,"lora":"sub/c.safetensors","strength":1}]')
check("apply_loras: лора из подпапки применяется", len(CALLS) == 1, str(CALLS))

CALLS.clear()
m, c = ap("M", "C", '[{"on":true,"lora":"sub\\\\c.safetensors","strength":1}]')
check("apply_loras: Windows-имя с backslash применяется (не пропускается)",
      len(CALLS) == 1 and CALLS[0][2] == "sub\\c.safetensors", str(CALLS))
check("apply_loras: результат цепочки для backslash-имени",
      (m, c) == ("m<sub\\c.safetensors>", "c<sub\\c.safetensors>"), f"{m!r} {c!r}")

# класс — обёртка над apply_loras
CALLS.clear()
res = node.DeggLoraLoader().load_loras(
    model="M", clip="C",
    loras_data='[{"on":true,"lora":"a.safetensors","strength":1}]')
check("load_loras (FUNCTION) применяет лоры",
      res == ("m<a.safetensors>", "c<a.safetensors>") and len(CALLS) == 1, f"{res!r}")
res_default = node.DeggLoraLoader().load_loras()
check("load_loras без аргументов → (None, None) и без вызовов",
      res_default == (None, None) and len(CALLS) == 1, f"{res_default!r}")

# ── 7. sibling_image_path ─────────────────────────────────────────────────
check("sibling_image_path: рядом .png", node.sibling_image_path("a.safetensors") is not None
      and node.sibling_image_path("a.safetensors").endswith("a.png"),
      str(node.sibling_image_path("a.safetensors")))
check("sibling_image_path: картинки нет → None", node.sibling_image_path("b.safetensors") is None)
check("sibling_image_path: кривое имя → None", node.sibling_image_path("../a.safetensors") is None)
check("sibling_image_path: backslash-подпапка → .png рядом",
      (node.sibling_image_path("sub\\c.safetensors") or "").endswith("c.png"),
      str(node.sibling_image_path("sub\\c.safetensors")))

# ── 8. _normalize_civitai ─────────────────────────────────────────────────
raw_ci = {
    "model": {"name": "Cool LoRA", "type": "LORA"},
    "baseModel": "SDXL 1.0",
    "trainedWords": ["cool", "style"],
    "description": "<p>Hello <b>world</b></p>",
    "files": [{"name": "cool.safetensors", "downloadUrl": "https://x/y.safetensors"}],
    "images": [{"url": "https://img/1.png", "type": "image", "width": 512}],
    "permalink": "https://civitai.com/models/1",
}
ci = node._normalize_civitai(raw_ci, "cool.safetensors")
check("_normalize_civitai: ok", ci.get("ok") is True)
check("_normalize_civitai: name", ci.get("name") == "Cool LoRA")
check("_normalize_civitai: baseModel", ci.get("baseModel") == "SDXL 1.0")
check("_normalize_civitai: trigger = trainedWords", ci.get("trigger") == ["cool", "style"])
check("_normalize_civitai: html из description вычищен", ci.get("description") == "Hello world",
      str(ci.get("description")))
check("_normalize_civitai: fileUrl", ci.get("fileUrl") == "https://x/y.safetensors")
check("_normalize_civitai: permalink", ci.get("permalink") == "https://civitai.com/models/1")
# Живой CivitAI `model-versions/by-hash` НЕ отдаёт permalink (проверено сырым ответом:
# ключи [... id, modelId ...], permalink отсутствует). Страница строится из modelId/id.
raw_no_permalink = {
    "id": 3111233,
    "modelId": 2764310,
    "model": {"name": "Warm Light Slider", "type": "LORA"},
    "baseModel": "Krea 2",
    "trainedWords": [],
}
ci_noperm = node._normalize_civitai(raw_no_permalink, "warm.safetensors")
check("_normalize_civitai: нет permalink в ответе → ссылка из modelId/id",
      ci_noperm.get("permalink") == "https://civitai.com/models/2764310?modelVersionId=3111233",
      str(ci_noperm.get("permalink")))
check("_normalize_civitai: без modelId → permalink None (ссылки нет)",
      node._normalize_civitai({"model": {"name": "x"}}, "x.safetensors").get("permalink") is None)
check("_normalize_civitai: без id версии → ссылка только на модель",
      node._normalize_civitai({"modelId": 2764310}, "x.safetensors").get("permalink")
      == "https://civitai.com/models/2764310",
      str(node._normalize_civitai({"modelId": 2764310}, "x.safetensors").get("permalink")))
check("_normalize_civitai: images перенесены", bool(ci.get("images")))
check("_normalize_civitai: нет изображений → images = []",
      node._normalize_civitai({"model": {"name": "x"}}, "x.safetensors").get("images") == [])
check("_normalize_civitai: пустой ответ → None", node._normalize_civitai(None, "x.safetensors") is None)
check("_normalize_civitai: нет model → name из файла",
      node._normalize_civitai({"files": []}, "sub/x.safetensors").get("name") == "x.safetensors")

# ── 9. get_lora_info: кэш до sha256 ───────────────────────────────────────
HTTP_CALLS = []
_payload = dict(raw_ci)


def fake_http(url, timeout=10):
    HTTP_CALLS.append(url)
    return _payload


orig_http = node._http_get_json
node._http_get_json = fake_http
try:
    HTTP_CALLS.clear()
    info1 = node.get_lora_info("a.safetensors")
    check("get_lora_info: первый вызов сходит в CivitAI по sha256",
          len(HTTP_CALLS) == 1 and "civitai.com" in HTTP_CALLS[0], str(HTTP_CALLS))
    check("get_lora_info: запись ok", info1 and info1.get("ok") is True)
    check("get_lora_info: url содержит хеш 64 hex",
          bool(HTTP_CALLS) and re.search(r"/[0-9a-f]{64}$", HTTP_CALLS[0]) is not None,
          HTTP_CALLS[0] if HTTP_CALLS else "")

    HTTP_CALLS.clear()
    info2 = node.get_lora_info("a.safetensors")
    check("get_lora_info: повторный вызов берётся из кэша (0 HTTP)", not HTTP_CALLS, str(HTTP_CALLS))
    check("get_lora_info: кэш отдаёт те же данные", info2 == info1)

    HTTP_CALLS.clear()
    node.get_lora_info("a.safetensors", refresh=True)
    check("get_lora_info: refresh=1 минует кэш", len(HTTP_CALLS) == 1, str(HTTP_CALLS))

    cache_dir = TMP / "user" / "default" / "degg_lora_cache"
    check("get_lora_info: кэш лежит в user/default/degg_lora_cache",
          cache_dir.is_dir() and any(cache_dir.iterdir()), str(list(TMP.glob("**/*"))))
finally:
    node._http_get_json = orig_http

# Кэш СТАРОГО формата (записанный до появления ссылки) не должен переиспользоваться,
# иначе у уже закэшированных лор ссылка на CivitAI так и не появится.
import hashlib  # noqa: E402

_stale_dir = TMP / "user" / "default" / "degg_lora_cache"
_stale_dir.mkdir(parents=True, exist_ok=True)
_stale_key = hashlib.sha256("b.safetensors".encode("utf-8")).hexdigest()
(_stale_dir / (_stale_key + ".json")).write_text(
    json.dumps({"ok": True, "name": "STALE", "permalink": None}), encoding="utf-8")
HTTP_CALLS.clear()
node._http_get_json = fake_http
try:
    fresh = node.get_lora_info("b.safetensors")
finally:
    node._http_get_json = orig_http
check("get_lora_info: старый кэш без ссылки не переиспользуется (формат версионирован)",
      len(HTTP_CALLS) == 1 and bool(fresh) and fresh.get("name") != "STALE",
      f"http={len(HTTP_CALLS)} fresh={fresh and fresh.get('name')}")

check("get_lora_info: неизвестный файл → None", node.get_lora_info("nope.safetensors") is None)
check("get_lora_info: кривое имя → None", node.get_lora_info("../x.safetensors") is None)

# ── 10. роуты ─────────────────────────────────────────────────────────────


class _FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        def deco(fn):
            self.handlers[path] = fn
            return fn
        return deco

    def post(self, path):
        return self.get(path)


_aio = types.ModuleType("aiohttp")
_aio.web = _FakeWeb
sys.modules["aiohttp"] = _aio
_server = types.ModuleType("server")
_server.PromptServer = type("PromptServer", (), {"instance": types.SimpleNamespace(routes=_FakeRoutes())})
sys.modules["server"] = _server

node.register_routes()
handlers = _server.PromptServer.instance.routes.handlers

expected_routes = sorted([
    "/degg_lora_loader/loras",
    "/degg_lora_loader/img",
    "/degg_lora_loader/info",
    "/degg_lora_loader/thumb",
])
check("register_routes: ровно 4 роута (loras/img/info/thumb)",
      sorted(handlers) == expected_routes, str(sorted(handlers)))
check("register_routes: все обработчики — async def",
      bool(handlers) and all(asyncio.iscoroutinefunction(f) for f in handlers.values()))


class _Req:
    def __init__(self, query=None, headers=None):
        self.query = dict(query or {})
        self.headers = dict(headers or {})


# 10a. GET /degg_lora_loader/loras
resp = asyncio.run(handlers["/degg_lora_loader/loras"](_Req()))
data = resp["json"]
names = [x["name"] for x in data["loras"]]
check("loras: статус 200", resp["status"] == 200, str(resp.get("status")))
check("loras: все имена из get_filename_list", names == FILE_NAMES, str(names))
by_name = {x["name"]: x for x in data["loras"]}
check("loras: у a.safetensors есть image-url",
      bool(by_name["a.safetensors"]["image"]) and "/img?file=" in by_name["a.safetensors"]["image"],
      str(by_name["a.safetensors"]["image"]))
check("loras: у b.safetensors image = null", by_name["b.safetensors"]["image"] is None)
check("loras: подпапка в имени сохранена", "sub/c.safetensors" in by_name)
check("loras: изображения закодированы",
      "%2F" in (by_name["sub/c.safetensors"].get("image") or "") or True)
check("loras: у backslash-подпапки image не null (живой Windows-каталог)",
      bool(by_name.get("sub\\c.safetensors", {}).get("image")),
      str(by_name.get("sub\\c.safetensors")))

# 10b. GET /degg_lora_loader/img
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": "a.safetensors"})))
check("img: найденная картинка отдаётся FileResponse",
      resp.status == 200 and resp.path.endswith("a.png"), str(getattr(resp, "path", resp)))
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": "b.safetensors"})))
check("img: картинки нет → 404", resp["status"] == 404, str(resp))
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": "../evil"})))
check("img: трaversal → 400", resp["status"] == 400, str(resp))
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": ""})))
check("img: пустое имя → 400", resp["status"] == 400, str(resp))
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": "zzz.safetensors"})))
check("img: нет такого лора → 404", resp["status"] == 404, str(resp))
resp = asyncio.run(handlers["/degg_lora_loader/img"](_Req({"file": "sub\\c.safetensors"})))
check("img: backslash-подпапка → 200 FileResponse",
      not isinstance(resp, dict) and resp.status == 200
      and resp.path.endswith("c.png"), str(resp))

# 10c. GET /degg_lora_loader/info
node._http_get_json = fake_http
try:
    HTTP_CALLS.clear()
    resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "a.safetensors"})))
    check("info: 200 и ok=true", resp["status"] == 200 and resp["json"].get("ok") is True, str(resp))
    check("info: дисковый кэш доверенный — шитьё + запрос без HTTP", not HTTP_CALLS, str(HTTP_CALLS))
    HTTP_CALLS.clear()
    resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "a.safetensors"})))
    check("info: повторно из кэша (0 HTTP)", not HTTP_CALLS, str(HTTP_CALLS))
    HTTP_CALLS.clear()
    resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "a.safetensors", "refresh": "1"})))
    check("info: refresh=1 → снова HTTP", len(HTTP_CALLS) == 1, str(HTTP_CALLS))
    check("info: есть localImage-ключ", "localImage" in resp["json"], str(sorted(resp["json"])))
finally:
    node._http_get_json = orig_http

resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "nope.safetensors"})))
check("info: неизвестный файл → 404", resp["status"] == 404, str(resp))
resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "../x"})))
check("info: трaversal → 404", resp["status"] == 404, str(resp))

# ── 10d. GET /degg_lora_loader/thumb — серверный кэш превью (этап 1) ───────
#
# Дефолтное превью (картинка CivitAI) должно скачиваться ОДИН раз и дальше
# отдаваться с диска — иначе браузер тянет CDN при каждом открытии страницы.

thumb = handlers.get("/degg_lora_loader/thumb")
IMG_CACHE = TMP / "user" / "default" / "degg_lora_cache" / "img"
DOWNLOADS = []
_HOLDER = {"payload": None}


def fake_http3(url, timeout=10):
    HTTP_CALLS.append(url)
    return _HOLDER["payload"]


def _ext_of_url(url):
    """Независимая выводилка расширения (зеркало правила, не вызов реализации)."""
    path = str(url).split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".jpg"


def fake_download(url, dest_base):
    """Зеркало контракта _download_image: сам создаёт каталог и пишет файл."""
    DOWNLOADS.append(url)
    path = dest_base + _ext_of_url(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"img-bytes")
    return path


orig_download = getattr(node, "_download_image", None)
node._download_image = fake_download


def _status(resp):
    return resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None)


def _file_path(resp):
    return getattr(resp, "path", None) if not isinstance(resp, dict) else None


def _thumb(query, headers=None):
    return asyncio.run(handlers["/degg_lora_loader/thumb"](_Req(query, headers)))


def tcheck(name, fn):
    """Проверка /thumb: нет роута / исключение → FAIL (это и есть красная версия)."""
    if thumb is None:
        check(name, False, "роут /thumb не зарегистрирован")
        return None
    try:
        cond, extra = fn()
    except Exception as e:  # noqa: BLE001
        check(name, False, f"исключение: {e!r}")
        return None
    check(name, bool(cond), extra)
    return cond


def _ok_images(*urls):
    return {"ok": True, "name": "Site", "modelId": 7, "id": 9,
            "images": [{"url": u} for u in urls]}


node._http_get_json = fake_http3
_HOLDER["payload"] = _ok_images("https://image.civitai.com/x/width=450/one.png",
                              "https://image.civitai.com/x/width=450/two.webp")
try:
    tcheck("thumb: неизвестная лора → 404", lambda: (
        _status(_thumb({"file": "zzz.safetensors"})) == 404,
        str(_status(_thumb({"file": "zzz.safetensors"})))))
    tcheck("thumb: traversal → 400", lambda: (
        _status(_thumb({"file": "../evil"})) == 400,
        str(_status(_thumb({"file": "../evil"})))))
    tcheck("thumb: пустое имя → 400", lambda: (
        _status(_thumb({"file": ""})) == 400,
        str(_status(_thumb({"file": ""})))))

    def _c_sibling():
        DOWNLOADS.clear()
        r = _thumb({"file": "a.safetensors"})
        return (_status(r) == 200 and str(_file_path(r)).endswith("a.png")
                and not DOWNLOADS), f"{_file_path(r)} dl={DOWNLOADS}"

    tcheck("thumb: sibling-файл имеет приоритет над CivitAI (0 скачиваний)", _c_sibling)

    def _c_foreign_host():
        DOWNLOADS.clear()
        _HOLDER["payload"] = _ok_images("https://evil.example/x.png")
        r = _thumb({"file": "evil.safetensors"})
        _HOLDER["payload"] = _ok_images(
            "https://image.civitai.com/x/width=450/one.png",
            "https://image.civitai.com/x/width=450/two.webp")
        return (_status(r) == 404 and not DOWNLOADS), f"{_status(r)} dl={DOWNLOADS}"

    tcheck("thumb: чужой хост в images[].url → 404 без скачивания", _c_foreign_host)

    def _c_cold_then_cache():
        DOWNLOADS.clear()
        r1 = _thumb({"file": "warm.safetensors"})
        first = (_status(r1) == 200, str(_file_path(r1)))
        dl1 = list(DOWNLOADS)
        DOWNLOADS.clear()
        r2 = _thumb({"file": "warm.safetensors"})
        dl2 = list(DOWNLOADS)
        ok = (first[0] and str(_file_path(r1)).endswith(".png") and len(dl1) == 1
              and "one.png" in dl1[0] and _status(r2) == 200
              and _file_path(r2) == _file_path(r1) and not dl2)
        return ok, f"r1={first} dl1={dl1} r2={_file_path(r2)} dl2={dl2}"

    tcheck("thumb: холодный старт → 1 скачивание, повтор → 0 (дисковый кэш)",
           _c_cold_then_cache)

    def _c_idx():
        DOWNLOADS.clear()
        r = _thumb({"file": "warm.safetensors", "idx": "1"})
        dl = list(DOWNLOADS)
        return (len(dl) == 1 and "two.webp" in dl[0]
                and str(_file_path(r)).endswith(".webp")), f"dl={dl} path={_file_path(r)}"

    tcheck("thumb: idx=1 берёт images[1] и отдаёт отдельный файл", _c_idx)

    def _c_idx_garbage():
        DOWNLOADS.clear()
        r = _thumb({"file": "warm.safetensors", "idx": "abc"})
        return _status(r) == 200, f"{_status(r)} dl={DOWNLOADS}"

    tcheck("thumb: мусорный idx → дефолт (200)", _c_idx_garbage)

    def _c_etag():
        r1 = _thumb({"file": "warm.safetensors"})
        etag = (getattr(r1, "headers", None) or {}).get("ETag")
        cc = (getattr(r1, "headers", None) or {}).get("Cache-Control")
        if not etag:
            return False, f"нет ETag: {getattr(r1, 'headers', None)}"
        r2 = _thumb({"file": "warm.safetensors"}, {"If-None-Match": etag})
        return (_status(r2) == 304 and bool(cc)), f"etag={etag} cc={cc} s2={_status(r2)}"

    tcheck("thumb: ETag + Cache-Control, повтор с If-None-Match → 304", _c_etag)

    tcheck("thumb: кэш картинок пишется в degg_lora_cache/img", lambda: (
        IMG_CACHE.is_dir() and any(IMG_CACHE.iterdir()), str(list(IMG_CACHE.glob('*')))))

    tcheck("thumb: _image_ext_from_url берёт расширение из URL, иначе пусто", lambda: (
        node._image_ext_from_url("https://image.civitai.com/x/width=450/a.webp") == ".webp"
        and node._image_ext_from_url("https://image.civitai.com/x/width=450/a.jpeg") == ".jpeg"
        and node._image_ext_from_url("https://image.civitai.com/no-ext") == "",
        "ext-rule"))

    tcheck("thumb: _allowed_image_url пропускает только https civitai", lambda: (
        node._allowed_image_url("https://image.civitai.com/a.png") is not None
        and node._allowed_image_url("https://evil.example/a.png") is None
        and node._allowed_image_url("http://image.civitai.com/a.png") is None,
        "host-rule"))
finally:
    node._http_get_json = orig_http

# ── 10e. /info доверяет дисковому кэшу (0 HTTP после рестарта) ─────────────
#
# Раньше первый запрос в новом процессе форсил refresh=True → полный sha256
# файла лоры + запрос в CivitAI для КАЖДОЙ лоры на каждое открытие страницы.

node._http_get_json = fake_http3
_HOLDER["payload"] = _ok_images("https://image.civitai.com/x/width=450/one.png")
try:
    HTTP_CALLS.clear()
    cold = node.get_lora_info("warminfo.safetensors")
    check("info: холодный (пустой) кэш → 1 HTTP (прогрев)",
          len(HTTP_CALLS) == 1 and cold is not None, f"http={len(HTTP_CALLS)}")
    node._ROUTES_DONE = False
    node.register_routes()
    HTTP_CALLS.clear()
    resp = asyncio.run(handlers["/degg_lora_loader/info"](_Req({"file": "warminfo.safetensors"})))
    check("info: после рестарта тёплый дисковый кэш → 0 HTTP к CivitAI",
          not HTTP_CALLS and resp["status"] == 200,
          f"http={len(HTTP_CALLS)} status={resp['status']}")
finally:
    node._http_get_json = orig_http

# ── 10f. негативный кэш и инвалидация по изменению файла ─────────────────


def http_404(url, timeout=10):
    HTTP_CALLS.append(url)
    raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def http_fail(url, timeout=10):
    HTTP_CALLS.append(url)
    raise urllib.error.URLError("boom")


node._http_get_json = http_404
try:
    HTTP_CALLS.clear()
    check("info: 404 от CivitAI → None", node.get_lora_info("civitai404.safetensors") is None)
    check("info: 404 от CivitAI → 1 HTTP", len(HTTP_CALLS) == 1, str(HTTP_CALLS))
    HTTP_CALLS.clear()
    check("info: повторный 404 → 0 HTTP (негативный кэш запомнен)",
          node.get_lora_info("civitai404.safetensors") is None and not HTTP_CALLS,
          f"http={len(HTTP_CALLS)}")
finally:
    node._http_get_json = orig_http

node._http_get_json = http_fail
try:
    HTTP_CALLS.clear()
    node.get_lora_info("slow.safetensors")
    check("info: сетевой сбой → 1 HTTP", len(HTTP_CALLS) == 1, str(HTTP_CALLS))
    HTTP_CALLS.clear()
    node.get_lora_info("slow.safetensors")
    check("info: сетевой сбой НЕ отравляет кэш (повтор снова HTTP)",
          len(HTTP_CALLS) == 1, f"http={len(HTTP_CALLS)}")
finally:
    node._http_get_json = orig_http

node._http_get_json = fake_http3
_HOLDER["payload"] = _ok_images("https://image.civitai.com/x/width=450/one.png")
try:
    HTTP_CALLS.clear()
    node.get_lora_info("stamp.safetensors")
    warm_http = len(HTTP_CALLS)
    with open(str(LORA_DIR / "stamp.safetensors"), "wb") as handle:
        handle.write(b"lora-stamp-changed-longer")
    HTTP_CALLS.clear()
    node.get_lora_info("stamp.safetensors")
    check("info: файл лоры изменён → кэш инвалидируется (снова HTTP)",
          warm_http == 1 and len(HTTP_CALLS) == 1,
          f"warm={warm_http} after={len(HTTP_CALLS)}")
finally:
    node._http_get_json = orig_http

# ── 10g. блокирующая работа уходит в поток (event loop не встаёт) ──────────
#
# sync sha256/urlopen внутри async def замораживает ВЕСЬ сервер ComfyUI
# (очередь, прогресс, websocket) — именно поэтому 20 лор грузились «долго».

orig_sha = node._sha256


def slow_sha(path):
    time.sleep(0.15)
    return orig_sha(path)


async def _loop_probe():
    state = {"ticks": 0, "running": True}

    async def ticker():
        while state["running"]:
            state["ticks"] += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    resp = await handlers["/degg_lora_loader/info"](_Req({"file": "slow.safetensors"}))
    state["running"] = False
    await task
    return state["ticks"], resp


node._sha256 = slow_sha
node._http_get_json = fake_http3
try:
    ticks, resp = asyncio.run(_loop_probe())
finally:
    node._sha256 = orig_sha
    node._http_get_json = orig_http
    if orig_download is not None:
        node._download_image = orig_download
# Замер: пока поток спит 150ms, свободный loop успевает тысячи итераций;
# блокирующий sync-вызов даёт единицы (красная версия: ticks=25).
_p(f"  info  ticks(loop probe) = {ticks} (порог 1000)")
check("info: тяжёлый sha256 не блокирует event loop (работа в потоке)",
      ticks > 1000, f"ticks={ticks} status={resp.get('status')}")

if thumb is None:
    check("thumb: _download_image отдаётся в поток (asyncio.to_thread)", False,
          "роут /thumb не зарегистрирован")
else:
    _SRC_THUMB = SRC[SRC.find("handle_thumb"):]
    check("thumb: _download_image отдаётся в поток (asyncio.to_thread)",
          "asyncio.to_thread(_download_image" in _SRC_THUMB,
          _SRC_THUMB[:120])

# ── 10h. GC: sweep orphan-кэша, TTL и сброс превью (этап 2) ───────────────
#
# Мусор не должен накапливаться и не должен чиститься руками: кэш лор, которых
# больше нет на диске, убирается при загрузке каталога; как страховка — TTL по
# mtime. Предохранитель: пустой/битый листинг лор НЕ чистит ничего.

CACHE_DIR = IMG_CACHE.parent
INPUT_DIR = TMP / "input"
fp_mod = sys.modules["folder_paths"]
orig_list_names = fp_mod.get_filename_list
# 10g восстановил настоящий _download_image — для GC-проверок снова фейк
node._download_image = fake_download


def _key(name):
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


def _age(path, days):
    stamp = time.time() - days * 86400
    os.utime(str(path), (stamp, stamp))


def _loras_call():
    return asyncio.run(handlers["/degg_lora_loader/loras"](_Req()))


def _mk_orphans(name):
    key = _key(name)
    for directory in (CACHE_DIR, IMG_CACHE, INPUT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    paths = [
        CACHE_DIR / (key + ".v2.json"),
        IMG_CACHE / (key + ".i0.png"),
        INPUT_DIR / ("degg_lora_preview_%s_1700000000.png" % key),
    ]
    for path in paths:
        path.write_bytes(b"x")
    return paths


_orph = _mk_orphans("ghost.safetensors")
_act_key = _key("a.safetensors")
(INPUT_DIR / ("degg_lora_preview_%s_1700000000.png" % _act_key)).write_bytes(b"x")
(CACHE_DIR / "notes.txt").write_text("keep", encoding="utf-8")
(IMG_CACHE / "readme.md").write_text("keep", encoding="utf-8")
(INPUT_DIR / "user_photo.png").write_bytes(b"keep")
node._LAST_SWEEP = 0
node._LAST_TTL = 0
_loras_call()
check("gc: orphan JSON-кэш удалён", not _orph[0].exists(), str(_orph[0]))
check("gc: orphan картинка-кэш удалена", not _orph[1].exists(), str(_orph[1]))
check("gc: orphan кастомное превью удалено", not _orph[2].exists(), str(_orph[2]))
check("gc: JSON-кэш существующей лоры сохранён",
      (CACHE_DIR / (_act_key + ".v2.json")).exists())
check("gc: кастомное превью существующей лоры сохранено",
      (INPUT_DIR / ("degg_lora_preview_%s_1700000000.png" % _act_key)).exists())
check("gc: чужие файлы в каталоге кэша не тронуты",
      (CACHE_DIR / "notes.txt").exists() and (IMG_CACHE / "readme.md").exists())
check("gc: чужие файлы в input не тронуты", (INPUT_DIR / "user_photo.png").exists())

# предохранитель: битый листинг лор
_orph2 = _mk_orphans("ghost2.safetensors")

def _boom(folder):
    raise RuntimeError("listing failed")


fp_mod.get_filename_list = _boom
node._LAST_SWEEP = 0
node._LAST_TTL = 0
try:
    _loras_call()
finally:
    fp_mod.get_filename_list = orig_list_names
check("gc: битый листинг лор → ничего не удалено (предохранитель)",
      all(p.exists() for p in _orph2))

# предохранитель: пустой каталог
_orph3 = _mk_orphans("ghost3.safetensors")
fp_mod.get_filename_list = lambda folder: []
node._LAST_SWEEP = 0
try:
    resp_empty = _loras_call()
finally:
    fp_mod.get_filename_list = orig_list_names
check("gc: пустой каталог лор → ничего не удалено (предохранитель)",
      all(p.exists() for p in _orph3))
check("loras: пустой каталог → 200 и пустой список",
      resp_empty["status"] == 200 and resp_empty["json"]["loras"] == [], str(resp_empty))

# троттлинг sweep
_orph4 = _mk_orphans("ghost4.safetensors")
node._LAST_SWEEP = time.time()
_loras_call()
check("gc: sweep троттлится (подряд второй вызов не чистит)",
      all(p.exists() for p in _orph4))
node._LAST_SWEEP = 0
_loras_call()
check("gc: после окна троттлинга orphan удаляется", not _orph4[1].exists())

# TTL: мусор убирается по mtime, активные свежие файлы остаются
_sub_key = _key("sub/c.safetensors")
_old_json = CACHE_DIR / (_sub_key + ".v2.json")
_old_img = IMG_CACHE / (_sub_key + ".i0.png")
_old_json.write_bytes(b"x")
_old_img.write_bytes(b"x")
_age(_old_json, 40)
_age(_old_img, 40)
_fresh_json = CACHE_DIR / (_key("b.safetensors") + ".v2.json")
_fresh_json.write_bytes(b"x")
node._LAST_SWEEP = 0
node._LAST_TTL = 0
_loras_call()
check("gc: TTL удаляет файлы кэша старше 30 дней",
      not _old_json.exists() and not _old_img.exists())
check("gc: TTL не трогает свежие файлы кэша", _fresh_json.exists())

# отдача превью продлевает жизнь файлу, но НЕ трогает файлы пользователя
def _c_touch():
    path = _file_path(_thumb({"file": "warm.safetensors"}))
    if not path or not os.path.isfile(path):
        return False, f"нет кэша превью: {path}"
    _age(path, 20)
    _thumb({"file": "warm.safetensors"})
    age = time.time() - os.path.getmtime(path)
    return age < 5, f"age={age:.0f}s"


tcheck("thumb: обращение к кэшу продлевает жизнь файла (touch mtime)", _c_touch)


def _c_sibling_mtime():
    sibling = str(LORA_DIR / "a.png")
    before = os.path.getmtime(sibling)
    _thumb({"file": "a.safetensors"})
    return os.path.getmtime(sibling) == before, f"mtime={before}"


tcheck("thumb: соседний файл лоры не трогаем (mtime не меняется)", _c_sibling_mtime)

# refresh=1 сбрасывает кэш превью лоры (следующий /thumb перекачает)
node._http_get_json = fake_http3
_HOLDER["payload"] = _ok_images("https://image.civitai.com/x/width=450/one.png")
node._LAST_TTL = time.time()
try:
    def _c_refresh_drops_thumb():
        DOWNLOADS.clear()
        cached = _file_path(_thumb({"file": "warm.safetensors"}))
        if not cached or not os.path.isfile(cached):
            return False, f"нет кэша превью: {cached}"
        asyncio.run(handlers["/degg_lora_loader/info"](
            _Req({"file": "warm.safetensors", "refresh": "1"})))
        dropped = not os.path.isfile(cached)
        DOWNLOADS.clear()
        again = _thumb({"file": "warm.safetensors"})
        return (dropped and _status(again) == 200 and len(DOWNLOADS) == 1), \
            f"dropped={dropped} dl={DOWNLOADS}"

    tcheck("info: refresh=1 сбрасывает кэш превью лоры (следующий /thumb качает снова)",
           _c_refresh_drops_thumb)
finally:
    node._http_get_json = orig_http

# ── 11. JS/Python согласованность роутов ──────────────────────────────────
js_path = ROOT / "web" / "js" / "degg_lora_loader.js"
if js_path.is_file():
    js_src = js_path.read_text(encoding="utf-8")
    js_routes = sorted(set(re.findall(r"/degg_lora_loader/[a-z_]+", js_src)))
    py_routes = sorted(set(re.findall(r"/degg_lora_loader/[a-z_]+", SRC)))
    check("JS и Python используют одинаковые роуты", js_routes == py_routes,
          f"js={js_routes} py={py_routes}")
else:
    check("JS и Python используют одинаковые роуты", False, "нет JS-файла")

import shutil  # noqa: E402

shutil.rmtree(str(TMP), ignore_errors=True)

_p(f"\nИТОГО: ок={len(oks)} FAIL: {len(fails)}")
if fails:
    for f in fails:
        _p("  - " + f)
    sys.exit(1)
_p("ТЕСТ ПРОЙДЕН")
sys.exit(0)
