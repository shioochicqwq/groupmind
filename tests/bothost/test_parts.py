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


def test_at_segments_without_a_name_get_the_name_the_account_is_shown_under():
    names = {"30001": "阿橘"}.get
    m = parse_group_message(event([{"type": "at", "data": {"qq": "30001"}}, {"type": "text", "data": {"text": "看这个"}},
                                   {"type": "at", "data": {"qq": "40004"}}]), names)
    assert m.text == "@阿橘 看这个@某人"
    assert parse_group_message(event([{"type": "at", "data": {"qq": "30001", "name": "群里写的名字"}}]), names).text == "@群里写的名字"


def test_pictures_keep_their_position_and_are_numbered_from_the_last_one_back():
    from bothost.app import number_pictures, replace_nth
    m = parse_group_message(event([{"type": "image", "data": {"url": "http://x/1"}}, {"type": "face", "data": {}},
                                   {"type": "image", "data": {"url": "http://x/2", "sub_type": 1}},
                                   {"type": "image", "data": {"url": "http://x/3"}}, {"type": "mface", "data": {"url": "http://x/4"}}]))
    assert m.text == "[图片][表情][表情][图片][表情]"   # a QQ face has no picture: only a placeholder
    assert m.images == [("图片", "http://x/1", 0), ("表情", "http://x/2", 1), ("图片", "http://x/3", 1), ("表情", "http://x/4", 2)]
    numbered = {(id(m), "图片", 0): 1, (id(m), "表情", 1): 2, (id(m), "图片", 1): 3}
    assert number_pictures(m, numbered) == "[图片1][表情][表情2][图片3][表情]"
    assert replace_nth("a[图片]b[图片]", "[图片]", "X", 1) == "a[图片]bX" and replace_nth("a", "[图片]", "X", 0) == "a"


def test_retext_keeps_the_keyword_index_and_its_statistics_in_step(tmp_path):
    s = Store(tmp_path / "m.db")
    s.add("a", "1", 100, "u1", "某人", "看 [图片]")
    s.add("a", "2", 101, "u2", "别人", "今天吃火锅")
    for i, t in enumerate(("下雨了", "周末去爬山", "作业写完没", "晚上打游戏")):   # enough messages for the term to weigh something
        s.add("a", str(10 + i), 110 + i, "u3", "路人", t)
    assert s.retext("a", "1", "看 [图片：一只橘猫在睡觉（机器看的）]") and not s.retext("a", "404", "x")
    assert [h["id"] for h in s.search("橘猫", 5)] == [1]
    fresh = Store(tmp_path / "fresh.db")
    fresh.add("a", "1", 100, "u1", "某人", "看 [图片：一只橘猫在睡觉（机器看的）]")
    fresh.add("a", "2", 101, "u2", "别人", "今天吃火锅")
    for i, t in enumerate(("下雨了", "周末去爬山", "作业写完没", "晚上打游戏")):   # enough messages for the term to weigh something
        fresh.add("a", str(10 + i), 110 + i, "u3", "路人", t)
    stats = lambda st: (sorted(map(tuple, st.db.execute("SELECT term, df FROM message_df"))), sorted(map(tuple, st.db.execute("SELECT k, v FROM message_fts_meta"))))
    assert stats(s) == stats(fresh)   # the same as if the message had come with this text


def test_share_cards_and_video_files_keep_their_links():
    import json as j
    bili = j.dumps({"app": "com.tencent.miniapp_01", "prompt": "[QQ小程序]某视频", "meta": {"detail_1": {
        "title": "哔哩哔哩", "desc": "某个视频的标题", "qqdocurl": "https://b23.tv/AbCd123?share_medium=android"}}})
    news = j.dumps({"app": "com.tencent.structmsg", "meta": {"news": {"title": "一篇文章", "desc": "摘要", "jumpUrl": "https://example.com/a?id=1"}}})
    m = parse_group_message(event([{"type": "json", "data": {"data": bili}}, {"type": "json", "data": {"data": news}},
                                   {"type": "json", "data": {"data": "not json"}}, {"type": "video", "data": {"url": "https://v.example/x.mp4"}},
                                   {"type": "video", "data": {}}]))
    assert m.text == ("[分享：哔哩哔哩｜某个视频的标题 https://b23.tv/AbCd123][分享：一篇文章｜摘要 https://example.com/a?id=1][卡片]"
                      "[视频文件 https://v.example/x.mp4][视频]")
