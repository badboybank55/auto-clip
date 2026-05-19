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


def _post_instagram(cfg: dict, video: Path, caps: dict,
                    fb_video_id: str = "") -> str:
    from src.uploader import FacebookUploader, InstagramUploader

    token   = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    user_id = os.getenv("INSTAGRAM_USER_ID", "")
    ig_caps = caps.get("instagram", {})

    if not token or not user_id:
        logger.warning("Instagram: INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID ไม่ได้ตั้งค่า → ข้าม")
        return ""

    # ถ้า cross_post_from_facebook: ดึง source URL จาก FB video แล้วใช้โพส IG
    video_url = os.getenv("INSTAGRAM_VIDEO_URL", "")
    if not video_url and fb_video_id:
        fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
        fb_page  = cfg["social_media"].get("facebook", {}).get("page_id", "me")
        try:
            fb = FacebookUploader(fb_token, fb_page)
            video_url = fb.get_video_source(fb_video_id)
            logger.info(f"Instagram: ใช้ Facebook CDN URL (video_id={fb_video_id})")
        except Exception as e:
            logger.warning(f"Instagram: ดึง FB source URL ไม่ได้ ({e}) → ข้าม")
            return ""

    if not video_url:
        logger.warning("Instagram: ไม่มี video_url → ข้าม")
        return ""

    ig = InstagramUploader(token, user_id)
    return ig.upload(
        video_path = str(video),
        caption    = ig_caps.get("caption", ""),
        video_url  = video_url,
    )


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


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-post คลิปขึ้นโซเชียล")
    parser.add_argument("output_dir", nargs="?", help="Output folder (default: latest)")
    parser.add_argument("--check",    action="store_true", help="ตรวจสอบ auth status")
    parser.add_argument("--auth",     choices=["youtube", "tiktok"], help="Auth platform")
    parser.add_argument("--code",     default="",  help="TikTok authorization_code")
    parser.add_argument("--redirect", default="",  help="TikTok redirect_uri")
    parser.add_argument("--dry-run",  action="store_true", help="แสดงแผนโดยไม่โพสจริง")
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

    # ── โพสแต่ละ platform ────────────────────────────────────────────────────
    results = {}

    if sm.get("youtube", {}).get("enabled"):
        logger.info("─ YouTube: กำลังอัปโหลด...")
        try:
            results["youtube"] = _post_youtube(cfg, video, thumb, caps)
        except Exception as e:
            logger.error(f"YouTube failed: {e}")
            results["youtube"] = f"ERROR: {e}"

    if sm.get("tiktok", {}).get("enabled"):
        logger.info("─ TikTok: กำลังอัปโหลด...")
        try:
            results["tiktok"] = _post_tiktok(cfg, video, caps)
        except Exception as e:
            logger.error(f"TikTok failed: {e}")
            results["tiktok"] = f"ERROR: {e}"

    if sm.get("facebook", {}).get("enabled"):
        logger.info("─ Facebook: กำลังอัปโหลด...")
        try:
            results["facebook"] = _post_facebook(cfg, video, caps, script_title)
        except Exception as e:
            logger.error(f"Facebook failed: {e}")
            results["facebook"] = f"ERROR: {e}"

    if sm.get("instagram", {}).get("enabled"):
        logger.info("─ Instagram: กำลังอัปโหลด...")
        # ถ้า cross_post_from_facebook ส่ง fb_video_id ไปด้วย
        fb_vid = ""
        if sm.get("instagram", {}).get("cross_post_from_facebook"):
            fb_vid = str(results.get("facebook", ""))
            if fb_vid.startswith("ERROR"):
                fb_vid = ""
        try:
            results["instagram"] = _post_instagram(cfg, video, caps, fb_vid)
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
