# Long-Term Memory for Chinese QQ Group Chats: Research Summary

[简体中文](research-report.md) | **English**

> This document summarizes groupmind's memory research from October–November 2026, for readers who want the findings without reading every experiment record.
> Detailed methods, per-question data and every correction are in the original documents (in Chinese): the phase-one reports [v1](../research/2026-11-memory-stage-report.md), [v2](../research/2026-11-memory-stage-report-v2.md) and [v3](../research/2026-11-memory-stage-report-v3.md), the experiment results [memory-benchmark-results.md](../memory-benchmark-results.md), the experiment ledger [memory-benchmark-ledger.md](../memory-benchmark-ledger.md), and the dated research notes under `docs/research/`.
> This document contains no real chat content. Groups are always referred to by codes; all numbers are aggregate statistics.

## Abstract

We designed and evaluated a long-term memory system for a bot that takes part in Chinese QQ group chats as a "group member". The system keeps every raw message. A model "colors" messages into micro-context segments, each with a one-sentence summary; retrieval indexes both the summaries and the raw-text chunks, and what is finally given to the answering model is raw text.

On two real development groups (about 16,000 and 46,000 messages), we ran about thirty controlled comparisons using 876 cross-week question-answering items. Main findings:

1. **The model must be given the original text.** Giving only summaries scores 10–21 percentage points lower.
2. **Combine keywords and vectors, and keep candidate lists shallow.** Four-route retrieval (summary/raw × BM25/vector) fused with RRF, taking only the top 5 per route, was the best configuration. The initial frozen version beat a 10-message-window baseline with the same budget by 12.5 and 17.2 percentage points (significant in paired comparison).
3. **The bottleneck is finding the evidence, not using it.** Once the evidence is in the context, the model's accuracy is about 93–95%; the remaining errors are mainly evidence that was not retrieved.
4. **Group chat has its own patterns.** The gap between a quote-reply and the quoted message has a median of about half a minute, with 99% within 4.5 hours, so quote-replies cannot serve as samples of long-term memory. Group-specific memes are fewer than expected, but the model barely understands them and a meme table is required. Many people change nicknames or use several accounts, so people can only be tracked by stable account.
5. **"Human-like" is a different yardstick.** People recall conversations by "remembering little, but what they remember is mostly right." We tried impression formation and a recall-policy layer; the mechanisms run, but have not been validated with human blind evaluation.

All findings come from the development sets; the frozen version has not been validated on an independent test set.

---

## 1. Problem

### 1.1 Goal

The bot's goal is to be a **group member with memory**: remember what happened, know the people in the group, understand the group's memes, recall old events naturally at the right moment, and not be led astray by irrelevant memories. The priority is "being like a group member > answering completely": it may not know or may remember vaguely, but it must not fabricate.

Phase one studied only the most basic piece of this, **recalling and injecting historical evidence**:

> Given a question *q* about past group chat and a time point *t*, the system may use only messages before *t*, and must select a set of raw messages within a fixed injection budget to give to the answering model. We evaluate whether the answer is correct; when the answer only appears after *t*, we evaluate whether the system abstains.

### 1.2 What is special about group-chat data

| Trait | Observed | Effect on retrieval |
|---|---|---|
| Many speakers, interleaved | Several topics often run in parallel at the same time | A fixed window mixes unrelated talk together, while a single message lacks context |
| Short messages | A context segment has a median of about 170 characters and 11 messages, a dozen or so characters each | Sparse lexical signal; per-message retrieval does worst |
| Quotes are close in time | 10,792 quote-replies across the two development groups: median gap about half a minute, 99% within 4.5 hours, only 6 quoting a message more than a day old | "Quote reconstruction" cannot be the main metric for long-term memory |
| Nickname changes | 27 of 104 people changed their name | Merging by name creates 40 extra identities |
| Slang | Among human-judged candidates, most were general internet slang; group-specific ones were a minority | A general dictionary is not enough; group memes must be learned separately |
| Safety refusals | About 2% of the tested model's calls returned empty | Empty answers must be recorded separately |

Public memory benchmarks are mostly two-party dialogues (LoCoMo [1], LongMemEval [2]) or synthetic English group chats (GroupMemBench [3], SocialMemBench [4]); none of them include the short messages, slang, nickname changes and interleaving of Chinese group chats. As a reference point we reproduced GroupMemBench's Technology subset: per-message BM25 scored 44.6% overall (95% CI 38.5–51.2) against 46.0% reported in the paper, suggesting the evaluation framework is broadly sound.

---

## 2. Method

### 2.1 Data

The data comes from the user's own QQ chat export. Groups were selected by aggregate statistics without looking at content. Before anything was sent to a model, names were replaced with pseudonyms, contact details and long numbers were masked, and messages matching high-sensitivity terms were withheld.

| | DEV-1 | DEV-2 |
|---|---:|---:|
| Messages after cleaning | 15,841 | 46,200 |
| Speakers | 104 | 81 |
| Time span | about 116 days | about 78 days |
| Colors (context segments) | 828 | 2,451 |

There are also validation groups and **frozen groups**: the frozen groups were sealed from the start — never colored or viewed — and kept for the final test. All numbers in this document come from the two development groups.

### 2.2 Coloring

A model reads messages in batches (150 messages per batch, with 20 messages of overlap between adjacent batches) and marks messages that belong to the same micro-context with the same color. A color can skip unrelated messages in between, and a message can belong to several colors. For each color the model outputs a type, a name, a one- or two-sentence summary (which must keep proper nouns, person codes, numbers and slang) and the message IDs.

The idea behind coloring is that a color is both a **way of chunking** the raw text and a **retrieval entry point**: the raw text is kept so it can be given to the model, and the summary exists so the chunk can be found. This differs from storing only extracted facts; an existing controlled experiment also shows that raw-text chunks clearly outperform storing only extraction results [5].

### 2.3 Evaluation

- **Questions**: 876 cross-week QA items, generated by a model from earlier chat and checked by a separate call; 105 of them were reviewed by three people. Each question is asked once while its answer is visible; another 150 are also asked before the answer appears, to test abstention.
- **Temporal visibility**: enforced by the framework; retrieval can only see colors that ended before `as_of`.
- **Injection budget**: a fixed number of characters (mostly 1,500), filled in rank order and stopping when the next chunk does not fit; duplicate messages are counted once.
- **Judging**: another model acts as judge. Each question is scored as correct, wrong or empty answer (mostly safety refusals). **End-to-end accuracy** (an empty answer counts as a failure) is the primary metric; **effective-answer accuracy** is reported for reference.
- **Statistics**: schemes are compared question by question with bootstrap 95% confidence intervals; a difference is called "significant" only if the interval excludes 0. No correction for multiple comparisons was applied.
- **Ledger**: every experiment is recorded as one row, with token usage recorded separately by role.

---

## 3. Results: retrieval and injection

### 3.1 Raw text or summaries

| Given to the model | DEV-1 end-to-end | DEV-2 end-to-end |
|---|---:|---:|
| Raw-text chunks (BM25 over raw text) | 74.3 | 56.0 |
| Summaries (BM25 over summaries) | 53.4 | 45.2 |
| Retrieve by summary, give raw text | 70.9 | 55.0 |

(1,500-character budget.)

**Giving only summaries is significantly worst**: 20.9 and 10.8 percentage points below raw-text chunks. The details a summary drops are exactly what QA needs. Retrieving by summary and giving raw text performs about the same as retrieving raw text directly. This is consistent with the existing finding that raw-text chunks beat extraction results [5].

### 3.2 Keywords and vectors

At first, vector retrieval alone had lower evidence recall than BM25 on every route and at every candidate depth. A later ablation found this was mainly a **configuration problem**: the embedding calls did not distinguish queries from documents, and queries carried no retrieval instruction. The Qwen3 Embedding paper [7] explicitly uses an "instruction + query" input. After the fix:

| Vector configuration | DEV-1 raw-text route R@5 | DEV-2 raw-text route R@5 |
|---|---:|---:|
| Original configuration | 73.0 | 49.8 |
| Separate query/document + retrieval instruction | 80.7 | 63.5 |
| Same, with a larger model | 84.5 | 67.2 |
| Reference: BM25 raw-text route | 80.7 | 59.4 |

The vector raw-text route matched or exceeded BM25, with the largest gains on questions with low lexical overlap. Two smaller findings: removing pseudonyms made the raw-text route significantly worse, which suggests "who said it" is itself a useful retrieval signal; and prepending the summary to the raw text made things worse.

But **only a small part of the recall gain turned into accuracy**: vector-route R@5 rose by 6–17 percentage points, while the evidence-inclusion rate after four-route fusion rose by only 1–3 points, because the keyword routes already covered most of the evidence.

### 3.3 Multi-route fusion and candidate depth

Fusing the four routes (summary/raw × BM25/vector) with reciprocal rank fusion (RRF [8]) was the best of all schemes. But the effect depends heavily on **how many candidates each route contributes** (the table below is under the initial vector configuration; after switching to the correct configuration this was retested, and top 5 per route was still the best on both groups):

| Candidates per route | DEV-1 end-to-end | DEV-2 end-to-end |
|---:|---:|---:|
| 3 | 83.0 | 69.3 |
| **5** | **82.7** | **70.6** |
| 10 | 82.0 | 70.0 |
| 20 | 81.1 | 66.7 |
| 30 | 79.8 | 66.3 |

With 30 candidates per route, chunks that rank mediocre in several routes accumulate RRF score and push out key evidence that ranks first in only one route, beyond the 1,500-character budget. 3–10 per route is a plateau; 20 or more is significantly worse on DEV-2. The frozen version takes the top 5 per route.

The packing method also matters. Filling strictly in RRF rank order, or taking from the routes in turn, both work well; reserving a fixed number of characters per route, or discounting scores by "newly added characters", are both significantly worse (−11 to −24 percentage points).

### 3.4 The frozen version

The final frozen retrieval is: four routes, top 5 per route, global RRF (k=60), raw text packed in rank order up to 1,500 characters, duplicate messages removed.

| | DEV-1 | DEV-2 |
|---|---:|---:|
| 10-message-window baseline (same budget) | 70.2 | 53.4 |
| ① Initial frozen version (D-028) | 82.7 | 70.6 |
| ② ① + correct vector configuration (D-029) | 85.5 | 71.3 |
| ③ ② + de-duplication of batch overlap (D-032, current version) | 84.1 | 71.1 |

- ① over the window baseline (+12.5, +17.2) is significant on both groups.
- ② vs ①: DEV-1 +2.7 (95% CI +0.5 to +5.2, significant), DEV-2 +0.7 (−2.3 to +3.4, not significant).
- ③ vs ②: DEV-1 −1.4 (−3.4 to +0.7), DEV-2 −0.2 (−2.5 to +2.1), neither significant. ③ did not improve accuracy; it was kept because it removes duplicate coloring and is the more sound design (D-032).

### 3.5 Where the errors are

For questions whose evidence entered the context under the frozen version, the model answered 92.9% (DEV-1) and 94.6% (DEV-2) correctly. The remaining loss is mainly **evidence that did not get in**: on DEV-2, 28% of questions had no evidence in the injected context. So the next thing to improve is recall, not answering.

For the few questions answered wrongly even though the evidence was present, the evidence chunks were on average further back, with more distracting text before them. This points in the same direction as the finding that performance drops when relevant information sits in the middle of a long context [6], but our injection is only about 1.3k characters — very different conditions — and no causal test was done.

Two other checks:

- **BM25 scores cannot decide "when to stay silent"**: comparing the top score for the same query with the answer visible and not visible gives a discriminative power (AUC 0.55–0.61) close to chance. Whether to recall should be left to the model.
- **A filtering model**: first having a cheap model pick the relevant candidates cut the injected messages from 71 to 11 on average, with no significant drop in accuracy.

### 3.6 Problems with coloring itself

The design allows a message to belong to several colors. A batch-by-batch check found **almost no multi-color messages within a batch** (only 3 and 30 in the two groups); the statistical "13% multi-color" came almost entirely from the overlap region between adjacent batches being colored twice. In other words, the model was effectively doing **near-single-label local segmentation**.

Merging similar colors from adjacent batches into long chunks significantly lowered the evidence-inclusion rate (−5.9 and −7.3 percentage points), because one long chunk can fill the whole budget. Only removing duplicates while keeping chunk boundaries had no measurable effect. Adding a layer of "global topics" did not help either. Conclusion: retrieval quality depends mainly on local segment structure. The real structural problems (the model does not assign multiple colors on its own, and colors cannot continue across batches) need to be solved at the coloring stage; that has not been done.

---

## 4. Results: memes and people

### 4.1 Memes

**The model understands only about half of general memes and barely understands group-specific ones.** Tested on 71 words whose meanings were confirmed by humans (with no memory at all):

| Condition | General layer | Group layer |
|---|---:|---:|
| Word only | 48.2% | 26.7% |
| Word + a chat snippet using it | 64.7% | 26.7% |

Adding a snippet of context significantly helps the general layer (+17.6 percentage points, 95% CI +3.9 to +31.4; small sample). The group layer has only 15 words, and context did not help (4 correct, unchanged); a meme table is required. The model answers "I don't know" about 30% of the time, and when it does give an explanation it is mostly right, so "I don't know" can serve as a trigger for consulting the meme table or searching the web.

**The meme table's recall is the main bottleneck.** When looking up relevant history by context alone, raw-text retrieval almost never finds the target word (only 2–5% of results contain it). The meme table finds some, raising fill-in accuracy from 10.6% to 15–18% (significant, but on a small sample: 85 questions, 40 words, and the words were not human-confirmed). Human annotation found that group-specific memes are mostly lost at the "evidence threshold" step: the threshold (at least 5 occurrences, 3 people, 2 days) kept out many genuine group memes.

The meme table therefore has two layers: general memes are shared across groups, group-specific memes stay within their group; updates go through "candidates + human confirmation" and are never rewritten automatically.

Among related open-source implementations, MaiBot's slang learning [9] decides whether a word is slang by checking whether "the meaning inferred from context" agrees with "the meaning inferred from the word alone". None of the projects we surveyed goes beyond "storing an explanation"; none measures "having learned it", that is, whether the bot can correctly understand and use the term in new conversations.

### 4.2 People

In one group, 27 of 104 people changed their name; merging by name would split them into 40 extra identities. Human annotation also found 6 people each with 2–3 accounts **in use at the same time**. People must be tracked by stable account, with support for multiple accounts per person; nicknames also often come from other groups or from outside the group.

---

## 5. Making memory human-like

The research above uses QA accuracy as its yardstick. But "being like a group member" has another side: people do not remember chats from months ago in perfect detail. This part **switches yardsticks** and judges by "how human-like".

### 5.1 From mechanisms to behavior

We first read mechanistic research on memory from cognitive science: complementary learning systems [10], emotional modulation of consolidation [11], event segmentation [12, 13], and so on. These describe neural mechanisms and give no behavioral numbers that could be used for tuning. Existing "human-like memory" systems [14, 15] take the same route: all use hand-set decay constants, and none has had humans judge "how human-like" they are. The only one with serious human evaluation, MADial-Bench [16], shows that human-likeness can only be judged by people, and that automatic metrics disagree with human rankings. Another study [17] found that models do not forget what is in their context and show no serial-position effect, so human-likeness cannot be expected to come from the model itself.

Turning instead to **how people behave when recalling conversations**, there are concrete behavioral numbers: 20 minutes after a three-person conversation, people can recall only 12–30% of it, but about 96% of what they recall is correct, and about 96% of the attributions of who said it are correct [18]. So "human-like" is mainly about **low coverage, gist rather than wording, and appropriately hedged statements**, not about misremembering. This conflicts with accuracy less than we first thought. Another study warns that memory consolidation can turn hedged statements into confident facts [19], so the original uncertain wording should be preserved in storage.

### 5.2 How group members themselves recall

We looked for "group members recalling" passages in the development groups (containing markers such as 记得 "remember", 上次 "last time", 来着 "what was it again") and had a model label them:

- Most of what group members recall is not group chat; recalls of in-group conversations are only 14–20%.
- They almost never quote the original words (2–3%); about 60% give the gist and about 30% only mention that something happened; about 20% use uncertain wording.
- The step of "matching a recall to the original message" is currently unreliable: two models' judgments almost never agreed.

Based on this we built a **recall-policy layer** v0: without calling a model, it uses "who said it, how long ago, whether it was a joke, whether it was brought up again later" to decide, for each piece of evidence, whether to give the original words, the gist, only that it happened, or nothing. The memory text given to the answering model dropped from about 1,280 characters to 210–540. No answers have been generated with it yet, and there has been no blind evaluation.

### 5.3 Impression formation

The user rejected "fading by time elapsed" and asked instead for the model to **form impressions of events**. The model reads the chat in chronological order, knowing only what came before, and states which things would leave an impression, how deep (deep, medium, shallow), why (funny, surprising, conflict, big event, novel, emotional), and writes down the gist; for deep impressions it also records one or two original sentences. At recall time the granularity depends on the depth of the impression. Time itself is not an input.

- **"Most of it drifts by like passing clouds" did emerge**: messages that left an impression were 12–16% of the total, more than half of the days left nothing, and the number of impressions per month did not decline over time.
- **Whether "some sentence is remembered vividly" depends on one sentence in the prompt**: with the line "deep ones are rare; don't exaggerate" in the prompt, there were almost no deep impressions; without it, there were some. The threshold is set by wording, and there is currently no basis for saying which is more human-like.
- **The gist is too short to answer detailed questions**; the benchmark questions are a rather harsh test for impression-based memory.
- Whether the model's impressions match a human's **has not been tested at all**; the blind-evaluation page is ready but the evaluation has not been completed.

This part is close in spirit to Generative Agents' [20] "recency × importance × relevance" and EM-LLM's [21] "segmenting events by surprise", but it has no time decay; impressions form "at the moment of reading".

---

## 6. Engineering findings

These are not the main line of the memory research, but may be useful when building similar systems.

- **The persona-bearing model can write its own compaction summary.** Replacing the compaction prompt with "write a private memo to yourself in your own voice" gave 93–97% cache hits on the summary request's input, and after compaction the model answered follow-up questions correctly. Both kinds of summary share one flaw: they can describe "the message just replied to" as "not yet replied to". A summary cannot replace the raw text.
- **Session lifetime**: under the same context limit, a long session is cheaper than starting a new session each day, and can pick up the past few days without querying the store. What drives cost is the compaction threshold, not whether sessions are cut daily. Providers with short-lived caches are the exception.
- **Session handoff**: slow tasks (watching videos, long fact-checks) are finished in the old session while a forked new session keeps chatting in the group; retired sessions must be closed explicitly. The kernel itself needs no time limit; the host only needs "stall detection".
- **Separating fact-checking from the persona**: web fact-checking runs in a separate conversation without the persona and returns only the conclusion, so role-play does not affect factual judgment.
- **Model refusals**: about 2% of calls return empty, and the more numerous and mixed the injected content, the more likely this is. It is itself a cost of a scheme, which is why the primary metric counts empty answers as failures.

---

## 7. Limitations

- **Only two development groups**; the questions were model-generated (part of them human-reviewed) and parameters were chosen on the development sets. The frozen version has not been validated on an independent test set.
- **No correction for multiple comparisons**; many comparisons only just pass the significance threshold and should be considered weak evidence.
- **The judge is a model.** The human-reviewed sample is small.
- **None of the "human-like" work has had human blind evaluation**; so far we can only say the mechanisms run.
- **Coloring used one model and one prompt**; other segmentation methods (such as predicting reply relations first and then clustering) were not compared.
- A recent study points out that naive raw-text retrieval often matches complex memory systems on several memory benchmarks [22]. Our results point in the same direction (raw text and simple fusion work best), but we did not compare directly against other memory frameworks [23, 24] on the same data.

## 8. Unfinished directions

- A final test on the frozen groups.
- Improving the coloring stage: letting colors continue across batches and encouraging multiple colors.
- The meme table's evidence threshold: relax or rewrite it, and check against the existing human annotations.
- Deciding "whether to recall at all", using the last few chat messages as the query, and proactive mentions.
- Human blind evaluation of impressions and the recall-policy layer.
- Interference tests (whether injected irrelevant memories get forced into the conversation) and cross-group leakage tests.

---

## References

All of the references below are cited in the project's research documents, which mark how thoroughly each source was checked (full text, abstract, or search-result summary). Where a source was marked "abstract", this document cites only the direction of its findings and did not check its specific numbers.

**Memory benchmarks**

1. Maharana, A. et al. *Evaluating Very Long-Term Conversational Memory of LLM Agents* (LoCoMo). ACL 2024.
2. Wu, D., Wang, H., Yu, W., Zhang, Y., Chang, K.-W., Yu, D. *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory.* ICLR 2025. arXiv:2410.10813.
3. Yang, J., Lai, K.-H., Wang, X., Chang, S., Harari, Y., Gabrilovich, E. *GroupMemBench: Benchmarking LLM Agent Memory in Multi-Party Conversations.* arXiv:2605.14498, 2026.
4. Owolabi, O. *SocialMemBench: Are AI Memory Systems Ready for Social Group Settings?* arXiv:2605.17789, 2026.
- Li, Y. et al. *Locomo-Plus: Beyond-Factual Cognitive Memory Evaluation Framework for LLM Agents.* arXiv:2602.10715, 2026. (We borrowed its method of filtering out lexically similar distractors.)

**Retrieval and long context**

5. An, T. *Fidelity Before Structure: Verbatim Chunks Beat Lossy Artifact Extraction in Long-Conversation LLM Memory.* arXiv:2601.00821, 2026.
6. Liu, N. F. et al. *Lost in the Middle: How Language Models Use Long Contexts.* TACL, 2024. arXiv:2307.03172.
7. Zhang, Y. et al. *Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models.* arXiv:2506.05176, 2025.
8. Cormack, G. V., Clarke, C. L. A., Büttcher, S. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods.* SIGIR 2009.

**Group-chat bots and knowledge acquisition**

9. MaiBot (slang learning and the A_Memorix memory module). https://github.com/MaiM-with-u/MaiBot

**Cognitive science**

10. Kumaran, D., Hassabis, D., McClelland, J. L. *What Learning Systems do Intelligent Agents Need? Complementary Learning Systems Theory Updated.* Trends in Cognitive Sciences 20(7), 512–534, 2016. doi:10.1016/j.tics.2016.05.004
11. McGaugh, J. L. *The amygdala modulates the consolidation of memories of emotionally arousing experiences.* Annual Review of Neuroscience 27, 1–28, 2004. doi:10.1146/annurev.neuro.27.070203.144157
12. Zacks, J. M. et al. Work on event segmentation, 2007.
13. Baldassano, C. et al. *Discovering Event Structure in Continuous Narrative Perception and Memory.* Neuron, 2017.
- Also consulted: Conway & Pleydell-Pearce (2000), self-memory system model of autobiographical memory; Talarico & Rubin (2003), flashbulb memories; Tse et al. (2007), schemas and rapid consolidation; Bjork & Bjork, reviews on forgetting and retrieval.

**Human-like memory and conversational recall**

14. Hou, Y., Tamoto, H., Miyashita, H. *"My agent understands me better": Integrating Dynamic Human-like Memory Recall and Consolidation in LLM-Based Agents.* CHI EA '24. arXiv:2404.00573.
15. Kerestecioglu et al. *Human-Inspired Memory Architecture for LLM Agents.* arXiv:2605.08538, 2026.
16. *MADial-Bench.* NAACL 2025. arXiv:2409.15240.
17. *Analyzing Memory Effects in Large Language Models through the Lens of Cognitive Psychology.* arXiv:2509.17138.
18. Brown-Schmidt, Jaeger, Lord & Benjamin. *Remembering conversation in group settings.* Memory & Cognition, 2024.
19. Kwon, A. *Manufactured Confidence: How Memory Consolidation Turns Hearsay into Confident Facts.* arXiv:2606.29279, 2026.
- Also consulted: *Forgetful but Faithful* (arXiv:2512.12856); Zhong et al., *Random Tree Model of Meaningful Memory* (arXiv:2412.01806); Bietti & Mayor (2023), *A longitudinal study of conversational remembering in WhatsApp group messages*, Memory, Mind & Media 2, e5; Chen, Molina, Liao & Cho (2026), *AI Never Forgets*, CHI '26; Tsfasman et al. (2024), the MeMo corpus (arXiv:2409.13715).

**Agent memory systems**

20. Park, J. S. et al. *Generative Agents: Interactive Simulacra of Human Behavior.* UIST 2023. arXiv:2304.03442.
21. Fountas, Z. et al. *Human-like Episodic Memory for Infinite Context LLMs* (EM-LLM). ICLR 2025. arXiv:2407.09450.
22. Bao et al. *Is Complex Agentic Memory Always Needed? Naive RAG Is Stronger Than We Thought.* arXiv:2610.30755, 2026.
23. Chhikara, P. et al. *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory.* arXiv:2504.19413, 2025.
24. Packer, C. et al. *MemGPT: Towards LLMs as Operating Systems.* arXiv:2310.08560, 2023.

**Engineering references on session compaction**: the context-compaction documentation of OpenClaw, Hermes Agent, NanoClaw and AstrBot; see [compaction-in-other-bots.md](../research/2026-11-compaction-in-other-bots.md) (in Chinese).
