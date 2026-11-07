# PROJECT.md — QQ AI 群聊 Bot

> 状态记录与架构入口。变更代码/配置后同步更新本文件；重要决策见 `DECISIONS.md`。
> 最近更新：2026-11-01

## 1. 项目目标与范围

- **目标**：让一个 QQ 小号在群聊中提供「像群友一样的 AI 陪聊/整活」能力，支持随时更换 LLM 模型/提供商。
- **当前范围**：单账号、群聊场景（@ 触发为主 + 后续低频主动插话）。
- **明确不做**（当前阶段）：QQ 官方机器人接入、多平台、商业客服、语音/视频。
- **最终形态**：部署到常驻 Windows PC 长期运行（AstrBot + SnowLuma，D-021，尚未部署）。

## 2. 架构

> 协议端已于 2026-11-01 决定从 NapCat 改为 SnowLuma（D-021），配置已准备但**未部署、未实测**。
> 本节下文和第 3、5 节里的 NapCat、`D:\` 路径与 VPS 内容是旧机器的历史记录。

```
QQ 小号 ⇄ 桌面 QQ + SnowLuma v2.3.3（OneBot v11）
        ⇄ 反向 WebSocket ws://127.0.0.1:6199/ws（token 鉴权）
        ⇄ AstrBot 4.29.1（消息分发 / 人格 / 上下文 / 插件 / LLM 编排）
        ├─ memory_beyond：事实记忆本子 + 上下文压缩（Markdown，data/plugin_data）
        ├─ Skill：data/skills/<name>/SKILL.md（模型用文件工具按需读取）
        └─ LLM Provider（DeepSeek 默认 + 聚合端点 5 模型）
```

- **AstrBot** 作为反向 WS 服务端（`ws_reverse_port: 6199`）；NapCat 作为 WS 客户端连入。
- **NapCat** 复用本机既有安装 `D:\Apps\NapCat`（原先用于 QQ 群图片抓取脚本），其 HTTP 服务 3000 端口和到 `127.0.0.1:8080` 的 HTTP 上报**保留不动**，只新增 `astrbot` WS 客户端。
- **AstrBot 数据目录**：`D:\qqbot\data`（由 AstrBot 的 `ASTRBOT_ROOT` 默认=当前工作目录决定），整个目录已被 gitignore，迁 VPS 时整体迁移。
- **Windows 本地**：`uv tool install astrbot`（全局工具，`C:\Users\Administrator\AppData\Roaming\uv\tools\astrbot`）。
- **记忆**：memory_beyond（固定提交，MIT），人物记忆跨会话、全局记忆先关；压缩由插件接管（D-013）。
- **文件工具**：`computer_use_runtime=local` + workspace 权限、禁执行（D-014），可读 QQ 发来的附件（落 `data/temp`）与技能文件，读不到 host。
- **VPS 目标（D-011）**：原生 systemd，不使用 Docker —— `qqbot-napcat`（NapCat AppImage + Xvfb）与
  `qqbot-astrbot`（uv 安装）两个服务，各自 `MemoryMax` 限内存；WebUI 只绑 `127.0.0.1`。
  Docker Compose 仅保留为可选 fallback（`deploy/linux/docker-compose.yml`）。

## 3. 当前已实现（已实际验证）

- [x] AstrBot v4.29.1 安装并启动成功（WebUI `http://127.0.0.1:6185`）
- [x] 仓库骨架 + git 初始化
- [x] `scripts/bootstrap_astrbot_config.py`：写入 OneBot v11 平台 + DeepSeek provider（key 走环境变量）+ 群聊上下文配置
- [x] `scripts/patch_napcat_onebot.py`：给 NapCat 增加 `astrbot` WS 客户端（幂等）
- [x] `deploy/windows/start-astrbot.ps1`、`deploy/windows/start-napcat.ps1`：本地启动脚本（加载 `.env`、避免 GBK 日志报错）
- [x] NapCat 4.18.28 启动成功，WebUI（6099）就绪，已进入扫码登录等待状态
- [x] AstrBot 反向 WS 端口 6199 已监听
- [x] 小号 `<BOT_QQ>`（example）扫码登录成功；AstrBot 日志出现「aiocqhttp(OneBot v11) 适配器已连接」
- [x] `send_private_msg` 实测成功（已发出测试消息），HTTP API / 好友列表可用
- [x] NapCat 升级 **4.18.28 → 4.18.41**：修复 `PacketBackend 不支持 QQ 9.9.32-51246` 兼容错误（升级后 `PacketHandler 初始化成功`）
- [x] VPS 部署资产：根目录 `docker-compose.yml`（AstrBot v4.29.1 + NapCat v4.18.41，WebUI 仅绑定 127.0.0.1）、`.env.example`、[deploy/linux/README.md](deploy/linux/README.md)、[docs/migration-vps.md](docs/migration-vps.md)
- [x] `scripts/backup_data.py` 已实测可打包 `data/`（排除 temp/）
- [x] 群聊整活初始策略已落地：人格 `example`（[config/personas/example.json](config/personas/example.json)）、群聊上下文 ICL、3% 主动插话、分段回复、20 条/分限流；调参说明见 [docs/group-chat-tuning.md](docs/group-chat-tuning.md)
- [x] `scripts/apply_persona.py` 通过 Dashboard API 幂等写入人格（已实测：AstrBot 启动日志 `Loaded 2 personas`）
- [x] 双 provider 已加载：DeepSeek（默认）+ 自定义聚合端点 5 个模型；WebChat 冒烟测试三种模型均正常回复（`scripts/smoke_llm.py`）
- [x] 小号 `<BOT_QQ>` 重新扫码登录成功，AstrBot WS 适配器已连接
- [x] 私聊/群聊测试链路已具备：QQ 消息 → NapCat → AstrBot（人设 example + 多模型）
- [x] VPS 部署方案改为**原生 systemd（不使用 Docker）**：`deploy/linux/native/`（README + 两个 systemd 单元），迁移清单同步更新；Docker Compose 降级为可选 fallback（D-011）
- [x] 一键体检脚本 `scripts/healthcheck.py`（跨平台，实测全 PASS）：端口、NapCat 登录/在线、平台适配器、6 provider、人格
- [x] **联网搜索**：启用 `web_search_deepseek`（复用 DeepSeek key），WebChat 实测能检索并回答时效问题（如 V4 发布日期）
- [x] **多模态**：图片 caption 用 `gemini-3.8-flash`（视觉模型），群聊上下文图片会转中文描述；聚合端点视觉输入已直连验证
- [x] **Skill 体系**：仓库 `skills/` 源 + `scripts/install_skill.py` 安装；示例技能 `web-lookup` 已安装并生效；开发指南 [docs/skills-dev.md](docs/skills-dev.md)
- [x] **插件层**：仓库 `plugins/` + `scripts/install_plugin.py`；`astrbot_plugin_strip_refs` 移除 QQ 里难看的 `<ref>` 引用标记（非流式路径已验证）
- [x] **记忆本子（A-11）**：memory_beyond v1.3.7（固定提交 `0ec75bf…`）已安装；私聊写事实 → `/reset` → 追问能回忆；`/mb_status` 正常；人物记忆开、全局记忆关
- [x] **文件工具（A-12）**：`computer_use_runtime=local` + workspace/禁执行；WebChat 实测读取 `data/temp` 文件成功，读 `D:\qqbot\PROJECT.md` 被拒；Skill 因此能真正读取 `SKILL.md`
- [x] **Token 策略（A-13）**：ICL 200→100；memory_beyond 0.70 压缩 + gemini-flash 摘要；`context_report.py` 基线；实测单轮固定开销 ~7.8k（固定 ~3.7k + 工具声明 ~4.1k，缓存命中 ~7k）；`skills_like` 无收益已回退
- [x] **Skill 教学/人味（A-13）**：[skill-tutorial.md](docs/skill-tutorial.md)、[corpus-and-style.md](docs/corpus-and-style.md)、`skills/style-humanizer` 已安装
- [x] **网页读取（A-14）**：自研 `web_reader` 插件（本地抓取正文+链接、SSRF 防护）；实测能顺着 whatasiger.xyz 首页链接挑文章并概括长文（DeepSeek fetch 首页只有 130 字且无链接，已降为 fallback）
- [x] **表情包数据集（A-15）**：自研只采集插件（无发送/无 LLM 工具）+ `data/sticker_dataset` + 标注/统计/评测脚本；示例图已跑通标注（委屈/生气）；**不发送表情包**
- [x] **换机迁移打包（A-16）**：整理仓库与缓存，提供 `scripts/package_transfer.py` 与 [docs/transfer-to-new-machine.md](docs/transfer-to-new-machine.md)，支持源码包与非密钥数据包分层打包、校验与 Google Drive 中转恢复（D-019）

## 4. 进行中 / 待验证

- [x] **QQ 私聊实测通过**（2026-10-24 17:10）：主号发「在吗」→ example 回「在呢，周六了还找我啥事」
- [ ] **QQ 文件附件实测**：你在 QQ 私聊/群聊发 `.txt`/`.pdf`/`.docx`，验证「总结这个文件」可用（机制已用 `data/temp` 文件验证）
- [ ] 群聊实测：用户确认现有群 `<GROUP_ID>` 不作为测试群；**暂缓**，待有合适的测试群再验收 @ 回复/上下文/主动插话
- [ ] 常驻 Windows PC 部署（**用户暂缓**）：按 [transfer-to-new-machine.md](docs/transfer-to-new-machine.md) 执行，并验收 SnowLuma 链路（D-021）
- [ ] VPS 原生部署：已不是当前路线（D-021）

## 5. 关键路径与端口

| 项目 | 位置 / 值 |
|---|---|
| 仓库 | `D:\qqbot` |
| AstrBot 数据 | `D:\qqbot\data`（cmd_config.json、data_v4.db、plugins…） |
| AstrBot WebUI | `http://127.0.0.1:6185`（用户 `astrbot`，初始密码见首次启动日志，登录后必须修改） |
| AstrBot OneBot 反向 WS | `0.0.0.0:6199`，路径 `/ws` |
| NapCat 安装 | `D:\Apps\NapCat`（升级到 4.18.41，旧版备份 `D:\Apps\NapCat.bak-*`；QQNT `C:\Program Files\Tencent\QQNT`） |
| NapCat WebUI | `http://127.0.0.1:6099/webui?token=<token>`（token 在 `D:\Apps\NapCat\config\webui.json`） |
| NapCat OneBot 配置 | `D:\Apps\NapCat\config\onebot11_<QQ号>.json` |
| 旧抓图脚本接口 | NapCat HTTP server `:3000`，HTTP 上报 `http://127.0.0.1:8080/qq_event`（保留） |
| 小号已加入群 | `<GROUP_ID>`「<GROUP_NAME>」（54 人，**不作为测试群**） |
| 记忆数据 | `data/plugin_data/astrbot_plugin_memory_beyond/memories/`（session/people/global） |
| 记忆插件配置 | `data/config/astrbot_plugin_memory_beyond_config.json` |
| 文件工具 | `computer_use_runtime=local`，workspace 权限、禁执行；附件落在 `data/temp` |
| 网页读取 | 自研插件 `web_reader`（`plugins/astrbot_plugin_web_reader`）：本地抓取正文+链接，SSRF 防护 |
| 表情包数据集 | `data/sticker_dataset/`（inbox/images/labels.jsonl，gitignored）；采集插件 `plugins/astrbot_plugin_sticker_collector` |
| 外部插件清单 | [docs/external-plugins.md](docs/external-plugins.md) |
| LLM Key | 本地 `.env` 的 `DEEPSEEK_API_KEY` / `MULTI_API_KEY`（gitignored） |

## 6. 模型切换能力

- 已配置两套 provider source（key 均以 `$ENV` 引用，不落盘）：
  - `deepseek_source` → `https://api.deepseek.com/v1`，模型 `deepseek-chat`（**默认**）
  - `multi_source` → `https://<GATEWAY_HOST>/v1`（OpenAI 兼容聚合端点），模型：
    `gemini-3.8-flash`、`claude-sonnet-4-6`、`claude-opus-4-6`、`gpt-6-astra`、`gpt-6.1-sol`
- 会话内切换：`/provider`、`/model`（管理员指令），按会话持久化；默认模型见
  `agent_runner.config.model.provider_id`。
- 管理员 ID：`astrbot`（Dashboard）与 `<ADMIN_QQ>`（QQ 主号，可用 `/provider`、`/model`、`/reset`）。
- 默认模型 `deepseek`（短、便宜、稳），`fallback_provider_ids=["gemini-3.8-flash"]`（deepseek 失败时自动回退）。
- 冒烟测试：`python scripts/smoke_llm.py --provider <id>`（经 AstrBot WebChat 全链路，见 runbook）；
  `--followup` 可在同一会话发第二条消息，验证多轮上下文。
- 人设评测：`python scripts/eval_persona.py --provider <id>`（10 个群聊场景 + 风格指标），
  结果与结论见 [docs/persona-eval.md](docs/persona-eval.md)。

**验证矩阵（2026-10-24，WebChat 全链路实测 6/6）**

| provider | 回复示例（群友口吻） | 状态 |
|---|---|---|
| `deepseek` | 群友<BOT_NAME>，闲聊摸鱼专用，别问我正经事 | ✅ |
| `gemini-3.8-flash` | 这破天忽冷忽热的，纯在随机抽人感冒。 | ✅ |
| `claude-sonnet-4-6` | 这鬼天气是在跟我过不去吧🙂 | ✅ |
| `claude-opus-4-6` | 宅家躺尸，不接受反驳 | ✅ |
| `gpt-6-astra` | 先睡到自然醒，剩下的醒了再说。 | ✅ |
| `gpt-6.1-sol` | 先睡到自然醒，剩下的醒了再说。 | ✅ |

- 多轮上下文：同一 WebChat 会话中「记住：我叫小明，喜欢打游戏」→「我叫什么？喜欢干嘛？」→
  「小明啊，喜欢打游戏，刚说完就考我」，✅ 记忆生效。
- 新增 provider：WebUI「模型提供商」添加 source + 模型，key 用 `$VAR` 环境变量。

**上下文与记忆**：会话隔离（umo）、memory_beyond 事实记忆（people/session，全局暂关）、群聊 ICL **100** 条 +
历史工具、图片描述、插件接管压缩；详见 [docs/context-and-memory.md](docs/context-and-memory.md)。
Token 策略与实测见 D-016；外部插件版本见 [docs/external-plugins.md](docs/external-plugins.md)。

## 7. 已知问题与技术债

- 本地 NapCat 升级到 4.18.41 后，快速登录（`-q <uin>`）要求手机 QQ 验证，需改回扫码；换机/换版本后扫码是常规路径。
- Windows 本机不能常驻，当前仅作开发验证；VPS 迁移需重新扫码登录（可能触发设备验证）。
- AstrBot 升级会带来配置迁移风险：当前锁定 4.29.1，升级前备份 `data/`。
- NapCat WebUI 默认无访问控制（`accessControlMode: none` 且监听 `::`），VPS 部署必须改用防火墙/仅内网监听（compose 已绑定 127.0.0.1）。
- NapCat / QQ 必须以 NapCat 目录为工作目录启动，否则会在仓库根写出 `guild*.db`（启动脚本已 `Set-Location` 修正，gitignore 兜底）。
- 主动插话依赖会话已存在（先 @ 一次产生对话），否则日志报 `No active conversation`。
- **主动插话当前关闭**（`active_reply.enable=false`）：小号所在群不是测试群，避免误插话；有测试群后再开并填白名单。
- 尚未做刷屏/被举报的线上观察，限流与主动插话概率需要实群调参。
- **内存容量风险（2026-10-24 实测）**：AstrBot RSS ≈ 264 MB，QQ 相关进程合计 ≈ 1.8 GB（Electron 多进程），
  NapCat 方案在 2 GB VPS 上会很紧；建议 ≥4 GB 或改官方 QQ 机器人（能力受限），见 D-011。
- **搜索 key 特殊处理（临时）**：AstrBot 的 `websearch_deepseek_key` 不支持 `$ENV` 引用，bootstrap 会把
  `DEEPSEEK_API_KEY` 的实际值写进 gitignored 的 `data/cmd_config.json`（provider key 仍是 `$ENV` 引用）。
- 引用标记 `<ref>`：联网搜索会自动要求模型输出 `<ref>`，已通过插件在发送前剥离（WebChat 流式模式仍会显示，QQ 非流式路径已清理）。
- **单轮固定开销偏高（实测 ~7.8k tokens）**：固定开销 ~3.7k + 工具声明 ~4.1k（本地文件/执行工具 schema 较大）；
  DeepSeek 有 prompt cache 命中（/mb_status 显示 ~7k 缓存），实际成本低于全价。后续可考虑自定义只读文件工具替代 local runtime。
- **memory_beyond 较新**（4 stars，v1.3.7）：接管压缩/身份标注，升级前必须备份并看 CHANGELOG；人物记忆跨群可见（隐私）。
- **网页读取限制（A-14）**：`web_reader` 对静态站效果好；JS 渲染站/登录墙/强反爬拿不到正文，需要时再评估第三方 reader（D-017）；
  所有人群聊可用，已做 SSRF 防护，后续可加域名白名单/频率限制。
- **表情包数据集限制（A-15）**：只采集不发送；少数 `mface` 段会被 AstrBot 跳过采集不到；标注依赖 VLM 成本，需人工复核；
  群友表情包版权/隐私仅本地保存（ID 哈希、不公开）。
- **账号被踢下线会漏消息**：2026-10-24 18:29 example 被 QQ 踢下线，离线期间消息不进 AstrBot；
  重登后用 NapCat `get_friend_msg_history` 拉取并手动补回（已补回两条）。小号勿多端同时登录。
- 图片 caption 会额外消耗视觉模型 token；主动插话仍关闭，等测试群。

## 8. 下一步计划

> 2026-11-07：记忆研究和联网模块的待办以 [docs/handover-2026-11-07.md](docs/handover-2026-11-07.md) 为准；下面是部署与调优方面的旧计划。

1. **本地调优优先（用户决定：VPS 暂缓，调好再说）**：
   - 记忆/文件/搜索已就绪；继续按用户方向迭代上下文与省 token（D-016）；
   - 支持用户自写 Skill：[skill-tutorial.md](docs/skill-tutorial.md) + [skills-dev.md](docs/skills-dev.md) + `install_skill.py`；
   - 人味：按 [corpus-and-style.md](docs/corpus-and-style.md) 建评测集 + few-shot，再迭代 [persona-eval.md](docs/persona-eval.md)。
2. **QQ 文件附件实测**：用户发 `.txt/.pdf/.docx` 验证「总结这个文件」（机制已在 WebChat 用 `data/temp` 文件验证）。
3. **表情包数据集验收**：用户在 QQ 群/私聊发几张表情包，确认采集器入库；再跑标注/复核/评测
   （[sticker-dataset.md](docs/sticker-dataset.md)）。**注意：当前不发送表情包**。
4. 群聊验收：等有合适的测试群后，把群号填入 `active_reply.whitelist` 并开启 `active_reply.enable`，
   按 [group-chat-tuning.md](docs/group-chat-tuning.md) 调参。
4. VPS 部署（暂缓）：按 [deploy/linux/native/README.md](deploy/linux/native/README.md) 与
   [migration-vps.md](docs/migration-vps.md) 执行；海外 VPS 注意 QQ 风控与内存上限（D-011）。
5. 安全收尾：WebUI 初始密码改为强密码；LLM key 使用一段时间后轮换。
6. 可选增强（按需）：表情包/戳一戳插件、self_learning（AGPL，D-015）、减少工具声明的自定义文件插件。

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

