"""What is searched versus what the model receives (R4, I3, I6, I7). DEV only.

A: raw block -> raw block. B: summary -> summary. C: summary -> raw block.
D1: both, fused -> raw block. D2: both, fused, filter sees summary and raw -> raw block.
Reference: 10-message windows, merged so no message repeats, with and without the filter.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from types import SimpleNamespace

from bench import chunking, metrics, realdata, tokenize
from bench.ledger import fingerprint
from bench.llm import DEFAULT_MODEL, JUDGE_MODEL, BatchLLM
from bench.memory_text import injected_messages, merged_windows, raw_blocks
from bench.retrievers.bm25 import BM25
from bench.retrievers.fusion import rrf
from bench.run_s0 import ANSWER, FILTER, JUDGE, final_of, is_refusal, render, sanitized
from bench.sanitize import Sanitizer, is_sensitive
from bench.schema import Visibility
from bench.tasks import silver, slang
from bench.tasks.real_tasks import clean_messages

TOP = 10
NO_FILTER_TOP = 5


def load_questions(out: Path, messages, end_ts, main_llm, check_llm, extra_segments: int, rejected: set[str]):
    """Round-1 questions plus a new batch from other segments; human-rejected ones are dropped."""
    first_path = out / "q2_questions.json"
    first = json.loads(first_path.read_text(encoding="utf-8")) if first_path.exists() else []
    path = out / "q2b_questions.json"
    if path.exists():
        more = json.loads(path.read_text(encoding="utf-8"))
    else:
        segments = silver.sample_segments(messages, end_ts, extra_segments, 40, 1, 7 * 86400)
        more, stats = silver.build_questions(segments, render, main_llm, check_llm, end_ts, id_prefix="q2b")
        path.write_text(json.dumps(more, ensure_ascii=False), encoding="utf-8")
        (out / "q2b_build.json").write_text(json.dumps(stats), encoding="utf-8")
    return [q for q in first + more if q["id"] not in rejected]


class Arm:
    def __init__(self, name, retrieve, filter_view, feed, budget=0):
        self.name = name
        self.retrieve = retrieve  # (query, as_of) -> list[Block]
        self.filter_view = filter_view  # list[Block] -> list[str], or None for no filter
        self.feed = feed  # list[Block] -> list[str]
        self.budget = budget  # characters actually injected; 0 means no cap


def arm_conditions(name: str) -> dict:
    """Stated conditions of each arm, for the experiment ledger."""
    from bench.ledger import cond

    base, _, budget = name.partition("@")
    index, filter_view, feed = {
        "A:raw->raw": ("颜色原文块", "原文片段", "原文块（去重）"),
        "B:summary->summary": ("颜色摘要", "摘要", "摘要"),
        "C:summary->raw": ("颜色摘要", "原文片段", "原文块（去重）"),
        "D:fused->raw": ("颜色摘要 + 颜色原文块（RRF）", "-", "原文块（去重）"),
        "D1:fused->raw": ("颜色摘要 + 颜色原文块（RRF）", "原文片段", "原文块（去重）"),
        "D2:fused+rerank->raw": ("颜色摘要 + 颜色原文块（RRF）", "摘要 + 原文片段", "原文块（去重）"),
        "ref:win10": ("原文", "-", "合并去重的窗口原文"),
        "ref:win10+filter": ("原文", "原文片段", "合并去重的窗口原文"),
        "ref:win5": ("原文", "-", "合并去重的窗口原文"),
        "V:summary->raw": ("颜色摘要（向量）", "-", "原文块（去重）"),
        "V:raw->raw": ("颜色原文块（向量）", "-", "原文块（去重）"),
        "DV:fused4->raw": ("摘要 + 原文块，关键词和向量四路 RRF", "-", "原文块（去重）"),
        "Dq:quota->raw": ("摘要 + 原文块，关键词两路，每路保底 3 块", "-", "原文块（去重）"),
        "DVq:quota4->raw": ("四路，每路保底 2 块", "-", "原文块（去重）"),
        "E1:rrf4": ("四路（关键词 + 向量）全局 RRF，严格按名次打包", "-", "原文块（去重）"),
        "E2:rr4": ("四路，各路轮流取候选", "-", "原文块（去重）"),
        "E3:reserve4": ("四路，每路先预留 1/4 预算，再按全局 RRF 补齐", "-", "原文块（去重）"),
        "E4:aware4": ("四路，按 RRF 分数 ÷ √新增字数贪心选块", "-", "原文块（去重）"),
        "E1:rrf2": ("关键词两路全局 RRF，严格按名次打包", "-", "原文块（去重）"),
        "E2:rr2": ("关键词两路，轮流取候选", "-", "原文块（去重）"),
        "E3:reserve2": ("关键词两路，每路先预留 1/2 预算，再按全局 RRF 补齐", "-", "原文块（去重）"),
        "E4:aware2": ("关键词两路，按 RRF 分数 ÷ √新增字数贪心选块", "-", "原文块（去重）"),
    }.get(base) or depth_index(base)
    filtered = filter_view != "-" and not budget
    chunking = "10 条窗口" if base.startswith("ref:win10") else "5 条窗口" if base == "ref:win5" else "颜色块"
    top_k = (int(base[1:].split(":")[0]) if base.startswith("K") else 10 if base.startswith("E") else 30) if budget else (NO_FILTER_TOP if base == "ref:win10" else TOP)
    tokenizer = "qwen3.7-text-embedding-flash（768 维）" if base.startswith("V:") else (
        "jieba+习得词 + qwen3.7-text-embedding-flash" if base.startswith("DV") or base.endswith("4") else "jieba+习得词")
    return cond(
        index=index, chunking=chunking, tokenizer=tokenizer, top_k=top_k, filter="是" if filtered else "否",
        filter_view=filter_view if filtered else "-", feed=feed, budget_chars=int(budget) if budget else "不限",
        model_main=DEFAULT_MODEL, model_filter=DEFAULT_MODEL if filtered else "-", judge=JUDGE_MODEL, seed=0,
    )


def depth_index(base: str) -> tuple[str, str, str]:
    """K<n>:rrf4 arms of the depth experiment: E1 with n candidates per route."""
    if not re.fullmatch(r"K\d+:rrf4", base):
        raise KeyError(base)
    return (f"四路（关键词 + 向量）每路前 {base[1:].split(':')[0]}，全局 RRF，严格按名次打包", "-", "原文块（去重）")


def within_budget(blocks, feed, budget: int) -> tuple[list, list[str]]:
    """Take ranked blocks while the injected text fits; the first block is cut to fit if needed."""
    taken: list = []
    for block in blocks:
        if sum(len(t) for t in feed(taken + [block])) > budget:
            break
        taken.append(block)
    if not taken and blocks:
        first = feed(blocks[:1])
        return blocks[:1], [first[0][:budget]] if first else []
    return taken, feed(taken)


def prepare(args) -> SimpleNamespace:
    """Data, models, questions and the two keyword indexes shared by every retrieval experiment."""
    raw = realdata.load_group(args.group)
    messages = sanitized(clean_messages(raw), Sanitizer(raw))
    by_id = {m.msg_id: m for m in messages}
    order = {m.msg_id: i for i, m in enumerate(messages)}
    end_ts = messages[-1].timestamp + 1
    channel = args.group
    main_llm = BatchLLM(args.out / "s0.main.cache.jsonl", DEFAULT_MODEL, args.workers)
    fast_llm = BatchLLM(args.out / "s0.fast.cache.jsonl", DEFAULT_MODEL, args.workers)
    judge_llm = BatchLLM(args.out / "s0.judge.cache.jsonl", JUDGE_MODEL, args.workers)

    merged = (json.loads(args.labels.read_text(encoding="utf-8")) if args.labels
              else {"questions": {"rejected": [], "awkward": []}})
    questions = load_questions(
        args.out, messages, end_ts, main_llm, fast_llm, args.extra_segments, set(merged["questions"]["rejected"])
    )
    awkward = set(merged["questions"]["awkward"])

    import jieba

    jieba.initialize()
    split_ts = messages[int(len(messages) * 0.7)].timestamp
    learned = tuple(
        w for w in slang.mine_words([m for m in messages if m.timestamp < split_ts], lambda w: bool(jieba.get_FREQ(w)))
        if not re.search(r"P\d", w)
    )
    tok = tokenize.make_jieba(learned)
    colors = [json.loads(x) for x in (args.out / "colors.gemini-3.8-flash-high.jsonl").read_text(encoding="utf-8").splitlines()]
    summary_blocks = chunking.from_colors(messages, colors, "summary")
    raw_color_blocks = chunking.from_colors(messages, colors, "raw")
    by_color = {b.block_id: b for b in raw_color_blocks}
    summary_of = {b.block_id: b.index_text for b in summary_blocks}
    summary_index = BM25(summary_blocks, tok)
    raw_index = BM25(raw_color_blocks, tok)
    return SimpleNamespace(**{k: v for k, v in locals().items() if k != "args"})


def evaluate_arm(arm: Arm, conditions, llms, awkward: set[str], raw_path: Path | None = None) -> dict:
    """Retrieve, optionally filter, inject, answer and judge every condition for one arm.

    raw_path receives one record per condition with every prompt, output and token count.
    """
    fast_llm, main_llm, judge_llm = llms
    retrieved, chosen, memories, filter_prompts, answer_prompts = build_inputs(arm, conditions, fast_llm)
    return _answer_and_judge(arm, conditions, (fast_llm, main_llm, judge_llm), awkward, raw_path,
                             retrieved, chosen, memories, filter_prompts, answer_prompts)


def build_inputs(arm: Arm, conditions, fast_llm):
    """Everything up to the answer prompt: retrieval, optional filter, budget and injected text.

    Without a filter this makes no model calls, so a new arm's answer prompts can be checked
    against the cache before anything is sent.
    """
    retrieved = [arm.retrieve(q["question"], t) for q, t, _ in conditions]
    filter_prompts: list[str] = [""] * len(conditions)
    if arm.filter_view is None:
        chosen = retrieved
    else:
        prompts = []
        for (q, _, _), blocks in zip(conditions, retrieved):
            lines = [f"[{i}] {text}" for i, text in enumerate(arm.filter_view(blocks), 1)]
            prompts.append(f"问题：{q['question']}\n候选：\n" + "\n".join(lines) if lines else "")
        outs = iter(fast_llm.map(FILTER, [p for p in prompts if p], role=f"筛选|{arm.name}"))
        chosen = []
        for blocks, p in zip(retrieved, prompts):
            picked: list[int] = []
            if p:
                found = re.search(r"\[[\d,\s]*\]", next(outs) or "")
                if found:
                    picked = [i for i in json.loads(found.group(0)) if 1 <= i <= len(blocks)]
            chosen.append([blocks[i - 1] for i in picked])
        filter_prompts = prompts
    if arm.budget:
        capped = [within_budget(blocks, arm.feed, arm.budget) for blocks in chosen]
        chosen = [c[0] for c in capped]
        memories = [c[1] for c in capped]
    else:
        memories = [arm.feed(blocks) for blocks in chosen]
    answer_prompts = [
        f"问题：{q['question']}\n记忆：\n" + ("\n---\n".join(mem) or "（无）")
        for (q, _, _), mem in zip(conditions, memories)
    ]
    return retrieved, chosen, memories, filter_prompts, answer_prompts


def _answer_and_judge(arm, conditions, llms, awkward, raw_path, retrieved, chosen, memories, filter_prompts,
                      answer_prompts) -> dict:
    fast_llm, main_llm, judge_llm = llms
    raw_answers = main_llm.map(ANSWER, answer_prompts, role=f"回答|{arm.name}")
    answers = [final_of(o) for o in raw_answers]
    judge_prompts = [
        f"问题：{q['question']}\n标准答案：{q['answer']}\n回答：{a}"
        for (q, _, visible), a in zip(conditions, answers) if visible
    ]
    verdicts = iter(judge_llm.map(JUDGE, judge_prompts, role=f"判官|{arm.name}"))
    judge_prompt_of = iter(judge_prompts)
    rows, records = [], []
    for (q, as_of, visible), found, blocks, mem, a, fp, ap in zip(
            conditions, retrieved, chosen, memories, answers, filter_prompts, answer_prompts):
        row = {
            "id": q["id"], "visible": visible, "answer": a, "empty": not mem,
            "msgs": injected_messages(blocks), "chars": sum(len(x) for x in mem),
            "overlap": silver.char_overlap(q["question"], q["evidence_text"]),
            "gold_injected": bool(set(q["gold"]) & {i for b in blocks for i in b.msg_ids}),
        }
        jp = None
        if visible:
            jp = next(judge_prompt_of)
            v = final_of(next(verdicts)).lower()
            row["correct"] = "correct" in v and "incorrect" not in v
        else:
            row["refused"] = is_refusal(a)
        rows.append(row)
        if raw_path:
            from bench import rawlog

            records.append({
                "arm": arm.name, "question_id": q["id"], "visible": visible, "as_of": as_of,
                "question": q["question"], "gold_answer": q["answer"], "gold_msg_ids": q["gold"],
                "retrieved": [b.block_id for b in found], "chosen": [b.block_id for b in blocks],
                "injected": mem, "filter": rawlog.call_record(fast_llm, FILTER, fp),
                "answer": rawlog.call_record(main_llm, ANSWER, ap), "final_answer": a,
                "judge": rawlog.call_record(judge_llm, JUDGE, jp),
                **{k: row[k] for k in ("correct", "refused", "overlap", "gold_injected", "chars", "msgs") if k in row},
            })
    if raw_path:
        from bench import rawlog

        rawlog.write(raw_path, records)
    pos = [r for r in rows if r["visible"]]
    neg = [r for r in rows if not r["visible"]]
    return {
        "accuracy": round(sum(r["correct"] for r in pos) / len(pos), 4),
        "accuracy_ci95": [round(x, 3) for x in metrics.bootstrap_ci([float(r["correct"]) for r in pos])],
        "accuracy_without_awkward": round(
            sum(r["correct"] for r in pos if r["id"] not in awkward) / max(1, sum(r["id"] not in awkward for r in pos)), 4
        ),
        "accuracy_low_overlap": round(
            sum(r["correct"] for r in pos if r["overlap"] == "low") / max(1, sum(r["overlap"] == "low" for r in pos)), 4
        ),
        "gold_injected": round(sum(r["gold_injected"] for r in pos) / len(pos), 4),
        "refusal_when_absent": round(sum(r["refused"] for r in neg) / max(len(neg), 1), 4),
        "empty_when_present": round(sum(r["empty"] for r in pos) / len(pos), 4),
        "avg_msgs": round(sum(r["msgs"] for r in pos) / len(pos), 1),
        "avg_chars": round(sum(r["chars"] for r in pos) / len(pos)),
        "conditions": arm_conditions(arm.name),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path, help="merged.json from a labeling round, if the group has one")
    ap.add_argument("--extra-segments", type=int, default=220)
    ap.add_argument("--absent", type=int, default=150, help="questions also asked before their answer existed")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--budget", type=int, default=1500, help="characters injected in the no-filter arms")
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("this run sends data out and is DEV only")

    ctx = prepare(args)
    messages, by_id, order, end_ts, channel = ctx.messages, ctx.by_id, ctx.order, ctx.end_ts, ctx.channel
    main_llm, fast_llm, judge_llm = ctx.main_llm, ctx.fast_llm, ctx.judge_llm
    questions, awkward, tok = ctx.questions, ctx.awkward, ctx.tok
    summary_blocks, raw_color_blocks, by_color = ctx.summary_blocks, ctx.raw_color_blocks, ctx.by_color
    summary_of, summary_index, raw_index = ctx.summary_of, ctx.summary_index, ctx.raw_index
    window_index = BM25(chunking.fixed_window(messages, 10, 5), tok)

    def search(index, k=TOP):
        return lambda q, t: [b for b, _ in index.search(q, t, k, channel)]

    def fused(q, t):
        return [b for b, _ in rrf([summary_index, raw_index], by_color, q, t, TOP, channel)]

    # Filter views stay one entry per block so the picked numbers line up; only the feed drops repeats.
    raw_view = lambda bs: raw_blocks_aligned(bs, by_id)  # noqa: E731
    summary_view = lambda bs: [summary_of[b.block_id] for b in bs]  # noqa: E731
    both_view = lambda bs: [f"{summary_of[b.block_id]}\n原文：{t}" for b, t in zip(bs, raw_blocks_aligned(bs, by_id))]  # noqa: E731
    windows_feed = lambda bs: merged_windows(bs, by_id, order)  # noqa: E731
    arms = [
        Arm("A:raw->raw", search(raw_index), raw_view, lambda bs: raw_blocks(bs, by_id)),
        Arm("B:summary->summary", search(summary_index), summary_view, summary_view),
        Arm("C:summary->raw", search(summary_index), raw_view, lambda bs: raw_blocks(bs, by_id)),
        Arm("D1:fused->raw", fused, raw_view, lambda bs: raw_blocks(bs, by_id)),
        Arm("D2:fused+rerank->raw", fused, both_view, lambda bs: raw_blocks(bs, by_id)),
        Arm("ref:win10", search(window_index, NO_FILTER_TOP), None, windows_feed),
        Arm("ref:win10+filter", search(window_index), raw_view, windows_feed),
    ]
    raw_feed = lambda bs: raw_blocks(bs, by_id)  # noqa: E731
    deep = lambda index: search(index, 30)  # noqa: E731
    window5_index = BM25(chunking.fixed_window(messages, 5, 3), tok)
    arms += [
        Arm(f"{name}@{args.budget}", retrieve, None, feed, args.budget)
        for name, retrieve, feed in (
            ("A:raw->raw", deep(raw_index), raw_feed),
            ("B:summary->summary", deep(summary_index), summary_view),
            ("C:summary->raw", deep(summary_index), raw_feed),
            ("D:fused->raw", lambda q, t: [b for b, _ in rrf([summary_index, raw_index], by_color, q, t, 30, channel)], raw_feed),
            ("ref:win10", deep(window_index), windows_feed),
            ("ref:win5", deep(window5_index), windows_feed),
        )
    ]

    absent_ids = {q["id"] for q in random.Random(0).sample(questions, min(args.absent, len(questions)))}
    conditions = [(q, end_ts, True) for q in questions] + [(q, q["first_ts"], False) for q in questions if q["id"] in absent_ids]

    report: dict = {
        "group": args.group, "questions": len(questions), "absent_questions": len(absent_ids), "arms": {},
        "data": {"colors": fingerprint(args.out / "colors.gemini-3.8-flash-high.jsonl"),
                 "questions": fingerprint(args.out / "q2b_questions.json"), "labels": fingerprint(args.labels) if args.labels else ""},
    }
    for arm in arms:
        from bench import rawlog

        report["arms"][arm.name] = evaluate_arm(arm, conditions, (fast_llm, main_llm, judge_llm), awkward,
                                                rawlog.arm_file(args.out, "abcd", arm.name))
        print(arm.name, {k: v for k, v in report["arms"][arm.name].items() if k != "rows"}, flush=True)
        (args.out / "abcd.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    def correct(name):
        return {r["id"]: float(r["correct"]) for r in report["arms"][name]["rows"] if r["visible"]}

    ids = sorted(correct("ref:win10"))
    pairs = {}
    at = f"@{args.budget}"
    comparisons = [("ref:win10", n) for n in report["arms"] if n != "ref:win10" and not n.endswith(at)]
    comparisons += [("ref:win10" + at, n) for n in report["arms"] if n.endswith(at) and n != "ref:win10" + at]
    for prefix, suffix in (("", ""), ("", at)):
        names = {k: f"{k}{suffix}" for k in ("A:raw->raw", "B:summary->summary", "C:summary->raw")}
        comparisons += [(names["A:raw->raw"], names["B:summary->summary"]), (names["A:raw->raw"], names["C:summary->raw"]),
                        (names["C:summary->raw"], names["B:summary->summary"])]
    comparisons += [("A:raw->raw", "D1:fused->raw"), ("D1:fused->raw", "D2:fused+rerank->raw"),
                    ("ref:win10", "ref:win10+filter"), ("A:raw->raw" + at, "D:fused->raw" + at)]
    for a, b in comparisons:
        x, y = correct(a), correct(b)
        pairs[f"{b} vs {a}"] = metrics.paired_delta([x[i] for i in ids], [y[i] for i in ids])
    report["paired"] = pairs
    report["tokens"] = {"main": main_llm.tokens, "filter": fast_llm.tokens, "judge": judge_llm.tokens}
    (args.out / "abcd.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    from bench import ledger, usage
    from bench.ledger_backfill import abcd

    usage.write(args.out / "usage.abcd.json", "R4/I3 检索对象 × 交给模型")

    ledger.append(args.out.parent / "ledger.jsonl", abcd(args.out.parent, args.out.name))
    print("done", json.dumps(report["tokens"]))
    return 0


def raw_blocks_aligned(blocks, by_id, limit: int = 300) -> list[str]:
    """Raw text per block without cross-block dedupe, so it lines up with each summary."""
    out = []
    for b in blocks:
        lines = [f"{by_id[i].author}: {by_id[i].content}" for i in b.msg_ids
                 if by_id[i].content and not is_sensitive(by_id[i].content)]
        out.append("\n".join(lines)[:limit] or "（无文字）")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
