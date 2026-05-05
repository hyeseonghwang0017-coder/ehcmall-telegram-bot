# 유진홈센터 DB 설명 봇

텔레그램으로 유진홈센터(EHC Mall) DB 테이블·컬럼을 물어보면 한국어로 설명해주는 봇입니다.  

---

## 동작 구조

```
사용자 (텔레그램)
    │  질문
    ▼
OpenClaw gateway
    │  스킬 실행
    ▼
FastAPI (localhost:8000)
    │  data/ehcmall_index.json 조회
    ▼
LLM → 한국어 답변 → 텔레그램
```

- OpenClaw와 API가 **같은 호스트**에서 돌아야 합니다 (서로 `localhost:8000` 통신).
- API는 사전에 ETL로 생성된 `ehcmall_index.json`만 읽으며, 실제 DB에 직접 접근하지 않습니다.
- 운영 모드는 두 가지:
  - **로컬 (Mac)**: OpenClaw가 사용자 PC에서 돌아 사용자 디스크(`~/Downloads/...`)에 직접 파일을 저장할 수 있다.
  - **서버 (Oracle Free Tier 등)**: Linux 서버에서 PM2로 24/7 운영. 결과물은 텔레그램으로만 전달.

---

## 폴더 구성

| 경로 | 설명 |
|------|------|
| `api/main.py` | FastAPI 서버. `ehcmall_index.json`을 메모리에 로드해 JSON 응답 |
| `requirements.txt` | Python 의존 패키지 (fastapi, uvicorn, reportlab) |
| `catalog_dates.py` | 테이블 기간·날짜 메타 정규화 및 한국어 기간 문구 생성. ETL·API가 동일 규칙을 공유 |
| `data/` | `ehcmall_index.json` 배치 위치 (git에서 제외됨) |
| `openclaw/SKILL_explain.md` | 테이블·컬럼 설명 스킬 |
| `openclaw/SKILL_search.md` | 테이블 검색 스킬 |
| `openclaw/SKILL_export.md` | CSV/PDF export 스킬 정의 (분기·명령 포함) |
| `openclaw/SKILL_report.md` | DB 전체 개요 PDF 리포트 스킬 |
| `openclaw/SKILL_send.md` | 저장된 파일 재전송 스킬 |
| `openclaw/SOUL_EHCMALL_TEMPLATE.md` | 유진홈 전용 에이전트 SOUL 템플릿 |
| `openclaw/skill.json` / `skill_search.json` | 스킬 메타 정의 (OpenClaw용) |
| `openclaw/system_prompt.md` | 에이전트 시스템 프롬프트 |
| `openclaw/plugin-ehcmall-export-gate/` | OpenClaw 플러그인: export 요청 `before_dispatch` 게이트 |
| `scripts/export_tables.py` | 키워드·도메인·직접 지정으로 테이블 수집 → CSV/PDF 생성 → 텔레그램 전송 |
| `scripts/export_pdf.py` | PDF 전용 래퍼. export_tables.py에 인자를 그대로 전달 |
| `scripts/generate_report.py` | DB 전체 개요 PDF 생성 전용 |
| `scripts/send_file.py` | 파일 단독 텔레그램 전송 유틸 |
| `deploy/ecosystem.config.js` | PM2 프로세스 설정 (FastAPI + OpenClaw gateway) |
| `deploy/server_setup.sh` | 서버 초기 셋업 보조 스크립트 |
| `setup.sh` | 로컬(Mac) 초기 셋업 스크립트 |
| `서버시작.command` | macOS에서 API를 더블클릭으로 기동 |

**포함하지 않는 것:** 원본 CSV, ETL 코드(`etl/`), 대량 `descriptions/` 등. 인덱스는 별도로 `data/`에 받아야 합니다.

---

## Export 기능

`scripts/export_tables.py` 는 프로젝트 주제 키워드 또는 도메인을 받아 DB 메타데이터를 수집하고, CSV/PDF 파일로 만들어 텔레그램으로 전송한다.

### 수집 방식

| 방식 | 인자 | 설명 |
|------|------|------|
| 키워드 검색 | 위치 인자 `keyword1 [keyword2 keyword3]` | `/v1/search` API로 관련 테이블 조회 |
| 도메인 전체 | `--domain 도메인명` | `/v1/tables?domain=` API로 특정 도메인 전체 수집 |
| 직접 지정 | `--tables TABLE_A TABLE_B ...` | 테이블명을 직접 나열해 검색 없이 수집 |

### 주요 플래그

| 플래그 | 설명 |
|--------|------|
| `--format csv\|pdf` | 출력 형식 지정 (필수) |
| `--auto-filter` | 검색 후 LLM/휴리스틱으로 관련 테이블 자동 선별 |
| `--summary "..."` | PDF 표지 아래 삽입할 요약 산문 (3~5문장) |
| `--recommendation $'...'` | PDF '추천 구성안' 섹션 텍스트 |
| `--reasons '{"TABLE":"이유"}'` | 테이블별 선택 이유 JSON (PDF '추천 이유' 표에 삽입) |

---

## 최근 변경 (v2.8)

### 도메인 혼입 경고

테이블 수집 완료 후 `sendDocument` 직전에 도메인 분포를 stdout에 출력한다.

- 도메인 1개: `[도메인 분포] 재고: 35개`
- 도메인 2개 이상: `[경고] 도메인 분포: 재고: 35개 | 기준정보: 10개 — 여러 도메인이 섞였습니다`

### summary 자동 텔레그램 전송

PDF 전송 직전, `--summary` 또는 `--recommendation` 값이 있으면 텍스트 메시지를 먼저 발송한다.

- `_send_message(token, chat_id, text)` 신규 추가 (Telegram `sendMessage` API 래퍼)
- `parse_mode` 없이 plain text 전송 (Markdown 400 오류 방지)

### SKILL 분기 체크리스트

`openclaw/SKILL_export.md` frontmatter에 exec 전 3분기 결정 체크리스트를 추가했다.

- `--domain {도메인명}` 사용 조건 명시 (키워드 검색 금지 케이스)
- `--search-json-only` 키워드 검색 조건 명시 (필터링 ON 기본 흐름)
- 필터링 OFF 단일 exec 조건 명시

---

## 서버 배포 (24/7 운영)

Oracle Free Tier 같은 Linux 서버에서 PM2로 항상 켜두는 절차. 사용자 PC가 꺼져 있어도 봇이 응답한다.

### 시스템 의존성

```bash
# Node.js 22 (NodeSource)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Python venv
sudo apt install -y python3-venv python3-pip

# 한글 PDF 폰트 (NanumGothic — generate_report.py / export_tables.py 가 자동 탐색)
sudo apt install -y fonts-nanum

# PM2
sudo npm install -g pm2
```

> **메모리 1GB 환경 (Oracle Free Tier)**: `npm install` 중 OOM이 발생할 수 있어 swap 2GB 미리 추가 권장.
> ```bash
> sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
> sudo mkswap /swapfile && sudo swapon /swapfile
> echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
> ```

### 셋업

```bash
git clone <repo-url> ~/ehcmall-telegram-bot
cd ~/ehcmall-telegram-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

데이터·OpenClaw 설정은 별도 전송한다 (서버에서는 ETL을 돌리지 않는다).

- `data/ehcmall_index.json` — Mac 등에서 scp/rsync로 복사
- `~/.openclaw/` 의 `openclaw.json`, `skills/`, `workspace-ehcmall/`, `agents/`, `identity/` — Mac 환경에서 rsync. Mac 절대 경로(`/Users/...`, `/opt/anaconda3/...`)가 박힌 항목은 서버 경로로 일괄 치환 필요.

### PM2 기동

```bash
pm2 start deploy/ecosystem.config.js   # ehcmall-api + ehcmall-bot 동시 실행
pm2 save
pm2 startup                            # 출력된 sudo 명령을 그대로 한 번 더 실행
```

`pm2 startup` 후 systemd에 등록되면 서버 재부팅에도 자동 복구된다.

### 운영 점검

```bash
pm2 status                # 프로세스 상태
pm2 logs ehcmall-bot --raw  # 실시간 로그
```

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

