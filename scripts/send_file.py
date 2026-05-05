#!/usr/bin/env python3
"""
send_file.py — 이미 존재하는 파일을 텔레그램으로 전송.

사용법:
    python3 send_file.py <chat_id> <file_path> [--account ehcmall] [--caption "캡션"]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.request
from pathlib import Path

OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
TG_API_BASE = "https://api.telegram.org"


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


def _send_document(
    token: str,
    chat_id: str,
    file_path: Path,
    caption: str,
    content_type: str,
) -> dict:
    url = f"{TG_API_BASE}/bot{token}/sendDocument"
    boundary = "----SendFileBoundary"
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


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 파일을 텔레그램으로 전송")
    parser.add_argument("chat_id", help="텔레그램 chat_id")
    parser.add_argument("file_path", help="전송할 파일의 경로 (절대 경로 또는 ~/... 형태)")
    parser.add_argument("--account", default="ehcmall", help="openclaw.json 계정명 (기본: ehcmall)")
    parser.add_argument("--token", default="", help="봇 토큰 직접 지정 (생략 시 openclaw.json에서 로드)")
    parser.add_argument("--caption", default="", help="파일 캡션 (생략 시 자동 생성)")
    args = parser.parse_args()

    file_path = Path(args.file_path).expanduser().resolve()
    if not file_path.exists():
        print(f"[오류] 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
        sys.exit(2)
    if not file_path.is_file():
        print(f"[오류] 경로가 파일이 아닙니다: {file_path}", file=sys.stderr)
        sys.exit(2)

    token = args.token.strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        token = _load_bot_token(args.account)

    ctype, _ = mimetypes.guess_type(str(file_path))
    if ctype is None:
        ctype = "application/octet-stream"

    caption = args.caption.strip() or f"`{file_path.name}`"

    size_kb = max(file_path.stat().st_size // 1024, 1)
    print(f"[1/2] 전송 중… ({file_path.name}, {size_kb} KB, chat_id={args.chat_id})", flush=True)
    result = _send_document(token, args.chat_id, file_path, caption, ctype)

    if result.get("ok"):
        print(f"[2/2] 전송 완료 ✓ (message_id={result['result']['message_id']})", flush=True)
        print(f"파일 저장 경로: {file_path}", flush=True)
    else:
        print(f"[오류] 텔레그램 전송 실패: {result}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
