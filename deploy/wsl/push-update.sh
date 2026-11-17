#!/bin/bash
# From the development machine: copy changed repository files to the PC's WSL app folder and restart bothost.
#   deploy/wsl/push-update.sh bothost/app.py bothost/tools.py ...
# Needs an ssh host alias "pc" (Windows OpenSSH, default shell cmd.exe) and Python on the PC's PATH.
# The tarball goes through D:\qqbot-bothost\packages because the WSL side reads Windows drives under /mnt/d.
set -euo pipefail
[ $# -gt 0 ] || { echo "usage: $0 <repo-relative files...>"; exit 2; }
cd "$(git rev-parse --show-toplevel)"
PKG='D:\qqbot-bothost\packages\update.tgz'
tar czf - "$@" | timeout 120 ssh -o BatchMode=yes pc \
  "python -c \"import sys,shutil; shutil.copyfileobj(sys.stdin.buffer, open(r'$PKG','wb'))\""
timeout 120 ssh -o BatchMode=yes pc "wsl -d qqbot -u bot -- bash -c 'cd /home/bot/qqbot/app && tar -xzf /mnt/d/qqbot-bothost/packages/update.tgz && rm /mnt/d/qqbot-bothost/packages/update.tgz && echo unpacked'"
# Stopping the process is enough: the scheduled task restarts it within a minute.
timeout 60 ssh -o BatchMode=yes pc "wsl -d qqbot -u bot -- bash -c 'pkill -f \"python -m bothost\" && echo stopped; true'"
echo "bothost will be restarted by QQBot-bothost within a minute; check ~/qqbot/logs/bothost.log"
