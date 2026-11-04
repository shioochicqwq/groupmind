"""Validate the pipeline: BM25 on GroupMemBench, following its baseline's QA and judge shape."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bench import chunking, tokenize
from bench.datasets import groupmembench as gmb
from bench import rawlog, usage
from bench.llm import DEFAULT_MODEL, JUDGE_MODEL, BatchLLM
from bench.metrics import bootstrap_ci
from bench.retrievers.bm25 import BM25

AGENT = (
    "You are a careful QA agent. Use only the retrieved conversation passages to answer the question.\n"
    "First provide a chain-of-thought reasoning paragraph. Then provide the final answer on a new line using the "
    "format:\nFinal: <answer>\nIf the answer is not supported by the retrieved passages, say so in the Final line."
)
JUDGE = (
    "You are a strict judge evaluating whether an agent's answer matches the gold answer for a question.\n"
    "Consider paraphrases correct if they have the same meaning as the gold answer.\n"
    "First provide a brief reasoning paragraph. Then provide the final judgment on a new line using the format:\n"
    "Final: Correct\nor\nFinal: Incorrect"
)


def final_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if re.match(r"\s*final( answer)?:", line, re.I):
            return line.split(":", 1)[1].strip()
    return (text or "").strip()


def verdict(text: str) -> bool | None:
    tail = final_line(text).lower()
    if "incorrect" in tail or "wrong" in tail or "not correct" in tail:
        return False
    return True if "correct" in tail else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--domain", default="Technology")
    ap.add_argument("--agent-model", default=DEFAULT_MODEL)
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    messages = gmb.load_messages(args.repo, args.domain)
    index = BM25(chunking.single_message(messages), tokenize.word)
    formatted = gmb.format_passages(args.repo, args.domain)
    agent = BatchLLM(args.out / "agent.cache.jsonl", args.agent_model)
    judge = BatchLLM(args.out / f"judge.{args.judge_model}.cache.jsonl", args.judge_model)

    results, per_type, raw = [], {}, []
    for qtype in gmb.QTYPES:
        questions = gmb.load_questions(args.repo, args.domain, qtype)
        prompts, retrieved_ids = [], []
        for q in questions:
            asker = q.get("asking_user_id") or ""
            hits = index.search(f"{asker} {q['question']}" if asker else q["question"], float("inf"), args.k)
            passages = []
            retrieved_ids.append([b.block_id for b, _ in hits])
            for i, (block, _) in enumerate(hits, 1):
                passages.append(f"[{i}] {formatted[block.msg_ids[0]]}")
            head = f"Asking user: {asker}\n\n" if asker else ""
            prompts.append(
                f"{head}Question:\n{q['question']}\n\nRetrieved passages:\n" + "\n\n".join(passages)
                + "\n\nAnswer the question using the retrieved passages."
            )
        answers = agent.map(AGENT, prompts, role="回答")
        judge_prompts = [
            f"Question:\n{q['question']}\n\nGold answer:\n{q.get('answer', '')}\n\nAgent answer:\n{final_line(a)}"
            for q, a in zip(questions, answers)
        ]
        verdicts = judge.map(JUDGE, judge_prompts, role="判官")
        scores = []
        for q, a, v, ap, jp, ids in zip(questions, answers, verdicts, prompts, judge_prompts, retrieved_ids):
            ok = verdict(v) if a and v else None
            results.append({"id": q["id"], "qtype": qtype, "correct": ok})
            raw.append({
                "question_id": q["id"], "qtype": qtype, "question": q["question"], "gold_answer": q.get("answer", ""),
                "asking_user_id": q.get("asking_user_id"), "retrieved": ids,
                "answer": rawlog.call_record(agent, AGENT, ap), "final_answer": final_line(a),
                "judge": rawlog.call_record(judge, JUDGE, jp), "correct": ok,
            })
            scores.append(float(bool(ok)))
        per_type[qtype] = {"n": len(scores), "acc": round(100 * sum(scores) / max(len(scores), 1), 2)}
        print(qtype, per_type[qtype], agent.tokens, flush=True)

    flat = [float(bool(r["correct"])) for r in results]
    lo, hi = bootstrap_ci(flat)
    summary = {
        "domain": args.domain,
        "per_type": per_type,
        "micro": round(100 * sum(flat) / len(flat), 2),
        "ci95": [round(100 * lo, 1), round(100 * hi, 1)],
        "macro": round(sum(v["acc"] for v in per_type.values()) / len(per_type), 2),
        "failed_calls": sum(r["correct"] is None for r in results),
        "tokens": {"agent": agent.tokens, "judge": judge.tokens},
        "agent_model": args.agent_model,
        "judge_model": args.judge_model,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (args.out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results), encoding="utf-8")
    usage.write(args.out / "usage.gmb.json", "B1 GroupMemBench")
    rawlog.write(args.out / "raw" / f"gmb.judge={args.judge_model}.jsonl", raw)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
