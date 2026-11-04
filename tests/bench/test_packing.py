from bench.retrievers import packing
from bench.schema import Block


def b(i, msgs):
    return Block(i, tuple(msgs), 0, "g", "")


TEXT = {str(n): "字" * 10 for n in range(100)}


def feed(blocks):
    seen, out = set(), []
    for block in blocks:
        new = [TEXT[m] for m in block.msg_ids if m not in seen]
        seen.update(block.msg_ids)
        if new:
            out.append("".join(new))
    return out


A1, A2, A3 = b("a1", ["1"]), b("a2", ["2"]), b("a3", ["3"])
B1, B2 = b("b1", ["11"]), b("b2", ["12"])


def test_round_robin_alternates_routes():
    assert [x.block_id for x in packing.round_robin([[A1, A2, A3], [B1, B2]])] == ["a1", "b1", "a2", "b2", "a3"]


def test_round_robin_skips_repeats():
    assert [x.block_id for x in packing.round_robin([[A1, A2], [A1, B1]])] == ["a1", "a2", "b1"]


def test_strict_packing_stops_at_first_misfit():
    big = b("big", ["20", "21", "22"])
    assert [x.block_id for x in packing.pack_in_order([A1, big, A2], feed, 25)] == ["a1"]


def test_reserved_gives_every_route_its_share():
    route_a = [A1, A2, A3]
    route_b = [B1, B2]
    # Strict RRF order would favour route a; each route still gets 20 of the 40 characters.
    got = {x.block_id for x in packing.reserved([route_a, route_b], feed, 40)}
    assert {"b1", "b2"} <= got and len(got) == 4


def test_budget_aware_prefers_new_content_and_respects_budget():
    dup = b("dup", ["1"])
    long = b("long", ["30", "31", "32", "33"])
    routes = [[A1, dup, long], [B1, A2]]
    got = packing.budget_aware(routes, feed, 30)
    ids = {x.block_id for x in got}
    assert "dup" not in ids and "long" not in ids and len(ids) == 3
    assert packing.size(feed, got) <= 30


def test_global_rrf_order():
    assert [x.block_id for x in packing.global_rrf([[A1, B1], [B1, A2]])][:1] == ["b1"]
