from types import SimpleNamespace

from bench.retrievers import frozen_pipeline as fp
from bench.schema import Block, Message


def _msgs():
    # m3 and m3b have the same text: a real repeated message must never be dropped.
    texts = {"m3b": "t3"}
    return [Message(i, "g", "u", float(k), texts.get(i, f"t{i[1:]}")) for k, i in
            enumerate(["m0", "m1", "m2", "m3", "m3b", "m4", "m5", "m6", "m7"])]


def _batches(msgs):
    return [msgs[0:6], msgs[3:9]]  # overlap: m3, m3b, m4


def _colors():
    return [
        {"color_id": "b0c0", "msg_ids": ["m1", "m3", "m4"], "summary": "A", "labels": ["事件"]},
        {"color_id": "b1c0", "msg_ids": ["m3", "m3b", "m4", "m6"], "summary": "A 续", "labels": []},
        {"color_id": "b1c1", "msg_ids": ["m3", "m4"], "summary": "重复", "labels": []},
        {"color_id": "b1c2", "msg_ids": ["m7"], "summary": "B", "labels": []},
    ]


def test_index_mode_dedups_by_message_id_not_text():
    msgs = _msgs()
    seen, _ = fp.index_colors(_colors(), _batches(msgs), "index+route")
    by = {c["color_id"]: c["msg_ids"] for c in seen}
    assert by["b0c0"] == ["m1", "m3", "m4"]
    assert by["b1c0"] == ["m3b", "m6"]          # same text as m3, different id: kept
    assert "b1c1" not in by                      # only overlap messages left: not indexed
    assert fp.index_colors(_colors(), _batches(msgs), "none")[0] is not None


def test_unknown_mode_is_refused():
    try:
        fp.index_colors([], [], "merge")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_manifest_keeps_full_blocks_and_records_what_is_indexed():
    msgs = _msgs()
    rows = {r["block_id"]: r for r in fp.block_manifest("x", "colors.jsonl", _colors(), _batches(msgs), msgs, "index+route")}
    assert rows["b1c0"]["msg_ids"] == ["m3", "m3b", "m4", "m6"]
    assert rows["b1c0"]["indexed_msg_ids"] == ["m3b", "m6"]
    assert rows["b1c1"]["indexed_msg_ids"] == [] and rows["b1c1"]["msg_ids"] == ["m3", "m4"]
    assert rows["b0c0"]["scope"] == "group:x" and rows["b0c0"]["batch"] == 0
    assert rows["b0c0"]["start_ts"] <= rows["b0c0"]["end_ts"]


class _FixedIndex:
    def __init__(self, ids, blocks):
        self.ids, self.blocks = ids, blocks

    def search(self, q, as_of, k, channel=""):
        return [(self.blocks[i], 1.0) for i in self.ids[:k]]


def test_retrieve_injects_original_blocks_and_route_skips_covered():
    full = {"x": Block("x", ("m1", "m2", "m3"), 0.0, "g", ""), "dup": Block("dup", ("m2", "m3"), 0.0, "g", ""),
            "y": Block("y", ("m4",), 0.0, "g", "")}
    # The index holds a trimmed copy of x; retrieval must still return the full original block.
    trimmed = {**full, "x": Block("x", ("m1",), 0.0, "g", "")}
    idx = _FixedIndex(["x", "dup", "y"], trimmed)
    msgs = {m: SimpleNamespace(content=m, author="P1", msg_id=m) for m in ("m1", "m2", "m3", "m4")}
    r = fp.FrozenRetriever([idx], full, msgs, "g", top_k=2, budget=10_000, mode="index+route")
    route = r.routes("q", 1.0)[0]
    assert [b.block_id for b in route] == ["x", "y"] and route[0].msg_ids == ("m1", "m2", "m3")
    r.mode = "none"
    assert [b.block_id for b in r.routes("q", 1.0)[0]] == ["x", "dup"]
