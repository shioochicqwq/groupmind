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
- **VPS 目标**：Docker Compose 同时跑 AstrBot + NapCat（sidecar），挂载 `./data` 持久化。

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

## 4. 进行中 / 待验证

- [ ] QQ 私聊实测：主号给 `example` 发消息 → 应收到人设化回复
- [ ] 测试群：把小号拉进测试群 → 群号填入 `active_reply.whitelist`，验证 @ 回复/上下文/主动插话
- [ ] 群聊整活实测迭代：按 [group-chat-tuning.md](docs/group-chat-tuning.md) 调概率/上下文/分段
- [ ] VPS Docker 化部署（资产已就绪，等 VPS 与迁移窗口）

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
| 小号已加入群 | `<GROUP_ID>`「<GROUP_NAME>」（54 人，待确认是否作为测试群） |
| LLM Key | 本地 `.env` 的 `DEEPSEEK_API_KEY` / `MULTI_API_KEY`（gitignored） |

## 6. 模型切换能力

- 已配置两套 provider source（key 均以 `$ENV` 引用，不落盘）：
  - `deepseek_source` → `https://api.deepseek.com/v1`，模型 `deepseek-chat`（**默认**）
  - `multi_source` → `https://<GATEWAY_HOST>/v1`（OpenAI 兼容聚合端点），模型：
    `gemini-3.8-flash`、`claude-sonnet-4-6`、`claude-opus-4-6`、`gpt-6-astra`、`gpt-6.1-sol`
- 会话内切换：`/provider`、`/model`（管理员指令），按会话持久化；默认模型见
  `agent_runner.config.model.provider_id`。
- 管理员 ID：`astrbot`（Dashboard）与 `<ADMIN_QQ>`（QQ 主号，可用 `/provider`、`/model`、`/reset`）。
- 冒烟测试：`python scripts/smoke_llm.py --provider <id>`（经 AstrBot WebChat 全链路，见 runbook）。
- 后续可用「配置文件（Config Profiles）」给不同群设不同默认模型。
- 新增 provider：WebUI「模型提供商」添加 source + 模型，key 用 `$VAR` 环境变量。

## 7. 已知问题与技术债

- 本地 NapCat 升级到 4.18.41 后，快速登录（`-q <uin>`）要求手机 QQ 验证，需改回扫码；换机/换版本后扫码是常规路径。
- Windows 本机不能常驻，当前仅作开发验证；VPS 迁移需重新扫码登录（可能触发设备验证）。
- AstrBot 升级会带来配置迁移风险：当前锁定 4.29.1，升级前备份 `data/`。
- NapCat WebUI 默认无访问控制（`accessControlMode: none` 且监听 `::`），VPS 部署必须改用防火墙/仅内网监听（compose 已绑定 127.0.0.1）。
- NapCat / QQ 必须以 NapCat 目录为工作目录启动，否则会在仓库根写出 `guild*.db`（启动脚本已 `Set-Location` 修正，gitignore 兜底）。
- 主动插话依赖会话已存在（先 @ 一次产生对话），否则日志报 `No active conversation`。
- 尚未做刷屏/被举报的线上观察，限流与主动插话概率需要实群调参。

## 8. 下一步计划

1. 重新扫码登录小号 `<BOT_QQ>` → 确认 AstrBot 日志「适配器已连接」。
2. 提供 LLM Key（写入 `.env`）→ 用 AstrBot 内置 Web Chat 验证模型回复，再进群 @ 测试。
3. 调人格与群聊行为（主动插话、分段、表情、频率限制）。
4. 迁移 VPS：按 [migration-vps.md](docs/migration-vps.md) 走，扫码后用 [deploy/linux/README.md](deploy/linux/README.md) 验收，观察 24h。
