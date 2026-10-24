# DECISIONS.md — 重要设计决策

> 每条决策记录：背景、约束、调查过的方案、最终选择与理由、放弃原因、风险与验证方式。
> 禁止只写「采用了什么」而不写「为什么」。历史决策不覆盖，被替代时追加新条目并交叉引用。

---

## D-001 接入方式：个人小号 + NapCat（OneBot v11）

- **日期**：2026-10-24
- **背景**：要做 QQ 群聊 AI bot；用户在群聊里陪聊/整活，需要自由进任意群、@ 即回复、可主动发消息。
- **约束**：
  - 腾讯官方 QQ 机器人对个人主体限制大：个人主体暂不支持公开使用，只能加入自己是群主/管理员的群（≤500 群），需个人认证审核；群聊白名单内 @ 触发，主动消息有频率限制（群聊 5 分钟 5 条、单聊 60 分钟 4 条）。
  - 用户接受使用小号，并已知第三方协议存在风控/冻结风险。
- **调查过的方案**：
  - 官方 QQ 机器人（qq-botpy / AstrBot `qq_official` 适配器）：合规稳定，但能力受限、需审核，不适合「随意进群整活」。
  - NapCatQQ（基于 NTQQ 注入，OneBot v11）：社区活跃（2026-10 仍在更新），同类中风险最低，功能完整。
  - go-cqhttp：已停止维护，不可用。
- **决策**：个人小号 + NapCat（NTQQ 协议端），OneBot v11 反向 WebSocket 接入 AstrBot。
- **理由**：功能自由度与合规成本的最优平衡；本机已有 NapCat 安装可直接复用；后续若需合规可平移到官方适配器（AstrBot 同时支持）。
- **风险与缓解**：小号被风控（专用小号、养号、控制频率、内容安全）、换机登录触发验证（VPS 固定环境）、协议更新失效（关注 NapCat 版本）。
- **证据**：官方 FAQ/接入指南（bot.q.qq.com/wiki）；NapCat GitHub（NapNeko/NapCatQQ，2026-10-21 仍有提交）。
- **验证**：AstrBot 日志出现 aiocqhttp 适配器连接；群里 @ 小号能收到回复。

## D-002 框架：AstrBot（插件层扩展，核心不动）

- **日期**：2026-10-24
- **背景**：需要快速拥有可用群聊 bot；用户担心 AstrBot 代码质量（「屎山」），但认可其生态。
- **约束**：开发周期短；后续可能深度定制；本机 Windows、VPS Linux；要能换模型。
- **调查过的方案**：
  - AstrBot：开箱即用，WebUI、1000+ 插件、原生多 LLM/DeepSeek、OneBot v11 + 官方 QQ 适配器，维护最活跃（2026-10-24 仍有提交）。
  - LangBot：生产级、多平台、WebUI，但更偏平台化/企业，QQ 个人号路径不如 AstrBot 成熟。
  - NoneBot2：最灵活、纯开发框架，但需要自己实现人格/上下文/插件生态，首版成本高。
  - MaiBot：拟人群聊玩法强，但部署配置重、可控性弱。
  - 全自研：重复造轮子，不符合「优先复用」原则。
- **决策**：先采用 AstrBot v4.29.1（uv tool 安装），**业务逻辑尽量写在插件层，不改核心**；锁定版本，升级前备份 `data/`。
- **放弃原因**：NoneBot2 首版成本高；MaiBot 可控性不足；全自研无必要。
- **迁移预案（Plan B）**：若 AstrBot 核心出现阻塞性问题（配置破坏、协议适配 bug、性能），保留 NapCat + 已沉淀的 prompt/人格/配置，改接 NoneBot2 或自研轻量 OneBot v11 客户端（约 500–1000 行）。业务规则（触发、频率、人格）不绑定 AstrBot 内部 API。
- **风险**：「屎山」导致调试成本；升级破坏配置；插件生态质量参差。
- **验证**：本地跑通群聊对话；插件层可独立禁用而不影响核心。

## D-003 消息通道：AstrBot 反向 WS 服务端（6199/ws），NapCat 作为 WS 客户端

- **日期**：2026-10-24
- **背景**：NapCat 既有配置使用 HTTP server(3000) + HTTP 上报(8080) 给旧的抓图脚本，未启用 WebSocket。
- **决策**：保留旧 HTTP 配置不动，仅新增名为 `astrbot` 的 `websocketClients`，URL `ws://127.0.0.1:6199/ws`；AstrBot 平台配置 `type: aiocqhttp`、`ws_reverse_host: 0.0.0.0`、`ws_reverse_port: 6199`。
- **理由**：AstrBot 的 aiocqhttp 适配器基于 `aiocqhttp` 的反向 WS（服务端），与 NapCat 的 WS 客户端天然匹配；不破坏旧脚本。
- **工具**：`scripts/patch_napcat_onebot.py`（幂等，优先改 `onebot11*.json`）。
- **验证**：NapCat 启动后 AstrBot 日志出现「aiocqhttp(OneBot v11) 适配器已连接」。

## D-004 模型可切换：多 Provider + 会话级 /provider、/model

- **日期**：2026-10-24
- **背景**：用户明确要求「能更换各种模型」，不绑定单一厂商。
- **决策**：
  - Provider 配置采用 v5 结构：`provider_sources`（连接/凭据）+ `provider`（模型实例）；
  - API Key 不落盘到配置文件，使用 `$ENV_VAR` 引用（如 `$DEEPSEEK_API_KEY`），由 `.env` 注入；
  - 新增 OpenAI 兼容 provider 只需在 WebUI 添加 source 并填 key；
  - 会话内切换使用内置 `/provider`、`/model` 指令（管理员），按会话持久化；默认模型由 `agent_runner.config.model.provider_id` 控制。
- **理由**：生态内已有成熟机制，避免自研模型路由；满足多模型、按群切换的长期需求。
- **风险**：`/provider`、`/model` 为管理员指令，普通群友不可用（符合防滥用预期）；模型能力差异会影响群聊表现，需要固定默认模型 + 手动切换。
- **验证**：配置多个 provider 后 `/provider` 列表可见、切换后回复模型变化。

## D-005 部署：Windows 本地验证 → Linux VPS Docker Compose

- **日期**：2026-10-24
- **背景**：本机为 Windows 且不能常驻；长期服务需放 VPS。
- **决策**：本机用 `uv tool install astrbot` + 既有 NapCat.Shell 验证；VPS 用 Docker Compose（AstrBot + NapCat sidecar，`./data` 挂载）。仓库内 `deploy/windows/` 与 `deploy/linux/` 分离部署资产。
- **理由**：AstrBot 官方推荐 NapCat sidecar 的 Compose 部署；数据目录可整体迁移；避免在 VPS 手工维护 Python 环境。
- **风险**：换机登录可能触发设备验证；Windows 与 Linux 的 NapCat 版本/配置差异；VPS 资源（内存/CPU）。
- **验证**：VPS 上 docker compose 启动后群聊可用、重启自愈、数据持久化。

## D-006 数据与密钥管理：data/ 全量 gitignore，密钥走 .env

- **日期**：2026-10-24
- **背景**：AstrBot `data/` 包含 WebUI 密码哈希、JWT secret、聊天记录 DB、插件数据；NapCat 配置包含 WebUI token 与 QQ 登录态。
- **决策**：仓库只提交代码/配置模板/文档；`data/`、`.astrbot`、`.env` 全部 gitignore；密钥以环境变量注入（provider key 使用 `$VAR` 引用）。VPS 迁移时通过加密传输整体迁移 `data/`。
- **理由**：避免密钥/隐私进 git；配置可整体迁移，不需要在 VPS 重建。
- **风险**：`data/` 丢失等于配置/记忆全丢 → 需要备份脚本与迁移清单（已补 `scripts/backup_data.py` 与 `docs/migration-vps.md`）。
- **验证**：`git status` 不含 `data/` 与 `.env`。

## D-007 VPS 部署拓扑：仓库根 Compose、镜像锁定、WebUI 只绑本机

- **日期**：2026-10-24
- **背景**：本机不能常驻，最终要跑在 Linux VPS；需要可重复、可回滚的部署方式。
- **调查**：AstrBot 官方 Docker 文档 + NapCat-Docker 的 `compose/astrbot.yml` 模板（NapCat 容器 `MODE=astrbot` 会基于 `/app/templates/astrbot.json` 生成 `onebot11.json`，反向 WS 指向 `ws://astrbot:6199/ws`）。
- **决策**：
  - Compose 放在仓库根 `docker-compose.yml`，`name: qqbot`；
  - 镜像锁定 `soulter/astrbot:v4.29.1`、`mlikiowa/napcat-docker:v4.18.41`（与已验证版本对齐）；
  - AstrBot WebUI `6185`、NapCat WebUI `6099` 均只绑定 `127.0.0.1`，通过 SSH 隧道访问；`6199` 不对外发布，只在 `qqbot_net` 内部通信；
  - AstrBot 数据沿用 `./data`（与 Windows 同名目录，整体迁移）；NapCat 状态放 `./runtime/napcat`、`./runtime/ntqq`；
  - 密钥统一放仓库根 `.env`（Windows 启动脚本与 compose 共用）。
- **放弃**：在 VPS 上重新初始化 AstrBot（密码/JWT/会话/聊天记录会丢）；把 WebUI 直接暴露公网（风控与安全风险）。
- **风险**：换机登录触发设备验证；QQ 自动升级导致 NapCat 版本不匹配（见 D-008）；国内 VPS 拉取 Docker Hub 镜像可能需代理。
- **验证**：`docker compose config` 通过；`up -d` 后 AstrBot 日志出现适配器连接、WebUI 经隧道可访问；`restart: unless-stopped` 自愈。

## D-008 NapCat 版本必须匹配 QQ 版本（本地升级 4.18.28 → 4.18.41）

- **日期**：2026-10-24
- **背景**：本地 QQNT 已自动升级到 `9.9.32-51246`，而 NapCat 4.18.28 启动后报
  `PacketBackend 不支持当前QQ版本架构：9.9.32-51246-x64` 与 `NativePacketClient: 未找到对应版本的偏移数据`。
  虽 `send_private_msg` 当时仍返回成功，但 Packet 后端不可用意味着群消息、媒体、部分 API 的可靠性存疑。
- **调查**：NapCat GitHub releases——
  - `v4.18.34` 发布说明明确「补齐 Windows QQ **9.9.32-51246、9.9.33-51802（x64）** 的兼容映射」；
  - 最新版 `v4.18.41`（2026-10-21），Docker Hub 有对应镜像 tag。
- **决策**：
  - 本地把 NapCat 升级到 **v4.18.41**（保留 `config/`，旧安装备份在 `D:\Apps\NapCat.bak-20261024-165715`）；
  - VPS 固定 `mlikiowa/napcat-docker:v4.18.41`；
  - 以后 QQ 自动更新后若再出现 Packet/偏移告警，先查 NapCat release 的兼容表，再升级 NapCat。
- **风险**：NapCat 升级会改变设备指纹/登录态，快速登录（`-q <uin>`）提示「登录需要手Q验证」，需回退扫码；QQ 自动更新可能再次超出兼容范围。
- **验证**：升级后日志 `[PacketHandler] 初始化成功`、无 `PacketBackend 不支持`；登录 + 发送消息实测通过（本次升级前已实测私聊发送成功，升级待重新扫码后复测）。

## D-009 群聊「陪聊/整活」初始策略：内置能力优先，插件后置

- **日期**：2026-10-24
- **背景**：目标是群聊里像群友一样陪聊/整活，需要人设、触发方式、上下文和防刷屏；但不能一上来堆插件导致难排查。
- **调查**：AstrBot 内置 `provider_ltm_settings`（`group_icl_enable` 群聊上下文注入、`active_reply` 概率主动回复、`group_message_history_enable` 历史持久化）+ `platform_settings.segmented_reply`（分段回复）+ 内置限流；社区有 `smart_wake` 等两级漏斗主动插话插件。
- **决策**（初始值，均在 `scripts/bootstrap_astrbot_config.py` 中幂等写入）：
  - 人设用 `example`（短句、口语、群友感、不 AI 腔），定义在 `config/personas/example.json`；
  - 群聊上下文：`group_icl_enable=true`、`group_message_max_cnt=200`、`group_message_history_enable=true`；
  - 主动插话：`active_reply.enable=true`、`method=possibility_reply`、概率 **3%**、白名单留空（测试群确定后填群号）；
  - 分段回复：开启，阈值 150 字、间隔 1.5–3.5s（像真人补话）；
  - 限流：60s / 20 条兜底；内容安全内置关键词保持开启。
- **理由**：全部复用内置能力，零额外依赖、可单独关闭、调参维度清晰；先跑通再按症状加插件（表情包、戳一戳、smart_wake）。
- **放弃**：首版直接上 `smart_wake`（多一层模型判定与配置，增加调试变量）；自写主动插话插件（无必要）。
- **风险**：3% 是全局概率，多群时会到处插话——先低概率并尽快填白名单；ICL 注入增加 token 成本；人设是否「像群友」需实群迭代。
- **验证**：见 `docs/group-chat-tuning.md` 验收清单；AstrBot 重启日志已确认 `Loaded 2 personas` 与 `Segmented-reply interval: [1.5, 3.5]`。

## D-010 多模型接入：DeepSeek 官方 + OpenAI 兼容聚合端点（密钥走环境变量）

- **日期**：2026-10-24
- **背景**：用户明确要求「能更换各种模型」，提供了两个凭据：DeepSeek 官方 key、以及一个 OpenAI 兼容聚合端点（`https://<GATEWAY_HOST>/v1`，提供 gemini/claude/gpt 共 5 个模型）。
- **决策**：
  - `provider_sources` 配两个 source：`deepseek_source`（api.deepseek.com）与 `multi_source`（聚合端点）；
  - 聚合端点注册 5 个 provider：`gemini-3.8-flash`、`claude-sonnet-4-6`、`claude-opus-4-6`、`gpt-6-astra`、`gpt-6.1-sol`；
  - 默认模型仍为 `deepseek-chat`（便宜稳定），其余按会话用 `/provider`、`/model` 切换；
  - 所有 key 以 `$DEEPSEEK_API_KEY` / `$MULTI_API_KEY` 引用，实际值只在 gitignored `.env`；
  - 新增 `scripts/smoke_llm.py`：经 AstrBot WebChat 全链路验证任意 provider（登录→建会话→SSE 流式回复）。
- **理由**：复用 AstrBot 多 provider 机制，零自研路由；一个聚合 key 覆盖多家模型；默认模型与实验模型分离，避免群聊被不稳定端点拖累。
- **放弃**：只接一个模型（不满足需求）；key 写进 `cmd_config.json`（配置易被备份/提交泄漏）。
- **风险**：第三方聚合端点的稳定性与隐私（请求经第三方转发），敏感对话不应走该端点；密钥曾出现在对话和 QQ 消息中，**建议使用一段时间后轮换**。
- **验证**：AstrBot 启动日志成功加载 6 个 provider 并选中 deepseek 为默认；`smoke_llm.py` 实测 `deepseek`、`gemini-3.8-flash`、`claude-sonnet-4-6` 均返回人设化回复（无报错）。
