# 语料与人味路线（含 Chatbox 记忆对比）

> 回答两个问题：① 语料数据集有没有用；② Chatbox 那种「模型自己的本子」怎么做。
> 相关决策：`DECISIONS.md` D-013（记忆）、D-015（Skill/语料）。

## 1. Chatbox 的记忆是怎么做的（源码核对）

Chatbox 1.23 引入 Memory（[发布说明](https://releases.chatboxai.app/en/blog/chatbox-1-23)），实现要点在
`src/renderer/packages/model-calls/toolsets/agent-memory.ts` 与 `src/shared/types/agent-persona.ts`：

- **事实条目**：每条 `{id, content, createdAt}`，单条 ≤ **1000 字符**；注入 system prompt 的总量 ≤ **8000 字符**；
- **模型自写**：提供 `save_memory` / `delete_memory` 工具，由模型决定何时记、记什么；
- **作用域**：Global Memory 或 Copilot（助手人格）私有记忆；会话开始时**冻结快照**进 prompt（稳定前缀利于缓存），
  当前会话的写入只对后续会话生效；
- **可审阅**：设置页可查看/删除；可扫描本地 Claude/Codex 记忆并逐条确认导入；
- 它**不是 RAG**：就是一份受长度限制的短事实列表。

**本项目采用 [memory_beyond](https://github.com/AlanBacker/astrbot_plugin_memory_beyond)**（MIT，无第三方依赖）：
同样是「模型自己写事实」，但用 Markdown 文件 + 目录索引 + 按需召回 + 压缩联动，支持 session / people / global
三种作用域，管理页可编辑；对长会话更省 token。配置与数据在 `data/plugin_data/astrbot_plugin_memory_beyond/`。

## 2. 语料有没有用：有，优先级如下

| 用途 | 需要量 | 收益 | 成本 |
|---|---|---|---|
| **评测集** | 30–50 条输入 + 评分标准 | 最高：每次改人设/skill 可判断是否变好 | 低 |
| **风格 few-shot** | 20–40 条短对话 | 高：直接改语感、口头禅、接梗 | 低（注意注入 token） |
| 自动风格学习 | 持续聊天记录 | 中：self_learning 类插件可挖表达/黑话 | 中（AGPL、审查、资源） |
| 微调 | 500–1000+ 干净样本 | 可能最高，但最难 | 高（数据/训练/隐私/维护） |

**结论**：先做前两项，能解决大部分「AI 味」；微调作为最后手段，等 few-shot 迭代 2–3 轮仍不满意再评估。

## 3. 语料采集与清洗

1. **导出**：`qq-chat-exporter`（5.8k stars，活跃，GPL-3.0）导出群/私聊记录（TXT/JSON）。
2. **授权与隐私**：只处理你本人参与/有权使用的记录；群聊涉及他人，先取得同意；**不提交仓库**，只放本地
   `data/` 或 `tmp/`（均已 gitignore）；导出后脱敏（QQ 号、手机号、地址、真实姓名、链接）。
3. **清洗**：
   - 去广告/复读/系统消息/纯表情；
   - 按「刺激 → 回复」成对保留，只留 1–2 句的短回复；
   - 剔除敏感话题（政治/色情/人身攻击/隐私）；
   - 标注场景（打招呼/接梗/吐槽/被问身份/被要求长篇/边界请求）。
4. **切分**：80% 风格库（few-shot/技能参考），20% 评测集（不参与训练/示例，避免自测自夸）。
5. **提炼**：句长分布、标点习惯、口头禅 top-N、接梗方式、拒绝方式、emoji 频率 → 写成人设规则与技能规则。

## 4. few-shot 放哪里（省 token）

- 人设 `begin_dialogs`：最多放 4–8 条**极短**对话（每轮都注入，贵）；
- Skill `references/examples.md`：放 20–40 条，仅在触发该技能时读取（便宜，推荐）；
- 不要把所有语料塞进 system prompt。

## 5. 评测方法

- 量化：`scripts/eval_persona.py` 已统计字数、AI 自指、Markdown、超长；
- 人评：给每条回复打 1–5 分（像群友 / 有情绪 / 接得住 / 不冒犯），记录改版前后对比；
- 回归：每次改人设/skill 都跑同一套 30–50 条评测集，避免「越调越怪」。

## 6. 什么时候考虑微调

同时满足再考虑：① few-shot/规则迭代 ≥3 轮仍明显 AI 腔；② 有 ≥500–1000 条干净、授权明确的样本；
③ 接受训练成本、部署与后续维护；④ 有独立评测集（不能用训练样本自测）。
