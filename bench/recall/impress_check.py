"""Do the impressions agree with what the group itself came back to? No model call. DEV only.

Two weak, independent traces of "this was remembered by someone":
  recalled   the message a later recall was linked to by bench.recall.run_link (model links, not yet
             checked by a person; the union over the judges that ran)
  revisited  a message that got a quote-reply an hour or more later
For each: the share that lies inside an impression, against the share of all messages that does.

    python -m bench.recall.impress_check --group 4fe395 --out <runs>/real-dev --impressions gemini-3.8-flash-high
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from bench import realdata
from bench.recall import policy
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages


def share(ids, known) -> dict:
    c = Counter(known[i]["strength"] if i in known else "无" for i in ids)
    n = sum(c.values())
    return {"n": n, **{s: c[s] for s in ("深", "中", "浅", "无")}, "inside": round(1 - c["无"] / n, 3) if n else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--impressions", required=True)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    messages = clean_messages(realdata.load_group(args.group))
    known = policy.index([json.loads(x) for x in (args.out / f"recall.impressions.{args.impressions}.jsonl").open(encoding="utf-8")])
    recalled = set()
    for path in sorted(args.out.glob("recall.links.deepseek-*.jsonl")):
        recalled |= {r["origin_msg_id"] for r in map(json.loads, path.open(encoding="utf-8")) if r.get("origin_msg_id")}
    late = [i for i, t in policy.revisits(messages).items() if t]
    out = {"group": args.group, "impressions_from": args.impressions,
           "all_messages": share([m.msg_id for m in messages], known),
           "recalled_later_by_a_member": share(recalled, known),
           "quote_replied_an_hour_or_more_later": share(late, known)}
    (args.out / f"recall.impress_check.{args.impressions}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
