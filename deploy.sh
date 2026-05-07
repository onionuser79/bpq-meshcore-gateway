#!/usr/bin/env bash
set -euo pipefail

HOST=iw2ohx2
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_DIR="/home/iw2ohx/bpq-meshcore-gateway"

echo ">> rsync $LOCAL_DIR/ -> $HOST:$REMOTE_DIR/"
rsync -az --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'deploy.sh' \
    "$LOCAL_DIR/" "$HOST:$REMOTE_DIR/"
echo ">> done"
