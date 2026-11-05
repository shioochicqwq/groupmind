from bench.color_fix import dedup_overlaps, merge_overlaps
from bench.schema import Message


def _batches():
    msgs = [Message(f"m{i}", "g", "u", float(i), f"t{i}") for i in range(8)]
    # Two batches of 5 with 2 overlapping messages (m3, m4).
    return [msgs[0:5], msgs[3:8]]


def _colors():
    return [
        {"color_id": "b0c0", "msg_ids": ["m1", "m3", "m4"], "summary": "A", "labels": ["事件"]},
        {"color_id": "b1c0", "msg_ids": ["m3", "m4", "m6"], "summary": "A 续", "labels": ["事件"]},
        {"color_id": "b1c1", "msg_ids": ["m5"], "summary": "B", "labels": ["闲聊"]},
    ]


def test_dedup_keeps_overlap_messages_only_in_the_earlier_colour():
    out, stats = dedup_overlaps(_colors(), _batches())
    by_id = {c["color_id"]: c["msg_ids"] for c in out}
    assert by_id == {"b0c0": ["m1", "m3", "m4"], "b1c0": ["m6"], "b1c1": ["m5"]}
    assert stats["multi_before"] == 2 and stats["multi_after"] == 0 and stats["links_removed"] == 2


def test_merge_joins_matching_colours_across_the_overlap():
    out, stats = merge_overlaps(_colors(), _batches())
    merged = [c for c in out if "merged_from" in c][0]
    assert merged["msg_ids"] == ["m1", "m3", "m4", "m6"] and merged["merged_from"] == ["b0c0", "b1c0"]
    assert stats["colors_after"] == 2


def test_skip_covered_never_drops_a_block_with_its_own_messages():
    from bench.run_color_layers import skip_covered
    from bench.schema import Block

    b = lambda i, ids: Block(i, tuple(ids), 0.0, "g", "", ())  # noqa: E731
    route = [b("x", ["m1", "m2", "m3"]), b("dup", ["m2", "m3"]), b("y", ["m3", "m4"]), b("z", ["m5"])]
    assert [x.block_id for x in skip_covered(route, 3)] == ["x", "y", "z"]
