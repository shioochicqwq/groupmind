from bench import chunking, evaluate, tokenize
from bench.retrievers.bm25 import BM25
from bench.sanitize import Sanitizer, clean_text, is_sensitive
from bench.schema import Message
from bench.tasks.real_tasks import clean_messages, identity_scores, quote_cases


def m(i, ts, author, text, reply=None, kind=(), nick=""):
    return Message(str(i), "g", author, float(ts), text, reply, kind, nick or author)


def test_quote_cases_clean_and_bucket():
    msgs = clean_messages([
        m(1, 0, "a", "火锅店在哪里"),
        m(2, 100, "b", "@a 就在学校门口", reply="1"),
        m(3, 200, "a", "@a 自己回复", reply="1"),
        m(4, 300, "b", "@a [图片:x.png]", reply="1"),
        m(5, 400, "b", "随便", reply="404"),
        m(6, 500, "c", "火锅店在哪里 真的", reply="1"),
    ])
    cases, funnel = quote_cases(msgs)
    assert [c.case_id for c in cases] == ["q1:2"]
    assert "@" not in cases[0].query
    assert cases[0].buckets["dist"] == "<10m"
    assert funnel == {
        "reply": 5, "kept": 1, "drop_self_quote": 1, "drop_query_no_text": 1,
        "drop_unresolved": 1, "drop_query_copies_target": 1,
    }


def test_quote_context_hides_what_is_already_on_screen():
    msgs = clean_messages([m(1, 0, "a", "目标消息"), m(2, 10, "c", "第二条"), m(3, 15, "b", "中间消息"), m(4, 20, "b", "回复", reply="1"), m(5, 30, "c", "未来")])
    case = quote_cases(msgs, context=2)[0][0]
    assert "未来" not in case.query and "目标消息" not in case.query and "中间消息" in case.query
    assert case.as_of == 10.0
    cases, funnel = quote_cases(msgs, context=3)
    assert cases == [] and funnel["drop_target_on_screen"] == 1


def test_quote_gold_found_end_to_end():
    msgs = clean_messages([m(i, i, "a", f"填充内容{i}") for i in range(1, 8)] + [
        m(8, 100, "a", "下周三去爬山"), m(9, 200, "b", "@a 爬山要带水", reply="8"),
    ])
    cases, _ = quote_cases(msgs)
    index = BM25(chunking.single_message(msgs), tokenize.bigram)
    assert evaluate.evaluate(index, cases)["per_case"]["q1:9"]["rank"] == 1


def test_identity_counts_shared_names_and_renames():
    r = identity_scores([m(1, 0, "a", "x", nick="n1"), m(2, 1, "a", "x", nick="n1"), m(3, 2, "b", "x", nick="n1"), m(4, 3, "a", "x", nick="n2")])
    assert r["resolvable"] == 2 and r["wrong_person"] == 1 and r["accuracy"] == 0.5
    assert r["false_merges_if_name_is_identity"] == 1
    assert r["split_identities_if_name_is_identity"] == 1 and r["rename_events"] == 1


def test_sanitizer_masks_people_and_identifiers():
    msgs = [m(1, 0, "111", "x", nick="小明同学")]
    s = Sanitizer(msgs)
    out = s.text("小明同学 电话13812345678 邮箱 a@b.com 群号123456789 https://x.cn/a")
    for leak in ("小明", "13812345678", "a@b.com", "123456789", "x.cn"):
        assert leak not in out
    assert s.author(msgs[0]) == "P001"


def test_sensitive_and_placeholder_filters():
    assert is_sensitive("我的身份证丢了") and is_sensitive("11010519491231002X") and not is_sensitive("今天吃饭")
    assert clean_text(m(1, 0, "a", "看[图片:a.png]这个", kind=("1",))) == "看这个"
    assert clean_text(m(1, 0, "a", "按钮内容", kind=("99",))) == ""


def test_budget_metric_charges_for_block_size():
    from bench.evaluate import summarize

    rows = {"a": {"rank": 2, "msgs": 40, "msgs_to_gold": 40, "buckets": {}}, "b": {"rank": 1, "msgs": 10, "msgs_to_gold": 10, "buckets": {}}}
    s = summarize(rows)["all"]
    assert s["R@1"] == 0.5 and s["R@msgs20"] == 0.5 and s["R@msgs50"] == 1.0
