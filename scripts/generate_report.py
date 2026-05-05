#!/usr/bin/env python3
"""
generate_report.py — EHC Mall DB 개요 PDF 생성 & 텔레그램 전송

사용법:
    python3 generate_report.py <chat_id> [옵션]
    python3 generate_report.py --no-send [옵션]   # 전송 없이 PDF만 생성

동작:
    1. /v1/overview API 호출 → DB 개요 데이터 수집
    2. reportlab으로 한국어 PDF 생성 → ~/Downloads/ehcmall-reports/ 저장
    3. Telegram sendDocument API로 파일 전송 (--no-send 생략 시)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ── reportlab ────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── 상수 (환경변수로 재정의 가능) ────────────────────────────────
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
FONT_NAME = "Korean"
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(Path.home() / "Downloads" / "ehcmall-reports")))
OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
TG_API_BASE = "https://api.telegram.org"

SECTION_CHOICES = ["summary", "domains", "top-tables"]
DEFAULT_SECTIONS = ["summary", "domains", "top-tables"]


# ── 폰트 등록 ────────────────────────────────────────────────────
def _register_font() -> None:
    try:
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
        pdfmetrics.registerFont(TTFont(FONT_NAME + "-Bold",   FONT_PATH))
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


# ── API 호출 ─────────────────────────────────────────────────────
def _fetch_overview(top_n: int = 10) -> dict:
    url = f"{API_BASE}/v1/overview?top_n={top_n}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _fetch_domain(domain: str) -> dict:
    url = f"{API_BASE}/v1/tables?domain={urllib.parse.quote(domain)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _fetch_keyword(keyword: str) -> dict:
    url = f"{API_BASE}/v1/search?q={urllib.parse.quote(keyword)}&limit=50"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ── 스타일 헬퍼 ──────────────────────────────────────────────────
def _make_styles() -> dict:
    base = getSampleStyleSheet()
    def _ps(name, parent="Normal", **kw):
        kw.setdefault("fontName", FONT_NAME)
        return ParagraphStyle(name, parent=base[parent], **kw)

    return {
        "title":      _ps("title",      fontSize=20, spaceAfter=6, textColor=colors.HexColor("#1a1a2e"), leading=26),
        "subtitle":   _ps("subtitle",   fontSize=11, spaceAfter=2, textColor=colors.HexColor("#4a4a6a")),
        "h2":         _ps("h2",         fontSize=13, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1a1a2e"), leading=18),
        "body":       _ps("body",       fontSize=10, leading=15),
        "small":      _ps("small",      fontSize=8.5, textColor=colors.grey, leading=12),
        "th":         _ps("th",         fontSize=9.5, leading=13, textColor=colors.white, wordWrap="CJK"),
        "td":         _ps("td",         fontSize=9,   leading=13, wordWrap="CJK"),
        "td_right":   _ps("td_right",   fontSize=9,   leading=13, alignment=2, wordWrap="CJK"),
    }


def _tbl_style(header_color=colors.HexColor("#1a1a2e")) -> TableStyle:
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  header_color),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5fa")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#ccccdd")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ])


def _th(text: str, S: dict) -> Paragraph:
    return Paragraph(text, S["th"])


def _td(text: str, S: dict, right: bool = False) -> Paragraph:
    return Paragraph(str(text), S["td_right"] if right else S["td"])


# ── PDF 빌드 ─────────────────────────────────────────────────────
def _build_pdf(
    data: dict,
    out_path: Path,
    generated_at: str,
    sections: list[str],
    domain_data: dict | None = None,
    keyword_data: dict | None = None,
) -> None:
    summary    = data["summary"]
    domains    = data["domains"]
    top_tables = data["top_tables"]

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
    )
    S = _make_styles()
    W = doc.width
    story = []

    # ── 제목 블록 ───────────────────────────────────────────────
    story.append(Paragraph("유진홈센터 DB 개요 리포트", S["title"]))
    story.append(Paragraph(f"생성 일시: {generated_at}", S["subtitle"]))
    story.append(Spacer(1, 6 * mm))

    # ── 섹션 1: DB 규모 요약 ─────────────────────────────────────
    if "summary" in sections:
        story.append(Paragraph("DB 규모 요약", S["h2"]))

        tt = summary["total_tables"]
        td_val = summary["total_domains"]
        tr = summary["total_rows_approx"]
        tm = summary["total_size_mb_approx"]
        dp = summary.get("data_period") or "(기간 정보 없음)"
        caveat = (summary.get("data_period_caveat") or "").strip()

        col_w = [W * 0.42, W * 0.58]
        summary_rows = [
            [_th("항목", S),              _th("수치", S)],
            [_td("전체 테이블 수", S),    _td(f"{tt:,} 개", S)],
            [_td("도메인 수", S),         _td(f"{td_val} 개", S)],
            [_td("총 데이터 행 수(근사)", S), _td(f"{tr:,} 행", S)],
            [_td("총 데이터 크기(근사)", S),  _td(f"{tm:,} MB", S)],
            [_td("메타데이터 일자 범위", S),  _td(dp, S)],
        ]
        t = Table(summary_rows, colWidths=col_w)
        t.setStyle(_tbl_style())
        story.append(t)
        if caveat:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(f"※ {caveat}", S["small"]))
        story.append(Spacer(1, 5 * mm))

    # ── 섹션 2: 도메인별 테이블 분포 ─────────────────────────────
    if "domains" in sections:
        story.append(Paragraph("도메인별 테이블 분포", S["h2"]))
        col_w2 = [W * 0.44, W * 0.22, W * 0.34]
        dom_rows = [
            [_th("도메인", S), _th("테이블 수", S), _th("총 행 수(근사)", S)],
        ]
        for d in domains:
            dom_rows.append([
                _td(d["domain"], S),
                _td(f"{d['table_count']:,}", S, right=True),
                _td(f"{d.get('total_rows', 0):,}", S, right=True),
            ])
        t2 = Table(dom_rows, colWidths=col_w2)
        t2.setStyle(_tbl_style())
        story.append(t2)
        story.append(Spacer(1, 5 * mm))

    # ── 섹션 3: 핵심 테이블 Top N ────────────────────────────────
    if "top-tables" in sections:
        n = len(top_tables)
        story.append(Paragraph(f"핵심 테이블 Top {n}", S["h2"]))
        col_w3 = [W * 0.06, W * 0.19, W * 0.11, W * 0.07, W * 0.09, W * 0.07, W * 0.41]
        top_rows = [
            [_th("순위", S), _th("테이블명", S), _th("도메인", S), _th("점수", S), _th("행 수", S), _th("컬럼 수", S), _th("설명", S)],
        ]
        for item in top_tables:
            desc = (item.get("description") or item.get("description_snippet") or "").strip()
            sc = item.get("score")
            rc = item.get("row_count")
            cc = item.get("column_count")
            top_rows.append([
                _td(str(item["rank"]), S, right=True),
                _td(item["table"], S),
                _td((item.get("domain") or "").strip() or "미분류", S),
                _td("-" if sc is None else str(sc), S, right=True),
                _td(f"{rc:,}" if isinstance(rc, int) else "-", S, right=True),
                _td(f"{cc:,}" if isinstance(cc, int) else "-", S, right=True),
                _td(desc, S),
            ])
        t3 = Table(top_rows, colWidths=col_w3, repeatRows=1)
        t3.setStyle(_tbl_style())
        story.append(t3)
        story.append(Spacer(1, 5 * mm))

    # ── 추가 섹션: 도메인 테이블 목록 ────────────────────────────
    if domain_data is not None:
        domain_name = domain_data.get("domain", "")
        tables = domain_data.get("tables", [])
        story.append(Paragraph(f"도메인 상세: {domain_name} ({len(tables)}개)", S["h2"]))
        col_wd = [W * 0.06, W * 0.25, W * 0.07, W * 0.62]
        dom_tbl_rows = [
            [_th("순위", S), _th("테이블명", S), _th("점수", S), _th("설명", S)],
        ]
        for item in tables:
            rk = item.get("rank")
            sc = item.get("score")
            dom_tbl_rows.append([
                _td("-" if rk is None else str(rk), S, right=True),
                _td(item["table"], S),
                _td("-" if sc is None else str(sc), S, right=True),
                _td((item.get("description_snippet") or "").strip(), S),
            ])
        td = Table(dom_tbl_rows, colWidths=col_wd, repeatRows=1)
        td.setStyle(_tbl_style())
        story.append(td)
        story.append(Spacer(1, 5 * mm))

    # ── 추가 섹션: 키워드 검색 결과 ──────────────────────────────
    if keyword_data is not None:
        kw = keyword_data.get("query", "")
        results = keyword_data.get("results", [])
        story.append(Paragraph(f"키워드 검색: '{kw}' ({len(results)}개)", S["h2"]))
        col_wk = [W * 0.06, W * 0.25, W * 0.13, W * 0.07, W * 0.49]
        kw_rows = [
            [_th("순위", S), _th("테이블명", S), _th("도메인", S), _th("점수", S), _th("설명", S)],
        ]
        for item in results:
            rk = item.get("rank")
            sc = item.get("score")
            kw_rows.append([
                _td("-" if rk is None else str(rk), S, right=True),
                _td(item["table"], S),
                _td((item.get("domain") or "").strip() or "미분류", S),
                _td("-" if sc is None else str(sc), S, right=True),
                _td((item.get("description_snippet") or "").strip(), S),
            ])
        tk = Table(kw_rows, colWidths=col_wk, repeatRows=1)
        tk.setStyle(_tbl_style())
        story.append(tk)
        story.append(Spacer(1, 5 * mm))

    # ── 푸터 ────────────────────────────────────────────────────
    story.append(Paragraph(
        f"이 리포트는 EHC Mall DB Ontology API ({API_BASE})가 제공한 메타데이터 기준입니다. "
        f"실제 운영 DB 내용과 차이가 있을 수 있습니다.",
        S["small"],
    ))

    doc.build(story)


# ── Telegram sendDocument ────────────────────────────────────────
def _send_document(token: str, chat_id: str, file_path: Path, caption: str) -> dict:
    url = f"{TG_API_BASE}/bot{token}/sendDocument"
    boundary = "----PdfReportBoundary"
    lines: list[bytes] = []

    def _field(name: str, value: str) -> None:
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value.encode("utf-8"))

    def _file_field(name: str, filename: str, data: bytes) -> None:
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode()
        )
        lines.append(b"Content-Type: application/pdf")
        lines.append(b"")
        lines.append(data)

    _field("chat_id", str(chat_id))
    _field("caption", caption)
    _field("parse_mode", "Markdown")

    with open(file_path, "rb") as f:
        pdf_bytes = f.read()
    _file_field("document", file_path.name, pdf_bytes)

    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines)

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ── 메인 ─────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="EHC Mall DB 개요 PDF 생성 & 텔레그램 전송")
    parser.add_argument("chat_id", nargs="?", default="",
        help="텔레그램 chat_id (숫자 또는 @채널명). --no-send 시 생략 가능")
    parser.add_argument("--account", default="ehcmall", help="openclaw.json 계정명 (기본: ehcmall)")
    parser.add_argument("--token",   default="",        help="봇 토큰 직접 지정 (생략 시 openclaw.json에서 로드)")
    parser.add_argument("--top-n",   type=int, default=10, help="상위 테이블 개수 (기본: 10)")

    # 섹션 제어
    parser.add_argument("--exclude", nargs="*", choices=SECTION_CHOICES, default=[],
        metavar="SECTION",
        help="제외할 섹션 (summary / domains / top-tables). 예: --exclude top-tables")
    parser.add_argument("--only", nargs="*", choices=SECTION_CHOICES, default=None,
        metavar="SECTION",
        help="이것만 포함 (--exclude와 택일). 예: --only summary domains")

    # 추가 섹션
    parser.add_argument("--domain", default=None,
        help="추가 섹션: 특정 도메인 테이블 목록. 예: --domain 재고")
    parser.add_argument("--keyword", default=None,
        help="추가 섹션: 키워드 검색 결과. 예: --keyword 주문")

    # 실행 제어
    parser.add_argument("--no-send", action="store_true",
        help="텔레그램 전송 없이 PDF만 생성")
    parser.add_argument("--out-dir", default=None,
        help="PDF 저장 경로 (기본: ~/Downloads/ehcmall-reports)")
    parser.add_argument("--api-base", default=None,
        help="API 서버 주소 (기본: http://127.0.0.1:8000 또는 $API_BASE)")

    args = parser.parse_args()

    # chat_id 필수 검증 (--no-send가 아닐 때)
    if not args.no_send and not args.chat_id:
        parser.error("chat_id는 --no-send 없이 실행할 때 필수입니다.")

    # api-base 인자 반영
    global API_BASE
    if args.api_base:
        API_BASE = args.api_base.rstrip("/")

    # 출력 경로
    out_dir = Path(args.out_dir) if args.out_dir else REPORT_DIR

    # 섹션 목록 계산
    if args.only is not None:
        sections = args.only
    else:
        sections = [s for s in DEFAULT_SECTIONS if s not in (args.exclude or [])]

    if not sections and domain_data is None and keyword_data is None:
        print("[경고] 포함할 섹션이 없습니다. --only 또는 --exclude 인자를 확인하세요.", file=sys.stderr)

    # 봇 토큰 (--no-send 시 불필요)
    token = ""
    if not args.no_send:
        args.chat_id = args.chat_id.strip().removeprefix("telegram:")
        token = args.token.strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            token = _load_bot_token(args.account)

    # 폰트
    _register_font()

    # API 호출
    print("[1/4] API 호출 중…", flush=True)
    data = _fetch_overview(args.top_n)

    domain_data = None
    keyword_data = None
    if args.domain:
        print(f"      도메인 섹션 수집: {args.domain}", flush=True)
        domain_data = _fetch_domain(args.domain)
    if args.keyword:
        print(f"      키워드 검색 수집: {args.keyword}", flush=True)
        keyword_data = _fetch_keyword(args.keyword)

    # PDF 생성
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"ehcmall_report_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    out_path = out_dir / filename

    print(f"[2/4] PDF 생성 중… → {out_path}", flush=True)
    _build_pdf(data, out_path, generated_at, sections, domain_data, keyword_data)
    size_kb = out_path.stat().st_size // 1024
    print(f"      완료: {size_kb} KB", flush=True)

    # 전송
    if args.no_send:
        print(f"[3/4] 전송 생략 (--no-send)", flush=True)
        print(f"[4/4] 완료", flush=True)
        print(f"PDF 저장 경로: {out_path}", flush=True)
        return

    tt = data["summary"]["total_tables"]
    td = data["summary"]["total_domains"]
    caption = (
        f"*유진홈센터 DB 개요 리포트*\n"
        f"생성: {generated_at}\n"
        f"테이블 {tt:,}개 / 도메인 {td}개"
    )
    print(f"[3/4] 텔레그램 전송 중… (chat_id={args.chat_id})", flush=True)
    result = _send_document(token, args.chat_id, out_path, caption)

    if result.get("ok"):
        print(f"[4/4] 전송 완료 ✓  (message_id={result['result']['message_id']})", flush=True)
        print(f"PDF 저장 경로: {out_path}", flush=True)
    else:
        print(f"[오류] 텔레그램 전송 실패: {result}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
