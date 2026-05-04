#!/usr/bin/env bash
# 유진홈센터 전용 텔레그램 봇 + OpenClaw 에이전트(ehcmall) 분리 설정 (OpenClaw 2026.4.x 기준)
# 사용법: bash openclaw/setup_ehcmall_agent.sh
# 사전준비: BotFather에서 새 봇 생성 후 토큰만 준비. 기존 봇 토큰은 openclaw.json에서 자동 읽음.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CFG="$OPENCLAW_HOME/openclaw.json"
WS="$OPENCLAW_HOME/workspace-ehcmall"
TEMPLATE="$SCRIPT_DIR/SOUL_EHCMALL_TEMPLATE.md"

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }

[[ -f "$CFG" ]] || die "설정 파일이 없습니다: $CFG"
[[ -f "$TEMPLATE" ]] || die "템플릿 없음: $TEMPLATE"
command -v openclaw >/dev/null || die "openclaw 명령을 찾을 수 없습니다."
command -v python3 >/dev/null || die "python3가 필요합니다."

BACKUP="$OPENCLAW_HOME/openclaw.json.bak.ehcmall-$(date +%Y%m%d-%H%M%S)"
cp "$CFG" "$BACKUP"
info "백업 완료: $BACKUP"

LEGACY="$(python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.openclaw/openclaw.json")
with open(p, encoding="utf-8") as f:
    d = json.load(f)
tg = d.get("channels", {}).get("telegram", {})
print(tg.get("botToken") or "")
PY
)"

if [[ -z "$LEGACY" ]]; then
  echo "❌ channels.telegram.botToken 이 비어 있습니다. 이미 accounts 로 분리했거나 수동 설정 상태입니다." >&2
  echo "   확인: openclaw channels list / openclaw agents list --bindings" >&2
  exit 1
fi

if openclaw agents list 2>/dev/null | grep -q '^- ehcmall'; then
  read -r -p "에이전트 'ehcmall' 이 이미 있습니다. 계속 진행할까요? [y/N] " a
  [[ "${a:-}" =~ ^[yY]$ ]] || { echo "중단했습니다."; exit 0; }
fi

info "기존 봇 토큰을 Telegram 계정 id **default** 로 등록합니다 (기존 단일 봇과 동일 역할)."
openclaw channels add --channel telegram --token "$LEGACY" --account default

echo ""
read -r -s -p "BotFather에서 만든 유진홈센터 **전용 새 봇** 토큰을 붙여 넣고 Enter: " NEWTOK
echo ""
[[ -n "${NEWTOK:-}" ]] || die "새 토큰이 비었습니다."
# 붙여넣기 시 공백·개행 제거, 형식 검사 (중복 붙여넣기 방지)
NEWTOK="${NEWTOK#"${NEWTOK%%[![:space:]]*}"}"
NEWTOK="${NEWTOK%"${NEWTOK##*[![:space:]]}"}"
NEWTOK="${NEWTOK//[[:space:]]/}"
NEWTOK="$NEWTOK" python3 <<'PY' || die "토큰 형식이 잘못되었습니다. BotFather가 준 '123456789:AAABBB...' 한 줄만 정확히 복사하세요. (한 번만 붙여넣기)"
import os, sys
t = os.environ["NEWTOK"].strip().replace(" ", "")
if t.count(":") != 1:
    print("콜론(:)은 딱 하나여야 합니다. 토큰이 두 번 이어 붙었을 수 있습니다.", file=sys.stderr)
    sys.exit(1)
left, right = t.split(":", 1)
if not left.isdigit() or not right or any(c.isspace() for c in right):
    sys.exit(1)
PY

info "새 봇을 Telegram 계정 id **ehcmall** 로 등록합니다."
openclaw channels add --channel telegram --token "$NEWTOK" --account ehcmall

info "레거시 channels.telegram.botToken 키 제거 (계정으로 이전했으므로)."
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / ".openclaw" / "openclaw.json"
data = json.loads(p.read_text(encoding="utf-8"))
tg = data.setdefault("channels", {}).setdefault("telegram", {})
if "botToken" in tg:
    del tg["botToken"]
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

mkdir -p "$WS"
if [[ ! -f "$WS/SOUL.md" ]]; then
  cp "$TEMPLATE" "$WS/SOUL.md"
  info "작성됨: $WS/SOUL.md (전용 템플릿 복사)"
else
  info "유지됨: $WS/SOUL.md (이미 있음)"
fi

if openclaw agents list 2>/dev/null | grep -q '^- ehcmall'; then
  info "에이전트 ehcmall 존재 — add 생략"
else
  info "에이전트 ehcmall 추가 + telegram:ehcmall 바인딩"
  openclaw agents add ehcmall --workspace "$WS" --bind telegram:ehcmall --non-interactive
fi

info "메인 에이전트 → 기존 봇(telegram:default) 로 라우팅"
if openclaw agents bind --agent main --bind telegram:default 2>/dev/null; then
  :
else
  info "(이미 바인딩되어 있을 수 있음) bindings 확인: openclaw agents bindings"
fi

echo ""
info "현재 에이전트·바인딩:"
openclaw agents list --bindings || true

echo ""
read -r -p "게이트웨이를 지금 재시작할까요? [y/N] " r
if [[ "${r:-}" =~ ^[yY]$ ]]; then
  openclaw gateway restart || info "gateway restart 가 실패했으면 터미널에서 직접 실행하세요."
fi

echo ""
echo "✅ 설정 스크립트 완료."
echo "   • 기존 봇: telegram 계정 **default** → 에이전트 **main**"
echo "   • 유진홈 봇: telegram 계정 **ehcmall** → 에이전트 **ehcmall** ($WS)"
echo "   • 새 봇 DM 시 페어링이 필요하면 예전과 같이 승인하세요."
echo "   • exec 허용: openclaw approvals allowlist add --agent ehcmall \"\$(which python3)\""
echo "   • 문제 시 복구: cp \"$BACKUP\" \"$CFG\" && openclaw gateway restart"
