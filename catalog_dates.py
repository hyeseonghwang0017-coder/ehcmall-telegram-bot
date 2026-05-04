"""
랭킹 CSV·인덱스의 기간 문자열 정규화 (YYYYMMDD → ISO) 및 한국어 표기.
api/main.py · etl/build_ontology.py 에서 공통 사용.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_YEAR_MIN, _YEAR_MAX = 1990, 2035


def normalize_period_endpoint(side: str) -> Optional[str]:
    """단일 끝점을 YYYY-MM-DD 또는 YYYY-MM 으로 통일. 불가면 None."""
    side = (side or "").strip()
    if not side:
        return None
    date_part = side.split()[0]

    if re.fullmatch(r"\d{8}", date_part):
        try:
            dt = datetime.strptime(date_part, "%Y%m%d")
        except ValueError:
            return None
        if not (_YEAR_MIN <= dt.year <= _YEAR_MAX):
            return None
        return dt.strftime("%Y-%m-%d")

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part):
        try:
            dt = datetime.strptime(date_part, "%Y-%m-%d")
        except ValueError:
            return None
        if not (_YEAR_MIN <= dt.year <= _YEAR_MAX):
            return None
        return date_part

    if re.fullmatch(r"\d{4}-\d{2}", date_part):
        y = int(date_part[:4])
        m = int(date_part[5:7])
        if not (_YEAR_MIN <= y <= _YEAR_MAX) or not (1 <= m <= 12):
            return None
        return date_part

    return None


def sanitize_period(raw: Optional[str]) -> Optional[str]:
    """'시작 ~ 끝' 문자열 검증 후 양 끝을 ISO 형태로 통일."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if "~" not in s:
        return None
    left, _, right = s.partition("~")
    left_n = normalize_period_endpoint(left)
    right_n = normalize_period_endpoint(right)
    if not left_n or not right_n:
        return None
    return f"{left_n} ~ {right_n}"


def period_from_first_last(first_raw: Optional[str], last_raw: Optional[str]) -> Optional[str]:
    fd = normalize_period_endpoint((first_raw or "").strip())
    ld = normalize_period_endpoint((last_raw or "").strip())
    if fd and ld:
        return f"{fd} ~ {ld}"
    return None


def effective_period(
    period_raw: Optional[str],
    first_raw: Optional[str],
    last_raw: Optional[str],
) -> Optional[str]:
    p = sanitize_period(period_raw)
    if p:
        return p
    return period_from_first_last(first_raw, last_raw)


def format_endpoint_korean(iso: str) -> str:
    """YYYY-MM-DD 또는 YYYY-MM → 한국어 날짜/월."""
    iso = iso.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        y, m, d = map(int, iso.split("-"))
        return f"{y}년 {m}월 {d}일"
    if re.fullmatch(r"\d{4}-\d{2}", iso):
        y, m = map(int, iso.split("-"))
        return f"{y}년 {m}월"
    return iso


def format_period_range_korean(iso_range: str) -> str:
    """'YYYY-MM-DD ~ YYYY-MM-DD' → '…년 …월 …일 ~ …'."""
    if "~" not in iso_range:
        return format_endpoint_korean(iso_range)
    left, _, right = iso_range.partition("~")
    return f"{format_endpoint_korean(left)} ~ {format_endpoint_korean(right)}"


def normalize_stored_date(raw: Optional[str]) -> Optional[str]:
    """first_date / last_date 필드용: 가능하면 ISO 일자로."""
    if not raw or not isinstance(raw, str):
        return None
    return normalize_period_endpoint(raw.strip()) or None
