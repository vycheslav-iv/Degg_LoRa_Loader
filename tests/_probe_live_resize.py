"""Живая диагностика ресайза Degg_LoRa_Loader в КЛАССИЧЕСКОМ (canvas) режиме.

Симптом (пользователь): в classic нода «будто заморожена» — её нельзя
растянуть за угол; в Nodes 2.0 всё работает.

Проба меряет СУТЬ задачи — «перетаскивание SE-угла мышью меняет размер
ноды» — а не симптом. Дополнительно собирает диагностику причины:

  * findResizeDirection(SE)   — видит ли LiteGraph resize-зону;
  * getWidgetOnPos(SE)        — не перехватывает ли зону виджет
                                (LGraphCanvas.processMouseDown: widget →
                                processWidgetClick, resize НЕ настраивается);
  * elementFromPoint(SE)      — не лежит ли поверх канваса DOM-элемент
                                виджета (тогда mousedown не доходит до
                                LiteGraph вообще);
  * widget.computedHeight / last_y vs node.size — переполняется ли
                                DOM-обёртка за нижний край ноды.

Контракт (ПРОВЕРЯЕМЫЙ):
    resizeDeltaOk = |ΔW − 120| ≤ 12  И  |ΔH − 80| ≤ 12
(реальный mouse-drag SE-углом на (+120, +80) экрана при масштабе 1).

Запуск (ComfyUI должен быть запущен на 127.0.0.1:8188):
    cd Degg_LoRa_Loader
    python tests/_probe_live_resize.py            # classic (по умолчанию)
    python tests/_probe_live_resize.py --nodes2   # для сравнения с Nodes 2.0

Приёмка:
    до фикса (classic): resizeDeltaOk=False, ΔW/ΔH ≈ 0 — FAIL: 1;
    после фикса (classic): resizeDeltaOk=True — FAIL: 0.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

SETUP_JS = r"""
(async () => {
  const out = {};
  const g = window.app && window.app.graph;
  if (!g) { out.error = "no graph"; return out; }
  const TYPE = "Degg_LoRa_Loader";
  if (!window.LiteGraph.registered_node_types[TYPE]) {
    out.error = "node type not registered: " + TYPE;
    out.known = Object.keys(window.LiteGraph.registered_node_types || {})
      .filter((k) => /degg|lora/i.test(k));
    return out;
  }
  const n = window.LiteGraph.createNode(TYPE);
  if (!n) { out.error = "createNode failed"; return out; }
  g.add(n);
  n.pos = [80, 80];
  window.__dlNodeId = n.id;

  const pump = async (k) => {
    for (let i = 0; i < k; i++) await new Promise((r) => requestAnimationFrame(r));
  };
  // Ждём DOM-виджет: onNodeCreated синхронен, но render() пишет в DOM асинхронно.
  for (let i = 0; i < 120; i++) {
    await pump(2);
    if (n._dlReady && (n.widgets || []).some((w) => w && w.element)) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  await new Promise((r) => setTimeout(r, 900));
  await pump(20);
  try { window.app.canvas.setDirty(true, true); window.app.canvas.draw(true, true); } catch (e) {}
  await pump(6);

  const c = window.app.canvas;
  try { c.centerOnNode(n); if (c.ds) c.ds.scale = 1; c.centerOnNode(n); } catch (e) { out.centerErr = String(e); }
  try { c.setDirty(true, true); c.draw(true, true); } catch (e) {}
  await pump(10);
  await new Promise((r) => setTimeout(r, 400));

  const w = (n.widgets || []).find((x) => x && x.name === "degg_lora_list");
  out.mode = (window.app.ui && window.app.ui.settings && window.app.ui.settings.getSettingValue)
    ? window.app.ui.settings.getSettingValue("Comfy.VueNodes.Enabled") : null;
  out.size = [n.size[0], n.size[1]];
  out.renderingSize = n.renderingSize ? [n.renderingSize[0], n.renderingSize[1]] : null;
  const cs = n.computeSize ? n.computeSize() : null;
  out.computeSize = cs ? [cs[0], cs[1]] : null;
  out.resizable = n.resizable;
  out.widget = w ? {
    type: w.type,
    last_y: w.last_y,
    computedHeight: w.computedHeight,
    margin: w.margin,
    width: w.width,
    hasElement: !!w.element,
    elementRect: w.element ? (() => {
      const r = w.element.getBoundingClientRect();
      return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
    })() : null,
  } : null;
  out.nodeScreenRect = (() => {
    const r = c.canvas.getBoundingClientRect();
    const ds = c.ds;
    const a = ds.convertOffsetToCanvas([n.pos[0], n.pos[1]]);
    const b = ds.convertOffsetToCanvas([n.pos[0] + n.size[0], n.pos[1] + n.size[1]]);
    return {
      canvas: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      node: [Math.round(r.left + a[0]), Math.round(r.top + a[1]),
             Math.round(b[0] - a[0]), Math.round(b[1] - a[1])],
      scale: ds.scale,
    };
  })();
  return out;
})()
"""

PROBE_JS = r"""
(() => {
  const n = window.app.graph.getNodeById(window.__dlNodeId);
  const c = window.app.canvas;
  const ds = c.ds;
  const out = { size: [n.size[0], n.size[1]] };
  const sr = c.canvas.getBoundingClientRect();
  // findResizeDirection / getWidgetOnPos живут в GRAPH-координатах (pos/size).
  // convertOffsetToCanvas переводит graph -> экранные пиксели канваса.
  const toScreen = (p) => {
    const t = ds.convertOffsetToCanvas(p);
    return [sr.left + t[0], sr.top + t[1]];
  };
  const pts = {
    se_inside: [n.pos[0] + n.size[0] - 3, n.pos[1] + n.size[1] - 3],
    se_mid:    [n.pos[0] + n.size[0] - 8, n.pos[1] + n.size[1] - 8],
    e_mid:     [n.pos[0] + n.size[0] - 3, n.pos[1] + n.size[1] / 2],
    s_mid:     [n.pos[0] + n.size[0] / 2, n.pos[1] + n.size[1] - 3],
    outside:   [n.pos[0] + n.size[0] + 30, n.pos[1] + n.size[1] + 30],
  };
  out.points = {};
  for (const [name, p] of Object.entries(pts)) {
    const s = toScreen(p);
    const hit = document.elementFromPoint(s[0], s[1]);
    const wdg = n.getWidgetOnPos ? n.getWidgetOnPos(p[0], p[1]) : "no-fn";
    out.points[name] = {
      graph: [Math.round(p[0]), Math.round(p[1])],
      screen: [Math.round(s[0]), Math.round(s[1])],
      resizeDir: n.findResizeDirection ? (n.findResizeDirection(p[0], p[1]) || null) : "no-fn",
      widget: wdg && typeof wdg === "object" ? (wdg.name || "unnamed") : (wdg || null),
      hit: hit ? hit.tagName + "." + String(hit.className || "").slice(0, 40) : null,
      hitIsCanvas: hit === c.canvas,
    };
  }
  // Кто держит события в зоне угла: обёртка .dom-widget и её pointer-events.
  const w = (n.widgets || []).find((x) => x && x.name === "degg_lora_list");
  if (w && w.element) {
    const er = w.element.getBoundingClientRect();
    const nr = (() => {
      const a = ds.convertOffsetToCanvas([n.pos[0], n.pos[1]]);
      const b = ds.convertOffsetToCanvas([n.pos[0] + n.size[0], n.pos[1] + n.size[1]]);
      return { l: sr.left + a[0], t: sr.top + a[1], r: sr.left + b[0], b: sr.top + b[1] };
    })();
    out.overflow = {
      right: Math.round(er.right - nr.r),
      bottom: Math.round(er.bottom - nr.b),
      widgetBottomVsNode: Math.round((w.last_y || 0) + (w.computedHeight || 0) - n.size[1]),
    };
    let host = w.element.parentElement;
    out.domStack = [];
    for (let i = 0; i < 5 && host; i++) {
      const r = host.getBoundingClientRect();
      out.domStack.push({
        cls: String(host.className || "").slice(0, 60),
        pe: getComputedStyle(host).pointerEvents,
        rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
      });
      host = host.parentElement;
    }
    out.elementPE = getComputedStyle(w.element).pointerEvents;
  }
  return out;
})()
"""


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _reexec_with_websockets() -> None:
    try:
        import websockets  # noqa: F401
        return
    except ImportError:
        pass
    me = Path(__file__).resolve()
    env = __import__("os").environ.get("COMFY_PY")
    cands = ([env] if env else []) + [r"D:\ComfyUI_windows_portable\python_embeded\python.exe"]
    for cand in cands:
        if not Path(cand).exists():
            continue
        if subprocess.run([cand, "-c", "import websockets"], capture_output=True).returncode == 0:
            r = subprocess.run([cand, str(me), *sys.argv[1:]], capture_output=True)
            sys.stdout.write(r.stdout.decode("utf-8", "replace"))
            sys.stderr.write(r.stderr.decode("utf-8", "replace"))
            sys.stdout.flush()
            sys.exit(r.returncode)
    print("ПРОБА НЕ ЗАПУЩЕНА: ни один интерпретатор не имеет websockets", flush=True)
    print("FAIL: 1", flush=True)
    sys.exit(1)


def find_chrome() -> str:
    import os
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    raise SystemExit("Chrome не найден (задай CHROME_PATH)")


def wait_devtools(port: int, timeout: float = 30.0) -> dict:
    url = f"http://127.0.0.1:{port}/json/list"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                pages = json.load(r)
            for p in pages:
                if p.get("type") == "page" and p.get("webSocketDebuggerUrl"):
                    return p
        except Exception:
            pass
        time.sleep(0.3)
    raise SystemExit("CDP не отвечает: страница не найдена")


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def call(self, method: str, params: dict | None = None):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expr: str, await_promise: bool = False):
        res = await self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise,
        })
        if "exceptionDetails" in res:
            d = res["exceptionDetails"].get("exception", {}).get("description", "eval error")
            raise RuntimeError(d)
        return res.get("result", {}).get("value")


async def wait_for(cdp: CDP, expr: str, timeout: float = 180.0, label: str = ""):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = await cdp.eval(expr)
            if last:
                return last
        except Exception as e:
            last = repr(e)
        await asyncio.sleep(0.5)
    raise SystemExit(f"не дождались: {label or expr} (последнее: {last!r})")


async def drag(cdp: CDP, x: float, y: float, dx: float, dy: float) -> None:
    await cdp.call("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1,
    })
    for step in (0.25, 0.5, 0.75, 1.0):
        await cdp.call("Input.dispatchMouseEvent", {
            "type": "mouseMoved", "x": x + dx * step, "y": y + dy * step,
            "button": "left", "buttons": 1,
        })
        await asyncio.sleep(0.05)
    await cdp.call("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x + dx, "y": y + dy,
        "button": "left", "buttons": 0, "clickCount": 1,
    })
    await asyncio.sleep(0.3)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8188/")
    ap.add_argument("--port", type=int, default=9446)
    ap.add_argument("--nodes2", action="store_true",
                    help="мерить в Nodes 2.0 вместо classic")
    ap.add_argument("--shot", default=str(Path(__file__).with_name("_shot_resize.png")))
    args = ap.parse_args()

    try:
        import websockets  # noqa: WPS433
    except ImportError:
        raise SystemExit("нет модуля websockets — запускай через python_embeded")

    profile = Path(tempfile.mkdtemp(prefix="dl-resize-"))
    chrome = subprocess.Popen([
        find_chrome(), "--headless=new",
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--window-size=1600,1000",
        "--disable-features=Translate",
        args.url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    errors: list[str] = []
    oks: list[str] = []

    def check(label: str, cond: bool, extra: str = "") -> None:
        (oks if cond else errors).append(label)
        print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  [{extra}]" if extra else ""))

    try:
        page = wait_devtools(args.port)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            await cdp.call("Runtime.enable")
            print("→ ждём загрузку фронтенда…")
            await wait_for(cdp, "!!(window.app && window.app.isGraphReady)", 180, "app.isGraphReady")

            want_vue = "true" if args.nodes2 else "false"
            print("→ переключаем VueNodes (Nodes 2.0) в", want_vue)
            await cdp.eval(
                "(()=>{const k='Comfy.VueNodes.Enabled';const a=window.app;"
                "try{if(a.ui&&a.ui.settings&&a.ui.settings.setSettingValue)"
                "{a.ui.settings.setSettingValue(k," + want_vue + ");return 'ok';}"
                "return 'no-api';}catch(e){return 'err:'+e}})()"
            )
            await asyncio.sleep(2.0)
            diag = await cdp.eval(
                "(()=>{const a=window.app;return {"
                "vue: (a&&a.ui&&a.ui.settings&&a.ui.settings.getSettingValue)"
                "? a.ui.settings.getSettingValue('Comfy.VueNodes.Enabled') : null,"
                "registered: Object.keys(window.LiteGraph.registered_node_types||{})"
                ".filter((k)=>/degg|lora/i.test(k))}})()"
            )
            print("→ diag:", json.dumps(diag, ensure_ascii=False))

            setup = await cdp.eval(SETUP_JS, await_promise=True)
            print("→ setup: " + json.dumps(setup, ensure_ascii=False, indent=2))
            if setup.get("error"):
                check("setup", False, setup["error"])
            else:
                probe = await cdp.eval(PROBE_JS)
                print("→ probe: " + json.dumps(probe, ensure_ascii=False, indent=2))

                # ── Живой mouse-drag SE-углом: СУТЬ задачи ──
                p = (probe.get("points") or {}).get("se_inside") or {}
                scr = p.get("screen") or [None, None]
                x, y = scr[0], scr[1]
                if x is None:
                    check("resize: точка SE-угла найдена", False, json.dumps(p))
                else:
                    s0 = list(setup["size"])
                    await drag(cdp, x, y, 120, 80)
                    s1 = await cdp.eval(
                        "(()=>{const n=window.app.graph.getNodeById(window.__dlNodeId);"
                        "return [n.size[0], n.size[1]]})()")
                    dW, dH = s1[0] - s0[0], s1[1] - s0[1]
                    print(f"→ drag SE: size {s0} -> {s1}  (ΔW={dW}, ΔH={dH})")
                    ok = abs(dW - 120) <= 12 and abs(dH - 80) <= 12
                    check("resize: SE-drag мышью реально меняет размер",
                          ok, f"ΔW={dW} ΔH={dH} (ждали ≈ +120/+80)")
                    check("resize: ΔW близок к 120", abs(dW - 120) <= 12, f"ΔW={dW}")
                    check("resize: ΔH близок к 80", abs(dH - 80) <= 12, f"ΔH={dH}")

                # Диагностика причины (не гейт, но печатаем)
                sp = (probe.get("points") or {}).get("se_inside") or {}
                print("→ SE-точка: resizeDir=%r widget=%r hit=%r hitIsCanvas=%r"
                      % (sp.get("resizeDir"), sp.get("widget"), sp.get("hit"), sp.get("hitIsCanvas")))
                print("→ overflow:", json.dumps(probe.get("overflow"), ensure_ascii=False))
                if sp.get("widget"):
                    print("→ ПРИЧИНА-кандидат: getWidgetOnPos вернул виджет — "
                          "LGraphCanvas.processMouseDown уходит в processWidgetClick "
                          "и resize не настраивается")
                if sp.get("hitIsCanvas") is False:
                    print("→ ПРИЧИНА-кандидат: поверх канваса лежит DOM-элемент "
                          f"({sp.get('hit')}) — mousedown не доходит до LiteGraph")
                ov = probe.get("overflow") or {}
                if isinstance(ov.get("bottom"), int) and ov["bottom"] > 0:
                    print(f"→ ПРИЧИНА-кандидат: DOM-виджет переполняется на {ov['bottom']}px "
                          "за нижний край ноды")

                # Скриншот как доказательство «до → после»
                if args.shot:
                    try:
                        shot = await cdp.call("Page.captureScreenshot", {"format": "png"})
                        Path(args.shot).write_bytes(base64.b64decode(shot["data"]))
                        print(f"  ok   скриншот  [{args.shot}]")
                    except Exception as e:
                        print("  --   скриншот не снят:", e)

                try:
                    await cdp.eval(
                        "(()=>{try{const n=window.app.graph.getNodeById(window.__dlNodeId);"
                        "if(n)window.app.graph.remove(n);window.app.canvas.setDirty(true,true);}"
                        "catch(e){}})()")
                except Exception:
                    pass
    finally:
        chrome.terminate()
        try:
            shutil.rmtree(profile, ignore_errors=True)
        except Exception:
            pass

    print(f"\nИТОГ: {len(oks)} ok, {len(errors)} FAIL")
    for e in errors:
        print("  FAIL:", e)
    print("FAIL:", len(errors))
    return 0 if not errors else 1


if __name__ == "__main__":
    _force_utf8()
    _reexec_with_websockets()
    sys.exit(asyncio.run(main()))
