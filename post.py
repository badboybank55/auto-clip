#!/usr/bin/env python3
"""
post.py — Auto-post คลิปที่ generate แล้วขึ้น TikTok, YouTube, Facebook, Instagram

Usage:
  # โพสคลิปล่าสุด
  python post.py

  # โพสจาก output folder ที่ระบุ
  python post.py output/20260518_233556

  # ตรวจสอบ auth (ไม่โพส)
  python post.py --check

  # Auth TikTok (ทำครั้งแรก)
  python post.py --auth tiktok --code <auth_code> --redirect <redirect_uri>

  # Auth YouTube (ทำครั้งแรก)
  python post.py --auth youtube
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ROOT    = Path(__file__).parent
CONFIG  = ROOT / "config" / "settings.yaml"
OUTPUT  = ROOT / "output"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _latest_output() -> Path:
    """คืน output folder ล่าสุด (เรียงตามชื่อโฟลเดอร์)"""
    import re
    dirs = sorted(
        [d for d in OUTPUT.iterdir() if d.is_dir() and re.match(r'^\d{8}_\d{6}$', d.name)],
        reverse=True,
    )
    if not dirs:
        raise FileNotFoundError("ไม่พบ output folder — รัน main.py --auto ก่อน")
    return dirs[0]


def _latest_long_output() -> Path:
    """คืน output folder long-form ล่าสุด (_long suffix)"""
    import re
    dirs = sorted(
        [d for d in OUTPUT.iterdir() if d.is_dir() and re.match(r'^\d{8}_\d{6}_long$', d.name)],
        reverse=True,
    )
    if not dirs:
        raise FileNotFoundError("ไม่พบ long-form output — รัน main.py --long --auto ก่อน")
    return dirs[0]


def _load_captions(run_dir: Path) -> dict:
    """อ่าน caption files ทุก platform จาก captions/ folder"""
    cap_dir = run_dir / "captions"
    captions = {}

    for platform in ("youtube", "tiktok", "facebook", "instagram"):
        txt = cap_dir / f"{platform}.txt"
        if not txt.exists():
            continue

        content = txt.read_text(encoding="utf-8").strip()

        if platform == "youtube":
            # Format: TITLE: ...\n\nDESCRIPTION:\n...\n\nTAGS:\n...
            title, description, tags_str = "", "", ""
            for section in content.split("\n\n"):
                if section.startswith("TITLE:"):
                    title = section.replace("TITLE:", "").strip()
                elif section.startswith("DESCRIPTION:"):
                    description = section.replace("DESCRIPTION:", "").strip()
                elif section.startswith("TAGS:"):
                    tags_str = section.replace("TAGS:", "").strip()
            captions["youtube"] = {
                "title": title,
                "description": description,
                "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
            }
        else:
            # Format: caption text + hashtags (single block)
            captions[platform] = {"caption": content}

    return captions


def _find_video(run_dir: Path) -> Path:
    vids = list((run_dir / "videos").glob("*.mp4"))
    if not vids:
        raise FileNotFoundError(f"ไม่พบวิดีโอใน {run_dir}/videos/")
    return vids[0]


def _find_thumbnail(run_dir: Path) -> Path:
    t = run_dir / "thumbnail.jpg"
    return t if t.exists() else Path("")


def _log_result(run_dir: Path, results: dict):
    """บันทึกผลการโพสลง post_log.json"""
    log_path = run_dir / "post_log.json"
    existing = {}
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
        except Exception:
            pass
    existing.update({
        "posted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
    })
    log_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    logger.info(f"Post log → {log_path}")


# ─── Platform handlers ───────────────────────────────────────────────────────

def _post_youtube(cfg: dict, video: Path, thumb: Path, caps: dict) -> str:
    from src.uploader import YouTubeUploader

    yt_cfg  = cfg["social_media"]["youtube"]
    yt_caps = caps.get("youtube", {})
    secret  = ROOT / "config" / "client_secret.json"

    if not secret.exists():
        logger.warning("YouTube: config/client_secret.json ไม่พบ → ข้าม")
        return ""

    yt = YouTubeUploader(str(secret))
    return yt.upload(
        video_path     = str(video),
        title          = yt_caps.get("title", "")[:100],
        description    = yt_caps.get("description", ""),
        tags           = yt_caps.get("tags", [])[:15],
        category_id    = str(yt_cfg.get("category_id", "22")),
        privacy        = yt_cfg.get("privacy", "public"),
        thumbnail_path = str(thumb),
    )


def _post_tiktok(cfg: dict, video: Path, caps: dict) -> str:
    from src.tiktok_uploader import TikTokUploader

    tt_cfg  = cfg["social_media"]["tiktok"]
    tt_caps = caps.get("tiktok", {})
    caption = tt_caps.get("caption", "")

    tt = TikTokUploader()
    return tt.upload(
        video_path      = str(video),
        caption         = caption,
        privacy         = tt_cfg.get("privacy", "PUBLIC_TO_EVERYONE"),
        disable_comment = tt_cfg.get("disable_comment", False),
        disable_duet    = tt_cfg.get("disable_duet", False),
        disable_stitch  = tt_cfg.get("disable_stitch", False),
    )


def _post_facebook(cfg: dict, video: Path, caps: dict, script_title: str) -> str:
    from src.uploader import FacebookUploader

    fb_cfg  = cfg["social_media"]["facebook"]
    token   = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
    fb_caps = caps.get("facebook", {})

    if not token:
        logger.warning("Facebook: FACEBOOK_ACCESS_TOKEN ไม่ได้ตั้งค่า → ข้าม")
        return ""

    fb = FacebookUploader(token, fb_cfg.get("page_id", "me"))
    return fb.upload(
        video_path  = str(video),
        title       = script_title,
        description = fb_caps.get("caption", ""),
    )


def _upload_cloudinary(video: Path) -> tuple[str, str]:
    """อัพวิดีโอขึ้น Cloudinary คืน (public_url, public_id)"""
    import subprocess, tempfile
    import cloudinary
    import cloudinary.uploader
    cloudinary.config(
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key    = os.getenv("CLOUDINARY_API_KEY"),
        api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    )

    # Re-encode audio เป็น 48kHz (Instagram requirement)
    tmp = Path(tempfile.mktemp(suffix=".mp4"))
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video),
        "-c:v", "copy", "-c:a", "aac", "-ar", "48000",
        str(tmp)
    ], capture_output=True)
    upload_path = tmp if tmp.exists() else video

    try:
        result = cloudinary.uploader.upload(
            str(upload_path),
            resource_type = "video",
            folder        = "auto-clip",
            overwrite     = True,
        )
    finally:
        if tmp.exists():
            tmp.unlink()

    url = result["secure_url"]
    if not url.endswith(".mp4"):
        url += ".mp4"
    return url, result["public_id"]


def _delete_cloudinary(public_id: str):
    """ลบวิดีโอออกจาก Cloudinary หลังโพส"""
    import cloudinary.uploader
    cloudinary.uploader.destroy(public_id, resource_type="video")
    logger.info(f"Cloudinary: ลบแล้ว ({public_id})")


def _comment_instagram(media_id: str, text: str):
    """โพส comment บน IG post แล้ว caller ต้องปักหมุดเองในแอป"""
    import requests
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    if not token or not media_id:
        return
    resp = requests.post(
        f"https://graph.facebook.com/v21.0/{media_id}/comments",
        params={"access_token": token},
        data={"message": text},
        timeout=15,
    )
    if resp.ok:
        logger.success(f"IG comment posted (ปักหมุดในแอปด้วยนะครับ)")
    else:
        logger.warning(f"IG comment failed: {resp.text[:200]}")


def _update_latest_redirect(youtube_url: str):
    """
    อัพเดต ngerngork.netlify.app/video ให้ redirect ไปคลิปใหม่
    Instagram bio ชี้ไปที่ URL นี้ตลอด → auto-update ทุกครั้งที่โพส
    """
    import io, zipfile, requests as _req

    token   = os.getenv("NETLIFY_TOKEN", "")
    site_id = os.getenv("NETLIFY_SITE_ID", "e5974388-1907-495d-aaf3-bd77f6abc80c")
    if not token:
        logger.warning("NETLIFY_TOKEN ไม่ได้ตั้งค่า → ข้าม redirect update")
        return

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url={youtube_url}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>เงินงอก — คลิปล่าสุด</title>
<script>window.location.replace('{youtube_url}');</script>
</head>
<body style="font-family:sans-serif;text-align:center;padding:40px">
  <h2>เงินงอก 💰</h2>
  <p>กำลังพาคุณไปยังคลิปล่าสุด...</p>
  <a href="{youtube_url}">คลิกที่นี่ถ้าไม่ redirect อัตโนมัติ</a>
</body>
</html>"""

    # Pack HTML เป็น zip แล้ว deploy ผ่าน Netlify API
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", html)
    buf.seek(0)

    resp = _req.post(
        f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/zip"},
        data=buf.getvalue(),
        timeout=30,
    )
    if resp.ok:
        logger.success("Redirect updated → https://ngerngork.netlify.app")
    else:
        logger.warning(f"Netlify update failed: {resp.text[:200]}")


def _post_instagram(cfg: dict, video: Path, caps: dict,
                    fb_video_id: str = "") -> str:
    from src.uploader import InstagramUploader

    token   = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    user_id = os.getenv("INSTAGRAM_USER_ID", "")
    ig_caps = caps.get("instagram", {})

    if not token or not user_id:
        logger.warning("Instagram: INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID ไม่ได้ตั้งค่า → ข้าม")
        return ""

    # อัพวิดีโอขึ้น Cloudinary เพื่อได้ public URL
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    if not cloud_name:
        logger.warning("Instagram: ไม่มี CLOUDINARY_CLOUD_NAME → ข้าม")
        return ""

    logger.info("Instagram: อัพโหลดขึ้น Cloudinary...")
    try:
        video_url, public_id = _upload_cloudinary(video)
        logger.info(f"Instagram: Cloudinary URL พร้อม ({video_url[:60]}...)")
    except Exception as e:
        logger.error(f"Instagram: Cloudinary upload ล้มเหลว ({e}) → ข้าม")
        return ""

    ig = InstagramUploader(token, user_id)
    result = ig.upload(
        video_path = str(video),
        caption    = ig_caps.get("caption", ""),
        video_url  = video_url,
    )

    # ลบออกจาก Cloudinary ทันทีหลังโพส
    try:
        _delete_cloudinary(public_id)
    except Exception as e:
        logger.warning(f"Instagram: Cloudinary ลบไม่ได้ ({e})")

    return result


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def _auth_tiktok(code: str, redirect_uri: str):
    from src.tiktok_uploader import TikTokUploader
    tt = TikTokUploader()
    tt.auth_from_code(code, redirect_uri)


def _auth_youtube():
    """ทริก OAuth flow สำหรับ YouTube (เปิด browser)"""
    from src.uploader import YouTubeUploader
    yt = YouTubeUploader(str(ROOT / "config" / "client_secret.json"))
    _ = yt.service  # triggers auth flow
    logger.success("YouTube: auth เสร็จ token บันทึกที่ config/youtube_token.pickle")


def _check_auth(cfg: dict):
    """แสดงสถานะ auth ของทุก platform"""
    sm = cfg.get("social_media", {})
    print("\n─── Auth Status ──────────────────────────")

    # YouTube
    yt_ok = (ROOT / "config" / "client_secret.json").exists() and \
            (ROOT / "config" / "youtube_token.pickle").exists()
    print(f"  YouTube  : {'✅ พร้อม' if yt_ok else '❌ ยังไม่ auth — รัน: python post.py --auth youtube'}")
    print(f"             enabled={sm.get('youtube',{}).get('enabled', False)}")

    # TikTok
    tt_ok = (ROOT / "config" / "tiktok_token.json").exists() and \
            bool(os.getenv("TIKTOK_CLIENT_KEY"))
    print(f"  TikTok   : {'✅ พร้อม' if tt_ok else '❌ ยังไม่ auth — ดู README สำหรับ TikTok OAuth'}")
    print(f"             enabled={sm.get('tiktok',{}).get('enabled', False)}")

    # Facebook
    fb_ok = bool(os.getenv("FACEBOOK_ACCESS_TOKEN"))
    print(f"  Facebook : {'✅ token มีแล้ว' if fb_ok else '❌ FACEBOOK_ACCESS_TOKEN ยังไม่ได้ตั้งค่า'}")
    print(f"             enabled={sm.get('facebook',{}).get('enabled', False)}")

    # Instagram
    ig_ok = bool(os.getenv("INSTAGRAM_ACCESS_TOKEN")) and bool(os.getenv("INSTAGRAM_USER_ID"))
    print(f"  Instagram: {'✅ token มีแล้ว' if ig_ok else '❌ INSTAGRAM_ACCESS_TOKEN / USER_ID ยังไม่ได้ตั้งค่า'}")
    print(f"             enabled={sm.get('instagram',{}).get('enabled', False)}")
    print("──────────────────────────────────────────\n")


# ─── Morning health check ────────────────────────────────────────────────────

def _morning_health_check():
    """เช็คทุกอย่างทุกเช้า slot 0 — แจ้ง Telegram ถ้าพบปัญหา"""
    import shutil, requests as _req
    from src.notifier import notify_credits_warning, _send

    warnings = []

    # 1. Disk space (เตือนถ้าเหลือ < 20GB)
    free_gb = shutil.disk_usage("/").free / 1e9
    if free_gb < 20:
        warnings.append(
            f"💾 Disk เหลือแค่ {free_gb:.1f}GB!\n"
            f"   → รัน: find ~/auto-clip/output -mtime +1 -exec rm -rf {{}} +\n"
            f"   → หรือเปิด Finder ลบไฟล์ใหญ่ๆ ที่ไม่ใช้"
        )

    # 2. ElevenLabs credits
    try:
        el_key = os.getenv("ELEVENLABS_API_KEY", "")
        if el_key:
            r = _req.get("https://api.elevenlabs.io/v1/user/subscription",
                         headers={"xi-api-key": el_key}, timeout=10)
            if r.ok:
                sub       = r.json()
                remaining = sub.get("character_limit", 0) - sub.get("character_count", 0)
                days_left = remaining / 13000
                if days_left <= 1:
                    _send(
                        f"🚨 <b>ElevenLabs จะหมดพรุ่งนี้!</b>\n"
                        f"⚡ เหลือ {remaining:,} credits (~{days_left:.1f} วัน)\n"
                        f"⏰ อัพ plan ก่อน 05:50 พรุ่งนี้ มิฉะนั้น pipeline หยุด"
                    )
                elif days_left <= 3:
                    notify_credits_warning("ElevenLabs", remaining, days_left)
    except Exception:
        pass

    # 3. Topic queue
    try:
        import yaml
        cfg = yaml.safe_load(Path("config/settings.yaml").read_text())
        from src.topic_manager import TopicManager
        tm = TopicManager()
        st = tm.status()
        pending = st.get("pending", 0)
        if pending <= 5:
            warnings.append(
                    f"📋 Topic queue เหลือแค่ {pending} หัวข้อ\n"
                    f"   → ระบบจะ generate 30 หัวข้อใหม่อัตโนมัติตอน pipeline รัน\n"
                    f"   → ไม่ต้องทำอะไร แต่ถ้า pipeline รันแล้วยังไม่แจ้ง ให้บอกผม"
                )
    except Exception:
        pass

    # 4. Pexels — ดู response header จาก search ทดสอบ
    try:
        pexels_key = os.getenv("PEXELS_API_KEY", "")
        if pexels_key:
            r = _req.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": pexels_key},
                         params={"query": "money", "per_page": 1}, timeout=10)
            if r.status_code == 429:
                warnings.append("🎬 Pexels API เกิน quota เดือนนี้! คลิปจะใช้ cache เก่า")
            elif r.ok:
                remaining_req = r.headers.get("X-Ratelimit-Remaining", "")
                if remaining_req and int(remaining_req) < 500:
                    warnings.append(f"🎬 Pexels เหลือ quota {remaining_req} requests")
    except Exception:
        pass

    # 5. Facebook unauthorized post check
    try:
        from datetime import datetime, timezone, timedelta
        fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
        page_id  = "118604523332820"
        if fb_token:
            since = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
            r = _req.get(
                f"https://graph.facebook.com/v21.0/{page_id}/videos",
                params={"access_token": fb_token,
                        "fields": "id,created_time",
                        "since": since, "limit": 20},
                timeout=10,
            )
            if r.ok:
                fb_posts = r.json().get("data", [])
                fb_ids   = {v["id"] for v in fb_posts}

                # เทียบกับ post_log ของเรา
                our_ids = set()
                for out_dir in sorted(ROOT.glob("output/*"), reverse=True)[:7]:
                    log = out_dir / "post_log.json"
                    if log.exists():
                        try:
                            data = json.loads(log.read_text())
                            for v in data.get("results", {}).values():
                                our_ids.add(str(v))
                        except Exception:
                            pass

                unknown = fb_ids - our_ids
                # กรอง ID ที่อาจเป็นของเราแต่ format ต่างกัน
                unknown = {u for u in unknown if len(u) > 5}
                if unknown:
                    warnings.append(
                        f"🚨 พบโพส FB ที่ไม่ได้สั่ง! ({len(unknown)} รายการ)\n"
                        f"   → อาจ token หลุด!\n"
                        f"   → ตรวจสอบหน้าเพจด่วน แล้วบอกผมให้ revoke token"
                    )
    except Exception:
        pass

    # 6. Anthropic API + credit balance
    try:
        anth_key = os.getenv("ANTHROPIC_API_KEY", "")
        if anth_key:
            r = _req.get("https://api.anthropic.com/v1/models",
                         headers={"x-api-key": anth_key,
                                  "anthropic-version": "2023-06-01"}, timeout=10)
            if r.status_code == 401:
                warnings.append(
                    "🤖 Anthropic API key ไม่ถูกต้อง!\n"
                    "   → Script generation จะพัง pipeline หยุด\n"
                    "   → เช็ค ANTHROPIC_API_KEY ใน .env แล้วบอกผม"
                )
            elif not r.ok:
                warnings.append(
                    f"🤖 Anthropic API มีปัญหา (HTTP {r.status_code})\n"
                    f"   → อาจ rate limit ชั่วคราว รอ 1 ชั่วโมงแล้วลองใหม่"
                )

    # Anthropic credit balance (ถ้าใกล้หมด)
    try:
        import requests as _req2
        anth_key = os.getenv("ANTHROPIC_API_KEY", "")
        if anth_key:
            r = _req2.get(
                "https://api.anthropic.com/v1/organizations/billing/credit_grants",
                headers={"x-api-key": anth_key,
                         "anthropic-version": "2023-06-01"}, timeout=10
            )
            if r.ok:
                grants = r.json().get("data", [])
                total_remaining = sum(
                    g.get("remaining_amount", 0) for g in grants
                    if g.get("status") == "active"
                )
                if 0 < total_remaining < 5:   # เหลือไม่ถึง $5
                    warnings.append(
                        f"🤖 Anthropic credits เหลือแค่ ${total_remaining:.2f}!\n"
                        f"   → เติมเงินที่ console.anthropic.com\n"
                        f"   → มิฉะนั้น pipeline และ bot จะหยุดทำงาน"
                    )
    except Exception:
        pass

    # 6. Facebook token
    try:
        fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
        if fb_token:
            r = _req.get("https://graph.facebook.com/v21.0/me",
                         params={"access_token": fb_token}, timeout=10)
            if not r.ok or "error" in r.json():
                warnings.append(
                    "📘 Facebook token มีปัญหา!\n"
                    "   → FB Reels โพสไม่ได้\n"
                    "   → แจ้งผม จะ refresh token ให้"
                )
    except Exception:
        pass

    # 7. Instagram token
    try:
        ig_token  = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
        ig_uid    = os.getenv("INSTAGRAM_USER_ID", "")
        if ig_token and ig_uid:
            r = _req.get(f"https://graph.facebook.com/v21.0/{ig_uid}",
                         params={"access_token": ig_token,
                                 "fields": "id"}, timeout=10)
            if not r.ok or "error" in r.json():
                warnings.append(
                    "📸 Instagram token มีปัญหา!\n"
                    "   → IG Reels โพสไม่ได้\n"
                    "   → แจ้งผม จะ refresh token ให้"
                )
    except Exception:
        pass

    # 8. Cloudinary
    try:
        import cloudinary, cloudinary.api
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        )
        usage = cloudinary.api.usage()
        bw_used_gb  = usage.get("bandwidth", {}).get("used_percent", 0)
        if bw_used_gb >= 80:
            warnings.append(
                f"☁️ Cloudinary ใช้ bandwidth ไป {bw_used_gb:.0f}%\n"
                f"   → IG จะโพสไม่ได้ถ้าเกิน 100%\n"
                f"   → reset ต้นเดือนหน้าอัตโนมัติ หรืออัพ plan ที่ cloudinary.com"
            )
    except Exception:
        pass

    # 9. YouTube quota (ประมาณจาก log วันนี้)
    try:
        log_path = Path("logs/post.log")
        if log_path.exists():
            today = __import__("datetime").date.today().strftime("%Y-%m-%d")
            today_lines = [l for l in log_path.read_text().splitlines() if today in l]
            yt_errors = sum(1 for l in today_lines if "quota" in l.lower() or "403" in l)
            if yt_errors >= 2:
                warnings.append(
                    "▶️ YouTube API เกิน quota วันนี้!\n"
                    "   → YouTube Shorts โพสไม่ได้วันนี้\n"
                    "   → reset อัตโนมัติตี 2 คืนนี้ พรุ่งนี้ปกติเอง"
                )
    except Exception:
        pass

    if warnings:
        div = "─" * 22
        body = f"\n{div}\n".join(warnings)
        _send(f"⚠️ <b>รายงานประจำวัน — พบปัญหา</b>\n{div}\n{body}")
    else:
        from src.notifier import notify_health_ok
        notify_health_ok({
            "disk":       f"{free_gb:.1f} GB ว่าง",
            "elevenlabs": f"{remaining:,} credits" if 'remaining' in dir() else "OK",
            "topics":     str(pending) if 'pending' in dir() else "OK",
        })


# ─── Long-form poster ────────────────────────────────────────────────────────

# โปสตารางเวลา (เวลาไทย)
_SLOT_TIMES = ["08:00", "11:30", "16:30", "19:00"]


def _load_long_caps(run_dir: Path) -> dict:
    """อ่าน YouTube long captions"""
    caps = {}
    yt_txt = run_dir / "long" / "captions" / "youtube.txt"
    if not yt_txt.exists():
        return caps
    content = yt_txt.read_text(encoding="utf-8")
    title, desc, tags_str = "", "", ""
    for section in content.split("\n\n"):
        if section.startswith("TITLE:"):
            title = section.replace("TITLE:", "").strip()
        elif section.startswith("DESCRIPTION:"):
            desc = section.replace("DESCRIPTION:", "").strip()
        elif section.startswith("TAGS:"):
            tags_str = section.replace("TAGS:", "").strip()
    return {
        "title": title,
        "description": desc,
        "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
    }


def _load_section_caps(short_dir: Path) -> tuple[dict, dict]:
    """อ่าน captions ของ section นั้น → (teaser_caps, fb_caps)"""
    teaser_caps = {}
    for platform in ("tiktok", "instagram", "youtube"):
        txt = short_dir / "captions" / "teaser" / f"{platform}.txt"
        if txt.exists():
            teaser_caps[platform] = {"caption": txt.read_text(encoding="utf-8").strip()}
    fb_caps = {}
    fb_txt = short_dir / "captions" / "fb" / "facebook.txt"
    if fb_txt.exists():
        fb_caps["facebook"] = {"caption": fb_txt.read_text(encoding="utf-8").strip()}
    return teaser_caps, fb_caps


def _post_section(
    idx: int, short_dir: Path, long_url: str,
    long_yt_caps: dict, cfg: dict,
    results: dict, prev: dict,
):
    """โพส teaser (YT Shorts + IG) + fb_complete (FB) สำหรับ 1 section"""
    sm  = cfg.get("social_media", {})
    key = f"s{idx + 1}"   # s1 / s2 / s3 / s4

    def _already(p):
        r = prev.get(p, "")
        return r and not str(r).startswith("ERROR")

    teaser_caps, fb_caps = _load_section_caps(short_dir)
    # YouTube Shorts ใช้ teaser_yt.mp4 (CTA: ลิงก์ใน description)
    # Instagram ใช้ teaser_ig.mp4 (CTA: ลิงก์ใน bio)
    # fallback: teaser.mp4 สำหรับ output เก่า
    teaser_yt = short_dir / "teaser_yt.mp4"
    teaser_ig = short_dir / "teaser_ig.mp4"
    teaser    = short_dir / "teaser.mp4"  # legacy fallback
    fb_vid    = short_dir / "fb_complete.mp4"

    yt_video = teaser_yt if teaser_yt.exists() else teaser
    ig_video = teaser_ig if teaser_ig.exists() else teaser

    logger.info(f"── Section {idx+1} ({short_dir.name}) ──────────────────")

    # YouTube Shorts — ใช้ teaser_yt.mp4 (CTA: ลิงก์ใน description)
    if sm.get("youtube", {}).get("enabled") and yt_video.exists():
        k = f"youtube_shorts_{key}"
        if _already(k):
            logger.info(f"  YT Shorts {key}: ข้าม")
        else:
            short_title = (long_yt_caps.get("title", "")[:85] +
                           f" ตอนที่ {idx+1} #shorts")
            short_desc = (
                f"{long_yt_caps.get('title', '')}\n\n"
                f"ดูคลิปเต็มได้ที่ 👇\n{long_url}\n\n"
                f"#shorts #เงินงอก #การเงิน #NgernNgork"
            )
            caps = {"youtube": {
                "title": short_title,
                "description": short_desc,
                "tags": long_yt_caps.get("tags", [])[:10] + ["shorts"],
            }}
            try:
                results[k] = _post_youtube(cfg, yt_video, Path("/dev/null"), caps)
                logger.success(f"  YT Shorts {key} ✅ {results[k]}")
            except Exception as e:
                logger.error(f"  YT Shorts {key}: {e}")
                results[k] = f"ERROR: {e}"

    # Instagram — ใช้ teaser_ig.mp4 (CTA: ลิงก์ใน bio)
    if sm.get("instagram", {}).get("enabled") and ig_video.exists():
        k = f"instagram_{key}"
        if _already(k):
            logger.info(f"  Instagram {key}: ข้าม")
        else:
            try:
                ig_result = _post_instagram(cfg, ig_video, teaser_caps)
                results[k] = ig_result if ig_result else "ERROR: empty"
                logger.success(f"  Instagram {key} ✅ {results[k]}")
                # auto-comment ลิงก์คลิปยาว
                if long_url and "instagram.com" in str(ig_result):
                    import requests as _req
                    _token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
                    _uid   = os.getenv("INSTAGRAM_USER_ID", "")
                    _r = _req.get(
                        f"https://graph.facebook.com/v21.0/{_uid}/media",
                        params={"fields": "id", "limit": 1, "access_token": _token},
                        timeout=10,
                    )
                    if _r.ok:
                        items = _r.json().get("data", [])
                        if items:
                            _comment_instagram(
                                items[0]["id"],
                                f"🎬 ดูคลิปเต็มได้ที่ลิงก์นี้เลยครับ 👇\n{long_url}",
                            )
            except Exception as e:
                logger.error(f"  Instagram {key}: {e}")
                results[k] = f"ERROR: {e}"

    # Facebook Reels
    if sm.get("facebook", {}).get("enabled") and fb_vid.exists():
        k = f"facebook_{key}"
        if _already(k):
            logger.info(f"  Facebook {key}: ข้าม")
        else:
            title = long_yt_caps.get("title", "")
            try:
                results[k] = _post_facebook(cfg, fb_vid, fb_caps, title)
                logger.success(f"  Facebook {key} ✅ {results[k]}")
            except Exception as e:
                logger.error(f"  Facebook {key}: {e}")
                results[k] = f"ERROR: {e}"


def _post_long_form(cfg: dict, args):
    """
    โพส long-form output ตาม --slot:
      slot 0 (08:00): YouTube Long + Section 1 (YT Short + IG + FB)
      slot 1 (11:30): Section 2
      slot 2 (16:30): Section 3
      slot 3 (19:00): Section 4
      slot ไม่ระบุ  : ทั้งหมด (manual run)
    """
    slot = getattr(args, "slot", None)
    if slot is not None:
        slot = int(slot)

    run_dir = Path(args.output_dir) if args.output_dir else _latest_long_output()
    if not run_dir.exists():
        logger.error(f"ไม่พบ folder: {run_dir}")
        return

    slot_label = f"slot {slot} ({_SLOT_TIMES[slot]})" if slot is not None else "all"
    logger.info(f"Long-form post: {run_dir.name} | {slot_label}")

    sm         = cfg.get("social_media", {})
    long_video = run_dir / "long" / "videos" / "long.mp4"
    long_thumb = run_dir / "long" / "thumbnail.jpg"
    long_yt_caps = _load_long_caps(run_dir)

    shorts_dir = run_dir / "shorts"
    short_dirs = sorted([d for d in shorts_dir.iterdir() if d.is_dir()]) \
                 if shorts_dir.exists() else []

    # Determine what to post
    post_long      = (slot is None or slot == 0)
    if slot is None:
        section_idxs = list(range(len(short_dirs)))
    else:
        section_idxs = [slot] if slot < len(short_dirs) else []

    # ── post_log ──────────────────────────────────────────────────────────────
    log_path = run_dir / "post_log.json"
    prev = {}
    if log_path.exists():
        try:
            prev = json.loads(log_path.read_text()).get("results", {})
        except Exception:
            pass
    results = dict(prev)

    def _already(p):
        r = prev.get(p, "")
        return r and not str(r).startswith("ERROR")

    # ── YouTube Long (slot 0 only) ────────────────────────────────────────────
    if post_long and sm.get("youtube", {}).get("enabled") and long_video.exists():
        if _already("youtube"):
            logger.info(f"─ YouTube Long: ข้าม (โพสแล้ว → {prev['youtube']})")
        else:
            logger.info(f"─ YouTube Long: อัปโหลด ({long_video.stat().st_size/1024/1024:.0f}MB)…")
            try:
                results["youtube"] = _post_youtube(cfg, long_video, long_thumb,
                                                    {"youtube": long_yt_caps})
                logger.success(f"YouTube ✅ {results['youtube']}")
                if results["youtube"] and not str(results["youtube"]).startswith("ERROR"):
                    _update_latest_redirect(results["youtube"])
            except Exception as e:
                logger.error(f"YouTube: {e}")
                results["youtube"] = f"ERROR: {e}"

    long_url = results.get("youtube", "")

    # ── Sections ──────────────────────────────────────────────────────────────
    for idx in section_idxs:
        if idx >= len(short_dirs):
            logger.warning(f"Section {idx+1} ไม่พบ → ข้าม")
            continue
        _post_section(idx, short_dirs[idx], long_url, long_yt_caps,
                      cfg, results, prev)
        _log_result(run_dir, results)   # บันทึกทุก section

    # ── TikTok (section 1 เท่านั้น ถ้ายังไม่ได้โพส) ──────────────────────────
    if (slot is None or slot == 0) and short_dirs and sm.get("tiktok", {}).get("enabled"):
        teaser = short_dirs[0] / "teaser.mp4"
        if _already("tiktok"):
            logger.info("─ TikTok: ข้าม (โพสแล้ว)")
        elif teaser.exists():
            teaser_caps, _ = _load_section_caps(short_dirs[0])
            logger.info(f"─ TikTok: อัปโหลด teaser…")
            try:
                results["tiktok"] = _post_tiktok(cfg, teaser, teaser_caps)
                logger.success(f"TikTok ✅ {results['tiktok']}")
            except Exception as e:
                logger.error(f"TikTok: {e}")
                results["tiktok"] = f"ERROR: {e}"

    _log_result(run_dir, results)
    print(f"\n─── ผลการโพส slot={slot_label} ──────────────────")
    for platform, result in results.items():
        icon = "✅" if not str(result).startswith("ERROR") else "❌"
        print(f"  {icon} {platform:14}: {result}")
    print("────────────────────────────────────────────\n")

    # แจ้ง Telegram
    from src.notifier import notify_post_done, notify_credits_warning
    slot_time = _SLOT_TIMES[slot] if slot is not None and slot < len(_SLOT_TIMES) else "all"
    notify_post_done(slot if slot is not None else -1, str(slot_time), results)

    # ── เช็คสุขภาพระบบ (เฉพาะ slot 0 ทุกเช้า) ───────────────────────────────
    if slot == 0 or slot is None:
        _morning_health_check()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-post คลิปขึ้นโซเชียล")
    parser.add_argument("output_dir", nargs="?", help="Output folder (default: latest)")
    parser.add_argument("--check",    action="store_true", help="ตรวจสอบ auth status")
    parser.add_argument("--auth",     choices=["youtube", "tiktok"], help="Auth platform")
    parser.add_argument("--code",     default="",  help="TikTok authorization_code")
    parser.add_argument("--redirect", default="",  help="TikTok redirect_uri")
    parser.add_argument("--dry-run",  action="store_true", help="แสดงแผนโดยไม่โพสจริง")
    parser.add_argument("--long",     action="store_true", help="โพสจาก long-form output folder")
    parser.add_argument("--slot",     type=int, choices=[0,1,2,3],
                        help="โพสเฉพาะ slot (0=08:00 1=11:30 2=16:30 3=19:00)")
    args = parser.parse_args()

    cfg = _load_config()

    # ── Auth mode ────────────────────────────────────────────────────────────
    if args.auth == "tiktok":
        if not args.code or not args.redirect:
            print("ต้องระบุ --code และ --redirect สำหรับ TikTok auth")
            print("ขั้นตอน TikTok OAuth:")
            print("  1. เปิด TikTok Developer Console")
            print("  2. ไป Apps → เลือก app → Manage → Authorization")
            print("  3. ใช้ URL: https://www.tiktok.com/v2/auth/authorize/")
            print("     ?client_key=YOUR_KEY&scope=video.publish&response_type=code")
            print("     &redirect_uri=YOUR_REDIRECT")
            print("  4. Login และ copy code จาก redirect URL")
            print("  5. รัน: python post.py --auth tiktok --code CODE --redirect URI")
            sys.exit(1)
        _auth_tiktok(args.code, args.redirect)
        return

    if args.auth == "youtube":
        _auth_youtube()
        return

    # ── Check mode ───────────────────────────────────────────────────────────
    if args.check:
        _check_auth(cfg)
        return

    # ── Post mode ────────────────────────────────────────────────────────────
    if args.long:
        _post_long_form(cfg, args)
        return

    run_dir = Path(args.output_dir) if args.output_dir else _latest_output()
    if not run_dir.exists():
        logger.error(f"ไม่พบ folder: {run_dir}")
        sys.exit(1)

    video = _find_video(run_dir)
    thumb = _find_thumbnail(run_dir)
    caps  = _load_captions(run_dir)
    sm    = cfg.get("social_media", {})

    # อ่าน title จาก script.txt
    script_txt = run_dir / "scripts" / "script.txt"
    script_title = ""
    if script_txt.exists():
        first_line = script_txt.read_text(encoding="utf-8").splitlines()[0]
        script_title = first_line.replace("TITLE:", "").strip()

    logger.info(f"Post target: {run_dir.name}")
    logger.info(f"Video: {video.name} ({video.stat().st_size/1024/1024:.1f}MB)")
    logger.info(f"Title: {script_title}")

    if args.dry_run:
        print("\n─── Dry Run ──────────────────────────────")
        for p in ("youtube", "tiktok", "facebook", "instagram"):
            enabled = sm.get(p, {}).get("enabled", False)
            cap_preview = str(caps.get(p, {}))[:80]
            print(f"  {p:10}: {'✅ จะโพส' if enabled else '⏭  disabled'} | {cap_preview}")
        print("──────────────────────────────────────────\n")
        return

    # ── โหลด post_log เดิม (ป้องกันโพสซ้ำ) ──────────────────────────────────
    log_path = run_dir / "post_log.json"
    prev = {}
    if log_path.exists():
        try:
            prev = json.loads(log_path.read_text()).get("results", {})
        except Exception:
            pass

    # ── โพสแต่ละ platform ────────────────────────────────────────────────────
    results = dict(prev)

    def _already_posted(platform):
        r = prev.get(platform, "")
        return r and not str(r).startswith("ERROR")

    if sm.get("youtube", {}).get("enabled"):
        if _already_posted("youtube"):
            logger.info(f"─ YouTube: ข้าม (โพสแล้ว → {prev['youtube']})")
        else:
            logger.info("─ YouTube: กำลังอัปโหลด...")
            try:
                results["youtube"] = _post_youtube(cfg, video, thumb, caps)
            except Exception as e:
                logger.error(f"YouTube failed: {e}")
                results["youtube"] = f"ERROR: {e}"

    if sm.get("tiktok", {}).get("enabled"):
        if _already_posted("tiktok"):
            logger.info(f"─ TikTok: ข้าม (โพสแล้ว)")
        else:
            logger.info("─ TikTok: กำลังอัปโหลด...")
            try:
                results["tiktok"] = _post_tiktok(cfg, video, caps)
            except Exception as e:
                logger.error(f"TikTok failed: {e}")
                results["tiktok"] = f"ERROR: {e}"

    if sm.get("facebook", {}).get("enabled"):
        if _already_posted("facebook"):
            logger.info(f"─ Facebook: ข้าม (โพสแล้ว)")
        else:
            logger.info("─ Facebook: กำลังอัปโหลด...")
            try:
                results["facebook"] = _post_facebook(cfg, video, caps, script_title)
            except Exception as e:
                logger.error(f"Facebook failed: {e}")
                results["facebook"] = f"ERROR: {e}"

    if sm.get("instagram", {}).get("enabled"):
        if _already_posted("instagram"):
            logger.info(f"─ Instagram: ข้าม (โพสแล้ว → {prev['instagram']})")
        else:
            logger.info("─ Instagram: กำลังอัปโหลด...")
            fb_vid = ""
            if sm.get("instagram", {}).get("cross_post_from_facebook"):
                fb_vid = str(results.get("facebook", ""))
                if fb_vid.startswith("ERROR"):
                    fb_vid = ""
            try:
                ig_result = _post_instagram(cfg, video, caps, fb_vid)
                results["instagram"] = ig_result if ig_result else "ERROR: post returned empty"
            except Exception as e:
                logger.error(f"Instagram failed: {e}")
                results["instagram"] = f"ERROR: {e}"

    if not results:
        logger.warning("ไม่มี platform ที่ enabled — แก้ config/settings.yaml แล้วลองใหม่")
        logger.info("ใช้ --check เพื่อดูสถานะ auth")
    else:
        _log_result(run_dir, results)
        print("\n─── ผลการโพส ─────────────────────────────")
        for platform, result in results.items():
            icon = "✅" if not str(result).startswith("ERROR") else "❌"
            print(f"  {icon} {platform:10}: {result}")
        print("──────────────────────────────────────────\n")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
