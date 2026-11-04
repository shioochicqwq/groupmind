# Linux VPS 部署总览

> **已不是当前路线（D-021）**：现在的目标是常驻 Windows PC + SnowLuma，见 [docs/transfer-to-new-machine.md](../../docs/transfer-to-new-machine.md)。本目录（含 `native/`、`docker-compose.yml`）仍是 NapCat 方案，仅作历史参考，且依赖的 `NAPCAT_*` 变量已从 `.env.example` 移除。

## 当前选择：原生 systemd（不使用 Docker）

原因：目标 VPS 内存/磁盘紧张且会跑编译，Docker 守护进程与镜像占用不可接受。
详见 `DECISIONS.md` D-011。

- 详细步骤：[native/README.md](native/README.md)
- systemd 单元：[native/qqbot-astrbot.service](native/qqbot-astrbot.service)、[native/qqbot-napcat.service](native/qqbot-napcat.service)
- 迁移清单：[docs/migration-vps.md](../../docs/migration-vps.md)

关键路径：

| 项目 | 值 |
|---|---|
| 仓库/数据 | `/opt/qqbot`、`/opt/qqbot/data` |
| AstrBot | uv 安装，systemd `qqbot-astrbot`，WebUI `127.0.0.1:6185` |
| NapCat | AppImage + Xvfb，systemd `qqbot-napcat`，WebUI `127.0.0.1:6099`，配置 `/opt/napcat/config` |
| OneBot 反向 WS | `ws://127.0.0.1:6199/ws`（仅本机） |
| 密钥 | `/opt/qqbot/.env`（600 权限，gitignored） |

## 可选 fallback：Docker Compose

仅当 VPS 资源充足（≥2 GB 可用内存、≥5 GB 磁盘）时才建议使用。

```bash
# 从仓库根目录执行；使用根目录 .env
docker compose --env-file .env -f deploy/linux/docker-compose.yml up -d
```

与原生方案的差异：数据目录仍是仓库根 `./data`；NapCat 状态在 `./runtime/napcat`、`./runtime/ntqq`；
WebUI 同样只绑 `127.0.0.1`。该路径**不是**本项目默认部署方式。
