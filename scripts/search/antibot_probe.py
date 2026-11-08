"""Which anti-bot sites can the web_reader plugin read from this machine, and at which tier?

Runs the plugin's own escalation path on each URL, tier by tier, and records the first tier
that returns the real page:

  plain        reader.fetch (requests)
  impersonate  reader.fetch_impersonate (curl_cffi, Chrome TLS/HTTP2 fingerprint)
  browser      browser.Browser.fetch_rendered (patchright; waits out / clicks Turnstile)

Gold standard (user, 2026-11-08): rateyourmusic.com. Each site has a marker that only the
real page contains. Results depend on the network: a datacenter IP fails Cloudflare even in a
real browser; run this on the machine the bot will actually use (home broadband).

  python scripts/search/antibot_probe.py --out probe.json [--headed] [--executable PATH]
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
    ("rym", "https://rateyourmusic.com/release/album/radiohead/ok-computer/", "OK Computer"),
    ("cf_test", "https://www.scrapingcourse.com/cloudflare-challenge", "You bypassed the Cloudflare challenge"),
    ("moegirl", "https://zh.moegirl.org.cn/%E5%88%9D%E9%9F%B3%E6%9C%AA%E6%9D%A5", "初音未来"),
    ("zhihu", "https://www.zhihu.com/question/19550225", "知乎"),
    ("baike", "https://baike.baidu.com/item/%E5%88%9D%E9%9F%B3%E6%9C%AA%E6%9D%A5", "初音未来"),
]


def text_of(raw: bytes, url: str) -> tuple[str, str]:
    d = reader.extract(raw, url, 0, reader.MAX_LIMIT)
    return d["title"], d["text"]


async def probe(name, url, marker, b, tiers):
    row = {"site": name, "url": url, "tiers": {}}
    for tier in tiers:
        t = time.time()
        try:
            if tier == "plain":
                final, _ct, raw = await asyncio.to_thread(reader.fetch, url)
            elif tier == "impersonate":
                final, _ct, raw = await asyncio.to_thread(reader.fetch_impersonate, url)
            else:
                final, html, passed = await b.fetch_rendered(url)
                raw = html.encode()
                if not passed:
                    raise reader.BotWall("challenge not passed")
            title, text = text_of(raw, final)
            # the real page: marker in the body text and a real amount of text (a check page has a title only)
            ok = marker in text and len(text) >= 500 and not reader.is_wall(200, (title + text[:2000]).encode())
            row["tiers"][tier] = {"ok": ok, "sec": round(time.time() - t, 1), "title": title[:80], "chars": len(text)}
        except Exception as exc:  # noqa: BLE001
            row["tiers"][tier] = {"ok": False, "sec": round(time.time() - t, 1), "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        if row["tiers"][tier]["ok"]:
            row["first_ok"] = tier
            break
    row.setdefault("first_ok", None)
    return row


async def main_async(args):
    profile = args.profile or tempfile.mkdtemp(prefix="antibot-profile-")
    b = br.Browser(br.BrowserConfig(profile_dir=profile, executable_path=args.executable, headless=not args.headed,
                                    challenge_wait=args.wait))
    rows = []
    try:
        for name, url, marker in SITES:
            if args.only and name not in args.only:
                continue
            r = await probe(name, url, marker, b, args.tiers)
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    finally:
        await b.close()
    egress = {}
    try:
        import urllib.request
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as resp:
            j = json.load(resp)
            egress = {"org": j.get("org"), "country": j.get("country")}  # no IP address stored
    except Exception:  # noqa: BLE001
        pass
    out = {"when": time.strftime("%Y-%m-%d %H:%M"), "host": socket.gethostname(), "egress": egress,
           "headed": args.headed, "rows": rows}
    if args.out:
        args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("summary", {r["site"]: r["first_ok"] for r in rows}, egress)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tiers", nargs="*", default=["plain", "impersonate", "browser"])
    ap.add_argument("--headed", action="store_true", help="show the browser window (needs a desktop or Xvfb)")
    ap.add_argument("--executable", default=os.environ.get("BROWSER_EXECUTABLE", ""))
    ap.add_argument("--profile", default="", help="browser profile dir; reuse it to keep clearance cookies")
    ap.add_argument("--wait", type=float, default=45)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
