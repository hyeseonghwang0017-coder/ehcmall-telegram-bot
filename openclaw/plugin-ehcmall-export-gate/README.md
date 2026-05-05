# ehcmall-export-gate (OpenClaw 플러그인)

텔레그램 `accountId=ehcmall` + 에이전트 `ehcmall` 세션에서, 사용자 메시지가 **프로젝트별 테이블 메타 CSV/PDF export**로 보일 때의 동작을 제어합니다.

- **`beforeDispatchMode` (기본값 `agent`)**: 게이트가 **가로채지 않고** 메시지를 **대화 LLM**으로 넘깁니다. 에이전트는 `SKILL_export.md`대로 `--search-json-only`로 `/v1/search` JSON을 exec로 받은 뒤 후보 안에서만 테이블을 고르고, `--tables` + `--reasons`로 export합니다.
- **`beforeDispatchMode`: `auto-export`**: 기존처럼 **`before_dispatch`** 에서 `export_tables.py --auto-filter`만 실행하고 그 턴은 채팅 모델을 호출하지 않습니다. (게이트웨이에 Anthropic/OpenAI 키가 있어야 스크립트 내 LLM 선별 품질이 나옵니다.)

- 실행 방식: `export_tables.py`에 **`--auto-filter`** — 검색 후보 중 **소수 테이블만 선별**하고, **`selection_reason`** 을 채워 PDF/CSV 생성 후 텔레그램 전송.
- 선별 백엔드(기본 **`--filter-backend auto`**): **`ANTHROPIC_API_KEY`** 가 있으면 Anthropic, 없고 **`OPENAI_API_KEY`** 가 있으면 OpenAI, 둘 다 없으면 **API 키 없는 휴리스틱**(순위·점수·이름 패턴·요청 단어 겹침). 품질은 LLM보다 낮을 수 있음.
- LLM을 쓰려면 게이트웨이 프로세스 환경에 해당 키를 넣습니다(OpenClaw를 띄우는 셸/`launchd` 등에 `export`).
- **DB 전체 개요 PDF**(`generate_report.py`)로 보이는 문장은 휴리스틱으로 **제외**합니다.

## 설치

1. 경로는 본인 Mac에 맞게 `index.mjs` 상단 기본값 또는 `openclaw.json` 플러그인 설정으로 조정합니다.
2. 게이트웨이가 있는 머신에서 (로컬 경로는 `--link` 권장). `child_process` 사용으로 **기본 설치가 차단**되므로 아래처럼 `--dangerously-force-unsafe-install` 가 필요합니다.

```bash
openclaw plugins install --link --dangerously-force-unsafe-install \
  "$EHCMALL_BOT_DIR/openclaw/plugin-ehcmall-export-gate"
```

3. `~/.openclaw/openclaw.json` 의 `plugins.entries` 에 다음을 추가(또는 병합)합니다:

```json
"ehcmall-export-gate": {
  "enabled": true,
  "config": {
    "beforeDispatchMode": "agent",
    "pythonPath": "python3",
    "exportScriptPath": "$EHCMALL_BOT_DIR/scripts/export_tables.py",
    "telegramAccountId": "ehcmall",
    "openclawAccount": "ehcmall"
  }
}
```

게이트에서만 끝내고 싶으면 `"beforeDispatchMode": "auto-export"` 로 바꿉니다.

4. `openclaw gateway restart`

## 주의

- `agents.list[].skills` 에 이 플러그인 id를 넣는 것이 아니라 **`plugins.install` + `plugins.entries`** 입니다.
- 휴리스틱이 **너무 넓으면** 일반 질의도 가로챌 수 있으니, 문제가 있으면 `wantsProjectTableExport` 조건을 조이세요.
