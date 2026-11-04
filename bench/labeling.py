"""Build per-person labeling pages and merge what comes back.

Pages hold sanitized text and local message numbers only. The mapping back to real
message ids stays in the manifest beside the data, outside the repository.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

TEMPLATE = Path(__file__).with_name("label_template.html")
HUMAN_CORRECT = {"correct": True, "incorrect": False}
SKIP = "skip"
INVALID_QUESTION = {"wrong", "weak", "knowledge"}
# Round 1 pages used a single choice for scope and meaning; map them onto the current codes.
OLD_TERM_LABELS = {"right": "specific_ok", "badmeaning": "specific_bad", "general": "general_ok"}


def _line(m, gold=False, near=False) -> dict:
    return {"who": m.author, "text": m.content, "gold": gold, "near": near}


def question_tasks(questions: Sequence[dict], messages: Sequence) -> list[dict]:
    from bench.sanitize import is_sensitive

    order = [m for m in messages if m.content and not is_sensitive(m.content)]
    position = {m.msg_id: i for i, m in enumerate(order)}
    tasks = []
    for q in questions:
        gold = [position[g] for g in q["gold"] if g in position]
        if not gold:
            continue
        shown = sorted({j for g in gold for j in range(max(0, g - 2), min(len(order), g + 3))})
        lines = [_line(order[j], gold=j in gold, near=j not in gold) for j in shown]
        tasks.append({
            "id": f"question:{q['id']}", "type": "question",
            "question": q["question"], "answer": q["answer"], "lines": lines,
        })
    return tasks


def answer_tasks(report: dict, questions: Sequence[dict], limit: int, seed: int) -> tuple[list[dict], dict]:
    """One card per distinct answer. The arm stays hidden; the manifest maps cards back to arms."""
    qmap = {q["id"]: q for q in questions}
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for arm in report["qa"]:
        for row in arm["rows"]:
            if row["visible"] and row.get("answer"):
                grouped[(row["id"], row["answer"])].append(arm["arm"])
    keys = sorted(grouped)
    random.Random(seed).shuffle(keys)
    tasks, mapping = [], {}
    for n, key in enumerate(keys[:limit]):
        qid, text = key
        task_id = f"answer:{n}"
        q = qmap[qid]
        tasks.append({
            "id": task_id, "type": "answer", "question": q["question"], "answer": q["answer"], "model_answer": text,
        })
        mapping[task_id] = {"question": qid, "arms": grouped[key]}
    return tasks, mapping


def term_tasks(entries: Sequence[dict], messages: Sequence, limit: int, seed: int) -> list[dict]:
    from bench.sanitize import is_sensitive

    rng = random.Random(seed)
    picked = list(entries)
    rng.shuffle(picked)
    tasks = []
    for n, entry in enumerate(picked[:limit]):
        uses = [
            m for m in messages
            if m.timestamp < entry["learned_before"] and entry["term"] in m.content and not is_sensitive(m.content)
        ]
        rng.shuffle(uses)
        tasks.append({
            "id": f"term:{entry['term']}", "type": "term", "term": entry["term"], "meaning": entry["meaning"],
            "usage": entry.get("usage", ""), "lines": [_line(m) for m in uses[:4]],
        })
    return tasks


def assign(tasks: Sequence[dict], people: int, overlap: int, seed: int) -> list[list[dict]]:
    """Everyone gets the shared overlap per type; the rest is dealt out evenly."""
    rng = random.Random(seed)
    packs: list[list[dict]] = [[] for _ in range(people)]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        by_type[t["type"]].append(t)
    for items in by_type.values():
        items = list(items)
        rng.shuffle(items)
        for t in items[:overlap]:
            for pack in packs:
                pack.append(t)
        for i, t in enumerate(items[overlap:]):
            packs[i % people].append(t)
    for n, pack in enumerate(packs):
        random.Random(f"{seed}:{n}").shuffle(pack)
    return packs


def render_page(pack: str, tasks: Sequence[dict], corpus: Sequence[dict]) -> str:
    data = json.dumps({"pack": pack, "tasks": list(tasks), "corpus": list(corpus)}, ensure_ascii=False)
    # A chat line could contain a closing tag, which would end the data block early.
    return TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", data.replace("</", "<\\/"))


def corpus_of(messages: Sequence) -> tuple[list[dict], dict[str, str]]:
    from bench.sanitize import is_sensitive

    corpus, numbers = [], {}
    for m in messages:
        if m.content and not is_sensitive(m.content):
            n = len(corpus)
            corpus.append({
                "n": n, "who": m.author, "text": m.content,
                "day": time.strftime("%m-%d", time.gmtime(m.timestamp + 8 * 3600)),
            })
            numbers[str(n)] = m.msg_id
    return corpus, numbers


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    if not a or len(a) != len(b):
        return None
    observed = sum(x == y for x, y in zip(a, b)) / len(a)
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / len(a) ** 2
    return 1.0 if expected == 1 else round((observed - expected) / (1 - expected), 4)


def agreement(results: Sequence[dict]) -> dict:
    """Mean pairwise kappa per task type over cards both people answered, ignoring skips."""
    scores: dict[str, list[float]] = defaultdict(list)
    counts: Counter = Counter()
    for x, y in itertools.combinations(results, 2):
        shared: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for task_id in set(x["labels"]) & set(y["labels"]):
            if SKIP not in (x["labels"][task_id], y["labels"][task_id]):
                shared[task_id.split(":", 1)[0]].append((x["labels"][task_id], y["labels"][task_id]))
        for kind, pairs in shared.items():
            kappa = cohen_kappa([p[0] for p in pairs], [p[1] for p in pairs])
            if kappa is not None:
                scores[kind].append(kappa)
                counts[kind] += len(pairs)
    return {k: {"kappa": round(sum(v) / len(v), 4), "pairs": counts[k]} for k, v in scores.items()}


def majority(results: Sequence[dict]) -> tuple[dict[str, str], list[str]]:
    votes: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        for task_id, label in r["labels"].items():
            if label != SKIP:
                votes[task_id][label] += 1
    decided, conflicts = {}, []
    for task_id, counter in votes.items():
        top = counter.most_common(2)
        if len(top) == 2 and top[0][1] == top[1][1]:
            conflicts.append(task_id)
        else:
            decided[task_id] = top[0][0]
    return decided, sorted(conflicts)


def normalize(results: Sequence[dict]) -> list[dict]:
    out = []
    for r in results:
        labels = {
            t: OLD_TERM_LABELS.get(v, v) if t.startswith("term:") else v for t, v in r.get("labels", {}).items()
        }
        out.append({**r, "labels": labels})
    return out


def term_votes(results: Sequence[dict]) -> tuple[dict[str, dict], list[str]]:
    """Vote per dimension: person or term, then whether the entry is right.

    A note on a term counts as a correction, so it votes the entry wrong. Scope (group-specific
    or general) is only counted, because people draw that line differently.
    """
    votes: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for r in results:
        notes = r.get("notes", {})
        for task_id, label in r["labels"].items():
            if not task_id.startswith("term:") or label == SKIP:
                continue
            v = votes[task_id]
            kind = label if label in ("person", "notterm") else "term"
            v["kind"][kind] += 1
            if kind == "term":
                v["meaning"][label.endswith("_ok") and not notes.get(task_id, "").strip()] += 1
                v["scope"]["specific" if label.startswith("specific") else "general"] += 1
    decided, conflicts = {}, []
    for task_id, v in votes.items():
        row = {}
        for dim in ("kind", "meaning", "scope"):
            top = v[dim].most_common(2)
            if not top:
                continue
            tie = len(top) == 2 and top[0][1] == top[1][1]
            row[dim] = None if tie else top[0][0]
            if tie and dim != "scope" and not (dim == "meaning" and row.get("kind") != "term"):
                conflicts.append(f"{task_id}:{dim}")
        decided[task_id] = row
    return decided, sorted(conflicts)


def term_summary(decided: dict[str, str]) -> dict:
    """Split term labels into whether it belongs to the group and whether the entry is right."""
    labels = [v for t, v in decided.items() if t.startswith("term:")]
    terms = [v for v in labels if v.startswith(("specific", "general"))]
    return {
        "labels": dict(Counter(labels)),
        "is_term_rate": round(len(terms) / len(labels), 4) if labels else None,
        "group_specific_rate": round(sum(v.startswith("specific") for v in labels) / len(labels), 4) if labels else None,
        "meaning_correct_rate": round(sum(v.endswith("_ok") for v in terms) / len(terms), 4) if terms else None,
    }


def merge(results: Sequence[dict], manifest: dict, report: dict, rulings: dict | None = None) -> dict:
    """rulings: the organizer's final calls, {task_id: label} or for terms {task_id: {dimension: value}}."""
    results = normalize(results)
    rulings = rulings or {}
    decided, conflicts = majority(results)
    terms, term_conflicts = term_votes(results)
    for task_id, ruling in rulings.items():
        if task_id.startswith("term:"):
            terms.setdefault(task_id, {}).update(ruling)
            if ruling.get("kind") in ("person", "notterm"):
                terms[task_id].pop("meaning", None)
                terms[task_id].pop("scope", None)
            term_conflicts = [c for c in term_conflicts if not c.startswith(task_id + ":")]
        else:
            decided[task_id] = ruling
            conflicts = [c for c in conflicts if c != task_id]
    conflicts = sorted([c for c in conflicts if not c.startswith("term:")] + term_conflicts)
    # "awkward" questions still test memory, so they are kept and reported both ways.
    question_labels = {t.split(":", 1)[1]: v for t, v in decided.items() if t.startswith("question:")}
    approved = {q for q, v in question_labels.items() if v == "ok"}
    awkward = {q for q, v in question_labels.items() if v == "awkward"}
    rejected = {q for q, v in question_labels.items() if v in INVALID_QUESTION}

    human: dict[tuple[str, str], bool] = {}
    for task_id, info in manifest["answers"].items():
        label = decided.get(task_id)
        if label in HUMAN_CORRECT:
            for arm in info["arms"]:
                human[(info["question"], arm)] = HUMAN_CORRECT[label]

    judge_pairs, arms = [], {}
    for arm in report["qa"]:
        rows = [r for r in arm["rows"] if r["visible"]]
        for r in rows:
            if (r["id"], arm["arm"]) in human:
                judge_pairs.append((human[(r["id"], arm["arm"])], r["correct"]))
        kept = [r for r in rows if r["id"] not in rejected]
        strict = [r for r in kept if r["id"] not in awkward]
        score = lambda rs: [human.get((r["id"], arm["arm"]), r["correct"]) for r in rs]  # noqa: E731
        arms[arm["arm"]] = {
            "questions": len(kept),
            "human_verdicts": sum((r["id"], arm["arm"]) in human for r in kept),
            "accuracy": round(sum(score(kept)) / len(kept), 4) if kept else None,
            "accuracy_without_awkward": round(sum(score(strict)) / len(strict), 4) if strict else None,
        }
    bad_answer_questions = sorted({
        manifest["answers"][t]["question"] for t, v in decided.items() if v == "badquestion" and t in manifest["answers"]
    })
    numbers = manifest["numbers"]
    written = [
        {
            "by": r.get("name", ""), "question": w["question"], "answer": w["answer"],
            "gold": [numbers[str(n)] for n in w["evidence"] if str(n) in numbers],
        }
        for r in results for w in r.get("written", [])
    ]
    return {
        "people": [r.get("name", "") for r in results],
        "agreement": agreement(results),
        "conflicts": conflicts,
        "questions": {"approved": sorted(approved), "awkward": sorted(awkward), "rejected": sorted(rejected)},
        "judge_vs_human": {
            "n": len(judge_pairs),
            "agreement": round(sum(a == b for a, b in judge_pairs) / len(judge_pairs), 4) if judge_pairs else None,
        },
        "arms": arms,
        "terms": term_summary(decided),
        "term_votes": {t.split(":", 1)[1]: v for t, v in terms.items()},
        "questions_flagged_from_answers": bad_answer_questions,
        "notes": {t: n for r in results for t, n in r.get("notes", {}).items() if n.strip()},
        "term_labels": {t.split(":", 1)[1]: v for t, v in decided.items() if t.startswith("term:")},
        "written_questions": written,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--group", required=True)
    b.add_argument("--runs", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--people", type=int, default=3)
    b.add_argument("--overlap", type=int, default=20)
    b.add_argument("--answers", type=int, default=120)
    b.add_argument("--terms", type=int, default=80)
    b.add_argument("--seed", type=int, default=0)
    m = sub.add_parser("merge")
    m.add_argument("--labels", type=Path, required=True, help="folder with returned labels-*.json")
    m.add_argument("--runs", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if args.cmd == "merge":
        results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.labels.glob("labels-*.json"))]
        manifest = json.loads((args.out / "manifest.json").read_text(encoding="utf-8"))
        report = json.loads((args.runs / "s0.json").read_text(encoding="utf-8"))
        rulings_path = args.out / "rulings.json"
        rulings = json.loads(rulings_path.read_text(encoding="utf-8")) if rulings_path.exists() else {}
        merged = merge(results, manifest, report, rulings)
        (args.out / "merged.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: merged[k] for k in ("people", "agreement", "judge_vs_human", "arms", "terms")}, ensure_ascii=False, indent=1))
        return 0

    from bench import realdata
    from bench.run_s0 import sanitized
    from bench.sanitize import Sanitizer
    from bench.schema import Visibility
    from bench.tasks.real_tasks import clean_messages

    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("labeling pages are built from DEV groups only")
    raw = realdata.load_group(args.group)
    messages = sanitized(clean_messages(raw), Sanitizer(raw))
    questions = json.loads((args.runs / "q2_questions.json").read_text(encoding="utf-8"))
    report = json.loads((args.runs / "s0.json").read_text(encoding="utf-8"))
    tables = json.loads((args.runs / "k_tables.json").read_text(encoding="utf-8"))
    entries = list({e["term"]: e for e in tables["stats"] + tables["model"]}.values())
    q_tasks = question_tasks(questions, messages)
    a_tasks, answer_map = answer_tasks(report, questions, args.answers, args.seed)
    t_tasks = term_tasks(entries, messages, args.terms, args.seed)
    tasks = q_tasks + a_tasks + t_tasks
    corpus, numbers = corpus_of(messages)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(json.dumps({"answers": answer_map, "numbers": numbers}), encoding="utf-8")
    packs = assign(tasks, args.people, args.overlap, args.seed)
    for n, pack in enumerate(packs):
        name = chr(ord("A") + n)
        (args.out / f"label-{name}.html").write_text(render_page(name, pack, corpus), encoding="utf-8")
        print(name, len(pack), Counter(t["type"] for t in pack))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
