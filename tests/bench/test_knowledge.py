from bench.schema import Message
from bench.tasks import knowledge as kn


def m(i, ts, author, text):
    return Message(str(i), "g", author, float(ts), text)


DAY = 86400


def test_parse_terms_filters_bad_values():
    assert kn.parse_terms('x ["绝活哥", "一", 3, "%s"] y' % ("长" * 13)) == ["绝活哥"]
    assert kn.parse_terms("不是 json") == [] and kn.parse_terms(None) == []


def test_gate_needs_uses_speakers_and_days():
    good = [m(i, i * DAY, f"u{i % 3}", "绝活哥") for i in range(5)]
    one_day = [m(i, i, f"u{i % 3}", "绝活哥") for i in range(5)]
    one_person = [m(i, i * DAY, "u", "绝活哥") for i in range(5)]
    few = good[:3]
    for msgs, expect in ((good, True), (one_day, False), (one_person, False), (few, False)):
        assert kn.passes_gate(kn.term_evidence(msgs, ["绝活哥"])["绝活哥"]) is expect


def test_person_codes_are_not_terms():
    assert "P012" not in kn.term_evidence([m(1, 0, "a", "P012 来了")], ["P012"])


def test_parse_entry_drops_non_terms_and_keeps_learned_time():
    assert kn.parse_entry("x", '{"is_term":false,"meaning":"m"}', 5) is None
    assert kn.parse_entry("x", "{broken", 5) is None
    e = kn.parse_entry("x", '{"is_term":true,"meaning":"m","usage":"u"}', 5)
    assert e["learned_before"] == 5 and kn.entry_text(e) == "x：m（用法：u）"


def test_entry_prompt_is_stable_and_limited():
    uses = [m(i, i, "a", f"用法{i}") for i in range(30)]
    a = kn.entry_prompt("词", uses, 0, limit=4)
    assert a == kn.entry_prompt("词", uses, 0, limit=4) and a.count("\n- ") == 4
