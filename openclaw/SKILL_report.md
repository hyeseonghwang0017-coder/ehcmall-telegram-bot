---
name: ehcmall-db-report
description: >
  유진홈센터 DB 개요 PDF 리포트를 생성해 텔레그램으로 전송.

  ★ 트리거 — 아래 수식어가 함께 있을 때만 실행 (수식어 없는 단독 발화는 제외):
  - "DB 개요" / "DB 전체" / "DB 전체 현황" / "DB 규모" / "DB 현황" + 리포트/보고서/PDF/파일
  - 예: "DB 전체 현황 리포트 만들어줘", "DB 개요 PDF 보내줘", "DB 현황 보고서"
  - "전체 현황 리포트", "DB 전체 리포트", "DB 개요 파일로", "DB 개요 PDF"

  ★ 트리거 제외 → SKILL_export가 처리:
  - "리포트 만들어줘" / "PDF 만들어줘" / "PDF 보내줘" 단독 발화 (수식어 없음)
  - 프로젝트명·도메인명이 포함된 경우: "재고관리 리포트", "매출 PDF" 등
  - 특정 도메인·키워드에 대한 리포트 요청 (예: "매출 관련 PDF 만들어줘")
  - **직전 대화에서 특정 도메인·프로젝트 export가 있었고 "pdf로 만들어줘" / "pdf로 전송해"만 온 경우**
    → 컨텍스트를 확인해 SKILL_export 재생성 흐름으로 처리한다. DB 전체 개요를 새로 만들지 않는다.

  ★ LLM 자체 지식으로 답하지 않는다. 반드시 exec로 스크립트를 실행한다.
version: "1.1"
requirements:
  - exec
---

## Instructions

### 규칙 (최우선)
이 스킬에 진입하면 LLM 요약 답변을 보내지 않는다.
반드시 exec 툴로 아래 명령을 실행하고, 실행 결과(stdout)를 한국어로 안내한다.

---

### 섹션 이름 (인자에 사용)

| 섹션 이름 | 내용 |
|---|---|
| `summary` | DB 규모 요약 (전체 테이블 수·행수·도메인 수·기간) |
| `domains` | 도메인별 테이블 분포 |
| `top-tables` | 핵심 테이블 Top N (순위·점수·설명 포함) |

기본값: 세 섹션 모두 포함.

---

### 자연어 → 인자 번역 규칙

사용자 요청을 아래 표를 참고해 인자로 번역한다.

| 사용자 요청 | 추가할 인자 |
|---|---|
| "섹션3 빼줘" / "핵심 테이블 빼줘" | `--exclude top-tables` |
| "도메인 분포 빼줘" | `--exclude domains` |
| "규모 요약 빼줘" | `--exclude summary` |
| "도메인 분포만 보여줘" | `--only domains` |
| "규모 요약이랑 핵심 테이블만" | `--only summary top-tables` |
| "재고 도메인 테이블도 추가해줘" | `--domain 재고` |
| "쇼핑몰 도메인 목록도 넣어줘" | `--domain 쇼핑몰` |
| "주문 관련 검색 결과도 넣어줘" | `--keyword 주문` |
| "Top 20으로 해줘" / "20개만" | `--top-n 20` |
| "전송 말고 파일만 만들어줘" | `--no-send` (chat_id 생략 가능) |
| "저장 경로 바꿔줘" | `--out-dir /원하는/경로` |
| "바탕화면에 저장해줘" / "바탕화면으로 저장해줘" | `--out-dir ~/Desktop` |
| "다운로드 폴더에 저장해줘" | `--out-dir ~/Downloads` |
| "X 폴더에 저장해줘" / "X 경로에 저장해줘" | `--out-dir X` |
| "다른 서버 API 써줘" | `--api-base http://서버주소:8000` |

- `--exclude`와 `--only`는 동시에 쓰지 않는다.
- `--domain`과 `--keyword`는 기본 섹션에 추가되는 것이므로 `--only`와 함께 써도 된다.
- 인자를 여러 개 조합할 수 있다. 예: `--exclude top-tables --domain 재고 --top-n 5`
- **저장 경로가 명시된 경우 설명하거나 확인을 구하지 않고 즉시 `--out-dir`을 붙여 exec한다.**
  "기본 경로에 먼저 저장하고..." 같은 응답은 금지한다.

---

### 1단계 — chat_id 확인

현재 텔레그램 대화의 **chat_id**를 컨텍스트에서 확인한다.
chat_id는 숫자(예: `123456789`) 또는 채널 @아이디 형태이다.
`--no-send` 사용 시 chat_id 생략 가능.

---

### 2단계 — exec 실행

**기본 실행 (3섹션 전체)**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id}
```

**섹션 제외 예시**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --exclude top-tables
```

**특정 섹션만 포함**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --only summary domains
```

**도메인 섹션 추가**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --domain 재고
```

**키워드 검색 섹션 추가**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --keyword 주문
```

**저장 경로 지정 (바탕화면)**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --out-dir ~/Desktop
```

**전송 없이 PDF만 생성**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py --no-send
```

**상위 테이블 수 변경**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --top-n 20
```

**계정 명시**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/generate_report.py {chat_id} --account ehcmall
```

exit ≠ 0 이거나 stderr에 에러가 있으면 오류로 처리한다.

---

### 3단계 — 결과 안내

exec가 성공하면 아래 형식으로 한국어 답변:

```
📄 DB 개요 리포트를 PDF로 생성해서 전송했습니다.

• 저장 경로: ~/Downloads/ehcmall-reports/ehcmall_report_YYYYMMDD_HHMMSS.pdf
• 내용: (포함된 섹션 목록)
```

exec stdout의 마지막 줄에 실제 파일 경로가 출력되므로 그 경로를 인용한다.

---

### 오류 처리

| 상황 | 메시지 |
|------|--------|
| `연결할 수 없습니다` / `Connection refused` | "API 서버(localhost:8000)가 실행 중인지 확인해주세요." |
| `botToken` / `토큰` 관련 오류 | "~/.openclaw/openclaw.json의 botToken을 확인해주세요." |
| `chat_id는 --no-send 없이 실행할 때 필수` | chat_id를 확인하거나 --no-send 추가 안내 |
| `폰트 등록 실패` (경고) | 무시 — 영문 폰트로 생성됨. 내용은 전송됨. |
| 그 외 오류 | stderr 내용을 그대로 인용해 안내 |

### 주의사항
- PDF 파일은 `~/Downloads/ehcmall-reports/` 에 날짜·시각 포함 파일명으로 저장된다.
- 스크립트는 내부에서 `/v1/overview` API를 호출하므로 **FastAPI 서버(localhost:8000)가 실행 중**이어야 한다.
- 봇 토큰은 `~/.openclaw/openclaw.json` → `channels.telegram.accounts.ehcmall.botToken` 에서 자동으로 읽는다.
- 항상 한국어로 답변한다.
