# dsh 的压缩钩子：宿主能听到什么、能换掉什么（2026-11-12）

目的：上线后的上色打算在主会话**冷启动**或**被压缩**时触发（D-047）。本文记录在 dsh 0.2.1-rc.4 上试出来的事实。全部用合成聊天和一个本地的桩模型端点测的，不耗模型用量；真实模型线路上没有跑通过一次压缩（当时 模型网关 线路连续 503）。

## 1. 结论

- **不用改 dsh，也不用新建运行档**。`sdk-minimal` 已经带压缩引擎；会话里的每个事件都会作为 `session.event` 通知发给宿主，其中包括 `compaction/start`、`compaction/summary`、`compaction/end`。
- bothost 现在把两种情况汇到一个入口 `Host.context_reset(alias, why)`：`Dsh.open()` 新建了会话（冷启动），或这一轮里收到了 `compaction/summary`（压缩）。用量文件的那一行多出 `reset` 和 `uncoloured`（还没上色的消息数）。上色任务本身还没有挂上去。
- **压缩引擎可以整个换成我们自己的**，用补丁就行：把内置的设为 `disabled: true`，再 `insert` 一个指向本地 `.mjs` 的条目。补丁不能改已有条目的 `name`（会被跳过并告警）。

## 2. 事件里有什么

`compaction/summary` 的 `data`：`summary`（文本块）、`shadowedRange`、`shadowedSeqs`（被摘要替换掉的会话事件序号）、`shadowedTokenCount`、`provider`、`model`；内置引擎还带 `usage`，字段是 `inputTokens`、`outputTokens`、`totalTokens`。压缩失败时没有 `summary` 事件，`compaction/end` 带 `error`。

序号是 dsh 会话日志里的序号，不是聊天消息的编号。宿主要知道「哪些聊天消息离开了上下文」，得自己记每一轮送进去的是哪些消息；目前的做法更简单：触发时把本群所有还没上色的消息都算作待上色。

## 3. 内置引擎的行为

- 在每一步开始前检查。压力取自上一次模型请求实际报回的输入量，加上之后新增内容的估算。阈值是 `min(窗口 × thresholdRatio, 窗口 − 预留输出 − headroomTokens)`，默认 0.8 和 65536。
- 摘要请求 = 当前整个上下文 + 一段指令，发给同一个模型（也可以用 `summarizationProvider`、`summarizationModel` 指到别的模型）。所以一次压缩大约多花一次全量输入。
- 指令是给编程助手写的（要求输出固定的 Markdown 结构：目标、进度、文件等），不适合群聊。
- 保留多少尾部按 dsh 自己的字数估算，中文约 4 个字算 1 个词元，比实际少数倍（合成聊天每轮约 800 字，dsh 估 206，Gemini 实际约 840）。`retainTokens` 设多少，实际留下的会多几倍。
- 摘要必须比被替换的内容短，否则这次压缩作废。
- 有手动压缩的入口 `compactNow(agent)`，现成的调用者只有给人用的 `/compact` 命令；JSON-RPC 里没有对应的方法。宿主想主动压缩，需要一个小插件把它暴露出来。**未试。**

## 4. 换引擎的写法

```yaml
- id: compaction-basic
  disabled: true
- insert:
    - id: compaction-chat
      name: /绝对路径/compaction-chat.mjs
      config: { ... }          # 与内置引擎相同的配置项
```

```js
import { createRequire } from 'node:module'
import { realpathSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
// 这个包在 dsh 的安装目录里，不在插件文件旁边
const require = createRequire(realpathSync(process.argv[1]))
const { BasicCompactionEngine } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-compaction-basic')).href)

class ChatCompaction extends BasicCompactionEngine {
  async summarize(input, agent, signal) {            // 唯一需要改的地方
    return { summary: [{ type: 'text', text: '……' }], provider: 'host', model: 'template' }
  }
}
export { ChatCompaction, ChatCompaction as default }
```

用一个不调模型、只写一句固定话的探针试过：能加载，压缩照常触发，宿主收到 `compaction/summary`，摘要调用的用量为 0。要注意内置引擎做摘要时能看到上一次的摘要并把它并进去；自己写的引擎要自己处理，否则每次压缩都会丢掉上一次摘要的内容。

## 5. 还没定的

- 现在每个群每天一个新会话，窗口 262,144，压缩实际上很少发生，触发基本都是每天的冷启动。要让压缩成为常态，得改会话的寿命或把阈值调低。
- 摘要是继续用内置的（编程助手口吻、多一次全量输入），还是换成面向群聊的。
- 上色结果怎么入库（新的 `color_run`、与前一批的重叠怎么衔接、习得词要不要重算）。

## 6. 未验证

- 真实模型线路上的压缩（只在桩模型上跑通）。
- 摘要请求是否命中主会话的缓存前缀。
- `compactNow` 经插件暴露给宿主。

## 7. 更新（2026-11-12 晚）

第 6 节前两项已在 DeepSeek 线路上验证：压缩能触发，摘要请求命中主会话的缓存前缀（93%–97%）。见 `2026-11-persona-compaction-and-session-lifetime.md`。
