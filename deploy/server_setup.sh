#!/usr/bin/env bash
# EHC Mall Bot — Oracle Free Tier Ubuntu 22.04 서버 초기 설정
# 사용법: bash server_setup.sh
set -e

REPO_URL="https://github.com/hyeseonghwang0017-coder/ehcmall-telegram-bot.git"
INSTALL_DIR="$HOME/ehcmall-telegram-bot"

echo "=== [1/6] 시스템 패키지 설치 ==="
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git curl

echo ""
echo "=== [2/6] Node.js 20 설치 ==="
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node $(node -v) / npm $(npm -v)"

echo ""
echo "=== [3/6] OpenClaw 설치 ==="
sudo npm install -g openclaw
echo "openclaw $(openclaw --version 2>/dev/null || echo '설치됨')"

echo ""
echo "=== [4/6] PM2 설치 ==="
sudo npm install -g pm2
pm2 --version

echo ""
echo "=== [5/6] 저장소 클론 및 Python 패키지 설치 ==="
if [ -d "$INSTALL_DIR" ]; then
    echo "이미 있음 → git pull"
    git -C "$INSTALL_DIR" pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
python3 -m pip install -r requirements.txt --quiet
python3 -m pip install -r api/requirements.txt --quiet 2>/dev/null || true

echo ""
echo "=== [6/6] 환경변수 등록 (~/.bashrc) ==="
INDEX_PATH_VALUE="$INSTALL_DIR/data/ehcmall_index.json"

add_env() {
    local key="$1" val="$2"
    if ! grep -q "$key" ~/.bashrc 2>/dev/null; then
        echo "export $key=\"$val\"" >> ~/.bashrc
        echo "✓ $key 추가됨"
    else
        echo "✓ $key 이미 있음"
    fi
}
add_env "EHCMALL_BOT_DIR" "$INSTALL_DIR"
add_env "INDEX_PATH" "$INDEX_PATH_VALUE"

export EHCMALL_BOT_DIR="$INSTALL_DIR"
export INDEX_PATH="$INDEX_PATH_VALUE"

echo ""
echo "========================================"
echo "설치 완료. 다음 단계를 순서대로 실행하세요:"
echo ""
echo "1) 데이터 파일 전송 (맥북 터미널에서):"
echo "   scp ~/Downloads/ehcmall/ehcmall-telegram-bot/data/ehcmall_index.json \\"
echo "       ubuntu@<서버IP>:$INSTALL_DIR/data/"
echo ""
echo "2) 봇 토큰 설정:"
echo "   mkdir -p ~/.openclaw"
echo "   nano ~/.openclaw/openclaw.json"
echo "   → 아래 형식으로 입력:"
cat <<'JSON'
   {
     "channels": {
       "telegram": {
         "accounts": {
           "ehcmall": {
             "botToken": "여기에_봇_토큰_입력"
           }
         }
       }
     }
   }
JSON
echo ""
echo "3) OpenClaw SKILL 파일 연결:"
echo "   openclaw skill add $INSTALL_DIR/openclaw"
echo ""
echo "4) PM2로 서비스 시작:"
echo "   cd $INSTALL_DIR"
echo "   pm2 start deploy/ecosystem.config.js"
echo "   pm2 save"
echo "   pm2 startup  (출력된 명령을 복사해서 실행)"
echo ""
echo "5) OpenClaw OAuth 인증:"
echo "   pm2 logs ehcmall-bot --lines 30"
echo "   → 출력된 URL을 맥북 브라우저에서 열어 Google 로그인"
echo ""
echo "6) 방화벽 열기 (Oracle 보안 목록에서도 8000 인바운드 허용 필요):"
echo "   sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT"
echo "========================================"
