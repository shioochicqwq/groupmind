# 迁移清单：Windows 本地 → Linux VPS

> 原则：**整体迁移 `data/` 目录，不做"VPS 上重新初始化"**。AstrBot 的 WebUI 密码、JWT、聊天记录、插件配置都在里面。
> 决策背景见 `DECISIONS.md` D-005 / D-007。

## 0. 迁移前检查（本地）

- [ ] 本地 AstrBot 已能正常启动、群聊可用（最低限度：provider 可用、WS 已连接）
- [ ] `python scripts/backup_data.py` 本地备份成功，并能在别处解压
- [ ] 记录当前版本：AstrBot `v4.29.1`、NapCat `4.18.28`（本地）/ 目标镜像 `v4.18.41`
- [ ] VPS 已装 Docker + Compose，`docker compose version` 正常
- [ ] VPS 能拉取 `soulter/astrbot:v4.29.1` 和 `mlikiowa/napcat-docker:v4.18.41`
      （国内 VPS 需要镜像加速或代理；拉取失败时在 Docker daemon 配代理）
- [ ] VPS 时间同步正常（`date`；容器用 `TZ=Asia/Shanghai`）
- [ ] 专用小号的手机号/密保可用，能完成可能出现的设备验证

## 1. 本地停服并打包

```powershell
# 本地：停 AstrBot（关闭运行它的终端进程）与 NapCat（结束 QQ.exe / NapCatWinBootMain.exe）
cd D:\qqbot
python scripts\backup_data.py --out D:\qqbot\backups
# 产物：D:\qqbot\backups\data-YYYYmmdd-HHMMSS.zip
```

不要把 `.env` 打进包里（默认排除）；`.env` 单独安全传递或在 VPS 上重新填写。

## 2. 上传到 VPS

```bash
# VPS 上
sudo mkdir -p /opt/qqbot && sudo chown "$USER":"$USER" /opt/qqbot
# 上传代码（不含 data/）
rsync -av --exclude data --exclude runtime --exclude .env --exclude .git \
      ./ user@vps:/opt/qqbot/
# 上传数据包
scp backups/data-YYYYmmdd-HHMMSS.zip user@vps:/opt/qqbot/
```

## 3. VPS 上还原

```bash
cd /opt/qqbot
unzip -o data-YYYYmmdd-HHMMSS.zip        # 得到 ./data/
cp .env.example .env
# 编辑 .env：DEEPSEEK_API_KEY、NAPCAT_WEBUI_TOKEN（openssl rand -hex 16）、NAPCAT_UID/GID
mkdir -p runtime/napcat runtime/ntqq
chown -R "${NAPCAT_UID:-1000}:${NAPCAT_GID:-1000}" runtime
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f astrbot
```

核对：

- AstrBot 日志无 provider 报错（有 key 时不应出现 `Missing credentials`）
- `docker compose logs napcat` 出现 WebUI 地址与二维码
- `data/cmd_config.json` 内容与本地一致（`platform` 中 aiocqhttp 端口 6199）

## 4. 扫码登录（关键步骤）

```bash
# 本地机器
ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 user@vps
```

浏览器打开 `http://127.0.0.1:6099/webui?token=<NAPCAT_WEBUI_TOKEN>`，用专用小号扫码。

**预期风险**：换设备/换 IP 登录可能触发设备验证或临时风控。建议：

- 迁移窗口内不要在手机端重复上下线小号
- 若出现验证，按手机 QQ 提示完成，再等待二维码刷新
- 登录成功后先观察 10–30 分钟再拉群测试

## 5. 验收

- [ ] AstrBot 日志：`aiocqhttp(OneBot v11) 适配器已连接`
- [ ] NapCat 生成了 `runtime/napcat/onebot11_<QQ号>.json`，URL 为 `ws://astrbot:6199/ws`
- [ ] 测试群 @ 小号有回复，上下文连续
- [ ] `/provider`、`/model` 可切换（管理员）
- [ ] `docker compose restart` 后自动恢复（napcat + astrbot 均 `restart: unless-stopped`）
- [ ] 服务器重启后容器自动拉起

## 6. 回滚

```bash
cd /opt/qqbot
docker compose down
unzip -o /path/to/backup-before-migration.zip -d .
docker compose up -d
```

## 7. 迁移后待办

- [ ] 配置每日备份 cron（`scripts/backup_data.py`）
- [ ] 关闭 NapCat WebUI 公网绑定（compose 已默认 `127.0.0.1`，不要改成 0.0.0.0）
- [ ] 观察 24h，确认无掉线/风控；再关闭本地旧实例
