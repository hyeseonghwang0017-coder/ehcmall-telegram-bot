#!/usr/bin/env bash
set -e

# EHC Mall Telegram Bot — 초기 설정 스크립트
# 사용법: bash setup.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== EHC Mall Bot 설정 ==="

# 1. 환경변수 등록 (현재 셸 + ~/.zshrc)
export EHCMALL_BOT_DIR="$SCRIPT_DIR"
SHELL_RC="$HOME/.zshrc"
if ! grep -q "EHCMALL_BOT_DIR" "$SHELL_RC" 2>/dev/null; then
    echo "" >> "$SHELL_RC"
    echo "# EHC Mall Bot" >> "$SHELL_RC"
    echo "export EHCMALL_BOT_DIR=\"$SCRIPT_DIR\"" >> "$SHELL_RC"
    echo "✓ EHCMALL_BOT_DIR=$SCRIPT_DIR → $SHELL_RC 에 추가됨"
else
    echo "✓ EHCMALL_BOT_DIR 이미 설정됨"
fi

# 2. Python 의존성 설치
echo ""
echo "패키지 설치 중..."
python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
echo "✓ 패키지 설치 완료"

# 3. OpenClaw SKILL 파일 등록 확인
echo ""
echo "=== 설정 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. source ~/.zshrc  (또는 터미널 재시작)"
echo "  2. ~/.openclaw/openclaw.json 에 botToken 설정"
echo "  3. python3 -m uvicorn api.main:app --reload  (FastAPI 서버 시작)"
echo "  4. openclaw start  (OpenClaw 게이트웨이 시작)"
