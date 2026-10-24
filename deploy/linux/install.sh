#!/usr/bin/env bash
# One-shot VPS bring-up for the AstrBot + NapCat stack.
# Prereq: repo uploaded to /opt/qqbot (or anywhere), Docker Engine + compose plugin installed,
#         .env created from .env.example and filled in, data/ migrated (see docs/migration-vps.md).
#
# Run with:  bash deploy/linux/install.sh
set -euo pipefail

cd "$(dirname "$0")/../.."
echo "repo: $(pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Engine first (https://docs.docker.com/engine/install/)." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose plugin not found." >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "ERROR: .env missing. Run: cp .env.example .env && edit it." >&2
  exit 1
fi
if [ ! -d data ]; then
  echo "WARN: data/ missing; AstrBot will start with a fresh profile (WebUI password/chat history lost)."
fi

# Load compose variables (NAPCAT_UID / GID / token / API keys).
set -a
# shellcheck disable=SC1091
. ./.env
set +a

mkdir -p data runtime/napcat runtime/ntqq
if [ -n "${NAPCAT_UID:-}" ] && [ -n "${NAPCAT_GID:-}" ]; then
  chown -R "${NAPCAT_UID}:${NAPCAT_GID}" runtime || echo "WARN: chown failed (run as root or matching owner)"
fi

echo "== docker compose pull =="
docker compose pull
echo "== docker compose up -d =="
docker compose up -d
echo "== docker compose ps =="
docker compose ps

cat <<'EOF'

Next steps:
  1. SSH tunnel:  ssh -L 6185:127.0.0.1:6185 -L 6099:127.0.0.1:6099 user@vps
  2. NapCat login: http://127.0.0.1:6099/webui?token=<NAPCAT_WEBUI_TOKEN>  (scan QR with the bot account)
  3. AstrBot:      http://127.0.0.1:6185
  4. Verify logs:  docker compose logs -f astrbot | grep -E "适配器已连接|Loading model"
EOF
