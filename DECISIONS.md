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

> **已更新（2026-10-24）**：用户明确 VPS 内存/磁盘紧张且要跑编译，Docker 方案被否决；
> VPS 部署改为**原生 systemd**，见 D-011。Docker Compose 仅保留为可选 fallback。

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

> **已更新（2026-10-24）**：Docker 方案被否决（内存/磁盘/编译需求），当前部署方式为
> 原生 systemd（D-011）。本条的 Compose 细节仅作为可选 fallback 保留。

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
- **验证**：AstrBot 启动日志成功加载 6 个 provider 并选中 deepseek 为默认；`smoke_llm.py` 实测全部 6 个 provider
  （deepseek / gemini-3.8-flash / claude-sonnet-4-6 / claude-opus-4-6 / gpt-6-astra / gpt-6.1-sol）均返回人设化回复（无报错）；
  同会话多轮追问实测记忆生效。

## D-011 VPS 改为原生 systemd 部署（不使用 Docker）

- **日期**：2026-10-24
- **背景**：原计划（D-005/D-007）用 Docker Compose 部署到 Linux VPS。用户明确：
  - VPS **内存/磁盘紧张**，且**有时要在上面跑编译**，Docker 守护进程 + 镜像（AstrBot ~1 GB、NapCat ~1 GB）占用不可接受；
  - VPS 在**海外**（QQ 协议端登录风控风险更高）。
- **调查**：
  - AstrBot 官方提供 uv 安装 + systemd 用户服务方式，适合裸机部署；
  - NapCat Linux 有两条原生路径：`napcat-linux-installer`（在已装 QQ Linux 上非侵入安装）
    与 **NapCatAppImageBuild**（QQ + NapCat 打包成 AppImage，需 `xvfb-run`/`xauth`，可用
    `--appimage-extract-and-run` 免 FUSE）；当前版本 `v4.18.41`（内含 QQ build 53644，约 300 MB）；
  - Lagrange V2 已不再支持 OneBot 11、V1 实现不再维护，不能作为更轻量的替代；
  - Docker 方案保留为可选 fallback（`deploy/linux/docker-compose.yml`）。
- **决策**：
  - AstrBot：`uv tool install astrbot --python 3.12`，systemd 系统服务 `qqbot-astrbot`，
    `MemoryMax=600M`、`Nice=10`、`CPUWeight/IOWeight=50`；
  - NapCat：AppImage + `xvfb-run`，systemd 服务 `qqbot-napcat`，`MemoryMax=1100M`；
  - 两个服务均 `Restart=always`，WebUI 仅监听 `127.0.0.1`，只经 SSH 隧道访问；
  - 迁移仍整体搬运 `data/`；VPS 上重新扫码登录（海外 IP 可能触发手机验证）。
- **理由**：无 Docker 守护进程/镜像开销；systemd 自带重启、日志（journald）与内存上限；
  资源紧张时可 `systemctl stop` 两个服务让编译任务独占内存。
- **放弃**：Docker Compose（资源开销）；Lagrange（OneBot 11 已停维护）；继续 Windows 常驻（本机不能常驻）。
- **风险 / 待验证**：
  - **内存实测（2026-10-24，Windows 本地）**：AstrBot（python）RSS ≈ 264 MB；QQ 相关进程合计 RSS ≈ 1.8 GB（Electron 多进程）。
    推算 Linux 上 NapCat + AstrBot 合计约 1–2 GB，**2 GB VPS 会非常紧张**；建议 ≥4 GB VPS，或退回官方 QQ 机器人方案（无客户端、轻量但能力受限）。
    未在目标 VPS 实测，需按实测调 `MemoryMax` 并配 swap；
  - AppImage 的配置目录路径（推测 `/opt/napcat/config`）与快登/扫码流程需在 VPS 上实测确认；
  - 海外 IP 的 QQ 风控是方案级风险，无法完全消除。
- **验证**：`deploy/linux/native/` 下的 README 与 systemd 单元为待执行清单；
  在 VPS 上完成扫码 + `journalctl` 出现「适配器已连接」后回填实测数据。
- **代码位置**：`deploy/linux/native/`、`docs/migration-vps.md`、`deploy/linux/README.md`。

## D-012 上下文 / 多模态 / 联网搜索 / Skill 与插件体系

- **日期**：2026-10-24
- **背景**：用户下一阶段方向是「上下文管理、多模态、联网搜索这一类」，并计划自己编写 Skill；
  要求不碰核心（D-002），实现尽量复用 AstrBot 已有能力。
- **调查**：
  - AstrBot 内置联网搜索工具（`web_search_deepseek` → `https://api.deepseek.com/v1/tools/search`、
    `deepseek_fetch_web_page`），激活条件 `provider_settings.web_search=true` + `websearch_provider=deepseek`，
    可复用现有 DeepSeek key，无需第三方搜索服务；功能工具里还有 `get_group_message_history`（群上下文）、
    `send_message_to_user`（主动消息）；
  - 多模态：`default_image_caption_provider_id` + `provider_ltm_settings.image_caption` 可用视觉模型给图片生成描述，
    让文本模型（deepseek）也能"看图"；
  - Skill：标准 `SKILL.md`（YAML frontmatter 仅 `name`/`description`，兼容 Codex/Claude），
    本地技能目录 `data/skills/<name>/`；仓库可版本化 `skills/`；
  - 插件层：`@filter.on_decorating_result()` 可在发送前改结果链，适合剥离 `<ref>` 标记。
- **决策**：
  - 联网搜索：`websearch_provider=deepseek`、`web_search_link=true`，WebChat 实测通过；
  - 多模态：`default_image_caption_provider_id=gemini-3.8-flash`、群聊 `image_caption=true`（视觉输入直连验证通过）；
  - Context：群聊 ICL 200 条 + `get_group_message_history` 工具 + AstrBot 自动上下文压缩；主动插话保持关闭；
  - Skill：仓库 `skills/` + `scripts/install_skill.py` + 示例 `web-lookup` + 指南 `docs/skills-dev.md`；
  - 插件：仓库 `plugins/` + `scripts/install_plugin.py` + `astrbot_plugin_strip_refs`（`on_decorating_result` 剥离 `<ref>`）。
- **理由**：全部走 AstrBot 既有工具/生命周期，核心零修改；Skill 与插件作为可版本化资产，便于 review 与迁移 VPS。
- **放弃**：自建搜索代理（DeepSeek 搜索 key 已够用）；改核心去掉 citation prompt（插件层可解决）；开 sandbox（内存不够）。
- **风险 / 临时 workaround**：
  - AstrBot 的 `websearch_deepseek_key` **不支持 `$ENV` 引用**，bootstrap 只能把实际 key 写入 gitignored 的
    `data/cmd_config.json`（provider key 仍走 `$ENV`）。**移除条件**：AstrBot 支持 websearch key 环境变量引用后改回。
  - `<ref>` 剥离只在**非流式**发送路径生效（stage 注释明确流式下插件可能不工作）；QQ/OneBot 是非流式，符合预期；
    WebChat 流式测试仍会看到 `<ref>`。
  - 图片 caption 会额外消耗视觉模型 token；sandbox 工具（shell/browser）在 `computer_use_runtime=none` 下不可用，
    Skill 只能依赖内置 function tools。
- **验证**：
  - 直接 `POST api.deepseek.com/v1/tools/search` 返回结果；WebChat 问答能引用 2026-04-24 等新信息；
  - 聚合端点视觉输入直连返回图片描述；
  - `GET /api/v1/skills` 列出 `web-lookup`；`find` 安装脚本幂等；
  - 非流式 WebChat 回复中不再出现 `<ref>`（3 次查询验证）。
- **代码位置**：`scripts/bootstrap_astrbot_config.py`、`skills/web-lookup/`、`plugins/astrbot_plugin_strip_refs/`、
  `scripts/install_skill.py`、`scripts/install_plugin.py`、`docs/skills-dev.md`。

## D-013 记忆本子：memory_beyond（Chatbox 式事实记忆的加强版）

- **日期**：2026-10-24
- **背景**：用户希望「模型自己有一个本子，记住认识的人的关键信息」，同时上下文管理要省 token。
- **调查**：
  - Chatbox 1.23 Memory 的实现（源码 `agent-memory.ts` / `agent-persona.ts`）：事实条目
    `{id, content, createdAt}`，单条 ≤1000 字符、注入总量 ≤8000 字符；模型用 `save_memory`/`delete_memory`
    工具自写；Global vs Copilot 两种作用域；会话开始时冻结快照（利于 prompt cache）；设置页可审阅/删除；
    不是 RAG。
  - 候选插件：memory_beyond（MIT、无第三方依赖、AstrBot>=4.5.7、v1.3.7、数据为 Markdown 文件、
    索引式注入 + 自带压缩 + people/global/session 作用域 + 管理页）、memory_companion（陪伴导向，重，许可待确认）、
    self_learning（风格学习 AGPL，另作 D-015）。
- **决策**：安装 memory_beyond 固定提交 `0ec75bf…`；人物记忆开（按 QQ 号锚定、跨会话），全局记忆先关；
  recall 最多 3 条；摘要用 `gemini-3.8-flash`、整理用 `claude-sonnet-4-6`；压缩阈值 0.70，并关闭 AstrBot
  内置压缩（`fallback_max_tokens=1e9`、`max_turns=-1`）与身份标注（`identifier=false`）。
- **理由**：与 Chatbox 一样「事实级、模型自写、可审阅」，但用文件+索引+按需召回，长会话更省 token；
  MIT 无依赖，风险可控；人和事的 markdown 文件可手工改、可迁移、可备份。
- **放弃**：memory_companion（复杂/许可）；自研（重复造轮子）；只做全局记忆（易被群友污染）。
- **风险**：插件较新（4 stars）、接管压缩可能配置冲突；人物记忆跨群可见带来隐私问题；记忆注入本身有 token 成本。
- **验证**：见 A-11；私聊写事实 → `/reset` → 追问能回忆；`/mb_status` 正常；记忆文件在
  `data/plugin_data/astrbot_plugin_memory_beyond/memories/`。

## D-014 文件工具：本机 runtime 只开放 workspace（读 QQ 发来的文件）

- **日期**：2026-10-24
- **背景**：用户明确要的是「发给 bot 的文件它能读」，不是读本机任意路径。
- **调查**：AstrBot 收到 File 消息会下载到 `data/temp`，并把
  `[File Attachment: name ..., path ...]` 注入模型；`astrbot_file_read_tool` 仅在
  `computer_use_runtime=local/sandbox` 时挂载，workspace 权限允许读 `data/temp`、`data/skills`、
  会话工作区，支持 txt/图片/PDF/docx/epub（本地 markitdown）；`allow_execution=false` 时无需
  bubblewrap 隔离。
- **决策**：`computer_use_runtime=local`；member/admin 都 `filesystem_scope=workspace`、
  `allow_execution=false`、`allow_network=false`。不开放 host、不执行 shell。
- **理由**：只满足「读收到的文件/技能」需求，攻击面小；同时修复了一个隐藏问题——此前 Skill 只有
  description 进 prompt、模型读不到 `SKILL.md`，技能实际不生效。
- **放弃**：admin `filesystem_scope=host`（能读 data/ 下密钥，风险大）；自定义白名单只读插件（多写一层）。
- **风险**：workspace 内仍可读技能/插件/临时文件；模型可能被诱导读取无关临时文件（权限仅限 workspace）。
- **验证**：WebChat 实际读取 `data/temp/qqbot-test-file.txt` 成功；读取 `D:\qqbot\PROJECT.md` 被权限拒绝；
  `astrbot_file_read_tool` 出现在工具列表。

## D-015 Skill 教学与人味：先评测集 + few-shot，微调后置

- **日期**：2026-10-24
- **背景**：用户要学做 Skill，并让 AI 更有人味；询问语料数据集是否有用。
- **决策**：
  - 交付 `docs/skill-tutorial.md`（三课 + 练习 + 检查表）、`docs/corpus-and-style.md`、示例
    `skills/style-humanizer`；Skill 通过 `skills/` + `install_skill.py` 版本化管理；
  - 人味路线：先 **评测集（30–50 条）+ few-shot（20–40 条，放技能 references 按需读）**，
    再考虑 `self_learning`（AGPL，自动风格/黑话/关系学习），最后才微调（≥500–1000 条干净授权样本）；
  - 语料用 `qq-chat-exporter` 导出，本地清洗、脱敏、不入库；群聊语料需授权。
- **放弃/后置**：立刻微调（成本/隐私/维护高）；直接上 self_learning（复杂 + AGPL）。
- **风险**：语料涉及他人隐私；few-shot 会占 token；人评主观。
- **验证**：教程可执行；`style-humanizer` 已安装并出现在 skills 列表；评测流程可复用 `eval_persona.py`。

## D-016 Token 策略与实测

- **日期**：2026-10-24
- **背景**：ICL 200 条 + 历史是固定开销；需要量化省 token 而不是拍脑袋。
- **决策/实测**：
  - ICL 200 → **100**（约省一半群消息注入）；
  - 压缩交给 memory_beyond（0.70 触发、摘要 gemini-flash、摘要 ≤1500 字、recall ≤3 条）；
  - 新增 `scripts/context_report.py`（按会话 token_usage + 记忆目录占用）做基线/对比；
  - 试过 `tool_schema_mode=skills_like`：工具声明 4110 vs 4066 tokens，**无收益**且多一次二阶段调用，
    已回退 `full`；
  - 当前单轮固定开销实测：约 7.8k tokens（固定开销 ~3.7k + 工具声明 ~4.1k + 记忆/历史）；
    DeepSeek 有 prompt cache 命中（`/mb_status` 显示缓存命中 ~7k），实际成本显著低于全价。
- **后续可选**：减少工具数量（自定义只读文件工具替代 local runtime）、关闭未用 builtin skills、
  按群配不同模型/上下文。
- **风险**：ICL 降低可能影响接梗；需群聊实测回归。
- **验证**：`/mb_status` 分项、`context_report.py` 输出、健康检查。
