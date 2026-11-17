"""Log in to a site inside the bot's own browser, once, by hand.

The bot's browser runs without a screen anyone can see. This opens it on the same profile and serves, on this
machine only, a page that shows what the browser shows and passes on clicks and typing. The login is then kept in
the profile like any cookie: page reading and video downloads use it afterwards.

    python -m bothost.login --profile DATA/browser-profile --url https://passport.bilibili.com/login
    (from your own computer)  ssh -L 3090:127.0.0.1:3090 this-host   then open the printed address

Stop the bot's browser first: two browsers cannot share a profile. Press 完成 when logged in, so the profile is written.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from plugins.astrbot_plugin_web_reader import browser as br

IDLE_S = 900
PAGE = """<!doctype html><meta charset=utf-8><title>bot browser</title>
<style>body{margin:8px;font:14px sans-serif;background:#222;color:#ddd}img{max-width:100%;border:1px solid #555;cursor:crosshair}
input,button{font:inherit;padding:4px 8px;margin:2px}#url{width:40%}#text{width:25%}</style>
<div><input id=url placeholder="网址"><button onclick="go('open',{url:url.value})">打开</button>
<input id=text placeholder="要输入的文字（先点一下页面里的输入框）"><button onclick="go('type',{text:text.value});text.value=''">输入</button>
<button onclick="go('key',{key:'Enter'})">回车</button><button onclick="go('key',{key:'Backspace'})">退格</button>
<button onclick="go('back',{})">后退</button><button onclick="go('done',{}).then(()=>document.body.textContent='已保存，可以关掉这个页面。')">完成</button>
<span id=where></span></div><img id=shot>
<script>
const go=(what,body)=>fetch('do/'+what,{method:'POST',body:JSON.stringify(body)}).then(r=>r.json()).then(j=>{where.textContent=j.url||'';return j});
shot.onclick=e=>{const r=shot.getBoundingClientRect();go('click',{x:(e.clientX-r.left)*shot.naturalWidth/r.width,y:(e.clientY-r.top)*shot.naturalHeight/r.height})};
const tick=()=>{const i=new Image();i.onload=()=>{shot.src=i.src;setTimeout(tick,700)};i.onerror=()=>setTimeout(tick,2000);i.src='shot?'+Date.now()};tick();
</script>"""


def in_use(profile: Path) -> bool:
    """Chrome leaves SingletonLock -> host-pid in a profile it has open."""
    try:
        pid = int(os.readlink(profile / "SingletonLock").rsplit("-", 1)[1])
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


async def serve(profile: str, url: str, port: int, executable: str, xvfb: str) -> None:
    b = br.Browser(br.BrowserConfig(profile_dir=profile, executable_path=executable, xvfb_command=xvfb))
    ctx, done, last = await b.context(), asyncio.Event(), [time.monotonic()]
    await (await b.new_page()).goto(url, wait_until="domcontentloaded")
    page = lambda: ctx.pages[-1]   # a login that opens a window of its own is followed

    async def index(_: Request) -> Response:
        return HTMLResponse(PAGE)

    async def shot(_: Request) -> Response:
        return Response(await page().screenshot(type="jpeg", quality=60), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def do(request: Request) -> Response:
        what, body, last[0] = request.path_params["what"], await request.json(), time.monotonic()
        p = page()
        if what == "click":
            await p.mouse.click(float(body["x"]), float(body["y"]))
        elif what == "type":
            await p.keyboard.type(str(body["text"]), delay=30)
        elif what == "key" and body.get("key") in ("Enter", "Backspace", "Tab", "Escape"):
            await p.keyboard.press(body["key"])
        elif what == "open" and str(body.get("url", "")).startswith(("http://", "https://")):
            await p.goto(body["url"], wait_until="domcontentloaded")
        elif what == "back":
            await p.go_back()
        elif what == "done":
            done.set()
        return JSONResponse({"url": page().url[:120]})

    key = secrets.token_urlsafe(12)   # other accounts on this machine can reach the port, not guess the path
    app = Starlette(routes=[Route(f"/{key}/", index), Route(f"/{key}/shot", shot), Route(f"/{key}/do/{{what}}", do, methods=["POST"])])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.1)
    print(f"open http://127.0.0.1:{port}/{key}/  (forward the port over ssh first); it closes after {IDLE_S // 60} minutes without input", flush=True)
    try:
        while not done.is_set() and not task.done() and time.monotonic() - last[0] < IDLE_S:
            await asyncio.sleep(1)
    finally:
        names = {c["name"] for c in await ctx.cookies(url)}
        server.should_exit = True
        await b.close()   # the profile is written when the browser closes
        print(f"closed; {len(names)} cookies kept for this site", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Log in by hand inside the bot's browser profile.")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", required=True, help="the site's login page")
    ap.add_argument("--port", type=int, default=3090)
    ap.add_argument("--browser-executable", default=os.environ.get("BROWSER_EXECUTABLE", ""))
    ap.add_argument("--xvfb", default=os.environ.get("XVFB_COMMAND", "Xvfb"))
    args = ap.parse_args()
    if in_use(Path(args.profile)):
        raise SystemExit("the profile is open in another browser (the bot's reads pages with it and closes it after a few idle minutes); try again then")
    asyncio.run(serve(args.profile, args.url, args.port, args.browser_executable, args.xvfb))


if __name__ == "__main__":
    main()
