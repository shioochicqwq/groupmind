import numpy as np

from bench import embed, usage
from bench.retrievers.fusion import quota
from bench.schema import Block


class FakeEmbedder(embed.Embedder):
    calls = 0

    def _request(self, texts, task):
        FakeEmbedder.calls += 1
        return [[1.0, 0.0] if "山" in t else [0.0, 1.0] for t in texts]


def blocks():
    return [Block("a", ("1",), 1, "g", "爬山"), Block("b", ("2",), 2, "g", "吃饭"), Block("c", ("3",), 9, "g", "香山")]


def test_vector_index_respects_time_and_caches(tmp_path):
    FakeEmbedder.calls = 0
    usage.reset()
    e = FakeEmbedder(tmp_path / "v.jsonl", dim=2)
    idx = embed.VectorIndex(blocks(), e, "向量摘要")
    assert [b.block_id for b, _ in idx.search("山", 5, 3)] == ["a", "b"]
    assert [b.block_id for b, _ in idx.search("山", 100, 1)][0] in {"a", "c"}
    calls = FakeEmbedder.calls
    embed.VectorIndex(blocks(), FakeEmbedder(tmp_path / "v.jsonl", dim=2), "向量摘要")
    assert FakeEmbedder.calls == calls
    assert "向量摘要|文档" in usage.summary()


def test_quota_keeps_each_routes_top_blocks():
    class Route:
        def __init__(self, order):
            self.order = order

        def search(self, q, t, k, channel=""):
            return [(by_id[i], 1.0) for i in self.order[:k]]

    by_id = {b.block_id: b for b in blocks()}
    one, two = Route(["a", "b", "c"]), Route(["c", "b", "a"])
    got = [b.block_id for b, _ in quota([one, two], by_id, "q", 100, 2, per_route=1)]
    assert got == ["a", "c"]


def test_aliyun_splits_reported_tokens_and_keeps_order(tmp_path, monkeypatch):
    import json

    class Resp:
        def __init__(self, request):
            self.texts = json.loads(request.data)["input"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            rows = [{"index": i, "embedding": [1.0, 0.0] if "山" in t else [0.0, 1.0]} for i, t in enumerate(self.texts)]
            # Returned out of order on purpose; the client must sort by index.
            return json.dumps({"data": rows[::-1], "usage": {"prompt_tokens": 30}}).encode()

    monkeypatch.setenv("QQBOT_ALIYUN_KEY", "secret-value")
    monkeypatch.setattr(embed.urllib.request, "urlopen", lambda r, timeout: Resp(r))
    usage.reset()
    e = embed.AliyunEmbedder(tmp_path / "a.jsonl", dim=2)
    v = e.embed(["山山", "饭"], "RETRIEVAL_DOCUMENT", role="向量|摘要")
    assert v[0][0] == 1.0 and v[1][1] == 1.0
    assert usage.summary()["向量|摘要"]["prompt"] == 30
    assert "secret-value" not in (tmp_path / "a.jsonl").read_text()


def test_aliyun_settings_are_part_of_the_cache_key(tmp_path):
    from bench.embed import AliyunEmbedder

    plain = AliyunEmbedder(tmp_path / "c.jsonl")
    asym = AliyunEmbedder(tmp_path / "c.jsonl", asymmetric=True)
    inst = AliyunEmbedder(tmp_path / "c.jsonl", asymmetric=True, instruct="检索")
    old = __import__("hashlib").sha256("qwen3.7-text-embedding-flash\x00768\x00RETRIEVAL_QUERY\x00问".encode()).hexdigest()
    assert plain._key("问", "RETRIEVAL_QUERY") == old
    keys = {e._key("问", "RETRIEVAL_QUERY") for e in (plain, asym, inst)}
    assert len(keys) == 3
    # The instruction only goes with queries, so documents share vectors across instructions.
    assert asym._key("文", "RETRIEVAL_DOCUMENT") == inst._key("文", "RETRIEVAL_DOCUMENT")


def test_frozen_config_matches_the_tested_v2_and_m1():
    from bench.frozen import ALTERNATIVE, FROZEN, LEGACY
    from bench.run_embed_ablation import CONFIGS

    for config, name in ((FROZEN, "V2"), (ALTERNATIVE, "M1"), (LEGACY, "V0")):
        e, c = config["embedding"], CONFIGS[name]
        assert (e["model"], e["dim"], e["asymmetric"], e["instruct"]) == (c["model"], c["dim"], c["asymmetric"], c["instruct"])
    assert FROZEN["top_k"] == 5 and FROZEN["budget_chars"] == 1500


def test_frozen_records_overlap_dedup():
    from bench.frozen import FROZEN, LEGACY

    assert FROZEN["overlap_dedup"] == "index+route" and LEGACY["overlap_dedup"] == "none"
