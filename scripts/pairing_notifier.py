#!/usr/bin/env python3
"""
EHC Mall pairing notifier daemon.

OpenClaw 게이트웨이 로그를 tail -F 로 따라가며,
'telegram pairing request' 이벤트를 감지하면 owner 에게 텔레그램 알림을 보낸다.

알림에는 사용자 정보 + 발급된 pairing code + 승인 명령어가 포함된다.
Owner 는 텔레그램에서 plugin (ehcmall-pairing-relay) 의 /approve <CODE> 로 승인.

환경변수
  OWNER_CHAT_ID       필수 — owner Telegram user id
  TELEGRAM_BOT_TOKEN  선택 — 비워두면 ~/.openclaw/openclaw.json 의 ehcmall.botToken 사용
  LOG_DIR             선택 — OpenClaw 로그 디렉토리 (기본: /tmp/openclaw)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOG_DIR", "/tmp/openclaw"))
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "").strip()


def load_bot_token():
    explicit = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if explicit:
        return explicit
    cfg_path = Path.home() / ".openclaw" / "openclaw.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return (
            cfg.get("channels", {})
            .get("telegram", {})
            .get("accounts", {})
            .get("ehcmall", {})
            .get("botToken", "")
        )
    except Exception as e:
        print(f"[notifier] failed to read {cfg_path}: {e}", file=sys.stderr)
        return ""


BOT_TOKEN = load_bot_token()

if not BOT_TOKEN or not OWNER_CHAT_ID:
    print(
        "[notifier] missing TELEGRAM_BOT_TOKEN (or openclaw.json botToken) "
        "or OWNER_CHAT_ID",
        file=sys.stderr,
    )
    sys.exit(1)


def latest_log():
    if not LOG_DIR.exists():
        return None
    candidates = sorted(LOG_DIR.glob("openclaw-*.log"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": OWNER_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }
    ).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            resp.read()
        print(f"[notifier] sent to {OWNER_CHAT_ID}: {text[:80]}")
    except Exception as e:
        print(f"[notifier] send failed: {e}", file=sys.stderr)


def parse_pairing_event(line):
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None
    parts = []
    for key in ("0", "1", "2"):
        v = obj.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif v is not None:
            parts.append(json.dumps(v, ensure_ascii=False))
    joined = " ".join(parts)
    if "telegram pairing request" not in joined:
        return None
    user = obj.get("1") if isinstance(obj.get("1"), dict) else {}
    return {
        "chatId": str(user.get("chatId") or ""),
        "senderUserId": str(user.get("senderUserId") or ""),
        "firstName": str(user.get("firstName") or ""),
        "lastName": str(user.get("lastName") or ""),
    }


def fetch_pairing_code_for(sender_user_id):
    """openclaw pairing list 출력에서 senderUserId 매칭하는 code 추출."""
    if not sender_user_id:
        return None
    try:
        r = subprocess.run(
            ["openclaw", "pairing", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as e:
        print(f"[notifier] pairing list failed: {e}", file=sys.stderr)
        return None
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    for line in text.splitlines():
        if sender_user_id in line:
            m = re.search(r"\b([A-Z0-9]{6,12})\b", line)
            if m and m.group(1) != sender_user_id:
                return m.group(1)
    return None


def tail_loop(log_path):
    print(f"[notifier] tailing {log_path}")
    proc = subprocess.Popen(
        ["tail", "-Fn0", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1,
    )
    assert proc.stdout
    seen = {}
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="ignore")
        info = parse_pairing_event(line)
        if not info:
            continue
        key = info["senderUserId"] or info["chatId"]
        now = time.time()
        if key in seen and now - seen[key] < 30:
            continue
        seen[key] = now

        time.sleep(1.0)
        code = fetch_pairing_code_for(info["senderUserId"])
        name = (info["firstName"] + " " + info["lastName"]).strip() or "(이름 없음)"
        msg = (
            "🔐 *새 Pairing 요청*\n\n"
            f"이름: {name}\n"
            f"User ID: `{info['senderUserId']}`\n"
        )
        if code:
            msg += f"코드: `{code}`\n\n*승인:* `/approve {code}`"
        else:
            msg += "코드: (확인 필요)\n\n`/pending` 으로 대기 목록 확인"
        send_telegram(msg)


def main():
    while True:
        log = latest_log()
        if not log:
            print("[notifier] waiting for log file…", file=sys.stderr)
            time.sleep(5)
            continue
        try:
            tail_loop(log)
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"[notifier] loop crashed: {e}; retrying in 5s", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
