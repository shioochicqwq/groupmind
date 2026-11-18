<div align="center">

<h1>groupmind</h1>

<p><b>A group-chat companion bot with long-term memory · research prototype</b></p>

<p>
<a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square"></a>
<img alt="Python 3.12 | 3.13" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB?style=flat-square&logo=python&logoColor=white">
<img alt="OneBot v11" src="https://img.shields.io/badge/OneBot-v11-black?style=flat-square">
<img alt="Status: research prototype" src="https://img.shields.io/badge/status-research%20prototype-orange?style=flat-square">
</p>

<p><a href="README.md">简体中文</a> | <b>English</b></p>

</div>

A chat bot that lives in QQ groups as a "group member", and the research on long-term memory for Chinese group chats built around it.

> **This is a work in progress.** The research part has fairly complete experiment records. The bot host runs end to end in shadow testing, but it has never posted in a real group. The project was published halfway through; deployment and compatibility were never finished. The deployment setup depends on the author's own environment and is **hard to reproduce as is**. There are no plans to fix this for now; the project may be improved later.

## Start with these two

- **[Architecture overview](docs/overview/architecture.en.md)**: how a "group member with memory" is put together — the message path, the three layers of memory data, coloring and the frozen retrieval pipeline, session compaction and handoff, tools, and current status and limitations.
- **[Research summary](docs/overview/research-report.en.md)**: experimental findings on long-term memory for Chinese QQ group chats, with references.

## Main findings

On two real development groups (about 16,000 and 46,000 messages) with 876 cross-week question-answering items:

- **The model must be given the original text.** Giving only summaries scores 10–21 percentage points lower than giving raw-text chunks.
- **Four-route retrieval with shallow candidate lists.** BM25 and vector retrieval over both summaries and raw text, fused with RRF, taking only the top 5 per route. The initial frozen version beat a fixed-window baseline with the same budget by 12.5 and 17.2 percentage points (significant in paired comparison). On DEV-2, taking 20 or more candidates per route was significantly worse.
- **The bottleneck is finding the evidence, not using it.** Once the evidence is in the context, the model answers about 93–95% correctly.
- **The model barely understands group-specific memes**, and a snippet of context does not help; a meme table is required, and the meme table's recall is in turn the main bottleneck for the next step.
- **"Human-like" needs a different yardstick.** People recall conversations by "remembering little, but what they remember is mostly right." The impression-formation and recall-policy mechanisms run, but have not been validated with human blind evaluation.

All findings come from the development sets; the frozen version has not been validated on an independent test set.

## Repository layout

| Directory | Contents |
|---|---|
| `bothost/` | Bot host: OneBot I/O, one agent session per group, MCP tools, session handoff, getting to know people |
| `deploy/dsh/` | Patches and plugins for the agent kernel (dsh): session handoff `handoff.mjs`, persona-aware compaction |
| `deploy/wsl/` | Current deployment scripts and templates (Windows + WSL) |
| `plugins/` | Readers for web pages and videos (directory names are left over from the AstrBot era; bothost imports them directly) |
| `bench/` | Memory research bench: import, coloring, retrieval, evaluation, judging, ledger |
| `scripts/memory/` | Person and meme snapshots, retrieval CLI |
| `tests/` | `tests/bothost` (host, with a fake model and fake OneBot), `tests/bench` |
| `docs/` | Design, research, handover. Documents marked "outdated" (已过时) are from the AstrBot era |

More entry points (in Chinese):

- Current system, code map, known issues: [docs/handover-2026-11-16.md](docs/handover-2026-11-16.md)
- The reasoning behind each decision: [DECISIONS.md](DECISIONS.md) (D-001 to D-056)
- Chronological development log: [PROJECT.md](PROJECT.md)
- Deployment (Windows PC + WSL): [deploy/wsl/README.md](deploy/wsl/README.md)

## About deployment

Please read the "Status and limitations" section of the architecture overview first. In short:

- It has only run in one environment: a WSL distribution on a Windows PC, with scheduled tasks and a script that pushes updates by hand.
- It depends on internal interfaces of [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) 0.2.1-rc.4; other versions need to be re-verified.
- The only protocol endpoint tried is SnowLuma (OneBot v11).
- Model endpoints and keys are passed in through config and environment variables. The template is `deploy/wsl/config.example.json`; field descriptions are in `bothost/config.py`. In some scripts the default endpoint is the placeholder `<GATEWAY_HOST>`, which you need to set yourself.
- `deploy/windows`, `deploy/linux` and `scripts/bootstrap_*` are from the AstrBot era and no longer apply.

The tests need no real account or model (they use a fake model and a fake OneBot):

```bash
python -m pytest -q tests/bothost tests/bench
```

`tests/bothost` needs `dsh` 0.2.1-rc.4 on PATH.

## Data and privacy

- Real chat logs, personas, human annotations and keys are **not in the repository**.
- Code, tests and docs contain no real chat content, QQ numbers or group numbers. Groups are always referred to by 6-character codes; numbers in the docs are aggregate statistics.
- Account numbers, group numbers, group names and some infrastructure addresses that appeared in past commits were replaced with placeholders (such as `<ADMIN_QQ>`, `<GROUP_ID>`, `<GATEWAY_HOST>`) before publication.
