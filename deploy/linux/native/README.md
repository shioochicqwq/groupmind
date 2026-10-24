# Linux VPS 原生部署（systemd，不使用 Docker）

> 选择原因见 `DECISIONS.md` D-011：目标 VPS 内存/磁盘紧张且要跑编译，Docker 守护进程 + 镜像
> 占用不可接受。Docker Compose 方案退居为可选 fallback（`deploy/linux/docker-compose.yml`），**不是当前路径**。

拓扑：

```
NapCat AppImage（内含 Linux QQ，Xvfb 无头运行）
  └─ OneBot v11 反向 WS → ws://127.0.0.1:6199/ws
AstrBot（uv 安装，Python 3.12，systemd 服务）
  └─ 读取 /opt/qqbot/data 与 /opt/qqbot/.env
```

> 状态说明：以下步骤基于 NapCat 4.18.41 AppImage 与 AstrBot 4.29.1 的官方文档整理，
> **尚未在目标 VPS 上实测**；标记 ⚠️ 的路径/数值需要在 VPS 上确认后回填本文档。

## 0. 资源预算（⚠️ 估算，待实测）

| 进程 | 常驻内存（估算） | 说明 |
|---|---|---|
| NapCat AppImage（Linux QQ Electron + NapCat） | 700 MB–1.5 GB | Electron 多进程；本地 Windows QQ 实测合计 RSS ≈ 1.8 GB |
| AstrBot（Python） | 250–450 MB | 本地实测运行时 RSS ≈ 264 MB（含依赖） |
| Xvfb | < 20 MB | 无头显示 |
| **合计** | **约 1–2 GB** | 2 GB VPS **非常紧张**；建议 ≥4 GB，或改用官方 QQ 机器人方案 |

> 2026-10-24 本地实测（Windows，仅供参考）：`python`（AstrBot）RSS ≈ 264 MB；
> QQ 相关进程合计 RSS ≈ 1.8 GB（Electron 多进程，含主进程/渲染/GPU）。
> Linux QQ 的进程模型类似，**不要按 2 GB VPS 规划**，除非接受频繁 OOM/swap 抖动。

建议：≥2 GB 内存的 VPS 至少配 **2 GB swap**；systemd 用 `MemoryMax` 兜底，
编译任务前 `systemctl stop qqbot-napcat qqbot-astrbot`。

## 1. 前置

```bash
# Debian/Ubuntu 示例
sudo apt update
sudo apt install -y python3 curl git xvfb xauth libfuse2 rsync
# uv（管理 AstrBot 的 Python 环境）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 专用用户与目录
sudo useradd -m -s /bin/bash qqbot   # 已存在则跳过
sudo mkdir -p /opt/qqbot /opt/napcat
sudo chown -R qqbot:qqbot /opt/qqbot /opt/napcat
```

> 海外 VPS 提醒：QQ 协议端从海外 IP 登录风控概率更高，可能频繁触发手机验证/设备验证；
> 这是方案固有风险（见 D-011），尽量保持 IP 固定、避免频繁换登录环境。

## 2. AstrBot

```bash
sudo -iu qqbot
export PATH="$HOME/.local/bin:$PATH"
uv tool install astrbot --python 3.12
cd /opt/qqbot
# 把本地 data/ 迁移过来（见 docs/migration-vps.md），或首次用 astrbot init 生成
astrbot init -y
```

安全调整（VPS 上 WebUI 只监听本机）：

```bash
cd /opt/qqbot
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("data/cmd_config.json")
cfg = json.loads(p.read_text(encoding="utf-8-sig"))
cfg["dashboard"]["host"] = "127.0.0.1"
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
print("dashboard.host = 127.0.0.1")
PY
```

密钥：`cp /opt/qqbot/.env.example /opt/qqbot/.env`，填 `DEEPSEEK_API_KEY`、`MULTI_API_KEY`，
权限 `chmod 600 /opt/qqbot/.env`。

## 3. NapCat（AppImage）

```bash
sudo -iu qqbot
cd /opt/napcat
# 从 https://github.com/NapNeko/NapCatAppImageBuild/releases 选择版本（当前 v4.18.41，amd64/arm64）
curl -fL -o NapCat.AppImage \
  https://github.com/NapNeko/NapCatAppImageBuild/releases/download/v4.18.41/QQ-53644_NapCat-v4.18.41-amd64.AppImage
chmod +x NapCat.AppImage

# 无头启动（xvfb-run 自动提供 DISPLAY）；无 FUSE 时加 --appimage-extract-and-run
xvfb-run -a ./NapCat.AppImage --appimage-extract-and-run
```

首次启动后：

1. 打开 `http://127.0.0.1:6099/webui`（本机 SSH 隧道）扫码登录小号；
2. ⚠️ 确认配置目录：README 要求固定工作目录以保留配置，实际应为 `/opt/napcat/config/`
   下的 `onebot11*.json`（待 VPS 实测确认）；
3. 给 NapCat 增加指向 AstrBot 的 WS 客户端：

```bash
python3 scripts/patch_napcat_onebot.py /opt/napcat/config ws://127.0.0.1:6199/ws
```

4. 安全：把 NapCat WebUI 绑定到 127.0.0.1（`/opt/napcat/config/webui.json` 的 `host`），
   并确保防火墙只放行 22。

## 4. systemd 服务

```bash
sudo cp deploy/linux/native/qqbot-astrbot.service /etc/systemd/system/
sudo cp deploy/linux/native/qqbot-napcat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qqbot-astrbot qqbot-napcat
systemctl status qqbot-astrbot qqbot-napcat --no-pager
```

- 日志：`journalctl -u qqbot-astrbot -f`、`journalctl -u qqbot-napcat -f`
- 资源上限在 unit 的 `MemoryMax=` 调整（默认 AstrBot 600M / NapCat 1100M）。
- 验证连接：`journalctl -u qqbot-astrbot | grep 适配器已连接`
- 一键体检（与本地相同脚本）：

```bash
export ASTRBOT_DASHBOARD_PASSWORD='<VPS 上 AstrBot WebUI 密码>'
python3 /opt/qqbot/scripts/healthcheck.py
```

## 5. 升级

```bash
# AstrBot
sudo -iu qqbot bash -lc 'uv tool upgrade astrbot --python 3.12'
sudo systemctl restart qqbot-astrbot

# NapCat：停服务 -> 替换 AppImage -> 起服务（配置/登录态保留）
sudo systemctl stop qqbot-napcat
sudo -iu qqbot bash -lc 'cd /opt/napcat && curl -fL -o NapCat.AppImage <新版本URL> && chmod +x NapCat.AppImage'
sudo systemctl start qqbot-napcat
```

升级前用 `scripts/backup_data.py` 备份 `/opt/qqbot/data`。

## 6. 排障

| 现象 | 处理 |
|---|---|
| NapCat 启动即退出 | `journalctl -u qqbot-napcat -n 100`；确认 `xvfb`/`xauth`/`libfuse2` 已装 |
| AstrBot 无「适配器已连接」 | 检查 `/opt/napcat/config/onebot11*.json` 的 WS url 是否为 `ws://127.0.0.1:6199/ws` |
| 内存吃紧/被 OOM | 加 swap；调小 `MemoryMax`；编译前停服务 |
| QQ 频繁验证 | 海外 IP 风控；保持环境固定，必要时换国内节点 |
| WebUI 打不开 | 只绑 127.0.0.1，需 SSH 隧道：`ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 user@vps` |
