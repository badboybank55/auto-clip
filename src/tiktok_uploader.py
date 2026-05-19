"""
TikTok Content Posting API uploader
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
ต้องการ: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET ใน .env
"""

import json
import os
import time
from pathlib import Path

import requests
from loguru import logger

_TOKEN_PATH = Path("config/tiktok_token.json")
_AUTH_URL   = "https://open.tiktokapis.com/v2/oauth/token/"
_INIT_URL   = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_INFO_URL   = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"


class TikTokUploader:
    """
    อัปโหลดวิดีโอขึ้น TikTok ผ่าน Content Posting API

    Flow:
      1. OAuth2 (authorization_code หรือ refresh token)
      2. POST /video/init/ → upload_url + publish_id
      3. PUT video bytes → upload_url
      4. Poll /status/fetch/ จนสถานะ PUBLISH_COMPLETE
    """

    def __init__(self, client_key: str = "", client_secret: str = ""):
        self.client_key    = client_key    or os.getenv("TIKTOK_CLIENT_KEY", "")
        self.client_secret = client_secret or os.getenv("TIKTOK_CLIENT_SECRET", "")
        self._token_data: dict = self._load_token()

    # ─── Token management ────────────────────────────────────────────────────

    def _load_token(self) -> dict:
        if _TOKEN_PATH.exists():
            try:
                return json.loads(_TOKEN_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save_token(self, data: dict):
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _access_token(self) -> str:
        """คืน access_token ที่ยังใช้ได้ — auto-refresh ถ้าหมดอายุ"""
        td = self._token_data
        if not td.get("access_token"):
            raise RuntimeError(
                "TikTok: ไม่มี access_token — รัน 'python post.py --auth tiktok' ก่อน"
            )

        # refresh ถ้าใกล้หมดอายุ (< 5 นาที เหลือ)
        expires_at = td.get("expires_at", 0)
        if time.time() > expires_at - 300:
            logger.info("TikTok: refreshing access token...")
            r = requests.post(_AUTH_URL, data={
                "client_key":     self.client_key,
                "client_secret":  self.client_secret,
                "grant_type":     "refresh_token",
                "refresh_token":  td["refresh_token"],
            }, timeout=30)
            r.raise_for_status()
            new = r.json()
            new["expires_at"] = time.time() + new.get("expires_in", 86400)
            self._token_data = new
            self._save_token(new)
            logger.info("TikTok: token refreshed")

        return self._token_data["access_token"]

    def auth_from_code(self, code: str, redirect_uri: str):
        """แลก authorization_code เป็น access_token (ทำครั้งแรกครั้งเดียว)"""
        r = requests.post(_AUTH_URL, data={
            "client_key":    self.client_key,
            "client_secret": self.client_secret,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  redirect_uri,
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
        data["expires_at"] = time.time() + data.get("expires_in", 86400)
        self._token_data = data
        self._save_token(data)
        logger.success("TikTok: authenticated and token saved")

    # ─── Creator info ─────────────────────────────────────────────────────────

    def creator_info(self) -> dict:
        """ดึงข้อมูล creator — max video duration, privacy options ฯลฯ"""
        token = self._access_token()
        r = requests.post(_INFO_URL,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=UTF-8"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("data", {})

    # ─── Upload ──────────────────────────────────────────────────────────────

    def upload(
        self,
        video_path: str,
        caption: str,
        privacy: str = "PUBLIC_TO_EVERYONE",  # PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | SELF_ONLY
        disable_comment: bool = False,
        disable_duet:    bool = False,
        disable_stitch:  bool = False,
    ) -> str:
        """
        อัปโหลดวิดีโอขึ้น TikTok
        คืน publish_id (string) หรือ raise Exception ถ้าล้มเหลว
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"TikTok: ไม่พบไฟล์ {video_path}")

        token     = self._access_token()
        file_size = video_path.stat().st_size
        headers   = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json; charset=UTF-8",
        }

        # Step 1: init upload
        init_body = {
            "post_info": {
                "title":           caption[:2200],
                "privacy_level":   privacy,
                "disable_comment": disable_comment,
                "disable_duet":    disable_duet,
                "disable_stitch":  disable_stitch,
            },
            "source_info": {
                "source":     "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            },
        }
        r = requests.post(_INIT_URL, headers=headers,
                          json=init_body, timeout=30)
        r.raise_for_status()
        resp_data  = r.json().get("data", {})
        publish_id = resp_data.get("publish_id", "")
        upload_url = resp_data.get("upload_url", "")

        if not publish_id or not upload_url:
            raise RuntimeError(f"TikTok init failed: {r.text}")

        logger.info(f"TikTok: uploading {file_size/1024/1024:.1f}MB → publish_id={publish_id}")

        # Step 2: upload video bytes (single chunk)
        with open(video_path, "rb") as fh:
            put_r = requests.put(
                upload_url,
                data=fh,
                headers={
                    "Content-Type":  "video/mp4",
                    "Content-Range": f"bytes 0-{file_size-1}/{file_size}",
                    "Content-Length": str(file_size),
                },
                timeout=600,
            )
        put_r.raise_for_status()
        logger.info("TikTok: video bytes uploaded, waiting for processing...")

        # Step 3: poll status
        for attempt in range(30):
            time.sleep(10)
            status_r = requests.post(
                _STATUS_URL,
                headers=headers,
                json={"publish_id": publish_id},
                timeout=30,
            )
            status_r.raise_for_status()
            status_data = status_r.json().get("data", {})
            status      = status_data.get("status", "")
            logger.debug(f"TikTok status [{attempt+1}]: {status}")

            if status == "PUBLISH_COMPLETE":
                tiktok_url = f"https://www.tiktok.com/@me/video/{publish_id}"
                logger.success(f"TikTok → {tiktok_url}")
                return publish_id

            if status in ("FAILED", "PUBLISH_FAILED"):
                fail_reason = status_data.get("fail_reason", "unknown")
                raise RuntimeError(f"TikTok publish failed: {fail_reason}")

        raise TimeoutError("TikTok: หมดเวลารอ publish — ตรวจสอบ TikTok Studio")
