# 迁移清单：Windows 本地 → Linux VPS（原生 systemd，无 Docker）

> **已过时（2026-11-16）**：本文是 AstrBot 时代的文档。机器人现在是 `bothost` + dsh，部署在 Windows PC 的 WSL 里。当前状态见 [handover-2026-11-16.md](handover-2026-11-16.md)，本文只作历史参考。

> **已不是当前路线（D-021）**：现在的目标是常驻 Windows PC + SnowLuma，见 [transfer-to-new-machine.md](transfer-to-new-machine.md)。本文仍是 NapCat 方案，仅作历史参考。

> 原则：**整体迁移 AstrBot 的 `data/` 目录**，不在 VPS 上重新初始化（WebUI 密码、JWT、会话、插件配置都在里面）。
> 部署方式与选型：`DECISIONS.md` D-005 / D-011；原生步骤：`deploy/linux/native/README.md`。
> 风险：海外 VPS 上 QQ 协议端风控更严，扫码后可能还要手机验证。

## 0. 迁移前检查

- [ ] 本地私聊链路已验收（2026-10-24 已通过）
- [ ] `python scripts/backup_data.py` 本地备份成功
- [ ] VPS：Debian/Ubuntu、≥2 GB 内存（建议配 2 GB swap）、≥3 GB 磁盘
- [ ] VPS 已装：`python3 curl git xvfb xauth libfuse2 rsync`，已装 `uv`
- [ ] 专用用户 `qqbot`，目录 `/opt/qqbot`、`/opt/napcat`
- [ ] 记录版本：AstrBot `4.29.1`；NapCat Linux AppImage `v4.18.41`（内含 QQ build 53644）

## 1. 本地停服并打包

```powershell
# 停 AstrBot（结束运行它的进程）与 NapCat（结束 QQ.exe / NapCatWinBootMain.exe）
cd D:\qqbot
python scripts\backup_data.py --out D:\qqbot\backups
# 产物：backups\data-YYYYmmdd-HHMMSS.zip；.env 默认不入包
```

## 2. 上传

```bash
# 本机（Windows 可用 scp / rsync via WSL，或用 VPS 面板上传）
scp backups/data-YYYYmmdd-HHMMSS.zip user@vps:/opt/qqbot/
rsync -av --exclude data --exclude .env --exclude .git --exclude tmp \
      ./ user@vps:/opt/qqbot/
```

## 3. VPS 上安装（摘要，完整步骤见 deploy/linux/native/README.md）

```bash
# 3.1 依赖 + 用户
sudo apt update && sudo apt install -y python3 curl git xvfb xauth libfuse2 rsync
sudo useradd -m -s /bin/bash qqbot || true
sudo mkdir -p /opt/qqbot /opt/napcat && sudo chown -R qqbot:qqbot /opt/qqbot /opt/napcat

# 3.2 AstrBot（qqbot 用户）
sudo -iu qqbot bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -iu qqbot bash -lc 'export PATH=$HOME/.local/bin:$PATH && uv tool install astrbot --python 3.12'

# 3.3 还原数据 + .env
cd /opt/qqbot && unzip -o data-YYYYmmdd-HHMMSS.zip
sudo -u qqbot cp .env.example .env   # 填入 DEEPSEEK_API_KEY / MULTI_API_KEY
sudo chmod 600 .env
sudo -u qqbot python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/opt/qqbot/data/cmd_config.json")
cfg = json.loads(p.read_text(encoding="utf-8-sig"))
cfg["dashboard"]["host"] = "127.0.0.1"
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
PY

# 3.4 NapCat AppImage
sudo -iu qqbot bash -lc 'cd /opt/napcat && curl -fL -o NapCat.AppImage https://github.com/NapNeko/NapCatAppImageBuild/releases/download/v4.18.41/QQ-53644_NapCat-v4.18.41-amd64.AppImage && chmod +x NapCat.AppImage'

# 3.5 systemd
sudo cp /opt/qqbot/deploy/linux/native/qqbot-*.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now qqbot-astrbot qqbot-napcat
```

## 4. 扫码登录（关键步骤）

```bash
# 本机
ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 user@vps
```

浏览器打开 `http://127.0.0.1:6099/webui`，用小号扫码。

- 海外 IP 可能触发手机验证/设备验证，按提示完成并等待二维码刷新；
- 登录成功后确认 `/opt/napcat/config/onebot11*.json` 有指向 `ws://127.0.0.1:6199/ws` 的客户端
 （没有就跑 `python3 scripts/patch_napcat_onebot.py /opt/napcat/config`）。

## 5. 验收

- [ ] `journalctl -u qqbot-astrbot | grep 适配器已连接`
- [ ] `journalctl -u qqbot-astrbot | grep "Loading model"` 显示 6 个 provider
- [ ] 私聊发一句「在吗」能回复（与本地一致）
- [ ] `systemctl restart qqbot-astrbot qqbot-napcat` 后自动恢复
- [ ] VPS 重启后服务自动拉起（`systemctl is-enabled`）
- [ ] 内存：`systemd-cgtop` / `systemctl status` 观察未触顶；必要时调 `MemoryMax`
- [ ] 编译任务前 `systemctl stop qqbot-napcat qqbot-astrbot`，避免争抢内存

## 6. 回滚

```bash
sudo systemctl disable --now qqbot-astrbot qqbot-napcat
# 恢复旧备份 data/ 或直接在本地继续运行（本地实例保留到 VPS 稳定运行 24h 再停）
```

## 7. 迁移后待办

- [ ] 每日备份 cron：`python3 scripts/backup_data.py --root /opt/qqbot --out /var/backups/qqbot`
- [ ] SSH 防火墙只开 22；6185/6099 不对外
- [ ] 观察 24h：掉线、内存、QQ 风控
- [ ] 本地旧实例停用（VPS 稳定后）
