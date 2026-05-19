import os
import pickle
import time
from pathlib import Path

import requests
from loguru import logger


# ─── YouTube ─────────────────────────────────────────────────────────────────

class YouTubeUploader:
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN_PATH = "config/youtube_token.pickle"

    def __init__(self, client_secret_path: str):
        self.client_secret_path = client_secret_path
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        if Path(self.TOKEN_PATH).exists():
            with open(self.TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self.TOKEN_PATH, "wb") as f:
                pickle.dump(creds, f)

        logger.info("YouTube: authenticated")
        return build("youtube", "v3", credentials=creds)

    def upload(self, video_path: str, title: str, description: str,
               tags: list, category_id: str = "22", privacy: str = "public",
               thumbnail_path: str = "") -> str:
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags[:15],
                "categoryId": category_id,
                "defaultLanguage": "th",
            },
            "status": {"privacyStatus": privacy},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        req = self.service.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = req.next_chunk()

        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        logger.success(f"YouTube → {url}")

        # อัปโหลด thumbnail ถ้ามี
        if thumbnail_path and Path(thumbnail_path).exists():
            try:
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                self.service.thumbnails().set(
                    videoId=video_id, media_body=thumb_media
                ).execute()
                logger.info("YouTube: thumbnail uploaded")
            except Exception as e:
                logger.warning(f"YouTube thumbnail failed: {e}")

        return url


# ─── Facebook ────────────────────────────────────────────────────────────────

class FacebookUploader:
    """Facebook Reels upload via 3-phase API"""
    API_VERSION = "v21.0"
    GRAPH_URL   = "https://graph.facebook.com"

    def __init__(self, access_token: str, page_id: str = "me"):
        self.token   = access_token
        self.page_id = page_id or "me"

    def upload(self, video_path: str, title: str, description: str,
               cross_post_instagram: bool = False) -> str:
        video_path = Path(video_path)
        file_size  = video_path.stat().st_size
        reels_url  = f"{self.GRAPH_URL}/{self.API_VERSION}/{self.page_id}/video_reels"

        # Phase 1: start — get upload_url + video_id
        r = requests.post(reels_url,
            params={"upload_phase": "start", "access_token": self.token},
            timeout=30)
        r.raise_for_status()
        data       = r.json()
        video_id   = data.get("video_id", "")
        upload_url = data.get("upload_url", "")
        if not video_id or not upload_url:
            raise RuntimeError(f"Facebook Reels init failed: {r.text}")

        logger.info(f"Facebook: uploading {file_size/1024/1024:.1f}MB → video_id={video_id}")

        # Phase 2: transfer — binary upload
        with open(video_path, "rb") as fh:
            put_r = requests.post(
                upload_url,
                data=fh,
                headers={
                    "Authorization": f"OAuth {self.token}",
                    "Content-Type":  "video/mp4",
                    "offset":        "0",
                    "file_size":     str(file_size),
                },
                timeout=600,
            )
        put_r.raise_for_status()
        logger.info("Facebook: transfer done, publishing...")

        # Phase 3: finish + publish
        finish_params = {
            "upload_phase":  "finish",
            "video_state":   "PUBLISHED",
            "video_id":      video_id,
            "title":         title[:255],
            "description":   description,
            "access_token":  self.token,
        }
        fin_r = requests.post(reels_url, params=finish_params, timeout=60)
        fin_r.raise_for_status()

        logger.success(f"Facebook Reels → video_id={video_id}")
        return video_id

    def get_video_source(self, video_id: str) -> str:
        """ดึง CDN URL ของ video (ใช้ cross-post ไป Instagram)"""
        r = requests.get(
            f"{self.GRAPH_URL}/{self.API_VERSION}/{video_id}",
            params={"fields": "source", "access_token": self.token},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("source", "")


# ─── Instagram ────────────────────────────────────────────────────────────────

class InstagramUploader:
    """Instagram Graph API — Reels upload (ต้องการ Business/Creator account)"""
    GRAPH_URL = f"https://graph.facebook.com/v21.0"

    def __init__(self, access_token: str, user_id: str):
        self.token   = access_token
        self.user_id = user_id

    def upload(self, video_path: str, caption: str,
               video_url: str = "") -> str:
        """
        Upload Reels ผ่าน Instagram Graph API
        video_url: URL สาธารณะ (จาก Facebook CDN หรือ hosting อื่น)
        """
        if not video_url:
            logger.warning("Instagram: ไม่มี video_url — ข้าม (ใช้ cross_post_from_facebook แทน)")
            return ""

        # Step 1: Create media container
        r = requests.post(
            f"{self.GRAPH_URL}/{self.user_id}/media",
            data={
                "media_type":    "REELS",
                "video_url":     video_url,
                "caption":       caption[:2200],
                "share_to_feed": "true",
                "access_token":  self.token,
            }, timeout=60,
        )
        r.raise_for_status()
        container_id = r.json().get("id", "")
        if not container_id:
            logger.error("Instagram: ไม่ได้ container_id")
            return ""

        # Step 2: รอให้ video processing เสร็จ (สูงสุด 5 นาที)
        for _ in range(30):
            time.sleep(10)
            status_r = requests.get(
                f"{self.GRAPH_URL}/{container_id}",
                params={"fields": "status_code", "access_token": self.token},
                timeout=30,
            )
            status = status_r.json().get("status_code", "")
            if status == "FINISHED":
                break
            if status == "ERROR":
                logger.error("Instagram: video processing error")
                return ""

        # Step 3: Publish
        pub_r = requests.post(
            f"{self.GRAPH_URL}/{self.user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.token},
            timeout=30,
        )
        pub_r.raise_for_status()
        media_id = pub_r.json().get("id", "")
        ig_url = f"https://www.instagram.com/reel/{media_id}/"
        logger.success(f"Instagram → {ig_url}")
        return ig_url


# ─── Orchestrator ─────────────────────────────────────────────────────────────

class SocialMediaUploader:
    def __init__(self, config: dict):
        self.cfg = config["social_media"]

    def upload_all(self, video_path: str, script_data: dict,
                   platform_captions: dict = None,
                   thumbnail_path: str = "") -> dict:
        """
        platform_captions: dict จาก generate_all_platform_captions()
          keys: tiktok, instagram, facebook, youtube
        """
        caps = platform_captions or {}
        results = {}

        # ── YouTube ──────────────────────────────────────────────────────────
        if self.cfg.get("youtube", {}).get("enabled"):
            secret = os.getenv("YOUTUBE_CLIENT_SECRET", "config/client_secret.json")
            yt_cap = caps.get("youtube", {})
            if Path(secret).exists():
                try:
                    yt = YouTubeUploader(secret)
                    results["youtube"] = yt.upload(
                        video_path,
                        title       = yt_cap.get("title", script_data["title"])[:100],
                        description = yt_cap.get("description", ""),
                        tags        = yt_cap.get("tags", []),
                        category_id = str(self.cfg["youtube"].get("category_id", "22")),
                        privacy     = self.cfg["youtube"].get("privacy", "public"),
                        thumbnail_path = thumbnail_path,
                    )
                except Exception as e:
                    logger.error(f"YouTube upload failed: {e}")
            else:
                logger.warning(f"YouTube: client_secret.json not found → ข้าม")

        # ── Facebook ─────────────────────────────────────────────────────────
        if self.cfg.get("facebook", {}).get("enabled"):
            token = os.getenv("FACEBOOK_ACCESS_TOKEN")
            fb_cap = caps.get("facebook", {})
            fb_desc = fb_cap.get("caption", "") + "\n" + " ".join(fb_cap.get("hashtags", []))
            if token:
                try:
                    fb = FacebookUploader(token, self.cfg["facebook"].get("page_id", "me"))
                    cross_ig = self.cfg.get("instagram", {}).get("cross_post_from_facebook", False)
                    results["facebook"] = fb.upload(
                        video_path,
                        title       = script_data["title"],
                        description = fb_desc.strip(),
                        cross_post_instagram = cross_ig,
                    )
                except Exception as e:
                    logger.error(f"Facebook upload failed: {e}")
            else:
                logger.warning("FACEBOOK_ACCESS_TOKEN not set → ข้าม")

        # ── Instagram (standalone Graph API) ─────────────────────────────────
        if self.cfg.get("instagram", {}).get("enabled") and \
           not self.cfg.get("instagram", {}).get("cross_post_from_facebook", False):
            ig_token   = os.getenv("INSTAGRAM_ACCESS_TOKEN")
            ig_user_id = os.getenv("INSTAGRAM_USER_ID")
            ig_video_url = os.getenv("INSTAGRAM_VIDEO_URL", "")
            ig_cap = caps.get("instagram", {})
            ig_caption = ig_cap.get("caption", "") + "\n" + " ".join(ig_cap.get("hashtags", []))
            if ig_token and ig_user_id:
                try:
                    ig = InstagramUploader(ig_token, ig_user_id)
                    results["instagram"] = ig.upload(
                        video_path, ig_caption.strip(), ig_video_url
                    )
                except Exception as e:
                    logger.error(f"Instagram upload failed: {e}")
            else:
                logger.warning("INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID not set → ข้าม")

        return results
