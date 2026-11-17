#!/bin/bash
# Run as the bot user: directories, the Python venv, dsh and yt-dlp. $1 is an unpacked copy of the repository.
set -euo pipefail
SRC=${1:?usage: setup-bot.sh <repository copy>}
B=/home/bot/qqbot
DSH=0.2.1-rc.4   # deploy/dsh/handoff.mjs relies on this version's internals; rerun tests/bothost before changing it

mkdir -p $B/app $B/data $B/logs $B/secrets $B/dsh $B/workspace
chmod 700 $B/secrets
cp -r "$SRC"/. $B/app/

python3 -m venv $B/venv
$B/venv/bin/pip install -q --disable-pip-version-check -r $B/app/bothost/requirements.txt yt-dlp pytest
$B/venv/bin/python -c 'import mcp, uvicorn, numpy, jieba, curl_cffi, patchright; print("python deps ok")'

cd $B/dsh
for i in 1 2 3; do npm install --no-fund --no-audit --loglevel=error "@deepseek-ai/dsh@$DSH" && break; sleep 5; done
node $B/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js --version

[ -f $B/config.json ] || cp $B/app/deploy/wsl/config.example.json $B/config.json
[ -f $B/run.sh ] || { cp $B/app/deploy/wsl/run.sh.example $B/run.sh; chmod 755 $B/run.sh; }
echo "done: fill $B/config.json, put keys in $B/secrets/, data files in $B/data/"
