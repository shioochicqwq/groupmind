"""People the bot learns by itself (bothost/people.py): finding a person by the name shown in a chat, facts with history
and undo, the 【人物】 section of a compaction note, and, with a real harness, the tools and the block appended to a turn."""
from __future__ import annotations

import asyncio
import json

import pytest

from bothost import people
from bothost.store import Store
from tests.bothost.handoff_rig import HAVE_DSH, Rig, call, newest, text_of

needs_dsh = pytest.mark.skipif(not HAVE_DSH, reason="the harness (dsh) is not installed")


def store(tmp_path):
    s = Store(tmp_path / "m.db")
    s.add("a", "1", 100, "u1", "阿青(123456789)", "早")     # a display name carrying a number
    s.add("a", "2", 200, "u1", "阿青", "在吗")
    s.add("a", "3", 300, "u2", "阿橘", "看猫")
    s.add("b", "4", 400, "u2", "橘子皮", "别的群")
    s.add("b", "5", 500, "u3", "阿青", "同名的另一个人")
    return s


def pid(s, uid):
    return s.db.execute("SELECT id FROM person WHERE platform_uid = ?", (uid,)).fetchone()[0]


def test_resolve_prefers_this_chat_then_nicknames_then_any_chat(tmp_path):
    s = store(tmp_path)
    assert people.resolve(s.db, "阿青", "a") == [pid(s, "u1")]                  # this chat first, though u3 uses it in b
    assert people.resolve(s.db, "阿青", "b")[0] == pid(s, "u3")
    assert people.resolve(s.db, "橘子皮", "a") == [pid(s, "u2")]               # shown so in another chat
    assert people.resolve(s.db, "没人", "a") == []
    people.add(s.db, pid(s, "u1"), "alias", "小猫", "tool", "a")
    assert people.resolve(s.db, "小猫", "a") == [pid(s, "u1")]                 # a learned nickname


def test_facts_replace_accumulate_and_undo(tmp_path):
    s = store(tmp_path)
    p = pid(s, "u1")
    first = people.add(s.db, p, "impression", "话少", "tool", "a")
    second = people.add(s.db, p, "impression", "其实挺能聊", "compaction", "a")
    assert people.add(s.db, p, "impression", "其实挺能聊", "tool", "a") is None   # nothing new
    people.add(s.db, p, "alias", "小猫", "tool", "a")
    people.add(s.db, p, "alias", "猫猫", "tool", "a")
    assert people.current_facts(s.db, p)["impression"] == "其实挺能聊" and people.current_facts(s.db, p)["aliases"] == ["小猫", "猫猫"]
    assert people.undo(s.db, second) and people.current_facts(s.db, p)["impression"] == "话少"   # the older one is back
    assert first and people.entry(s.db, p) == "- 群里显示为：阿青；外号：小猫、猫猫；印象：话少"
    assert "后来认识的人" in people.learned_section(s.db)


def test_people_section_of_a_note_and_unknown_names(tmp_path):
    s = store(tmp_path)
    note = "刚才在聊猫。\n\n【人物】\n- 阿青｜外号：小猫｜态度：挺喜欢\n阿橘｜印象：爱发猫图｜外号：无\n路人甲｜印象：不认识\n"
    rows = people.parse_section(note)
    assert rows == [{"name": "阿青", "alias": "小猫", "attitude": "挺喜欢"}, {"name": "阿橘", "impression": "爱发猫图"},
                    {"name": "路人甲", "impression": "不认识"}]
    got = people.apply(s.db, rows, "compaction", "a")
    assert got == {"recorded": 3, "unknown": ["路人甲"], "ambiguous": []}
    entries, upto = people.changed_since(s.db, 0)
    assert len(entries) == 2 and upto == people.latest_id(s.db) and people.changed_since(s.db, upto) == ([], upto)
    assert people.parse_section("没有人物这一段") == []


@needs_dsh
def test_the_bot_notes_a_person_sees_it_appended_next_turn_and_looks_people_up(tmp_path):
    async def go():
        async with Rig(tmp_path, handoff=False) as r:
            r.say("小林", "叫她小猫就行 " + call("note_person", name="阿橘", alias="小猫", impression="爱发猫图"), at=True)
            await r.until(lambda: r.idle() and r.model.asked("叫她小猫"))
            r.say("阿橘", "我来了")   # 阿橘 speaks, so the name is known to the store before the tool resolves it next time
            await r.until(lambda: r.idle() and r.model.asked("我来了"))
            r.say("小林", "再记一次 " + call("note_person", name="阿橘", alias="小猫", impression="爱发猫图"), at=True)
            await r.until(lambda: r.idle() and r.model.asked("再记一次"))
            r.say("小林", "小猫是谁 " + call("who_is", name="小猫"), at=True)
            await r.until(lambda: r.idle() and len(r.model.asked("小猫是谁")) >= 2)
            facts = [tuple(x) for x in r.host.store.db.execute("SELECT kind, value, source FROM person_fact ORDER BY id")]
            assert ("alias", "小猫", "tool") in facts and ("impression", "爱发猫图", "tool") in facts
            q = r.model.asked("小猫是谁")[0]
            told = text_of(q["messages"][newest(q["messages"])])
            assert told.startswith(people.OPEN) and "外号：小猫" in told   # appended at the start of the next turn, marked
            answer = [m for m in r.model.asked("小猫是谁")[-1]["messages"] if m["role"] == "tool"][-1]
            assert "群里显示为：阿橘" in text_of(answer)
            # a compaction note that ends with a people section
            r.group.dsh.notes_written.setdefault(r.group.last_session, []).append("备忘。\n【人物】\n小林｜态度：靠谱")
            r.say("小林", "好")
            await r.until(lambda: r.idle() and r.model.asked("好"))
            assert ("attitude", "靠谱", "compaction") in [tuple(x) for x in r.host.store.db.execute("SELECT kind, value, source FROM person_fact")]
    asyncio.run(go())


def test_snapshot_people_section_is_split_from_the_fixed_text():
    from bothost.app import split_people
    people_part, rest = split_people("# 快照\n\n## 人物\n- 甲；外号：小甲\n\n## 梗与说法\n- 某梗：意思\n")
    assert people_part.startswith("## 人物\n- 甲") and "梗与说法" in rest and "小甲" not in rest


@needs_dsh
def test_the_people_table_is_rebuilt_when_the_prefix_is_lost_anyway_and_appended_in_between(tmp_path):
    snap = tmp_path / "snapshot.md"
    snap.write_text("# 记忆快照\n\n## 人物\n- 标注的人甲\n\n## 梗与说法\n- 某梗：意思\n", encoding="utf-8")

    async def go():
        async with Rig(tmp_path, handoff=False, snapshot_file=str(snap)) as r:
            db = r.host.store.db
            r.host.store.add("g1", "900", 1, "7001", "老面孔", "以前说过话")
            people.add(db, people.resolve(db, "老面孔", "g1")[0], "impression", "很早就认识", "manual", "g1")
            system = lambda q: text_of(q["messages"][0])
            r.say("小林", "第一句")
            await r.until(lambda: r.idle() and r.model.asked("第一句"))
            first = r.model.asked("第一句")[0]
            assert "标注的人甲" in system(first) and "很早就认识" in system(first) and "某梗" in system(first)   # the whole table at start
            assert people.OPEN not in text_of(first["messages"][newest(first["messages"])])                 # nothing to append yet
            people.add(db, people.resolve(db, "小林", "g1")[0], "alias", "林子", "manual", "g1")
            r.say("小林", "第二句")
            await r.until(lambda: r.idle() and r.model.asked("第二句"))
            second = r.model.asked("第二句")[0]
            assert system(second) == system(first)                                                      # prompt unchanged: cache kept
            assert "外号：林子" in text_of(second["messages"][newest(second["messages"])])               # learned since: appended
            await r.group.refresh_people(r.group.last_session)                                          # what a compaction triggers
            r.say("小林", "第三句")
            await r.until(lambda: r.idle() and r.model.asked("第三句"))
            third = r.model.asked("第三句")[0]
            assert "外号：林子" in system(third)                                                         # folded into the table
            assert people.OPEN not in text_of(third["messages"][newest(third["messages"])])
    asyncio.run(go())


@needs_dsh
@pytest.mark.parametrize("handoff", [False, True])   # the SDK's prompt, and the host plugin's (images stored as attachments)
def test_a_picture_reaches_the_model_and_what_it_saw_is_kept_with_the_message(tmp_path, handoff):
    async def go():
        async with Rig(tmp_path, handoff=handoff, llm_images=True) as r:
            r.host.on_event({"post_type": "message", "message_type": "group", "self_id": 20000, "group_id": 100001, "message_id": 555,
                             "time": 1700000000, "user_id": 4242, "sender": {"card": "阿橘", "nickname": "阿橘"},
                             "message": [{"type": "at", "data": {"qq": "20000"}}, {"type": "text", "data": {"text": "看我家猫"}},
                                         {"type": "image", "data": {"url": f"http://127.0.0.1:{r.llm_port}/img.png"}}]})
            await r.until(lambda: r.idle() and r.model.requests)
            q = r.model.requests[0]
            told = text_of(q["messages"][newest(q["messages"])])
            assert "[图片1]" in told and any(p.get("type") in ("image_url", "image") for m in q["messages"] if isinstance(m.get("content"), list) for p in m["content"])
            await r.until(lambda: "橘猫" in r.host.store.db.execute("SELECT text FROM message WHERE source_msg_id = 'ob:555'").fetchone()[0])
            assert r.host.store.db.execute("SELECT text FROM message WHERE source_msg_id = 'ob:555'").fetchone()[0].endswith(
                "看我家猫[图片：一只橘猫在键盘上睡觉（机器看的）]")
    asyncio.run(go())


@needs_dsh
def test_stickers_are_seen_apart_and_never_hold_the_session_up(tmp_path):
    def sticker_event(r, msg_id, text):
        return {"post_type": "message", "message_type": "group", "self_id": 20000, "group_id": 100001, "message_id": msg_id,
                "time": 1700000000, "user_id": 4242, "sender": {"card": "阿橘", "nickname": "阿橘"},
                "message": [{"type": "at", "data": {"qq": "20000"}}, {"type": "text", "data": {"text": text}},
                            {"type": "image", "data": {"url": f"http://127.0.0.1:{r.llm_port}/img.png", "sub_type": 1}}]}

    async def go():
        async with Rig(tmp_path, handoff=False, llm_images=True, stickers=True) as r:
            r.host.on_event(sticker_event(r, 601, "你看"))
            await r.until(lambda: r.idle() and r.model.asked("你看"))
            first = r.model.asked("你看")[0]
            assert "[表情]" in text_of(first["messages"][newest(first["messages"])]) and r.model.sticker_calls == 1   # did not wait
            assert not any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
                           for m in first["messages"])   # the sticker itself never went to the group's model
            stored = lambda i: r.host.store.db.execute("SELECT text FROM message WHERE source_msg_id = ?", (f"ob:{i}",)).fetchone()[0]
            await r.until(lambda: "翻白眼" in stored(601))
            assert stored(601).endswith("你看[表情：翻白眼，表示无语（机器看的）]")
            r.say("小林", "然后")
            await r.until(lambda: r.idle() and r.model.asked("然后"))
            q = r.model.asked("然后")[0]
            assert "阿橘 刚才发的表情：翻白眼，表示无语" in text_of(q["messages"][newest(q["messages"])])   # told in the next turn
            r.host.on_event(sticker_event(r, 602, "又一个"))   # the same sticker again: from the cache
            await r.until(lambda: "翻白眼" in stored(602))
            assert r.model.sticker_calls == 1
            assert any("sticker" in json.loads(x) for x in (r.cfg.data_dir / "usage.jsonl").read_text().splitlines())   # its use is logged
    asyncio.run(go())
