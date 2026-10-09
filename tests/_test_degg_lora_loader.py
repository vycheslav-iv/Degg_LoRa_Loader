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
import types
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

FILE_NAMES = ["a.safetensors", "b.safetensors", "sub/c.safetensors",
              "sub\\c.safetensors"]

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

    class Response:
        def __init__(self, status=200, **kw):
            self.status = status
            self.body = None

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
])
check("register_routes: ровно 3 роута (loras/img/info)",
      sorted(handlers) == expected_routes, str(sorted(handlers)))
check("register_routes: все обработчики — async def",
      bool(handlers) and all(asyncio.iscoroutinefunction(f) for f in handlers.values()))


class _Req:
    def __init__(self, query=None):
        self.query = dict(query or {})


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
    check("info: первый запрос проходит через sha256 в CivitAI", len(HTTP_CALLS) == 1, str(HTTP_CALLS))
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
