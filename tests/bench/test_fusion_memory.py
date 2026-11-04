from bench import chunking, tokenize
from bench.memory_text import injected_messages, merged_windows, raw_blocks
from bench.retrievers.bm25 import BM25
from bench.retrievers.fusion import rrf
from bench.schema import Block, Message


def m(i, text):
    return Message(str(i), "g", f"P{i}", float(i), text)


MSGS = [m(i, t) for i, t in enumerate(["火锅 学校", "爬山 香山", "火锅 门口", "无关 一", "无关 二", "无关 三", "爬山 带水"])]
BY_ID = {x.msg_id: x for x in MSGS}
ORDER = {x.msg_id: i for i, x in enumerate(MSGS)}


def test_raw_blocks_show_each_message_once():
    a = Block("a", ("0", "2"), 2, "g", "")
    b = Block("b", ("2", "6"), 6, "g", "")
    c = Block("c", ("0",), 0, "g", "")
    assert raw_blocks([a, b, c], BY_ID) == ["P0: 火锅 学校\nP2: 火锅 门口", "P6: 爬山 带水"]
    assert injected_messages([a, b, c]) == 3


def test_overlapping_windows_merge_into_spans():
    w1 = Block("w1", ("0", "1", "2"), 2, "g", "")
    w2 = Block("w2", ("2", "3"), 3, "g", "")
    w3 = Block("w3", ("6",), 6, "g", "")
    spans = merged_windows([w2, w1, w3], BY_ID, ORDER)
    assert len(spans) == 2 and spans[0].count("\n") == 3 and spans[1] == "P6: 爬山 带水"


def test_rrf_rewards_agreement_between_indexes():
    blocks = chunking.single_message(MSGS)
    by_block = {b.block_id: b for b in blocks}
    one = BM25(blocks, tokenize.bigram)
    fused = rrf([one, one], by_block, "爬山", 100, 3)
    alone = one.search("爬山", 100, 3)
    assert [b.block_id for b, _ in fused] == [b.block_id for b, _ in alone]
    assert all(b.end_ts < 4 for b, _ in rrf([one], by_block, "爬山", 4, 5))


def test_filter_view_has_one_entry_per_block():
    from bench.run_abcd import raw_blocks_aligned

    a = Block("a", ("0", "2"), 2, "g", "")
    b = Block("b", ("2",), 2, "g", "")
    views = raw_blocks_aligned([a, b], BY_ID)
    assert len(views) == 2 and views[1] == "P2: 火锅 门口"


def test_budget_counts_injected_text_and_cuts_an_oversized_first_block():
    from bench.run_abcd import within_budget

    a = Block("a", ("0", "2"), 2, "g", "")
    b = Block("b", ("2", "6"), 6, "g", "")
    feed = lambda bs: raw_blocks(bs, BY_ID)  # noqa: E731
    total = len("P0: 火锅 学校\nP2: 火锅 门口")
    taken, text = within_budget([a, b], feed, total + 3)
    assert taken == [a] and sum(map(len, text)) <= total + 3
    # b only adds one new message because 2 was already shown, so a bigger budget fits both.
    taken, _ = within_budget([a, b], feed, total + len("P6: 爬山 带水"))
    assert taken == [a, b]
    taken, text = within_budget([a], feed, 5)
    assert taken == [a] and text == ["P0: 火"]
