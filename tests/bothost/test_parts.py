from bothost.onebot import parse_group_message
from bothost.store import Store


def event(segments, **extra):
    return {"post_type": "message", "message_type": "group", "self_id": 20000, "group_id": 100001, "message_id": 7,
            "time": 1700000000, "user_id": 1001, "sender": {"card": "", "nickname": "阿橘"}, "message": segments, **extra}


def test_parse_marks_at_and_reply_and_keeps_placeholders():
    m = parse_group_message(event([{"type": "reply", "data": {"id": "55"}}, {"type": "at", "data": {"qq": "20000"}},
                                   {"type": "text", "data": {"text": " 看这个 "}}, {"type": "image", "data": {}}]))
    assert (m.at_me, m.reply_to, m.text, m.name) == (True, "55", "看这个 [图片]", "阿橘")
    assert parse_group_message({"post_type": "meta_event"}) is None
    assert parse_group_message(event([{"type": "at", "data": {"qq": "999"}}])).at_me is False


def test_store_ranks_like_the_bench_bm25_and_follows_live_messages(tmp_path):
    from bench.retrievers.bm25 import BM25
    from bench.schema import Block
    from bench.tokenize import make_jieba

    texts = ["我家猫叫年糕，是只三花", "周六打羽毛球，体育馆三号场", "年糕好吃，年糕要蘸糖", "猫 猫 猫", "打卡", "体育馆的羽毛球场要预约", "好的"]
    s = Store(tmp_path / "m.db")
    for i, t in enumerate(texts):
        s.add("b" if i % 3 == 0 else "a", str(i), 100 + i, "bot" if t == "好的" else str(i % 3), "某人", t, "3" if i == 4 else "")
    ref = BM25([Block(str(i + 1), (), 100 + i, "", t) for i, t in enumerate(texts)], make_jieba())
    for q in ("年糕", "猫叫什么", "羽毛球 体育馆", "年糕 年糕 猫"):
        want = [(int(b.block_id), round(sc, 3)) for b, sc in ref.search(q, float("inf"), 5)]
        assert [(h["id"], h["score"]) for h in s.search(q, 5)] == want and want
    assert {h["chat"] for h in s.search("年糕", 5)} == {"a", "b"}   # all groups by default
    assert [h["chat"] for h in s.search("年糕", 5, groups=("b",))] == ["b"] and [h["chat"] for h in s.search("年糕", 5, exclude=("b",))] == ["a"]
    assert s.search("年糕", 5, as_of=101) == [h for h in s.search("年糕", 5) if h["id"] == 1]
    assert [r["hit"] for r in s.search("打卡", 1, around=1)[0]["lines"]] == [False, True, False]   # neighbours come from the same group
    assert s.is_from("b", "6", "bot") and not s.is_from("b", "0", "bot") and not s.is_from("a", "6", "bot")
    assert s.recent("b", 2)[-1]["text"] == "好的" and Store(tmp_path / "m.db").index_missing() == 0
    # a live account linked to an imported person is that person, not a new one
    s.db.execute("INSERT INTO person_account VALUES ('qq', '10001', (SELECT id FROM person WHERE platform_uid = '1'))")
    people = s.db.execute("SELECT count(*) FROM person").fetchone()[0]
    s.add("a", "7", 200, "10001", "某人", "又来了")
    assert s.db.execute("SELECT count(*) FROM person").fetchone()[0] == people and s.is_from("a", "7", "10001") and s.is_from("a", "1", "10001")
