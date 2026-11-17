#!/bin/bash
# Run once as root in a freshly imported Ubuntu 24.04 WSL distro: system packages, Node, Chrome, the bot user,
# wsl.conf and fixed DNS. Then `wsl --terminate qqbot` so wsl.conf takes effect.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
NODE=v24.19.0

# WSL's generated resolv.conf failed intermittently on the user's PC; use fixed public resolvers.
rm -f /etc/resolv.conf
printf 'nameserver 223.5.5.5\nnameserver 119.29.29.29\noptions timeout:2 attempts:3 rotate\n' > /etc/resolv.conf
printf '[user]\ndefault=bot\n[boot]\nsystemd=false\n[network]\ngenerateResolvConf=false\n' > /etc/wsl.conf

apt-get update -q
apt-get install -y -q python3-venv python3-pip zstd ffmpeg xvfb ca-certificates curl xz-utils git fonts-noto-cjk

F=node-$NODE-linux-x64.tar.xz
cd /tmp
curl -fsSL -o $F https://nodejs.org/dist/$NODE/$F
curl -fsSL https://nodejs.org/dist/$NODE/SHASUMS256.txt | grep " $F\$" | sha256sum -c -
tar -xJf $F -C /opt
for b in node npm npx; do ln -sf /opt/node-$NODE-linux-x64/bin/$b /usr/local/bin/$b; done
rm -f $F

# The browser tier of the page reader and the B站 cookie fallback of the video reader need a real Chrome.
# If dl.google.com is too slow, copy a .deb in by hand and pass its path as $1.
DEB=${1:-}
if [ -z "$DEB" ]; then DEB=/tmp/chrome.deb; curl -fsSL -o $DEB https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; fi
apt-get install -y -q "$DEB"
google-chrome --version

id bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot
echo "done: now run 'wsl --terminate qqbot' on Windows, then setup-bot.sh as bot"
