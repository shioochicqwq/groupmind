# Linux VPS 部署（Docker Compose）

生产拓扑由仓库根目录的 [`docker-compose.yml`](../../docker-compose.yml) 定义：

```
napcat (mlikiowa/napcat-docker:v4.18.41)  --ws://astrbot:6199/ws-->  astrbot (soulter/astrbot:v4.29.1)
```

- AstrBot WebUI `127.0.0.1:6185`、NapCat WebUI `127.0.0.1:6099` **只绑定本机**，通过 SSH 隧道访问，不直接暴露公网。
- 数据：`./data`（AstrBot，与 Windows 本地同名目录，可整体迁移）。
- NapCat：`./runtime/napcat`（OneBot/WebUI 配置）、`./runtime/ntqq`（QQ 登录态）。
- 密钥：仓库根 `.env`（DEEPSEEK_API_KEY / NAPCAT_WEBUI_TOKEN / UID/GID）。

## 1. 前置条件

- Linux VPS（建议 ≥2C2G，Debian/Ubuntu 22.04+），已装 Docker Engine + Compose 插件
- 能访问 Docker Hub（国内 VPS 可能需要镜像加速/代理）
- 已通过本地验证的数据目录（见 `docs/migration-vps.md`）

## 2. 准备目录与配置

```bash
# 在 VPS 上，仓库路径示例 /opt/qqbot
cd /opt/qqbot
cp .env.example .env
# 编辑 .env：填入 DEEPSEEK_API_KEY、MULTI_API_KEY、NAPCAT_WEBUI_TOKEN（openssl rand -hex 16）
# 注意 NAPCAT_UID/NAPCAT_GID 要与目录属主一致
mkdir -p data runtime/napcat runtime/ntqq
sudo chown -R "${NAPCAT_UID:-1000}:${NAPCAT_GID:-1000}" runtime
```

> `data/` 从本地迁移过来（包含 AstrBot 配置、密码哈希、聊天记录、插件）；
> 不要在新机器上重新初始化，否则 WebUI 密码和会话都会变。

## 3. 启动

```bash
cd /opt/qqbot
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f astrbot
```

首次启动后：

1. 本地起 SSH 隧道：
   ```bash
   ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 user@vps
   ```
2. 浏览器打开 `http://127.0.0.1:6099/webui?token=<NAPCAT_WEBUI_TOKEN>`，
   用专用小号扫码登录（**换机会触发设备验证，属正常现象**）。
3. NapCat 登录成功后会自动生成 `runtime/napcat/onebot11_<QQ号>.json`，
   其中 reverse-WS 指向 `ws://astrbot:6199/ws`；AstrBot 日志应出现
   `aiocqhttp(OneBot v11) 适配器已连接`。
4. 打开 `http://127.0.0.1:6185` 登录 AstrBot WebUI 验证模型/人格/插件。

## 4. 升级

- 镜像版本在 `docker-compose.yml` 中固定；升级时改 tag → `docker compose pull && docker compose up -d`。
- AstrBot 升级前先备份 `data/`（见 `scripts/backup_data.py`）并在本地验证同版本。
- NapCat 升级一般保留 `runtime/` 三个目录即可；QQ 版本升级后若出现偏移数据警告，优先升级 NapCat。

## 5. 备份与恢复

```bash
# 备份（建议 cron 每日执行）
python3 scripts/backup_data.py --root . --out /var/backups/qqbot

# 恢复：停服务 -> 解压覆盖 data/ -> 起服务
docker compose down
unzip -o /var/backups/qqbot/data-YYYYmmdd-HHMMSS.zip -d .
docker compose up -d
```

`data/` 含密码哈希、JWT secret、聊天记录与可能的 provider key 引用，备份文件按敏感数据处理。

## 6. 排障速查

| 现象 | 排查 |
|---|---|
| AstrBot 起不来 | `docker compose logs astrbot`；确认 `data/` 权限与磁盘空间 |
| NapCat 起来了但 AstrBot 无连接 | `docker compose logs napcat`；确认 `runtime/napcat/onebot11*.json` 中 url 为 `ws://astrbot:6199/ws`；容器网络 `qqbot_net` 正常 |
| 二维码不出来 | 查看 NapCat 容器日志；确认 `MODE=astrbot` 且 `runtime/napcat/onebot11.json` 已生成 |
| WebUI 打不开 | 端口绑定在 127.0.0.1，必须 SSH 隧道；检查 `docker compose ps` 端口映射 |
| 群聊不回复 | 见 `docs/runbook-local.md` 的常见问题（平台 enable、@ 触发、provider key） |
