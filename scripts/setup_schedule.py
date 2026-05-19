#!/usr/bin/env python3
"""
ตั้งค่า cron job สร้างคลิปอัตโนมัติ 2 ครั้งต่อวัน
Thai TikTok peak hours: 7:30 AM + 7:30 PM

Usage:
  python scripts/setup_schedule.py          # ตั้งค่า cron
  python scripts/setup_schedule.py --remove # ลบ cron
  python scripts/setup_schedule.py --status # ดู cron ปัจจุบัน
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR  = Path(__file__).parent.parent.resolve()
PYTHON       = PROJECT_DIR / ".venv" / "bin" / "python"
LOG_FILE     = PROJECT_DIR / "logs" / "schedule.log"
CRON_TAG     = "# auto-clip"

SCHEDULES = [
    ("30", "7",  "07:30 AM (Thai morning peak)"),
    ("30", "19", "07:30 PM (Thai evening peak)"),
]


def _get_crontab() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _set_crontab(content: str):
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def _make_entry(minute: str, hour: str) -> str:
    cmd = (f"cd {PROJECT_DIR} && "
           f"{PYTHON} main.py --auto "
           f">> {LOG_FILE} 2>&1")
    return f"{minute} {hour} * * *  {cmd}  {CRON_TAG}"


def setup():
    LOG_FILE.parent.mkdir(exist_ok=True)
    current = _get_crontab()
    # ลบ entries เดิมออกก่อน
    lines   = [l for l in current.splitlines() if CRON_TAG not in l]
    for minute, hour, label in SCHEDULES:
        lines.append(_make_entry(minute, hour))
        print(f"  ✅ ตั้งค่า cron: {label}")
    _set_crontab("\n".join(lines) + "\n")
    print(f"\nLog: {LOG_FILE}")
    print("รัน 'crontab -l' เพื่อยืนยัน")


def remove():
    current = _get_crontab()
    lines   = [l for l in current.splitlines() if CRON_TAG not in l]
    _set_crontab("\n".join(lines) + "\n")
    print("✅ ลบ auto-clip cron jobs แล้ว")


def status():
    current = _get_crontab()
    entries = [l for l in current.splitlines() if CRON_TAG in l]
    if entries:
        print(f"✅ auto-clip cron active ({len(entries)} entries):")
        for e in entries:
            print(f"  {e}")
    else:
        print("❌ ไม่มี auto-clip cron — รัน 'python scripts/setup_schedule.py' เพื่อตั้งค่า")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--remove", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    if args.remove:
        remove()
    elif args.status:
        status()
    else:
        setup()
