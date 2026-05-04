# 유진홈센터 DB 설명 봇

텔레그램으로 유진홈센터(EHC Mall) DB 테이블·컬럼을 물어보면 한국어로 설명해주는 봇입니다.  
상위 `ehcmall` 저장소 중 **실제 운영에 필요한 것만** 추린 최소 패키지입니다.

---

## 동작 구조

```
사용자 (텔레그램)
    │  질문
    ▼
OpenClaw (이 PC)
    │  스킬 실행
    ▼
FastAPI (localhost:8000)
    │  data/ehcmall_index.json 조회
    ▼
LLM → 한국어 답변 → 텔레그램
```

- OpenClaw와 API가 **같은 PC**에서 돌아야 합니다.
- API는 사전에 ETL로 생성된 `ehcmall_index.json`만 읽으며, 실제 DB에 직접 접근하지 않습니다.

---

## 폴더 구성

| 경로 | 설명 |
|------|------|
| `api/main.py` | FastAPI 서버. `ehcmall_index.json`을 메모리에 로드해 JSON 응답 |
| `api/requirements.txt` | 의존 패키지 (fastapi, uvicorn) |
| `catalog_dates.py` | 테이블 기간·날짜 메타 정규화 및 한국어 기간 문구 생성. ETL·API가 동일 규칙을 공유 |
| `data/` | `ehcmall_index.json` 배치 위치 (git에서 제외됨) |
| `openclaw/SKILL_explain.md` | 테이블·컬럼 설명 스킬 |
| `openclaw/SKILL_search.md` | 테이블 검색 스킬 |
| `openclaw/SOUL_EHCMALL_TEMPLATE.md` | 유진홈 전용 에이전트 SOUL 템플릿 |
| `openclaw/setup_ehcmall_agent.sh` | OpenClaw 에이전트·봇 연결 자동 설정 스크립트 |
| `openclaw/skill.json` / `skill_search.json` | 스킬 메타 정의 (OpenClaw용) |
| `openclaw/system_prompt.md` | 에이전트 시스템 프롬프트 |
| `서버시작.command` | macOS에서 API를 더블클릭으로 기동 |
| `sync-from-parent.sh` | 상위 저장소에서 변경된 파일을 이 패키지로 동기화 |

**포함하지 않는 것:** 원본 CSV, ETL 코드(`etl/`), 대량 `descriptions/` 등. 인덱스는 별도로 `data/`에 받아야 합니다.

---

## API 엔드포인트

서버가 뜨면 `http://localhost:8000/docs` 에서 전체 스펙을 확인할 수 있습니다.

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /v1/explain?table=테이블명` | 테이블 메타(순위·행수·기간·컬럼 전체) 조회 |
| `GET /v1/explain?table=T&column=C` | 특정 컬럼의 한글 라벨 조회 |
| `GET /v1/search?q=검색어` | 테이블명·도메인·설명 키워드 검색 |
| `GET /v1/domains` | 업무 도메인 목록 및 테이블 수 |
| `GET /v1/tables?domain=도메인명` | 도메인 소속 테이블 전체 목록 |
| `GET /v1/overview` | DB 전체 개요 (규모·도메인 분포·상위 테이블) |
| `GET /health` | 서버 상태 및 로드된 테이블 수 확인 |

