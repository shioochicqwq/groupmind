"""P0 smoke for the search module: the existing web_reader on static / dynamic / failing pages, and Bilibili public APIs (T0, no login).

Usage: python scripts/search/p0_smoke.py [--warm]   (needs requests, beautifulsoup4, lxml). Re-run on the machine the bot runs on.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "astrbot_plugin_web_reader"))
import requests
import reader

PAGES = [
    ("static-wiki", "https://zh.wikipedia.org/wiki/%E7%96%AF%E7%8B%82%E6%98%9F%E6%9C%9F%E5%9B%9B"),
    ("static-moegirl", "https://zh.moegirl.org.cn/V%E6%88%9150"),
    ("static-baike", "https://baike.baidu.com/item/%E7%96%AF%E7%8B%82%E6%98%9F%E6%9C%9F%E5%9B%9B"),
    ("dynamic-zhihu", "https://www.zhihu.com/question/493219567"),
    ("dynamic-bili-video", "https://www.bilibili.com/video/BV1GJ411x7h7"),
    ("dynamic-bili-search", "https://search.bilibili.com/all?keyword=v%E6%88%9150"),
    ("fail-404", "https://httpbin.org/status/404"),
    ("fail-429", "https://httpbin.org/status/429"),
    ("fail-dns", "https://no-such-host.invalid/"),
    ("blocked-local", "http://127.0.0.1:8317/v1/models"),
]
rows = []
for name, url in PAGES:
    t = time.time()
    try:
        final, ctype, body = reader.fetch(url)
        data = reader.extract(body, final)
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        rows.append({"case": name, "status": "ok", "chars": len(text), "title": (data.get("title") if isinstance(data, dict) else "")[:40],
                     "links": len(data.get("links", [])) if isinstance(data, dict) else None, "head": text[:80].replace("\n", " ")})
    except reader.BlockedURL as e:
        rows.append({"case": name, "status": "blocked", "why": str(e)[:80]})
    except reader.FetchError as e:
        rows.append({"case": name, "status": "fetch_error", "why": str(e)[:120]})
    except Exception as e:
        rows.append({"case": name, "status": "error", "why": f"{type(e).__name__}: {str(e)[:100]}"})
    rows[-1]["sec"] = round(time.time() - t, 2)
for r in rows:
    print(json.dumps(r, ensure_ascii=False))

# T0: Bilibili public APIs, no login.
UA = {"User-Agent": reader.UA, "Referer": "https://www.bilibili.com/"}
SESSION = requests.Session()
if "--warm" in sys.argv:
    w = SESSION.get("https://www.bilibili.com/", headers=UA, timeout=15)   # a normal first visit sets buvid cookies
    print(json.dumps({"warm_http": w.status_code, "warm_cookies": sorted(SESSION.cookies.keys())}))
bv = "BV1GJ411x7h7"
def get(url):
    t = time.time()
    try:
        r = SESSION.get(url, headers=UA, timeout=15)
        try:
            j = r.json()
        except ValueError:
            j = None
        return r.status_code, j, round(time.time() - t, 2)
    except Exception as e:
        return None, {"err": f"{type(e).__name__}"}, round(time.time() - t, 2)
code, view, s = get(f"https://api.bilibili.com/x/web-interface/view?bvid={bv}")
d = (view or {}).get("data") or {}
print(json.dumps({"api": "view", "http": code, "code": (view or {}).get("code"), "sec": s, "title": d.get("title", "")[:30],
                  "duration": d.get("duration"), "aid": d.get("aid"), "cid": d.get("cid"), "has_desc": bool(d.get("desc"))}, ensure_ascii=False))
if d.get("aid"):
    code, tags, s = get(f"https://api.bilibili.com/x/tag/archive/tags?bvid={bv}")
    print(json.dumps({"api": "tags", "http": code, "code": (tags or {}).get("code"), "n": len((tags or {}).get("data") or []), "sec": s}))
    code, pl, s = get(f"https://api.bilibili.com/x/player/v2?aid={d['aid']}&cid={d['cid']}")
    subs = (((pl or {}).get("data") or {}).get("subtitle") or {}).get("subtitles") or []
    print(json.dumps({"api": "player/v2 subtitles", "http": code, "code": (pl or {}).get("code"), "n_subtitles": len(subs), "sec": s}))
    code, rep, s = get(f"https://api.bilibili.com/x/v2/reply?type=1&oid={d['aid']}&sort=1&ps=20&pn=1")
    print(json.dumps({"api": "reply", "http": code, "code": (rep or {}).get("code"), "msg": str((rep or {}).get("message"))[:40],
                      "n": len(((rep or {}).get("data") or {}).get("replies") or []), "sec": s}, ensure_ascii=False))
