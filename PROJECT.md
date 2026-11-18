# PROJECT.md — QQ AI 群聊 Bot

> 状态记录与架构入口。变更代码/配置后同步更新本文件；重要决策见 `DECISIONS.md`。
> **交接总入口：[docs/handover-2026-11-16.md](docs/handover-2026-11-16.md)**（结构、位置、迁移、未完成事项、规矩）。
> 最近更新：2026-11-16。§1–§8 按当前状态重写；AstrBot 时代的旧版见 git 历史（提交 `5547da6` 及以前），§9 变更记录原样保留。

## 1. 项目目标与范围

- **目标**：让一个 QQ 小号在群聊里像群友一样聊天、整活。它要认得群里的人、记得群里的事，能自己查网页、看视频。
- **两条线**：
  1. **群聊机器人**：`bothost/`，当前在用户 PC 上做影子测试。
  2. **长期记忆研究**：`bench/`、`docs/memory-*`、`docs/research/`，分支 `exp/humanlike-memory`。记忆分三个想法：原文准确回忆、模糊印象、像人（D-043、D-044）。
- **当前范围**：单账号，只在一个群（代号 `ed14b7`）做影子测试，不往群里发消息。
- **明确不做**：QQ 官方机器人接口、多平台、发表情包。

## 2. 架构

```
QQ 桌面客户端（小号）⇄ SnowLuma v2.4.2（OneBot v11，Windows）
   ⇄ 反向 WS ws://127.0.0.1:6199/ws（token）
   ⇄ bothost（WSL 发行版 qqbot）
        ├─ 每群一个 dsh 0.2.1-rc.4 会话（sdk-minimal 内核；插件：会话接力 handoff.mjs、人设压缩）
        ├─ MCP 工具（/mcp）：发言、记忆上下文与检索、记人/查人、查证 look_up、看视频 watch_video
        ├─ memory.db：导入的群历史与上线后的消息同库（D-045），冻结版检索（D-046），人物事实表
        └─ 模型：主模型 gemini-3.8-flash（经开发机网关，临时，D-056）；查证 deepseek-flash；视频 gemini-3.8-flash-high
```

- bothost 代替了 AstrBot（D-045）：宿主进程只管收发消息、存库、调度，「怎么想」交给 dsh 这个通用 agent 内核。
- 慢任务（看视频、要开浏览器的网页）走会话接力（D-052）：旧会话在后台做完，新会话接着聊群。会话由插件持有，退休时关闭。不按时长限制，只做卡死检测。
- 人物表：人工标注的快照，加上机器人自己记下的人（D-054、D-055）。启动时、开新会话时、压缩时整张重建；中途新记的，作为【人物表追加】附在下一轮开头。
- 部署：Windows 上跑 QQ 和 SnowLuma；bothost 和 dsh 跑在专用 WSL 发行版里（D-053），见 [deploy/wsl/README.md](deploy/wsl/README.md)。

## 3. 当前已实现（已实际验证）

- [x] bothost 多群并行宿主，dsh 作内核，工具走 MCP（A-39～A-41）
- [x] 一个库：历史与新消息合并，跨群回忆；冻结版检索接入（A-41、A-43）
- [x] 人设模型自己写压缩备忘；DeepSeek 用长会话，Gemini 每天开新会话（A-44、D-048）
- [x] 查证帮手：在单独的对话里搜索、读网页，按层升级读取器（DeepSeek 接口 → 指纹请求 → Chrome），只交回结论（D-050）
- [x] 看视频：YouTube、B 站、QQ 视频文件直链（D-051；直链下载 2026-11-16 加上）
- [x] 会话接力：T1–T10 测试；连续接力 30 次后进程里只剩 1 个会话（D-052）
- [x] PC 部署（WSL）和影子测试：2026-11-15 00:42 到 11-16 17:48，共 716 个回合，0 错误（D-053）
- [x] 补群历史：从主号本地库导出后并入；冻结组单独封存（D-053）
- [x] @ 显示真名；人物表带「群里显示为」；机器人自己认识人（D-054、D-055）
- [x] 主模型直接看图；表情包另开调用看懂，不卡会话（D-056）
- [x] 测试：`tests/bothost` 加 `tests/bench` 共 156 个通过（2026-11-16）

## 4. 进行中 / 待验证

已知缺陷、没验证过的事、等用户定的事，都列在交接文档第 7 节。最要紧的三条：

1. **工具调用超过 5 分钟一定失败**：已修（2026-11-18，A-44 补记二十二），真实部署上还没跑过超过 5 分钟的调用。
2. **没交给后台的查证会挡住整个群**：建议这种情况下预算恢复 150 秒。
3. **Gemini 主模型慢**：p50 18 秒，DeepSeek 是 2.4 秒。要不要换回 DeepSeek，等用户定。

## 5. 关键路径与端口

| 项目 | 位置 / 值 |
|---|---|
| 代码（开发机） | `/home/<user>/projects/qq-bot`，分支 `exp/humanlike-memory`（大量未提交改动） |
| 数据（开发机） | `/home/<user>/projects/qqbot-data/`（库、快照、人设、实验产出、账本、密钥文件），不进仓库 |
| 运行（PC） | WSL `qqbot`，`/home/bot/qqbot/{app,config.json,run.sh,secrets,data,logs,venv,dsh}` |
| SnowLuma（PC） | `D:\qqbot-bothost\snowluma`，WebUI `127.0.0.1:5099`，OneBot HTTP 3000 / WS 3001 |
| bothost 监听 | `127.0.0.1:6199`：`/ws` 给 SnowLuma，`/mcp` 给 dsh |
| 计划任务（PC） | `QQBot-SnowLuma`、`QQBotWsl-keepalive`、`QQBot-bothost` |
| 模型网关（开发机） | `https://<GATEWAY_HOST>` → Caddy → `model-gateway:8318` → 模型网关 `:8317` |
| 影子输出 | PC `data/shadow.jsonl`，并私聊转发给主号 |
| 账本 | `qqbot-data/runs/ledger.jsonl`（255 行） |

## 6. 模型

| 角色 | 模型 | 走哪里 | 备注 |
|---|---|---|---|
| 群聊主会话 | `gemini-3.8-flash` | 开发机网关 | 临时（D-056）；DeepSeek 时用 `deepseek-flash` 和 DeepSeek 官方 API |
| 查证帮手 | `deepseek-flash` | DeepSeek 官方 | 搜索和读页用 DeepSeek 的 `/v1/tools/search`、`/v1/tools/fetch` |
| 视频 | `gemini-3.8-flash-high` | 网关的 Gemini 原生 `generateContent` | 视频以 base64 内联发送 |
| 表情包 | 同主模型 | — | 按图片 sha256 缓存 |
| 压缩备忘 | 同主模型（带人设） | — | D-048 |

切换模型改的是 PC 上的 `config.json`（`model`、`llm_base_url`、`llm_images`），改完重启 bothost。

## 7. 已知问题与技术债

- 见交接文档第 7 节。
- 依赖 dsh 0.2.1-rc.4 的内部接口（`agents.create/resume`、`buildForkSeed`、`agent.cancel`），升级 dsh 要先在 PC 上重跑 `tests/bothost`。
- 调用归属靠参数匹配；收尾要靠模型照格式写；超时或中断时机器人不会在群里说一句（见会话接力报告 v2 的风险清单）。
- `term_candidates.py` 依赖会话日志里的 `search_web`，在 bothost 会话上接不上，未处理（A-44 补记三）。
- 插件目录名还叫 `astrbot_plugin_*`，其实已由 bothost 直接 import。

## 8. 下一步计划

1. 查证预算（没交给后台的查证会挡住整个群）；5 分钟的工具调用墙已修。
2. 用户决定主模型用 Gemini 还是 DeepSeek，然后结束影子测试，真的往群里发。
3. 开发机迁移：按交接文档第 5 节改网关地址和 ssh 隧道。
4. 提交当前改动（等用户要求）。
5. 记忆研究：上线后的上色已接进 bothost（D-047 更新），默认关闭，要在 PC 上配 `colour_model` 并观察第一次运行；第三个想法的回忆策略层（D-044）。

## 9. 变更记录

### A-1（2026-10-24）项目初始化与本地链路搭建

- 仓库骨架、`PROJECT.md`/`DECISIONS.md`/runbook、Windows 启动脚本；
- AstrBot v4.29.1（uv tool）+ 本机既有 NapCat（OneBot v11 反向 WS）；
- 打通 `QQ ⇄ NapCat ⇄ AstrBot` 基础链路。

### A-2（2026-10-24）NapCat 兼容性修复与 VPS 资产

- 定位并修复 NapCat 4.18.28 对 QQ 9.9.32-51246 的 Packet 不兼容：升级到 **4.18.41**（旧版已备份）；
- 新增根目录 `docker-compose.yml`（AstrBot + NapCat，WebUI 仅绑 127.0.0.1）、`.env.example`、VPS 迁移清单、`backup_data.py`；
- 修正 NapCat 启动脚本工作目录（避免在仓库根生成 `guild*.db`）。

### A-3（2026-10-24）群聊陪聊/整活策略

- 人设 `example`（群友口吻）落库，`scripts/apply_persona.py` 幂等写入；
- 群聊上下文 ICL、3% 概率主动插话、分段回复、20 条/分限流写入 bootstrap 配置；
- 新增 [group-chat-tuning.md](docs/group-chat-tuning.md) 与验收/回滚清单。

### A-4（2026-10-24）多模型接入与 QQ 私聊验收

- 接入 DeepSeek 官方 + OpenAI 兼容聚合端点（5 模型），密钥走 `.env` + `$ENV` 引用；
- 新增 `scripts/smoke_llm.py`，WebChat 全链路实测 deepseek/gemini/claude 均正常；
- 管理员 ID 增加 QQ 主号 `<ADMIN_QQ>`（`/provider`、`/model`、`/reset`）；
- **QQ 私聊实测通过**（「在吗」→「在呢，周六了还找我啥事」）；群聊测试经用户确认暂缓。

### A-5（2026-10-24）VPS 部署方案改为原生 systemd（弃用 Docker）

- 用户约束：VPS 内存/磁盘紧张、要跑编译 → Docker 方案否决（D-011，D-005/D-007 标注被取代）；
- 新增 `deploy/linux/native/`：原生部署 README（AstrBot uv + NapCat AppImage + Xvfb）、
  `qqbot-astrbot.service`、`qqbot-napcat.service`（含 MemoryMax/CPU/IO 限制）；
- `docker-compose.yml` 移至 `deploy/linux/` 并标注为可选 fallback；删除 Docker 版 install.sh；
- 重写 `docs/migration-vps.md` 为原生迁移清单（含海外 VPS 风控与 swap/内存建议）。

### A-6（2026-10-24）一键体检脚本

- 新增 `scripts/healthcheck.py`（Windows/Linux 通用，stdlib）：端口、NapCat 登录/在线、
  平台适配器运行状态、LLM provider 数量、人格列表；
- 本地实测 10 项全 PASS；runbook 与原生部署文档补充用法；
- 可为 VPS 验收提供统一检查口径。

### A-7（2026-10-24）内存实测与容量结论

- 实测本地：AstrBot RSS ≈ 264 MB；QQ 相关进程合计 ≈ 1.8 GB（Electron 多进程）；
- 结论：NapCat + AstrBot 合计约 1–2 GB，2 GB VPS 极紧张；VPS 建议 ≥4 GB + swap，
  否则退回官方 QQ 机器人方案（轻量但能力受限）；
- 已更新 `deploy/linux/native/README.md`（资源预算）与 D-011 风险记录；更正目标描述为「原生 systemd 部署」。

### A-8（2026-10-24）全模型与多轮上下文验证

- `scripts/smoke_llm.py` 增加 `--followup`（同会话第二条消息）；
- 全部 6 个 provider 经 AstrBot WebChat 实测回复正常（见第 6 节验证矩阵）；
- 多轮上下文实测通过（自我介绍 → 追问记忆）；
- 结论：多模型切换 + 对话记忆链路在 QQ 之外已完整验证，QQ 私聊也已实测。

### A-9（2026-10-24）本地调优：人设评测、主动插话收紧、模型回退

- 用户决定 **VPS 暂缓，先本地调好**；
- 新增 `scripts/eval_persona.py`（10 个群聊场景 + 风格指标），deepseek 与 gemini-3.8-flash 各测一轮：
  平均 16.4 / 23.6 字，0 超长、0 AI 自指、0 Markdown；结论与样例见 [docs/persona-eval.md](docs/persona-eval.md)；
- 默认模型保持 deepseek，新增失败回退 `gemini-3.8-flash`；
- **主动插话改为默认关闭**（小号所在群非测试群，避免误插话），开启条件写入调参文档；
- 当轮未测项：图片理解未开、分段实际频率、真实群上下文与主动插话。

### A-10（2026-10-24）上下文/多模态/联网搜索 + Skill 与插件体系

- 联网搜索：启用 `web_search_deepseek`（复用 DeepSeek `tools/search`，直连实测通过），WebChat 实测能检索并回答时效问题；
- 多模态：图片 caption 改用 `gemini-3.8-flash`（视觉），`default_image_caption_provider_id` + 群聊 `image_caption` 均开启；聚合端点视觉输入直连验证通过；
- Skill：新增 `skills/web-lookup/SKILL.md` + `scripts/install_skill.py`，技能已安装并由 WebUI API 确认；编写指南 `docs/skills-dev.md`；
- 插件：新增 `plugins/astrbot_plugin_strip_refs` + `scripts/install_plugin.py`，剥离 QQ 回复里的 `<ref></ref>`（非流式路径验证）；
- `smoke_llm.py` 增加 `--no-stream`（更接近 QQ 非流式路径，用于验证装饰/发送阶段行为）；
- 已知临时 workaround：websearch key 不支持 `$ENV`，实际值落在 gitignored 的 cmd_config.json。

### A-11（2026-10-24）记忆本子 memory_beyond

- 安装 memory_beyond v1.3.7（固定提交 `0ec75bf…`，MIT，无第三方依赖），新增 4 个记忆工具；
- 配置：人物记忆开、全局记忆关、recall≤3、摘要 gemini-flash、整理 claude-sonnet、压缩 0.70；
- 关闭 AstrBot 内置压缩（fallback=1e9、max_turns=-1）与 identifier，交由插件接管；
- 人设增加记忆使用规范（何时记/不记、不宣告、不编）；
- 验证：私聊写事实 → `/reset` → 追问能回忆；`/mb_status` 显示记忆/压缩状态；记忆文件在 data/plugin_data。

### A-12（2026-10-24）文件工具（只读 workspace）

- `computer_use_runtime=local`，member/admin 均 `filesystem_scope=workspace`、禁执行/禁网络；
- 修复隐藏问题：此前 Skill 正文读不到，技能不生效；现在模型可读 `data/skills` 与 QQ 附件（data/temp）；
- 验证：读 `data/temp/qqbot-test-file.txt` 成功；读 `D:\qqbot\PROJECT.md` 被权限拒绝；工具列表含 file_read。

### A-13（2026-10-24）省 token、Skill 教程与语料方案

- ICL 200→100；新增 `scripts/context_report.py`；`/mb_status` 实测固定开销 ~7.8k（缓存命中 ~7k）；
- `tool_schema_mode=skills_like` 无收益（4110 vs 4066 tokens）已回退 full；
- 新增 [skill-tutorial.md](docs/skill-tutorial.md)、[corpus-and-style.md](docs/corpus-and-style.md)、
  [external-plugins.md](docs/external-plugins.md)、`skills/style-humanizer`；
- 健康检查扩展：记忆插件/文件工具/记忆工具/记忆目录/上下文配置/runtime 检查，全 PASS。

### A-14（2026-10-24）网页读取：自研 web_reader 插件

- 定位「看网页吃力」根因：DeepSeek fetch 首页仅 130 字且**无链接**、目录页无链接、搜索小站 0 结果、fetch 多次 504；
- 新增 `plugins/astrbot_plugin_web_reader`：本地 requests+BeautifulSoup 抓正文与链接，支持 offset 续读；
  SSRF 防护（仅 http/https、禁 localhost/内网/私有 IP、重定向逐跳校验）；所有人群聊可用；
- `skills/web-lookup` 改为优先 `web_reader`：首页链接→挑文章→读正文；失败可自然推脱但不编造；
- 实测：首页 341 字+45 链接、文章 1474 字可续读；WebChat 能选中《Q君与世界的外侧》并概括约四万字长文；
- `web_search_deepseek` 保留搜索，`deepseek_fetch_web_page` 降为 fallback；健康检查新增 web_reader 检查；
- 已知限制：JS 渲染/登录墙/强反爬站仍可能读不到，需要时再上第三方 reader（D-017）。

### A-15（2026-10-24）表情包数据集：只采集、不发送

- 用户决定：**暂不发表情包**，但收集/整理表情包数据集（AI 理解表情包能力差）；
- 新增 `plugins/astrbot_plugin_sticker_collector`：监听 raw OneBot image 段（sub_type/summary）采集候选、
  手动 `/sticker add`、`/sticker status`；**无发送工具、不发消息**；
- 数据集 `data/sticker_dataset/`（inbox/images/rejected/labels.jsonl/review.csv/stats.json），sha256 去重、ID 哈希；
- 新增标注（gemini 视觉 + taxonomy）、统计/复核、generic vs sticker-aware 评测脚本；
- `image_caption_prompt` 改为表情包感知；人设要求理解表情包但不发送；
- 验证：示例图标注出「委屈/生气/初音未来」，report/eval 可运行；插件加载、数据集目录、healthcheck 正常；
- 已知限制：`mface` 段可能被 AstrBot 跳过；标注需人工复核；隐私仅本地。

### A-16（2026-10-31）换机迁移打包与仓库整理

- 本机不能常驻，支持上传 Google Drive 并迁移到新设备继续处理；
- 清理 `tmp/` 中历史大文件（`tmp/upgrade` 143MB 与 `tmp/stealer-ref` 3.4MB），释放磁盘空间；
- 编写安全分层打包脚本 `scripts/package_transfer.py`：
  - 源码包 `qqbot-source-<date>.zip`：包含 tracked 源码、完整 `.git` 历史及元数据，严格排除 `.env`、`data/`、`backups/`、`tmp/`、日志与缓存，可安全上传网盘；
  - 数据包 `qqbot-data-bundle-<date>.zip`（可选）：仅包含 `data/sticker_dataset`（表情包及标注）、`data/plugin_data`（memory_beyond 记忆）等非密钥数据；
  - 自动为每个包生成 `.sha256` 校验文件；
- 编写配套恢复手册 `docs/transfer-to-new-machine.md`：详细记录新环境依赖安装、配置一键生成、插件/技能恢复与验收步骤（D-019）。

### A-17（2026-11-01）从 Google Drive 恢复仓库到新机器

- 用户决定以 Drive 上的 `qqbot-source-20261031.zip` 作为开发仓库，取代新机器上初始化的 `qq-bot` 仓库（D-020）；
- 源码包与数据包的 SHA256 均与随附校验文件一致，`git fsck` 无报错；
- 路径 `/home/<user>/projects/qq-bot` 不变，`master` 现为 Drive 历史（`5747219`），旧历史保留在本地分支 `legacy/bootstrap`（`ca800f0`）；
- 保留包内未提交的 `AGENTS.md` 改动与 `TRANSFER_MANIFEST.txt`；保留旧仓库的 `CLAUDE.md`、`README.md`（均未跟踪）；
- 未解压数据包，未安装依赖，未运行项目代码或测试；`docs/transfer-to-new-machine.md` 的恢复与验收步骤尚未执行；
- Drive 上的 `qqbot/qqnt_export_work/` 是 QQ 聊天记录数据，计划作为研究测试样本，本次未下载。

### A-18（2026-11-01）协议端改为 SnowLuma，配置面向常驻 Windows PC（未部署）

- 用户决定弃用 NapCat、改用 SnowLuma，未来部署到常驻 Windows PC，当前不部署（D-021）；
- 新增 `scripts/configure_snowluma.py`（生成 `onebot.json` / `runtime.json`，token 写入 `.env`）、`deploy/windows/start-snowluma.ps1`、`deploy/windows/register-autostart.ps1`；`start-astrbot.ps1` 增加 `-KeepAlive`；
- 删除 `deploy/windows/start-napcat.ps1`、`scripts/patch_napcat_onebot.py`；
- `bootstrap_astrbot_config.py`：平台 id 改为 `snowluma`，反向 WS 只听 `127.0.0.1` 并启用 token；缺配置时给出明确报错；补上文档已声明但脚本遗漏的 `identifier=false`；
- `healthcheck.py` 改查 SnowLuma 端口并带 token；更新 `.env.example`、运行手册与恢复手册；Linux 文档标记为历史参考；
- 验证：用临时副本运行配置脚本和 bootstrap（幂等、备份、两端 token 一致）；`healthcheck.py` 在无服务时能正常报 FAIL；
- **未验证**：SnowLuma 未运行，PowerShell 脚本未执行过（本机是 Linux 且没有 `pwsh`），QQ 注入、AstrBot 连接、QQ 收发均待部署时验收。

### A-19（2026-11-02）长期记忆系统需求确认与设计草案

- 与用户逐项确认长期记忆系统的需求，调研现有项目、记忆评测论文与模型渠道；
- 查阅 Drive 中聊天导出的说明文档（未读取聊天内容、密钥和数据库）；
- 新增 [docs/memory-system-design.md](docs/memory-system-design.md)：需求、依据、架构、评测和第一阶段计划，**待用户审阅，尚无实现**（D-022）。

### A-20（2026-11-02）记忆相关开源项目调研

- 审计 10 个指定项目（共 14 个仓库）的源码、测试和自建评测，报告见 [docs/research/2026-11-memory-project-survey.md](docs/research/2026-11-memory-project-survey.md)；
- 结论：未发现能表达上色或满足 QQ 人物身份需求的项目，这两层需要自建；心跳和伪学习在聊天场景的收益未被证明，不进入最小架构；
- 验证：部分无依赖测试在无网沙箱实跑；未安装插件，未调用模型；大型仓库为抽读。A 级项目未提供名单，未单独审计。

### A-21（2026-11-02）知识习得与伪学习调研

- 用户将持续知识习得列为核心方向，并提供 S/A 级名单（D-023）；
- 按名单审计，并追加与梗学习直接相关的 MaiBot、qq-bridge，报告见 [docs/research/2026-11-knowledge-acquisition-survey.md](docs/research/2026-11-knowledge-acquisition-survey.md)；
- 结论：现有项目能存解释，但都未评测学习后的实际运用；提出四级含义状态和离线评测设计；
- 验证：本轮只读源码，未运行测试和模型；部分 A 级项目只看 README。

### A-22（2026-11-02）选项登记与 benchmark 方案

- 新增 [docs/memory-options.md](docs/memory-options.md)：保留各决策点的多个选项，等实验结果决定；
- 新增 [docs/memory-benchmark-plan.md](docs/memory-benchmark-plan.md)：调查现成 benchmark，提出公共 + 真实群聊两层方案；
- 补读 A_memorix、dsh-heartbeat、dsh-j-space，并在调研报告 12a 节逐项回答「调研后决定」的选项；
- 验证：公共 benchmark 的数字取自论文，未下载或复现；方案尚未实现，待用户审阅。

### A-23（2026-11-02）确定实验起点

- 用户说明原文喂给模型、上色即分块；逐项选定起点，调研方案改为对照（D-024）；
- 重写 [docs/memory-options.md](docs/memory-options.md)，更新 benchmark 方案和设计文档；尚无实现。

### A-24（2026-11-02）benchmark 第一轮

- 新增 `bench/` 评测框架和 `tests/bench/`，真实数据和运行结果放在仓库外的 `qqbot-data/`。
- GroupMemBench 验证通过（44.6%，论文 46.0%）；S0 与基线的第一批对比见 [docs/memory-benchmark-results.md](docs/memory-benchmark-results.md)。
- 批量模型调用走本地模型网关 的 `gemini-3.8-flash-high`，判官用 `gpt-6.1-sol`，不用 Claude 模型。
- 梗表第一次测出提升；`bench/labeling.py` 生成多人离线打标页，第一轮 3 份在 `qqbot-data/labels/round1/`。

### A-25（2026-11-04）检索版本冻结

- 主实验在 DEV-2 复现；完成向量检索、打包与保底（E1–E4）、候选深度（K3–K30）三组实验，各组的条件、结果、分角色 token 和逐题原始记录都记在台账里（`docs/memory-benchmark-ledger.md`）。
- 冻结当前检索版本：四路 RRF、每路前 5、1500 字、交原文块（D-028）。
- 候选深度实验按完整请求的哈希复用历史回答，约一半回答和九成以上判定不必重跑。
- 下一步：证据进入上下文之后，模型用得好不好。

### A-26（2026-11-04～05）向量配置、SQLite、上色重叠

- 向量路改用 V2（文档/查询区分 + 检索指令），保留 M1（D-029）；三态评分（端到端 + 有效回答 + 空回答率）。
- 采用 SQLite（`bench/store/`），研究期不换关键词索引，旧→新 ID 对照文件保证旧实验可复现（D-030）。
- 上色重叠：合并方案显著变差、不采纳（D-031）；采用「去重不合并」B（D-032）。
- 阶段报告 v1–v3、下一阶段路线和待决问题在 `docs/research/2026-11-memory-*`。

### A-27（2026-11-05～06）梗表与人物打标、梗基线

- 可复用离线打标组件 `bench/labelkit/`；梗表与人物第一轮交回：机器梗表 33 条里 26 条是通用词、本群梗 0；被证据门槛丢掉的抽样里 2/3 是真词（只出现 1–4 次）；6 人各有多个账号。
- 梗表分两层：通用层跨群共享，本群层不合并（D-033）。
- 梗基线：不给梗表时模型解释对 43.7%（通用层 48%、本群层 27%），加一段语境通用层到 65%、本群层不变。
- 结果在 `docs/memory-benchmark-results.md` 末尾几节。

### A-28（2026-11-06）实验分支 exp/humanlike-memory：B 收尾、事件层旁路、文献

- 按《长期记忆与拟人化研发任务书》开分支 `exp/humanlike-memory`（未合入 master、未推送）。
- B 接入主管线 `bench/retrievers/frozen_pipeline.py`，回归逐题复现旧实验（`bench/check_frozen_pipeline.py`）；B 改变约 78% 的注入内容，问答层待补测（约 680 次回答调用）。说明见 `docs/memory-frozen-pipeline.md`。
- 事件层旁路原型 `bench/events/`（只引用 B 块，不参与检索），「晚上」打标页已发给用户（等交回），三种方案的预测已预先存档。设计见 `docs/research/2026-11-event-layer-design.md`。
- 认知科学文献笔记与设计立场：`docs/research/2026-11-cognitive-memory-notes.md`。

### A-29（2026-11-07）联网与视频模块 P0

- 按《联网搜索与视频理解模块计划书》做 P0：Bilibili-Video-Research 安装、测试、MCP 连通、Gemini 画面理解验证通过；本容器和 <HK_HOST> 都是机房 IP，中文百科 403、B 站视频下载失败。
- 网页读取比较：Crawl4AI 明显优于现有 `web_reader` 和 mcp-server-fetch（D-035，初步）。
- 模型分工：视频 Gemini，其余 DeepSeek（D-034）。
- 记录在 `docs/research/2026-11-search-module-p0.md`；交接清单见 `docs/handover-2026-11-07.md`。

### A-30（2026-11-07）补测启动：B 问答层、网页读取模型版、视频改走 模型网关

- **B 问答层补测完成**（补 D-032 的缺口）：DEV-1 端到端 84.1%（A/V2 85.5%，配对 −1.4，CI −3.4~+0.7）、DEV-2 71.1%（A 71.3%，−0.2，CI −2.5~+2.1），均不显著。回答 gemini-3.8-flash-high、判官 gpt-6.1-sol，经 模型网关。新增回答调用 323 + 358 次。台账 2 行已补，结果写进 `docs/memory-benchmark-results.md`；`bench/ledger_backfill.py` 增加 `embed_qa_B` 映射。
- **网页读取接模型实测**（`reader_eval.py model`，11 题）：web_reader 10/11 答对、1 编造；mcp-server-fetch 9/11、0 编造；Crawl4AI 10/11、2 编造。与无模型 ceiling 的「web_reader 链接截断」结论不同，模型会直接猜目标 URL。**DeepSeek 密钥（`qqbot-data/tools/deepseek.key`）实测 401 invalid**，本轮临时改用 模型网关 的 gemini-3.8-flash-high，与 D-034 口径不同，待补有效密钥后复测。D-035 暂不升级为正式决定。
- **视频（及所有 Gemini 调用）改走 模型网关**（用户决定，D-036）：模型网关 有 Gemini 原生接口、无 Files API；BVR（仓库外 `qqbot-data/vendor/bvr`）已改 `src/video-analysis.ts` 支持 `GEMINI_BASE_URL` + inline base64，6 秒合成视频经 MCP `analyze_video` 实测正确（8.45 s）。限制：>23 MiB 视频不能内联。
- **准备候选深度 V2 补测**：`bench/run_depth.py` 增加 `--vectors` 参数（默认 V0 保持旧行为），下一步跑 K3/K10/K20/K30 的 V2 问答层补测。
- 环境备注：本机 2 核 / 3.8GB 内存，跑批量模型调用时不要同时开多个重任务；磁盘当前约 80% 已用。

### A-31（2026-11-07）补测收尾、DeepSeek 密钥修复与搜索模块改进

- **DeepSeek 密钥修复**：`qqbot-data/tools/deepseek.key` 换成 dsh 凭据里的有效 key（旧 key 对 `api.deepseek.com` 返回 401）。网页读取评测恢复 D-034 的 DeepSeek 口径。
- **候选深度 V2 补测完成（两群）**：DEV-1 K3 83.9 / K5 85.5 / K10 84.3 / K20 83.9 / K30 82.5；DEV-2 70.6 / 71.3 / 71.1 / 69.7 / 68.4。**K5 在两个群都仍是第一**，D-028 的深度选择不需要改；K30 在 DEV-2 上显著变差。台账 +10 行，结果写进 `docs/memory-benchmark-results.md`（旧结果另存 `depth.V0.json`，`depth_V2.json` 为新补测）。
- **web_reader 0.2.0**（`plugins/astrbot_plugin_web_reader/`）：正文区链接优先（`article`/`main` 再补整页）、链接上限 60→150、新增 `links_offset` 分页与 `links_more`/`links_next`、工具说明加「引用原文前必须确认它出现在返回内容里」。新增 5 项单元测试（`tests/bench/test_web_reader.py`，全仓 106 项通过）。
- **评测判定修正**：`reader_eval.py` 的「编造」从「整段原文逐字匹配」改为「5 字符片段覆盖率 <0.5 才算编造」，修掉列表拼接/标点差异造成的假阳性；旧结果保留，新结果 `model2_ds.*.json`。
- **DeepSeek 口径三读取器打平**：11 题模型版 web_reader / mcp-server-fetch / Crawl4AI 都是 10/11；编造 0 / 0 / 1；平均 3.5 / 10.2 / 11.9 秒。**不引入 Crawl4AI 作为默认读取器**（D-037），Playwright MCP 留给需要点击/登录态的页面。
- 后续（未做）：真实场景（梗、百科、文档站）扩大样本；候选打包 E1–E4 与向量组 V/DV/DVq 的 V2 补测脚本已就绪（`--vectors/--experiment`），待跑；事件打标等用户交回。


### A-32（2026-11-08）DSH 测试会话落地与梗表更新闭环

- **测试会话**：DSH preset `test`（「测试（搜索+记忆）」）。系统提示由 `persona-botname.mjs` 拼装：`~/.dsh/profiles/web/persona-botname.md`（<BOT_NAME>人设与规则，用户可改）+ `qqbot-data/store/memory_snapshot.md`（人物/梗快照，常注入）。工具只有 `search_web`、`fetch_page`、`memory_context`、`memory_search`。
- **工具输出修复**：DSH 按 `output.schema` 投影工具返回值，原 schema 未声明字段时结果被裁成 `{}`（会话记录里 `memory_context` 返回 `{}`、`memory_search` 只剩 `{"query":...}`），模型因此“搜不到”。四个工具改为返回 `{text}` 包装并在 schema 声明。
- **梗表更新闭环**（`scripts/memory/term_candidates.py`）：`extract`（从会话工具查询词抽候选，过滤已知/停用词）→ `list` → `confirm`（写入 memory.db 的 term/term_sense，`source_table=session:<id>`）或 `reject` → `rebuild`（重新生成快照）。`build_snapshot.py` 现在合并 DB 中已确认词条（chat code `general` 为通用层，其余为本群层，DB 覆盖同名标注）。
- **验证**：确认「奶蛙」（通用层，含义：奶龙 AI 生成失败图衍生的表情包）后，快照通用梗 56 → 57 条，`memory_snapshot.md` 第 75 行出现该词条；其余 6 条噪声候选已 reject，剩 1 条「星紗」待判定。
- **限制**：候选抽取基于查询词，人名/产品名等噪声需人工 reject；快照更新需重启一次（冷前缀）；“尾部增量注入”（不重启）尚未做。

### A-33（2026-11-08）测试会话修复、梗表自动入表、交接准备

- **DSH 工具输出修复**：`output.schema` 未声明字段会被投影成 `{}`，模型因此“搜不到星纱”；`web-tools.mjs` / `memory-tools.mjs` 四个工具改为 `{text}` 包装。
- **搜索确认即入表**（D-039 补记）：`term_candidates.py extract` 对 `search_web` 结果含梗信号（梗/meme/表情包/抽象/网络用语/流行/网红/二创/玩梗）的候选，直接写 `term`（status=confirmed，来源 `search:<session>`），**不过频率门槛、不等人工确认**；其余候选仍走人工 confirm/reject。合成会话验证通过。
- **当前梗表**：通用层 57 条（含「奶蛙」）、本群层 15 条；人物 11 人。
- **测试会话**：`19d53a84` 可继续（恢复按当前 profile 挂载）；`10a6e6b0` 的 memory-test preset 已删，建议弃用。
- **交接文档**：`docs/handover-2026-11-08.md`（仓库外配置、会话状态、未完成项、注意事项）。

### A-34（2026-11-11）第三个想法：群友回忆标注试点与回忆策略层 v0

- **方向**（D-043）：记忆分三个想法，第三个（像人）不按问答准确率评。先做回忆策略层（路线 A），同时拿本群聊天当行为数据（路线 B）。调研见 `docs/research/2026-11-humanlike-memory-directions.md`。
- **路线 B 试点**：`bench/recall/`。正则粗筛、模型在上下文里标注（一阶段）、用冻结检索找回原文并让模型指认是哪一行（二阶段）。只用两个 DEV 群，共判出 821 条回忆，其中回忆群内聊天的 126 条；引原话的占 2% 到 3%。
- **二阶段不可靠**：DEV-1 上两个模型各判一次，24 条至少一方对上原文的回忆里只有 4 条指向同一行。间隔和角色的数字要等人工核对。
- **引用回复**：10,792 条里引用一天以前消息的只有 6 条，不能当回忆样本。
- **路线 A v0**：`bench/recall/policy.py`，按角色、时间、是否玩笑梗、是否被再次提起，把每段证据定为原话、大意、有这回事或不出现；明说查记录时走精确模式。规则表是暂定初值。空跑时记忆文本从约 1,280 字降到 210 到 540 字。还没生成回答，没做盲评。
- **核对页**（仓库外）：`qqbot-data/labels/recall-r1/label-recall-r1-dev1.html`、`label-recall-r1-dev2.html`，等用户核对。
- **花费**：台账新增 7 行，全部 DeepSeek，按角色分开；其中 2 行是作废的二阶段第一版。DeepSeek 账户余额已用完（接口返回 402），后续回答生成暂停。
- **结果文档**：`docs/research/2026-11-recall-pilot.md`；认知笔记新增第 11 节。测试 124 项通过。

### A-35（2026-11-11）第三个想法改为「形成印象」：回放、策略层 v2、盲评页

- **方向**（D-044）：用户否定按时间淡化。改为按时间顺序回放聊天，读的人只知道此前的事，判断哪些会留下印象（深、中、浅）；回忆时按印象给原话、大意、有这回事或不出现。A-34 里按「距今多久」的规则表作废。
- **代码**：`bench/recall/run_impress.py`（回放）、`policy.py`（改写，时间分桶去掉）、`run_policy.py`（空跑）、`impress_probe.py`（措辞探查）、`impress_check.py`（和群友后来提起的事对照）、`pair_pack.py` 加 `bench/labelkit/pages/recall_pairs_round1.js`（盲评页）、`report.py --impressions`（台账）。
- **结果**：留下印象的消息占 12% 到 16%，一半以上的日子什么都没留下；每千条消息的印象数不随时间递减。带着提示词里「深的很少，不要拔高」一句，DEV-1 深印象 0 件、DEV-2 只有 1 件；去掉这句重跑 DEV-1，深印象 6 件、记住原话 11 句。深印象的门槛由这一句措辞决定，没有基准。
- **问题**：大意限 40 字，答不了细节题；基准题上印象一侧多数回答是「不记得」。和群友后来回忆的原文对照，两个群方向相反，看不出关系。模型印象和人的印象是否一致没有检验。
- **盲评页**（仓库外）：`qqbot-data/labels/recall-pairs-r1/label-recall-pairs-r1-dev1.html`，32 加 4 题，同一回答模型只换记忆部分；第一问问用户自己还记不记得，用作印象深浅的标准。等用户做。
- **等用户定**：大意放宽到多少字；深印象门槛用哪种措辞（建议拿盲评第一问来对）。
- **花费**：台账新增 13 行（208 → 221），全部 `gemini-3.8-flash-high` 经 模型网关，合计输入约 222 万、输出约 39 万 token，按角色分开。
- **结果文档**：`docs/research/2026-11-impression-formation.md`。测试 125 项通过。

### A-36（2026-11-11）标注页改为只做选择题，去掉凭空回忆的题

- **用户要求**：标注尽量用选择题，备注框可以留；靠人凭空回忆的题去掉，人凭空不好回忆。
- **回忆对比盲评页**：去掉「先别看回答：这件事你自己还记得吗」。改为在回答下面直接显示当时的原文（问到的那几句标出，前后各两句），再用选择题问「对照原文，这件事你有印象吗」（一看就认得 / 大意对得上 / 看了才隐约想起来 / 看了也没印象 / 当时没看到）。这一问仍是印象深浅的标准，但从「回想」变成了「辨认」，分析时要记得两者不等价。参考答案改为直接显示。抽样、回答和甲乙对应关系都没变，没有新的模型调用。
- **晚上打标页**：去掉第 1 步的四个凭印象填写框和「写完才显示记录」的锁。原第 3 步的日期下拉框改为选择题，候选按标注者自己在打分步骤的回答列出（乱和热闹取打分最高的晚上，尴尬取标了「尴尬场面」的，难忘取选了「本来就记得」的），每个候选附当晚最长一段话题的摘要。「有没有印象」加了「当时没看群」一项。原设计里「印象先行」的检验（`docs/research/2026-11-event-layer-design.md` 第 5 节第 1 条）因此不再做。
- **回忆标注核对页**：本来就全是选择题，没有改。
- **代码**：`bench/labelkit/pages/recall_pairs_round1.js`、`events_round1.js`、`bench/recall/pair_pack.py`（加原文片段）、`bench/events/label_pack.py`；标注包的名字改为取自输出文件名，新文件不会沿用旧页面的本机进度。
- **页面**（仓库外，旧版保留）：`qqbot-data/labels/recall-pairs-r1/label-recall-pairs-r1-dev1-v2.html`（32 加 4 题）、`qqbot-data/labels/events-r1/label-events-r1-dev1-v2.html`（23 个晚上）、`label-events-r1-dev2-v2.html`（20 个晚上）、`qqbot-data/labels/recall-r1/label-recall-r1-dev1.html` 和 `-dev2.html`（未改）。五个页面经 dsh 发给用户。无头浏览器检查通过，测试 125 项通过。
- **补充（同日）：五页合一**。用户要求合成一页一起做。新增 `bench/labelkit/combine.py`：把已生成的几个标注页的数据和页面脚本原样取出，放进一个文件，每部分一个标签，首次打开时才加载；各页自己的「完成」区去掉，底部只留一个「下载全部结果」，下载的 JSON 里 `parts` 按标注包名分开。进度的本机存储键和单页相同。页面：`qqbot-data/labels/all-r1/label-all-r1.html`（约 1.8 MB，五部分），无头浏览器检查通过，经 dsh 新会话（默认 Gemini）发给用户。

### A-37（2026-11-11）调研：专属工作区与一篇群聊 bot 文章的借鉴

- **起因**：用户给出一篇 Telegram 群 bot 的文章，要求记忆仍按自己的思路，看别的可借鉴之处，重点是专属工作区。
- **做法**：通读文章；读 AstrBot v4.29.1 源码和随附文档核对它的沙箱、子代理、主动回复能力；核对文章引用的论文存在。没有改配置和代码，没有部署或运行沙箱。
- **结论**：AstrBot 有第三方沙箱（Shipyard Neo，独立容器，技术预览）和子代理（实验性），没有脚本式工具调用，也没有小模型判断是否接话。本机隔离不支持 Windows，所以部署到 Windows PC 时只能在「禁执行」和「第三方沙箱」里选。沙箱执行默认只对管理员开放。
- **等用户定**：部署时上不上沙箱；执行权限是否对群友开放。
- **文档**：`docs/research/2026-11-workspace-notes.md`。这是项目层面的调研，提交时应进 `master`，不与记忆实验的条目同一次提交。

### A-38（2026-11-11）试跑：用 dsh 代替 AstrBot 做 bot 运行框架

- **起因**：用户考虑抛掉 AstrBot，改用 dsh 或 Pi；本机只有 dsh，先用它试；将来上 Windows 也要 Linux 沙箱。
- **做法**：读本机 dsh 0.2.1-rc.4 的随附文档；用合成群聊跑了 6 次（`sdk-minimal` 档，JSON-RPC 驱动，假的发消息和查记录工具经 MCP 接入，模型走 模型网关 的 Gemini）。没有接 QQ，没有用真实聊天，没有动正在运行的 dsh 网页服务。
- **结果**：不接话、查记录后回答、shell 算数写文件、进程重启后恢复会话、脚本式工具调用，都跑通。沙箱设为「只可写工作区」后：工作区外写不进宿主机，shell 里没有模型密钥；但能读家目录和 `~/.dsh`，能访问本机网络服务。
- **结论**：dsh 能当运行框架，接入量小；它自带的沙箱只管写文件，「专属工作区」要靠把整个 dsh 放进容器（Windows 上经 WSL2）。QQ 接入、攒批、是否接话、发送要自己写。
- **等用户定**：是否正式改用 dsh（会推翻 D-014、D-021 中与 AstrBot 有关的部分）；本机是否装容器运行时来试容器这一层；上下文压缩产生的摘要怎么处理。
- **未验证**：Pi、Windows、容器、子会话、压缩、缓存命中率、长时间运行。
- **文档与数据**：`docs/research/2026-11-dsh-harness-trial.md`；试跑材料在仓库外 `qqbot-data/runs/dsh-trial-2026-11-11/`；台账第 222 行。属于项目层面的调研，提交时进 `master`。

### A-39（2026-11-12）最小宿主进程 `bothost/`（Linux 版，合成消息）

- **起因**：用户决定 Windows 上把 dsh 直接开在 WSL 里；不通用的部分先在本机做 Linux 版。
- **做法**：新增 `bothost/`（约 580 行）。一个端口上同时提供 OneBot v11 反向 WS（`/ws`，校验 Bearer 令牌）和给 dsh 用的 MCP（`/mcp`，每次启动随机令牌）；聊天记录存 SQLite（FTS5 三字切分，短词走 LIKE）；被 @、被回复、被叫名字才开一轮，等 2 秒攒批，没触发的消息累积到下一批；会话按群按天，进程重启后恢复，新会话带最近 40 行原文；工具两个：`send_group_message`（每轮上限 3 条，超时回「状态不明，不要重发」）和 `search_chat`；每轮用量写 `usage.jsonl`。dsh 侧只有一个补丁文件 `deploy/dsh/bot.patch.yml`，不写 dsh 插件。
- **结果**：`scripts/bothost_synthetic.py`（假的协议端 + 真 dsh + 真模型）跑了三次。通过过的项：错误令牌被拒、无触发不开轮、被 @ 后按本批内容回答、轮后闲聊不接话、重启后会话历史还在。**没通过的两项**：回复 bot 后查旧记录作答、发送无应答时不重发。三次运行期间上游 Gemini 容量不足（503、空响应，直连一次调用 40 到 97 秒），这两项所在的轮次都以模型错误或超时结束，不能判断是宿主的问题还是上游的问题。
- **顺带修的**：模型失败的一轮现在在日志和 `usage.jsonl` 里带错误码；一轮超时后杀掉 dsh 进程再重开，避免上一轮迟到的发言混进下一轮（改后未重跑）。
- **已知限制**：全局一次只跑一轮；失败的一轮不自动重试；超时的一轮不记用量；dsh 没有「发完就结束」和取消接口，发送后模型还会多走一步；本机没有容器，dsh 的 shell 读得到宿主文件，所以本机版只用于合成测试。
- **未验证**：真实 SnowLuma 连接、Windows 与 WSL、图片等非文本消息的实际形态、多群并发、长时间运行。
- **数据**：台账第 223 行（16 次成功调用，输入 43,386、输出 440）。属于项目层面的改动，提交时进 `master`。D-045 等用户决定正式改用后再写。

### A-40（2026-11-12）bothost 改为多群并行；与 dsh 测试会话的重合调查

- **起因**：用户指出两点：多群不应该排队；dsh 里早有测试会话（A-32、A-33），bothost 与它有重复，要整合。
- **多群并行**：每个群一个 dsh 进程、工作目录、队列和工作协程；各群的 dsh 用各自的随机令牌连工具端口，宿主按令牌认群，模型无法指定群号；dsh 进程首次被叫到才启动，闲置 30 分钟停掉；同时进行的轮数上限默认 4。超时的一轮现在也记用量。
- **验证**：合成测试加了第二个群。两个群同时被 @，两轮同一秒开始、各跑约 285 秒、各自发了 1 条。其余检查项仍受上游 Gemini 拖累（单次调用一到数分钟、空响应），结果见后续补记。
- **调查**：用户批准后读了 `~/.dsh/profiles/web/` 下 `test` 预设的人设、三个插件。结论：两边互补为主，重复的是系统提示词的拼法和查聊天记录的工具；测试会话的内容全在仓库外、写成 dsh 插件、路径写死。建议工具都归到宿主一侧经 MCP 提供，人设拆成三段，测试会话改成挂同一套东西的薄壳。详见 `docs/research/2026-11-bothost-and-test-preset.md`。
- **已做**：bothost 加了配置项 `snapshot_file`（快照接在人设后面）。没有改 `~/.dsh` 下任何东西。
- **等用户定**：群里查历史是否跨群；历史库 `memory.db` 和新库 `chat.db` 怎么合；人设是否就用<BOT_NAME>这份。
- 属于项目层面的改动，提交时进 `master`。
- **补记（A-40，同日）**：第四次合成测试 9 项全过，但 5 轮都以错误结束：4 轮是发送后模型返回空内容、被 dsh 重试到放弃，1 轮超时（杀掉重开后下一轮正常）。把提示词改成「发完后正文只写（完）」后第五次重跑，9 项全过，5 轮无一出错，每轮 44 到 91 秒（此前 190 到 300 秒）。每个群的 dsh 进程约 132 MiB。台账第 224、225 行。

### A-41（2026-11-12）一个库、跨群回忆、测试会话改薄壳（D-045）

- **起因**：用户对 A-40 留下的问题作了选择：所有群一起查；两个库合成一个；人设先用<BOT_NAME>这份；同意现在就把 dsh 的 `test` 预设改成薄壳并重启 dsh web。
- **库**：`bothost/store.py` 改为直接用 `bench/store/schema.sql` 的表，新消息写进 `message` 等表，`chat.db` 不再使用。`schema.sql` 末尾加了关键词索引的三张表（`message_fts`、`message_df`、`message_fts_meta`）。索引逐条更新；启动时补上还没进索引的消息（例如导入脚本新加的）。协议端来的消息编号加 `ob:` 前缀，避免和导入的编号相撞。
- **检索**：FTS5 找候选，分数用 `bench.retrievers.bm25` 的同一条公式（D-030）。在真实库上先备份（`memory.db.bak-20261112T060509Z`）再建索引：8.8 秒，库从 27 MiB 到 34 MiB。用 47 个查询和旧的内存 BM25 比，前 10 名的编号和分数全部相同；查询中位 2 毫秒，最慢 314 毫秒。旧的 pickle 缓存（`~/.cache/qqbot-memory-bm25/`）不再使用。
- **工具**：`bothost/tools.py` 现在提供 `send_group_message`、`memory_context`、`memory_search`（默认所有群，可限定群和时间）、以及配置了 `QQBOT_SEARCH_API_KEY` 才出现的 `search_web`、`fetch_page`（`bothost/web.py`）。`search_chat` 取消。同一份工具也能单独以 stdio 方式启动（`python -m bothost.tools --db …`），给没有群的会话用。`scripts/memory/memory_search.py` 改成同一个库上的命令行查看工具。
- **人设**：性格、语气和示例搬到仓库外的 `qqbot-data/bot/persona.md`；`bothost/prompt.md` 只留群聊规矩和记忆用法，联网用法在 `bothost/prompt_web.md`。系统提示词的顺序是人设、群聊规矩、快照。
- **dsh 侧**（先备份为 `*.bak-20261112T060621Z`）：`test` 预设去掉 `memory-tools.mjs`，改挂 bothost 的 stdio 工具服务；`persona-botname.mjs` 改读共用的人设文件，`persona-botname.md` 只留这个一对一会话的工具说明；`web-tools.mjs` 暂时保留。`dsh --profile web --dump-config` 通过后用 `restart-web.sh` 重启。重启后工具服务作为 dsh web 的子进程在运行（约 68 MiB），预设 `test` 的工具列表里有 `mcp__qq__memory_context` 和 `mcp__qq__memory_search`。
- **黑话候选**：`term_candidates.py` 认带 `mcp__qq__` 前缀的工具名，能读未压缩的会话文件，新增 `--session-root`。没有实际运行（它会写词条表）。
- **合成测试**（第六次，台账第 226 行，17 次调用，输入 52,227、输出 315）：10 项过 9 项，6 轮无一出错，每轮 17 到 80 秒。新加的「在第二个群问第一个群里说过的事」通过。没过的一项：回复 bot 后问旧事，模型用两三个字的词查了三次都没命中。原因有两个，都是这种检索方式本来就有的：jieba 把「猫叫」切成一个词，单查「猫」对不上；发言人的昵称不在索引里，查昵称找不到那个人说的话。上一版用的三字切分加 LIKE 没有这个问题。
- **未验证**：测试会话里真正跑一轮对话（只确认了工具挂上）；联网工具的成功路径（DeepSeek 返回 402，余额为负；401 和输入检查验证过）；`restart-web.sh` 的健康检查把「连不上」也算成健康，这次是我另外确认服务起来的。
- 属于项目层面的改动，提交时进 `master`。
- **补记（A-41，同日）**：短词漏查（「猫」对不上被切成一个词的「猫叫」；昵称不在索引里）问过用户，答复是记录下来、暂缓，以后做实验再看。这是 jieba 关键词检索本来就有的，原测试会话的 `memory_search` 同样如此（两者结果已核对相同），不是合库引入的。

### A-42（2026-11-12）历史里的人和上线后的人对成同一个（用户同意）

- **问题**：导入的历史用 QQ 客户端的内部标识（`u_` 开头）记人，协议端给的是 QQ 号，同一个人上线后会被记成两个人。原有的 `id_map` 只记「研究文件 ID ↔ 库里的行」，没有 QQ 号。
- **做法**：新表 `person_account(platform, account, person_id)`。导出文件成员名单的头像地址里带 QQ 号，`python -m bench.store.importer accounts --db <库>` 据此建表，只读库里已有的群。bothost 记新消息时先查这张表，查不到才新建人。
- **结果**：真实库 249 人对上 248 人，没有一个号对多人的情况；库先备份为 `memory.db.bak-20261112T102155Z`，完整性检查通过。测试 3 项通过。
- **限制**：对不上的 1 人上线后仍是新的人。消息编号也是两套（导入的是客户端编号，协议端另有一种），以后若把上线期间的聊天再导入会重复，未处理。未在真实 QQ 连接上验证。
- **补记（A-41，2026-11-12 稍后）**：测试会话的联网工具也换成 bothost 的（用户要求）。`bothost.tools` 加了 `--web-key-file`，因为 dsh 启动子进程时会清掉名字带 KEY 的环境变量；密钥文件用 `qqbot-data/tools/deepseek.key`（用户确认只有一个 DeepSeek 账号）。`test` 预设去掉 `web-tools.mjs`，配置备份 `*.bak-20261112T103004Z`，校验通过后重启，预设工具列表里现在是 `mcp__qq__` 开头的 4 个。搜索的成功路径仍未验证（402，余额为负）。

### A-43（2026-11-12）bothost 的回忆换成冻结版检索；冷启动和压缩的触发点（D-046、D-047）

- **冻结版检索接进 bothost**：新文件 `bench/store/frozen.py` 从 `memory.db` 构建冻结版管线，`memory_search` 调用它。库加了 `embedding` 表，存 6,174 个文档向量（从研究用的缓存文件抄入，没有重新嵌入）；加表前备份 `memory.db.bak-20261112T163248Z`。
- **一致性**：`python -m bench.store.frozen check` 对冻结版答案级那次运行逐行比较，4fe395 590/590、ed14b7 586/586 行的块和注入文本全部相同。为此从 `bench/run_abcd.py` 抽出 `color_indexes`，从 `bench/memory_text.py` 抽出 `new_messages`；`bench.check_frozen_pipeline` 在两个 DEV 群上仍然全部通过。
- **上线时的差别**：问题先换成代号再检索；结果显示真实昵称和原话；问题的向量现取（约 2～4 秒一次调用），取不到时退到两路关键词并写明；多个群按群并列；最后一条已上色消息之后的新消息仍由逐条 BM25 查。顺带修了 `messages_from_db` 读不了上线后新消息的问题（它们没有媒体列表）。
- **触发点**：`Host.context_reset` 在会话冷启动或被压缩时被调用，用量文件多出 `reset`、`uncoloured` 两个字段。用合成聊天加本地桩模型验证：冷启动和压缩都能触发；`compaction/summary` 的用量字段名核对无误。
- **dsh 压缩引擎可替换**：补丁里禁用内置引擎、插入本地插件即可，不需要新运行档。记录在 `docs/research/2026-11-dsh-compaction-hook.md`。
- **未验证**：真实模型线路上的压缩（模型网关 线路当时连续 503，一次 5 轮的实验后 3 轮全部失败）；dsh 网页档的测试会话仍在跑旧工具，重启后才会用上冻结版；阿里云问题向量在持续使用下的配额。测试 4 项通过。
- **补记（2026-11-12 稍后）**：用户同意后重启了 dsh web（配置未改，备份 `cordis.patch.yml.bak-20261112T224808Z`，校验通过），测试会话的工具进程换成了新代码；没有在测试会话里实际对话验证。用户确认多群结果按群并列。会话寿命先做实验再定；压缩摘要怎么处理，先查了别的项目的做法，见 `docs/research/2026-11-compaction-in-other-bots.md`。

### A-44（2026-11-12）人设模型写压缩摘要；会话寿命小实验

- **人设摘要**：本地插件继承 dsh 的压缩引擎，只换摘要指令（中文、第一人称、给自己看的备忘），不改 dsh。合成群聊加 `deepseek-flash`：压缩后的回问全部答对（2/2、3/3），内置指令同样 3/3。差别在摘要的样子和长度（577、757 对 804 个输出 token），内置的会重抄系统提示里的规则。两种都会把刚回过的话写成没回。插件和指令还没入库，在数据目录 `runs/compaction-2026-11-12/`。
- **缓存**：摘要请求的输入 93%–97% 命中缓存；dsh 的 `inputTokens` 不含命中部分。用量文件新增 `cached`、`compact_cached`。
- **会话寿命**：新配置项 `daily_session`（默认不变）。缩小窗口模拟三天：长会话未命中输入 11,426 对每天新会话 22,351，命中 140,160 对 178,944。放到真实窗口，决定花销的是压缩阈值而不是按不按天切。
- **未验证**：隔夜缓存是否还在；多次压缩后摘要是否走样；真实聊天上的效果。
- 记录：`docs/research/2026-11-persona-compaction-and-session-lifetime.md`，账本 5 行（共 231 行）。阈值、是否改成长会话、是否采用人设摘要，等用户定。
- **补记（2026-11-13）**：用户定了用人设摘要、DeepSeek 上用长会话（D-048）。插件和指令入了 `deploy/dsh/`，bothost 启动时写补丁挂上；`daily_session` 默认改为 `false`，新增 `compact_at_tokens`（暂定 30,000）、`compact_keep_tokens`（暂定 1,250）。按默认接法加小窗口测试补丁复查：压缩触发，回问 3/3。中途发现补丁里的插件名不能写成表达式，写了的话插件被静默禁用、会话不再压缩，所以改成由宿主写绝对路径。账本共 232 行。
- **补记二（2026-11-13）**：用户定阈值照文章（约 11 万触发、留约 2 万原话），配置已改，上面的暂定值作废；联网结果要放到子会话里处理。探查了 dsh 自带的子会话工具：补丁插入即可运行，但不加限制时子会话和主会话同提示同工具、主会话自己也搜、通知引起的一轮和子会话用量宿主都没记。怎么挂还没定。账本共 233 行。
- **补记三（2026-11-13）**：用户选了宿主同步跑。新增 `bothost/lookup.py`、`prompt_lookup.md`，主会话的联网工具换成 `look_up`，用量行多一个 `lookup`。合成两问：主会话未命中 2,609 和 1,251（主会话自己搜时是 19,706）。`term_candidates.py` 依赖会话日志里的 `search_web`，在 bothost 会话上接不上了，未处理。账本共 235 行。
- **补记四（2026-11-13）**：按用户要求把今天的东西合进 dsh 网页端的测试会话并重启：联网换成 `look_up`，加了人设压缩的一对一版（`deploy/dsh/compaction-chat.*`），回忆排除 `0f51cf`。重启后服务和工具进程正常，日志无加载错误；没有在里面实际对话（未验证）。修了窗口小于阈值时比例大于 1 导致插件不加载的错。账本共 238 行。
- **补记五（2026-11-13）**：用户要求消息附带时间。bothost 每轮开头加一行日期和星期（每条消息原本就带月日时分）；测试预设加 dsh 自带的时间插件；`memory_context` 的「现在」改为真实时间。账本共 240 行。
- **补记六（2026-11-13）**：用户要求测试会话之间记忆互通。测试预设的会话从 dsh 会话日志抄进库里，算作一段一对一聊天 `dm`（`bothost/sessions.py`，D-049）；新会话的 `memory_context` 给出之前几次私聊的末尾，`memory_search` 搜得到全部原话；群聊机器人排除 `dm`。现有 2 个会话抄进 44 行，重复抄不增加。已重启 dsh 网页端；没有在真实会话里试过（未验证）。账本仍是 240 行。
- **补记七（2026-11-13）**：测试会话查 rateyourmusic 没拿到。原因是读网页走的 DeepSeek 接口被拦，自家读取器没接进来。按用户决定改成自家读取器在前、DeepSeek 接口在最低一层（`plugins/astrbot_plugin_web_reader/tiers.py`、`bothost/web.py`），`look_up` 交回查证过程并可用编号追问（D-050）。合成两问答出，但专辑页本身仍有没过验证的情况，原因未查明。bot 的 Python 环境装了 patchright 和 curl_cffi。账本共 242 行。
- **补记八（2026-11-13）**：读页顺序按用户决定改为 DeepSeek 接口 → 普通请求 → 浏览器指纹 → Chrome（补记七里「自家在前」是误读）。三个公开页面各读一次都读到，rateyourmusic 专辑页经浏览器 47.5 秒。dsh 网页端的配置已改好，按用户要求没有重启，测试会话还是旧行为。
- **补记九（2026-11-13）**：本机读取的第一档由普通请求换成浏览器指纹请求（实测不比普通请求慢）；浏览器档没读到时写明卡在哪一步。rateyourmusic 专辑页在 Chrome 档冷读 19.7 秒、热读 13.5 秒，其中等网络空闲固定吃满 8 秒；DeepSeek 接口读这一页要 16 秒才失败。没有模型调用，账本仍是 242 行。
- **补记十（2026-11-13）**：按用户选择做了三项读页提速：等正文稳定代替等网络空闲；记住 DeepSeek 接口读不了的站，之后直接走本机读取；「要从站内进」的站存到文件。已知的站写进读取器的 `sites.json`，随代码发布。rateyourmusic 专辑页从 47.5 秒降到 6–7 秒（各一次）。同一页约 3 秒内连读两次，第二次被拒，一分钟后恢复。没有重启 dsh 网页端。
- **补记十一（2026-11-13）**：帮手每次调用的输出上限从 1,000 改为 4,000 token，结论上限从 800 改为 1,500 字，结论为空时不带工具再写一次（用户决定）。原因是测试会话里读到了 rym 日本榜却交回「没查到」、追问时列表被截断。改后合成一问完整列出 15 张。账本共 243 行。
- **补记十二（2026-11-13）**：测试会话里查四张专辑的 rym 名次，失败原因是帮手在总榜里翻（第 2 页要登录），以及读页太密被拦（503）。按用户决定在 `sites.json` 加了 rym 提示、在帮手提示里加了「去读该项自己的页面」，先不限速。顺带修了：工具调用写成文字被当成结论、失败读取显示成「读到」、同一网址重复读、快超时时没写结论。重跑一次时帮手直接去读专辑页，但该站仍在拦，没有结论。账本共 244 行。
- **补记十三（2026-11-13）**：看视频接进 bothost（D-051）：新增 `bothost/watch.py` 和 `watch_video` 工具，复用 D-041 的视频读取器；群提示加 `prompt_video.md`。YouTube 短片看对，102.6 秒里约 100 秒在等模型；之后 模型网关 上游对 `gemini-3.8-flash-high` 回 503。B 站在本机仍 412。dsh 网页端配置和人设已改好并备份，重启后生效。
- **补记十四（2026-11-13）**：Chrome 档读 B 站视频页正常（11.8 秒），412 只出在 yt-dlp 下载。下载被拒时改为带机器人浏览器里该站点的 cookie 再试一次，B 站公开视频在本机能看了（第一分钟 115.7 秒）。新增 `bothost/login.py`，用来在机器人的浏览器里手动登录一次（D-051 更新二）。测试会话要重启后才用上。
- **补记十五（2026-11-14）**：会话接力（D-052）。
  - 审计结论在 `docs/research/2026-11-session-handoff-audit.md`：dsh 进程内能复制会话，旧会话的工具调用照常返回给它。
  - 新增和改动：插件 `deploy/dsh/handoff.mjs`、`bothost/handoff.py`；`app.py` 按会话分开记录回合，并加了发言门禁和引用回复；`tiers.read_html` 加了升层钩子；`sites.json` 加了 `browser_first`（rym）。
  - 开关 `handoff` 默认关。测试 T1–T10 通过。实测数字见 `docs/research/2026-11-session-handoff-report.md`，ledger 记了 5 行。
- **补记十六（2026-11-14）**：按用户意见修改会话接力（D-052 更新）。
  - 开着接力时不再按总时长限制，只保留卡死检测：10 分钟没有任何事件、也没有正在执行的工具调用，才取消那一个会话。
  - 会话改由插件负责打开和关闭，退休的会话会被释放。连续接力 30 次后，进程里只剩 1 个会话。
- **补记十七（2026-11-14）**：bothost 部署到用户 PC 的 WSL 里做影子测试；用主号本地库补了群历史（D-053）。
  - 新增 `Config.shadow`、`bench/store/backfill.py`；接力插件改走回环 TCP；`bothost/requirements.txt` 补全了依赖。
  - 在 PC 的 WSL 里跑通了 `tests/bothost` 的 16 个测试。
  - 合并后 PC 上的记忆库：ed14b7 新增 1,869 条，新群 19d60e、257d47 共 99,474 条。冻结组导出后单独封存，没有并入。
- **补记十八（2026-11-15）**：
  - 影子测试加了私聊转发：机器人每准备说一句，就由小号私聊发给主号，附上群里最近 4 条消息（`Config.shadow_forward_to`）。
  - 人物表补上「群里显示为」，外号按文字写（D-054）。
- **补记十九（2026-11-15）**：机器人自己认识人（D-055）。
  - 新增 `bothost/people.py`、`person_fact` 表，以及 `note_person`、`who_is` 两个工具。
  - 压缩备忘可以带【人物】段，接力摘要带 `people` 字段，都会自动记下。
  - 已经记下的人放进系统提示词，之后新记的用【人物表追加】附在下一轮开头。
  - 已部署到 PC 的影子测试。
- **补记二十（2026-11-15）**：
  - @ 显示真名字。
  - 人物表改为在启动、开新会话、压缩时重建。
  - PC 主模型暂时换成 Gemini，图片和表情包直接交给主模型看，描述以「机器看的」写回记忆库（D-055 更新、D-056）。
- **补记二十一（2026-11-16）**：
  - **影子测试收数**：2026-11-15 00:42 到 11-16 17:48，共 716 个回合，0 错误。
    - DeepSeek 186 回合，p50 2.4 秒；Gemini 530 回合，p50 18.1 秒、p95 90.1 秒。
    - 真实接力 1 次（看视频，51.6 秒，交回的是引用回复）。
    - 自己记下的人物事实 5 条。
    - 数据在 `qqbot-data/runs/shadow-2026-11-15/`。
  - **查出的问题**：一个回合挡了群 563 秒，是两次长查证。其中一次 5 分钟后返回 `fetch failed`：dsh 调工具的 HTTP 请求被 Node 的 `headersTimeout`（300 秒）截断。所以接力模式下，任何超过 5 分钟的工具调用都会失败。修法待用户确认。
  - **视频直链**：QQ 发的视频文件，yt-dlp 不认 `application/octet-stream`，加了直接下载并检查文件头（`video.py` 的 `_direct_file`）。
  - **交接文档**：新增 `docs/handover-2026-11-16.md` 和 `deploy/wsl/`（安装脚本、计划任务、配置模板、推送更新），README 改成入口页，§1–§8 按当前状态重写。`tests/bothost` 加 `tests/bench` 共 156 个通过。
- **补记二十二（2026-11-18）**：
  - **5 分钟的工具调用墙**：原因是 dsh 的 MCP 客户端走 Node 全局 fetch，宿主等工具做完才回应，undici 默认等响应头 300 秒。`deploy/dsh/handoff.mjs` 在开着接力（设了 `QQBOT_TOOL_TIMEOUT_MS`）时，只给发往 `QQBOT_MCP_URL` 的请求换一个等待上限为工具时限加 60 秒的连接，其余请求仍走 dsh 装好的分发器（代理和默认超时不变）。用 330 秒才回应的本地服务验证：MCP 地址 330 秒返回，其他地址 300 秒超时。
  - **上线后的上色**（D-047 更新，用户选了每次单独一个颜色批次、模型同冻结版）：新增 `bench/store/online.py`、`bothost/colouring.py`；`bench/store/frozen.py` 合并冻结颜色和上线后的批次，搜索时发现新批次就重建该群；配置项 `colour_model`、`colour_base_url`，密钥 `QQBOT_COLOUR_API_KEY`（默认用主模型的）。默认关闭，没有在真实数据上跑过。
  - **文档**：架构文档时机表里的「人物/梗表」改正：梗快照在进程启动时随系统提示固定，新会话和压缩只重建人物表。
  - 测试：`tests/bench`、`tests/bothost` 共 159 个通过（新增 `tests/bench/test_online.py` 5 个），2 个因本机缺依赖跳过。没有模型调用，账本不变。
