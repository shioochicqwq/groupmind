# 会话接力：P0 审计结论与文件级计划（2026-11-13）

依据：`session-handoff-plan-for-claude.md`（用户提供）。本文只写现有代码里查到和试出来的东西。

## 1. 结论

- **可以做，而且不用改 dsh。** dsh 0.2.1-rc.4 的 SDK 协议（stdio JSON-RPC）只有 `initialize / session/prompt / session/resume / session/wait / working-directory / shutdown`，没有 fork，也没有 cancel。但 dsh 内部有 `ctx.sessions.fork` 和 `buildForkSeed`（`@deepseek-ai/dsh-session/fork`），dsh 自己的 Web API fork 就用它们。我们的 harness 插件（同 `compaction-persona.mjs` 的写法）能在同一个进程里调用这两个函数。
- **试验已通过**（`qqbot-data/runs/handoff-2026-11-13/spike2.py`，假模型 + 本地慢工具）：
  1. 会话 A 卡在一次 6 秒的工具调用里时，插件在 0.05 秒内复制出会话 B，再通过 `session/resume` 交给 SDK。
  2. B 立刻开始新回合，A 仍在等。A 的工具结果回到了 A 自己的调用上。
  3. B 的模型请求里：system 和 tools 与 A 完全相同，A 那次请求的 5 条消息全部是 B 的前缀，可以命中前缀缓存。
  4. B 的请求里没有任何 tool_call，A 的长工具结果（3,000 字）也没有进到 B。
- **切点：** 发起慢调用的那条模型消息之前。B 继承的是触发这一回合的群消息，以及同一回合里已经完成的步骤（比如已经发出的「我去看看」）。没完成的步骤由 dsh 自带的 fork closer 关闭。所以 B 的输入里没有 tool_call，不需要伪造工具结果。
- **最佳接力边界在 bothost 宿主进程**，不在 dsh 里：
  - 慢工具（`look_up`、`watch_video`）本来就由宿主通过 MCP 提供，升层决定也发生在宿主进程内：`bothost/web.fetch` → `tiers.read_html`。
  - 宿主从 dsh 的 `session.event` 通知里能看到每次 `tool/call`（会话 id、call id、参数），所以能把一次 MCP 请求对应到发起它的会话。

## 2. 现状审计

| 项 | 位置 | 现状 |
|---|---|---|
| 群消息入口 | `bothost/app.py` `Host.ws` → `on_event` → `Group.add` | 存库，判断是否叫到机器人，防抖后进 `Group.worker` |
| 会话生命周期 | `Group.run_turn`；`bothost/harness.py` `Dsh` | 每个群一个 dsh 进程。一个群一条会话：名字是别名，`daily_session` 时是别名加日期。`open` 先尝试 resume；`turn` 发 `session/prompt` 后等这个会话变回 idle |
| 工具暂停与恢复 | dsh 内部 | 一次工具调用就是一个挂起的 MCP HTTP 请求（`toolCallTimeoutMs` 180 秒），宿主返回结果后 dsh 继续回合。SDK 没有取消方法，只能杀进程 |
| 串行点 | `Group.worker` 等 `run_turn` 结束 | 慢工具期间新消息只能排队。回合超时（300 秒）会直接杀掉整个进程 |
| 发消息 | `Host.send` | 只发纯文本，不支持引用。`in_turn` 加每轮条数上限 |
| 联网分层 | `bothost/web.fetch` | L1 是 DeepSeek fetch 端点（`local_first` 站点跳过）。L2 是指纹请求（`tiers.read_html` 里的 `fetch_impersonate`）。L3 是 Chrome（`b.fetch_rendered`）。**L2→L3 的升层点在 `tiers.read_html` 进入浏览器循环之前** |
| 网站画像 | `sites.json` 加学到的 `web-sites.json` | 只有 `front_door`、`local_first` 和 `notes`，**没有「必须走浏览器」这一类** |
| 视频 | `Host.watch_video` → `watch.Watcher` | 一次只看一个视频。超过 160 秒先返回「还没看完」，要再调一次 |
| 网页互动 | 无 | 群机器人没有点击、填表一类的工具（`bothost/login.py` 是人工登录用的） |
| 存储 | `memory.db`（`Store`） | 研究用的消息库，改动前必须备份 |
| 测试 | `tests/bothost/test_parts.py`（2 个） | 只测解析和检索，没有回合级测试 |
| dsh web 测试会话 | `~/.dsh/profiles/web`，工具走 stdio | **不经过 bothost 的 Group，本方案不覆盖它** |

## 3. 设计

- **会话状态：** `ACTIVE → DETACHED → COMPLETED / FAILED → RETIRED`。**任务状态**单独记：`running → completed / failed / timed_out`。
- **作用域是一个群。** 每个群各有一个 active 指针和一个代数（generation），不同群互不影响。
- **持久化：** 用一个 SQLite 文件（WAL），三张表：
  - `event`：`seq, ts, grp, session, task, type, source_msg, payload`
  - `task`
  - `active`：每群一行，带 generation，做 CAS
- **触发**（不计时、不额外调用模型）：
  - `watch_video`：调用时直接接力。
  - `look_up` 内部升层：用一个 contextvar 把 `request_handoff` 传给 `web.fetch` 和 `tiers.read_html`。L1、L2 成功都不触发。L2 被拦或页面太空、准备开浏览器时，在 `fetch_rendered` **之前**触发。
  - 已知要走浏览器的站：在任何请求之前触发。
  - 只有 ACTIVE 会话能触发，同一个 call id 只接力一次。
- **原子交接**，顺序如下：
  1. 在群锁里检查调用方是不是 ACTIVE，以及并发数有没有到上限。
  2. 复制会话；复制失败就什么都不改，按原来的串行方式继续。
  3. 用 CAS 改 active 指针，登记任务，写 `handoff` 事件。
  4. 放开 `Group.worker`，A 的回合转到后台等待。
- **B 怎么知道：** B 的下一个回合，在群消息前面加一段「内部记录」。内容按事件提交顺序排列，带原时间：
  - 旧会话在做什么、原消息是谁说的，并说明尚无结果、不得假装看过。
  - 已完成任务的回复和摘要。

  不往正在进行的请求里插任何东西。
- **A 怎么收尾：**
  1. 慢工具的结果回到 A 时，宿主在结果后面加一段收尾说明：不要再调用发言工具，在正文按【回复】【摘要】格式写完就结束。
  2. 宿主在 A 的回合结束后解析正文，由 ReplyGate 用 OneBot 的 reply 段引用原消息发一次。回复和摘要出自同一次模型生成。
  3. A 如果调用 `send_group_message` 会被拒绝。超时或失败的任务，后来的输出一律丢弃。
- **长期记忆：** 摘要里的「可记候选」只写进事件表，不进 `memory.db`。
- **恢复：**
  - 宿主启动时，把还在 running 的任务记为失败，并写事件告诉当前 active。
  - 回合超时或进程退出时，同一进程里的后台任务一起记为失败。
  - active 指针只在新会话打开成功以后才改，所以不会出现没有主会话的群。
- **开关：** `Config.handoff`（默认关）。关闭时代码路径和现在完全一样。

## 4. 文件级修改计划

| 文件 | 改动 |
|---|---|
| `deploy/dsh/handoff.mjs`（新，已写） | 插件：Unix socket 上提供 `fork`，切点在慢调用的模型消息之前 |
| `bothost/harness.py` | 记录未完成的调用和每个会话最后一段正文；新增 `find_call`、`fork` |
| `bothost/handoff.py`（新） | 协调器、事件日志、任务表、ReplyGate、收尾说明和摘要解析 |
| `bothost/app.py` | `Group` 按会话分开记录回合；`run_turn` 可以中途放开；工具调用归属到会话；`send` 加门禁和引用；`look_up` 和 `watch_video` 接入触发 |
| `bothost/web.py`、`plugins/astrbot_plugin_web_reader/tiers.py` | 升层钩子（一个可选回调参数），已知浏览器站点跳过 L2 |
| `bothost/config.py` | `handoff`、并发上限、后台任务超时 |
| `tests/bothost/test_handoff.py`（新） | T1–T10：真 dsh 加假模型、mock 工具、mock QQ |

## 5. 不做的

- 不改 dsh。不改 QQ 桥接协议，只在发送时加 reply 段。不改记忆检索和联网分层逻辑。
- 不引入 LayerFS。不做手机模拟器。
- RETIRED 会话没法从 SDK 关掉（没有 close 方法），只能等进程空闲 30 分钟停掉时释放。
