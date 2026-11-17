"""Session handoff (bothost/handoff.py): acceptance tests T1-T10 of the handoff plan.

The turn-level tests run a real harness process against a scripted model (tests/bothost/handoff_rig.py), so they
check what each session was actually shown. The rest test the pieces: page reading's escalation point, the
coordinator's pointer and task records.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from bothost import handoff, web
from bothost.handoff import Handoff, Origin
from plugins.astrbot_plugin_web_reader import tiers
from plugins.astrbot_plugin_web_reader.reader import BotWall
from plugins.astrbot_plugin_web_reader.sites import Sites
from tests.bothost.handoff_rig import HAVE_DSH, Rig, call, dangling, newest, text_of

needs_dsh = pytest.mark.skipif(not HAVE_DSH, reason="the harness (dsh) is not installed")
PAGE = "<html><body><article>" + "<p>页面正文，讲的是一件事。</p>" * 40 + "</article></body></html>"


# ---- page reading: where the handoff hook is called (T1, T2, T3 for pages) ----

class FakeBrowser:
    def __init__(self, log):
        self.log, self.cfg, self.why = log, type("C", (), {"engine": "chrome"})(), ""

    async def fetch_rendered(self, url):
        self.log.append("browser")
        return url, PAGE, True

    async def close(self):
        pass


def reading(monkeypatch, l1: str | None, l2: str):
    """Page reading with each tier stood in for. l1: the endpoint's text (None: it fails); l2: "ok", "wall" or "thin"."""
    log = []

    async def endpoint(url, key, body, timeout=30.0):
        log.append("l1")
        return {"title": "t", "content": l1} if l1 else "失败：页面读不到（HTTP 404）。"

    def request(url):
        log.append("l2")
        if l2 == "wall":
            raise BotWall("check page")
        return url, "text/html", (PAGE if l2 == "ok" else "<html><body>.</body></html>").encode()

    monkeypatch.setattr(web, "_call", endpoint)
    monkeypatch.setattr(tiers, "fetch_impersonate", request)
    monkeypatch.setattr(web, "_browser", FakeBrowser(log))
    monkeypatch.setattr(web, "_sites", Sites())   # in memory only
    monkeypatch.setattr(web, "_close_later", lambda: None)

    async def hook(kind, url):
        log.append(f"handoff:{kind}")
    return log, hook


async def fetch_with(hook, url):
    token = web.ESCALATE.set(hook)
    try:
        return await web.fetch("key", url)
    finally:
        web.ESCALATE.reset(token)


def test_t1_endpoint_or_request_tier_reading_does_not_hand_over(monkeypatch):
    log, hook = reading(monkeypatch, "正文" * 50, "ok")
    assert "正文" in asyncio.run(fetch_with(hook, "https://a.example/p")) and log == ["l1"]
    log, hook = reading(monkeypatch, None, "ok")
    assert "页面正文" in asyncio.run(fetch_with(hook, "https://a.example/p")) and log == ["l1", "l2"]


def test_t2_request_tier_failing_hands_over_before_the_browser_and_the_result_still_comes_back(monkeypatch):
    for l2 in ("wall", "thin"):
        log, hook = reading(monkeypatch, None, l2)
        out = asyncio.run(fetch_with(hook, "https://wall.example/p"))
        assert log == ["l1", "l2", "handoff:l3", "browser"] and "页面正文" in out
        assert web._sites.has("browser_first", "https://wall.example/x")   # learned: next time straight to the browser


def test_t3_site_known_to_need_a_browser_hands_over_before_any_request(monkeypatch):
    log, hook = reading(monkeypatch, None, "ok")
    web._sites.add("browser_first", "rateyourmusic.com")
    assert Sites().has("browser_first", "https://rateyourmusic.com/release/album/x/y/")   # shipped in sites.json
    out = asyncio.run(fetch_with(hook, "https://rateyourmusic.com/release/album/x/y/"))
    assert log == ["handoff:known_l3", "browser"] and "页面正文" in out


# ---- the coordinator (T7, T8) ----

def origin():
    return Origin("55", 1700000000, "阿橘", "看看这个")


def test_t7_one_successor_per_call_and_only_the_active_session_can_hand_over(tmp_path):
    h = Handoff(tmp_path / "h.db")
    assert h.active("g1", "g1") == "g1"
    forks = []

    async def fork(child):
        forks.append(child)

    async def go():
        first = await h.hand_over("g1", "g1", "call_1", "video", "u", origin(), fork)
        again = await h.hand_over("g1", "g1", "call_1", "video", "u", origin(), fork)   # the same call escalating twice
        other = await h.hand_over("g1", "g1", "call_2", "l3", "u2", origin(), fork)     # g1 no longer has the group
        both = await asyncio.gather(*(h.hand_over("g1", "g1-h1", f"c{i}", "l3", "u", origin(), fork) for i in range(5)))
        return first, again, other, both
    first, again, other, both = asyncio.run(go())
    assert first == again and first[1] == "g1-h1" and other is None
    assert sum(b is not None for b in both) == 1 and len({b for b in both if b}) == 1   # simultaneous requests: one successor
    assert forks == ["g1-h1", "g1-h2"] and h.active("g1", "g1") == "g1-h2"
    assert h.state("g1") == "DETACHED" and h.state("g1-h1") == "DETACHED" and h.state("g1-h2") == "ACTIVE"


def test_t8_failed_copy_keeps_the_session_and_a_restart_fails_running_tasks(tmp_path):
    h = Handoff(tmp_path / "h.db", max_tasks=1)
    h.active("g1", "g1")

    async def broken(child):
        raise RuntimeError("cannot open")

    async def ok(child):
        pass
    assert asyncio.run(h.hand_over("g1", "g1", "c1", "video", "u", origin(), broken)) is None
    assert h.active("g1", "g1") == "g1" and h.state("g1") == "ACTIVE"
    task, child = asyncio.run(h.hand_over("g1", "g1", "c2", "video", "u", origin(), ok))
    assert asyncio.run(h.hand_over("g1", child, "c3", "video", "u", origin(), ok)) is None   # over the task limit: runs the old way
    again = Handoff(tmp_path / "h.db")   # the process stopped and started
    assert again.recover() == 1 and not again.running(task) and again.active("g1", "g1") == child
    notes, _ = again.notes("g1")
    assert "没做成" in notes[-1] and "重启" in notes[-1]
    assert not again.finish(task, True, "迟到的回复", {}, sent=True)   # a late result of a closed task is dropped


def test_wrap_up_parsing():
    reply, summary = handoff.parse_wrap_up('【回复】看完了，挺好笑\n【摘要】{"task": "看视频", "observed": ["猫"]}')
    assert reply == "看完了，挺好笑" and summary["observed"] == ["猫"]
    assert handoff.parse_wrap_up("【回复】无\n【摘要】{}")[0] == ""
    assert handoff.parse_wrap_up("随便写了点")[1] == {"unstructured": "随便写了点"}


# ---- whole turns with a real harness (T3 video, T4, T5, T6, T7, T8, T9, T10) ----

@needs_dsh
def test_t3_t4_t5_t7_t9_t10_video_hands_over_and_the_result_comes_back_once(tmp_path):
    async def go():
        async with Rig(tmp_path) as r:
            asked = r.say("阿橘", "看看这个视频 " + call("send_group_message", text="我去看看")
                          + call("watch_video", url="https://v.example/TRY-SEND", question="讲了什么"))
            await r.until(lambda: r.host.watcher.started)
            url, _, tasks_then = r.host.watcher.started[0]
            assert len(tasks_then) == 1   # T3: handed over before the video started
            a, b = tasks_then[0]["session"], tasks_then[0]["successor"]
            assert r.active() == b and r.conn.texts() == ["我去看看"]
            # T4: the group goes on with the new session while the video is still running
            r.say("小林", "在吗 " + call("send_group_message", text="在"))
            await r.until(lambda: "在" in r.conn.texts())
            assert not any(e.is_set() for e in r.host.watcher.done.values())   # the video is still running
            b_first = r.model.asked("在吗")[0]
            r.finish_video(url)
            await r.until(lambda: r.tasks()[0]["status"] != "running")
            # T5, T7: one reply, quoting the message that asked; the background session's own try to talk was refused
            assert r.conn.quoted() == [(asked, r.conn.texts()[-1])] and r.conn.texts()[-1].startswith("结果是")
            assert "偷偷说一句" not in r.conn.texts() and r.tasks()[0]["status"] == "completed"
            assert ("impression", "爱发视频", "handoff") in [tuple(x) for x in r.host.store.db.execute(
                "SELECT kind, value, source FROM person_fact")]   # people met during the task are kept from its account
            r.say("小林", "然后呢")
            await r.until(lambda: r.model.asked("然后呢") and r.idle())
            b_next = r.model.asked("然后呢")[0]
            told = text_of(b_next["messages"][newest(b_next["messages"])])
            assert "后台看视频" in told and "阿橘" in told and "已经引用" in told and "候选事实" in told   # T5
            # T9: no session was ever shown a call without its result; the new one never saw the video call
            assert all(not dangling(q["messages"]) for q in r.model.requests)
            assert not any("watch_video" in json.dumps(m.get("tool_calls") or []) for m in b_first["messages"])
            # T10: A's request just before it made the video call is, whole, the start of B's first request
            # (same system prompt, tools and history: the provider's prefix cache applies); the video's text stayed in A
            a_before = next(q for q in r.model.requests if q["messages"][-1]["role"] == "tool" and "已发送" in str(q["messages"][-1]["content"]))
            assert b_first["messages"][:len(a_before["messages"])] == a_before["messages"] and b_first.get("tools") == a_before.get("tools")
            assert not any("很长的画面描述" * 3 in json.dumps(q["messages"], ensure_ascii=False) for q in (b_first, b_next))   # only the short account came over
            assert a != b and r.host.handoff.state(a) == "RETIRED"
    asyncio.run(go())


@needs_dsh
def test_t6_second_handoff_and_results_out_of_order_reach_the_session_active_then(tmp_path):
    async def go():
        async with Rig(tmp_path) as r:
            first = r.say("阿橘", "这个呢 " + call("watch_video", url="https://v.example/1", question="讲了什么"))
            await r.until(lambda: len(r.host.watcher.started) == 1 and r.idle())
            second = r.say("小林", "还有这个 " + call("watch_video", url="https://v.example/2", question="讲了什么"))
            await r.until(lambda: len(r.host.watcher.started) == 2 and r.idle())
            t1, t2 = r.tasks()
            assert t2["session"] == t1["successor"] and r.active() == t2["successor"]   # A -> B -> C
            r.finish_video("https://v.example/2")   # the later task finishes first
            await r.until(lambda: r.tasks()[1]["status"] == "completed")
            r.finish_video("https://v.example/1")
            await r.until(lambda: r.tasks()[0]["status"] == "completed")
            assert [q[0] for q in r.conn.quoted()] == [second, first]
            r.say("小林", "好的")
            await r.until(lambda: r.model.asked("好的") and r.idle())
            q = r.model.asked("好的")[0]
            told = text_of(q["messages"][newest(q["messages"])])
            assert told.index("v.example/2") < told.index("v.example/1")   # in the order they finished
            assert r.active() == t2["successor"] and json.loads(r.events("task_completed")[0]["payload"])["detail"].endswith("/2")
    asyncio.run(go())


@needs_dsh
def test_t8_harness_lost_mid_task_marks_it_failed_and_the_group_keeps_its_session(tmp_path):
    async def go():
        async with Rig(tmp_path) as r:
            r.say("阿橘", "看 " + call("watch_video", url="https://v.example/1", question="讲了什么"))
            await r.until(lambda: r.host.watcher.started and r.idle())
            active = r.active()
            await r.group.dsh.kill()   # the process dies (crash, out of memory)
            await r.until(lambda: r.tasks()[0]["status"] == "failed")
            r.say("小林", "还在吗 " + call("send_group_message", text="在的"))
            await r.until(lambda: "在的" in r.conn.texts() and r.idle())
            q = r.model.asked("还在吗")[0]
            told = text_of(q["messages"][newest(q["messages"])])
            assert r.active() == active and "没做成" in told
    asyncio.run(go())


@needs_dsh
def test_switch_off_keeps_the_old_serial_behaviour(tmp_path):
    async def go():
        async with Rig(tmp_path, handoff=False) as r:
            r.say("阿橘", "看 " + call("watch_video", url="https://v.example/1", question="讲了什么"))
            await r.until(lambda: r.host.watcher.started)
            r.say("小林", "在吗 " + call("send_group_message", text="在"))
            await asyncio.sleep(1.5)
            assert "在" not in r.conn.texts()   # the slow call holds the group
            r.finish_video("https://v.example/1")
            await r.until(lambda: "在" in r.conn.texts() and r.idle())
            assert r.conn.quoted() == [] and not (r.cfg.data_dir / "handoff.db").exists()
    asyncio.run(go())


@needs_dsh
def test_t2_page_needing_the_browser_hands_over_inside_a_look_up_and_the_page_returns_to_the_old_session(tmp_path, monkeypatch):
    log, _ = reading(monkeypatch, None, "wall")
    let_go = asyncio.Event()

    class SlowBrowser(FakeBrowser):
        async def fetch_rendered(self, url):
            log.append(("browser", len(rig.tasks())))
            await let_go.wait()
            return url, PAGE, True

    class Lookups:   # the helper conversation, reduced to reading the two pages it is asked about
        async def ask(self, question, follow_up=""):
            pages = [await web.fetch("key", u) for u in question.split()[1:]]
            return "\n".join(p[:40] for p in pages), {"calls": 1, "prompt": 1, "cached": 0, "completion": 1, "web_calls": 2, "seconds": 0.1}

    async def go():
        global rig
        async with Rig(tmp_path, search_api_key="key") as rig:
            monkeypatch.setattr(web, "_browser", SlowBrowser(log))
            rig.host.lookups = Lookups()
            asked = rig.say("阿橘", "查查 " + call("look_up", question="读 https://wall.example/a https://wall.example/b"))
            await rig.until(lambda: ("browser", 1) in log)
            assert log[:3] == ["l1", "l2", ("browser", 1)] and rig.active() != "g1"   # handed over before the browser started
            rig.say("小林", "在吗 " + call("send_group_message", text="在"))
            await rig.until(lambda: "在" in rig.conn.texts())
            let_go.set()
            await rig.until(lambda: rig.tasks()[0]["status"] == "completed")
            assert len(rig.tasks()) == 1 and log.count(("browser", 1)) == 2   # the second page: known now, no second handoff
            assert rig.conn.quoted() == [(asked, rig.conn.texts()[-1])] and "经浏览器读取" in rig.conn.texts()[-1]   # the browser's page reached the old session
    asyncio.run(go())


@needs_dsh
def test_retired_sessions_leave_memory_however_long_the_chain(tmp_path):
    async def go():
        async with Rig(tmp_path) as r:
            for i in range(4):   # four handoffs one after another: A -> B -> C -> D -> E
                r.say("阿橘", f"看{i} " + call("watch_video", url=f"https://v.example/{i}", question="讲了什么"))
                await r.until(lambda: len(r.host.watcher.started) == i + 1 and r.idle())
                r.finish_video(f"https://v.example/{i}")
                await r.until(lambda: r.tasks()[i]["status"] == "completed" and not r.group.turns)
            stats = await r.group.dsh.plugin("stats")
            assert stats["open"] == [r.active()] and r.active().endswith("-h4")   # only the session that has the group
            assert all(r.host.handoff.state(t["session"]) == "RETIRED" for t in r.tasks())
    asyncio.run(go())


@needs_dsh
def test_no_time_limit_on_a_turn_and_a_stalled_session_alone_is_cancelled(tmp_path):
    async def go():
        async with Rig(tmp_path, search_api_key="key", turn_timeout_s=1.0, stall_s=2.0) as r:
            class Slow:   # a look-up that reads fine without a browser: no handoff, the group's own turn just takes long
                async def ask(self, question, follow_up=""):
                    await asyncio.sleep(4)
                    return "查到了", {"calls": 1, "seconds": 4}
            r.host.lookups = Slow()
            r.say("阿橘", "查 " + call("look_up", question="一个问题") + call("send_group_message", text="查完了"))
            await r.until(lambda: "查完了" in r.conn.texts() and r.idle())   # 4 s turn with turn_timeout_s = 1: not cut
            pid = r.group.dsh.proc.pid
            r.say("小林", "卡住 [[hang]]")
            await r.until(lambda: r.idle(), 20)   # stands still for stall_s: that session alone is cancelled
            r.say("小林", "还在吗 " + call("send_group_message", text="在"))
            await r.until(lambda: "在" in r.conn.texts() and r.idle())
            rows = [json.loads(x) for x in (r.cfg.data_dir / "usage.jsonl").read_text().splitlines()]
            assert r.group.dsh.proc.pid == pid and [x.get("error") for x in rows] == [None, "stalled", None]
    asyncio.run(go())


@needs_dsh
def test_shadow_mode_answers_every_message_and_sends_nothing(tmp_path):
    async def go():
        async with Rig(tmp_path, shadow=True, shadow_forward_to="5555") as r:
            r.say("阿橘", "随便聊聊 " + call("send_group_message", text="我也觉得"), at=False)   # nobody calls the bot
            await r.until(lambda: (r.cfg.data_dir / "shadow.jsonl").exists() and r.idle())
            kept = [json.loads(x) for x in (r.cfg.data_dir / "shadow.jsonl").read_text().splitlines()]
            assert [k["text"] for k in kept] == ["我也觉得"] and r.conn.sent == []
            assert not r.host.store.db.execute("SELECT 1 FROM message WHERE text = '我也觉得'").fetchone()   # not in the record either
            [(action, dm)] = r.conn.other   # shown privately to the one account, with the line it answers
            text = dm["message"][0]["data"]["text"]
            assert action == "send_private_msg" and dm["user_id"] == 5555 and text.startswith("【影子·g1】我也觉得") and "随便聊聊" in text
    asyncio.run(go())
