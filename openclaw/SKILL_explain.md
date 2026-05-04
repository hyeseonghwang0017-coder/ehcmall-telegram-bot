---
name: ehcmall-db-explain
description: >
  유진홈센터(EHC Mall) DB 테이블 또는 컬럼에 대한 모든 질문에 실행.

  ★ 핵심 트리거 — 아래 중 하나라도 해당하면 무조건 실행:
  - 대문자+언더바 패턴 코드명 언급: SA_SALE_DETAIL, IN_RECVPAY, BA_CCPY, AC_CSTMR 등
  - SA_ / IN_ / BA_ / AC_ / TM_ / CM_ / IF_ / BT_ / M_ 로 시작하는 이름
  - "이 테이블", "테이블 설명", "테이블 구조", "컬럼이 뭐야", "DB에 뭐 저장해"
  - "뭐야", "뭔지", "설명해줘", "알려줘" + 테이블명 조합

  ★ LLM 자체 지식으로 절대 답하지 않는다. 반드시 exec로 API를 호출한다.
version: "1.0"
requirements:
  - exec
---

## Instructions

### 규칙 (최우선)
이 스킬에 진입하면 LLM 자체 지식으로 답변하지 않는다.
반드시 exec 툴로 아래 명령을 실행하고 그 JSON 응답만 근거로 한국어로 답한다.

**금지 문구**: `주요 컬럼`, `columns_preview 최대 30개`, `미리보기`, `상위 N개만` 등 구버전 헤더를 쓰지 않는다.

**블록 순서**: (1) **`reply_intro_block`** 통째 출력 — 순위·점수·행 수·컬럼 수·기간 포함, 생략 금지 (2) **`reply_description_block`** 통째 출력 (3) 선택 부연 (4) **`reply_column_heading`** + 컬럼 전체.

**설명 블록 고정**: **`reply_description_block`**을 **편집·요약·불릿화 없이 통째로** 출력한다 (줄바꿈 포함). 불릿 요약으로 대체 금지.

**추측 금지**: 테이블명 `_TMP` 등만 보고 임시·작업용 여부를 추측하지 않는다 (JSON·카탈로그에 없으면 언급 금지).

**헤더 고정**: JSON의 `reply_column_heading` 값을 **수정 없이 그대로** 출력한 뒤 컬럼 목록을 이어 쓴다.

### 1단계 — 테이블명 추출

사용자 메시지에서 테이블명을 추출한다.
- 대문자+언더바 패턴 (예: `SA_SALE_DETAIL`, `IN_RECVPAY_MTH_CLOSE_PARTITION`)
- 테이블명이 없으면 ehcmall-db-search 스킬로 연결한다.

### 2단계 — exec 호출 (python3 사용)

**테이블 전체 조회:**
```
exec: /opt/anaconda3/bin/python3 -c "import urllib.request, sys; r=urllib.request.urlopen('http://127.0.0.1:8000/v1/explain?table={테이블명}'); print(r.read().decode())"
```

**특정 컬럼 조회 (컬럼 코드가 언급된 경우):**
```
exec: /opt/anaconda3/bin/python3 -c "import urllib.request, sys; r=urllib.request.urlopen('http://127.0.0.1:8000/v1/explain?table={테이블명}&column={컬럼코드}'); print(r.read().decode())"
```

exit ≠ 0 이거나 stderr에 에러가 있으면 오류로 처리한다.
응답에 `"detail"` 키가 있으면 404 오류로 처리한다.

### 3단계 — 응답 포맷 (텔레그램 마크다운)

JSON 응답을 받아 아래 형식으로 출력한다:

```
{reply_intro_block 전체 — JSON에서 복사, 수정·생략 금지}

{reply_description_block 전체 — JSON에서 복사, 수정 금지}

(선택) 위 설명 블록 아래에만 부연

{reply_column_heading}  ← JSON 필드 값 그대로
  • {code} → {label 또는 라벨 없으면 코드만}
  (텔레그램 글자 수 한도로 한 번에 다 못 넣으면 이어서 메시지로 나눔)
```

### 오류 처리
- 404 (`"detail"` 포함): "해당 테이블을 찾지 못했습니다. 검색해드릴까요?"
- 연결 실패: "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."
- 어떤 경우에도 LLM 자체 지식으로 테이블을 추측·설명하지 않는다.

### 주의사항
- **`reply_intro_block`**(순위·점수·행 수·기간)과 **`reply_description_block`**을 반드시 위 순서로 통째 인용한다.
- PK/FK 조인 관계: "현재 버전에서는 조인 관계 정보가 포함되어 있지 않습니다"
- 실제 데이터 값이나 개인정보는 절대 언급하지 않는다.
- 항상 한국어로 답변한다.
