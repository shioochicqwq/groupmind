# 记忆相关开源项目调研报告

> 日期：2026-11-02。目的：为长期记忆系统选型提供证据，不包含实现。
> 需求基线：[memory-system-design.md](../memory-system-design.md)。
> 路径格式：`仓库@提交:文件`，函数名写在后面。
>
> **已有部分结论被更新**：伪学习已升级为核心方向，人物身份和群聊评测的结论也已修正，见 [续篇 2.2 节](2026-11-knowledge-acquisition-survey.md)。本文保留原始记录。

## 1. 结论

1. **没有项目能表达「上色」**。所查项目的结构化记忆都指向单个来源位置，或挂在树形父节点下；没有一个能把一个语义对象映射到一组不连续的原始消息。这层要自建，但表结构很简单。
2. **没有项目满足人物身份需求**。代码中未发现 QQ ID、昵称历史、头像历史或跨群身份映射；`kenz1117/dsh-engram` 和 ClearAI 还会按名称归并，这正是我们禁止的做法。
3. **可以借鉴的是小机制，不是框架**。最值得借鉴的是：中文全文切词、RRF 融合、事实有效期、模型只能引用已有证据 ID、来源闸门、`SILENT` 退出和配对评测流程。
4. **心跳和伪学习的收益都没有被证明适用于聊天场景**。有说服力的正向结果都来自编码任务，且主要证明「写下的信息能被送达」；`dsh-host-rsi` 自己的审计判定其某个版本净效用「边际偏负」。所以这两项不应进入 MVP。
5. **自建 benchmark 普遍不能跨项目比较**。零干扰检索池、反复调到满分的 16 题、作者自评榜单都不能当作选型依据。可借鉴的是 `skepsun/dsh-engram` 的 G6 实验方法，不是它的分数。

## 2. 调研范围与证据等级

### 2.1 仓库选择
「同名仓库」并不唯一。选择时优先看功能与本项目的相关性，其次看星数。

| 名称 | 审计的仓库 | 提交 | 版本 | 许可证 | 说明 |
|---|---|---|---|---|---|
| dsh-engram | `kenz1117/dsh-engram` | `d3529cd` | 0.11.3 | MIT | 同名仓库中星数最高 |
| dsh-engram | `skepsun/dsh-engram` | `fb91b4a` | 0.9.0 | MIT | 有详细自建评测 |
| dsh-memory | `FuRongJun-1999/dsh-memory` | `5cf8108` | 0.9.21 | MIT | 同名中星数最高（规模大，只抽读） |
| dsh-linghun | `syyr1987/dsh-linghun` | `377e130` | 1.0.0 | AGPL-3.0（`PROJECT.md` 自述） | 另读后继 `dsh-linghun-memory@488c8a2` |
| dsh-linghun-assembler | `syyr1987/dsh-linghun-assembler` | `5c69ce4` | 0.4.1 | 同系列许可证（GitHub 未识别） | |
| dsh-soul | `icyaaaww/dsh-soul` | `382d807` | 2.0.0 | MIT | 其他同名仓库主要是人设类 |
| dsh-maoying | `lifangjin/dsh-maoying` | `97f5ece` | 0.1.35 | MIT | **网文创作插件，不是记忆插件** |
| dsh-heartbeat | `Kanadego/dsh-heartbeat` | `d56379f` | 2.1.0 | MIT | 同名中星数最高，面向「活人感」 |
| dsh-proactive | `Dx3906-xn/dsh-proactive` | `d2f9083` | 0.1.0 | **未见 LICENSE** | 最贴近陪伴场景，只能借鉴思路 |
| dsh-proactive | `john-walks-slow/dsh-proactive` | `cae01f3` | - | **未见 LICENSE** | 只看 README，定时闹钟 |
| dsh-proactive | `beijingwahw/dsh-proactive` | `e043002` | 1.0.0 | MIT | 只看 README 和目录规模 |
| dsh-host-rsi | `pk14742952-AD/dsh-host-rsi` | `7de2722` | 0.3.1 | MIT | |
| clearai-dsh | `Clearailhc/clearai-dsh` | `47f8cda` | 0.5.7 | Apache-2.0 | 研究本体，不是聊天记忆 |

**你提到的 A 级项目没有给出名单，所以未单独审计。** 此次顺带看到的候选（`Phant0Meow/dsh-meow-memory`、`Yuuyuko-uu/dsh-fish-memory`、`Aik358/dsh-auto-memory`、`csyangwen/dsh-memory-evolve`）未读源码。

### 2.2 证据等级
| 标记 | 含义 |
|---|---|
| **宣称** | README 或文档这样写，未核实 |
| **源码** | 我读到了实现 |
| **有测试** | 仓库有对应测试文件，但我没运行 |
| **实跑** | 我在隔离环境运行并通过 |
| **未验证** | 没有找到证据，或范围内未查到 |

### 2.3 实跑方式
使用 `bwrap` 无网沙箱，HOME 为临时目录，不安装依赖，因此只运行不需要第三方包的测试；未调用任何模型。

| 仓库 | 测试 | 结果 |
|---|---|---|
| `dsh-soul` | validation、span-index、graph-memory、dynamics、lesson、gate | 59/59 通过 |
| `dsh-host-rsi` | retrieve、signal、policy、guard、source-gate | 53/53 通过 |
| `dsh-linghun-memory` | mmr_bucket、goal、map | 38/38 通过 |
| `Dx3906-xn/dsh-proactive` | policy、state、compose | 3/3 个套件通过 |
| `skepsun/dsh-engram` | rerank、preference、redact、entity-page、supersede | 12 通过，3 个因缺 `zod` 未能运行 |
| `dsh-linghun-assembler` | assembler、team | 因缺宿主包未能运行 |

`kenz1117/dsh-engram`、`dsh-memory`、`dsh-heartbeat`、ClearAI 的测试需要安装依赖，未运行。**测试通过只说明机制按代码预期工作，不说明它能改善对话质量。**

### 2.4 调研的局限
- `dsh-memory` 的 `md_cg` 约 27 万行（含测试），只抽读了核心模块和评测文档。
- `kenz1117/dsh-engram` 的 `sqlite.ts` 共 2179 行，只读了结构、搜索和实体解析部分。
- 「未发现」的结论来自关键词搜索和所读范围，不是逐行证明。

## 3. 项目逐项报告

### 3.1 `kenz1117/dsh-engram`
- **宣称**：本地跨会话记忆，23 个窄工具，FTS5 + 向量混合检索，证据门，全链路审计，SM-2 复习，记忆宫殿。
- **数据模型（源码）**：`src/store/sqlite.ts:438-488`。`nodes` 只有单个 `source_session_id/source_round/source_seq`，`edges` 记录节点关系，`facts` 带 `valid_at/invalid_at/replaced_by/source_node_id`，`observations` 带 `status/sources_json/proof_count`，`profile_block_versions` 保存画像版本，`op_log` 记录操作。
- **检索（源码）**：`sqlite.ts` 的 `search()`（约 1044 行起）分 FTS 和向量两路，RRF `K=60`，再乘 recency 与 proof 因子；向量维度不一致时降级为关键词并标记 `degraded`。向量是进程内暴力扫描，矩阵缓存上限 50,000 行，注释明说更大规模该用 `sqlite-vec`。
- **中文（源码）**：`tokenizeForFts()` 对中文做 2-gram。
- **写入（源码）**：`src/write-disposition.ts:decideWrite` 输出 ACCEPT/MERGE/DROP/DEFER，同类余弦 ≥0.92 合并，≥0.88 判为疑似矛盾。
- **证据门（源码，有测试）**：`src/retrieve/evidence.ts:assessEvidence`，模型只能引用同一检索批次里的 ref，`sufficient` 由代码判定，上限 8 条，连续不足时提示换检索方式。
- **信念巩固（源码，有测试）**：`src/consolidation/reflect.ts:reflectObservations`，form/refine/still/refute 四动作，原始记忆保留。
- **自建 benchmark**：未发现质量评测。`docs/research/2026-10-23-dsh-market-benchmark.md` 的主题是商店下载量，不是记忆效果。
- **与 DSH 耦合**：插件入口、工具、LLM 路由依赖宿主；`sqlite.ts`、`evidence.ts`、`rewrite.ts`、`write-disposition.ts` 没有直接的宿主 import（相对路径依赖未逐一展开）。
- **对我们的关键问题**：`resolveEntities()` 按 `normalizeEntityName` 和别名归并实体，同名即同实体，不能用于人物身份。

### 3.2 `skepsun/dsh-engram`
- **宣称**：省 token，零 LLM 捕获，符号索引逐层展开，ESR 证据闭环。
- **源码**：`lib/capture.js` 按模式捕获；`lib/rerank.js:evidenceBoost` 为 `1 + α·min(hits, cap)`；`lib/entity-page.js` 按实体投影事实、时间线、未决项和冲突，但 `resolveEntity` 也按名称匹配；`lib/ledger.js` 记账 `net = avoided − injected − rewrite×(1−折扣)`；`[ENGRAM]` 索引块按会话冻结以稳定缓存前缀。
- **自建 benchmark**：见第 5 节，方法是所有项目中最严谨的。
- **局限**：面向编码 agent，捕获模式和偏好正则都针对工程语境。
- **与 DSH 耦合**：`rerank.js`、`ledger.js`、`redact.js`、`util.js` 没有宿主 import，可移植；`store.js` 依赖 `zod` 和宿主存储域。

### 3.3 `FuRongJun-1999/dsh-memory`（灵枢）
- **宣称**：「不可遗忘」「无幻觉」的白箱记忆，五维评分第一。
- **数据模型（源码）**：`md_cg/nodefile.py`，每个节点是一个 Markdown 文件（frontmatter + 六要素），索引是可重建的派生物（`mdcg.py` 文件头）。`md_cg/subgraph.py` **明确要求每个节点至多一个父节点**，违反即报 `multi_parent`。
- **检索（源码）**：多路 RRF、条件路由、预算装包；有意不使用神经向量。`retrieve.py` 定型返回：非 success 时 `hit_count` 必须为 null，「不能让人把故障读成没有」。
- **经验实验（文档）**：`docs/eval/Memory-RSI_*`，结论是「保留实验代码，继续默认关闭」，metadata 交付存在负结果（42.9% 低于原版 47.6%）。这种如实记录值得学习。
- **评分**：`memory_score.md` 由作者校准，其中声称的领先缺少同等条件的第三方证据，**不应作为选型依据**。
- **与 DSH 耦合**：通过 MCP 子进程解耦，理论上最容易接入其他宿主，但体量和依赖面很大。
- **判断**：一条记忆一个文件、单父结构、规模都不适合 77 万条级别的底座，但可以参考几个局部纪律。

### 3.4 `syyr1987/dsh-linghun` 系列
- **dsh-linghun（源码）**：`memory.js` 把暖记忆存为 Markdown，用 high/medium/low/wrong 置信度；`wrong` 不再注入；序时账按天保存原始对话。
- **assembler（源码）**：`team/cycle.js`，每轮判官 → 捞取 → 组装 → 反馈 → 校准。**反馈仅靠下一轮消息和素材包的关键词重叠**（约 338 行），这只是相关性信号，不能证明记忆有用。
- **linghun-memory（源码，实跑）**：`memory.js:mmrSelect` 用 Jaccard 贪心排重，BM25 + MMR；事件、事实、规则三型写入；`map.js` 四轴导航。
- **自建 benchmark**：见第 5 节。
- **许可证**：AGPL-3.0，不能直接把代码并入计划开源的项目，除非接受其条款。

### 3.5 `icyaaaww/dsh-soul`
- **宣称**：记忆骨架 + 受控演化，默认关闭演化，配对验证。
- **数据模型（源码，实跑）**：`src/store.js:169-236`。`span` 以 `(scope, session, seq)` 为地址保存原文，`span_fts` 全文索引；`node` 带 `valid_from/valid_to/recorded_at`（双时间轴）、`anchor`、`support`、`hits`；`edge` 有类型和权重；`activation` 记录每次回忆。
- **`span-index.js`（实跑）**：增量摄入 + 水位线，中文逐字切分再用短语查询，`session-search.js:densestWindow` 截取最相关窗口。这是**唯一找到的可寻址原文索引**。
- **`graph-memory.js`（实跑）**：把激活度（ACT-R）、结构中心度、重要性分开使用，不压成一个分数；时钟按 5 分钟量化以稳定缓存前缀。
- **配对闸门（实跑）**：`validation.js:compareTrials` 要求至少 2 对，**每一对**都有提升（最小 0.2）才通过，任何工具错误回退即拒绝；`verifierFingerprint` 防止 agent 修改验收文件。
- **经验（实跑）**：`lesson.js` 只把重复信号暂存，不注入主代理，且不把「看起来结束了」当作成功。
- **局限**：`span_hash` 以内容哈希全局去重，**不能照搬**（见第 7 节）。演化依赖 Git 工作树和可执行检查，聊天场景没有这种客观验证方式。
- **与 DSH 耦合**：所查核心模块没有宿主 import，是本次可移植性最好的一组。

### 3.6 `lifangjin/dsh-maoying`
- **定位**：网文创作插件，不是记忆系统。文件式「数据库」（角色卡、关系图、时间线、伏笔账本）。
- **有借鉴意义的只有一点**：`foreshadows.yml` 的状态机 planted → progressing → resolved/abandoned，并记录埋设和回收章节、超期提醒（`lib/novel-parse.mjs`）。可借鉴到长期话题状态。它是作者手工维护的，不解决自动判定。

### 3.7 `Kanadego/dsh-heartbeat`
- **宣称**：按节律醒来，维护画像，感知忙闲，闲逛，把没说完的话带到下一拍。
- **源码（有测试，未运行）**：`src/gate/gate.ts` 是表达前最后一道闸（安静时段、忙碌窗口、日上限、冷却），且**只有投递成功后才消耗额度**；`src/profile/consolidate.ts` 中模型只能提交观察编号，证据由代码 `materializeEvidence` 生成，画像带时间层级。
- **效果评测**：在 README 和 docs 中未发现对照实验。**「活人感」的提升未验证。**
- **局限**：感知依赖桌面和屏幕（PowerShell），面向一对一陪伴，不是群聊。

### 3.8 `dsh-proactive`（三个同名仓库）
- **`Dx3906-xn`（实跑）**：`lib/policy.js:maySpeak` 六道闸（静默时段、最小间隔且未回复时翻倍、连续 3 条未回即停、对方刚说话不插嘴、日上限、素材质量门槛）；`lib/compose.js` 让模型可以只回 `SILENT` 拒绝，且拒绝不扣预算。设计小而清晰，但**没有效果评测，也没有 LICENSE**。
- **`john-walks-slow`（宣称）**：模型自设宿主级闹钟。这解决「何时唤醒」，不涉及质量。
- **`beijingwahw`（宣称）**：科学家/理论家双心智、贝叶斯实验设计、Raft 共识、自主进化等。317 个源文件，只发现 7 个测试类文件，未见效果证据。**不建议投入，也未深读。**

### 3.9 `pk14742952-AD/dsh-host-rsi`
- **宣称**：越用越强，自动沉淀可信教训。
- **源码（实跑）**：`lib/policy.js:isSystemLikeText` 来源闸门；`lib/retrieve.js` 停用词 + IDF；`lib/guard.js` 五态循环检测。
- **最有价值的是它的自我审计**：`UTILITY-VERDICT-0.2.1.md` 用真实 165 行记忆发现，可信记忆中 **10.5% 是插件自己注入的系统文本被回灌**，净效用「边际偏负」。
- **后续证据（宣称）**：README 称跨会话任务无插件 0/5、有插件 5/5（p=0.0079），但样本只有 5；自检尾行在约 350 轮/组的评估中**未见显著提升**。
- **局限**：针对本地模型编码循环，L1/L2/L3 信号都依赖任务成败或用户纠正。

### 3.10 `Clearailhc/clearai-dsh`
- **宣称**：以证据核验的研究生长成领域本体。
- **源码（有测试，未运行）**：`preset/plugins/knowledge-items.js` 区分已排除、未解、缺陷等负向知识，`exclusionStrength` 按推翻来源强弱区分；`tools/verify-truth-table.mjs` 机械核对「文档声明」和「代码实际」。
- **诚实边界**：`docs/known-gaps.zh-CN.md` 明确写着实体「同名即同节点，不做实体消解」。
- **判断**：面向研究工作流，不适合聊天。可借鉴负向知识和「文档与代码对账」的工程做法。

## 4. 需求对照

✅ 有可用实现；🟡 部分相关，需要改造；❌ 未发现。

| 需求 | engram(kenz) | engram(skep) | dsh-memory | linghun 系列 | dsh-soul | 其他 |
|---|---|---|---|---|---|---|
| 完整保留原始记录 | ❌ | ❌ | 🟡 | 🟡 按天账本 | ✅ span（但去重） | |
| 可重叠、不连续的多标签 | ❌ | ❌ | ❌ 单父 | ❌ | ❌ | |
| 标签指向一组原始消息 | ❌ 单个来源 | ❌ | 🟡 派生关系 | ❌ | ❌ 单 anchor | |
| 多人群聊语境分离 | ❌ | ❌ | ❌ | ❌ | ❌ | |
| QQ ID 与昵称历史 | ❌ | ❌ | ❌ | ❌ | ❌ | |
| 别名 | 🟡 按名归并 | 🟡 按名查找 | 🟡 | 🟡 | ❌ | ClearAI 同名归并 |
| 头像与身份变更 | ❌ | ❌ | ❌ | ❌ | ❌ | |
| 事实随时间变化 | ✅ facts | 🟡 supersede | 🟡 | 🟡 | ✅ 双时间轴 | |
| 区分来源可信度 | 🟡 | 🟡 | ✅ 验证基底 | 🟡 四级置信度 | 🟡 | heartbeat 代码生成证据 |
| 中文全文检索 | ✅ 2-gram | ✅ bigram | ✅ | 🟡 | ✅ 逐字 | |
| 混合检索 | ✅ RRF | 🟡 仅词法 | ✅ 无向量 | 🟡 BM25+MMR | 🟡 仅词法 | |
| 证据约束的筛选 | ✅ 证据门 | 🟡 | 🟡 | ❌ | 🟡 | |
| 上下文预算 | ✅ | ✅ | ✅ | 🟡 | ✅ | |
| 群聊接话判断 | ❌ | ❌ | ❌ | ❌ | ❌ | Dx 有一对一闸门 |
| 按「是否读过」限制知识 | ❌ | ❌ | ❌ | ❌ | ❌ | |

**上色的调查结论**：最接近的是 `kenz` 的 `node_entities`（节点与实体多对多）和 `dsh-soul` 的 `span`（原文可寻址），但前者连接的是派生节点，不是原始消息；后者没有语义层。把两者组合起来才接近我们的 `color_link`。不要把现有的互斥分块或摘要结构套到上色上。

## 5. 自建 benchmark 审查

| 项目 | 实验 | 样本 | 基线/消融 | 独立性 | 能得出什么 |
|---|---|---|---|---|---|
| skepsun | G6 配对编码任务 | 多轮，单轮 13–20 对 | 裸机对照；作废过被污染的 +30pp | 作者自跑，但记录了多轮泄漏修复 | 记忆能送达**不可推导的约定**（+95pp/+60pp）；此前可推导语料上仅「不伤害」。这是编码任务 |
| skepsun | PersonaMem 检索 | 589 题 | BM25 各变体、FTS、last-k | 使用公开数据；作者自跑 | R@5 约 30%；last-k 高达 71% 是因为答案都在会话尾部，作者已注明 |
| skepsun | 真实记忆自召回 | 97 条，61 题 | 多变体 | 自己的数据；查询是实体名 | MRR 0.197→0.221，提升很小 |
| dsh-memory | bench6 | 100 题，137 条 | 六家对比 | 作者自跑；README 已注明不是榜单 | **检索池全是答案，零干扰**，是上界，不能说明真实效果 |
| dsh-memory | locomo-zh-500 | 500 题，567 条 | | 中文词项由作者注写，查询是关键词串 | 同样零干扰，不是自然语言 |
| dsh-memory | 五维评分 | 无 | 无 | 作者自评 | 不是证据 |
| linghun | BEAM | 1M/10M 各约 20 题 | 隔离基线 60 分 | 作者自跑，方案随结果迭代 | 方向可参考，幅度不可靠 |
| linghun-memory | LoCoMo-Plus | 16 题 | v0.1.4 → v0.1.5 | 针对失败题改进后得到 16/16 | **有在测试集上调参的风险**；401 题约 83–90% 更值得参考 |
| dsh-soul | 骨架压缩 | 300 个确定性场景 | 窗口、摘要 | 合成数据，指标是字面量是否存在 | 压缩预算紧时有效；2400 字节时均匀采样反超。没有模型参与 |
| dsh-soul | 记忆调度 | 60 节点 40 轮，**已实跑** | 最新优先、重要性 | 合成模拟 | 只按最新排序 7/60 覆盖，动态排序 60/60，说明调度不退化，不代表回答变好 |
| host-rsi | 跨会话 | 5 题 | 无插件 | 未读原始数据 | 样本太小，且仍是编码任务 |

**共同问题**：几乎都是两人对话或编码任务，没有一项在**多人交错群聊**上评测，也没有一项衡量「回复是否更像群友」或「无关记忆是否干扰」。这些必须由我们自己测。

**值得复用的方法**（`skepsun/dsh-engram:docs/G6-quality-ab.zh.md`）：同题配对、确定性判据、至少 10 对才算数、不够就写「未测」、把作废结果和泄漏记录公开，以及先让对照组真正查不到答案。

## 6. 值得复用的机制

成本是相对估计：低（≤1 天）、中（数天）、高（需要专门研究）。

| 机制 | 来源 | 用途 | 适用条件 | 局限 | 成本 |
|---|---|---|---|---|---|
| 中文 FTS 预切词 | `soul:span-index.js:segment`、`kenz:sqlite.ts:tokenizeForFts` | 检索短句、黑话和昵称 | SQLite FTS5 | 逐字索引较大；2-gram 查不到单字；要实验比较 | 低 |
| 可寻址原文 + 水位线增量摄入 | `soul:span-index.js:ingest` | 原始层、阅读位置 | 有稳定序号 | 要去掉哈希去重 | 低 |
| RRF 融合与降级标记 | `kenz:sqlite.ts:search` | 多路候选融合 | 各路排名可比 | 暴力向量到 5 万行就要换索引 | 低 |
| 语境级 RRF | Refind 思路，转引自 `skepsun:research/aml_top_systems/SYNTHESIS.md` | 消息分与颜色分融合 | 有颜色 | 只读二手总结，需要实验 | 低 |
| 事实有效期、双时间轴 | `kenz:facts`、`soul:node` | 观点演变、旧昵称 | 能判定变化时间 | 判定本身可能错 | 中 |
| 模型只能引用已有证据 | `kenz:evidence.ts:assessEvidence`、`heartbeat:consolidate.ts` | 筛选模型、上色、人物印象 | 候选先带编号 | 防伪造引用，不防误读；增加一轮调用 | 低 |
| 信念四动作 + 证据集合 | `kenz:reflect.ts` | 人物印象 | 有后台模型 | `proof_count` 不等于证据独立，同一人刷屏会放大 | 中 |
| 写入四态 | `kenz:write-disposition.ts` | 只用于派生记忆 | 向量已校准 | 0.92/0.88 是代码记忆的阈值，不可照搬；不能用于原始消息 | 中 |
| 来源闸门 | `host-rsi:policy.js:isSystemLikeText` 及其审计 | 排除机器人自己和注入的文本 | 消息带来源 | 正则会漏，应优先用结构化字段判断 | 低 |
| 三信号不合并 | `soul:graph-memory.js` | 只降权遗忘 | 记录访问 | 只在合成场景验证 | 中 |
| 失败不等于没有 | `dsh-memory:retrieve.py` 的 I1 | 召回失败与空结果分开 | 所有召回 | 无 | 低 |
| 负向知识 | `clearai:knowledge-items.js`、`dsh-memory` 的 rejected | 记录「已否定」的说法 | 有否定信号 | 群聊中否定信号很吵 | 中 |
| 话题状态机 | `maoying` 伏笔 | 长期话题状态 | 显式第二层 | 自动判定状态未解决 | 中 |
| 发言闸门与 `SILENT` | `Dx3906-xn:policy.js`、`compose.js`，`heartbeat:gate.ts` | 第二阶段接话 | 需改为群聊语境 | Dx 无 LICENSE，只能重新实现；效果未证明 | 低 |
| 投递成功才扣额度 | `heartbeat:gate.ts` | 第二阶段接话 | 有发送回执 | 无 | 低 |
| 上下文记账 | `skepsun:ledger.js` | 衡量记忆的 token 花费 | 有用量统计 | 只算成本，不算质量 | 低 |
| 配对闸门 | `soul:validation.js:compareTrials` | 评测流程 | 有判据 | 2 对太少，我们要更多 | 低 |
| 文档与代码对账 | `clearai:verify-truth-table.mjs` | 防止文档漂移 | 开源阶段 | 只查结构 | 低 |

## 7. 不适合复用的设计

| 设计 | 来源 | 原因 |
|---|---|---|
| 按名称或别名归并实体 | `kenz:resolveEntities`、`skepsun:resolveEntity`、ClearAI | 同名不同人，且违反明确要求 |
| 按内容哈希全局去重原文 | `soul:span_hash` | 群聊里两个人都说「哈哈」是两条消息，去重会破坏顺序和完整性；导入去重必须按来源消息 ID |
| 单一来源字段 | `kenz:nodes.source_*`、`soul:node.anchor` | 无法表达不连续的颜色覆盖 |
| 单父树结构 | `dsh-memory:subgraph.py` | 明确禁止多父，与多色冲突 |
| 一条记忆一个文件 | `dsh-memory:nodefile.py` | 百万级文件不现实；适合少量知识，不适合聊天底座 |
| 用访问次数当证据 | `kenz` proof、`skepsun:evidenceBoost` | 被检索得多不等于正确，有自我强化风险 |
| 每轮多角色 Agent | `assembler:team/` | 成本和延迟高，所读范围内没有证据证明比简单方案好 |
| 关键词重叠当反馈 | `assembler:cycle.js` | 只能说明话题相近 |
| 预设修正正则 | `skepsun:preference.js` | 面向用户指令；群友的话是数据，「记住」这类词不能触发写入 |
| 记忆宫殿、SM-2 复习 | `kenz` | 为人类记忆术和编码 agent 设计，对聊天没有已知收益 |
| 用 Git + 可执行检查做自我进化 | `soul:evolve.js` | 聊天没有客观判据，无法照搬 |
| 作者自评榜单 | `dsh-memory:memory_score.md` | 不是证据 |

## 8. 心跳和伪学习：能否测出收益

| 问题 | 现有证据 | 判断 |
|---|---|---|
| 定期心跳能让机器人更像真人吗？ | 未发现对照实验 | **未知** |
| 后台整理能改善召回吗？ | 只有合成调度结果 | **未知**，但可以离线测 |
| 经验注入有用吗？ | 编码任务上有正向结果，但主要证明信息送达；`host-rsi` 还发现自污染 | 聊天场景**未知**，且有已知风险 |
| 自我反思有用吗？ | `host-rsi` 自检未见显著提升；`dsh-memory` 默认关闭 | 现有证据偏负面 |

**因此 MVP 不包含这些机制。** 只有下面的测量方式定义清楚后才考虑加入：

- **后台整理**：同一批评测题，比较整理前后的召回率和错误合并率。可以离线做，优先级最高。
- **接话与主动发话**：回放历史群聊，判断模型想接话的时机，并和真实群友的接话、被回应情况比较；再由你盲评。在线实验必须有对照时段，否则无法区分因果。
- **伪学习**：分成训练期和保留期。先注入经验，再在**没见过的**相似场景上配对比较，要有预先规定的判据和至少 10 对；管理员纠正是最可靠的信号来源，也要测试经验是否干扰无关对话。
- **Notebook**：只有当评测里反复出现「多轮才能完成、当前上下文装不下」的失败时才加入，并比较有无 Notebook 的结果。

## 9. 最小可行架构

相比设计草案，这里进一步砍掉所有未证明的组件。

```
导入器 ──> 原始层（只追加）
            │
            ├─> 索引：FTS（中文切词）+ 向量（待实验）
            ├─> 上色：color / color_link（多对多，带版本）
            └─> 身份：person / identity_claim（只凭稳定 ID 自动合并）

查询 ──> 多路候选（原文、颜色、人物、时间）
     ──> RRF
     ──> 带编号的候选 → 可选筛选模型（只能引用编号，可返回空）
     ──> 展开原文 → 上下文（有预算）
```

### 9.1 核心表
```sql
message(id, source, source_msg_id, chat_id, sender_id, ts, order_key,
        text, quote_of, raw_ref, UNIQUE(source, source_msg_id))
color(id, chat_id, layer, kind, name, summary, status, version, model, created_at)
color_link(color_id, message_id, role, confidence, run_id, PRIMARY KEY(color_id, message_id, run_id))
color_relation(from_id, to_id, rel, confidence, run_id)  -- 只在实验证明需要时使用
person(id, platform, platform_uid, UNIQUE(platform, platform_uid))
person_name(person_id, chat_id, name, kind, first_seen, last_seen, source_message_id)
person_avatar(person_id, image_hash, first_seen, last_seen)
identity_candidate(a, b, evidence, status, decided_by)  -- pending 永远不自动转正
claim(id, subject, speaker, kind, content, valid_from, valid_to, source_message_id)
read_mark(chat_id, up_to_order_key)
revision(target, old, new, reason, at)
```

设计要点：
- **去重**按 `(source, source_msg_id)`，不按内容。
- **一个 `run_id` 就是一次上色**，多个方案可以并存对比，而不覆盖。
- **自动合并只认平台稳定 ID**；昵称相同只能产生 `identity_candidate`。
- **头像**只作为证据，不作为身份依据。
- `read_mark` 现在就可以预留，历史导入时设为全部已读。

### 9.2 必须有 / 暂不做
| 必须有 | 暂不做（等实验证明） |
|---|---|
| 原始层、导入器、来源映射 | 多 Agent 编排 |
| FTS + RRF + 原文展开 | 心跳和后台自主运行 |
| 上色（可多方案并存）| 自我进化 |
| 稳定 ID 身份 + 候选队列 | Notebook |
| 评测框架 | 经验积累 |
| 来源闸门（排除机器人自己） | 图数据库、知识图谱 |
| 可选的筛选步骤，可关闭对比 | 复习调度 |

### 9.3 存储和技术栈
- **语言**：AstrBot 插件是 Python；可复用模块多为 JS，但都是小算法，**用 Python 重写比桥接划算**。
- **数据库**：SQLite（WAL + FTS5）起步。**向量库待测**：消息和颜色的向量规模一旦超过几十万，暴力扫描就不够。
- **接入**：独立记忆服务 + 薄适配器。代码上先保持这个边界，部署上可以先进程内运行。

## 10. 需要原型实验决定的争议

| # | 争议 | 选项 | 判据 | 数据 |
|---|---|---|---|---|
| E1 | 中文 FTS 切词 | 逐字 / 2-gram / 分词 | 回放 Recall@k、索引大小 | 样本 |
| E2 | 检索单元 | 固定窗口 / 语境颜色 / 单条 | 回放 + 人工题 | 几周记录 |
| E3 | 语境分离 | 模型按对话簇分配 / 回复链 + 聚类 | 用清洗后的引用作参照 | 1000 条 |
| E4 | 第二层 | 隐式向量 / 显式话题 | 跨日、跨周题得分；错误关联率 | 几周记录 |
| E5 | 是否需要向量 | 仅 FTS / FTS + 向量 / 不同模型 | 增量收益和费用；黑话场景单列 | 几周记录 |
| E6 | 筛选步骤 | 无 / 规则 / 模型 / 模型 + 证据门 | 无关记忆注入率、延迟、费用 | 回放 |
| E7 | 记忆干扰 | 相关 / 弱相关 / 无关注入 | 强行提及率 + 你的盲评 | 选定模型 |
| E8 | 召回方式 | 自动注入 / 工具调用 / 组合 | 漏召回率、干扰率、token | 第二阶段前 |
| E9 | 人物印象 | 从历史生成 | 你抽查准确率；错误归因率 | 少量熟悉人物 |
| E10 | 跨群泄漏 | 凭语境判断 | 不该提时提及的比例 | 专门题 |
| E11 | 投毒处理 | 记录说法 / 按信任加权 | 对抗样例采信率 | 构造样例 |

## 11. 开发顺序

| 阶段 | 内容 | 产物 | 决策点 |
|---|---|---|---|
| 0 | 核对导出字段；统计引用跨度和质量 | 字段映射、引用清洗规则 | 能否用作标准答案 |
| 1 | 原始层和导入器（1000 条，再扩展到几周）| 可追溯、可重复导入 | 完整性校验通过 |
| 2 | 评测框架和基线（窗口 + FTS）| 一键复跑的分数 | 你确定达标线 |
| 3 | E1、E5 | 检索基线定型 | 是否要向量 |
| 4 | 上色试验（E3）+ 单价 | 多个 `run_id` | 上色方法 |
| 5 | E2、E4 | 上色相对基线的提升 | 第二层方案、全量策略 |
| 6 | E6、E7 | 筛选和注入规则 | 是否需要抑制机制 |
| 7 | 身份和人物（E9）| 身份表、候选队列 | 进入第二阶段 |

第二阶段再做 AstrBot 适配、阅读和接话、心跳与伪学习实验。

## 12. 评测设计

- **四类数据**：人工题（你出）、时间切分回放、清洗后的引用、构造的对抗样例。
- **防泄漏**：只索引时间点之前的数据；去掉引用字段；不同方案共用同一批题；调参集和保留集分开，保留集只在定型时用一次。
- **检索指标**：Recall@k、MRR，跨日和跨周单列，黑话和昵称题单列。
- **筛选指标**：无关注入率、无答案时正确返回空结果的比例。这正是公开研究里原文检索的弱项。
- **回复指标**：强行提及率 + 你的盲评（随机打乱，隐藏方案）。
- **成本指标**：每千条的费用和用时、单次回复延迟、注入 token。
- **规则**：每个结果记录提交、配置、数据版本和随机种子；不足规定样本量时标记「未测」；失败和作废的实验也记录。

## 12a. 「调研后决定」项的逐项结论（2026-11-02 补充）

本节补读了 `MaiBot/src/A_memorix`、`dsh-heartbeat`、`dsh-j-space`，以及 `skepsun/dsh-engram` 对公开榜单的分析。**以下都是待实验验证的提议，分数多为作者自跑或二手转述，未复现。**

### 召回判断
| 机制 | 来源 | 做法 | 证据与局限 |
|---|---|---|---|
| 聊天印象查询 | `MaiBot:src/maisaka/memory/heuristic_injector.py` | 不用最后一句检索，先由便宜模型把最近窗口概括成一段「印象」，再检索；寒暄也如实说明 | 能解决「上次那个问题又来了」这种短句。未见效果评测；每次多一次模型调用 |
| 触发节流 | 同上 | 最小间隔（默认 180 秒）、最少新消息数、结果缓存 TTL、注入上限 900 字 | 工程上简单；可能错过突然提到的旧事 |
| 零模型分流 | `dsh-linghun-assembler:team/roles.js` | 正则判 light/medium/deep，并选时间线、矛盾、综述等检索策略 | 群聊口语未必命中；有测试，效果未知 |
| 模型按图自走 | `dsh-linghun-memory:docs/TECH_REPORT_v0.1.7.md` §3.2 | 注入记忆地图，模型自己回溯，不替它选候选 | 401 题 83.04% 对候选注入 80.05%，但 value 型下降 9pp；作者自跑 |
| 符号索引 + 下钻 | `skepsun/dsh-engram` | 只注入极短索引，需要时再展开 | 省 token；依赖模型愿意调用 |
| 动态阈值 | `A_memorix:core/retrieval/threshold.py` | 按结果分布定阈值（百分位、标准差、跳变检测） | 解决固定阈值难定；未读效果数据 |

**提议**：不让主模型每条判断。默认用节流 + 印象查询 + 动态阈值决定是否注入，同时提供检索工具供主模型深入。与「每条检索」「纯工具」「主模型判断」做对照（E6、E8）。

### 索引方式
| 机制 | 来源 | 做法 | 证据与局限 |
|---|---|---|---|
| 不必迷信复杂检索 | `skepsun:research/AML-leaderboard-2026-08.md` | 榜首是朴素 RAG（45.06），Refind 44.97，Mem0 42.07，SQLite-FTS 41.79，纯 BM25 38.47 | 二手快照，未核实榜单；差距小，但榜单非群聊 |
| 多粒度同一索引 | FlowGrid，转引自 `SYNTHESIS.md` | 消息、窗口、会话段进同一 FTS | **可映射为消息、窗口、颜色摘要同索引** |
| 相邻证据加分 | 同上 | 候选 seq±1 也命中时加分 | 群聊交错时可能失效，需按颜色内相邻测试 |
| 二级 RRF | Refind，同上 | `1/(60+rank_块) + 1/(60+rank_会话)` | **可改成颜色级**；低成本 |
| 时间和说话人写入文本 | Hybrid Episodic，同上 | 单元文本含时间戳和角色 | 利于解析相对时间；增加索引噪声 |
| 新近度要谨慎 | 同上 | 候选集内相对新近，时间意图时才放大 | `skepsun` 自测又显示无条件略好，**证据矛盾，需实验** |
| 不能裸做「新的覆盖旧的」 | FlowGrid 消融 | 纯结构判定 MRR 下降；要更新词门控 | 对「旧信息与变化信息」直接适用 |
| 分词可切换 | `A_memorix:core/retrieval/sparse_bm25.py` | jieba / mixed / char_2gram，n-gram 兜底，**可加用户词典** | **习得的梗可写入词典**，连接知识层和索引 |
| 融合方法可比较 | `A_memorix:core/retrieval/score_calibration.py` | 候选不变，只换校准方法 | 是好的消融设计 |
| 话题索引优先 + BM25 兜底 | `dsh-linghun-memory` §3.3 | BEAM 基线 60 → 85/90 | 作者自跑；支持显式第二层，但证据弱 |
| 图检索 | `A_memorix:core/retrieval/dual_path.py` | 关系 + 段落双路、PageRank、图可靠性门控 | 复杂（3272 行），第一阶段不做；E4 后再评估 |

**对上色的修正**：`A_memorix:core/utils/episode_segmentation_service.py` 的提示词明确允许「省略无关段落，并在相关 episode 中复用段落」，输出是段落序号列表，并记录分段模型、版本和输入指纹。这是目前**最接近上色的实现**，只是单位是段落而不是消息。可以直接参考其输出格式和版本记录。

**提议**：第一版用 FTS（分词比较）+ 向量（可关闭）对消息窗口和颜色摘要共同建索引，颜色级 RRF，再展开原文。向量是否必要仍由 E5 决定。

### Notebook
| 机制 | 来源 | 做法 | 局限 |
|---|---|---|---|
| 单槽笔记 | `dsh-heartbeat:src/notepad/store.ts` | 只有一个槽位，写入即替换；看过且未再触碰就放下；重启不丢 | 面向陪伴；未见效果评测 |
| 工作账本 | `dsh-j-space:preset/skills/j-space/scripts/jspace.py` | 记录下一步、目标、核心项、已验证检查点、未决问题及解决条件；**只记录，不决策也不阻塞** | 面向任务；只读了脚本说明 |

**提议**：Notebook 只记「正在进行的事」，不存事实；内容只算线索，不算证据。第一阶段不做。如果实验显示需要，优先试「单槽 + 未决问题列表」。

### 经验来源
| 信号 | 来源 | 现有做法 | 提议权重 |
|---|---|---|---|
| 管理员明确纠正 | `dsh-dream`、`dsh-host-rsi` L3 | 直接采纳 | 最高 |
| 读到原文的证据 | `dsh-dream:src/evidence.ts` | 可用但标记未审阅 | 中 |
| 群友明确纠正 | `A_memorix:core/utils/feedback_policy.py` | 关键词触发 + 自动应用阈值 0.85 | 只产生候选，防投毒 |
| 群友反应 | 未见成熟实现 | 无 | 弱信号，先测 |
| 自我反思 | `dsh-host-rsi`（未见显著提升）、`dsh-memory`（默认关闭） | 现有证据偏负面 | 只产生候选，不能自动转正 |

## 13. 待你确认
1. A 级项目名单：是否需要补充审计？
2. 同名仓库的选择是否符合你的预期，特别是 `dsh-proactive`、`dsh-memory`、`dsh-soul`？
3. 可复用模块按 Python 重写是否可以接受？
