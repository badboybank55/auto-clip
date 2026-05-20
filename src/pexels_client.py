import hashlib
import shutil
import subprocess
import requests
from pathlib import Path
from typing import Optional
from loguru import logger

# Persistent video cache — เก็บ video ที่ผ่าน QC ไว้ใช้ซ้ำ
_PEXELS_CACHE = Path("input/pexels_cache")


def _cache_key(keyword: str) -> str:
    return hashlib.md5(keyword.lower().strip().encode()).hexdigest()[:10]


def _get_cached_video(keyword: str) -> Optional[str]:
    """คืน path ของ video ที่ cache ไว้สำหรับ keyword นี้ — สุ่มเพื่อไม่ให้ซ้ำเดิมทุกครั้ง"""
    import random
    _PEXELS_CACHE.mkdir(parents=True, exist_ok=True)
    key = _cache_key(keyword)
    hits = [f for f in _PEXELS_CACHE.glob(f"{key}_*.mp4")
            if f.stat().st_size > 700_000]
    return str(random.choice(hits)) if hits else None


def _save_to_cache(src: str, keyword: str) -> str:
    """คัดลอก video ที่ผ่าน QC ไปเก็บใน cache"""
    _PEXELS_CACHE.mkdir(parents=True, exist_ok=True)
    key = _cache_key(keyword)
    dst = _PEXELS_CACHE / f"{key}_{Path(src).name}"
    if not dst.exists():
        shutil.copy2(src, dst)
        logger.debug(f"Cached: {dst.name}")
    return str(dst)


def _video_duration(path: str) -> float:
    """ffprobe duration check — คืน 0.0 ถ้าไม่ใช่ video จริง"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=8,
        )
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def _video_fps(path: str) -> float:
    """ffprobe fps check — คืน 0.0 ถ้าเป็น slideshow (fps ต่ำมาก)"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=8,
        )
        val = r.stdout.strip()
        if "/" in val:
            n, d = val.split("/")
            return float(n) / float(d) if float(d) > 0 else 0.0
        return float(val) if val else 0.0
    except Exception:
        return 0.0


QUALITY_PRIORITY = ["4k", "uhd", "hd", "sd", ""]
# fallback chain: ลองทีละ keyword จนกว่าจะเจอ video จริง
FALLBACK_KEYWORDS = [
    "person counting money cash", "hand wallet payment",
    "woman phone banking app", "man laptop working desk",
    "couple discussing finances", "piggy bank saving",
    "credit card payment terminal", "coins stacking money",
    "person smiling confident business", "office meeting table",
    "hands writing notebook pen", "phone screen calculator",
    "young adult thinking planning", "city lifestyle commute",
    "coffee shop person working", "shopping bags retail",
]


class PexelsClient:
    VIDEOS_URL = "https://api.pexels.com/videos/search"

    def __init__(self, api_key: str):
        self.headers = {"Authorization": api_key}

    # ─── Search ──────────────────────────────────────────────────────────────

    def search(self, query: str, orientation: str = "portrait", per_page: int = 10) -> list:
        params = {
            "query": query,
            "per_page": min(per_page, 80),
            "size": "large",
            **({"orientation": orientation} if orientation else {}),
        }
        try:
            resp = requests.get(self.VIDEOS_URL, headers=self.headers,
                                params=params, timeout=15)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            logger.debug(f"Pexels '{query}' [{orientation or 'any'}]: {len(videos)} hits")
            return videos
        except Exception as e:
            logger.warning(f"Pexels search error ({query}): {e}")
            return []

    # ─── File selection ───────────────────────────────────────────────────────

    def _pick_file(self, video: dict, quality: str = "4k") -> Optional[str]:
        files = video.get("video_files", [])
        portrait = [f for f in files if f.get("height", 0) > f.get("width", 0)]

        start = QUALITY_PRIORITY.index(quality) if quality in QUALITY_PRIORITY else 0
        for q in QUALITY_PRIORITY[start:]:
            for pool in (portrait, files):
                for f in pool:
                    if not q or f.get("quality") == q:
                        res = f"{f.get('width', '?')}x{f.get('height', '?')}"
                        logger.debug(f"  file: {res} q={f.get('quality')}")
                        return f["link"]
        return None

    # ─── Download ─────────────────────────────────────────────────────────────

    def download(self, url: str, output_path: str) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        written = 0
        with open(output_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 17):
                fh.write(chunk)
                written += len(chunk)
        logger.info(f"  ↓ {output_path.name} ({written/1024/1024:.1f}/{total/1024/1024:.1f} MB)")
        return str(output_path)

    # ─── Single background (legacy) ───────────────────────────────────────────

    def fetch_background(self, keywords: list, output_path: str,
                         quality: str = "4k") -> Optional[str]:
        for kw in keywords:
            for orientation in ("portrait", "landscape", ""):
                videos = self.search(kw, orientation=orientation, per_page=5)
                if videos:
                    url = self._pick_file(videos[0], quality)
                    if url:
                        logger.info(f"Pexels bg: '{kw}' → {videos[0].get('url', '')}")
                        return self.download(url, output_path)
        logger.warning(f"No Pexels background for {keywords}")
        return None

    # ─── Per-scene fetch (keyword[i] → video[i]) ─────────────────────────────

    def fetch_per_scene_videos(
        self,
        sentence_keywords: list,
        output_dir: str,
        quality: str = "4k",
    ) -> list:
        """
        Fetch one matching video per sentence keyword, maintaining order.
        dedup by URL — reuses cached file if same URL appears again.
        Falls back to any previously-downloaded video if a keyword fails.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        url_to_path: dict = {}   # url → local path (dedup)
        result_paths: list = []
        fallback_paths: list = []

        MIN_FILE_BYTES = 700_000  # < 700KB = คลิปสั้นหรือคุณภาพต่ำ → ข้าม

        for i, kw in enumerate(sentence_keywords):
            matched = False
            prev_path = result_paths[-1] if result_paths else None  # ห้ามซ้ำ scene ก่อนหน้า

            # ── ตรวจ persistent cache ก่อน download ───────────────────────────
            cached = _get_cached_video(kw)
            if cached and cached != prev_path:
                out = str(output_dir / f"scene_{i:03d}.mp4")
                shutil.copy2(cached, out)
                logger.info(f"  ↳ cache hit: {Path(cached).name}")
                result_paths.append(out)
                fallback_paths.append(out)
                url_to_path[f"__cache__{kw}"] = out
                continue

            for orientation in ("portrait", ""):
                videos = self.search(kw, orientation=orientation, per_page=15)
                for v in videos:
                    url = self._pick_file(v, quality)
                    if not url:
                        continue
                    if url not in url_to_path:
                        out = output_dir / f"scene_{i:03d}.mp4"
                        self.download(url, str(out))
                        # ตรวจ size / duration / fps — ถ้าไม่ผ่านให้ข้ามหา video ถัดไป
                        sz  = Path(str(out)).stat().st_size
                        dur = _video_duration(str(out))
                        fps = _video_fps(str(out))
                        if sz < MIN_FILE_BYTES or dur < 2.0 or fps < 12:
                            logger.warning(f"  ↳ {Path(str(out)).name} ไม่ผ่าน (size={sz//1024}KB dur={dur:.1f}s fps={fps:.0f}) → ข้าม")
                            Path(str(out)).unlink(missing_ok=True)
                            continue
                        _save_to_cache(str(out), kw)   # บันทึก cache
                        url_to_path[url] = str(out)
                    local = url_to_path[url]
                    if local == prev_path:  # ห้ามซ้ำ scene ติดกัน
                        continue
                    result_paths.append(local)
                    fallback_paths.append(local)
                    matched = True
                    break
                if matched:
                    break

            if not matched:
                # ลอง generic fallback keywords ก่อนให้ซ้ำ video
                for fb_kw in FALLBACK_KEYWORDS:
                    for orientation in ("portrait", ""):
                        videos = self.search(fb_kw, orientation=orientation, per_page=5)
                        for v in videos:
                            url = self._pick_file(v, quality)
                            if not url:
                                continue
                            if url not in url_to_path:
                                out = output_dir / f"scene_{i:03d}.mp4"
                                self.download(url, str(out))
                                sz  = Path(str(out)).stat().st_size
                                dur = _video_duration(str(out))
                                fps = _video_fps(str(out))
                                if sz < MIN_FILE_BYTES or dur < 2.0 or fps < 12:
                                    logger.warning(f"  ↳ fallback {Path(str(out)).name} ไม่ผ่าน ({sz//1024}KB) → ข้าม")
                                    Path(str(out)).unlink(missing_ok=True)
                                    continue
                                url_to_path[url] = str(out)
                            local = url_to_path[url]
                            if local == prev_path:  # ห้ามซ้ำ scene ติดกัน
                                continue
                            result_paths.append(local)
                            fallback_paths.append(local)
                            matched = True
                            break
                        if matched:
                            break
                    if matched:
                        break
                    logger.warning(f"Pexels: '{kw}' → '{fb_kw}' ก็ไม่เจอ ลองต่อ")

            if not matched:
                # last resort: เลือก video ที่ไม่ซ้ำ scene ก่อนหน้า
                if fallback_paths:
                    prev = result_paths[-1] if result_paths else None
                    candidates = [p for p in fallback_paths if p != prev] or fallback_paths
                    fb = candidates[i % len(candidates)]
                    result_paths.append(fb)
                    logger.warning(f"Pexels: ทุก keyword ล้มเหลว → ซ้ำ {Path(fb).name}")
                else:
                    # ยังไม่มี video เลย ลอง "nature" ไม่จำกัด orientation
                    for emergency_kw in ["nature", "sky", "water", "abstract"]:
                        videos = self.search(emergency_kw, orientation="", per_page=3)
                        for v in videos:
                            url = self._pick_file(v, "hd")
                            if url:
                                out = output_dir / f"scene_{i:03d}.mp4"
                                self.download(url, str(out))
                                if Path(str(out)).stat().st_size >= MIN_FILE_BYTES:
                                    url_to_path[url] = str(out)
                                    result_paths.append(str(out))
                                    fallback_paths.append(str(out))
                                    matched = True
                                    break
                        if matched:
                            break
                    if not matched:
                        logger.error(f"Scene {i+1}: ไม่พบ video เลย — จะใช้สีพื้น")

        logger.info(f"Per-scene fetch: {len(url_to_path)} unique downloads for {len(sentence_keywords)} scenes")
        return result_paths

    # ─── Scene pool (legacy) ─────────────────────────────────────────────────

    def fetch_scene_videos(
        self,
        keywords: list,
        n_scenes: int,
        output_dir: str,
        quality: str = "4k",
        orientation: str = "portrait",
    ) -> list:
        """
        ดาวน์โหลด video pool สำหรับทุกฉาก — dedup by Pexels video ID
        Return: list[str] ของ path ยาว n_scenes (repeating if pool < scenes)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # — รวบรวม unique video entries จากทุก keyword —
        per_kw = max(5, -(-n_scenes // max(len(keywords), 1)))  # ceiling div
        unique: dict = {}   # id → {url, pexels_url}

        orient_fallbacks = (orientation, "") if orientation else ("",)
        for kw in keywords:
            for orient in orient_fallbacks:
                results = self.search(kw, orientation=orient,
                                      per_page=min(per_kw, 15))
                for v in results:
                    vid_id = v["id"]
                    if vid_id not in unique:
                        url = self._pick_file(v, quality)
                        if url:
                            unique[vid_id] = {
                                "url": url,
                                "pexels_url": v.get("url", ""),
                                "keyword": kw,
                            }
                if results:
                    break  # พบผลลัพธ์แล้ว ไม่ต้องลอง orientation ถัดไป
            if len(unique) >= n_scenes:
                break

        if not unique:
            logger.warning("Pexels: ไม่พบ video เลย")
            return []

        # — ดาวน์โหลด unique videos —
        url_to_path: dict = {}
        ordered_paths = []
        for info in list(unique.values())[:n_scenes]:
            url = info["url"]
            if url not in url_to_path:
                idx = len(url_to_path)
                out = output_dir / f"scene_{idx:03d}.mp4"
                self.download(url, str(out))
                url_to_path[url] = str(out)
            ordered_paths.append(url_to_path[url])

        logger.info(f"Pexels pool: {len(url_to_path)} unique videos for {n_scenes} scenes")

        # — ถ้า pool น้อยกว่า scenes ให้ rotate —
        if not ordered_paths:
            return []
        while len(ordered_paths) < n_scenes:
            ordered_paths = ordered_paths + ordered_paths
        return ordered_paths[:n_scenes]
