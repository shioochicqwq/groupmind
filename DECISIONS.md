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

## D-017 网页读取：自研 `web_reader` 插件（本地抓取 + 链接导航 + SSRF 防护）

- **日期**：2026-10-24
- **背景**：用户反馈模型「看网页很吃力，没读到想让它读的东西」。实测定位：
  - DeepSeek `fetch` 抓 `whatasiger.xyz` 首页只返回 130 字标题串、**不带任何链接**；
    抓 `/carrier_wave/` 只返回 344 字章节列表、也无链接；抓单篇文章能返回正文但混入 UI/评论；
  - `site:whatasiger.xyz` 搜索 **0 条结果**（个人小站未被收录）；
  - bot 对「看看这个网站」连续调 5 次 fetch 全 504 超时，最后只说「那我再瞅瞅」；
  - 本地 Python + BeautifulSoup 抓同一首页：**能拿到 10 篇文章链接**、文章正文 1474 字。
- **决策**：新增自研插件 `plugins/astrbot_plugin_web_reader`（仓库源码，安装到 data/plugins）：
  - 工具 `web_reader(url, offset, limit)`：本地 `requests` 抓 HTML → BeautifulSoup 提取标题/正文/全部链接；
    返回正文（可分段续读）+ 链接列表，模型可「首页 → 挑文章 → 读正文」；
  - SSRF 防护：仅 http/https，拒绝账号密码 URL；解析并拦截 localhost/私有/回环/链路本地/保留地址；
    手动跟随重定向并逐跳校验；限制响应大小（2.5MB）、超时、重定向次数；
  - 权限：**所有人可用**（用户决定）；失败时模型可自然推脱（网不好/等会儿），但不许编造；
  - `web_search_deepseek` 保留做搜索入口，`deepseek_fetch_web_page` 保留为 fallback。
- **理由**：根因是「没有链接 + 黑盒抽取 + 超时」；本地抓取能同时解决链接发现与内容获取，
  无需外部 key；属插件层扩展（D-002）。
- **放弃**：只改 prompt（解决不了链接/超时）；第三方 reader API（需 key/费用，JS 站后续再议）；
  无头浏览器（内存/依赖重，VPS 不现实）。
- **风险 / 限制**：
  - JS 渲染站、登录墙、强反爬页面仍可能拿不到正文；需要时再上第三方 reader（D 方案）；
  - 所有人群聊可用 → 抓取来源需遵守站点条款；已做 SSRF 防护，后续可加域名白名单/频率限制；
  - 工具声明增加少量 token（/mb_status 可看）；新增外部抓取行为，注意日志与隐私。
- **验证**：
  - 单元测试：`reader.validate_url` 拦截 `http://127.0.0.1`、`http://10.0.0.1`、`http://169.254.169.254`、`file://`；
  - 提取：首页 341 字 + 45 链接；文章 1474 字，`offset=600` 续读正常；
  - AstrBot WebChat 实测：「看看 carrier_wave 页面」能说清 18 篇目录；「看看网站挑一篇讲讲」
    能选中《Q君与世界的外侧》并概括内容（约四万字长文，模型自行分段读）。
- **代码位置**：`plugins/astrbot_plugin_web_reader/`、`skills/web-lookup/SKILL.md`、`scripts/install_plugin.py`。

## D-018 表情包：只收集/标注数据集，不发送（用户决定）

- **日期**：2026-10-24
- **背景**：用户希望处理群聊表情包，但明确「暂时让模型不发表情包」；真正需求是**收集表情包数据集并整理**，
  因为 AI 对表情包的理解很差（通用 image caption 只描述画面，不解释梗/情绪/文字/用法）。
- **调查**：
  - 收：NapCat 把 QQ 表情包以 `image` 消息段上报（子类型/`[动画表情]`），AstrBot 当图片处理；已启用
    `gemini-3.8-flash` caption；少数 `mface` 段会被 AstrBot 适配器跳过；
  - 发：`send_message_to_user` 可发图片但仅限 workspace/temp；要发表情包需图库+工具或 QQ 原生 mface
    （需 emoji_id/package_id/key，NapCat 无导出收藏表情接口）；
  - 生态：`astrbot_plugin_stealer`（AGPL，76★，活跃）能偷图+分类+按情绪自动发+LLM 工具，但自带发送能力；
    `smart_imagechat_hub`（GPL，35★）更重；两者都不适合「只收集不发送」。
- **决策**：自研 `plugins/astrbot_plugin_sticker_collector`（只采集，无 LLM 工具、无发送）：
  - 从 raw OneBot image 段读 `sub_type/summary` 判定候选；只收候选/GIF，收到即下载去重；
  - 数据集 `data/sticker_dataset/`（inbox/images/rejected/labels.jsonl/review.csv/stats.json）；
  - 标注脚本 `scripts/label_sticker_dataset.py`（gemini 视觉 + 固定 taxonomy），
    统计/复核 `scripts/sticker_dataset_report.py`，评测 `scripts/eval_sticker_understanding.py`；
  - 附带改进：`image_caption_prompt` 改为表情包感知；人设要求「理解表情包但不发表情包」。
- **放弃**：装 stealer 只采集（自带发送工具/AGPL/较重）；QQ 原生 mface（不可行）；微调（数据集先做标注/评测）。
- **风险 / 限制**：
  - 群友表情包隐私/版权：仅本地、ID 哈希、不公开、可删除；
  - `mface` 段被 AstrBot 跳过时采集不到（已知限制）；
  - VLM 标注成本/错误：小批量 + 人工复核 + 可迭代 taxonomy；
  - 普通照片误收：只收有 sticker 信号/GIF，人工审核。
- **验证**：
  - store：`has_sticker_signal` 正确、sha256 去重生效；
  - 用示例图跑标注：得到 `caption/emotion/intent/character/usage`（初音玩偶 → 委屈/生气）；
  - report 生成 `stats.json`/`review.csv`；eval 能输出 generic vs sticker-aware 的 emotion/intent 分数；
  - AstrBot 启动加载插件、创建数据集目录；healthcheck 通过。
- **代码位置**：`plugins/astrbot_plugin_sticker_collector/`、`scripts/label_sticker_dataset.py`、
  `scripts/sticker_dataset_report.py`、`scripts/eval_sticker_understanding.py`、`docs/sticker-dataset.md`。

## D-019 换机迁移：安全分层打包与网盘中转策略

- **日期**：2026-10-31
- **背景**：开发机无法常驻，用户需将项目打包上传至 Google Drive 网盘，后续下载至新设备恢复运行。
- **调查与约束**：
  - 密钥安全：`.env` 与 `data/cmd_config.json` 包含 API key，绝不能上传网盘；
  - 存储体积：`tmp/` 曾含旧安装包（140+ MB），`backups/` 含历史及旧工程，直接整包压缩体积巨大且混杂无关文件；
  - 依赖与状态：AstrBot 插件（如 memory_beyond）及本地配置均可通过脚本幂等重建，无需拷贝含有本地绝对路径与 DB 的 `data/` 全量目录；
  - 数据集与记忆：用户收集的表情包数据及 Markdown 记忆为劳动成果，需要可选迁移，但应与源码解耦并防泄漏。
- **决策**：
  - 源码包（`qqbot-source-YYYYMMDD.zip`）：仅打包 tracked 文件与完整 `.git` 历史，包含恢复清单与 SHA256 校验；严格排除所有临时文件、备份、运行数据与密钥；
  - 数据包（`qqbot-data-bundle-YYYYMMDD.zip`，可选）：仅打包 `sticker_dataset`、`plugin_data`（记忆文件）等非密钥数据，不含 `cmd_config.json` 与聊天数据库；
  - 清理本地 `tmp/` 无关大文件缓存；
  - 提供自动化打包脚本 `scripts/package_transfer.py` 和恢复文档 `docs/transfer-to-new-machine.md`。
- **验证**：运行打包脚本生成 source 与 data 两个 zip 包，校验文件结构、解压合并路径与 SHA256 哈希。
- **代码位置**：`scripts/package_transfer.py`、`docs/transfer-to-new-machine.md`。

## D-020 换机后以 Drive 源码包为开发仓库，聊天记录样本暂不下载（用户决定）

- **日期**：2026-11-01
- **背景**：新机器上已初始化 `qq-bot` 仓库（3 个文档提交），Drive 上另有按 D-019 打包的项目仓库（21 个提交），两者历史无共同祖先。
- **约束**：
  - 新机器的会话与 `claude remote-control` 绑定在 `/home/<user>/projects/qq-bot`，路径不能变；
  - `qqbot/qqnt_export_work/` 已枚举部分超过 3.2 GiB 且未枚举完，当时本机磁盘仅剩 5.7 GB；
  - 该目录从文件名看含聊天记录、数据库与密钥文件（内容未打开，属推测）。
- **决策**：
  - 以 Drive 源码包历史作为 `master`，旧历史保留为分支 `legacy/bootstrap`，不合并两段无关历史；
  - 文档沿用本仓库的 `AGENTS.md` 与 `A-N` / `D-N` 记录方式，旧仓库的 `EVT-*` / `DEC-*` 不再使用；
  - `qqnt_export_work/` 暂不下载；用户计划将其作为项目研究测试样本，使用方式待定。
- **放弃的方案**：
  - 保留旧仓库再逐步合入 Drive 内容：旧仓库只有规范文档，没有需要保留的代码；
  - 删除旧目录后整体覆盖：需要删除操作，而切换分支可达到同样结果并保留旧历史。
- **风险**：仓库没有 Git 远端，`legacy/bootstrap` 与切换前的备份都只存在于本机。
- **验证**：SHA256 校验、`git fsck`、`git status` 与逐文件对比；项目运行未验证。

## D-021 协议端改用 SnowLuma，部署目标改为常驻 Windows PC（用户决定）

- **日期**：2026-11-01
- **取代**：D-001 中的 NapCat 选型、D-008（NapCat 版本匹配）、D-003 中的 NapCat 客户端部分；部署目标取代 D-005 / D-007 / D-011。历史条目保留不改。
- **背景**：用户决定弃用 NapCat、改用 SnowLuma；此前的开发机内存不足以再跑 QQ（可用约 1.4 GiB、swap 已满），未来部署到一台常驻 Windows PC。当前只准备配置，不部署。
- **调查**（均针对 2026-11-01 的 SnowLuma v2.3.3 源码、官方文档和 AstrBot v4.29.1 源码）：
  - 接入：AstrBot 官方支持任意 OneBot v11 反向 WS 协议端；SnowLuma 文档建议 AstrBot 用 `wsClients` 连 `/ws`；
  - 鉴权：SnowLuma 发 `Authorization: Bearer <token>`、`X-Self-ID`、`X-Client-Role`，与 aiocqhttp 的校验逻辑匹配；
  - 插件：表情包采集依赖的图片段 `sub_type` / `summary` 在 SnowLuma 输出中存在；
  - **文档与源码不一致，以源码为准**：`hookAutoLoad` 默认 `false`（Windows 文档称默认开启）；非 Docker 默认监听 `127.0.0.1`（配置文档写 `0.0.0.0`）；发行包是 `.zip`（文档写 `.tar.gz`）；
  - `compat/qq.json` 的 `knownGoodVersions` 为空，官方没有给出已验证的 QQ 版本。
- **决策**：
  - 拓扑：AstrBot 与 SnowLuma 同机，SnowLuma 经 `wsClients` 连接 `ws://127.0.0.1:6199/ws`；
  - 收窄暴露面：AstrBot 反向 WS 改听 `127.0.0.1` 并启用 token（旧配置是 `0.0.0.0` 且无 token）；关闭 SnowLuma 默认 `ws-default`；HTTP 3000 只听回环、带独立 token，仅供体检；
  - 显式设置 `hookAutoLoad=true`，否则重启后不自动注入；显式关闭 `statusCommand`（默认任何人发 `#sl` 都可能触发状态回复）；
  - 配置写全局 `config/onebot.json`，由 `scripts/configure_snowluma.py` 生成，避免手填；
  - 版本先钉 SnowLuma v2.3.3 + 关闭 QQ 自动更新，验收后记录可用的 QQ 版本；
  - 平台 id 由 `napcat` 改为 `snowluma`。代价是旧会话键失效，但目标机器是全新数据目录，bundle 里只有少量 `napcat_FriendMessage_*` 状态受影响；
  - EULA 确认留给运营者在首次启动时手动完成，不预设 `SNOWLUMA_ACCEPT_EULA`。
- **放弃的方案**：
  - 保留 NapCat：用户决定弃用；
  - 正向 WS（AstrBot 连 SnowLuma）：AstrBot 这条链路的现有配置和官方建议都是反向；
  - 计划任务以系统账户开机运行：SnowLuma 注入要求与 QQ 同用户、同权限，且 QQ 需要桌面会话，所以用登录时触发。
- **风险与限制**：
  - 许可：SnowLuma 是源码可见的非商业许可，不是开源；原生组件闭源。本项目须保持非商业使用；
  - 账号：EULA 写明使用非官方协议工具可能违反平台条款并带来账号风险，且第 4 条禁止违反所接入平台条款的用途，须由用户自行判断并承担；
  - 项目很新、发版频繁（2026-10-31 至 11-01 发了 4 个版本），升级前要验收；
  - 隐私政策称公开发行版截至 2026-06-17 未含遥测，但条款保留了默认开启的遥测机制，升级时需看发布说明；
  - 重启后 QQ 能否免扫码上线未验证（文档称登录只支持扫码）；若不能，常驻 PC 每次重启都需要人工扫码；
  - 与 D-019 相同，token 属于密钥，只放 `.env` 和被 gitignore 的目录，SnowLuma 的 `config/` 不进仓库。
- **验证**：配置脚本与 bootstrap 用临时副本测试通过；**SnowLuma 运行、QQ 注入、AstrBot 连接、QQ 收发、PowerShell 脚本均未验证**。
- **代码位置**：`scripts/configure_snowluma.py`、`scripts/bootstrap_astrbot_config.py`、`scripts/healthcheck.py`、`deploy/windows/`、`docs/transfer-to-new-machine.md`。

## D-022 长期记忆系统的方向与第一阶段范围（用户决定，设计待审阅）

- **日期**：2026-11-02
- **背景**：项目实际目标是让机器人成为有长期记忆和人物认知的群友，并以真实 QQ 聊天记录建立和测试记忆系统。
- **调查与依据**：见 `docs/memory-system-design.md` 第 3 节。
- **决策**：
  - 保留完整原始记录，派生记忆可追溯、可回滚；上色是核心设计，作为检索入口，分局部语境和长期话题两层；
  - 历史视为机器人潜水时全部读过；上线后未读的消息不算它知道；
  - 群友的话是数据，不是指令；删除请求只停止召回；
  - 第一阶段以离线评测通过为终点，不接入线上 QQ；
  - 批处理使用本机已有模型网关，渠道必须可替换。
- **放弃的方案**：
  - 让基线决定上色的去留：原文也要分块，单条消息难以有效索引，因此固定窗口只作对照。
- **验证**：尚无实现，方案未经实验验证。
- **代码位置**：`docs/memory-system-design.md`。

## D-023 持续知识习得与伪学习升级为核心方向（用户决定）

- **日期**：2026-11-02
- **修改**：扩展 D-022 的范围；此前调研报告中「伪学习不进入最小架构」的结论不再成立，但其「机制需由实验决定」的部分保留。
- **背景**：基础模型缺少网络梗、内部梗和小圈子文化知识，用户要求机器人能发现、归纳、关联、修正、运用这些知识，并通过反馈和后台维护改进。
- **调查**：见 `docs/research/2026-11-knowledge-acquisition-survey.md`。未发现任何项目评测过学习后的实际运用。
- **决策**：
  - 第一阶段以离线方式评测知识习得，目标是在新对话中正确理解和运用；
  - 区分「出现过 / 推测含义 / 证据充分 / 掌握语境」，状态属于含义，不能由模型自我声明掌握；
  - 多 Agent、自反思、Notebook、定时心跳不预设，由对照实验和成本决定。
- **待审阅的提议**（尚未由用户确认）：梗复用上色结构；知识实验先于全量上色；保留只检索原文的对照组。
- **风险**：知识抽取可能不如直接检索原文；错误知识可能导致误用或冒犯；相关开源项目的许可证限制代码复用。
- **验证**：尚无实现，方案未经实验验证。

## D-024 记忆系统实验起点（用户决定）

- **日期**：2026-11-02
- **背景**：调研产生大量选项。用户决定保留记录，但起点用最初讨论 idea 时定的方案和用户选定的方案，调研项目的方案只作对照。
- **决策**：
  - 保留原文是为了喂给模型；上色既是索引，也是分块；第一层颜色是微语境；人物和时间是原文的元数据；
  - 各决策点的起点和对照以 `docs/memory-options.md` 为准；
  - 起点不为缓存和长度优化：自有记忆系统本来缓存命中率低，主模型上下文足够大，测试确实过大时再处理；
  - 代码放本仓库，清理后开源，公开前必须清除历史中的真实 ID；实现为 Python 服务 + 薄适配器。
- **放弃的方案**：由调研结果直接决定起点。起点不会因单项调研改变，只有 benchmark 证明不好时才更换。
- **风险**：
  - 主模型读每条消息都判断，模型调用量大；
  - 证据充分就能使用梗，早期误用率可能偏高；
  - ACT-R 降权可能自我强化；
  - 自我回顾的现有证据偏弱；
  - 代码与真实 ID 同仓，需防止公开前遗漏。
- **验证**：尚无实现。
- **代码位置**：`docs/memory-options.md`、`docs/memory-benchmark-plan.md`。

## D-025 benchmark 批量模型走本地模型网关（用户决定）

批量处理用本地模型网关 的 `gemini-3.8-flash-high`，判官用 `gpt-6.1-sol`，不用 Claude 模型；密钥运行时从本地服务读取，不写入仓库。真实聊天过滤后才外发，当前的高敏感词表是临时的，待用户定规则。

## D-026 打标页不额外化名外号、不扣健康内容（用户决定）

2026-11-03 用户决定：打标页沿用现有过滤，群友外号不另做化名，健康、用药相关消息也不扣下或遮盖。打标页仍属隐私内容，由用户决定发给谁。

## D-027 检索起点改为两路合并、交原文块（用户决定）

2026-11-03 用户决定：I3/I6 起点改为对颜色摘要和颜色原文块分别做关键词检索，用 RRF 合并，交给模型的是原文块。依据是两个开发群的主实验：这一组在 DEV-1、DEV-2 上都最好，比 10 条窗口基线高 9.8 和 13.3 个百分点；只给摘要最差。原起点「只搜颜色摘要」改为对照。见 `docs/memory-benchmark-results.md`。

## D-028 冻结当前检索版本：四路 RRF + 每路前 5 + 1500 字 + 原文块（用户决定）

2026-11-04 用户决定：起点改为四路检索，即颜色摘要和颜色原文块各做关键词（jieba + 习得词）和向量（`qwen3.7-text-embedding-flash`）检索。每路取前 5 个候选，用全局 RRF（k=60）合并，严格按名次装入 1500 字预算（按去重后实际注入的字数计算），不经筛选模型，交给模型的是原文块。这一版暂时冻结，作为当前版本。

- **依据**：两个开发群的候选深度实验。每路取前 3–10 个是一个平台，彼此差异都不显著；取 20 及以上明显变差，DEV-2 上显著。前 5 在两个群上都排第一或接近第一（82.7% / 70.6%，10 条窗口基线是 70.2% / 53.4%）。逐题看，候选越深，在多路都排得一般的块累加 RRF 分数，越会把只在一路排第 1 的证据挤出预算；前 3 又会丢掉一部分第 4–5 名的支持。
- **放弃的方案**：D-027 的关键词两路（每路 30 个）；每路预留预算（E3）和按长度贪心（E4），这两种实现偏向短块，丢掉了长证据块。
- **风险**：前 5 是在同一批 DEV 题上挑出来的，可能对开发集过拟合；DEV-2 的题没有人工复核；向量依赖云端接口。
- **验证**：方案冻结后，在独立 TEST 集上验证一次再定稿。
- **代码位置**：`bench/run_depth.py`、`bench/retrievers/packing.py`；结果见 `docs/memory-benchmark-results.md`「候选深度 K」。


## D-029 冻结版的向量改用正确配置 V2；保留 M1（用户决定）

2026-11-05 用户决定：冻结版的结构不变（四路 RRF、每路前 5、1500 字、交原文块、不筛选），两条向量路改用 V2，即 `qwen3.7-text-embedding-flash` 的正确调用方式：文档用 `text_type=document`，查询用 `text_type=query`，查询带检索指令。M1（同样配置，换用 `qwen3.7-text-embedding`）作为备选保留，不冻结。配置集中写在 `bench/frozen.py`。

- **依据**：
  - V2 是这个接口的正确用法。之前的 V0 没有区分查询和文档，也没有加指令，是 2026-11-04 审计发现的实现问题。
  - 检索层：V2 的向量原文路 R@5 在 DEV-1 上追平 BM25，在 DEV-2 上超过。
  - 问答层：端到端准确率 85.5% / 71.3%，冻结版原来是 82.7% / 70.6%；DEV-1 上显著。
  - 不换模型，没有额外成本。
- **M1**：问答层 84.8% / 73.4%，两个群合并后显著优于原冻结版（p≈0.03），但与 V2 的差异不显著，而且要换成更大的模型。等 TEST 验证后再决定。
- **历史数据口径**：2026-11-05 之前的所有实验都用 V0。旧结果保留不改，台账照旧记录 V0。需要比较的组，等额度充足时用 V2 补测（见路线图「更新三」）。在补测之前，**V2 与旧实验的比较只在问答层的这一组实验里成立**。
- **风险**：V2 的提升在 DEV-2 上不显著；检索指令是在 DEV 上写的，没有调过。
- **代码位置**：`bench/frozen.py`、`bench/run_embed_qa.py`；结果见 `docs/memory-benchmark-results.md` 最后两节。

## D-030 采用 SQLite；研究阶段不换关键词索引，上线时再换 FTS5（用户决定）

2026-11-05 用户决定：记忆系统采用 SQLite 存储，数据模型按 `docs/research/2026-11-memory-storage-design.md` 第 2 节设计。研究阶段要保证之前实验的可信度，所以：

- **研究阶段**：
  - `bench/` 继续用现有的内存 BM25（与 `rank_bm25` 同参数），以及 JSONL 和 JSON 文件，不换 FTS5。
  - 如果要把评测数据导入 SQLite，必须先证明等价：同一批题的检索结果和注入内容逐题相同，才可以改用库里的数据。
- **上线时**：关键词检索换成 FTS5，用「FTS5 找候选 + 现有公式打分」。在全部 876 题、两个索引上，这种方式的前 30 名与现有 BM25 完全相同（`tests/bench/test_fts5.py`）。如果改用 FTS5 自带的 bm25() 排序，就要当作新配置重新评测，因为它的前 5 名与基线只有 50–77% 的题相同。
- **风险**：研究阶段和上线时是两套存储，上线迁移可能引入不一致。迁移时，要在冻结题集上逐题比较检索结果。
- **代码位置**：`bench/retrievers/fts5.py`（只用于等价性验证，评测流程不用它）。
- **ID 对照**（用户补充）：研究数据迁入 SQLite 时，每个旧 ID 和新 ID 的对应关系单独写进一份文件 `qqbot-data/store/id_map.jsonl`，库里也存一份。2026-11-05 首次迁移两个 DEV 群，消息、颜色和 BM25 前 30 名全部逐条一致。见 `docs/memory-store-migration.md`。

## D-031 上色重叠去重：dedup-v1 和 merged-v1 都不采纳（用户叫停，2026-11-05）

> **状态：不采纳。** 用户看了结果后叫停，要求改用三方案离线实验（原方案 / 去重不合并但保留色块边界 / 分层）重新设计。冻结版继续用原始上色。下面保留当时的做法和结果，作为实验记录。

上色的批与批之间重叠 20 条消息，这些消息会被上下两批各上一次色，同一段语境因此出现两个相近的颜色。用户要求修正这个问题，并标明修正后的条件与之前的实验不同。

- **做法**：重叠区的消息只保留在前一批的匹配颜色里；后一批的颜色只剩重叠部分的，整块删掉（`bench/color_fix.py` 的 `dedup_overlaps`）。原始上色文件不动，修正后另存为 `colors.<模型>.dedup-v1.jsonl`。
- **依据**：重复上色基本消除（DEV-1 多色消息从 1,568 降到 16，DEV-2 从 4,217 降到 70）。用冻结版 V2 评测，端到端准确率为 84.8% / 70.2%，原始上色是 85.5% / 71.3%，差异不显著。
- **放弃的方案**：merged-v1（把重复的颜色合并），颜色变得太长，证据进入率显著下降 5.9 和 7.3 个百分点。
- **条件变更**：没有发生，冻结版仍用原始上色。台账里 `dedup-v1` 和 `merged-v1` 的行在「切块」一栏注明「与此前实验条件不同」，只作为实验记录。
- **未解决**：模型几乎不主动多色，颜色也不能跨批。需要改上色方式后重新上色，见结果文档。
- **代码位置**：`bench/color_fix.py`、`bench/frozen.py`、`bench/run_embed_qa.py`（`--colors-file`、`--experiment color_fix`）。

## D-032 冻结版采用 B：重叠去重、不合并、保留色块边界（用户决定，2026-11-05）

- **做法**：
  - 色块边界和注入单元保持原始批次色块不变。
  - 建索引时，重叠区的每条消息只计入一个色块，即前一批的匹配色块（B-index）。
  - 每路候选中，消息全部已经出现在更靠前的块里的块，跳过并往下补位（B-route）。
  - 任何消息都不会因此丢失。实现见 `bench/run_color_layers.py`，配置记在 `bench/frozen.py`。
- **依据**：三方案离线实验（只测检索层，结果文档「重叠重复与分层」一节）。B 相对原方案 A 的证据进入率为 −0.5（DEV-1，CI −1.8～+0.7）和 −0.5（DEV-2，CI −2.1～+1.1），不显著；B 修正了重复上色这一数据缺陷。分层方案 C 没有改进；合并方案 merged-v1 显著变差（D-031）。
- **条件变更**：此前的所有实验都用方案 A。B 与它们条件不同，需要比较时应在 B 上补测。
- **未测**：B 的问答层准确率。等额度充足时，和 V2 补测一起做。
- **研究发现**：本研究发现，LLM 批次上色过程实际表现出近似单标签的局部语义分段特征。其检索效果主要依赖局部片段结构，而非跨批次重复标注。将局部片段合并为全局长块会显著降低证据注入率，而对重复进行去除、保留局部边界的方案未观察到明确的性能损失。这提示语义主题组织与证据检索单元应分别设计和评估。


## D-033 梗表分两层：通用梗跨群共享，本群梗只留在本群（用户决定，2026-11-05）

- **做法**：上线时梗表分两层。
  - **通用层**：通用网络用语、圈子里的通用说法、药名缩写等，所有群共用一份，从各群合并而来，同一写法只存一条，证据可以来自任何群。
  - **本群层**：某个群特有的梗、外号，只属于这个群，不与其他群合并，也不进通用层。
  - 同一写法两层都有时，检索时本群层优先，因为本群用法会覆盖通用含义。
- **依据**：第一轮人工打标（结果文档「梗表与人物：第一轮人工打标」）。机器梗表 33 条里 26 条是通用词，本群梗 0 条。通用词本来就跨群成立，按群分开存是重复劳动，也让每个群都要重新学一遍。
- **对评测的影响**：
  - 「本群梗 0 条」不再算梗表的失败。通用词进通用层，照样有用。
  - 本群梗另算，主要漏在证据门槛那一步，要单独改、单独测。
  - 打标页的「类型」题直接对应分层：本群梗、外号进本群层；通用、口头禅进通用层。
- **存储**：`term.chat_scope` 为空表示通用层，为群 ID 表示本群层。研究用的 `bench/store/schema.sql` 目前按群存（`chat_id NOT NULL`），等建通用层时再改，并在 id 对照文件里记下变动。
- **未决**：
  - 「圈子通用」（同一批成员的几个群共用，但不是全网通用）要不要再单独一层，先归入通用层，看打标结果再定。
  - 通用层的含义可以借助模型本身的常识，本群层不行，两层的入表门槛可能要分开设。

> **D-032 补记（2026-11-06）：B 正式接入主管线。** 此前 B 只在离线实验脚本里实现，冻结配置虽写着 `index+route`，问答脚本实际仍按 A 运行。现在冻结版检索收进 `bench/retrievers/frozen_pipeline.py`，`run_embed_qa` 默认用 B，`--overlap none` 复现旧实验。回归检查（`bench/check_frozen_pipeline.py`）在两个 DEV 群上逐题复现了 V2、V0 的历史注入和离线实验的 A、B。B 的问答层仍未测。说明见 `docs/memory-frozen-pipeline.md`。

> **D-032 补记二（2026-11-07）：B 的问答层已补测。** DEV-1 端到端 84.1%（A/V2 85.5%，配对差 −1.4，CI −3.4~+0.7）、DEV-2 71.1%（A 71.3%，−0.2，CI −2.5~+2.1），两个群都不显著。B 可以按当前形态留在冻结版，不必为它改检索参数。结果见 `docs/memory-benchmark-results.md`「B 问答层补测」。

## D-034 模型分工：视频用 Gemini，其他模型工作用 DeepSeek（用户决定，2026-11-07）

- **做法**：视频理解（Bilibili-Video-Research）用 Gemini 服务商，模型设 `GEMINI_VIDEO_MODEL=gemini-3-flash-preview`（BVR 默认的 `gemini-2.5-flash` 已停用）；其余批量模型工作（回答、写词条、事件问答、网页读取评测等）改用 DeepSeek。始终不用 Claude 模型做批量任务（D-024 起）。
- **依据**：当时 Gemini 额度将尽。2026-11-07 稍后用户告知 Gemini 额度已恢复，分工未改，变更需用户决定。
- **密钥**：DeepSeek 在 `qqbot-data/tools/deepseek.key`，Gemini 直连在 `qqbot-data/tools/gemini.key`（均仓库外，不打印）；模型网关（`127.0.0.1:8317`）上的 Gemini、gpt-6.1-sol 仍可用，`bench/llm.py` 从 模型网关 配置读密钥。
- **口径**：DeepSeek 跑的结果与此前 Gemini 跑的实验是不同条件，台账必须写明模型。

## D-035 网页读取改用现成项目，首选 Crawl4AI（初步，2026-11-07）

- **背景**：用户认为自研 `web_reader` 能力「诡异」，且不希望依赖 DeepSeek 搜索 API（结果和性能不可控），要求用插件解决读网页。
- **测试**：原文提取 11 题（直接链接 5、深链接 6），见 `docs/research/2026-11-search-module-p0.md` 第 7–8 节。`web_reader` 只返回前 60 个链接，GitHub 和文档站的正文链接被截掉；沿正确路径的链接交出率：web_reader 1/4、mcp-server-fetch 1/4、**Crawl4AI 4/4**；Crawl4AI 的浏览器还能打开直连 403 的萌娘百科。
- **方向**：把 Crawl4AI 包成插件工具（读页面 + 全部链接 + 分段续读）替换 `web_reader`；需要点击、展开、登录态的页面再考虑 Playwright MCP（只开放导航、快照、点击）。
- **未完成**：接上模型（DeepSeek）后的原文拿回率与编造率还没测（`scripts/search/reader_eval.py model --backend ...`）；测完再定为正式决定。

> **D-035 补记（2026-11-07 晚）：模型版实测与初步结论相反。** 11 题接上模型（临时用 模型网关 的 gemini-3.8-flash-high，DeepSeek 密钥 401 无效）后：web_reader 10/11、mcp-server-fetch 9/11、Crawl4AI 10/11；编造分别是 1 / 0 / 2 题。模型会直接猜目标 URL，绕开「只返回前 60 个链接」的限制。样本太小，**D-035 暂不升级为正式决定**；DeepSeek 密钥恢复后复测、扩大题量再定。详见 `docs/research/2026-11-search-module-p0.md` 第 9 节。

## D-036 视频与所有 Gemini 调用统一走 模型网关，不用官方 Gemini API（用户决定，2026-11-07）

- **背景**：用户明确「Gemini 因为没有官方 API 额度，所以走 模型网关」。此前视频走直连 Google Gemini（`qqbot-data/tools/gemini.key`），与 模型网关 额度是两回事。
- **做法**：Gemini 调用一律经本地模型网关（`127.0.0.1:8317`），模型用 **gemini-3.8-flash-high**（与旧实验同模型；模型网关 目录里没有 BVR 默认的 `gemini-2.5-flash`，也没有 `gemini-3-flash-preview`）。
- **依据与调查**：
  - 模型网关 提供 Gemini 原生接口 `POST /v1beta/models/<model>:generateContent`（Bearer 或 `?key=` 均可），实测可用。
  - 模型网关 **不提供 Files API**：`/v1beta/files` 与 `/upload/v1beta/files` 均 404。所以 BVR 原先「上传视频到 Files API → 按 URI 引用」的路径在 模型网关 上走不通。
  - 视频可以内联：Gemini 原生接口接受 `inlineData` + base64，单请求上限约 23 MiB（BVR 的 DFSC 模式原本就是这个上限）。
- **实现**：修改仓库外的 vendored 代码 `qqbot-data/vendor/bvr/src/video-analysis.ts`（基线 commit `db78c19`）：设置 `GEMINI_BASE_URL` 时，用 `@google/genai` 的 `httpOptions.baseUrl` 指向 模型网关，并用 inline base64 代替 Files API；视频与文字两条路径都支持。未改 BVR 的 MCP 工具面。
- **验证**：6 秒合成视频（第 3 秒右上角出现绿色方块），直接调 模型网关 原生接口 3.9 秒答对；经 BVR MCP `analyze_video` 8.45 秒答对（时间、颜色、位置、不确定性都正确）。
- **限制/风险**：
  - >23 MiB 的视频不能内联，B 站长视频要先用 `inspect_video_window` 截取片段，或等 模型网关 支持 Files API。
  - 模型网关 是本地代理，可用性取决于上游账号状态；视频调用可能比文本慢。
  - 真实 B 站视频（下载、字幕、长视频）仍需在机器人实际运行的机器上测（本容器机房 IP 下载失败）。
  - `analyze_video` / `inspect_video_window` 可读本机任意路径，**不暴露给 RP 层**（沿用 A-29 的约束）。
- **关系**：D-034 的「视频用 Gemini、其余用 DeepSeek」仍按原文保留；D-036 只改「Gemini 走哪条路」。其余批量工作仍应用 DeepSeek（待有效密钥）。

> **D-034 补记（2026-11-07）：DeepSeek 密钥已换。** `qqbot-data/tools/deepseek.key` 原值对 `api.deepseek.com` 返回 401；用户授权从 dsh 凭据（`~/.dsh/.credentials.yaml` 的 `DEEPSEEK_API_KEY`）取有效 key 写入该文件（权限 600），实测 `deepseek-chat` 可用。网页读取评测已改用 DeepSeek 口径。

## D-037 搜索模块先改进自研 web_reader，不引入 Crawl4AI 作为默认读取器（2026-11-07）

- **背景**：D-035 的初步结论是「Crawl4AI 明显更好」，依据是无模型 ceiling：沿正确路径的下一跳链接交出率 Crawl4AI 4/4、web_reader 1/4。但那是**无模型**的测试，模型本身会用其它方式找目标。
- **实验（DeepSeek 口径，11 题模型版）**：web_reader 0.2.0 与 mcp-server-fetch、Crawl4AI 都答对 10/11；编造 0 / 0 / 1；平均每题 3.5 / 10.2 / 11.9 秒。改进后的 web_reader（正文优先 + 150 链接 + 分页）在 ceiling 上的深链接可达从 1/4 升到 2/4。
- **决定**：继续用自研 `web_reader` 作为默认网页读取工具，**不把 Crawl4AI 或 Playwright 装成常驻依赖**；需要点击、展开、登录态的页面按需用 Playwright MCP（只开放导航、快照、点击，沿用 A-29 约束）。
- **依据**：读取器之间的差距在模型版里消失，瓶颈转移到模型行为（读不到时会猜 URL、引用记忆里的内容）；Crawl4AI 慢 3 倍，还要维护常驻浏览器。评测方法上，原来的「整段原文逐字匹配」会把列表拼接、标点差异误判成编造，已改为字符片段覆盖率。
- **未决/限制**：样本只有 11 题，k6（萌娘百科）受本容器机房 IP 的 403 限制；真实使用场景要扩大题量后再复核。Crawl4AI 仍保留在 `qqbot-data/vendor/readers-venv` 供对照实验，不删。
- **代码**：`plugins/astrbot_plugin_web_reader/{reader,main}.py`（0.2.0）、`scripts/search/{reader_eval,backends}.py`；验证 `tests/bench/test_web_reader.py` 与 `model2_ds.*.json`。

## D-038 搜索模块以 DeepSeek 官方 search/fetch 为主，自研只补缺口（2026-11-07）

- **背景**：用户指出重新考虑实现方式——DeepSeek API 本身有搜索与 fetch，自建插件的前提只是「API 读不了群友发的链接、看不了视频、会被反爬挡」。此前把比较重点放在「哪个网页读取器更好」，偏离了搜索模块的整体问题。
- **核实（2026-11-07 实测 + 源码/文档）**：
  - 官方只提供 `POST /v1/tools/search` 与 `POST /v1/tools/fetch`；实测 search 0.4 s、fetch 0.13 s，`need_content=true` 可在搜索时直接带回正文，计费各 5 元/1000 次成功请求。
  - **没有官方 research 端点**：`/v1/tools/research` 返回 404，官方指南只列 search/fetch；第三方 `deepseek_research` 是 search+fetch 的组合封装。
  - AstrBot 内置的 `web_search_deepseek` / `deepseek_fetch_web_page` 就是直调这两个端点（`astrbot/core/tools/web_search_tools.py`），项目不需要自建平行搜索。
  - 非 FROZEN 群 4 个、共 93,214 条消息；`store/memory.db` 现有 2 个 DEV 群，需补导入 `eb61a2`、`0f51cf`。
- **决定**：
  - 搜索主路径 = AstrBot 内置 DeepSeek search / fetch；`need_content` 用于一次拿到正文。
  - “research” = 工具层循环 search → 选源 → fetch → 换源，**不新增独立研究 Agent**，也不依赖未文档化端点。
  - 自研 `web_reader` 只做兜底：fetch 失败时的链接导航/替代读取；其 0.2.0 的正文优先与链接分页保留。
  - 视频继续走 BVR + 模型网关（D-036）；需要点击/展开/登录态的页面按需用 Playwright MCP（只开放导航、快照、点击）。
- **关系**：D-035（首选 Crawl4AI）与 D-037（web_reader 作为默认读取器）中关于「默认读取器」的表述由本条重新定位；D-037 对 web_reader 的改进与评测方法修正仍然有效。
- **验证**：`docs/research/2026-11-search-module-p0.md` 第 11 节（实测与群规模）；阶段 1/2 的人工体验会话按此分工实现。

## D-039 梗表更新走「候选表 + 人工确认 + 重建快照」，不自动改写（2026-11-08）

- **背景**：测试会话中模型联网理解了新梗（如「奶蛙」），但当时没有任何写回路径——快照是静态文件，问答结束知识就丢了。
- **做法**：
  - `scripts/memory/term_candidates.py` 从 DSH 会话的工具查询词中抽取**候选**（过滤已知词条、停用词、单字和含人称代词的句子），写入 `qqbot-data/store/term_candidates.jsonl`，状态 `pending`。
  - 人工 `confirm` 后才写入 `memory.db` 的 `term`/`term_sense`（`status=confirmed`，`source_table=session:<id>`）；`reject` 只记录、永不注入。
  - `build_snapshot.py` 合并 DB 已确认词条（`chat code=general` 为通用层，其他群为本群层，DB 覆盖同名标注），重新生成 `memory_snapshot.md`；persona 插件下次启动读取。
- **依据**：梗和人物是有证据门槛的长期知识，自动写入会污染快照，且模型在会话里“理解”不等于该词成立；人工确认把质量责任放在可追溯的一步。
- **验证**：确认「奶蛙」后快照通用梗从 56 条增至 57 条，`memory_snapshot.md` 第 75 行出现该词条；`extract` 在三个会话上抽到 8 条候选，6 条噪声 reject 后剩 1 条待判定。
- **限制/待办**：
  - 候选抽取只看查询词，人名、产品名、已有词的变体（如繁体「星紗」）会产生噪声，需要人工复核；
  - 快照更新需要重启 DSH 一次（一次冷前缀），尚未实现“尾部增量注入”（不重启生效）；
  - 证据字段目前只有会话 id 与查询词，未自动关联到群消息/时间；后续可从 `memory_search` 命中结果补。

> **D-039 补记（2026-11-08）：搜索确认是梗的，直接进梗表。** 用户要求：通过搜索了解到“这是一个梗”的，直接写入梗表，不过频率门槛。`term_candidates.py extract` 现在读取 `search_web` 自己的返回结果，命中梗信号（梗/meme/表情包/抽象/网络用语/流行/网红/二创/玩梗）即写入 `term`（`status=confirmed`，来源 `search:<session>`），含义取搜索结果第一条摘要；候选记录标 `auto-confirmed` 便于追溯。其余候选仍需人工 `confirm`/`reject`。合成会话验证：`auto_confirmed: 1`。

## D-040 网页读取逐级升级过反爬；给模型浏览器操作工具（2026-11-08）

- **背景**：用户指出搜索模块没优化完：模型要能实际使用网页（问卷、小测试、小游戏），并能过反爬；金标准是 rym 能否打开。最终部署在家宽，但本机能做到的插件也要做到。
- **决定**：
  - `web_reader` 0.3.0 逐级升级：普通请求 → curl_cffi（浏览器 TLS 指纹）→ patchright 真浏览器（持久 cookie、自动点 Turnstile）。只有前一档被拦或正文过少才升级。
  - 新增 `browser_open/click/type/select/key/find` 六个工具，快照用无障碍树加 ref。浏览器每个请求都过公网地址检查，不下载文件。
  - 不引入第三方浏览器 MCP（Playwright MCP 等）作为常驻依赖；需要的能力已在插件内，权限面更小。
- **依据**：本地夹具评测修正后 30/30（DeepSeek）；本机机房 IP 下萌娘百科、百度百科从 403 变为可读。rym 和 Cloudflare 测试页在本机任何方式都过不了（IP 信誉），需在家宽机器上用 `scripts/search/antibot_probe.py` 复测。
- **限制**：真实问卷站点未测；canvas 游戏需要视觉模型；知乎在本机仍停在其安全验证。详见 `docs/research/2026-11-search-module-p0.md` 第 12 节。

## D-041 视频由插件取回、压缩、按内联上限切片后逐段交给 Gemini（2026-11-08）

- **背景**：模型网关 没有 Files API，视频只能内联，单请求约 20 MiB（D-036）。用户要求插件负责取回和切片。
- **决定**：新增 `astrbot_plugin_video_reader`，链路是 yt-dlp 下载 → 一次转码（360p、2 fps、低码率音频，每 20 秒一个关键帧）→ 按码率算等长片段并用 stream copy 切开 → 每段带原视频时间窗提问 → 文字合并。模型只能传 http(s) 链接。BVR 继续保留作对照，不作为部署依赖。
- **验证**：93 MB 合成视频（压缩后 2 MB）和强制切片两种情况，时间映射正确；YouTube 短片 18 秒答对并转录原话。
- **限制**：B 站在机房 IP 上 412，要在家宽机器上测；还没做 B 站字幕/弹幕/评论的文字通道（BVR 有，后续可移植）；超过 3 小时的视频要求给时间窗。

## D-042 浏览器档改为真 Chrome 有界面加本地守卫代理，冷链接被拒时走首页（2026-11-10）

- **背景**：D-040 的浏览器档在本机过不了 Cloudflare 和 rym，当时归因为机房 IP。11-10 自检发现旧配置自己就漏了一串特征（UA 带 `HeadlessChrome`、Chromium 130、请求拦截、UTC 时区），归因不成立。
- **决定**：web_reader 0.4.0。浏览器优先用系统 Google Chrome，默认有界面，无桌面的 Linux 由插件起 Xvfb；不改 UA 和请求头；时区可配。公网地址检查从请求拦截改为本地转发代理 `GuardProxy`，WebRTC 也不许绕过它。Camoufox 作为可选的第二引擎，只用于读取。页面直接回错误又没有验证可解时，先开首页再跳到目标页，并记住该站点。同站点页面加载间隔至少 3 秒。
- **验证**：本机机房 IP 上，Cloudflare 测试页、rym 首页、艺人页、专辑页都读到了，专辑页用全新配置目录约 22 秒。公开检测页都判为非机器人。网页操作评测 10/10，测试 118 项通过。
- **限制**：知乎仍被拦，原因没拆开。rym 访问太快会出 reCAPTCHA，这一层不解，只靠节流。结果只在本机测过，部署机要装 Chrome 和 Xvfb 并重跑探测。详见 `docs/research/2026-11-search-module-p0.md` 第 14 节。
