"""Telegram notification — เงินงอก Pipeline"""

import os
from datetime import datetime
import requests
from loguru import logger

_SLOT_TIMES = ["08:00", "11:30", "16:30", "19:00"]
_DIV = "─" * 22


def _now() -> str:
    return datetime.now().strftime("%H:%M น.")


def _send(text: str):
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": "true"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram: {e}")


# ─── Pipeline ────────────────────────────────────────────────────────────────

def notify_pipeline_start(topic: str):
    _send(
        f"🎬 <b>เริ่มสร้างคลิปแล้ว</b>\n"
        f"{_DIV}\n"
        f"📌 <b>หัวข้อ:</b> {topic}\n"
        f"⏰ <b>เริ่ม:</b> {_now()}\n"
        f"{_DIV}\n"
        f"⏳ คาดว่าเสร็จใน ~1 ชั่วโมง"
    )


def notify_pipeline_done(topic: str, run_dir: str, n_shorts: int):
    _send(
        f"✅ <b>สร้างคลิปเสร็จแล้ว!</b>\n"
        f"{_DIV}\n"
        f"📌 {topic}\n"
        f"🎥 1 คลิปยาว + {n_shorts} shorts\n"
        f"{_DIV}\n"
        f"📤 จะโพสอัตโนมัติตอน 08:00 น."
    )


def notify_pipeline_fail(topic: str, error: str):
    _send(
        f"❌ <b>Pipeline พัง!</b>\n"
        f"{_DIV}\n"
        f"📌 {topic}\n"
        f"🔴 <code>{error[:180]}</code>\n"
        f"{_DIV}\n"
        f"🔧 ดู log: <code>logs/pipeline.log</code>\n"
        f"💬 ส่ง error มาให้ผมแก้ได้เลย"
    )


# ─── Post ────────────────────────────────────────────────────────────────────

def notify_post_done(slot: int, slot_time: str, results: dict):
    icons = {
        "youtube":        "▶️ YouTube Long  ",
        "youtube_shorts": "🩳 YT Shorts     ",
        "facebook_s1":    "📘 Facebook S1   ",
        "facebook_s2":    "📘 Facebook S2   ",
        "facebook_s3":    "📘 Facebook S3   ",
        "facebook_s4":    "📘 Facebook S4   ",
        "instagram_s1":   "📸 Instagram S1  ",
        "instagram_s2":   "📸 Instagram S2  ",
        "instagram_s3":   "📸 Instagram S3  ",
        "instagram_s4":   "📸 Instagram S4  ",
        "tiktok":         "🎵 TikTok        ",
    }

    lines = [f"📤 <b>Slot {slot} ({slot_time}) เสร็จแล้ว</b>", _DIV]
    for key, result in results.items():
        label = icons.get(key, f"   {key:<16}")
        if not result or str(result).startswith("ERROR"):
            lines.append(f"❌ {label}พัง")
        else:
            short = str(result)
            if "youtu.be" in short or "youtube" in short:
                lines.append(f"✅ {label}<a href='{short}'>ดูคลิป</a>")
            elif "instagram" in short:
                lines.append(f"✅ {label}<a href='{short}'>ดู Reel</a>")
            else:
                lines.append(f"✅ {label}สำเร็จ")

    # บอก slot ถัดไป
    next_slot = slot + 1 if slot is not None else None
    if next_slot is not None and next_slot < len(_SLOT_TIMES):
        lines.append(_DIV)
        lines.append(f"🔜 Slot {next_slot+1} จะโพสตอน {_SLOT_TIMES[next_slot]} น.")

    _send("\n".join(lines))


def notify_post_fail(slot: int, platform: str, error: str):
    _send(
        f"⚠️ <b>โพสไม่ได้! Slot {slot}</b>\n"
        f"{_DIV}\n"
        f"📱 {platform}\n"
        f"🔴 <code>{error[:180]}</code>\n"
        f"{_DIV}\n"
        f"🔄 ระบบ retry อัตโนมัติแล้ว\n"
        f"💬 ถ้ายังพัง ส่ง error มาให้ผมแก้"
    )


# ─── Credits / Health ─────────────────────────────────────────────────────────

def notify_credits_warning(service: str, remaining: int, days_left: float):
    urgent = days_left <= 1
    emoji  = "🚨" if urgent else "⚠️"
    action = (
        "อัพ plan ก่อน 05:50 พรุ่งนี้ มิฉะนั้น pipeline หยุด!"
        if urgent else
        f"อัพ plan ภายใน {days_left:.0f} วัน"
    )
    _send(
        f"{emoji} <b>{service} Credits แจ้งเตือน</b>\n"
        f"{_DIV}\n"
        f"💳 เหลือ: <b>{remaining:,} credits</b>\n"
        f"📅 คาดหมด: <b>{days_left:.1f} วัน</b>\n"
        f"{_DIV}\n"
        f"🔧 {action}"
    )


def notify_health_ok(stats: dict):
    lines = [
        f"🟢 <b>รายงานประจำวัน — ปกติทุกอย่าง</b>",
        _DIV,
        f"💾 Disk          {stats.get('disk','?')}",
        f"💳 ElevenLabs    {stats.get('elevenlabs','?')}",
        f"📋 Topics        {stats.get('topics','?')} หัวข้อ",
        f"🎬 Pexels        ✅",
        f"🤖 Anthropic     ✅",
        f"📘 Facebook      ✅",
        f"📸 Instagram     ✅",
        f"☁️ Cloudinary    ✅",
        f"▶️ YouTube       ✅",
        _DIV,
        f"⏰ {_now()}",
    ]
    _send("\n".join(lines))


def notify_topics_generated(topics: list):
    preview = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics[:5]))
    _send(
        f"📋 <b>Generate หัวข้อใหม่ 30 topic แล้ว!</b>\n"
        f"{_DIV}\n"
        f"{preview}\n"
        f"  ... และอีก {max(0, len(topics)-5)} หัวข้อ\n"
        f"{_DIV}\n"
        f"✅ ใช้ต่อได้ {len(topics)} วัน"
    )
