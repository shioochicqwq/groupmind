# 别的项目怎么处理「通用 agent 框架当聊天 bot 宿主」时的压缩（2026-11-12）

用户的问题：dsh 内置的压缩摘要是给编程助手写的，别人遇到同样的情况是怎么做的。下面只写从文档和源码里查到的；标了「转述」的来自第三方页面，没有对到一手来源。

## 1. 结论

- **没有哪个项目为聊天另写一套压缩**。三个用通用框架的项目都沿用框架自带的、编程口吻的结构化摘要，只留出改指令或换实现的口子。
- **它们靠的是摘要之外的两样东西**：压缩之前先把要长期留的东西写进另一处记忆；被压掉的原文留着、能搜到。摘要只负责让对话接得上。
- **「压缩前先做一次记忆整理」是现成做法**（OpenClaw），和我们「压缩时上色」是同一个形状。它的做法有两点和我们的设想不同：在到达压缩线之前就提前做；用的是主模型在一份脱离主会话的副本上做。

## 2. 各项目

| | OpenClaw | Hermes Agent | NanoClaw | AstrBot（不是编程框架，作对照） |
|---|---|---|---|---|
| 底层 | 内嵌的通用 agent 循环 | 自己的 agent 循环 | Claude Agent SDK | 自己的对话管线 |
| 会话寿命 | 默认不重置，靠压缩；可设每天（默认 4 点）或闲置多久重置，群聊可单独设 | 靠压缩 | 靠压缩 | 靠压缩 |
| 何时压缩 | 窗口的 75% 与「窗口 − 预留（默认 2 万）」取小 | 窗口的 50%（小于 51.2 万的窗口最低按 75%）；网关另有 85% 的兜底 | SDK 自动 | 窗口的约 82% |
| 留多少原文 | 最近约 2 万词元 | 开头 3 条 + 结尾约 1～2.5 万词元 | SDK 决定 | 最近 4 轮 |
| 摘要谁写、什么样 | 模型；结构化检查点；可用插件整个换掉（`compaction.provider`） | 辅助模型；固定模板（目标、进度、相关文件、下一步等）；下一次压缩在上一份摘要上更新 | SDK 自带 | 默认直接丢最早的一轮；可选模型总结，提示词可改 |
| 压缩前 | 离压缩线还差 4,000 词元时，跑一轮用户看不见的「现在写记忆」，写进当天的记忆文件；在脱离主会话的副本上跑，不进主会话历史；每个压缩周期一次 | 文档里没有 | 把整段记录存档到该群的文件夹（转述） | 无 |
| 压缩后 | 可选把指定的说明段落重新注入 | 摘要里带一句「更早的内容可以用会话搜索找回」；被压掉的轮次只标记为归档，仍可搜索 | 重新注入记忆文件；重新提醒可用的发送目标（转述） | 无 |

## 3. 对我们的含义

- **原文可找回**这一条我们已经有了：聊天都在库里，`memory_search` 能查。摘要里放一句指向它的话就够，不需要摘要自己保全细节。
- **摘要用模型写、只改指令**是通行做法。dsh 没有改指令的配置项，要用一个小插件覆盖 `summarize()`（已试通，见 `2026-11-dsh-compaction-hook.md`）。
- **提前量**值得借鉴：压缩是在一轮对话中间同步发生的，上色一批要几十秒到几分钟；等到压缩那一刻才开始上色，刚被压掉的那一段会有一阵子查不到。OpenClaw 的做法是在压缩线之前留一段余量先做。
- **会话寿命**：OpenClaw 现在的默认是不按天重置，Hermes 和 NanoClaw 也都是长会话靠压缩。每天新会话是可选项，不是主流默认。

## 4. 没查到的

- 这些项目在群聊里压缩后的实际效果，没有找到评测。
- NanoClaw 的存档格式和触发细节只有技能说明页和问题单的转述，仓库里的入口文件只确认了「新建、清空、压缩之后会重新注入记忆」。

## 来源

- OpenClaw：<https://docs.openclaw.ai/reference/session-management-compaction/compaction>、<https://docs.openclaw.ai/reference/session-management-compaction/housekeeping>、<https://docs.openclaw.ai/concepts/session>
- Hermes Agent：<https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching>
- NanoClaw：<https://raw.githubusercontent.com/qwibitai/nanoclaw/main/container/agent-runner/src/memory/session-hook.ts>、<https://skills.sh/qwibitai/nanoclaw/add-compact>
- AstrBot：<https://docs.astrbot.app/use/context-compress.html>
