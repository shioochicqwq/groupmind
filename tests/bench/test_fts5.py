from bench.retrievers.bm25 import BM25
from bench.retrievers.fts5 import FTS5Index
from bench.schema import Block


def _blocks():
    texts = ["今天 吃 火锅", "火锅 店 关门 了", "明天 去 学校", "学校 后门 新 开 了 火锅 店", "随便 聊聊"]
    return [Block(f"b{i}", (f"m{i}",), float(i), "g", t, ()) for i, t in enumerate(texts)]


def test_rescore_matches_bm25_exactly_and_respects_time():
    blocks, tok = _blocks(), str.split
    bm, fts = BM25(blocks, tok), FTS5Index(blocks, tok, "rescore")
    for q, as_of in (("火锅 店", 10.0), ("学校 火锅", 10.0), ("火锅", 2.0), ("没有 这个 词", 10.0)):
        a = [(b.block_id, round(s, 9)) for b, s in bm.search(q, as_of, 5, "g")]
        b = [(b.block_id, round(s, 9)) for b, s in fts.search(q, as_of, 5, "g")]
        assert a == b


def test_native_mode_finds_the_same_candidates():
    blocks, tok = _blocks(), str.split
    nat = FTS5Index(blocks, tok, "native")
    assert {b.block_id for b, _ in nat.search("火锅", 10.0, 5)} == {"b0", "b1", "b3"}
