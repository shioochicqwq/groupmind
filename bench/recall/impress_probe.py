"""Wording probe: is "no deep impression at all" the reader's judgement or the prompt's caution?

Re-reads only the chunks where the main run (bench.recall.run_impress) left a 中 impression, with
the same input (the same note of what is usual, the same earlier impressions of the day) and the
system prompt minus its one sentence of caution ("深的很少。不要因为…拔高。"). Reports what changes.
This is a diagnosis, not a second version of the impressions: its rows are not used by the policy.

    python -m bench.recall.impress_probe --group 4fe395 --out <runs>/real-dev --model gemini-3.8-flash-high
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from bench import realdata, usage
from bench.llm import BatchLLM
from bench.recall import run_impress as ri
from bench.sanitize import Sanitizer
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages

assert ri.CAUTION in ri.SYSTEM


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", required=True)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this sends data out and is DEV only")
    raw = realdata.load_group(args.group)
    messages, san = clean_messages(raw), Sanitizer(raw)
    rows = [json.loads(x) for x in (args.out / f"recall.impressions.{args.model}.jsonl").open(encoding="utf-8")]
    notes = [json.loads(x) for x in (args.out / f"recall.usual.{args.model}.jsonl").open(encoding="utf-8")]
    plan = ri.chunks(messages)
    llm = BatchLLM(args.out / f"recall.impress_probe.{args.model}.cache.jsonl", args.model)
    system = ri.SYSTEM.replace(ri.CAUTION, "")
    before, after, changed, kept, out = Counter(), Counter(), 0, 0, []
    todo = sorted({r["chunk"] for r in rows if r["strength"] == "中"})
    for k in todo:
        day, idx = plan[k]
        usual = next((n["usual"] for n in reversed(notes[:k]) if n["usual"]), "")
        earlier = [r["gist"] for r in rows if r["day"] == day and r["chunk"] < k]
        try:
            got = ri.parse(llm.call(system, ri.render(messages, idx, san, day, usual, earlier), role="回忆印象|措辞探查"), len(idx))
        except RuntimeError:
            got = None
        if got is None:
            continue
        mine = [r for r in rows if r["chunk"] == k]
        before.update(r["strength"] for r in mine)
        after.update(it["strength"] for it in got[0])
        deep = [it for it in got[0] if it["strength"] == "深"]
        changed += bool(deep)
        kept += sum(len(it["keep"]) for it in deep)
        out.append({"chunk": k, "day": day, "before": [r["strength"] for r in mine],
                    "after": [{"strength": it["strength"], "why": it["why"], "gist": it["gist"],
                               "keep": [messages[idx[j - 1]].msg_id for j in it["keep"]]} for it in got[0]]})
    summary = {"group": args.group, "model": args.model, "chunks_reread": len(out), "of": len(todo),
               "with_caution": dict(before), "without_caution": dict(after),
               "chunks_with_a_deep_one": changed, "kept_lines": kept, "tokens": usage.summary()}
    (args.out / f"recall.impress_probe.{args.model}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    (args.out / f"recall.impress_probe.{args.model}.summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
