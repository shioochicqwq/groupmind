"""Which anti-bot sites can the web_reader plugin read from this machine, and at which tier?

Runs the plugin's own escalation path on each URL, tier by tier, and records the first tier
that returns the real page:

  plain        reader.fetch (requests)
  impersonate  reader.fetch_impersonate (curl_cffi, Chrome TLS/HTTP2 fingerprint)
  browser      browser.Browser.fetch_rendered, real Chrome through patchright
  camoufox     the same with the Camoufox engine (skipped when camoufox is not installed)

Before the sites, a self-check: what the browser tells a page about itself (UA, client hints,
languages, timezone, screen, WebGL) and what public detection pages make of it (sannysoft,
deviceandbrowserinfo, BrowserScan, CreepJS). A leak found there is ours to fix; a site that
still refuses a browser with a clean self-check is judging the network (IP class) or the
request rate, not the browser.

Gold standard (user, 2026-11-08): rateyourmusic.com. Each site has a marker that only the
real page contains. Run this on the machine the bot will actually use (home broadband).
The browser timezone is set to the egress IP's zone unless --timezone says otherwise.

  python scripts/search/antibot_probe.py --out probe.json [--executable CHROME] [--xvfb XVFB]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "astrbot_plugin_web_reader"
sys.path.insert(0, str(PLUGIN))
import browser as br  # noqa: E402
import reader  # noqa: E402

SITES = [
    ("cf_test", "https://www.scrapingcourse.com/cloudflare-challenge", "You bypassed the Cloudflare challenge", 0),
    ("moegirl", "https://zh.moegirl.org.cn/%E5%88%9D%E9%9F%B3%E6%9C%AA%E6%9D%A5", "初音未来", 500),
    ("zhihu", "https://www.zhihu.com/question/19550225", "知乎", 500),
    ("baike", "https://baike.baidu.com/item/%E5%88%9D%E9%9F%B3%E6%9C%AA%E6%9D%A5", "初音未来", 500),
    # rym answers fast loading with its own reCAPTCHA page, so its pages come last and far apart
    ("rym_home", "https://rateyourmusic.com/", "RYM", 500),
    ("rym_artist", "https://rateyourmusic.com/artist/radiohead", "Radiohead", 500),
    ("rym", "https://rateyourmusic.com/release/album/radiohead/ok-computer/", "OK Computer", 500),
]

FINGERPRINT_JS = """async () => {
  const gl = (() => { try { const c = document.createElement('canvas').getContext('webgl');
    const e = c.getExtension('WEBGL_debug_renderer_info');
    return c.getParameter(e.UNMASKED_VENDOR_WEBGL) + ' / ' + c.getParameter(e.UNMASKED_RENDERER_WEBGL); } catch (x) { return null; } })();
  const uad = navigator.userAgentData;
  return {
    userAgent: navigator.userAgent, webdriver: navigator.webdriver,
    brands: uad ? uad.brands.map(b => b.brand + ' ' + b.version) : null, platform: navigator.platform,
    languages: navigator.languages, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    screen: [screen.width, screen.height], outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight],
    cores: navigator.hardwareConcurrency, plugins: navigator.plugins.length, webgl: gl,
  };
}"""

# public detection pages: (name, url, JS that returns what the page concluded)
DETECTORS = [
    ("sannysoft", "https://bot.sannysoft.com/",
     "() => [...document.querySelectorAll('td.failed, td.warn')].map(td => td.parentElement.innerText.replace(/\\s+/g, ' ').slice(0, 100))"),
    ("deviceandbrowserinfo", "https://deviceandbrowserinfo.com/are_you_a_bot",
     "() => { const m = document.body.innerText.match(/\\{\\s*\"isBot\"[\\s\\S]*?\\}\\s*\\}/); if (!m) return null; const j = JSON.parse(m[0]);"
     " return {isBot: j.isBot, flagged: Object.keys(j.details).filter(k => j.details[k])}; }"),
    ("browserscan", "https://www.browserscan.net/bot-detection",
     "() => { const L = document.body.innerText.split('\\n').map(s => s.trim()).filter(Boolean); const i = L.indexOf('Test Results:');"
     " const bad = []; L.forEach((s, k) => { if (/^(Abnormal|Robot)$/i.test(s) && k > i + 1) bad.push(L[k - 1] + ': ' + s); });"
     " return {result: i >= 0 ? L[i + 1] : null, flagged: bad}; }"),
    ("creepjs", "https://abrahamjuliot.github.io/creepjs/",
     "() => (document.body.innerText.match(/\\d+% (like headless|headless|stealth)/g) || [])"),
]


def text_of(raw: bytes, url: str) -> tuple[str, str]:
    d = reader.extract(raw, url, 0, reader.MAX_LIMIT)
    return d["title"], d["text"]


async def selfcheck(b) -> dict:
    """What this browser looks like from inside a page, and what detection pages say about it."""
    out = {"engine": b.cfg.engine}
    page = await b.new_page()
    try:
        await page.goto("https://example.com/", timeout=40000)
        out["fingerprint"] = await page.evaluate(FINGERPRINT_JS)
        out["mode"] = b.mode
        for name, url, js in DETECTORS:
            try:
                await page.goto(url, timeout=40000, wait_until="domcontentloaded")
                await page.wait_for_timeout(12000)
                out[name] = await page.evaluate(js)
            except Exception as exc:  # noqa: BLE001
                out[name] = f"error: {type(exc).__name__}: {str(exc)[:100]}"
    finally:
        await page.close()
    return out


async def probe(name, url, marker, min_chars, browsers, tiers):
    row = {"site": name, "url": url, "tiers": {}}
    for tier in tiers:
        if tier in ("browser", "camoufox") and tier not in browsers:
            continue
        t = time.time()
        try:
            if tier == "plain":
                final, _ct, raw = await asyncio.to_thread(reader.fetch, url)
            elif tier == "impersonate":
                final, _ct, raw = await asyncio.to_thread(reader.fetch_impersonate, url)
            else:
                final, html, passed = await browsers[tier].fetch_rendered(url)
                raw = html.encode()
                if not passed:
                    title, text = text_of(raw, final)
                    raise reader.BotWall(f"challenge not passed: {title[:40]} | {' '.join(text.split())[:80]}")
            title, text = text_of(raw, final)
            # the real page: marker in the body text and a real amount of text (a check page has a title only)
            ok = marker in text and len(text) >= min_chars and not reader.is_wall(200, (title + text[:2000]).encode())
            row["tiers"][tier] = {"ok": ok, "sec": round(time.time() - t, 1), "title": title[:80], "chars": len(text)}
        except Exception as exc:  # noqa: BLE001
            row["tiers"][tier] = {"ok": False, "sec": round(time.time() - t, 1), "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        if row["tiers"][tier]["ok"]:
            row["first_ok"] = tier
            break
    row.setdefault("first_ok", None)
    return row


def egress_info() -> dict:
    """Network class and timezone of the egress IP (the address itself is not kept)."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as resp:
            j = json.load(resp)
            return {"org": j.get("org"), "country": j.get("country"), "timezone": j.get("timezone")}
    except Exception:  # noqa: BLE001
        return {}


async def main_async(args):
    egress = egress_info()
    tz = egress.get("timezone", "") if args.timezone == "auto" else args.timezone
    profile = args.profile or tempfile.mkdtemp(prefix="antibot-profile-")
    common = dict(headless=args.headless, timezone=tz, xvfb_command=args.xvfb, challenge_wait=args.wait,
                  min_host_interval=args.interval)
    browsers = {}
    if "browser" in args.tiers and br.available():
        browsers["browser"] = br.Browser(br.BrowserConfig(profile_dir=profile, executable_path=args.executable, **common))
    if "camoufox" in args.tiers and br.available("camoufox"):
        browsers["camoufox"] = br.Browser(br.BrowserConfig(profile_dir=profile + "-camoufox", engine="camoufox", **common))
    rows, checks = [], []
    try:
        if not args.no_selfcheck:
            for b in browsers.values():
                c = await selfcheck(b)
                checks.append(c)
                print(json.dumps(c, ensure_ascii=False), flush=True)
        for name, url, marker, min_chars in SITES:
            if (args.only and name not in args.only) or (not args.only and name.startswith("rym") and not args.rym):
                continue
            r = await probe(name, url, marker, min_chars, browsers, args.tiers)
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            if name.startswith("rym"):
                await asyncio.sleep(args.rym_gap)
    finally:
        for b in browsers.values():
            await b.close()
    out = {"when": time.strftime("%Y-%m-%d %H:%M"), "host": socket.gethostname(), "egress": egress, "timezone": tz,
           "modes": {k: b.mode for k, b in browsers.items()}, "selfcheck": checks, "rows": rows}
    if args.out:
        args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("summary", {r["site"]: r["first_ok"] for r in rows}, out["modes"], egress)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tiers", nargs="*", default=["plain", "impersonate", "browser", "camoufox"])
    ap.add_argument("--rym", action="store_true", help="include the rateyourmusic pages (slow on purpose; do not repeat often)")
    ap.add_argument("--rym-gap", type=float, default=40, help="seconds to wait after each rym page")
    ap.add_argument("--no-selfcheck", action="store_true")
    ap.add_argument("--headless", action="store_true", help="headless browser (detectable; only to compare)")
    ap.add_argument("--timezone", default="auto", help="browser timezone; auto = the egress IP's zone")
    ap.add_argument("--xvfb", default=os.environ.get("XVFB_COMMAND", "Xvfb"))
    ap.add_argument("--executable", default=os.environ.get("BROWSER_EXECUTABLE", ""))
    ap.add_argument("--profile", default="", help="browser profile dir; reuse it to keep clearance cookies")
    ap.add_argument("--wait", type=float, default=45)
    ap.add_argument("--interval", type=float, default=5, help="minimum seconds between page loads on one host")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
