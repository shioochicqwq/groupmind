# 持续知识习得与伪学习：调研报告

> 日期：2026-11-02。这是 [第一份调研报告](2026-11-memory-project-survey.md) 的续篇，按用户提供的 S/A 级名单审计。
> 路径格式：`仓库@提交:文件`。证据等级同第一份报告：宣称 / 源码 / 有测试 / 实跑 / 未验证。

## 1. 结论

1. **最接近需求的两个项目不在名单内**：`MaiBot`（黑话学习 + `A_memorix`）和 `qq-bridge`（`slang-learner`）。名单内没有发现完整的群聊梗学习实现。
2. **所有项目都只做到「存下解释」，没有一个测量「学会了」**。没有发现任何项目评测过：机器人学习后能否在新对话里正确理解和运用。这部分研究必须自建，也是本项目真正新增的部分。
3. **四级状态需要自建**。现有方案只有「候选 / 已确认」或一个 `is_jargon`；最好的状态机来自 `dsh-dream`，但它管的是任务经验。
4. **梗可以复用上色结构**：一个梗就是一种长期颜色，它的多次出现是可重叠、不连续的覆盖。这样两条研究线共用同一底座。
5. **知识习得可以先于全量上色开展**，因为找到一个词的所有出现只需要全文检索。
6. **不需要预设多 Agent、心跳或 Notebook**。第 8 节的对照实验能直接判断它们是否有用。

## 2. 范围

### 2.1 审计深度
| 级别 | 项目 | 深度 |
|---|---|---|
| S | `dsh-engram`、`dsh-memory`、`linghun`、`linghun-assembler`、`dsh-soul`、`dsh-maoying`、`dsh-heartbeat`、`dsh-host-rsi`、`clearai-dsh` | 上一轮已审计，本轮针对知识习得复查 |
| S | `john-walks-slow/dsh-proactive@cae01f3` | 本轮补读调度与唤醒的结构，未逐行读完 |
| A，读到关键实现 | `dsh-dream@2a8d609`、`DSH-AGINT@be6b257`（只读评测规范）、`dsh-outer-brain@ad687d0`（部分） | |
| A，读了评测结果 | `dsh-second-angle@9ac01ed`、`dsh-gungnir@4038c3e`、`dsh-harness2@bd9dfd0` | |
| A，只看 README 和结构 | `dsh-simulated-life`、`dsh-j-space`、`dsh-switchman`、`dsh-advisor-flow`、`dsh-advisor-plugin`、`dsh-cot-anchor`、`dsh-story`、`deepseek-servant` | 与本问题关系弱，未深入 |
| 名单外（我追加） | `Mai-with-u/MaiBot@c642954`、`Derpyu520/qq-bridge@b80fa51` | 关键词搜索后发现直接相关，深读 |

本轮没有运行任何测试和模型。`MaiBot` 体量很大，只读了黑话、表达方式、身份和反馈相关模块。

### 2.2 对上一份报告的修正
| 原结论 | 修正 |
|---|---|
| 伪学习不进入最小架构 | **改为**：是正式核心方向，第一阶段要包含离线评测；具体机制仍由实验决定 |
| 没有项目满足人物身份需求 | 只对当时审计的范围成立。`A_memorix` 已实现只按 ID 合并和历史称呼，见 3.3 |
| 没有项目在多人群聊上评测 | `A_memorix` 有群聊 benchmark，但规模很小且是合成数据，见 3.3 |
| `dsh-proactive` 选 `Dx3906-xn` | 用户指定的是 `john-walks-slow`。`Dx3906-xn` 的 `SILENT` 思路仍然值得借鉴 |
| 上色结构最接近的是节点-实体表 | `A_memorix` 的 `episode_paragraphs` 映射更接近，但仍指向段落而不是原始消息 |

## 3. 关键发现

### 3.1 `MaiBot` 黑话学习（GPL-3.0）
**流程（源码）**：
1. **提取**：`src/learners/jargon_learner.py` + `prompts/zh-CN/learn_jargon.prompt`，模型从 USER 消息中提取候选，要求给出来源消息 id。
2. **累计**：`jargon_miner.py:process_extracted_entries` 累计次数和证据引用。数据模型 `database_model.py:Jargon` 有 `content、evidence_messages、meaning、session_id_dict、count、is_jargon、is_complete、is_global、last_inference_count`。
3. **按次数推断**：`JARGON_INFERENCE_THRESHOLDS = [4, 8, 25, 100]`，到阈值才调用模型，节省成本。
4. **核心判定** `infer_meaning`：先基于上下文推断含义，再**只看词本身**推断一次，由模型比较两者。如果相似就不算黑话，有差异才算（`is_jargon = not is_similar`）。上下文不足可返回 `no_info`。
5. **使用** `src/maisaka/jargon_context_matcher.py`：当前消息机械匹配词条，最多 10 条，并标明这是「猜测含义，仅作理解」。

**优点**：两次推断对比是个巧妙的「模型是否本来就懂」的探针；按阈值推断省钱；证据引用原始消息；机器人自己的发言不参与学习。

**局限（对照我们的需求）**：
| 需求 | 问题 |
|---|---|
| 一词多义 | `meaning` 是单个字符串 |
| 持续修正 | 次数 ≥100 后 `is_complete`，**不再推断**，无法追踪后续演变；虽会把旧含义传给模型参考，但没有版本和冲突记录 |
| 人物典故 | 提取规则**排除人名和图片内容**，而这正是内部梗的重要来源 |
| 状态 | 只有 `is_jargon` 布尔值，没有掌握程度 |
| 使用 | 只帮助理解，没有评估使用是否恰当 |
| 判定稳定性 | 「是否相似」由模型判断，容易抖动；模型自以为懂但理解错时，会被判为普通词 |
| 排序 | `_calculate_match_score` 主要靠高频词和次数，不看语义是否相符 |

**评测**：`pytests` 中未发现黑话学习的测试，只发现表达方式选择的测试；README 和 changelog 中未发现对照实验。

**表达方式学习**（`expression_learner.py`、`Expression` 表）：学习「情景 → 表达方式」，有 `checked` 人工审核字段和可选的自我评估。这是目前唯一发现的「学用法」结构，适用于需求 5，但其效果同样未见评测。

### 3.2 `qq-bridge` 黑话学习（PolyForm Noncommercial）
**源码** `src/slang-learner.js`：
- **状态**：`candidate → confirmed / rejected`，人工可在控制台操作。
- **字段**：`content、meaning、usage、example、risk、sources、scope、count、evidence`，有容量上限。
- **范围隔离**：`normalizeSlangScope`、`slangScopeVisible` **fail-closed**，范围无效时隔离，不退回全局。
- **防注入**：`escapeLearnerText` 转义聊天文本，提示词写明聊天内容只是语料。
- **研究**：`buildResearchPrompt` 用联网搜索确认，要求给来源 URL，搜不到就 `confirmed: false`。

**局限**：
- `buildSlangContext` **按出现次数取前 8 条注入，不看当前对话是否用到**，这正是我们要避免的无关注入。
- 联网确认适合公共网络梗，**对群内部梗基本无效**，这些梗搜不到就一直无法确认。
- 把词条发到搜索服务有隐私问题（其 `NOTICE.md` 已说明）。
- 测试只有一个结构自检脚本（`scripts/test-slang-learn.mjs`），没有效果评测。
- 未发现长期记忆检索模块。

### 3.3 `A_memorix`（`MaiBot/src/A_memorix`，AGPL-3.0）
- **人物身份（源码，有相关测试）**：`core/storage/metadata_identity.py:observe_person_identity` 注释明确写「只按 ID 合并身份，保留每次观察到的昵称，不用昵称认领其他用户」；`person_identity_aliases` 表记录 `(person_id, alias, group_id, first_seen, last_seen)`；`find_person_identities` 返回同名的所有人，并要求调用方不得猜测。**这与我们的要求一致**，但没有头像。
- **Episode（源码）**：`episodes` 有 `evidence_ids_json、segmentation_model、segmentation_version、input_fingerprint`，通过 `episode_paragraphs` 映射到段落，这是目前最接近两层颜色的结构，但段落不是原始消息。是否允许一个段落属于多个 episode 未核实。
- **反馈修正（源码，有测试，未运行）**：`core/utils/feedback_policy.py` 用关键词（「不对」「记错了」「应该是」等）触发，`feedback_correction_service.py` 排队处理，自动应用阈值 0.85，有回滚计划、陈旧标记、重建 episode 和刷新画像。这是所查项目中**最完整的修正链路**。缺点是「不是」「改成」在群聊里噪声很大。
- **生命周期**：`core/utils/memory_lifecycle_policy.py` 用纯函数计算关系记忆状态，事件包括访问、证据、强化、减弱和冻结。
- **群聊 benchmark**：`pytests/A_memorix_test/data/benchmarks/`。合成数据，hard 版只有 70 条消息和 4 个 search 用例，目标 `accuracy_at_1` 仅 0.4。作者还要求「只把 Bot 参与过的话题写入长期记忆」，**这与我们的潜水设定相反**。未找到运行它的测试入口。
- **许可证**：AGPL-3.0，可以学习设计，不宜直接复制代码。

### 3.4 名单内对知识习得有用的部分
| 项目 | 机制 | 位置 | 适用性 |
|---|---|---|---|
| `dsh-dream`（MIT） | 经验状态 candidate/usable/disputed/stale/rejected，迁移规则显式，rejected 只能回到 candidate | `src/knowledge.ts:15,136` | **状态机模板** |
| `dsh-dream` | 工具参数只算声明，读到匹配记录后才算证据 | `src/evidence.ts` | 防止伪造来源 |
| `dsh-dream` | 使用反馈 useful/not-applicable | `src/knowledge.ts:65` | 反馈字段 |
| `dsh-dream` | 零注入断言测试（5 个场景必须不注入） | `test/l1-eval.test.mjs` | **负向评测范式** |
| `dsh-dream` | 必要字段不截断，放不下就停止，不倒序 | `src/retrieval.ts` | 注入预算 |
| `dsh-engram` | 信念 form/refine/still/refute，原始记忆保留 | `src/consolidation/reflect.ts` | 复核旧解释 |
| `dsh-soul` | 重复信号先暂存，不注入；成功必须有验证 | `src/lesson.js` | 后台习得 |
| `dsh-soul` | 配对闸门，每一对都要提升 | `src/validation.js:compareTrials` | 评测 |
| `clearai-dsh` | 负向知识，按推翻来源强弱分级 | `preset/plugins/knowledge-items.js` | 记录已否定的解释 |
| `dsh-heartbeat` | 模型提议，代码护栏；代码生成证据；确定性老化 | `src/profile/store.ts`、`consolidate.ts` | 后台维护 |
| `dsh-host-rsi` | 来源闸门；实际审计发现自污染 | `lib/policy.js`、`UTILITY-VERDICT-0.2.1.md` | 机器人发言不算证据 |
| `dsh-outer-brain` | 贝叶斯置信度（似然比封顶、Brier 分） | `dsh/belief.mjs` | 可作为证据累积的候选，有 LR 上限；未见效果评测和测试目录 |
| `dsh-second-angle` | 核对声明和证据，给矛盾标引用 | `eval/EVAL_RESULTS.md` | 复核解释的思路；24 个自写用例，作者自己说明证据有限 |
| `DSH-AGINT` | 评测集可见性（EVOLUTION/VALIDATION/FROZEN）和标签权威性正交 | `docs/specs/evaluation-protocol-v1.md` | **防止习得过程看到测试集**。文档写明隔离尚未落地 |
| `john-walks-slow/dsh-proactive`（MIT） | 单循环调度，静默时段、小时上限、预算、抖动、重试；静默结束后压缩为墓碑 | `src/scheduler.ts`、`framing.ts` | 后台任务调度；`scheduler.ts`、`cron.ts` 未见宿主 import，`wake.ts` 强依赖 DSH。**只解决何时运行，不证明有用** |

### 3.5 其他 A 级项目
- `dsh-gungnir`：20 个自建任务，假验收 0，一致率 100%。是任务验收，不是知识；可借鉴「假验收数」作为最高权重指标。
- `dsh-harness2`：README 写明未对照论文基准验证，比较靠模型而不是真值。
- `dsh-simulated-life`：掷骰生成生活事件并注入。可作为第二阶段人设素材，与习得无关。
- `dsh-story`：角色目录和世界书每轮全量读取，不适合大规模知识。
- 其余（`switchman`、`advisor-*`、`cot-anchor`、`j-space`、`deepseek-servant`）解决编码 agent 的上下文或审查问题，未发现可用于梗学习的机制。

## 4. 七项能力对照

✅ 有实现；🟡 部分；❌ 未发现。**「实现」不等于「有效」，表中没有一项有效果证据。**

| 能力 | MaiBot | qq-bridge | A_memorix | dsh-dream | engram | 其他 |
|---|---|---|---|---|---|---|
| 1 发现新知识 | ✅ 模型提取 + 高频词 | ✅ 模型提取 | ❌ | 🟡 任务经验 | 🟡 | |
| 2 归纳含义 | ✅ 上下文 vs 词本身 | ✅ 含联网 | ❌ | 🟡 | 🟡 reflect | 都排除或未用图片 |
| 3 知识关联（来源、人物、范围、证据） | 🟡 证据 + 会话 | 🟡 范围 + 证据 + URL | 🟡 图谱（通用） | 🟡 | 🟡 | 未发现典故和演变结构 |
| 4 修正、多义、演变 | ❌ 单含义，100 次后停 | ❌ | 🟡 通用修正链路 | ✅ 状态 | ✅ refute | 未发现一词多义 |
| 5 实际运用 | 🟡 帮助理解；表达方式另算 | 🟡 按次数注入 | ❌ | ❌ | ❌ | **未发现使用恰当性评估** |
| 6 反馈学习 | ❌ | 🟡 人工确认 | ✅ | 🟡 投票 | 🟡 | |
| 7 主动维护 | 🟡 阈值触发 | 🟡 定时研究 | ✅ | 🟡 | 🟡 | heartbeat、proactive 有调度 |

## 5. 不适合复用的设计

| 设计 | 原因 |
|---|---|
| 把「模型自己判断懂了」当作掌握 | 模型自评不可靠 |
| 次数到阈值就视为确认 | 一个人刷屏也会累积；要看独立发言者和场景 |
| 达到次数后停止推断（MaiBot） | 含义会变 |
| 按次数全量注入（qq-bridge） | 无关注入，且旧梗永远排在前面 |
| 联网结果直接确认 | 同名词的网络含义可能和群内含义不同 |
| 用关键词判定纠正 | 「不是」太常见，且任何群友都能触发，可能被投毒；只能作为低权重信号 |
| 排除人名和图片 | 人物典故和表情图是内部梗的主要来源 |
| 把定义塞进系统提示 | 模型容易复述定义，正是用户明确不想要的结果（待实验验证） |

**许可证**：`MaiBot` GPL-3.0、`A_memorix` 和 `deepseek-servant` AGPL-3.0、`qq-bridge` PolyForm 非商业。若本项目要以宽松许可证开源，这些只能参考思路，代码需独立实现。这不是法律意见。

## 6. 最小知识层设计

### 6.1 复用上色
```sql
-- 词条就是一种颜色；它的所有出现都写入 color_link（kind = 'term'）
term(color_id, surface, normalized, scope_chat_id)

-- 一个词可以有多个含义，含义才有状态
sense(id, term_id, gloss, usage, register, origin, status, valid_from, valid_to,
      version, model, created_at)

-- 证据指向原始消息；同一条可以支持一个含义、反驳另一个
sense_evidence(sense_id, message_id, stance, kind, sender_id, run_id)
-- stance: supports | contradicts | explains；kind: usage | explicit_definition | reaction | image | forward

term_link(term_id, target_type, target_id, rel, evidence_message_id)  -- 关联人物、事件、其他梗
probe(term_id, model, known, answer, at)                              -- 模型原本是否懂
usage_event(sense_id, message_id, by_bot, outcome, evidence)          -- 使用及结果
revision(target, old, new, reason, at)
```

### 6.2 四级状态（对应用户要求）
状态都属于**含义**，只有第一级属于词条。

| 状态 | 含义 | 晋级依据（门槛待校准） |
|---|---|---|
| `observed` | 这个表达在群里出现过 | 统计或模型发现 |
| `hypothesized` | 机器人推测了含义 | 有带编号的证据，模型只能引用已有消息 |
| `supported` | 有充分证据支持解释 | **多个独立发言者**、多个不同场景，或有明确解释、管理员确认；**没有未解决的矛盾证据** |
| `operational` | 掌握了适用语境 | **通过保留数据的运用测试**（第 8 节），不能由模型自我声明 |
| 旁路：`disputed`、`stale`、`rejected` | 有矛盾、可能过时、已否定 | 迁移规则显式；被否定后只能回到 `hypothesized` |

**只有 `operational` 才允许机器人主动使用这个梗**；`supported` 可以用来理解；`hypothesized` 只能带不确定标记。这条规则本身也要实验验证。

### 6.3 发现方式（待比较）
| 方式 | 做法 | 优点 | 风险 |
|---|---|---|---|
| 统计 | 群内词频相对参考语料的偏离、时间突发、跨发言者传播 | 无模型费用，能全量跑 | 需要分词和参考语料；项目中未见实现（`MaiBot` 只有高频词） |
| 模型提取 | 按批提取（`MaiBot`、`qq-bridge`） | 能发现短语和含义 | 费用高，漏掉不常见的 |
| 模型未知探针 | 只给词本身，看模型能否解释（`MaiBot` 思路） | 把学习资源用在真正不懂的词上 | 模型可能自信地解释错 |
| 显式信号 | 「X 是什么意思」「X 就是 Y」 | 高质量证据，甚至可作为测试答案 | 数量少 |

## 7. 技术争议（新增）

| # | 争议 | 选项 | 判据 |
|---|---|---|---|
| K1 | 发现方式 | 统计 / 模型 / 组合 | 用户标注样本上的 P@k 和召回 |
| K2 | 表示形式 | 定义 / 定义 + 例句 / **只检索原文不抽取** | 第 8 节 T3–T5 |
| K3 | 注入方式 | 匹配后注入 / 工具查询 / 仅在不确定时 | 理解得分、复述率、无关注入率 |
| K4 | 证据门槛 | 次数 / 独立发言者 / 贝叶斯累积 | 含义准确率；刷屏和投毒样例 |
| K5 | 图片与表情 | 不用 / 视觉模型描述 / 按表情 ID 聚合 | 依赖图片的梗的理解得分 |
| K6 | 多义和演变 | 单含义更新 / 多含义 + 有效期 | 时间回放中的新旧含义判断 |
| K7 | 后台维护 | 不维护 / 按阈值 / 定时 Agent | 同一批题上得分变化、错误修正率、费用 |
| K8 | 反馈信号 | 仅管理员 / 加群友反应 | 修正后在**新场景**的提升；误修正率 |
| K9 | 多 Agent | 单步 / 提取 + 复核分离 | 准确率提升是否值得费用和延迟 |
| K10 | Notebook | 无 / 有 | 是否减少多轮推断失败 |

## 8. 评测设计

评测目标：**面对原本不了解的知识，学习历史后，能否在新对话中正确理解和运用。**

### 8.1 选题
1. **前测**：只给词本身和不含线索的上下文，记录模型能否解释。**只有模型原本不懂的词才计入学习提升**，懂的单独报告，否则会高估效果。
2. **时间切分**：每个词选定截止时间，之前用于学习，之后用于测试。要求之后有足够的出现。
3. **分层**：公共网络梗、群内部梗、人物典故、依赖图片的梗、一词多义、含义变化的词分别统计。
4. **防泄漏**：测试消息不进入学习；**测试集不能被习得和维护流程看到**（借鉴 AGINT 的可见性分层）；调参集和最终保留集分开。

### 8.2 任务
| # | 测什么 | 做法 | 答案来源 | 指标 |
|---|---|---|---|---|
| T1 | 发现 | 从历史生成候选词 | 用户标注的样本 | P@k、召回 |
| T2 | 解释 | 给出含义和用法 | 用户盲评；群聊中明确的解释 | 准确率、幻觉率 |
| T3 | 理解 | 根据真实上下文，从真实下一句和干扰句中选择 | **真实聊天** | 准确率提升 |
| T4 | 判断语境 | 区分真实使用和被换到错误语境的使用；一词多义时选择含义 | **真实聊天** | 准确率、AUC |
| T5 | 运用 | 保留语境下生成回复 | 用户盲评 | 恰当使用率、**误用率、强行使用率、复述定义率** |
| T6 | 修正 | 按时间回放含义变化的词 | 用户标注 | 更新延迟、错误坚持率 |
| T7 | 反馈 | 注入纠正后测试**新场景** | 用户标注 | 新场景提升、误修正率 |
| T8 | 抗干扰 | 刷屏、恶意定义、假例子 | 构造样例 | 错误采信率 |

T3、T4 不需要人工答案，可以大规模运行。T5 必须盲评，它最接近真实目标，但成本最高。

### 8.3 对照组
| 组 | 配置 | 回答的问题 |
|---|---|---|
| A0 | 无知识 | 基线 |
| A1 | 仅原文检索，不抽取 | **是否真的需要知识抽取** |
| A2 | 定义 | 最小抽取 |
| A3 | 定义 + 例句 + 适用语境 | 用法信息的价值 |
| A4 | A3 + 状态门控 | 状态的价值 |
| A5 | A4 + 后台维护 | 维护的价值 |
| A6 | A4 + 反馈 | 反馈的价值 |

A1 很关键：第一份报告引用的论文显示，保留原文常常胜过抽取。如果 A1 赢过 A2/A3，知识层就要重新设计。

### 8.4 判定规则
- 同一批题配对比较，报告样本量、置信区间和逐题胜负；样本不足时标记为「未测」。
- 门槛在看到基线结果后由用户确定，确定后不再修改；最终保留集只运行一次。
- 失败和作废的实验都记录。
- **最高权重指标**是错误知识造成的伤害：误用率和幻觉率。提升再大，如果误用率超过上限也不算通过。

### 8.5 后台机制的判定
- **后台维护**：同一批题上，比较有无维护（A4 vs A5）。可完全离线回放，不需要真实心跳。
- **心跳**：只有后台维护证明有价值后才考虑；它只决定运行时机，可以用普通定时任务替代。先比较「按证据阈值触发」和「定时触发」。
- **主动发话**：仍按之前的决定，先测试，效果差就不加。

## 9. 开发顺序（调整）

知识层可以和上色并行。只要全文检索就能找到词的所有出现，所以不必等全量上色。

| 阶段 | 内容 | 决策点 |
|---|---|---|
| 0 | 核对数据，统计引用 | 字段映射 |
| 1 | 原始层和导入器 | 完整性 |
| 2 | 全文检索 + 评测框架 + 基线 | 用户确定门槛 |
| **3a** | **小规模知识实验**：用户标注约 50 个词（各类型都有）；前测；K1 发现 | 模型到底不懂多少 |
| **3b** | **T3/T4 + A0/A1/A2/A3 对照** | 是否需要抽取（K2） |
| 4 | 上色试验 | 上色方法 |
| 5 | 记忆对照（上一份报告的 E2、E4、E5） | 第二层、向量 |
| **6** | **K4–K6：证据门槛、图片、多义** | 状态门控规则 |
| **7** | **T5 盲评和 T6–T8** | 第一阶段是否通过 |
| 8 | K7、K9、K10：后台维护、多 Agent、Notebook | 这些机制是否进入第二阶段 |

**第 3a 是最值得先做的小实验**：花费低，却能回答整个研究方向的前提——模型对这些群的梗到底有多不懂，学完能提升多少。

## 10. 风险
- **隐私**：联网研究会把词条发出去。内部梗和人物相关词条不应外发；默认关闭，只对判断为公共梗的词开启。
- **伤害**：错误解释可能让机器人说出冒犯的话；攻击性和隐私类用法必须有 `risk` 标记，默认禁止主动使用。
- **隐含事实**：部分梗涉及具体人物的尴尬事。「机器人能否用」需要单独规则，第二阶段前不启用。
- **用户标注负担**：T1、T2、T5 依赖你的判断，这是目前无法替代的。
- **数据缺口**：约 37.6% 媒体元素无候选文件（含 19,479 个商城表情），依赖这些图片的梗可能无法学习。
