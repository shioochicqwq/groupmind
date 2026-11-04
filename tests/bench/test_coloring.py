from bench.coloring import batches, parse_colors, render
from bench.sanitize import Sanitizer
from bench.schema import Message


def m(i, text="内容", nick="昵称很长"):
    return Message(str(i), "g", f"u{i % 2}", float(i), text, nickname_at_time=nick)


def test_batches_overlap_cover_everything_and_skip_sensitive():
    msgs = [m(i) for i in range(10)] + [m(99, "我的身份证号")]
    parts = batches(msgs, size=4, overlap=1)
    seen = {x.msg_id for p in parts for x in p}
    assert seen == {str(i) for i in range(10)}
    assert parts[1][0].msg_id == parts[0][-1].msg_id


def test_render_hides_real_identity():
    msgs = [m(1, "昵称很长 说了什么 13812345678")]
    text = render(msgs, Sanitizer(msgs))
    assert "u1" not in text and "昵称很长" not in text and "13812345678" not in text


def test_parse_maps_local_ids_and_ignores_garbage():
    batch = [m(10), m(11), m(12)]
    out = 'x [{"type":"事件","name":"甲","summary":"乙","ids":[1,3,9,"a"]},{"ids":[]},3] y'
    colors = parse_colors(out, batch, 7)
    assert len(colors) == 1 and colors[0]["msg_ids"] == ["10", "12"] and colors[0]["color_id"] == "b7c0"
    assert colors[0]["summary"] == "甲 乙" and colors[0]["labels"] == ["事件"]
    assert parse_colors("不是 json", batch, 0) == [] and parse_colors("[oops]", batch, 0) == []
