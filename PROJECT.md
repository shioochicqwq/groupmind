# PROJECT.md — QQ AI 群聊 Bot

> 状态记录与架构入口。变更代码/配置后同步更新本文件；重要决策见 `DECISIONS.md`。
> 最近更新：2026-10-24

## 1. 项目目标与范围

- **目标**：让一个 QQ 小号在群聊中提供「像群友一样的 AI 陪聊/整活」能力，支持随时更换 LLM 模型/提供商。
- **当前范围**：单账号、群聊场景（@ 触发为主 + 后续低频主动插话）、Windows 本地验证。
- **明确不做**（当前阶段）：QQ 官方机器人接入、多平台、商业客服、语音/视频。
- **最终形态**：部署到 Linux VPS 长期运行（Docker Compose：AstrBot + NapCat）。

## 2. 架构

```
QQ 小号 ⇄ NapCat 4.18.28（NTQQ 协议端，OneBot v11）
        ⇄ 反向 WebSocket ws://127.0.0.1:6199/ws
        ⇄ AstrBot 4.29.1（消息分发 / 人格 / 上下文 / 插件 / LLM 编排）
        ⇄ LLM Provider（DeepSeek 或任意 OpenAI 兼容服务）
```

- **AstrBot** 作为反向 WS 服务端（`ws_reverse_port: 6199`）；NapCat 作为 WS 客户端连入。
- **NapCat** 复用本机既有安装 `D:\Apps\NapCat`（原先用于 QQ 群图片抓取脚本），其 HTTP 服务 3000 端口和到 `127.0.0.1:8080` 的 HTTP 上报**保留不动**，只新增 `astrbot` WS 客户端。
- **AstrBot 数据目录**：`D:\qqbot\data`（由 AstrBot 的 `ASTRBOT_ROOT` 默认=当前工作目录决定），整个目录已被 gitignore，迁 VPS 时整体迁移。
- **Windows 本地**：`uv tool install astrbot`（全局工具，`C:\Users\Administrator\AppData\Roaming\uv\tools\astrbot`）。
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

## 4. 进行中 / 待验证

- [x] **QQ 私聊实测通过**（2026-10-24 17:10）：主号发「在吗」→ example 回「在呢，周六了还找我啥事」
- [ ] 群聊实测：用户确认现有群 `<GROUP_ID>` 不作为测试群；**暂缓**，待有合适的测试群再验收 @ 回复/上下文/主动插话
- [ ] VPS 原生部署（**用户暂缓**，等 VPS 就绪）：按 `deploy/linux/native/README.md` + [migration-vps.md](docs/migration-vps.md) 执行

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

**上下文与记忆**：会话隔离（umo）、群聊 ICL（200 条）+ 历史工具、图片描述、自动压缩策略；
详见 [docs/context-and-memory.md](docs/context-and-memory.md)。

## 7. 已知问题与技术债

- 本地 NapCat 升级到 4.18.41 后，快速登录（`-q <uin>`）要求手机 QQ 验证，需改回扫码；换机/换版本后扫码是常规路径。
- Windows 本机不能常驻，当前仅作开发验证；VPS 迁移需重新扫码登录（可能触发设备验证）。
- AstrBot 升级会带来配置迁移风险：当前锁定 4.29.1，升级前备份 `data/`。
- NapCat WebUI 默认无访问控制（`accessControlMode: none` 且监听 `::`），VPS 部署必须改用防火墙/仅内网监听（compose 已绑定 127.0.0.1）。
- NapCat / QQ 必须以 NapCat 目录为工作目录启动，否则会在仓库根写出 `guild*.db`（启动脚本已 `Set-Location` 修正，gitignore 兜底）。
- 主动插话依赖会话已存在（先 @ 一次产生对话），否则日志报 `No active conversation`。
- **主动插话当前关闭**（`active_reply.enable=false`）：小号所在群不是测试群，避免误插话；有测试群后再开并填白名单。
- 图片理解未开：群里有图只会显示 `[Image]`，可后续用视觉模型做 image caption。
- 尚未做刷屏/被举报的线上观察，限流与主动插话概率需要实群调参。
- **内存容量风险（2026-10-24 实测）**：AstrBot RSS ≈ 264 MB，QQ 相关进程合计 ≈ 1.8 GB（Electron 多进程），
  NapCat 方案在 2 GB VPS 上会很紧；建议 ≥4 GB 或改官方 QQ 机器人（能力受限），见 D-011。
- **搜索 key 特殊处理（临时）**：AstrBot 的 `websearch_deepseek_key` 不支持 `$ENV` 引用，bootstrap 会把
  `DEEPSEEK_API_KEY` 的实际值写进 gitignored 的 `data/cmd_config.json`（provider key 仍是 `$ENV` 引用）。
- 引用标记 `<ref>`：联网搜索会自动要求模型输出 `<ref>`，已通过插件在发送前剥离（WebChat 流式模式仍会显示，QQ 非流式路径已清理）。
- 图片 caption 会额外消耗视觉模型 token；主动插话仍关闭，等测试群。

## 8. 下一步计划

1. **本地调优优先（用户决定：VPS 暂缓，调好再说）**：
   - 按用户方向迭代「上下文管理 / 多模态 / 联网搜索」相关体验；
   - 支持用户自写 Skill：`skills/` + [docs/skills-dev.md](docs/skills-dev.md) + `install_skill.py`；
   - 人设/群聊行为继续用 [persona-eval.md](docs/persona-eval.md) 评测。
2. 群聊验收：等有合适的测试群后，把群号填入 `active_reply.whitelist` 并开启 `active_reply.enable`，
   按 [group-chat-tuning.md](docs/group-chat-tuning.md) 调参。
3. VPS 部署（暂缓）：按 [deploy/linux/native/README.md](deploy/linux/native/README.md) 与
   [migration-vps.md](docs/migration-vps.md) 执行；海外 VPS 注意 QQ 风控与内存上限（D-011）。
4. 安全收尾：WebUI 初始密码改为强密码；LLM key 使用一段时间后轮换。
5. 可选增强（按需）：表情包/戳一戳插件、技能市场调研、主动插话升级（smart_wake 类）。

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
