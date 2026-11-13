"""Gemini embeddings with an on-disk cache, and a brute-force vector index (I4, I5, I14)."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from bench import usage
from bench.schema import Block

MODEL = "gemini-embedding-001"
DIM = 768
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
KEY_FILE = Path(os.environ.get("QQBOT_GEMINI_KEY_FILE", Path(__file__).resolve().parents[2] / "qqbot-data" / "tools" / "gemini.key"))
BATCH = 20
# Free-tier limits are per minute; stay under them instead of retrying into them.
TOKENS_PER_MINUTE = 28000
REQUESTS_PER_MINUTE = 60


def api_key() -> str:
    return os.environ.get("QQBOT_GEMINI_KEY") or KEY_FILE.read_text(encoding="utf-8").strip()


class Embedder:
    batch = BATCH

    def __init__(self, cache_path: Path, model: str = MODEL, dim: int = DIM):
        self.cache_path, self.model, self.dim = cache_path, model, dim
        self.lock = threading.Lock()
        self.cache: dict[str, list[float]] = {}
        self.spent: dict[str, int] = {}
        self.sent: list[tuple[float, int]] = []
        if cache_path.exists():
            for line in cache_path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.cache[row["key"]] = row["v"]
                self.spent[row["key"]] = row.get("tokens", 0)

    def _key(self, text: str, task: str) -> str:
        return hashlib.sha256(f"{self.model}\0{self.dim}\0{task}\0{text}".encode()).hexdigest()

    def _pace(self, tokens: int) -> None:
        while True:
            now = time.time()
            self.sent = [(t, n) for t, n in self.sent if now - t < 60]
            if (sum(n for _, n in self.sent) + tokens <= TOKENS_PER_MINUTE
                    and len(self.sent) < REQUESTS_PER_MINUTE) or not self.sent:
                self.sent.append((now, tokens))
                return
            time.sleep(1)

    def _request(self, texts: Sequence[str], task: str) -> list[list[float]]:
        body = json.dumps({"requests": [{
            "model": f"models/{self.model}", "content": {"parts": [{"text": t or " "}]},
            "taskType": task, "outputDimensionality": self.dim,
        } for t in texts]}).encode()
        req = urllib.request.Request(URL.format(model=self.model), body,
                                     {"Content-Type": "application/json", "x-goog-api-key": api_key()})
        delay = 30.0
        for _ in range(10):
            # Chinese text runs about 0.7 tokens per character.
            self._pace(int(0.7 * sum(len(t) for t in texts)))
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return [e["values"] for e in json.load(resp)["embeddings"]]
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"embedding http {e.code}") from None
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, ValueError):
                pass
            time.sleep(delay)
            delay = min(delay * 2, 600.0)
        raise RuntimeError("embedding kept failing")

    def embed(self, texts: Sequence[str], task: str, role: str = "向量") -> np.ndarray:
        keys = [self._key(t, task) for t in texts]
        missing = sorted({(k, t) for k, t in zip(keys, texts) if k not in self.cache})
        for i in range(0, len(missing), self.batch):
            part = missing[i : i + self.batch]
            self.last_tokens = []
            vectors = self._request([t for _, t in part], task)
            # Gemini reports no token counts, so characters stand in there; Bailian reports real ones.
            spent = self.last_tokens or [len(t) for _, t in part]
            with self.lock:
                with self.cache_path.open("a", encoding="utf-8") as f:
                    for (k, t), v, n in zip(part, vectors, spent):
                        v = [round(x, 5) for x in v]
                        self.cache[k] = v
                        self.spent[k] = n
                        f.write(json.dumps({"key": k, "v": v, "tokens": n}) + "\n")
                        usage.record(role, self.model, k, True, n, 0)
        for k in keys:
            if k in self.spent and not any(k == m[0] for m in missing):
                usage.record(role, self.model, k, False, self.spent[k], 0)
        arr = np.array([self.cache[k] for k in keys], dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)


class VectorIndex:
    """Cosine search over blocks, with the same time visibility as BM25."""

    def __init__(self, blocks: Sequence[Block], embedder: Embedder, role: str):
        self.blocks = list(blocks)
        self.embedder, self.role = embedder, role
        self.matrix = embedder.embed([b.index_text for b in self.blocks], "RETRIEVAL_DOCUMENT", role=f"{role}|文档")
        self.end_ts = np.array([b.end_ts for b in self.blocks])
        self.channels = np.array([b.channel for b in self.blocks])

    def search(self, query: str, as_of: float, k: int, channel: str = "") -> list[tuple[Block, float]]:
        q = self.embedder.embed([query], "RETRIEVAL_QUERY", role=f"{self.role}|查询")[0]
        scores = self.matrix @ q
        visible = self.end_ts < as_of
        if channel:
            visible &= self.channels == channel
        scores = np.where(visible, scores, -np.inf)
        top = np.argsort(-scores, kind="stable")[:k]
        return [(self.blocks[i], float(scores[i])) for i in top if np.isfinite(scores[i])]


ALIYUN_URL = os.environ.get(
    "QQBOT_ALIYUN_EMBED_URL", "https://ws-b3chmsmkylao66wz.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings")
ALIYUN_KEY_FILE = KEY_FILE.with_name("aliyun.key")


class AliyunEmbedder(Embedder):
    """Bailian's OpenAI-compatible endpoint.

    By default no text_type is sent, which the endpoint treats as query mode for documents too
    (found in the 2026-11-04 audit). `asymmetric=True` sends text_type=query/document by task,
    and `instruct` is sent with queries only, as the Qwen3 Embedding paper does. Both settings
    are part of the cache key, so vectors from different settings never mix; the default
    settings keep the old keys and still hit the old cache.
    """

    batch = 20  # qwen3.7-text-embedding rejects more than 20 inputs per request
    tries, first_delay, timeout = 8, 5.0, 120   # patient, for batch work; a live caller sets its own

    def __init__(self, cache_path: Path, model: str = "qwen3.7-text-embedding-flash", dim: int = DIM,
                 asymmetric: bool = False, instruct: str = ""):
        super().__init__(cache_path, model, dim)
        self.asymmetric, self.instruct = asymmetric, instruct
        self.last_tokens: list[int] = []

    def _key(self, text: str, task: str) -> str:
        variant = ""
        if self.asymmetric or self.instruct:
            variant = f"\0asym={int(self.asymmetric)}\0instruct={self.instruct if task == 'RETRIEVAL_QUERY' else ''}"
        return hashlib.sha256(f"{self.model}\0{self.dim}\0{task}\0{text}{variant}".encode()).hexdigest()

    def _request(self, texts: Sequence[str], task: str) -> list[list[float]]:
        key = os.environ.get("QQBOT_ALIYUN_KEY") or ALIYUN_KEY_FILE.read_text(encoding="utf-8").strip()
        payload = {"model": self.model, "input": [t or " " for t in texts], "dimensions": self.dim, "encoding_format": "float"}
        if self.asymmetric:
            payload["text_type"] = "query" if task == "RETRIEVAL_QUERY" else "document"
        if self.instruct and task == "RETRIEVAL_QUERY":
            payload["instruct"] = self.instruct
        body = json.dumps(payload).encode()
        req = urllib.request.Request(ALIYUN_URL, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        delay = self.first_delay
        for _ in range(self.tries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.load(resp)
                total = data.get("usage", {}).get("prompt_tokens", 0)
                chars = [max(len(t), 1) for t in texts]
                # The API reports one total per request; split it by length so each text has a share.
                self.last_tokens = [round(total * c / sum(chars)) for c in chars]
                return [row["embedding"] for row in sorted(data["data"], key=lambda r: r["index"])]
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"embedding http {e.code}") from None
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, ValueError):
                pass
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
        raise RuntimeError("embedding kept failing")
