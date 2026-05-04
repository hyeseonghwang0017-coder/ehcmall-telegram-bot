# 유진홈센터 DB 설명 봇 — 텔레그램 운영용 최소 패키지

**표·컬럼 설명(메타데이터)** 를 `ehcmall_index.json` 에서 찾아 JSON으로 돌려주는 **로컬 API**와, OpenClaw에 넣는 **스킬·템플릿**만 모은 폴더입니다.  
원본 CSV·ETL·대량 `descriptions/` 등은 포함하지 않습니다.

## 포함된 것

| 경로 | 역할 |
|------|------|
| `api/` | FastAPI (`localhost:8000`) |
| `catalog_dates.py` | API에서 import (루트에 고정) |
| `openclaw/` | 스킬 문서·`setup_ehcmall_agent.sh` 등 |
| `서버시작.command` | macOS에서 API 기동 |

## 준비

1. **`data/ehcmall_index.json`** 을 받아 `data/` 아래에 둡니다. (`data/README.md` 참고)
2. Python 3.11+ 권장  
   `pip install -r api/requirements.txt`
3. API 실행  
   - macOS: `서버시작.command` 더블클릭  
   - 터미널: `INDEX_PATH=./data/ehcmall_index.json python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000`
4. `curl http://localhost:8000/health` 로 로드된 테이블 수 확인
5. OpenClaw에 스킬 설치·SOUL 규칙·텔레그램 연결은 **상위 저장소 README**의 「다른 컴퓨터에서 사용하기」「유진홈센터 전용 에이전트」절을 그대로 따르되, 경로만 이 폴더 기준으로 바꿉니다.

```bash
cp openclaw/SKILL_explain.md ~/.openclaw/skills/ehcmall-db-explain/SKILL.md
cp openclaw/SKILL_search.md  ~/.openclaw/skills/ehcmall-db-search/SKILL.md
```


---

전체 설계·ETL·온톨로지 설명은 상위 디렉터리의 `README.md` 를 참고하세요.
