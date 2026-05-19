#!/usr/bin/env python3
"""
เงินงอก Telegram Bot — Claude AI assistant
พิมอะไรก็ได้ ตอบรู้บริบทโปรเจคทั้งหมด
"""

import os, sys, time, subprocess, json
from pathlib import Path
from datetime import datetime

import requests
import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ANTH_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
ROOT      = Path(__file__).parent.parent

client = anthropic.Anthropic(api_key=ANTH_KEY)

# Rate limit: ไม่เกิน 20 ข้อความต่อชั่วโมง
_msg_times: list = []
MAX_MSG_PER_HOUR = 20


def _is_rate_limited() -> bool:
    now = time.time()
    global _msg_times
    _msg_times = [t for t in _msg_times if now - t < 3600]
    if len(_msg_times) >= MAX_MSG_PER_HOUR:
        return True
    _msg_times.append(now)
    return False


SYSTEM = """คุณคือ AI assistant ส่วนตัวของช่อง YouTube "เงินงอก" (@NgernNgork)
คุณดูแลระบบ auto-clip pipeline บน Mac ที่รันอัตโนมัติทุกวัน

=== โปรเจค ===
Path: /Users/badboybank/auto-clip
Pipeline: สร้างคลิปยาว 16:9 + 4 shorts 9:16 จาก 1 topic/วัน
ตารางโพส: 05:50 generate → 08:00/11:30/16:30/19:00 โพสแต่ละ slot

=== Platform ===
- YouTube: คลิปยาว + 4 Shorts (description ลิงก์ไปคลิปยาว)
- Instagram: 4 Reels + auto-comment ลิงก์ + bio → ngerngork.netlify.app
- Facebook: 4 Reels (จบในตัว)
- TikTok: รอ app approval

=== Tech stack ===
- Script: Claude Sonnet API
- TTS: ElevenLabs eleven_v3 (เสียงชาย)
- Video: FFmpeg + PIL animations
- BG: Pexels API
- Scheduler: macOS LaunchAgents
- Notify: Telegram (bot นี้)

=== Files สำคัญ ===
- logs/pipeline.log — log การ generate
- logs/post.log — log การโพส
- config/topics.json — topic queue + history
- output/ — คลิปที่ generate แล้ว (เก็บ 3 วัน)
- .env — API keys ทั้งหมด

=== วิธีตอบ ===
- ตอบภาษาไทย กระชับ เข้าใจง่าย
- ถ้าถามสถานะ ดูข้อมูล context ที่ให้มา
- ถ้าถามวิธีแก้ปัญหา ให้คำแนะนำตรงๆ
- ถ้าสั่งรัน บอกผลลัพธ์
- ใช้ emoji ให้อ่านง่าย แต่ไม่เยอะเกิน"""


def _get_live_context() -> str:
    """ดึงข้อมูล live ให้ Claude รู้สถานะปัจจุบัน"""
    ctx = []

    # Log ล่าสุด
    for log_name in ("pipeline", "post"):
        p = ROOT / "logs" / f"{log_name}.log"
        if p.exists():
            lines = p.read_text(encoding="utf-8").splitlines()
            last = "\n".join(lines[-8:])
            ctx.append(f"=== {log_name}.log (8 บรรทัดล่าสุด) ===\n{last}")

    # Topic queue
    topics_file = ROOT / "config" / "topics.json"
    if topics_file.exists():
        try:
            data = json.loads(topics_file.read_text(encoding="utf-8"))
            pending = len(data.get("pending", []))
            used    = len(data.get("used", []))
            ctx.append(f"=== Topics: pending={pending}, used={used} ===")
        except Exception:
            pass

    # Output folders
    output = ROOT / "output"
    if output.exists():
        folders = sorted(output.iterdir(), reverse=True)[:3]
        names = [f.name for f in folders if f.is_dir()]
        ctx.append(f"=== Output folders (ล่าสุด 3): {names} ===")

    # ElevenLabs credits
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    if el_key:
        try:
            r = requests.get("https://api.elevenlabs.io/v1/user/subscription",
                             headers={"xi-api-key": el_key}, timeout=8)
            if r.ok:
                sub = r.json()
                used_c  = sub.get("character_count", 0)
                limit_c = sub.get("character_limit", 0)
                ctx.append(f"=== ElevenLabs: {used_c:,}/{limit_c:,} chars used ===")
        except Exception:
            pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"[ข้อมูล live ณ {now}]\n" + "\n".join(ctx)


def _run_command(cmd: str) -> str:
    """รัน shell command แล้วคืน output"""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, cwd=str(ROOT),
        )
        return (r.stdout + r.stderr).strip()[:800] or "(no output)"
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return str(e)


def _tg_send(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=10,
    )


def _tg_typing():
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction",
        data={"chat_id": CHAT_ID, "action": "typing"},
        timeout=5,
    )


def handle_message(text: str):
    """ส่งข้อความไป Claude แล้วตอบกลับ"""
    if _is_rate_limited():
        _tg_send("⚠️ ส่งมากเกินไป รอสักครู่แล้วลองใหม่นะครับ (max 20 ข้อความ/ชั่วโมง)")
        return
    _tg_typing()

    # ถ้าสั่งรัน pipeline/post โดยตรง
    if text.strip().startswith("/run"):
        _tg_send("🚀 กำลังรัน pipeline... (ใช้เวลา ~1 ชั่วโมง)")
        out = _run_command(
            "source .venv/bin/activate && "
            "DYLD_LIBRARY_PATH=/opt/homebrew/lib "
            "python3 main.py --long --auto"
        )
        _tg_send(f"✅ เสร็จแล้ว:\n<code>{out[-500:]}</code>")
        return

    if text.strip().startswith("/post"):
        slot = text.strip().split()[-1] if len(text.split()) > 1 else ""
        cmd = f"source .venv/bin/activate && python3 post.py --long"
        if slot.isdigit():
            cmd += f" --slot {slot}"
        out = _run_command(cmd)
        _tg_send(f"📤 Post result:\n<code>{out[-500:]}</code>")
        return

    # ส่งไป Claude พร้อม context live
    live_ctx = _get_live_context()
    messages = [{"role": "user", "content": f"{live_ctx}\n\n---\nคำถาม: {text}"}]

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM,
            messages=messages,
        )
        reply = resp.content[0].text
    except Exception as e:
        reply = f"❌ Claude API error: {e}"

    # ส่งทีละ 4000 chars (Telegram limit)
    for i in range(0, len(reply), 4000):
        _tg_send(reply[i:i+4000])


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("ไม่มี TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID")
        sys.exit(1)

    print(f"🤖 เงินงอก Bot เริ่มแล้ว | polling...")
    offset = 0

    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35,
            )
            if not r.ok:
                time.sleep(5)
                continue

            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                # รับเฉพาะ message จาก chat_id ของเจ้าของ
                if str(msg.get("chat", {}).get("id", "")) != str(CHAT_ID):
                    continue
                text = msg.get("text", "").strip()
                if text:
                    print(f"→ {text}")
                    handle_message(text)

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
