from bench.schema import Message
from bench.tasks import silver, slang


def m(i, ts, author, text):
    return Message(str(i), "g", author, float(ts), text)


def test_mine_words_needs_several_speakers_and_skips_known():
    msgs = [m(i, i, f"u{i % 3}", t) for i, t in enumerate(["绝活哥来了", "他是绝活哥", "看绝活哥打", "绝活哥牛啊", "哇绝活哥呢", "就绝活哥吧"])]
    msgs += [m(9, 9, "solo", "独占词")] * 6
    words = slang.mine_words(msgs, known=lambda w: w == "来了")
    assert "绝活哥" in words and "来了" not in words and "独占词" not in words


def test_items_only_after_split_and_hide_the_word():
    words = ["绝活哥", "摆大烂", "狠狠爱", "润去吧"]
    msgs = [m(i, i, "a", f"普通消息{i}") for i in range(10)]
    msgs += [m(20, 20, "b", "绝活哥又来了"), m(5000, 5000, "a", "前文"), m(5001, 5001, "a", "前文二"), m(5002, 5002, "b", "摆大烂吧")]
    items = slang.build_items(msgs, words, split_ts=1000, n=5, seed=1)
    assert [i["word"] for i in items] == ["摆大烂"]
    item = items[0]
    assert "摆大烂" not in item["masked"] and item["options"][item["answer"]] == "摆大烂" and len(item["options"]) == 4


def test_history_examples_cannot_see_the_future():
    msgs = [m(1, 1, "a", "绝活哥"), m(2, 100, "a", "绝活哥")]
    assert [x.msg_id for x in slang.history_examples(msgs, "绝活哥", 50, 5, 0)] == ["1"]


def test_segments_respect_minimum_age():
    msgs = [m(i, i * 100, "a", f"内容{i}") for i in range(100)]
    segs = silver.sample_segments(msgs, end_ts=10000, n=3, size=5, seed=0, min_age=5000)
    assert len(segs) == 3 and all(x.timestamp < 5000 for s in segs for x in s)


def test_overlap_and_age_buckets():
    assert silver.char_overlap("火锅", "今天吃火锅") == "high"
    assert silver.char_overlap("烧烤", "今天吃火锅") == "low"
    assert silver.age_bucket(8 * 86400) == "7-30d" and silver.age_bucket(40 * 86400) == ">30d"
