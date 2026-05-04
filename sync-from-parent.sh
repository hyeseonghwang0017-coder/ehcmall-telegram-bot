#!/usr/bin/env bash
# ehcmall-telegram-bot 이 ehcmall 저장소의 하위 폴더일 때: 상위에서 런타임 파일만 다시 복사
set -euo pipefail
PARENT="$(cd "$(dirname "$0")/.." && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "From: $PARENT"
echo "To:   $HERE"
cp "$PARENT/catalog_dates.py" "$HERE/"
cp "$PARENT/api/main.py" "$PARENT/api/requirements.txt" "$HERE/api/"
cp "$PARENT/openclaw/"* "$HERE/openclaw/"
echo "Done."
