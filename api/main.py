"""
EHC Mall DB Ontology API
========================
FastAPI 서버 — data/ehcmall_index.json을 메모리에 로드하여
OpenClaw 스킬 및 텔레그램 봇에 JSON 메타데이터를 제공합니다.

보안 정책: 이 서버는 사전에 오프라인 ETL로 생성된 인덱스만 읽습니다.
`/v1/explain` 은 `reply_intro_block`, `reply_description_block`, 컬럼 목록 전체를 반환합니다.
`/v1/overview` 는 `reply_report_markdown`(고정 포맷 개요 리포트)을 포함합니다. 검색·목록은 스니펫만 반환합니다.
"""
from __future__ import annotations

import json
import os
import pathlib
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from catalog_dates import (
    effective_period,
    format_period_range_korean,
    normalize_stored_date,
)

# ──────────────────────────────────────────────
# 설정 상수
# ──────────────────────────────────────────────
DEFAULT_SEARCH_LIMIT = 50      # /v1/search 기본 반환 개수
MAX_SEARCH_LIMIT = 250        # limit 파라미터 상한 (과대 응답 방지)

INDEX_PATH = pathlib.Path(os.getenv("INDEX_PATH", "/data/ehcmall_index.json"))


# ──────────────────────────────────────────────
# 앱 초기화
# ──────────────────────────────────────────────
app = FastAPI(
    title="EHC Mall DB Ontology API",
    version="1.0.0",
    description="유진홈센터 DB 테이블·컬럼 메타데이터 질의 API (RAG 미사용)",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_INDEX: dict[str, dict] = {}


@app.on_event("startup")
async def _load_index() -> None:
    global _INDEX
    if not INDEX_PATH.exists():
        raise RuntimeError(
            f"인덱스 파일을 찾을 수 없습니다: {INDEX_PATH}\n"
            "먼저 'etl/build_ontology.py'를 실행하세요."
        )
    with open(INDEX_PATH, encoding="utf-8") as f:
        _INDEX = json.load(f)
    print(f"[startup] 인덱스 로드 완료: {len(_INDEX)}개 테이블")


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────

def _lookup_table(table: str) -> tuple[str, dict]:
    """대소문자 무시 테이블 조회. (canonical_name, entry)를 반환."""
    entry = _INDEX.get(table)
    if entry is not None:
        return table, entry
    upper = table.upper()
    for k, v in _INDEX.items():
        if k.upper() == upper:
            return k, v
    raise HTTPException(status_code=404, detail=f"테이블 '{table}'을 찾을 수 없습니다.")


def _trunc(s: str, limit: int) -> str:
    return s[:limit] + "…" if len(s) > limit else s


def _explain_rank_line(entry: dict) -> str:
    r = entry.get("rank")
    if r is None:
        return "(순위 없음)"
    return f"{r}위"


def _explain_score_line(entry: dict) -> str:
    s = entry.get("score")
    if s is None:
        return "(점수 없음)"
    return str(s)


def _explain_rows_line(entry: dict) -> str:
    n = entry.get("row_count")
    if n is None:
        return "(없음)"
    return f"{n:,}"


def _explain_period_line(entry: dict) -> str:
    p = effective_period(
        entry.get("period") or None,
        entry.get("first_date") or None,
        entry.get("last_date") or None,
    )
    if p:
        return format_period_range_korean(p)
    return "(원본에 유효한 기간 없음)"


def _explain_domain_line(entry: dict) -> str:
    d = (entry.get("domain") or "").strip()
    return f"{d} 도메인" if d else "(도메인 없음)"


def _overview_reply_markdown(summary: dict, domains: list, top_tables: list) -> str:
    """텔레그램용 고정 포맷 리포트 — LLM이 요약·단순화하지 않도록 통째로 제공."""
    lines: list[str] = []
    lines.append("## 유진홈센터 DB 개요")
    lines.append("")
    lines.append("**규모**")
    tt = summary["total_tables"]
    td = summary["total_domains"]
    tr = summary["total_rows_approx"]
    tm = summary["total_size_mb_approx"]
    lines.append(f"• 전체 테이블: {tt:,}개 / 도메인: {td}개")
    lines.append(f"• 총 데이터 행 수: 약 {tr:,}행")
    lines.append(f"• 총 데이터 크기: 약 {tm:,} MB")
    dp = summary.get("data_period")
    lines.append(
        f"• 메타데이터 일자 범위(전 테이블 합집합): {dp if dp else '(기간 정보 없음)'}"
    )
    caveat = (summary.get("data_period_caveat") or "").strip()
    if caveat:
        lines.append(f"• ※ {caveat}")
    lines.append("")
    lines.append("**도메인별 테이블 수**")
    for d in domains:
        lines.append(f"• {d['domain']}: {d['table_count']:,}개")
    lines.append("")
    n = len(top_tables)
    lines.append(f"**핵심 테이블 Top {n}**")
    for item in top_tables:
        r = item["rank"]
        name = item["table"]
        dom = (item.get("domain") or "").strip() or "(미분류)"
        lines.append(f"• {r}위 {name} ({dom})")
        snip = (
            (item.get("description") or "").strip()
            or (item.get("description_snippet") or "").strip()
        )
        if snip:
            lines.append(snip)
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────

@app.get(
    "/v1/explain",
    summary="테이블(·컬럼) 메타데이터 조회",
    response_description="테이블 또는 컬럼의 개요·통계·한글 라벨",
)
def explain(
    table: str = Query(..., description="테이블 이름 (대소문자 무시)"),
    column: Optional[str] = Query(None, description="컬럼 코드 (선택)"),
):
    """
    **테이블 조회** (`?table=T`): 도메인, rank/score, 행수, 기간, 설명, 컬럼 전체 목록 반환.

    **컬럼 조회** (`?table=T&column=C`): 컬럼의 한글 라벨과 민감정보 힌트(향후) 반환.
    """
    canon_table, entry = _lookup_table(table.strip())

    if column:
        col_upper = column.strip().upper()
        cols: dict[str, Optional[str]] = entry.get("columns", {})
        for code, label in cols.items():
            if code.upper() == col_upper:
                return {
                    "table": canon_table,
                    "column": code,
                    "label": label,
                    "sensitivity_hint": None,
                    "_note": "민감컬럼 분류 속성(sensitivity_hint)은 향후 버전에서 추가 예정입니다.",
                }
        raise HTTPException(
            status_code=404,
            detail=f"컬럼 '{column}'을 테이블 '{canon_table}'에서 찾을 수 없습니다.",
        )

    # 테이블 수준 응답 — 라벨 있는 컬럼 우선, 나머지는 코드만(structure 기준)
    cols: dict[str, Optional[str]] = entry.get("columns", {})
    labeled = [{"code": code, "label": lbl} for code, lbl in cols.items() if lbl]
    unlabeled = [{"code": code, "label": None} for code, lbl in cols.items() if not lbl]
    cols_preview = labeled + unlabeled
    labeled_count = sum(1 for v in cols.values() if v)
    ncols = len(cols)

    raw_desc = entry.get("description") or ""
    desc_heading = "📎 카탈로그 설명 (API 원문):"
    if raw_desc.strip():
        reply_description_block = f"{desc_heading}\n{raw_desc}"
    else:
        reply_description_block = (
            f"{desc_heading}\n(카탈로그에 등록된 설명 문구가 없습니다.)"
        )

    reply_intro_block = (
        f"📋 *{canon_table}* ({_explain_domain_line(entry)})\n"
        f"• 순위: {_explain_rank_line(entry)} / 점수: {_explain_score_line(entry)}\n"
        f"• 행 수: {_explain_rows_line(entry)} / 컬럼: {ncols}개\n"
        f"• 기간: {_explain_period_line(entry)}"
    )

    return {
        "table": canon_table,
        "domain": entry.get("domain") or None,
        "rank": entry.get("rank"),
        "score": entry.get("score"),
        "row_count": entry.get("row_count"),
        "column_count": entry.get("column_count"),
        "data_size_mb": entry.get("data_size_mb"),
        "period": effective_period(
            entry.get("period") or None,
            entry.get("first_date") or None,
            entry.get("last_date") or None,
        ),
        "first_date": normalize_stored_date(entry.get("first_date"))
        or ((entry.get("first_date") or "").strip() or None),
        "last_date": normalize_stored_date(entry.get("last_date"))
        or ((entry.get("last_date") or "").strip() or None),
        "description": entry.get("description") or "",
        # 텔레그램 답변용 — 제목·순위·행수·기간을 한 블록으로 복사
        "reply_intro_block": reply_intro_block,
        # 텔레그램 답변용 — LLM이 요약으로 대체하지 않도록 서버가 고정 블록 제공
        "reply_description_block": reply_description_block,
        "columns_preview": cols_preview,
        "columns_total": ncols,
        "columns_with_korean_label": labeled_count,
        # 텔레그램 등 답변 포맷 — LLM이 구버전 헤더를 쓰지 않도록 서버가 고정 문자열 제공
        "reply_column_heading": f"📌 컬럼 전체 ({ncols}개):",
        "_note": (
            "PK/FK 조인 관계 추론은 현재 범위 밖입니다. "
            "columns_preview는 컬럼 전체입니다. label이 null이면 한글 라벨 미등록입니다. "
            "텔레그램 답변 순서 (모두 수정 없이 통째 출력): "
            "(1) reply_intro_block "
            "(2) reply_description_block (불릿 요약으로 대체 금지) "
            "(3) 선택적 짧은 부연은 설명 블록 아래에만 "
            "(4) reply_column_heading 한 줄 후 columns_preview 전체. "
            "'주요 컬럼', 'columns_preview 최대 30개', '미리보기' 문구 금지. "
            "테이블명 접미사(_TMP 등)·용도에 대한 추측은 JSON에 없으면 쓰지 마세요."
        ),
    }


@app.get(
    "/v1/search",
    summary="테이블 검색",
    response_description="이름·도메인·설명으로 매칭된 테이블 목록",
)
def search(
    q: str = Query(..., min_length=1, description="검색어 (테이블명 일부 또는 도메인)"),
    domain: Optional[str] = Query(
        None,
        description="업무 도메인으로 한정 (예: 쇼핑몰). 생략 시 전체 테이블에서 검색",
    ),
    limit: int = Query(
        DEFAULT_SEARCH_LIMIT,
        ge=1,
        le=MAX_SEARCH_LIMIT,
        description=f"최대 결과 개수 (기본 {DEFAULT_SEARCH_LIMIT}, 상한 {MAX_SEARCH_LIMIT})",
    ),
):
    """테이블 이름, 도메인, 설명 앞부분에서 키워드를 부분 매칭합니다.

    ``domain`` 을 주면 해당 도메인 테이블만 대상으로 하며, ``limit`` 개까지 이 집합 안에서 채웁니다.
    ``domain`` 없이 짧은 키워드만 검색하면 인덱스 순서상 다른 도메인이 먼저 매칭될 수 있습니다.
    """
    q_lower = q.strip().lower()
    dom_needle = domain.strip().lower() if domain and domain.strip() else None
    results = []
    for name, entry in _INDEX.items():
        if dom_needle is not None:
            entry_dom = (entry.get("domain") or "").strip().lower()
            if entry_dom != dom_needle:
                continue
        desc_head = (entry.get("description") or "")[:120].lower()
        if (
            q_lower in name.lower()
            or q_lower in (entry.get("domain") or "").lower()
            or q_lower in desc_head
        ):
            results.append({
                "table": name,
                "domain": entry.get("domain") or None,
                "rank": entry.get("rank"),
                "score": entry.get("score"),
                "description_snippet": _trunc(entry.get("description") or "", 120),
            })
        if len(results) >= limit:
            break
    out: dict = {
        "query": q,
        "limit": limit,
        "results": results,
        "count": len(results),
    }
    if domain is not None and domain.strip():
        out["domain_filter"] = domain.strip()
    return out


@app.get(
    "/v1/domains",
    summary="업무 도메인 목록",
    response_description="도메인별 테이블 수 집계",
)
def list_domains():
    """모든 업무 도메인과 각 도메인의 테이블 수를 반환합니다."""
    from collections import Counter
    counter: Counter = Counter()
    for entry in _INDEX.values():
        d = entry.get("domain") or "(미분류)"
        counter[d] += 1
    return {
        "domains": [
            {"domain": k, "table_count": v}
            for k, v in sorted(counter.items(), key=lambda x: -x[1])
        ]
    }


@app.get(
    "/v1/tables",
    summary="도메인별 테이블 전체 목록",
    response_description="특정 도메인의 모든 테이블 목록",
)
def list_tables(
    domain: str = Query(..., description="도메인명 (예: 쇼핑몰, 매출, 재고)"),
):
    """특정 도메인에 속하는 테이블을 모두 반환합니다 (상한 없음)."""
    d_lower = domain.strip().lower()
    results = []
    for name, entry in _INDEX.items():
        entry_domain = (entry.get("domain") or "").lower()
        if not entry_domain:
            continue
        if d_lower in entry_domain or entry_domain in d_lower:
            results.append({
                "table": name,
                "rank": entry.get("rank"),
                "score": entry.get("score"),
                "description_snippet": _trunc(entry.get("description") or "", 80),
            })
    results.sort(key=lambda x: (x["rank"] is None, x["rank"] or 9999))
    return {"domain": domain, "tables": results, "count": len(results)}


@app.get(
    "/v1/overview",
    summary="DB 전체 개요 (리포트용)",
    response_description="도메인 분포, 상위 테이블, 데이터 규모 요약",
)
def overview(top_n: int = Query(10, description="도메인별 상위 테이블 N개")):
    """DB 전체 구조 개요를 한 번의 호출로 반환합니다."""
    from collections import Counter

    domain_counter: Counter = Counter()
    domain_rows: dict[str, int] = {}
    total_rows = 0
    total_size_mb = 0.0
    date_min, date_max = "", ""

    for entry in _INDEX.values():
        d = entry.get("domain") or "(미분류)"
        domain_counter[d] += 1
        rows = entry.get("row_count") or 0
        domain_rows[d] = domain_rows.get(d, 0) + rows
        total_rows += rows
        size = entry.get("data_size_mb") or 0.0
        total_size_mb += size
        eff_p = effective_period(
            entry.get("period"),
            entry.get("first_date"),
            entry.get("last_date"),
        )
        if eff_p and "~" in eff_p:
            left, _, right = eff_p.partition("~")
            for side in (left.strip(), right.strip()):
                if len(side) >= 10 and side[4] == "-" and side[7] == "-":
                    d10 = side[:10]
                    if not date_min or d10 < date_min:
                        date_min = d10
                    if not date_max or d10 > date_max:
                        date_max = d10

    # 상위 도메인 정리
    domains = [
        {
            "domain": k,
            "table_count": v,
            "total_rows": domain_rows.get(k, 0),
        }
        for k, v in sorted(domain_counter.items(), key=lambda x: -x[1])
    ]

    # rank 기준 상위 테이블 — description_snippet 은 짧은 미리보기용, description 은 전문
    ranked = [
        {
            "rank": e.get("rank"),
            "table": t,
            "domain": e.get("domain"),
            "score": e.get("score"),
            "row_count": e.get("row_count"),
            "description": (e.get("description") or "").strip(),
            "description_snippet": _trunc(e.get("description") or "", 100),
        }
        for t, e in _INDEX.items()
        if e.get("rank") is not None
    ]
    ranked.sort(key=lambda x: x["rank"])
    top_slice = ranked[:top_n]

    summary_out = {
        "total_tables": len(_INDEX),
        "total_domains": len(domain_counter),
        "total_rows_approx": total_rows,
        "total_size_mb_approx": round(total_size_mb, 1),
        "data_period": f"{date_min} ~ {date_max}" if date_min else None,
        "data_period_caveat": (
            "실제 적재·운영 시계열과 다를 수 있습니다. "
            "최대일은 소수 테이블 메타(예: 포인트 적립 유효종료 등)의 미래 일자 때문에 당겨질 수 있습니다."
        ),
    }

    reply_report_md = _overview_reply_markdown(summary_out, domains, top_slice)

    return {
        "summary": summary_out,
        "domains": domains,
        "top_tables": top_slice,
        "reply_report_markdown": reply_report_md,
        "_note": (
            "텔레그램·채팅 답변 시 **`reply_report_markdown`** 필드를 "
            "줄바꿈·숫자 포함 수정 없이 통째로 출력합니다. "
            "‘간단 리포트’, ‘핵심 특징’, ‘한 줄 요약’, 도메인 일부만 골라 적기, "
            "행 수·크기·기간을 반올림해 다시 쓰기 등 자작 요약·해석은 금지입니다. "
            "Top 테이블 설명은 인덱스 전체 문장(`description`)이며 잘리지 않습니다."
        ),
    }


@app.get("/health", include_in_schema=False)
def health():
    """배포 확인용: api_revision이 최신인지 curl로 비교하세요."""
    return {
        "status": "ok",
        "tables_loaded": len(_INDEX),
        "api_revision": "2026-05-03-overview-period-caveat",
    }
