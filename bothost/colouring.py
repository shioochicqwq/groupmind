"""Colouring after going live (D-047), done by the host apart from every group's session.

When a group's session loses context (a compaction, or a new session) the messages that left it are due. A job reads
them from the store, colours them in the frozen way (bench/coloring.py: same prompt, batches of 150 overlapping by 20,
the frozen colour model), requests the document vectors the new colours need, and stores all of it as one colour run
(bench/store/online.py). Recall picks the run up on its next search. The group's session never sees any of this.

A compaction colours full batches only: what is left is still in front of the model. A new session colours everything
due, the last batch partly filled. A job that fails stores nothing; the same messages are due again next time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from bench import coloring
from bench.frozen import FROZEN
from bench.store import frozen, online

log = logging.getLogger(__name__)


class Colouring:
    def __init__(self, db: Path, model: str, base_url: str, api_key: str, usage_file: Path, timeout: float = 300.0) -> None:
        self.db, self.model, self.base_url, self.api_key = Path(db), model, base_url.rstrip("/"), api_key
        self.usage_file, self.timeout = Path(usage_file), timeout
        self.running: set[str] = set()

    def _ask(self, prompt: str) -> tuple[str, dict]:
        body = {"model": self.model, "messages": [{"role": "system", "content": coloring.SYSTEM}, {"role": "user", "content": prompt}]}
        req = urllib.request.Request(self.base_url + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        error: Exception | None = None
        for wait in (0, 10, 30):   # a busy gateway gets two more tries; anything else fails the job
            time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    d = json.loads(r.read())
                return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "", d.get("usage") or {}
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    raise
                error = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                error = e
        raise error or RuntimeError("no answer")

    def run(self, code: str, final: bool, why: str = "") -> dict:
        """Colour what is due in one chat and store it. Blocking: call it off the event loop."""
        t0 = time.monotonic()
        con = sqlite3.connect(self.db, timeout=30)
        try:
            h = online.history(con, code, FROZEN)
            job = online.plan(con, h, final)
            if job is None:
                return {"batches": 0}
            outputs, prompt_tokens, completion_tokens = [], 0, 0
            for batch, p in zip(job.batches, job.prompts()):
                text, usage = self._ask(p)
                if not coloring.parse_colors(text, batch, 0):   # one more try for an answer that is not a colour list
                    text, again = self._ask(p)
                    prompt_tokens += int(usage.get("prompt_tokens") or 0)
                    completion_tokens += int(usage.get("completion_tokens") or 0)
                    usage = again
                outputs.append(text)
                prompt_tokens += int(usage.get("prompt_tokens") or 0)
                completion_tokens += int(usage.get("completion_tokens") or 0)
            online.take(job, outputs)
            # vectors for the new colours, requested before anything is written so the store never holds a run without them
            emb = frozen.StoreEmbedder(con, FROZEN, fetch=True)
            emb.tries, emb.first_delay, emb.timeout = 4, 5.0, 60
            frozen.load(con, code, emb, FROZEN, online.with_run(h, job))
            run_id = online.store(con, code, job, self.model, h.size, h.overlap, emb.fetched, emb.model, {"trigger": why})
            return {"run": run_id, "batches": len(job.batches), "failed_batches": job.failed, "colors": len(job.colors),
                    "messages": len(job.new), "prompt": prompt_tokens, "completion": completion_tokens,
                    "vectors": len(emb.fetched), "embedding_tokens": emb.spent, "seconds": round(time.monotonic() - t0, 1)}
        finally:
            con.close()

    async def start(self, code: str, why: list[str]) -> None:
        """Run a job for this chat in the background, unless one is running already (the next reset picks up the rest)."""
        if code in self.running:
            return
        self.running.add(code)
        try:
            got = await asyncio.to_thread(self.run, code, "cold_start" in why, "+".join(why))
        except Exception as e:
            log.warning("colouring in %s failed, nothing stored: %s", code, type(e).__name__)
            got = {"error": type(e).__name__}
        finally:
            self.running.discard(code)
        if got.get("batches") or "error" in got:
            log.info("colouring in %s: %s", code, got)
            with open(self.usage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "group": code, "model": self.model, "colour": got},
                                   ensure_ascii=False) + "\n")
