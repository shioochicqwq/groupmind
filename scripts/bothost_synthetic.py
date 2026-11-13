"""End-to-end check of bothost with made-up chat: a fake protocol side on one end, the real harness and a real
model on the other. Needs QQBOT_LLM_API_KEY in the environment.

    python scripts/bothost_synthetic.py <empty work dir> <model> <llm base url>
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import websockets

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from bothost.store import Store  # noqa: E402

PORT, GROUP, GROUP2, OTHER_GROUP, BOT, TOKEN = 6299, "100001", "100002", "100003", "20000", "synthetic-token"
NOW = int(time.time())


class Fake:
    """Plays the protocol side: pushes events, answers send actions, remembers what was sent."""

    def __init__(self, ws) -> None:
        self.ws, self.sent, self.answer, self.mid = ws, [], True, 5000
        self.task = asyncio.create_task(self.pump())

    async def pump(self) -> None:
        async for raw in self.ws:
            act = json.loads(raw)
            self.mid += 1
            self.sent.append({"group": act["params"]["group_id"], "text": act["params"]["message"][0]["data"]["text"], "id": self.mid})
            if self.answer:
                await self.ws.send(json.dumps({"status": "ok", "retcode": 0, "data": {"message_id": self.mid}, "echo": act["echo"]}))

    async def say(self, name: str, text: str, *, at=False, reply="", group=GROUP) -> None:
        self.mid += 1
        segs = ([{"type": "reply", "data": {"id": reply}}] if reply else []) + ([{"type": "at", "data": {"qq": BOT}}] if at else [])
        segs.append({"type": "text", "data": {"text": text}})
        await self.ws.send(json.dumps({"post_type": "message", "message_type": "group", "self_id": int(BOT), "group_id": int(group),
                                       "message_id": self.mid, "time": int(time.time()), "user_id": abs(hash(name)) % 10**6 + 1000,
                                       "sender": {"nickname": name}, "message": segs}))

    async def settle(self, usage: Path, turns: int, timeout=600) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if usage.exists() and len(usage.read_text().splitlines()) >= turns:
                return
            await asyncio.sleep(0.5)
        raise SystemExit(f"turn {turns} did not finish in {timeout}s")


async def connect(token=TOKEN):
    return await websockets.connect(f"ws://127.0.0.1:{PORT}/ws", additional_headers={"Authorization": f"Bearer {token}", "X-Self-ID": BOT})


def start(cfg: Path, log: Path) -> subprocess.Popen:
    env = {**os.environ, "QQBOT_ONEBOT_TOKEN": TOKEN}
    return subprocess.Popen([sys.executable, "-m", "bothost", str(cfg)], cwd=REPO, env=env, stdout=open(log, "ab"), stderr=subprocess.STDOUT)


async def main(work: Path, model: str, base_url: str) -> None:
    data = work / "data"
    data.mkdir(parents=True)
    cfg = work / "config.json"
    cfg.write_text(json.dumps({"data_dir": str(data), "bot_names": ["小岚"], "groups": {GROUP: "g-test", GROUP2: "g-two"}, "model": model,
                               "llm_base_url": base_url, "listen_port": PORT, "debounce_s": 1.5, "send_timeout_s": 4}))
    # Old chat that is too far back for the start-of-session recap, so answering needs the search tool.
    store = Store(data / "memory.db")
    store.add("g-test", "1", NOW - 30 * 86400, "1001", "阿橘", "我家猫叫年糕，是只三花，去年冬天在车棚捡的")
    for i in range(60):
        store.add("g-test", str(2 + i), NOW - 20 * 86400 + i * 60, "1002", "木头", f"打卡第 {i + 1} 天")
    del store

    usage, checks = data / "usage.jsonl", []
    def check(name: str, ok: bool, detail="") -> None:
        checks.append(ok)
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

    host = start(cfg, work / "host.log")
    await asyncio.sleep(4)
    try:
        try:
            bad = await connect("wrong")
            await bad.recv()
            check("wrong token is rejected", False)
        except Exception:
            check("wrong token is rejected", True)

        f = Fake(await connect())
        await f.say("木头", "周六晚上八点打羽毛球，体育馆三号场，谁来")
        await f.say("小满", "我来，带两筒球")
        await f.say("路人", "小岚 出来", group=OTHER_GROUP)
        await asyncio.sleep(5)
        check("no trigger, no turn", not usage.exists() and not f.sent)

        await f.say("阿橘", "周六几点打球来着", at=True)
        await f.say("豆包", "用一个字回答：晴天的天空是什么颜色", at=True, group=GROUP2)
        await f.settle(usage, 2)
        one = [x["text"] for x in f.sent if str(x["group"]) == GROUP]
        two = [x["text"] for x in f.sent if str(x["group"]) == GROUP2]
        check("@ -> one turn, answer from the batch", len(one) >= 1 and ("八" in one[-1] or "8" in one[-1]), " | ".join(one))
        check("second group answered in its own group only", len(two) >= 1 and "蓝" in two[-1] and not any("蓝" in x for x in one), " | ".join(two))
        r = [json.loads(x) for x in usage.read_text().splitlines()]
        t = [time.mktime(time.strptime(x["started"], "%Y-%m-%d %H:%M:%S")) for x in r]
        check("the two groups ran side by side", r[0]["group"] != r[1]["group"] and max(t) < min(t[0] + r[0]["seconds"], t[1] + r[1]["seconds"]),
              f"{r[0]['group']} {r[0]['seconds']}s, {r[1]['group']} {r[1]['seconds']}s")
        rss = subprocess.run("ps -o rss= --ppid %d" % host.pid, shell=True, capture_output=True, text=True).stdout.split()
        print("harness processes (MiB):", [int(x) // 1024 for x in rss], flush=True)
        n = len(f.sent)

        await f.say("小满", "那阿橘家的猫叫什么名字", reply=str([x for x in f.sent if str(x["group"]) == GROUP][-1]["id"]))
        await f.settle(usage, 3)
        check("reply to the bot -> turn, answer needs search", len(f.sent) > n and "年糕" in f.sent[-1]["text"], f.sent[-1]["text"] if len(f.sent) > n else "")
        n = len(f.sent)

        await f.say("豆包", "我记得有人说过在车棚捡了只猫，那只猫叫什么来着", at=True, group=GROUP2)
        await f.settle(usage, 4)
        check("recall reaches the other group's history", len(f.sent) > n and "年糕" in f.sent[-1]["text"], f.sent[-1]["text"] if len(f.sent) > n else "")
        n = len(f.sent)

        await f.say("木头", "今天食堂的面还行")
        await f.say("阿橘", "嗯嗯")
        await asyncio.sleep(5)
        check("chatter after a turn stays quiet", len(f.sent) == n and len(usage.read_text().splitlines()) == 4)

        f.answer = False
        await f.say("木头", "小岚 帮我算下 37 乘 43")
        await f.settle(usage, 5)
        got = [s for s in f.sent[n:]]
        check("name -> turn; unanswered send is not repeated", len(got) == 1 and "1591" in got[0]["text"], " | ".join(s["text"] for s in got))
        f.answer = True
        n = len(f.sent)
        await f.ws.close()

        host.terminate()
        host.wait(60)
        host = start(cfg, work / "host.log")
        await asyncio.sleep(4)
        f = Fake(await connect())
        await f.say("小满", "刚才那个乘法的结果再加 9 是多少", at=True)
        await f.settle(usage, 6)
        check("after a restart the session still has its history", any("1600" in x["text"] for x in f.sent), " | ".join(x["text"] for x in f.sent))
        await f.ws.close()
    finally:
        host.terminate()
        host.wait(60)
    rows = [json.loads(x) for x in usage.read_text().splitlines()]
    print("turns:", json.dumps([{k: r[k] for k in ("group", "lines", "sent", "calls", "prompt", "completion", "seconds", "error") if k in r} for r in rows]))
    print("total:", sum(r["calls"] for r in rows), "calls,", sum(r["prompt"] for r in rows), "in,", sum(r["completion"] for r in rows), "out")
    raise SystemExit(0 if all(checks) else 1)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
