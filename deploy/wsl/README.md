# 部署：Windows PC + WSL（当前路线，D-053）

QQ 桌面客户端和 SnowLuma 跑在 Windows 上，bothost 和 dsh 跑在一个专用的 WSL 发行版里，这样机器人的工作区是一个真正的 Linux 环境。两边只通过本机回环通信，WSL2 会把 Windows 的 `127.0.0.1` 转发进来。

```
Windows                                    WSL 发行版 qqbot（用户 bot）
┌───────────────────────────┐             ┌──────────────────────────────────────────┐
│ QQ 桌面客户端（人工登录）    │             │ bothost（python -m bothost config.json） │
│ SnowLuma v2.4.2           │  反向 WS    │   ├─ OneBot 服务端 127.0.0.1:6199/ws     │
│   OneBot HTTP 3000/WS 3001│ ──────────► │   ├─ MCP 工具服务 127.0.0.1:6199/mcp     │
│   WebUI 127.0.0.1:5099    │             │   └─ 每个群一个 dsh 进程（按需启停）      │
└───────────────────────────┘             └──────────────────────────────────────────┘
```

本目录的文件：

| 文件 | 用途 |
|---|---|
| `setup-root.sh` | 在新导入的发行版里以 root 运行一次：系统包、Node、Chrome、用户 `bot`、`wsl.conf`、DNS |
| `setup-bot.sh` | 以 `bot` 运行：建目录、Python venv、dsh、yt-dlp |
| `run.sh.example` | 启动脚本模板，复制成 `/home/bot/qqbot/run.sh`。密钥从 `secrets/` 里的文件读 |
| `config.example.json` | bothost 配置模板，复制成 `/home/bot/qqbot/config.json` 后填群号 |
| `register-tasks.ps1` | 在 Windows 上注册三个登录时启动的计划任务 |
| `push-update.sh` | 从开发机把改动的文件推到 PC 并重启 bothost |

## 1. Windows 侧

1. **WSL2**：启用「适用于 Linux 的 Windows 子系统」和「虚拟机平台」两个功能，装 WSL 内核更新包，`wsl --set-default-version 2`。启用后要重启；第一次重启后如果报 hypervisor 没运行，再重启一次（2026-11-14 在用户 PC 上就是这样）。
2. **导入发行版**：用 Ubuntu 24.04 官方 WSL rootfs（`ubuntu-noble-wsl-amd64.rootfs.tar.gz`，对照官方 SHA256SUMS）：
   ```powershell
   wsl --import qqbot D:\WSL\qqbot <rootfs.tar.gz> --version 2
   ```
3. **SnowLuma**：Windows x64 发行版 zip（当前 v2.4.2，几个镜像公布的哈希一致）解压到 `D:\qqbot-bothost\snowluma`。在 WebUI（`http://127.0.0.1:5099`）里：
   - 关闭遥测（启动时设 `SNOWLUMA_TELEMETRY=0`，计划任务里已带）；
   - 给机器人小号加一个 **WebSocket 客户端**，地址 `ws://127.0.0.1:6199/ws`，access token 与 WSL 里 `secrets/onebot.token` 相同；
   - HTTP 3000、WS 3001 留在本机，不对外。
4. **QQ 登录**：用户本人在桌面上打开 QQ，登录机器人小号。SnowLuma 接管这个已登录的客户端，不需要扫码脚本。
5. **计划任务**：以要登录桌面的那个 Windows 用户运行 `register-tasks.ps1`。三个任务都是「用户登录时」触发，所以 PC 必须登录桌面（可设自动登录）。

## 2. WSL 侧

```bash
# 在 Windows 上：把仓库打包放到 D:\，再进发行版
wsl -d qqbot -u root -- bash /mnt/d/<路径>/deploy/wsl/setup-root.sh
wsl --terminate qqbot            # 让 wsl.conf 生效
wsl -d qqbot -u bot -- bash /mnt/d/<路径>/deploy/wsl/setup-bot.sh /mnt/d/<仓库解压目录>
```

然后以 `bot` 准备：

| 路径 | 内容 |
|---|---|
| `~/qqbot/app/` | 仓库代码（只需 `bothost/`、`bench/`、`plugins/`、`deploy/dsh/`、`scripts/memory/`、`tests/`） |
| `~/qqbot/config.json` | 由 `config.example.json` 改 |
| `~/qqbot/run.sh` | 由 `run.sh.example` 改，`chmod 755` |
| `~/qqbot/secrets/` | `onebot.token`、`gateway.key`、`deepseek.key`，权限 600 |
| `~/qqbot/data/` | `memory.db`、`persona.md`、`memory_snapshot.md`（从开发机的 `qqbot-data/` 拿，**不进仓库**） |

验收：

```bash
cd ~/qqbot/app && PATH=~/qqbot/dsh/node_modules/.bin:$PATH ~/qqbot/venv/bin/python -m pytest -q tests/bothost
```

2026-11-14 在 PC 上是 16 个测试全过；现在 `tests/bothost` 更多，以实际数为准。

## 3. 日常操作

| 要做的事 | 怎么做 |
|---|---|
| 重启 bothost | Windows 上 `Stop-ScheduledTask QQBot-bothost; Start-ScheduledTask QQBot-bothost`（或在 WSL 里 `pkill -f "python -m bothost"`，任务会在 1 分钟内拉起） |
| 看日志 | `~/qqbot/logs/bothost.log`；SnowLuma 在 `D:\qqbot-bothost\logs\snowluma.log` |
| 影子测试的输出 | `~/qqbot/data/shadow.jsonl`（每条准备说的话）；`shadow_forward_to` 设了的话同时私聊转发 |
| 用量 | `~/qqbot/data/usage.jsonl`（每回合一行，按角色分开） |
| 机器人记下的人 | `~/qqbot/venv/bin/python -m bothost.people history --db ~/qqbot/data/memory.db`，撤销用 `undo ID` |
| 更新代码 | 开发机上 `deploy/wsl/push-update.sh <文件…>` |
| 补群历史 | `python -m bench.store.backfill --db … --exports <目录> --codes <代号> --frozen-codes <冻结代号>`（见该文件开头的说明） |

## 4. 已知坑

- **WSL 空闲会自动关机**，bothost 跟着没了。`QQBotWsl-keepalive` 任务挂一个 `sleep infinity` 防止这件事。
- **WSL 自动生成的 DNS 时好时坏**：`setup-root.sh` 关掉自动生成，固定为 223.5.5.5 和 119.29.29.29。
- **Windows 上不能用 Unix socket 连 dsh 插件**，所以接力插件 `deploy/dsh/handoff.mjs` 走回环 TCP 加随机 token。
- **PC 自己的代理（FlClash）当前没有可用节点**：PC 访问外网都直连。Chrome 是在 2026-11-15 直连下载装上的（157.0.8103.78）。
- `dsh` 是 `@deepseek-ai/dsh@0.2.1-rc.4`，接力插件依赖它的内部接口；升级 dsh 前先在 PC 上跑 `tests/bothost`。
