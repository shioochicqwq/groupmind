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

**groupmind aims to be a long-term "group member" in QQ groups**: it remembers what happened in the group months ago, knows the people in it, understands the group's memes, responds when someone @-mentions it, and doesn't leave the whole group hanging while it fact-checks something or watches a video. Around this goal, the project also ran a set of experiments on long-term memory for Chinese group chats.

> **This is a work in progress.** The bot runs end to end in shadow mode (what it would say is only recorded, not sent to the group), and the memory research has fairly complete experiment records; but it has **never posted in a real group**, and deployment was never finished — it has only run in the author's own environment and is hard to reproduce as is. There are no plans to fix deployment for now; the project may be improved later.

## What it can do

| Capability | How | Status |
|---|---|---|
| **Staying in the group for the long term** | One long session per group; the prefix is kept stable so the cache keeps hitting; when the context is nearly full, the persona-bearing model writes its own "memo to itself" to compact it | Implemented, running in shadow testing |
| **Recall** | Raw messages are append-only; a model "colors" messages into micro-context segments; summaries and raw-text chunks are indexed, four retrieval routes are fused, and **only raw text is given to the model** | Implemented; the retrieval scheme was validated on development sets, not on an independent test set |
| **Knowing people** | People are identified by stable account, with nicknames, impressions and attitudes; the bot records them itself and also adds to them in compaction memos | Implemented; the quality of what it records by itself has not been assessed |
| **Understanding memes** | General memes and group-specific memes form two layers; the meme table goes into the system prompt after human confirmation | Meme table implemented; candidate mining is still the bottleneck |
| **Web fact-checking** | A separate conversation without the persona searches and reads pages, returning only a conclusion; page reading escalates from a cheap API up to a real browser, with SSRF protection | Implemented, running in shadow testing |
| **Watching videos** | Download, compress, split and hand to a video model | Implemented; video files sent directly in QQ have not been tested on real messages |
| **Session handoff** | Slow work is finished in the old session while a forked new session carries on in the group; the result comes back as a quote-reply to the original message | Implemented, with end-to-end tests; tool calls longer than 5 minutes fail |
| Coloring after going live, event layer, impression formation, recall-policy layer | See the research report | Research prototypes, not wired into the bot |
| Proactive speaking | — | Does not exist |

## A few distinctive design choices

- **The raw text is the only source of truth.** Summaries, colors, people and memes are all derived artifacts that can be rebuilt; summaries only help find the raw text, and what the model is given to answer from is always the original words.
- **Searching shallow finds more.** Each of the four retrieval routes contributes only its top 5 candidates before fusion; taking more actually pushes out key evidence that ranks first in only one route.
- **Keep the prefix fixed; append the changes.** The people table is updated only when the cache prefix has to be rebuilt anyway, and background results enter the next turn as "internal notes" instead of being inserted into a request in progress.
- **Slow work leaves the session that talks.** Session handoff stops "being present" and "getting things done" from blocking each other.

The full design motivation, the approaches given up and their costs are in the **[architecture overview](docs/overview/architecture.en.md)**.

## Research findings

On two real development groups (about 16,000 and 46,000 messages) with 876 cross-week question-answering items:

- **The model must be given the raw text**: giving only summaries scores 10.8–20.9 percentage points below giving raw-text chunks.
- **Four-route fusion with shallow candidate lists works best**: the initial version beat a fixed window with the same budget by 12.5 and 17.2 percentage points; the current version's end-to-end accuracy is 84.1% and 71.1%.
- **The bottleneck is finding the evidence**: once it is in the context, the model answers about 93–95% correctly.
- **Some counter-intuitive findings**: the model almost never puts one message into more than one color; merging colors into long chunks makes things significantly worse; and the advantage of coloring as a way of chunking, over fixed windows, is not solid.
- **The model barely understands group-specific memes**, and a snippet of context does not help.

All findings come from the development sets; the frozen version has not been validated on an independent test set, and the "human-likeness" part has had no human blind evaluation. The question, hypothesis, controlled conditions and limitations of each experiment are in the **[research report](docs/overview/research-report.en.md)**.

## Status and deployment

- It has only run in one environment: a dedicated WSL distribution on a Windows PC, with scheduled tasks and a script for pushing updates by hand. There is no container image; isolation relies mainly on the dedicated distribution, an ordinary user and "the shell writes only to its workspace" — there is no container sandbox.
- It depends on internal interfaces of [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) 0.2.1-rc.4; the only protocol endpoint tried is SnowLuma (OneBot v11).
- The tests need no real account or model (they use a fake model and a fake OneBot): `python -m pytest -q tests/bothost tests/bench`; `tests/bothost` needs dsh 0.2.1-rc.4 on PATH.

<details>
<summary>Deployment details and repository layout</summary>

- Model endpoints and keys are passed in through config and environment variables. The template is `deploy/wsl/config.example.json`; field descriptions are in `bothost/config.py`. In some scripts the default endpoint is the placeholder `<GATEWAY_HOST>`, which you need to set yourself.
- The current deployment steps are in [deploy/wsl/README.md](deploy/wsl/README.md) (Chinese). `deploy/windows`, `deploy/linux` and `scripts/bootstrap_*` are from the AstrBot era and no longer apply.

| Directory | Contents |
|---|---|
| `bothost/` | Bot host: OneBot I/O, one agent session per group, MCP tools, session handoff, getting to know people |
| `deploy/dsh/` | Patches and plugins for the agent kernel (dsh): session handoff, persona compaction |
| `deploy/wsl/` | Current deployment scripts and templates (Windows + WSL) |
| `plugins/` | Readers for web pages and videos (directory names are left over from the AstrBot era) |
| `bench/` | Memory research bench: import, coloring, retrieval, evaluation, judging, ledger |
| `scripts/memory/` | Person and meme snapshots, retrieval CLI |
| `tests/` | `tests/bothost` (with a fake model and fake OneBot), `tests/bench` |
| `docs/` | Design, research, handover. Documents marked "outdated" (已过时) are from the AstrBot era |

</details>

## Further reading

| To learn about | Read |
|---|---|
| Why it is designed this way | [Architecture overview](docs/overview/architecture.en.md) |
| What the experiments did and how far to trust them | [Research report](docs/overview/research-report.en.md) |
| The current system, code map, known issues | [docs/handover-2026-11-16.md](docs/handover-2026-11-16.md) (Chinese) |
| The reasoning behind each decision | [DECISIONS.md](DECISIONS.md) (Chinese) |
| Chronological development log | [PROJECT.md](PROJECT.md) (Chinese) |

## Data and privacy

- Real chat logs, personas, human annotations and keys are **not in the repository**.
- Code, tests and docs contain no real chat content, QQ numbers or group numbers. Groups are always referred to by 6-character codes, numbers in the docs are aggregate statistics, and example conversations are fictional.
- Account numbers, group numbers, group names and some infrastructure addresses that appeared in past commits were replaced with placeholders (such as `<ADMIN_QQ>`, `<GROUP_ID>`, `<GATEWAY_HOST>`) before publication.

## License

[Apache-2.0](LICENSE)
