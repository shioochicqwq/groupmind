import datetime as dt

from bench.events.build import build, episodes_by_gap, features, primary_color
from bench.events.label_pack import evening_of
from bench.schema import Message


def _m(i, t, author="u1", text="x"):
    return Message(f"m{i}", "g", author, float(t), text)


def test_gap_splits_on_silence_only():
    ms = [_m(0, 0), _m(1, 100), _m(2, 4000), _m(3, 4100)]
    assert [[m.msg_id for m in p] for p in episodes_by_gap(ms, 1800)] == [["m0", "m1"], ["m2", "m3"]]


def test_interleave_counts_thread_switches():
    ms = [_m(i, i * 10, author=f"u{i % 2}") for i in range(4)]
    color_of = {"m0": "a", "m1": "b", "m2": "a", "m3": "b"}
    f = features(ms, color_of, {"a": "T0", "b": "T1"})
    assert f["thread_interleave"] == 1.0 and f["threads"] == 2 and f["turn_switch_rate"] == 1.0
    same = features(ms, color_of, {"a": "T0", "b": "T0"})
    assert same["thread_interleave"] == 0.0


def test_primary_colour_is_the_earliest_and_build_keeps_references():
    ms = [_m(i, i * 10) for i in range(30)]
    colors = [{"color_id": "b0c0", "msg_ids": [f"m{i}" for i in range(0, 20)], "summary": "A"},
              {"color_id": "b1c0", "msg_ids": [f"m{i}" for i in range(15, 30)], "summary": "A 续"}]
    assert primary_color(colors)["m16"] == "b0c0"
    batches = [ms[0:20], ms[15:30]]
    ep = build("x", ms, colors, batches, gap=1800, min_msgs=5)[0]
    assert ep.scope == "group:x" and ep.n_msgs == 30
    assert [r["block_id"] for r in ep.block_refs] == ["b0c0", "b1c0"]
    assert len(ep.threads) == 1  # the overlap links the two batch colours into one thread


def test_evening_is_beijing_time():
    tz8 = dt.timezone(dt.timedelta(hours=8))
    late = dt.datetime(2026, 5, 24, 23, 30, tzinfo=tz8).timestamp()
    early = dt.datetime(2026, 5, 25, 2, 0, tzinfo=tz8).timestamp()
    noon = dt.datetime(2026, 5, 25, 12, 0, tzinfo=tz8).timestamp()
    assert evening_of(late) == evening_of(early) == dt.date(2026, 5, 24)
    assert evening_of(noon) is None
