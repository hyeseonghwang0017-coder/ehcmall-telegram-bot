#!/usr/bin/env python3
"""
PDF export wrapper — passes all args to export_tables.py.
Use this instead of export_tables.py for PDF requests.
For CSV, continue using export_tables.py directly.

--summary is required for PDF format. If omitted, this script exits 1
so the caller sees an explicit error rather than a silently empty summary.
"""
import sys
import subprocess
import os

REAL_SCRIPT = os.path.join(os.path.dirname(__file__), "export_tables.py")


def _extract(args, flag):
    """Return value after `flag` in args list, or None."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return None


args = sys.argv[1:]

has_summary = "--summary" in args
fmt = _extract(args, "--format")

if fmt == "pdf" and not has_summary:
    print("[export_pdf] 오류: PDF 형식에는 --summary가 필수입니다. SKILL_export.md 3단계를 확인하세요.", file=sys.stderr)
    sys.exit(1)

result = subprocess.run([sys.executable, REAL_SCRIPT] + args)
sys.exit(result.returncode)
