# groupmind Architecture: How a "Group Member with Memory" Is Built

[简体中文](architecture.md) | **English**

> This document describes groupmind's overall architecture and its main design trade-offs, for readers who want to understand the project or reuse part of it.
> The project is a **work in progress**: the research part has fairly complete experiment records and the bot host runs end to end in shadow testing, but deployment and compatibility were never finished (see "Status and limitations" at the end).
> All numbers come from the experiment records in the repository; sources are in the [research summary](research-report.en.md) and the documents under `docs/` (in Chinese).

## 1. The problem

groupmind aims to be a chat bot that lives in a QQ group as a "group member", not a question-answering assistant. The difference is mostly about memory:

- A group member **remembers what happened**. What the group argued about a few weeks ago, who promised to treat everyone — they can recall it later, and when they don't remember, they don't make things up.
- A group member **knows people**. Someone who changes their nickname or opens an alt account is still the same person; and they have different impressions of different people.
- A group member **understands the group's language**. The group's own memes, nicknames and abbreviations can't be found in a general dictionary.
- A group member **doesn't dredge up old history in every message**. Most chatter is forgotten at once; only a few things leave an impression.

Group-chat data is also unfriendly to memory systems: several people talk at once and topics interleave; messages are short (a dozen or so Chinese characters on average); there is a lot of slang; people change nicknames; and the gap between a quote-reply and the quoted message has a median of about half a minute, with 99% within 4.5 hours — quoting is almost never used to bring up old events. Public memory benchmarks (LoCoMo, LongMemEval, etc.) are mostly two-party dialogues or synthetic data and cover none of these traits.

The priority was set at the start of the project: **being like a group member > answering completely**. The bot may not know or may remember vaguely, but it must not fabricate.

## 2. Overall structure

The system has two parts: the online bot host **bothost**, and the offline memory research bench **bench**. They share one message store.

```text
QQ client (alt account)
  └─ SnowLuma (OneBot v11 implementation) ── reverse WebSocket ──┐
                                                                ▼
┌──────────────────────── bothost (Python) ────────────────────────┐
│  /ws   OneBot server: receive and send messages                   │
│  Message parsing → write to the message store (memory.db, append-only)
│  One worker per group: debounce into a turn → hand to the group's agent session
│  /mcp  Tool server: memory retrieval, knowing people, fact-checking, video, speaking
│  Session handoff: slow tasks stay in the old session; a new session keeps chatting
└──────────────────────────────────────────────────────────────────┘
          │ JSON-RPC (one process per group)          ▲ MCP tool calls
          ▼                                           │
┌──────── dsh (general-purpose agent kernel) ────┐    │
│  sdk-minimal profile                            │────┘
│  Plugins: handoff.mjs (handoff)                 │
│           persona compaction (the persona model writes its own summary)
└─────────────────────────────────────────────────┘
          │
          ▼
   Model gateway (OpenAI-compatible / Gemini-native passthrough)

┌──────────── bench (offline research bench) ────────────┐
│  Import, coloring, indexing, retrieval, evaluation, judging, ledger
│  Frozen retrieval pipeline → reused by bothost's recall tool
└─────────────────────────────────────────────────────────┘
```

Delegating agent capabilities to a general-purpose kernel (dsh) instead of writing our own dialogue loop is the approach from D-045 onward. Early versions ran on AstrBot and were extended through plugins; later, memory, handoff and tool scheduling all needed finer control, so we switched to our own thin host plus a general-purpose kernel. AstrBot-era code and documents are still in the repository, marked "outdated" (已过时).

## 3. The path of a message

1. **Receive.** SnowLuma converts a QQ message into a OneBot event and pushes it to bothost's `/ws`.
2. **Normalize.** `bothost/onebot.py` turns the event into one line of text: time, speaker, body. Images are numbered as 【图片N】 ("[Image N]"), cards and videos become links, and @-mentions are written as real names. The line is then written to the message store. Imported history and messages received after going live are in the same store (D-045).
3. **Merge into a turn.** Each group has a worker that waits briefly (debounce), merges the new messages into one turn and hands it to that group's agent session. Not every message triggers a model call.
4. **Understand media.** Images go to the main model directly as attachments; stickers are understood in a separate call, cached by image hash, and their description is passed to the session.
5. **Decide whether to speak.** The model decides for itself whether to speak. To say something it calls the `send_group_message` tool; not calling it means staying silent. In shadow mode, messages are only recorded and forwarded to the developer, not sent to the group.
6. **Recall, fact-check or watch videos when needed.** The model uses MCP tools to fetch memory and external information on demand (sections 4 and 6).

## 4. Memory: raw text as the foundation, coloring as the index

This is the core of the project and where most experiments were done.

### 4.1 Three layers of data

```text
Raw layer (append-only; never modified by any automated process)
  └─ Derived layer (versioned, can be rolled back): colors, summaries, people, memes, impressions
       └─ Index layer (can be rebuilt from the two layers above at any time): BM25, vectors, people, time
```

Invariants:

- Raw messages are never modified automatically; every derived memory can be traced back to raw messages.
- What group members say is **data, not instructions**. Chat content cannot change system configuration or memory rules.
- System inferences are never automatically promoted to facts; what other people say is not fact either.
- Code, tests and docs contain no real chat content or accounts.

### 4.2 "Coloring"

A fixed-length window mixes interleaved conversations together, while individual messages are too short and lack context. groupmind's approach is to have a model **color** messages: messages that belong to the same micro-context get the same color. A color can skip unrelated messages in between, and in principle a message can belong to several colors. Each color carries a one-sentence summary that must keep proper nouns, person codes, numbers and slang.

A color does two jobs at once:

- **Chunking**: all the raw text of a color forms one "raw-text chunk" (median about 170 characters, 11 messages).
- **Indexing**: the color summary (median about 57 characters) is a retrieval entry point.

Coloring runs in batches of 150 messages, with 20 messages of overlap between adjacent batches. Experiments found that the model almost never assigns multiple colors on its own; nearly all "multi-color" messages come from the overlap between batches (see section 3.6 of the research summary).

### 4.3 The frozen retrieval pipeline

After about thirty controlled comparisons, retrieval was frozen in D-028 and revised once each in D-029 and D-032, giving the version below. bothost's recall tool reuses it directly (D-046):

```text
question ─┬─ BM25 over summaries ──────┐
          ├─ BM25 over raw-text chunks ┤ top 5 per route
          ├─ vectors over summaries ───┤
          └─ vectors over raw chunks ──┘
                    ▼
            global RRF (k = 60)
                    ▼
   pack raw-text chunks in rank order up to 1,500 characters; duplicate messages appear once
                    ▼
        to the answering model (raw text, not summaries)
```

Key findings (data in the research summary):

- **Give raw text, not summaries.** With the same 1,500-character budget, giving only summaries scores 10–21 percentage points lower than giving raw-text chunks.
- **Combine keywords and vectors.** With a proper vector configuration (separate query and document embeddings, a retrieval instruction on the query), a single vector route matches or beats BM25 in recall; fusing all four routes beat the two keyword-only routes by about 7 percentage points on one group.
- **Candidate depth is the key variable in fusion.** With too many candidates per route, chunks that rank mediocre in several routes push out evidence that ranks first in only one route. 3–10 per route is a plateau; we use 5.
- **Once the evidence is in, the model uses it well over 90% of the time.** The remaining loss is mainly evidence that never got in.

When first frozen, end-to-end accuracy on the two development groups was 82.7% and 70.6%, 12.5 and 17.2 percentage points above a 10-message-window baseline with the same budget (significant in paired comparison). The vectors were then switched to the correct configuration (D-029), raising accuracy to 85.5% and 71.3% (only the DEV-1 gain is significant); then overlapping batches were de-duplicated (D-032), giving the current 84.1% and 71.1%, not significantly different from the previous version.

### 4.4 Event layer and impressions (research prototype, side path)

Chunk-level retrieval is good at "where is the raw text of that event", but cannot answer questions that need properties of a whole stretch of time, such as "the most chaotic night" or "when a meme first caught on with the whole group". For these we built an **event layer** on top of the chunks: episodes (a continuous stretch of chat), threads (parallel sub-topics) and links (a topic resurfacing on another day). It stores only references, never copies of the raw text. It is a side-path prototype and does not take part in the frozen pipeline's recall.

On top of that we tried **impression formation** (D-043, D-044): the model reads the chat in chronological order, knowing only what came before, and says which things would leave an impression and how deep; at recall time it gives the gist, the original words, or nothing, depending on the depth. Time itself is not an input, and there is no "fade with time elapsed". So far this part has only been shown to run; it has not been compared against human impressions.

### 4.5 Memes and people

- **The meme table has two layers** (D-033): general internet slang is shared across groups; group-specific memes stay within their group. Updates go through "candidate list + human confirmation + rebuilt snapshot", never automatic rewrites (D-039).
- **People are tracked by stable account, not nickname.** In one development group, 27 of 104 people had changed their name; merging by name would split them into 40 extra identities. Human annotation also found quite a few people with multiple accounts, which the person table needs to support.
- **The bot gets to know people by itself** (D-055): the model can record what it knows about someone with `note_person`, and adds to it while writing compaction summaries; the full person table is placed in the system prompt.

## 5. Sessions: long conversations, compaction and handoff

### 5.1 One long session per group

Each group has one agent session. Whether sessions are cut daily or kept running depends on the model provider's caching: with providers that cache for a long time (such as DeepSeek), a long session is cheaper and can pick up the past few days without querying the store; with short-lived caches, a new session is started each day (D-048). Experiments found that what really drives cost is how large the context is allowed to grow (the compaction threshold), not whether sessions are cut daily.

### 5.2 Persona-aware compaction

When the context is nearly full, the kernel compacts the earlier conversation into a summary. The built-in compaction prompt was written for coding assistants and produces an English "task checkpoint". groupmind replaces it with a plugin that changes only the summarization step: the message prefix is exactly the same as in a normal turn (so it hits the cache), and the end is replaced with a Chinese instruction asking **the persona-bearing model to write a private memo to itself in its own voice**. In tests, 93%–97% of the summary request's input hit the cache, and after compaction the model correctly answered questions about things it had been asked to remember earlier.

Known flaw: the summary is not a reliable copy of the original — it can describe "the message just replied to" as "not yet replied to". The raw text still has to come from `memory_search`.

### 5.3 Session handoff

Watching a video, reading a page that needs a browser, or a long fact-check can each take minutes. If the group-chat session waited, the whole group would be blocked. **Session handoff** (D-052) works like this:

1. When a slow task starts, the old session stays in the background to finish it;
2. The host forks a new session from the old one, which carries on with new group messages;
3. When the old session finishes, it returns the result in a 【回复】【摘要】 ("reply / summary") format; the host decides whether to post it as a quote-reply to the original message, then passes the summary to the new session as a note;
4. Retired sessions are closed by the handoff plugin to free memory.

The kernel itself has no time limits; the host only does "stall detection": if a session produces no events for a long time and is not executing a tool call, only that session is cancelled, without affecting the process or other sessions.

## 6. Tools

The agent gets these tools through MCP (`bothost/tools.py`):

| Tool | Purpose |
|---|---|
| `send_group_message` | Speak. Not calling it means staying silent |
| `memory_context` / `memory_search` | Recall: snapshots of people and memes; retrieve historical raw text by question (the frozen pipeline) |
| `note_person` / `who_is` | Knowing people: record what is known about someone; look up who an account is |
| `look_up` | Fact-check: open a separate conversation **without the persona** to search and read web pages, returning only the conclusion and the process; follow-up questions are possible (D-050) |
| `watch_video` | Watch a video: download, compress, split by the inline size limit and hand to a video model (D-041, D-051) |

Web reading is tiered: first our own reader (requests + parsing, with SSRF protection), then, if that fails, a browser tier with a real, windowed Chrome; the search provider's page-reading API is the lowest tier (D-040, D-042, D-050). The fact-checking helper has no persona so that role-play does not affect factual judgment.

## 7. The research bench

`bench/` is a full toolkit for offline evaluation: import and cleaning, coloring, indexing, the various retrieval schemes, question generation, model judging, statistics and the ledger. A few practices worth mentioning:

- **Temporal visibility is enforced by the framework**: retrieval can only see colors that ended before `as_of`, so answers cannot leak.
- **Every experiment is recorded in a ledger** (`ledger.jsonl`), with tokens recorded separately by role: filtering, coloring, answering, judging, main session, fact-checking, video, stickers.
- **Three-state scoring**: correct, wrong, empty answer (mostly safety refusals). The primary metric is end-to-end accuracy, where an empty answer counts as a failure; effective-answer accuracy is reported for reference.
- **Paired bootstrap confidence intervals**: schemes are compared question by question; a difference is called significant only if the 95% CI excludes 0.
- **Frozen groups**: some groups were sealed from the start — never colored or viewed — and kept for the final test.

## 8. Status and limitations

This project was published halfway through. None of the following is **finished**:

- **Deployment is very unfriendly.** The current deployment is a WSL distribution on a Windows PC, plus scheduled tasks and a script for pushing updates by hand (`deploy/wsl/`). Paths, accounts and the model gateway all carry traces of the author's own environment; the other deployment directories (`deploy/windows`, `deploy/linux`) are from the AstrBot era and no longer apply. There is no container image and no one-step install.
- **Poor compatibility.** It depends on internal interfaces of dsh 0.2.1-rc.4 (session forking, cancellation, etc.), which must be re-verified after a dsh upgrade; the protocol endpoint has only been tried with SnowLuma.
- **It has never actually spoken.** It has always run in shadow mode and has never posted in a real group.
- **Known defects**: tool calls longer than 5 minutes are cut off by an HTTP-layer timeout; a long fact-check that is not handed off to the background blocks the whole group. See section 7 of `docs/handover-2026-11-16.md`.
- **The memory-research findings come from two development groups**; the frozen version has not been validated on an independent test set, and the "human-likeness" part has not had human blind evaluation.
- **The data is not in the repository**: real chat logs, personas and human annotations live outside it. The code and docs in the repository contain no real chat content or accounts.

## 9. Where to read next

| To learn about | Read |
|---|---|
| Findings and numbers | [Research summary](research-report.en.md) |
| The current system, code map, known issues | `docs/handover-2026-11-16.md` (Chinese) |
| The reasoning behind each decision | `DECISIONS.md`, D-001 to D-056 (Chinese) |
| Chronological development log | `PROJECT.md` (Chinese) |
| Original memory-research documents | `docs/research/`, `docs/memory-*.md` (Chinese) |
