---
name: ehcmall-send-file
description: >
  ~/Downloads/ehcmall-reports/ 에 저장된 CSV·PDF 파일을 텔레그램으로 재전송.

  ★ 트리거 — 아래 중 하나라도 해당하면 실행:
  - "아까 만든 파일 보내줘", "방금 파일 다시 보내줘", "파일 다시 전송해줘"
  - "{프로젝트명} 파일 보내줘", "{프로젝트명} CSV/PDF 보내줘"
  - "저장된 파일 보내줘", "최근 파일 보내줘", "마지막 파일 보내줘"
  - 파일 경로나 파일명을 직접 언급하며 전송 요청

  ★ 파일을 새로 생성하지 않는다. 저장된 파일을 찾아 전송하는 것만 한다.
  ★ LLM이 파일을 만들어내거나 내용을 추측하지 않는다.
version: "1.0"
requirements:
  - exec
---

## Instructions

### 규칙 (최우선)
이 스킬에 진입하면 파일을 새로 생성하거나 내용을 답변으로 출력하지 않는다.
반드시 exec로 파일 목록을 확인한 뒤 올바른 파일을 전송한다.

---

## 분기 판단

사용자 메시지에서:
- **경로나 파일명이 명시된 경우** → [바로 전송] 섹션으로 이동
- **프로젝트명·형식·"최근"·"아까" 등 단서가 있는 경우** → [목록 조회 후 선택] 섹션으로 이동
- **단서 없이 그냥 "파일 보내줘"** → [목록 조회 후 선택] 섹션으로 이동

---

## [바로 전송]

파일 경로 또는 파일명이 명시된 경우, 바로 전송한다.
파일명만 주어진 경우 `~/Downloads/ehcmall-reports/{파일명}` 으로 간주한다.

```
exec: python3 $EHCMALL_BOT_DIR/scripts/send_file.py {chat_id} "{파일 절대경로}" --account ehcmall
```

**예:**
```
exec: python3 $EHCMALL_BOT_DIR/scripts/send_file.py 123456789 "$HOME/Downloads/ehcmall-reports/ehcmall_export_재고관리_20260101_120000.csv" --account ehcmall
```

---

## [목록 조회 후 선택]

### 1단계 — 파일 목록 exec

아래 명령으로 저장된 파일 목록을 최신순으로 조회한다.

```
exec: python3 -c "
from pathlib import Path
import datetime, os
d = Path.home() / 'Downloads' / 'ehcmall-reports'
if not d.exists():
    print('REPORT_DIR_NOT_FOUND')
else:
    files = sorted([f for f in d.iterdir() if f.is_file()], key=lambda f: f.stat().st_mtime, reverse=True)[:20]
    if not files:
        print('NO_FILES')
    else:
        for i, f in enumerate(files, 1):
            mt = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            print(f'{i}. {f.name}  [{mt}]  {f}')
"
```

stdout 형식:
```
1. ehcmall_export_재고관리_20260101_120000.csv  [2026-01-01 12:00]  /Users/.../ehcmall-reports/...
2. ehcmall_report_20260101_110000.pdf          [2026-01-01 11:00]  /Users/.../ehcmall-reports/...
...
```

### GPT 파일 선택 (exec 없이 추론)

목록을 바탕으로 사용자가 원하는 파일을 특정한다.

판단 기준:
- 프로젝트명 언급 → 파일명에 해당 키워드가 포함된 파일
- 형식 언급 (CSV / PDF) → 해당 확장자 우선
- "아까", "방금", "최근", "마지막" → 가장 최신 파일 (목록 1번)
- 위 단서가 없거나 후보가 여럿이면 → 목록 상위 5개를 보여주고 «몇 번 파일을 보내드릴까요?» 한 줄 묻는다 (이 경우 2단계로 넘어가지 않고 사용자 응답을 기다림)

### 2단계 — 전송 exec

파일이 특정되면 절대 경로로 전송한다.

```
exec: python3 $EHCMALL_BOT_DIR/scripts/send_file.py {chat_id} "{절대경로}" --account ehcmall
```

exit ≠ 0 이면 stderr 내용을 인용해 안내한다.

---

## 결과 안내

exec stdout 마지막 줄에 `파일 저장 경로: ...` 가 출력된다. 이 값을 사용해 답한다.

```
📤 파일을 전송했습니다.

• 파일명: {파일명}
• 경로: {파일 저장 경로 그대로}
```

---

## 오류 처리

| 상황 | 안내 |
|------|------|
| `REPORT_DIR_NOT_FOUND` | "리포트 저장 경로(~/Downloads/ehcmall-reports/)가 없습니다. 먼저 export나 리포트를 생성해주세요." |
| `NO_FILES` | "저장된 파일이 없습니다. 먼저 리포트를 만들어주세요." |
| `파일을 찾을 수 없습니다` (exit 2) | "해당 파일을 찾을 수 없습니다. 파일 목록을 다시 확인해드릴까요?" |
| `botToken` / `토큰` 관련 | "~/.openclaw/openclaw.json의 botToken을 확인해주세요." |
| 그 외 | stderr 내용을 그대로 인용 |

---

## 주의사항
- `~/Downloads/ehcmall-reports/` 밖의 파일은 전송하지 않는다.
- 파일 내용을 읽거나 요약해서 답변하지 않는다 (파일 자체를 전송하는 것이 목적).
- 항상 한국어로 답변한다.
