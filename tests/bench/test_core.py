import pytest

from bench import chunking, evaluate, metrics, tokenize
from bench.retrievers.bm25 import BM25
from bench.schema import HoldoutViolation, Message, RetrievalCase, Visibility


def msg(i, ts, text, ch="c"):
    return Message(f"m{i}", ch, "a", float(ts), text)


MSGS = [
    msg(0, 0, "apple pie recipe"),
    msg(1, 10, "banana bread"),
    msg(2, 20, "apple cider"),
    msg(3, 30, "completely unrelated words here"),
    msg(4, 40, "more filler text"),
    msg(5, 50, "yet another line"),
]


def index(messages=MSGS):
    return BM25(chunking.single_message(messages), tokenize.word)


def test_future_blocks_are_invisible():
    hits = index().search("apple", as_of=15, k=5)
    assert [b.block_id for b, _ in hits] == ["m0"]


def test_as_of_is_exclusive():
    hits = index().search("apple", as_of=20, k=5)
    assert [b.block_id for b, _ in hits] == ["m0"]


def test_window_ends_at_last_message_so_it_cannot_leak():
    blocks = chunking.fixed_window(MSGS, size=2, stride=2)
    assert [b.end_ts for b in blocks] == [10.0, 30.0, 50.0]
    hits = BM25(blocks, tokenize.word).search("cider", as_of=25, k=5)
    assert hits == []


def test_window_covers_every_message():
    for size, stride in ((2, 1), (3, 2), (2, 2), (10, 5)):
        covered = {i for b in chunking.fixed_window(MSGS, size, stride) for i in b.msg_ids}
        assert covered == {m.msg_id for m in MSGS}


def test_colors_may_overlap_and_skip():
    colors = [
        {"color_id": "x", "msg_ids": ["m0", "m2"], "summary": "fruit"},
        {"color_id": "y", "msg_ids": ["m2", "m3"], "summary": "other"},
    ]
    blocks = chunking.from_colors(MSGS, colors, "raw")
    assert blocks[0].msg_ids == ("m0", "m2") and blocks[0].end_ts == 20.0
    assert chunking.from_colors(MSGS, colors, "summary")[0].index_text == "fruit"


def test_rank_and_recall():
    case = RetrievalCase("q", "banana", 100.0, frozenset({"m1"}))
    run = evaluate.evaluate(index(), [case])
    assert run["per_case"]["q"]["rank"] == 1
    assert run["summary"]["all"]["R@1"] == 1.0


def test_gold_after_as_of_counts_as_miss():
    case = RetrievalCase("q", "banana", 5.0, frozenset({"m1"}))
    assert evaluate.evaluate(index(), [case])["per_case"]["q"]["rank"] is None


def test_leaking_retriever_is_rejected():
    class Leaky(BM25):
        def search(self, query, as_of, k, channel=""):
            return super().search(query, float("inf"), k, channel)

    case = RetrievalCase("q", "cider", 5.0, frozenset({"m2"}))
    with pytest.raises(evaluate.TimeLeak):
        evaluate.evaluate(Leaky(chunking.single_message(MSGS), tokenize.word), [case])


@pytest.mark.parametrize("vis", [Visibility.VALIDATION, Visibility.FROZEN])
def test_holdout_needs_explicit_flag(vis):
    case = RetrievalCase("q", "banana", 100.0, frozenset({"m1"}), visibility=vis)
    with pytest.raises(HoldoutViolation):
        evaluate.evaluate(index(), [case])
    evaluate.evaluate(index(), [case], allow_holdout=True)


def test_matches_rank_bm25_scores():
    rank_bm25 = pytest.importorskip("rank_bm25")
    docs = ["a b c", "a a d", "e f", "b b b g", "c d e f"]
    ours = BM25(chunking.single_message([msg(i, i, d) for i, d in enumerate(docs)]), str.split)
    ref = rank_bm25.BM25Okapi([d.split() for d in docs])
    for q in ("a", "b d", "e f g", "c a"):
        expect = ref.get_scores(q.split())
        got = dict.fromkeys(range(len(docs)), 0.0)
        for block, score in ours.search(q, 1e9, 10):
            got[int(block.block_id[1:])] = score
        assert [round(got[i], 6) for i in range(len(docs))] == [round(float(s), 6) for s in expect]


def test_metrics():
    assert metrics.recall_at([1, 5, None, 20], 5) == 0.5
    assert metrics.mrr([1, None]) == 0.5
    assert metrics.auc([3, 4], [1, 2]) == 1.0
    assert metrics.auc([1, 1], [1, 1]) == 0.5
    d = metrics.paired_delta([0, 1, 0], [1, 1, 0])
    assert d["wins"] == 1 and d["losses"] == 0


def test_tokenizers_handle_chinese():
    assert tokenize.bigram("今天吃饭ok") == ["ok", "今天", "天吃", "吃饭"]
    assert tokenize.unigram("吃饭") == ["吃", "饭"]
    assert "吃饭" in tokenize.make_jieba()("今天吃饭")
    assert "绝绝子哦" in tokenize.make_jieba(("绝绝子哦",))("这个绝绝子哦")
