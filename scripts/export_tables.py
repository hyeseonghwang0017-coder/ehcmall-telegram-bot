#!/usr/bin/env python3
"""
export_tables.py — 프로젝트 주제 키워드를 받아 관련 DB 테이블 메타데이터를
CSV 또는 PDF 리포트로 만들어 텔레그램으로 전송.

사용법:
    # 키워드 검색 후 export (기존):
    python3 export_tables.py <chat_id> <keyword> [keyword2 keyword3] \\
        --format csv|pdf [--project "프로젝트명"] [--account ehcmall]

    # 테이블 직접 지정 후 export (필터링 2단계):
    python3 export_tables.py <chat_id> --tables TABLE_A TABLE_B ... \\
        --format csv|pdf [--project "프로젝트명"] [--account ehcmall]

    # 검색 결과만 출력 (1단계 GPT 필터링용, 사람이 읽기 쉬운 텍스트):
    python3 export_tables.py --search-only <keyword> [keyword2 keyword3]

    # 검색 결과를 /v1/search JSON 그대로(dedupe) stdout에 출력 (대화 LLM·에이전트용):
    python3 export_tables.py --search-json-only <keyword> [keyword2 keyword3]

    # 검색 후 선별+export (키 없으면 휴리스틱, 있으면 LLM):
    python3 export_tables.py <chat_id> <kw1> [kw2 kw3] --format pdf \\
        --auto-filter [--filter-backend auto|anthropic|openai|heuristic] [--max-picks 12] ...

동작:
    1. 키워드별로 /v1/search?q=&limit=250 호출 → 결과 dedupe(테이블명 기준)
       (--tables 지정 시 검색 건너뜀)
    2. 각 테이블에 대해 /v1/explain?table= 호출 → 전체 상세(컬럼 포함) 수집
    3. 형식에 따라 CSV 또는 PDF 생성 → ~/Downloads/ehcmall-reports/ 저장
    4. Telegram sendDocument API로 파일 전송
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ── reportlab ────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── 상수 ─────────────────────────────────────────────────────────
API_BASE = "http://127.0.0.1:8000"
ANTHROPIC_API_BASE = "https://api.anthropic.com"
OPENAI_API_DEFAULT = "https://api.openai.com/v1"
FILTER_MODEL = "claude-haiku-4-5-20251001"
OPENAI_FILTER_MODEL_DEFAULT = "gpt-4o-mini"
SEARCH_LIMIT = 250
FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
FONT_NAME = "Korean"
REPORT_DIR = Path.home() / "Downloads" / "ehcmall-reports"
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
TG_API_BASE = "https://api.telegram.org"

CSV_COLUMNS = [
    "table_name", "domain", "rank", "score", "row_count",
    "column_count", "data_size_mb", "period",
    "description", "columns", "selection_reason",
]


# ── 폰트 등록 ────────────────────────────────────────────────────
def _register_font() -> None:
    try:
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
        pdfmetrics.registerFont(TTFont(FONT_NAME + "-Bold", FONT_PATH))
        pdfmetrics.registerFont(TTFont(FONT_NAME + "-Italic", FONT_PATH))
        registerFontFamily(
            FONT_NAME,
            normal=FONT_NAME,
            bold=FONT_NAME + "-Bold",
            italic=FONT_NAME + "-Italic",
            boldItalic=FONT_NAME + "-Bold",
        )
    except Exception as e:
        print(f"[경고] 한국어 폰트 등록 실패: {e}", file=sys.stderr)
        print("[경고] 영문 폰트로 대체합니다.", file=sys.stderr)


# ── 봇 토큰 조회 ─────────────────────────────────────────────────
def _load_bot_token(account: str) -> str:
    if not OPENCLAW_CONFIG.exists():
        raise FileNotFoundError(f"OpenClaw 설정 파일이 없습니다: {OPENCLAW_CONFIG}")
    with open(OPENCLAW_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    accounts = cfg["channels"]["telegram"]["accounts"]
    entry = accounts.get(account) or accounts.get("default") or {}
    token = (entry.get("botToken") or "").strip()
    if not token:
        raise ValueError(
            f"텔레그램 봇 토큰을 찾을 수 없습니다 (account={account}). "
            f"~/.openclaw/openclaw.json의 channels.telegram.accounts.{account}.botToken 확인"
        )
    return token


# ── HTTP ─────────────────────────────────────────────────────────
def _http_get_json(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _search(keyword: str) -> list[dict]:
    qs = urllib.parse.urlencode({"q": keyword, "limit": str(SEARCH_LIMIT)})
    return _http_get_json(f"{API_BASE}/v1/search?{qs}").get("results", [])


def _explain(table_name: str) -> dict:
    qs = urllib.parse.urlencode({"table": table_name})
    return _http_get_json(f"{API_BASE}/v1/explain?{qs}")


# ── 데이터 수집 ──────────────────────────────────────────────────
def _search_dedupe(keywords: Iterable[str]) -> list[str]:
    """키워드별 search → 테이블명 dedupe 목록 반환."""
    seen_order: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        try:
            hits = _search(kw)
        except Exception as e:
            print(f"[경고] 검색 실패 (q={kw}): {e}", file=sys.stderr)
            continue
        for hit in hits:
            name = hit.get("table")
            if name and name not in seen:
                seen.add(name)
                seen_order.append(name)
    return seen_order


def _snippet(s: str, n: int = 120) -> str:
    t = (s or "").replace("\r", " ").replace("\n", " ").strip()
    return t[:n] + ("…" if len(t) > n else "")


def _search_dedupe_raw_hits(keywords: Iterable[str]) -> list[dict]:
    """키워드별 /v1/search 결과를 테이블명 기준 dedupe. 각 항목은 API가 준 dict(첫 등장) 얕은 복사."""
    seen_order: list[str] = []
    seen: set[str] = set()
    by_name: dict[str, dict] = {}

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        try:
            hits = _search(kw)
        except Exception as e:
            print(f"[경고] 검색 실패 (q={kw}): {e}", file=sys.stderr)
            hits = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            name = (hit.get("table") or "").strip()
            if not name:
                continue
            by_name[name] = dict(hit)
            if name not in seen:
                seen.add(name)
                seen_order.append(name)

    return [by_name[n] for n in seen_order if n in by_name]


def _hit_to_meta_row(hit: dict) -> dict:
    desc = hit.get("description_snippet") or hit.get("description") or ""
    name = (hit.get("table") or "").strip()
    return {
        "table": name,
        "domain": (hit.get("domain") or "").strip() or "-",
        "snippet": _snippet(str(desc), 120),
        "rank": hit.get("rank"),
        "score": hit.get("score"),
    }


def _search_dedupe_rows(keywords: Iterable[str]) -> list[dict]:
    """검색 dedupe + 테이블별 도메인·설명 스니펫 (휴리스틱 선별용)."""
    return [_hit_to_meta_row(h) for h in _search_dedupe_raw_hits(keywords)]


def _anthropic_messages(api_key: str, model: str, user_prompt: str, max_tokens: int = 4096) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{ANTHROPIC_API_BASE}/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    blocks = data.get("content") or []
    texts: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            texts.append(b.get("text") or "")
    return "\n".join(texts).strip()


def _parse_llm_picks(
    raw: str,
    allowed: set[str],
    max_picks: int,
) -> tuple[list[str], dict[str, str]]:
    """모델 응답에서 JSON picks 파싱. picks: [{\"table\": \"...\", \"reason\": \"...\"}]"""
    raw = raw.strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("모델 응답에서 JSON 객체를 찾지 못했습니다.")
    data = json.loads(m.group(0))
    picks = data.get("picks")
    if picks is None and isinstance(data.get("tables"), list):
        picks = data["tables"]
    if not isinstance(picks, list) or not picks:
        raise ValueError("JSON에 picks(또는 tables) 배열이 없습니다.")

    names: list[str] = []
    reasons: dict[str, str] = {}
    for item in picks:
        if not isinstance(item, dict):
            continue
        name = (item.get("table") or item.get("table_name") or "").strip()
        reason = (item.get("reason") or item.get("selection_reason") or "").strip()
        if not name or name not in allowed:
            continue
        if name in reasons:
            continue
        reasons[name] = reason or "(이유 없음)"
        names.append(name)
        if len(names) >= max_picks:
            break
    if not names:
        raise ValueError("유효한 테이블명이 하나도 없습니다(후보 목록과 불일치).")
    return names, reasons


_TABLE_FILTER_NOISE = re.compile(
    r"(?i)(^BAK_|_TMP$|_TMP_|_BACKUP|BATCH_JOB|BATCH_|APPLICATION_LOG|REPORT_CGI|"
    r"_PARTITION|EXECUTION_SEQ|SESSION_REGISTRY|_SEQ$)",
)


def _user_hint_tokens(*parts: str) -> list[str]:
    blob = " ".join(p for p in parts if p)
    words = re.findall(r"[\u3131-\u318E\uAC00-\uD7A3]{2,}", blob)
    stop = {
        "있어요", "있어", "합니다", "해줘", "주세요", "싶은데", "모르겠어", "알려", "알려줘",
        "추천", "리포트를", "리포트가", "테이블을", "테이블은", "칼럼은", "컬럼은", "무슨",
        "어떤", "뭘", "해야", "하는지", "구축하고", "같은", "이런", "그런", "정말", "진짜",
        "해서", "것", "등", "관련", "필요한", "쓸", "만들", "작성",
    }
    out: list[str] = []
    for w in words:
        if w in stop or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= 24:
            break
    return out


def _table_filter_prompt(
    raw_search_hits: list[dict],
    project: str,
    user_context: str,
    max_picks: int,
    max_candidates: int,
) -> tuple[str, set[str]]:
    """선별용 프롬프트. 후보는 /v1/search 가 반환한 객체들(JSON)만 사용."""
    capped = raw_search_hits[:max_candidates]
    allowed = {(h.get("table") or "").strip() for h in capped if (h.get("table") or "").strip()}
    json_block = json.dumps({"catalog_search_hits": capped}, ensure_ascii=False, indent=2)
    prompt = f"""당신은 이커머스 DW 메타데이터 카탈로그 담당자입니다.
아래 JSON의 catalog_search_hits 배열은 **로컬 메타 API(/v1/search)가 반환한 원본 객체**를 테이블명 기준으로 dedupe 한 것입니다. 대부분은 프로젝트와 무관할 수 있습니다.

프로젝트(리포트 제목): {project}
사용자 요청 원문:
{user_context or "(원문 없음)"}

--- API 검색 결과 JSON (후보 전부; 필드값은 인용 시 그대로만 사용) ---
{json_block}
---

작업:
1. catalog_search_hits에 **실제로 등장한 table 필드 값만** 고릅니다. 배치/로그/임시(TMP)/백업 등 범용·부가 테이블은 제외합니다.
2. **최대 {max_picks}개**, 최소 1개. 정말 관련 없으면 가장 핵심적인 것만 1~3개만 고릅니다.
3. 각 테이블마다 picks[].reason에 **한국어 2~4문장**을 씁니다.
4. reason에는 **위 JSON에 실제로 있는** 필드(도메인·설명·테이블명·순위·점수 등)만 근거로 인용합니다. JSON에 없는 수치·문장을 새로 만들지 않습니다.
5. reason에 **금지**: 시스템 내부 구현, API 경로·엔드포인트 이름, "휴리스틱", "알고리즘", "점수화", "검색 엔진", "LLM", 모델명, 프롬프트 메타 설명.
6. **의미 혼동 주의**: 프로젝트가 물류·공급망·SCM·배송 최적화라면, 「유통기한(EXPIRY_DATE, 제조일자 등)」 관련 테이블은 맥락이 다르므로 제외한다. 프로젝트가 재고·물류 최적화인데 EXPIRY/유통기한 테이블이 후보에 있으면 반드시 빼고 고른다.

반드시 아래 JSON **한 덩어리만** 출력합니다. 마크다운 코드펜스 금지. 설명 문장 금지.
{{"picks":[{{"table":"테이블명_정확히","reason":"선택 이유 한국어"}}]}}
테이블명은 catalog_search_hits[].table 과 **완전히 동일**해야 합니다."""
    return prompt, allowed


def _openai_chat_completions(
    api_key: str,
    base_url: str,
    model: str,
    user_prompt: str,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI 응답에 choices가 없습니다.")
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


def _heuristic_filter_tables(
    meta_rows: list[dict],
    project: str,
    user_context: str,
    max_picks: int,
    max_candidates: int = 80,
) -> tuple[list[str], dict[str, str]]:
    """API 키 없이 rank·score·이름 패턴·사용자 문맥 단어 겹침으로 소수 선별."""
    capped = meta_rows[:max_candidates]
    tokens = _user_hint_tokens(user_context, project)
    scored: list[tuple[float, int, float, str, dict, list[str]]] = []
    for r in capped:
        name = (r.get("table") or "").strip()
        if not name or _TABLE_FILTER_NOISE.search(name):
            continue
        dom = (r.get("domain") or "").strip()
        snip = (r.get("snippet") or "").strip()
        blob = f"{name} {dom} {snip}".lower()
        hit_toks: list[str] = []
        for t in tokens:
            if len(t) >= 2 and t.lower() in blob:
                hit_toks.append(t)
        hit_toks = list(dict.fromkeys(hit_toks))
        overlap = len(hit_toks)
        rk = r.get("rank")
        try:
            rkv = int(rk) if rk is not None else 999_999
        except (TypeError, ValueError):
            rkv = 999_999
        sc = r.get("score")
        try:
            scv = float(sc) if sc is not None else 0.0
        except (TypeError, ValueError):
            scv = 0.0
        composite = overlap * 10_000 + scv - rkv * 0.001
        scored.append((composite, rkv, scv, name, r, hit_toks))

    scored.sort(key=lambda x: -x[0])

    if not scored:
        picked_rows = [r for r in capped if (r.get("table") or "").strip() and not _TABLE_FILTER_NOISE.search(r["table"])]
        picked_rows = picked_rows[:max(1, max_picks)]
    else:
        picked_rows = [t[4] for t in scored[:max(1, max_picks)]]

    names: list[str] = []
    reasons: dict[str, str] = {}
    for r in picked_rows:
        name = (r.get("table") or "").strip()
        if not name or name in reasons:
            continue
        rk = r.get("rank")
        sc = r.get("score")
        dom = (r.get("domain") or "").strip()
        snip = (r.get("snippet") or "").strip()
        blob = f"{name} {dom} {snip}".lower()
        hit_toks = [t for t in tokens if len(t) >= 2 and t.lower() in blob]
        hit_toks = list(dict.fromkeys(hit_toks))[:8]
        dom_label = dom if dom else "미분류"
        parts: list[str] = [
            f"카탈로그에서 이 테이블은 「{dom_label}」 영역으로 분류되어 있습니다.",
        ]
        if hit_toks:
            q = "」, 「".join(hit_toks)
            parts.append(
                f"요청·프로젝트 문구에 나온 「{q}」가 테이블명·도메인·카탈로그 설명 요약 가운데 함께 나타나, "
                f"이번 리포트 주제와 직접 맞춰 볼 수 있는 근거가 됩니다."
            )
        if snip:
            parts.append(f"카탈로그 설명(발췌): 「{_snippet(snip, 120)}」")
        if not hit_toks:
            rk_s = str(rk) if rk is not None else "—"
            sc_s = str(sc) if sc is not None else "—"
            parts.append(
                f"요청문과 똑같은 한글 단어가 설명에서 바로 드러나지는 않았습니다. "
                f"동일 주제로 묶인 후보 가운데, 카탈로그에 표시된 순서 {rk_s}번째·관련도 {sc_s}인 항목으로 "
                f"이번 리포트에 넣었습니다. (숫자는 본문 표의 순위·점수와 같습니다.)"
            )
        reason = " ".join(parts)
        reasons[name] = reason
        names.append(name)
        if len(names) >= max_picks:
            break

    if not names:
        raise ValueError("휴리스틱 선별 후 테이블이 0개입니다.")
    return names, reasons


def _llm_filter_tables(
    raw_search_hits: list[dict],
    project: str,
    user_context: str,
    model: str,
    api_key: str,
    max_picks: int,
    max_candidates: int = 70,
) -> tuple[list[str], dict[str, str]]:
    """Anthropic Messages로 후보 중 소수 + 이유. 파싱 실패 시 1회 재시도."""
    prompt, allowed = _table_filter_prompt(
        raw_search_hits, project, user_context, max_picks, max_candidates,
    )
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            raw = _anthropic_messages(api_key, model, prompt, max_tokens=4096)
            return _parse_llm_picks(raw, allowed, max_picks)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[경고] 선별 JSON 파싱 실패 (시도 {attempt + 1}/2): {e}", file=sys.stderr)
    raise ValueError(f"선별 JSON 파싱 2회 실패: {last_err}")


def _llm_filter_tables_openai(
    raw_search_hits: list[dict],
    project: str,
    user_context: str,
    model: str,
    api_key: str,
    base_url: str,
    max_picks: int,
    max_candidates: int = 70,
) -> tuple[list[str], dict[str, str]]:
    """OpenAI Chat Completions로 후보 중 소수 + 이유. 파싱 실패 시 1회 재시도."""
    prompt, allowed = _table_filter_prompt(
        raw_search_hits, project, user_context, max_picks, max_candidates,
    )
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            raw = _openai_chat_completions(api_key, base_url, model, prompt)
            return _parse_llm_picks(raw, allowed, max_picks)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[경고] 선별 JSON 파싱 실패 (시도 {attempt + 1}/2): {e}", file=sys.stderr)
    raise ValueError(f"선별 JSON 파싱 2회 실패: {last_err}")


def _explain_all(table_names: Iterable[str]) -> list[dict]:
    """테이블명 목록 → explain 상세 수집 → rank 기준 정렬."""
    detailed: list[dict] = []
    for name in table_names:
        try:
            detailed.append(_explain(name))
        except Exception as e:
            print(f"[경고] 상세 조회 실패 ({name}): {e}", file=sys.stderr)
    detailed.sort(key=lambda d: (
        d.get("rank") is None,
        d.get("rank") if d.get("rank") is not None else 9999,
        d.get("table") or "",
    ))
    return detailed


def _collect_tables(keywords: Iterable[str]) -> list[dict]:
    """키워드별 search → 테이블명 dedupe → 각 테이블 explain 으로 상세 채움."""
    return _explain_all(_search_dedupe(keywords))


def _search_and_print(keywords: list[str]) -> None:
    """검색 결과를 GPT가 읽기 쉬운 텍스트로 stdout 출력 후 종료 (1단계 exec용)."""
    seen_order: list[str] = []
    seen: set[str] = set()
    hits_by_kw: dict[str, list[dict]] = {}

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        try:
            hits = _search(kw)
        except Exception as e:
            print(f"[경고] 검색 실패 (q={kw}): {e}", file=sys.stderr)
            hits = []
        hits_by_kw[kw] = hits
        for hit in hits:
            name = hit.get("table")
            if name and name not in seen:
                seen.add(name)
                seen_order.append(name)

    print(f"[검색 결과] 키워드: {', '.join(keywords)} → 총 {len(seen_order)}개 테이블 (중복 제거 후)")
    print("=" * 72)
    print(f"{'#':<4} {'테이블명':<40} {'도메인':<18} 설명(앞 100자)")
    print("-" * 72)

    # 각 hit의 snippet 정보 수집 (마지막으로 검색된 키워드 기준)
    snippet_map: dict[str, dict] = {}
    for hits in hits_by_kw.values():
        for hit in hits:
            name = hit.get("table") or ""
            if name:
                snippet_map[name] = hit

    for idx, name in enumerate(seen_order, 1):
        hit = snippet_map.get(name, {})
        domain = (hit.get("domain") or "").strip() or "-"
        desc = (hit.get("description") or "").replace("\n", " ").strip()[:100]
        print(f"{idx:<4} {name:<40} {domain:<18} {desc}")

    print("=" * 72)
    print(f"SEARCH_COUNT={len(seen_order)}")
    print(f"SEARCH_KEYWORDS={','.join(keywords)}")


def _search_json_only_dump(keywords: list[str]) -> None:
    """에이전트/대화 LLM용: /v1/search 원본 객체 배열만 stdout(JSON)."""
    kws = [k.strip() for k in keywords if k and k.strip()]
    raw = _search_dedupe_raw_hits(kws)
    print(json.dumps({"keywords": kws, "results": raw}, ensure_ascii=False, indent=2))


def _fetch_domain_tables(domain: str) -> list[dict]:
    """/v1/tables?domain=... → search hit 형식의 dict 목록 반환."""
    qs = urllib.parse.urlencode({"domain": domain, "limit": "1000"})
    data = _http_get_json(f"{API_BASE}/v1/tables?{qs}")
    tables = data.get("tables") or []
    result = []
    for t in tables:
        if not isinstance(t, dict):
            continue
        name = (t.get("table") or "").strip()
        if not name:
            continue
        result.append({
            "table": name,
            "domain": domain,
            "rank": t.get("rank"),
            "score": t.get("score"),
            "description_snippet": t.get("description_snippet") or "",
        })
    return result


def _domain_json_only_dump(domain: str) -> None:
    """에이전트/대화 LLM용: /v1/tables?domain=... 결과를 --search-json-only 와 동일 형식으로 stdout 출력."""
    raw = _fetch_domain_tables(domain)
    print(json.dumps({"domain": domain, "results": raw}, ensure_ascii=False, indent=2))


# ── CSV ─────────────────────────────────────────────────────────
def _columns_join(cols_preview: list[dict]) -> str:
    """columns_preview → 'CODE(라벨);CODE2(라벨2);CODE3' 직렬화."""
    parts: list[str] = []
    for c in cols_preview or []:
        code = (c.get("code") or "").strip()
        if not code:
            continue
        label = (c.get("label") or "").strip()
        if label:
            parts.append(f"{code}({label})")
        else:
            parts.append(code)
    return ";".join(parts)


def _build_csv(rows: list[dict], out_path: Path, reasons: dict[str, str] | None = None) -> None:
    reasons = reasons or {}
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(CSV_COLUMNS)
        for r in rows:
            desc = (r.get("description") or "").replace("\r\n", "\n").replace("\r", "\n")
            table_name = r.get("table") or ""
            writer.writerow([
                table_name,
                (r.get("domain") or "").strip(),
                "" if r.get("rank") is None else r.get("rank"),
                "" if r.get("score") is None else r.get("score"),
                "" if r.get("row_count") is None else r.get("row_count"),
                "" if r.get("column_count") is None else r.get("column_count"),
                "" if r.get("data_size_mb") is None else r.get("data_size_mb"),
                (r.get("period") or "").strip(),
                desc,
                _columns_join(r.get("columns_preview") or []),
                reasons.get(table_name, ""),
            ])


# ── PDF ─────────────────────────────────────────────────────────
def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _make_styles() -> dict:
    base = getSampleStyleSheet()

    def _ps(name, parent="Normal", **kw):
        kw.setdefault("fontName", FONT_NAME)
        return ParagraphStyle(name, parent=base[parent], **kw)

    return {
        "title":    _ps("title",    fontSize=20, spaceAfter=6,  textColor=colors.HexColor("#1a1a2e"), leading=26),
        "subtitle": _ps("subtitle", fontSize=11, spaceAfter=2,  textColor=colors.HexColor("#4a4a6a")),
        "h2":       _ps("h2",       fontSize=13, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1a1a2e"), leading=18),
        "h3":       _ps("h3",       fontSize=11, spaceBefore=8,  spaceAfter=3, textColor=colors.HexColor("#1a1a2e"), leading=15),
        "body":     _ps("body",     fontSize=10, leading=15),
        "small":    _ps("small",    fontSize=8.5, textColor=colors.grey, leading=12),
        "rec_reason": _ps("rec_reason", fontSize=9, leading=13, leftIndent=14, textColor=colors.HexColor("#555555")),
        "th":       _ps("th",       fontSize=9.5, leading=13, textColor=colors.white, wordWrap="CJK"),
        "td":       _ps("td",       fontSize=9,   leading=12, wordWrap="CJK"),
        "td_right": _ps("td_right", fontSize=9,   leading=12, alignment=2, wordWrap="CJK"),
    }


def _tbl_style(header_color=colors.HexColor("#1a1a2e")) -> TableStyle:
    return TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  header_color),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5fa")]),
        ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#ccccdd")),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
    ])


def _th(text: str, S: dict) -> Paragraph:
    return Paragraph(_xml_escape(text), S["th"])


def _td(text, S: dict, right: bool = False) -> Paragraph:
    return Paragraph(_xml_escape(str(text)), S["td_right"] if right else S["td"])


def _domain_distribution(rows: list[dict]) -> list[tuple[str, int]]:
    c: Counter = Counter()
    for r in rows:
        d = (r.get("domain") or "").strip() or "(미분류)"
        c[d] += 1
    return sorted(c.items(), key=lambda x: -x[1])


def _build_pdf(rows: list[dict], project: str, out_path: Path, generated_at: str, reasons: dict[str, str] | None = None, summary_text: str = "", recommendation_text: str = "", include_column_details: bool = True) -> None:
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
    )
    reasons = reasons or {}
    S = _make_styles()
    W = doc.width
    story: list = []

    # ── 표지 ────────────────────────────────────────────────────
    story.append(Paragraph(f"{_xml_escape(project)} 관련 테이블 분석 리포트", S["title"]))
    story.append(Paragraph(f"생성 일시: {generated_at}", S["subtitle"]))
    story.append(Spacer(1, 5 * mm))

    if summary_text and summary_text.strip():
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(_xml_escape(summary_text.strip()), S["body"]))
        story.append(Spacer(1, 3 * mm))

    # ── 요약 ────────────────────────────────────────────────────
    story.append(Paragraph("요약", S["h2"]))
    distribution = _domain_distribution(rows)
    dist_text = ", ".join(f"{d}: {n:,}개" for d, n in distribution) or "(없음)"
    summary_rows = [
        [_th("항목", S),       _th("값", S)],
        [_td("총 테이블 수", S), _td(f"{len(rows):,}개", S)],
        [_td("도메인 분포", S),  _td(dist_text, S)],
    ]
    t1 = Table(summary_rows, colWidths=[W * 0.28, W * 0.72])
    t1.setStyle(_tbl_style())
    story.append(t1)
    story.append(Spacer(1, 5 * mm))

    # ── 테이블 목록 ─────────────────────────────────────────────
    story.append(Paragraph("테이블 목록", S["h2"]))
    list_rows = [[
        _th("순위", S),
        _th("테이블명", S),
        _th("도메인", S),
        _th("점수", S),
        _th("행 수", S),
        _th("컬럼 수", S),
        _th("설명", S),
    ]]
    for r in rows:
        rank = r.get("rank")
        rc = r.get("row_count")
        sc = r.get("score")
        cc = r.get("column_count")
        list_rows.append([
            _td("-" if rank is None else str(rank), S, right=True),
            _td(r.get("table") or "", S),
            _td((r.get("domain") or "").strip() or "(미분류)", S),
            _td("-" if sc is None else str(sc), S, right=True),
            _td(f"{rc:,}" if isinstance(rc, int) else "-", S, right=True),
            _td(f"{cc:,}" if isinstance(cc, int) else "-", S, right=True),
            _td((r.get("description") or "").strip(), S),
        ])
    t2 = Table(
        list_rows,
        colWidths=[W * 0.06, W * 0.20, W * 0.12, W * 0.07, W * 0.10, W * 0.08, W * 0.37],
        repeatRows=1,
    )
    t2.setStyle(_tbl_style())
    story.append(t2)

    has_reason_text = any((v or "").strip() for v in (reasons or {}).values())
    if has_reason_text:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("테이블별 추천 이유", S["h2"]))
        reason_rows = [[_th("테이블명", S), _th("추천 이유", S)]]
        for r in rows:
            name = r.get("table") or ""
            reason = (reasons.get(name) or "").strip() or "—"
            reason_rows.append([_td(name, S), _td(reason, S)])
        rw = Table(
            reason_rows,
            colWidths=[W * 0.26, W * 0.74],
            repeatRows=1,
        )
        rw.setStyle(_tbl_style())
        story.append(rw)
        story.append(Spacer(1, 4 * mm))

    if recommendation_text.strip():
        normalized_rec = recommendation_text.replace("\\n", "\n")
        story.append(Spacer(1, 14))
        story.append(Paragraph("추천 구성안", S["h2"]))
        story.append(Paragraph("가장 먼저 쓰면 좋은 조합은 이렇습니다.", S["body"]))
        first_bullet = True
        for line in normalized_rec.strip().splitlines():
            s = line.strip()
            if not s or s.rstrip(":") in ("추천 구성안", "추천구성안"):
                continue
            is_bullet = s.startswith("•") or (len(s) > 1 and s[0].isdigit() and s[1] in ").")
            if is_bullet:
                if not first_bullet:
                    story.append(Spacer(1, 6))
                story.append(Paragraph(_xml_escape(s), S["body"]))
                first_bullet = False
            else:
                story.append(Paragraph(_xml_escape(s), S["rec_reason"]))

    if include_column_details:
        # ── 테이블별 컬럼 상세 ──────────────────────────────────────
        story.append(PageBreak())
        story.append(Paragraph("테이블별 컬럼 상세", S["h2"]))
        for r in rows:
            name = r.get("table") or ""
            dom = (r.get("domain") or "").strip() or "(미분류)"
            rank = r.get("rank")
            prefix = f"{rank}위 · " if rank is not None else ""
            col_count = r.get("column_count") or len(r.get("columns_preview") or [])
            story.append(Paragraph(
                f"{_xml_escape(name)} "
                f"<font color='#666666'>({_xml_escape(prefix)}{_xml_escape(dom)} · {col_count}컬럼)</font>",
                S["h3"],
            ))
            cols = r.get("columns_preview") or []
            if not cols:
                story.append(Paragraph("(컬럼 정보 없음)", S["small"]))
                story.append(Spacer(1, 3 * mm))
                continue
            col_rows = [[_th("컬럼 코드", S), _th("한글 라벨", S)]]
            for c in cols:
                code = (c.get("code") or "").strip()
                label = (c.get("label") or "").strip() or "-"
                col_rows.append([_td(code, S), _td(label, S)])
            ct = Table(col_rows, colWidths=[W * 0.40, W * 0.60], repeatRows=1)
            ct.setStyle(_tbl_style())
            story.append(ct)
            story.append(Spacer(1, 4 * mm))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "이 리포트는 EHC Mall DB Ontology API (localhost:8000)가 제공한 메타데이터 기준입니다. "
        "실제 운영 DB 내용과 차이가 있을 수 있습니다.",
        S["small"],
    ))

    doc.build(story)


# ── Telegram sendMessage ─────────────────────────────────────────
def _send_message(token: str, chat_id: str, text: str) -> dict:
    url = f"{TG_API_BASE}/bot{token}/sendMessage"
    body = json.dumps({
        "chat_id": str(chat_id),
        "text": text,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ── Telegram sendDocument ────────────────────────────────────────
def _send_document(
    token: str,
    chat_id: str,
    file_path: Path,
    caption: str,
    content_type: str,
) -> dict:
    url = f"{TG_API_BASE}/bot{token}/sendDocument"
    boundary = "----ExportTablesBoundary"
    lines: list[bytes] = []

    def _field(name: str, value: str) -> None:
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value.encode("utf-8"))

    def _file_field(name: str, filename: str, data: bytes, ctype: str) -> None:
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
        )
        lines.append(f"Content-Type: {ctype}".encode())
        lines.append(b"")
        lines.append(data)

    _field("chat_id", str(chat_id))
    _field("caption", caption)
    _field("parse_mode", "Markdown")

    with open(file_path, "rb") as f:
        data = f.read()
    _file_field("document", file_path.name, data, content_type)

    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines)

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


# ── 메인 ─────────────────────────────────────────────────────────
def _safe_filename(name: str) -> str:
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^0-9A-Za-z가-힣_\-]", "", name)
    return name[:40] or "export"


def _resolve_filter_backend(flag: str) -> str:
    f = (flag or "auto").strip().lower()
    if f not in {"auto", "anthropic", "openai", "heuristic"}:
        f = "auto"
    if f != "auto":
        return f
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return "anthropic"
    if (os.environ.get("OPENAI_API_KEY") or "").strip():
        return "openai"
    return "heuristic"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="프로젝트 키워드로 관련 테이블을 모아 CSV/PDF 리포트로 텔레그램 전송",
    )
    parser.add_argument("chat_id", nargs="?", default="", help="텔레그램 chat_id (--search-only 시 생략 가능)")
    parser.add_argument("keywords", nargs="*", help="검색 키워드 1~3개 (공백 분리, --tables 지정 시 불필요)")
    parser.add_argument("--format", choices=["csv", "pdf"], help="출력 형식 (--search-only 시 불필요)")
    parser.add_argument("--project", default="", help="리포트 제목용 프로젝트명 (생략 시 키워드 사용)")
    parser.add_argument("--account", default="ehcmall", help="openclaw.json 계정명 (기본: ehcmall)")
    parser.add_argument("--token", default="", help="봇 토큰 직접 지정 (생략 시 openclaw.json에서 로드)")
    parser.add_argument(
        "--tables", nargs="+", metavar="TABLE",
        help="export할 테이블명 직접 지정 (지정 시 키워드 검색 건너뜀)",
    )
    parser.add_argument(
        "--domain", default="",
        help="도메인명 지정 시 키워드 검색 대신 /v1/tables?domain=... 으로 해당 도메인 테이블만 수집",
    )
    parser.add_argument(
        "--search-only", action="store_true",
        help="검색 결과만 사람 읽기 텍스트로 stdout 출력 후 종료",
    )
    parser.add_argument(
        "--search-json-only", action="store_true",
        help="/v1/search 원본 JSON(dedupe)만 stdout에 출력 후 종료 (대화 LLM·에이전트 1단계)",
    )
    parser.add_argument(
        "--reasons", default="",
        help='JSON 문자열. {"TABLE_NAME": "선택 이유", ...} (선택적)',
    )
    parser.add_argument(
        "--auto-filter",
        action="store_true",
        help="검색 후 소수 테이블만 선별+선택 이유 후 export. 키 없으면 휴리스틱, 있으면 LLM(--filter-backend)",
    )
    parser.add_argument(
        "--filter-backend",
        choices=["auto", "anthropic", "openai", "heuristic"],
        default="auto",
        help="선별 방식: auto=Anthropic→OpenAI→휴리스틱 순으로 사용 가능한 것",
    )
    parser.add_argument(
        "--filter-model",
        default=FILTER_MODEL,
        help=f"Anthropic 선별 모델 (기본: {FILTER_MODEL})",
    )
    parser.add_argument(
        "--max-picks",
        type=int,
        default=12,
        help="선별 후 export할 최대 테이블 수 (기본: 12)",
    )
    parser.add_argument(
        "--user-context",
        default="",
        help="사용자 원문 요청(LLM 선별 컨텍스트). EXPORT_USER_CONTEXT 환경변수도 인식",
    )
    parser.add_argument(
        "--summary",
        default="",
        help="PDF 제목 아래에 삽입할 종합 코멘트 산문 (LLM이 생성, 선택적)",
    )
    parser.add_argument(
        "--recommendation",
        default="",
        help="PDF '추천 구성안' 섹션 텍스트 (줄바꿈 포함 불릿, 생략 시 섹션 없음)",
    )
    parser.add_argument(
        "--no-column-details",
        action="store_true",
        help="PDF에서 '테이블별 컬럼 상세' 섹션을 제외합니다.",
    )
    parser.add_argument(
        "--out-dir",
        default="",
        help="파일 저장 디렉토리 (기본: ~/Downloads/ehcmall-reports). 예: ~/Desktop",
    )
    args = parser.parse_args()

    # ── --search-only / --search-json-only ───────────────────────
    if args.search_only and args.search_json_only:
        print("[오류] --search-only 과 --search-json-only 는 동시에 쓸 수 없습니다.", file=sys.stderr)
        sys.exit(2)

    if args.search_only or args.search_json_only:
        domain = (args.domain or "").strip()
        if domain:
            if args.search_json_only:
                _domain_json_only_dump(domain)
            else:
                print(f"[도메인 검색] {domain}", flush=True)
                rows = _fetch_domain_tables(domain)
                for r in rows:
                    print(f"  {r['table']} (rank={r.get('rank')}, score={r.get('score')})")
                print(f"총 {len(rows)}개 테이블", flush=True)
            return
        keywords = [k.strip() for k in (args.keywords or []) if k and k.strip()]
        if args.chat_id and args.chat_id.strip():
            keywords = [args.chat_id.strip()] + keywords
        if not keywords:
            mode = "--search-json-only" if args.search_json_only else "--search-only"
            print(f"[오류] {mode} 에는 키워드 또는 --domain 이 필요합니다.", file=sys.stderr)
            sys.exit(2)
        if args.search_json_only:
            _search_json_only_dump(keywords)
        else:
            _search_and_print(keywords)
        return

    # ── reasons 파싱 (직접 --tables 시에만 선적용; --auto-filter는 아래에서 덮어씀) ─
    reasons: dict[str, str] = {}
    if args.reasons and args.reasons.strip():
        try:
            parsed = json.loads(args.reasons)
            if not isinstance(parsed, dict):
                print("[경고] --reasons 값이 JSON 객체가 아닙니다. 이유 없이 진행합니다.", file=sys.stderr)
            else:
                reasons = {k: str(v) for k, v in parsed.items() if isinstance(k, str)}
                if args.tables:
                    valid = {t.strip() for t in args.tables if t and t.strip()}
                    bad = [k for k in reasons if k not in valid]
                    if bad:
                        print(f"[경고] --reasons에 --tables에 없는 키 {bad} → 무시합니다.", file=sys.stderr)
                        reasons = {k: v for k, v in reasons.items() if k in valid}
        except json.JSONDecodeError as e:
            print(f"[경고] --reasons JSON 파싱 실패 (이유 없이 진행): {e}", file=sys.stderr)

    # ── export 모드 공통 검증 ────────────────────────────────────
    if not args.format:
        print("[오류] --format csv|pdf 가 필요합니다.", file=sys.stderr)
        sys.exit(2)

    chat_id = args.chat_id.strip().removeprefix("telegram:")
    if not chat_id:
        print("[오류] chat_id 가 필요합니다.", file=sys.stderr)
        sys.exit(2)

    token = args.token.strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        token = _load_bot_token(args.account)

    # ── 테이블 수집 ──────────────────────────────────────────────
    if args.tables:
        if args.auto_filter:
            print("[경고] --tables 지정 시 --auto-filter 는 무시됩니다.", file=sys.stderr)
        table_names = [t.strip() for t in args.tables if t and t.strip()]
        project = args.project.strip() or " ".join(table_names[:3])
        print(f"[1/4] 테이블 직접 지정 ({len(table_names)}개)…", flush=True)
        rows = _explain_all(table_names)
    elif (args.domain or "").strip():
        domain = args.domain.strip()
        project = args.project.strip() or f"{domain} 도메인"
        print(f"[1/4] 도메인 전체 수집 (domain={domain})…", flush=True)
        domain_hits = _fetch_domain_tables(domain)
        if not domain_hits:
            print(f"[오류] '{domain}' 도메인에서 테이블을 찾을 수 없습니다.", file=sys.stderr)
            sys.exit(3)
        table_names = [h["table"] for h in domain_hits]
        print(f"      총 {len(table_names)}개 테이블 발견", flush=True)
        rows = _explain_all(table_names)
    else:
        keywords = [k.strip() for k in (args.keywords or []) if k and k.strip()]
        if not keywords:
            print("[오류] 키워드, --tables, 또는 --domain 이 필요합니다.", file=sys.stderr)
            sys.exit(2)
        if len(keywords) > 3:
            print(f"[경고] 키워드가 {len(keywords)}개 입력됨 — 앞 3개만 사용합니다.", file=sys.stderr)
            keywords = keywords[:3]
        project = args.project.strip() or " ".join(keywords)
        print(f"[1/4] 검색 ({len(keywords)}개 키워드: {', '.join(keywords)})…", flush=True)

        if args.auto_filter:
            backend = _resolve_filter_backend(args.filter_backend)
            raw_hits = _search_dedupe_raw_hits(keywords)
            meta_rows = [_hit_to_meta_row(h) for h in raw_hits]
            if not meta_rows:
                print("[오류] 검색 결과가 없습니다. 다른 키워드로 시도해보세요.", file=sys.stderr)
                sys.exit(3)
            user_ctx = (
                (args.user_context or "").strip()
                or (os.environ.get("EXPORT_USER_CONTEXT") or "").strip()
            )
            mp = max(1, min(args.max_picks, 30))
            print(
                f"      → 후보 {len(meta_rows)}개 테이블, 선별: {backend} (최대 {mp}개)",
                flush=True,
            )

            try:
                if backend == "heuristic":
                    picked_names, reasons = _heuristic_filter_tables(
                        meta_rows, project, user_ctx, max_picks=mp,
                    )
                elif backend == "openai":
                    okey = (os.environ.get("OPENAI_API_KEY") or "").strip()
                    if not okey:
                        print("[오류] --filter-backend openai 인데 OPENAI_API_KEY 가 없습니다.", file=sys.stderr)
                        sys.exit(2)
                    obase = (os.environ.get("OPENAI_API_BASE") or OPENAI_API_DEFAULT).strip()
                    omodel = (os.environ.get("OPENAI_FILTER_MODEL") or OPENAI_FILTER_MODEL_DEFAULT).strip()
                    picked_names, reasons = _llm_filter_tables_openai(
                        raw_hits, project, user_ctx, omodel, okey, obase, max_picks=mp,
                    )
                else:
                    akey = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
                    if not akey:
                        print(
                            "[오류] --filter-backend anthropic/auto 인데 ANTHROPIC_API_KEY 가 없습니다.",
                            file=sys.stderr,
                        )
                        sys.exit(2)
                    picked_names, reasons = _llm_filter_tables(
                        raw_hits,
                        project,
                        user_ctx,
                        (args.filter_model or FILTER_MODEL).strip(),
                        akey,
                        max_picks=mp,
                    )
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")[:2000]
                except Exception:
                    pass
                print(f"[오류] 선별 API HTTP 오류: {e}\n{err_body}", file=sys.stderr)
                sys.exit(4)
            except Exception as e:
                print(f"[오류] 선별 실패: {e}", file=sys.stderr)
                sys.exit(4)
            print(f"      → 선별 {len(picked_names)}개: {', '.join(picked_names)}", flush=True)
            rows = _explain_all(picked_names)
        else:
            rows = _collect_tables(keywords)

    if not rows:
        print("[오류] 검색 결과가 없습니다. 다른 키워드로 시도해보세요.", file=sys.stderr)
        sys.exit(3)
    print(f"      → {len(rows)}개 테이블", flush=True)

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    stem = f"ehcmall_export_{_safe_filename(project)}_{now.strftime('%Y%m%d_%H%M%S')}"

    if args.format == "csv":
        out_path = out_dir / f"{stem}.csv"
        print(f"[2/4] CSV 생성 중… → {out_path}", flush=True)
        _build_csv(rows, out_path, reasons)
        ctype = "text/csv; charset=utf-8"
    else:
        _register_font()
        out_path = out_dir / f"{stem}.pdf"
        print(f"[2/4] PDF 생성 중… → {out_path}", flush=True)
        _build_pdf(rows, project, out_path, generated_at, reasons, summary_text=args.summary, recommendation_text=args.recommendation or "", include_column_details=not args.no_column_details)
        ctype = "application/pdf"

    size_kb = max(out_path.stat().st_size // 1024, 1)
    print(f"      완료: {size_kb} KB", flush=True)

    def _md1_escape(s: str) -> str:
        return s.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

    cap_extra = " (선택 이유 포함)" if reasons else ""
    caption = (
        f"*{_md1_escape(project)} 관련 테이블 분석 리포트*{cap_extra}\n"
        f"생성: {generated_at}\n"
        f"테이블 {len(rows):,}개 / 형식 {args.format.upper()}"
    )
    _dist = _domain_distribution(rows)
    _dist_parts = [f"{d}: {n}개" for d, n in _dist]
    _dist_str = " | ".join(_dist_parts)
    if len(_dist) >= 2:
        print(f"[경고] 도메인 분포: {_dist_str} — 여러 도메인이 섞였습니다", flush=True)
    else:
        print(f"[도메인 분포] {_dist_str}", flush=True)
    print(f"[3/4] 텔레그램 전송 중… (chat_id={chat_id})", flush=True)
    if args.format == "pdf":
        intro_parts: list[str] = []
        if (args.summary or "").strip():
            intro_parts.append(f"리포트 요약: {args.summary.strip()}")
        rec = (args.recommendation or "").replace("\\n", "\n").strip()
        if rec:
            intro_parts.append(rec)
        if intro_parts:
            try:
                _send_message(token, chat_id, "\n\n".join(intro_parts))
                print("      summary·추천 구성안 텍스트 전송 완료", flush=True)
            except Exception as e:
                print(f"[경고] summary 텍스트 전송 실패 (PDF 전송은 계속): {e}", file=sys.stderr)
    try:
        result = _send_document(token, chat_id, out_path, caption, ctype)
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[오류] 텔레그램 전송 HTTP 오류 {e.code}: {err_body}", file=sys.stderr)
        sys.exit(1)

    if result.get("ok"):
        print(f"[4/4] 전송 완료 ✓ (message_id={result['result']['message_id']})", flush=True)
        print(f"파일 저장 경로: {out_path}", flush=True)
        print(f"TABLES_COUNT={len(rows)}", flush=True)
        print(f"FORMAT={args.format}", flush=True)
        print(f"PROJECT={project}", flush=True)
    else:
        print(f"[오류] 텔레그램 전송 실패: {result}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
