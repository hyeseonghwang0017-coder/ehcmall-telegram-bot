#!/bin/bash
# 더블클릭 시 API 서버 실행 (텔레그램 봇·OpenClaw가 붙는 로컬 창구)

cd "$(dirname "$0")"

echo "================================================"
echo "  EHC Mall DB 메타데이터 API (포트 8000)"
echo "================================================"
echo ""

if [ ! -f "data/ehcmall_index.json" ]; then
    echo "❌  data/ehcmall_index.json 이 없습니다."
    echo "    data/README.md 를 읽고 인덱스를 받아 넣은 뒤 다시 실행하세요."
    exit 1
fi

if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "의존성 설치 중... (최초 1회)"
    pip3 install -r api/requirements.txt --quiet
fi

if lsof -ti:8000 >/dev/null 2>&1; then
    echo "⚠️  포트 8000 사용 중 — 기존 프로세스 종료"
    kill $(lsof -ti:8000) 2>/dev/null || true
    sleep 1
fi

echo ""
echo "✅  서버 시작 — 텔레그램/OpenClaw 쪽에서 localhost:8000 호출 가능"
echo "   확인: curl http://localhost:8000/health"
echo "   종료: 이 창 닫기"
echo ""

INDEX_PATH=./data/ehcmall_index.json python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000
