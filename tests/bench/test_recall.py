"""Recall markers and the recall policy (synthetic text only)."""
from bench.recall import markers, policy
from bench.recall.run_link import parse
from bench.schema import Block, Message

DAY = 86400.0


def msg(i, author, ts, text, reply_to=None):
    return Message(f"m{i}", "g", author, ts, text, reply_to)


def test_markers_catch_recall_phrases_and_skip_plain_chat():
    assert "remember" in markers.categories("我记得你上次说过要去")
    assert "laizhe" in markers.categories("那个叫什么来着")
    assert markers.categories("今天吃什么") == []


def test_program_like_account_is_found_by_format():
    human = [msg(i, "a", i, "好的") for i in range(30)]
    bot = [msg(100 + i, "b", i, "**标题**\n- 第一点\n- 第二点" * 5) for i in range(30)]
    assert markers.program_like(human + bot) == {"b"}


def test_grain_follows_the_impression_not_the_age():
    assert policy.grain("深", False, False, False) == "原话"
    assert policy.grain("中", False, False, False) == "大意"
    assert policy.grain("", False, False, False) == "不出现"       # no impression, however recent beyond a day
    assert policy.grain("", True, False, False) == "有这回事"      # the bot took part: one grain clearer
    assert policy.grain("浅", False, True, False) == "大意"        # talked about again later
    assert policy.grain("", False, False, True) == "大意"          # still present to mind


def test_decide_impressions_lookup_and_render():
    ms = [msg(1, "x", 0, "平常的话"), msg(2, "y", 10, "那句谁都忘不了的话"), msg(3, "y", 20, "接着说"),
          msg(4, "y", 30, "别的事"), msg(5, "me", 40, "我插一句")]
    by_id = {m.msg_id: m for m in ms}
    blocks = [Block(f"b{i}", (f"m{i}",), by_id[f"m{i}"].timestamp, "g", "") for i in range(1, 6)]
    deep = {"strength": "深", "gist": "有人说了一句很绝的话", "msg_ids": ["m2", "m3"], "keep": ["m2"], "formed_at": 100}
    known = policy.index([deep, {"strength": "浅", "gist": "泛泛聊过", "msg_ids": ["m3", "m4"], "keep": [], "formed_at": 100}])
    as_of = 60 * DAY
    ev = policy.decide(blocks, by_id, known, {}, me="me", as_of=as_of)
    # two months on: no impression is gone, the deep one keeps its line, one impression is told once
    assert [e.tier for e in ev] == ["不出现", "原话", "不出现", "有这回事", "有这回事"]
    text, shown = policy.render(ev, by_id, {"b5": "我说过一句"}, as_of, 500, me="me")
    assert "那句谁都忘不了的话" in text and "接着说" not in text and "平常的话" not in text and len(shown) == 3
    assert policy.decide(blocks, by_id, known, {}, me="me", as_of=50)[1].tier == "大意"  # impression not formed yet; fresh
    looked = policy.decide(blocks, by_id, known, {}, me="me", as_of=as_of, query="帮我查一下聊天记录里他怎么说的")
    assert {e.tier for e in looked} == {"原话"}


def test_impression_references_must_exist():
    from bench.recall.run_impress import parse as read
    text = ('{"impressions": [{"from": 2, "to": 4, "strength": "深", "why": "好笑", "gist": "某事", "keep": [3, 9]},'
            ' {"from": 5, "to": 99, "strength": "中", "gist": "越界"}, {"from": 1, "to": 1, "strength": "中", "keep": [1]}], "usual": "常聊某事"}')
    found, usual = read(text, 10)
    assert [(i["from"], i["to"], i["keep"]) for i in found] == [(2, 4, [3]), (1, 1, [])] and usual == "常聊某事"
    assert read("不是 JSON", 10) is None


def test_link_answer_must_name_an_existing_line():
    assert parse('{"line": "2.3", "fidelity": "一致", "surface": "换了说法", "who": "没提是谁"}', [4, 5])["found"] == 2
    assert parse('{"line": "2.9", "fidelity": "一致"}', [4, 5]) == {"found": 0, "line": 0, "fidelity": "", "surface": "", "who": ""}
    assert parse('{"line": ""}', [4, 5])["found"] == 0
