# 上下文与记忆机制

> 目标：让 bot 在私聊/群聊里「记得住人、接得上梗」，同时控制 token。
> 实现：AstrBot 会话历史 + 群聊 ICL + **memory_beyond 插件**（事实记忆 + 压缩）。
> 决策：`DECISIONS.md` D-013 / D-016；插件版本见 [external-plugins.md](external-plugins.md)。

## 1. 三层结构

| 层 | 机制 | 当前配置 |
|---|---|---|
| 短期对话 | AstrBot 按 `umo` 保存会话历史；群聊额外 ICL 注入 | ICL **100** 条；历史持久化 200 条 |
| 长期记忆 | memory_beyond 的 Markdown 事实文件 + 索引 + 按需召回 | people 开 / global 关 / recall≤3 |
| 压缩 | memory_beyond 滚动摘要（0.70 触发），摘要用便宜模型 | gemini-3.8-flash，摘要≤1500 字 |

会话隔离：私聊 `napcat:FriendMessage:<QQ>`、群聊 `napcat:GroupMessage:<群号>`，互不串；`/reset` 清当前会话。

## 2. 记忆本子（memory_beyond）

- **数据**：`data/plugin_data/astrbot_plugin_memory_beyond/memories/` 下 session / people / global 的 Markdown；
  一个文件一条事实，webUI「插件页面 → 记忆管理」可查看/编辑/整理/删除。
- **工具**：模型用 `memory_write/read/edit/search` 自己读写；`/mb_status` 看状态与 token 构成；
  `/mb_reset` 清本会话压缩状态；`/mb_probe` 测摘要链路。
- **作用域**：
  - session：本群/本私聊的人和事（默认）；
  - people：同一个人跨群/私聊（按 QQ 号锚定，**开启**，注意隐私）；
  - global：bot 自身的全局规则（**关闭**，避免任何群污染全局）。
- **写入策略**（已写入人设）：稳定事实才记；一次性状态、秘密、key 不记；不向群友宣告；不编。
- **与 Chatbox 对比**：Chatbox 是「≤1000 字/条、总量≤8000 字的事实列表 + 冻结快照」；
  memory_beyond 用文件+索引+按需召回+压缩，长会话更省 token，且多 people/global 作用域（详见
  [corpus-and-style.md](corpus-and-style.md) 第 1 节）。

## 3. Token 实测（2026-10-24）

`/mb_status` 单轮估算 ≈ **7.8k tokens**（deepseek，首次会话）：

| 组成 | 约 |
|---|---|
| 固定开销（system prompt/人设/skills 列表等） | 3.7k |
| 工具声明（文件/执行/搜索/记忆等 schema） | 4.1k |
| 记忆索引/摘要/召回 | 0–0.3k |
| 历史原文 | 少 |

- 缓存命中约 7k tokens（DeepSeek prompt cache），实际成本显著低于全价；
- 省 token 手段：ICL 100、memory 压缩/摘要、recall≤3、摘要模型用 gemini-flash；
- 试过 `tool_schema_mode=skills_like`：工具声明 4110 vs 4066，无收益，已回退 full；
- 后续可选：自定义只读文件工具替代 `computer_use_runtime=local`（可去掉 file/shell schema，省约 2–3k）。

## 4. 群聊上下文

- ICL：每轮注入最近 100 条群消息（`group_message_max_cnt`），⚠️[DIRECTED AT YOU] 标注 @；
- `get_group_message_history` 工具：需要更早消息时模型主动检索（200 条持久化）；
- 图片：`gemini-3.8-flash` 生成一句中文描述后进上下文；
- 主动插话仍关闭（等测试群）。

## 5. 边界与注意

- people 记忆跨群可见，隐私敏感时关 `enable_people_memory`；
- 压缩后机器人侧历史由摘要接棒，平台侧聊天记录不受影响；
- 迁移 VPS：`data/plugin_data/...` 随 `data/` 一起搬；插件版本/提交见 external-plugins；
- 人设/模型切换会影响记忆注入的固定开销，换 1M 模型时可调大 `max_context_tokens`。
