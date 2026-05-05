---
name: ehcmall-db-search
description: >
  유진홈센터 DB에서 테이블을 검색할 때 실행.
  "매출 관련 테이블 찾아줘", "재고 테이블이 뭐가 있어", "회원 테이블 알려줘",
  "어떤 테이블이 있어", "테이블 목록", "관련 테이블 검색" 등의 표현 포함.
  특정 테이블명을 모르고 도메인이나 키워드로 찾는 경우에 실행.
version: "1.0"
requirements:
  - exec
---

## Instructions

### 1단계 — 검색어·도메인·호출 차수

사용자 메시지에서 검색 키워드를 추출한다. 질문에 도메인이 있으면 아래 exec에서 `domain`에 넣는다.

**호출 차수 (중요)**

- **첫 질의**(키워드로 관련 테이블을 묻는 일반 질문): API에 **`limit=10`**만 넣어 호출한다. 사용자에게도 **최대 10건**까지만 보여 준다.
- **후속 질의**(같은 주제로 사용자가 더 보여 달라고 할 때 — 예: «더», «전부», «나머지», «다 출력», «계속»): 직전에 쓴 **같은 검색어·같은 domain**(있었다면)으로 **`limit=250`**(상한)까지 다시 호출하고, 응답에 나온 **전체**를 테이블명 위주로 출력한다. 스니펫은 길어지면 이름만 나열해도 된다.
- 직전 검색 맥락이 없으면 «어떤 키워드로 더 보실지» 한 줄 묻는다.

### 2단계 — exec 호출 (python3 사용)

**키워드 검색 (첫 질의 — limit 10):**
```
exec: python3 -c "import urllib.request, urllib.parse; p=urllib.parse.urlencode({'q':'{검색어}','limit':'10'}); r=urllib.request.urlopen('http://127.0.0.1:8000/v1/search?'+p); print(r.read().decode())"
```

**키워드 검색 (더 보기 — limit 250):**
```
exec: python3 -c "import urllib.request, urllib.parse; p=urllib.parse.urlencode({'q':'{검색어}','limit':'250'}); r=urllib.request.urlopen('http://127.0.0.1:8000/v1/search?'+p); print(r.read().decode())"
```

**도메인까지 지정 (예: 쇼핑몰에서만 프로모션 관련 테이블):**  
질문에 도메인이 있으면 `domain` 쿼리를 넣는다. 생략하면 다른 도메인이 먼저 상한을 채워 원하는 도메인 결과가 거의 안 나올 수 있다.

• 첫 질의: `limit=10`  
• 더 보기: `limit=250`

```
exec: python3 -c "import urllib.request, urllib.parse; p=urllib.parse.urlencode({'q':'{검색어}','domain':'{도메인}','limit':'10'}); r=urllib.request.urlopen('http://127.0.0.1:8000/v1/search?'+p); print(r.read().decode())"
```

```
exec: python3 -c "import urllib.request, urllib.parse; p=urllib.parse.urlencode({'q':'{검색어}','domain':'{도메인}','limit':'250'}); r=urllib.request.urlopen('http://127.0.0.1:8000/v1/search?'+p); print(r.read().decode())"
```

**도메인 전체 목록:**
```
exec: python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/v1/domains'); print(r.read().decode())"
```

exit ≠ 0 이면 "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."로 처리한다.

### 3단계 — 응답 포맷

```
🔍 '{검색어}' 관련 테이블 ({count}건):

• {table} [{domain}] — {description_snippet}
• ...

💡 상세 조회: 테이블명을 말씀해주세요 (예: "{table} 설명해줘")
더 많이 필요하면 「더 보여줘」라고 해주세요 (같은 검색으로 최대 250건까지).
```

- 결과가 없으면 "검색 결과가 없습니다. 다른 키워드로 시도해보세요"라고 안내한다.
- **첫 답**에서 JSON `count`가 **10**이면, 문장 한 줄로 «아직 더 있을 수 있으니 더 보여 달라고 하면 이어서 검색합니다»라고 안내할 수 있다. `count`가 10 미만이면 그 안내는 생략한다.
- **250건(full 호출) 후에도 `count`가 250**이면 «API 상한(250건)까지 표시했으며, 그 외 후보는 도메인별 목록(`/v1/tables`)이나 검색어를 좁혀 주세요»라고 안내한다.
- 항상 한국어로 답변한다.
