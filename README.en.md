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

**groupmind is an AI RolePlay solution**, broadly made up of these basic features
Memory: chunking and retrieving the raw text; long-term memory and impressions
Web module: raising the success rate of reading web pages that have anti-bot protection
Session handoff: when the model is stuck on a long tool call, a new session takes over, so the stuck old session no longer leaves group messages unanswered
Around this goal, the project also ran a set of experiments on long-term memory for Chinese group chats.

> **This is a work in progress.** The bot runs end to end in shadow mode (what it would say is only recorded, not sent to the group), and the memory research has fairly complete experiment records; but it has **never posted in a real group**, and deployment was never finished — it has only run in our own environment and is hard to reproduce as is. There are no plans to fix deployment for now; the project may be improved later.

## What it can do

| Capability | How | Status |
|---|---|---|
| **Long-term memory** | All raw messages go into SQLite; a model "colors" messages into micro-context segments; summaries and raw-text chunks each get keyword and vector indexes, four retrieval routes are fused, and **only raw text is given to the model**; recent messages not yet colored are searched one by one by keyword | Implemented; the retrieval scheme was validated on development sets, not on an independent test set; automatic coloring after going live is not wired in |
| **Session management** | One long session per group; the system prompt stays fixed so the cache keeps hitting, while newly known people and background results are appended at the start of the next turn; when the context is nearly full, the persona-bearing model writes its own "memo to itself" to compact it | Implemented, running in shadow testing |
| **Session handoff** | Slow work such as watching a video or reading a page that needs a browser is finished in the old session; the host forks a new session that carries on in the group, and the old session's result comes back as a quote-reply to the original message and as an internal note for the new session | Implemented, with end-to-end tests; tool calls longer than 5 minutes fail |
| **Web module** | A separate conversation without the persona searches and reads pages, returning only a conclusion; page reading escalates from a page-reading API through a request with a browser fingerprint to a real Chrome, raising the success rate against anti-bot checks; with SSRF protection | Implemented, running in shadow testing |
| Watching videos | Download, compress, split and hand to a video model | Implemented; video files sent directly in QQ have not been tested on real messages |
| Knowing people, understanding memes | People are identified by stable account, with nicknames, impressions and attitudes; general and group-specific memes form two layers, and the meme table is human-confirmed | Implemented; the quality of what the bot records by itself has not been assessed, and meme candidate mining is still the bottleneck |
| Event layer, impression formation, recall-policy layer | See the research report | Research prototypes, not wired into the bot |
| Proactive speaking | — | Does not exist |

## A few distinctive design choices

- **The raw text is the source of truth; summaries are only retrieval entry points.** Summaries, colors, people and memes are all derived artifacts that can be rebuilt; what the model answers from is always the original words.
- **Searching shallow finds more.** Each of the four retrieval routes contributes only its top 5 candidates before fusion; taking more actually pushes out key evidence that ranks first in only one route.
- **Keep the prefix fixed; append the changes.** The people table is updated only when the cache prefix has to be rebuilt anyway, and background results enter the next turn as "internal notes" instead of being inserted into a request in progress.
- **Slow work leaves the session that talks.** Session handoff stops "being present" and "getting things done" from blocking each other.

The data structures, execution order, failure handling and code entry points of each mechanism are in the **[architecture overview](docs/overview/architecture.en.md)**.

## Research findings

A common role-play memory design is "chat history → summaries → a vector index of the summaries → retrieve summaries and inject them". groupmind keeps the raw text instead, and splits retrieval into three layers measured separately. On two real development groups (about 16,000 and 46,000 messages) with 876 cross-week question-answering items:

- **Raw-text injection**: with retrieval unchanged, changing only what the model receives from summaries to raw text raises accuracy by 17.5 and 9.8 percentage points.
- **Multi-route retrieval**: on top of color chunks, adding the summary and vector routes and taking only 5 candidates per route adds 8.4 and 14.6 points in total — the layer that contributes the most.
- **Coloring as a way of chunking**: 4.1 and 2.6 points above 10-message windows under the same budget, with weak evidence; moreover, the model almost never puts one message into more than one color, and merging colors into long chunks makes things significantly worse.
- **The bottleneck is finding the evidence**: once it is in the context, the model answers about 93–95% correctly.
- **The model barely understands group-specific memes**, and a snippet of context does not help.

All findings come from the development sets; the frozen version has not been validated on an independent test set, and the "human-likeness" part has had no human blind evaluation. Concept explanations and each experiment's hypothesis, controlled conditions and limitations are in the **[research report](docs/overview/research-report.en.md)**.

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
