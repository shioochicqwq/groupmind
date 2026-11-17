# 会话接力：实施报告（2026-11-14）

依据：用户提供的接力计划书；P0 审计见 `2026-11-session-handoff-audit.md`；决定记录见 D-052。

## 1. 完成范围

| 阶段 | 状态 |
|---|---|
| P0 审计 + 文件级计划 | 完成。先用最小试验确认 dsh 进程内可以复制会话，再动代码 |
| P1 最小原型（mock 工具、mock QQ） | 完成，见 `tests/bothost/handoff_rig.py` |
| P2 真实触发 | 完成：视频、L2→L3 升层、已知浏览器站。网页互动：群机器人没有这类工具，不适用 |
| P3 持久化与并发 | 完成：`handoff.db`、CAS 指针、多个后台任务、乱序归并、重启恢复、并发上限 |
| P4 实测 | 模拟流（假模型）和真模型（合成对话）各跑了一组。没接真实 QQ，所以未实测真实群 |

## 2. 实际改动

| 文件 | 改动 |
|---|---|
| `deploy/dsh/handoff.mjs`（新） | dsh 插件，在 Unix socket 上提供 `fork`。切点在发起慢调用的模型消息之前，未闭合的步骤用 dsh 自带的 fork closer 关闭 |
| `bothost/handoff.py`（新） | 协调器：active 指针、generation、CAS；任务、事件和会话状态；收尾说明；【回复】【摘要】解析；给活跃会话的内部记录 |
| `bothost/harness.py` | 从 `session.event` 记下未完成的工具调用和每个会话最后一段正文；新增 `find_call`、`fork` |
| `bothost/app.py` | `Turn` 按会话记录回合；`run_turn` 在接力时放开群（旧回合转后台）；`_background` 负责收尾；`Host.send` 加门禁；`post` 支持引用；`escalate`；`look_up` 和 `watch_video` 接入触发 |
| `bothost/web.py` | `ESCALATE` 钩子；已知浏览器站先接力再直接走浏览器；请求档失败、浏览器读到时学习站点 |
| `plugins/astrbot_plugin_web_reader/tiers.py` | `read_html` 新增 `before_browser`、`browser_only` 两个可选参数 |
| `plugins/astrbot_plugin_web_reader/sites.json` | 新增 `browser_first` 类：rym |
| `bothost/config.py` | `handoff`（默认关）、`handoff_max_tasks`（2）、`handoff_max_total`（4）、`handoff_task_timeout_s`（600） |
| `tests/bothost/handoff_rig.py`、`test_handoff.py`（新） | 测试台和 11 个测试 |

**没动的：** dsh 本体、QQ 协议层（只在发送时多了 reply 段）、记忆检索、联网分层的顺序、dsh web 测试会话。

## 3. 状态流与事件结构

**会话状态**（表 `session`）：
- ACTIVE → DETACHED：在慢工具的边界交出群聊。
- DETACHED → COMPLETED 或 FAILED → RETIRED：收尾时依次经过。
- 换日时，旧的 ACTIVE 直接变成 RETIRED。

**任务状态**（表 `task`）：`running → completed | failed`，与会话状态分开记。task 表的字段有：

- `id`、`grp`
- `session`（旧会话）、`successor`（新会话）、`call_id`、`kind`、`detail`
- `source_msg`、`source`（原消息的 id、时间、昵称、文字）
- `status`、`started`、`finished`、`reply`、`summary`

`(session, call_id)` 唯一，所以同一个调用重复升层只会接力一次。

**指针**（表 `active`）：每群一行，记 `session, base, generation, delivered`。
- 交接时用 `UPDATE … WHERE generation = 旧值` 改指针。
- 新会话打开成功之后才改指针，打开失败什么都不改，这次调用照原样串行跑完。

**事件**（表 `event`）：字段是 `seq, ts, grp, session, task, type, source_msg, payload`。type 有：
- `handoff`、`handoff_refused`、`handoff_failed`
- `task_completed`、`task_failed`

活跃会话在下一回合按 seq 读取 `delivered` 之后的 `handoff` 和 `task_*` 事件，放在群消息前面的「内部记录」里，每条带原时间和原消息。

**一次接力的顺序：**
1. 宿主收到 `watch_video`，或读页即将启动浏览器。
2. 从 dsh 事件里找出发起这次调用的会话和 call id。
3. 在群锁里确认它是 ACTIVE、没超出并发上限。
4. 插件复制会话。
5. 宿主 resume 新会话，CAS 改指针，登记任务，写 `handoff` 事件。
6. 放开群的 worker，旧回合转后台。
7. 慢工具继续执行，结果回到旧会话，并附上收尾说明。
8. 旧会话写【回复】【摘要】。
9. 宿主引用原消息发一次回复，写 `task_completed`，旧会话退休。

**回退：** `handoff: false`（默认）时，不加载插件，不建 `handoff.db`，行为与改动前一致，由 `test_switch_off_keeps_the_old_serial_behaviour` 验证。

## 4. 验证结果

**自动化测试：** `pytest tests/bothost/test_handoff.py` 11 个全部通过，连跑 4 次一致，每次约 19 秒。回归 `tests/bothost tests/bench` 共 139 个通过（包括检索、存储、读网页、看视频的已有测试）。

| 编号 | 测试 | 检查的内容 |
|---|---|---|
| T1 | `test_t1_…` | L1 读到、L2 读到都不触发 |
| T2 | `test_t2_request_tier_failing…`、`test_t2_page_needing_the_browser…` | L2 被拦或页面太空时，接力发生在浏览器启动之前；整轮测试里浏览器读到的页面回到旧会话，并引用原消息回复；同一 look_up 里的第二页不再接力 |
| T3 | `test_t3_site_known…`、整轮视频测试 | 已知站点在任何请求之前接力；视频在开始看之前接力 |
| T4 | 整轮视频测试 | 视频还没看完时，新会话已经回了新消息 |
| T5 | 整轮视频测试 | 只发一次引用回复；新会话下一回合看到时间、原消息的人、回复内容和摘要（含候选事实） |
| T6 | `test_t6_…` | A→B→C；后开始的任务先完成，两个结果都按完成顺序进了当时的 C，各自引用对的原消息 |
| T7 | `test_t7_…`、整轮视频测试 | 同一调用重复申请得到同一个继任者；5 个并发申请只产生 1 个；DETACHED 不能再接力；旧会话自己调用发言被拒 |
| T8 | `test_t8_failed_copy…`、`test_t8_harness_lost…` | 复制失败不改指针；超出上限按串行跑；重启时 running 任务记失败；迟到的结果被丢弃；进程中途死掉，任务记失败，群照常由原活跃会话接着聊，并被告知没做成 |
| T9 | 整轮视频测试 | 所有模型请求里都没有缺结果的 tool_call；新会话从没见过视频调用 |
| T10 | 整轮视频测试 | 旧会话发起视频调用前的那次请求，整个是新会话第一次请求的前缀（system 和 tools 也相同）；视频的长文本没进新会话，只有摘要 |

**P4 模拟高频群聊**（`qqbot-data/runs/handoff-2026-11-13/p4_stream.py`）
- 条件：脚本化假模型，每次调用 1 秒；视频替身 60 秒；40 条叫到机器人的合成消息，每 4 秒一条；第 2、14 条请求看视频。

| 模式 | 回复 | P50 | P95 | 最长 | 超过 60 秒 | 模型调用 |
|---|---|---|---|---|---|---|
| 串行 | 40/40 | 45.0 秒 | 79.5 秒 | 85.4 秒 | 10 条 | 48 |
| 接力 | 40/40 | 1.1 秒 | 1.1 秒 | 2.3 秒 | 0 | 82 |

- 接力模式下两条视频回复都引用了原消息，两个任务都完成。
- 结果里报了一个「重复」：两条视频回复的开头文字相同。这是假模型只回显前 12 个字造成的，两条分别引用了不同的原消息，不是重复发送。
- 接力模式的模型调用更多，因为新消息不再被慢回合攒成一批。假模型的 token 数没有意义，所以不比较。

**P4 真模型**（`p4_real.py`）
- 条件：deepseek-flash；合成对话；视频替身 30 秒。流程是：A 请求看视频，3 秒后另一人问晚饭，看完后有人追问视频内容。

| 模式 | 晚饭那条多久回 | 调用 | 未命中缓存输入 | 命中缓存输入 | 输出 |
|---|---|---|---|---|---|
| 串行 | 28.3 秒 | 7 | 3,320 | 14,720 | 412 |
| 接力 | 1.9 秒 | 6 | 1,480 | 14,336 | 680 |
| 接力（重跑） | 3.4 秒 | 6 | 1,669 | 14,848 | 917 |

- **跨会话缓存：** 新会话第一次请求命中 4,608，未命中 329；重跑时分别是 4,736 和 431。
- **按角色分：**（接力那次）
  - 群聊会话：4 次调用，未命中 908，命中 10,112，输出 318。
  - 后台会话：2 次调用，未命中 572，命中 4,224，输出 362。
- **行为（重跑那次）：**
  - 视频期间，新会话照实说「还在看」。
  - 旧会话引用原消息回了视频内容。
  - 追问时，新会话按摘要答对了是什么菜。
- **对比的偏差：**
  - 串行先跑，替两种模式付了共享 system 前缀的冷缓存，所以未命中输入这一列偏向接力。看总输入：串行 18,040，接力 15,816 和 16,517。
  - 接力的输出更多，因为后台会话要写摘要 JSON。
  - 样本只有 1 到 2 次，只能说明方向。
- ledger 记了 5 行（`session-handoff-p4`），token 按群聊会话和后台会话分开。

## 5. 剩余风险与未完成项

1. **没在真实 QQ 群里跑过。** 引用回复用的是 OneBot 的 `reply` 段，NapCat 下是否显示为引用，未验证。
2. **dsh web 测试会话没有接力**（用户决定只做 bothost）。目前 bothost 也没有常驻进程在跑，开关默认关。
3. **退休的会话占着内存。** SDK 没有关闭会话的方法，要等进程空闲 30 分钟停掉才释放。一天内接力很多次时，进程内存会涨，未实测。
4. **活跃会话的回合超时（300 秒）会杀整个进程**，同一进程里的后台任务一起记为失败。SDK 没有取消单个会话的方法，所以绕不开。
5. **超时或中断不会在群里自动说一句。** 失败的结果只交给下一回合的活跃会话，由它决定要不要提。只有旧会话自己跑完、模型写了失败的回复时，才会引用原消息说没看成。
6. **调用归属靠参数匹配。** 宿主把 MCP 请求和 dsh 的 `tool/call` 事件按工具名和参数对上，最多等 3 秒。两个会话同时用完全相同的参数调用同一个工具时，可能认错会话。对不上时当作活跃会话处理。
7. **`browser_first` 会自动学习。** 某个站的请求档偶然失败一次，之后它就一直直接走浏览器，可以在 `qqbot-data/bot/web-sites.json` 里手动删掉。
8. **依赖 dsh 内部模块。** 插件用了 dsh 0.2.1-rc.4 的内部模块 `@deepseek-ai/dsh-session/fork`，dsh 升级后要重跑 `tests/bothost/test_handoff.py`。
9. **旧会话的收尾靠模型照格式写。** 格式不对时，摘要按原文存（`unstructured`）；没写【回复】就不发。
10. **全部改动都没提交。**
