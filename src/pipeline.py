import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from tqdm import tqdm

from .script_generator import ScriptGenerator
from .tts_engine import TTSEngine
from .subtitle_generator import SubtitleGenerator
from .scene_builder import SceneBuilder
from .uploader import SocialMediaUploader
from .pexels_client import PexelsClient
from .music_library import MusicLibrary
from . import thumbnail_generator


class AutoClipPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.script_gen = ScriptGenerator(config)
        self.tts = TTSEngine(config)
        self.subtitle_gen = SubtitleGenerator()
        self.scene_builder = SceneBuilder(config)
        self.uploader = SocialMediaUploader(config)

    def run(
        self,
        topic: str,
        style: Optional[str] = None,
        duration: Optional[int] = None,
        background_path: Optional[str] = None,
        upload: bool = False,
        prefetched_script: Optional[dict] = None,
        last_framework: str = "",
        last_hook_types: list = None,
        last_cta: str = "",
        used_subtopics: list = None,
    ) -> dict:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path("output") / ts

        pexels_key = os.getenv("PEXELS_API_KEY")
        use_pexels = (pexels_key and background_path is None
                      and self.config.get("pexels", {}).get("enabled", True))

        steps = [
            "สร้างสคริปต์ AI",
            "ดึง scene videos จาก Pexels" if use_pexels else "เตรียม background",
            "สร้าง / ดาวน์โหลด background music",
            "แปลงเป็นเสียงพากย์ (TTS)",
            "สร้างซับไตเติ้ล",
            "ประกอบวิดีโอ (scene-by-scene)",
        ]
        if upload:
            steps.append("อัปโหลดโซเชียล")

        with tqdm(steps, desc="Auto-Clip", unit="step") as bar:

            # ── 1. Script ──────────────────────────────────────────────────────
            bar.set_description(steps[0])
            script_data = prefetched_script or self.script_gen.generate(
                topic, style, duration,
                last_framework=last_framework,
                last_hook_types=last_hook_types or [],
                last_cta=last_cta,
                used_subtopics=used_subtopics or [],
            )
            script_path = run_dir / "scripts" / "script.txt"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(
                f"TITLE: {script_data['title']}\n\n"
                + "\n".join(script_data["sentences"]),
                encoding="utf-8",
            )
            bar.update()

            # ── 2. Pexels scene pool ───────────────────────────────────────────
            bar.set_description(steps[1])
            scene_video_paths = []
            n_scenes = len(script_data["sentences"])

            if use_pexels:
                bg_dir = run_dir / "backgrounds"
                client = PexelsClient(pexels_key)
                quality = self.config.get("pexels", {}).get("quality", "4k")
                sentence_kws = script_data.get("sentence_keywords") or []

                if sentence_kws and len(sentence_kws) == n_scenes:
                    # per-scene: keyword[i] → video[i]
                    scene_video_paths = client.fetch_per_scene_videos(
                        sentence_keywords=sentence_kws,
                        output_dir=str(bg_dir),
                        quality=quality,
                    )
                else:
                    # fallback: global keyword pool
                    kws = script_data.get("pexels_keywords") or [topic.split()[0]]
                    scene_video_paths = client.fetch_scene_videos(
                        keywords=kws,
                        n_scenes=n_scenes,
                        output_dir=str(bg_dir),
                        quality=quality,
                    )
                if scene_video_paths:
                    logger.success(f"Pexels: {len(set(scene_video_paths))} unique videos "
                                   f"→ {n_scenes} scenes")
                else:
                    logger.warning("Pexels ไม่สำเร็จ — ใช้สีพื้นหลังแทน")
            elif background_path:
                scene_video_paths = [background_path] * n_scenes
            bar.update()

            # ── 3. Background music — mood ตาม framework ──────────────────────
            bar.set_description(steps[2])
            _FRAMEWORK_MOOD = {
                "story": "calm", "confession": "calm",
                "before_after": "inspirational", "deep_dive": "calm",
                "what_if": "calm", "comparison": "calm",
                "list": "upbeat", "countdown": "upbeat", "myth": "upbeat",
            }
            music_lib = MusicLibrary(cache_dir="input/music")
            fw = script_data.get("framework", "")
            mood = _FRAMEWORK_MOOD.get(fw, self.config.get("audio", {}).get("bg_music_mood", "calm"))
            logger.info(f"Music mood: {fw} → {mood}")
            music_path = None
            if self.config.get("audio", {}).get("bg_music_enabled", True):
                music_path = music_lib.get(mood, duration_hint=60.0)
            bar.update()

            # ── 4. TTS — เลือก voice ตาม framework (story/confession→หญิง, countdown/myth→ชาย)
            bar.set_description(steps[3])
            if not self.config["tts"].get("voice_id"):
                self.tts.auto_set_voice(
                    script_data["sentences"],
                    framework=script_data.get("framework", ""),
                )
            timing_data = self.tts.synthesize_all(
                script_data["sentences"], str(run_dir / "audio")
            )
            audio_path = run_dir / "audio" / "combined.mp3"
            TTSEngine.merge_audio(timing_data, str(audio_path))
            # scene split: ประโยค > 5 วินาที → แบ่งเป็น 2 scenes ที่ midpoint word
            timing_data = _split_long_scenes(timing_data, max_sec=3.0)
            bar.update()

            # ── 5. Subtitle files (SRT + ASS) ─────────────────────────────────
            bar.set_description(steps[4])
            srt_path = self.subtitle_gen.generate_srt(
                timing_data, str(run_dir / "subtitles" / "subtitles.srt")
            )
            ass_path = self.subtitle_gen.generate_ass(
                timing_data,
                str(run_dir / "subtitles" / "subtitles.ass"),
                font_size=self.config["video"]["font_size"],
                resolution=self.config["video"]["resolution"],
            )
            bar.update()

            # ── 6. Build scene-based video ────────────────────────────────────
            bar.set_description(steps[5])
            video_path = run_dir / "videos" / f"{ts}.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            self.scene_builder.build(
                timing_data=timing_data,
                scene_video_paths=scene_video_paths,
                audio_path=str(audio_path),
                output_path=str(video_path),
                bg_music_path=music_path,
                framework=script_data.get("framework", ""),
            )
            bar.update()

            # ── 7. Upload ─────────────────────────────────────────────────────
            upload_results = {}
            if upload:
                bar.set_description("อัปโหลดโซเชียล")
                upload_results = self.uploader.upload_all(
                    str(video_path), script_data,
                    platform_captions=platform_caps,
                    thumbnail_path=str(thumb_path) if thumb_path.exists() else "",
                )
                bar.update()

        # ── Thumbnail ─────────────────────────────────────────────────────────
        thumb_path = run_dir / "thumbnail.jpg"
        thumbnail_generator.generate(
            str(video_path), script_data["title"], str(thumb_path),
            sentences=script_data.get("sentences", []),
        )

        # ── Multi-platform captions ───────────────────────────────────────────
        platform_caps = self.script_gen.generate_all_platform_captions(
            script_data["title"], script_data["sentences"], topic,
            framework=script_data.get("framework", "list"),
        )
        _write_all_captions(run_dir, script_data["title"], platform_caps)

        unique_bgs = len(set(scene_video_paths)) if scene_video_paths else 0
        caption_path = run_dir / "captions" / "tiktok.txt"
        result = {
            "title": script_data["title"],
            "framework": script_data.get("framework", "list"),
            "hook_type": script_data.get("hook_type", ""),
            "cta_type":  script_data.get("cta_type", ""),
            "subtopic":  script_data.get("subtopic", ""),
            "pexels_keywords": script_data.get("pexels_keywords", []),
            "video_path": str(video_path),
            "thumbnail_path": str(thumb_path) if thumb_path.exists() else "",
            "script_path": str(script_path),
            "caption_path": str(caption_path),
            "captions_dir": str(run_dir / "captions"),
            "srt_path": srt_path,
            "duration": round(timing_data[-1]["end"], 1) if timing_data else 0,
            "sentences": n_scenes,
            "unique_bg_videos": unique_bgs,
            "music": Path(music_path).name if music_path else "none",
            "uploads": upload_results,
        }
        # ── Cleanup backgrounds/ — ลบ Pexels originals หลัง render เสร็จ ────────
        bg_dir = run_dir / "backgrounds"
        if bg_dir.exists():
            import shutil as _shutil
            _shutil.rmtree(bg_dir)
            logger.info("Cleanup: backgrounds/ deleted (saved to pexels_cache)")

        logger.success(f"Done! → {video_path}")
        return result


def _split_long_scenes(timing_data: list, max_sec: float = 5.0) -> list:
    """แบ่ง scene ที่ยาวกว่า max_sec วินาที เป็น 2 scene ที่ midpoint word
    word_timings ใช้ relative time (จากต้นประโยค) — duration คำนวณจาก relative เสมอ"""
    result = []
    for item in timing_data:
        dur = float(item.get("duration", 0))
        words = item.get("word_timings", [])
        if dur <= max_sec or len(words) < 4:
            result.append(item)
            continue
        mid = len(words) // 2
        # mid_time เป็น relative time จากต้นประโยค
        mid_rel = float(words[mid]["start"])
        dur_a = mid_rel
        dur_b = dur - mid_rel
        # ป้องกัน scene สั้นเกิน — subtitle ไม่มีเวลาแสดงพอ → ไม่ split
        if dur_a < 0.9 or dur_b < 0.9:
            result.append(item)
            continue
        if dur_a <= 0 or dur_b <= 0:
            result.append(item)
            continue
        part_a = dict(item)
        part_a["word_timings"] = words[:mid]
        part_a["duration"] = dur_a
        part_b = dict(item)
        # normalize part_b word_timings: subtract mid_rel so first word starts near 0
        new_words_b = []
        for w in words[mid:]:
            nw = dict(w)
            nw["start"] = float(w["start"]) - mid_rel
            nw["end"]   = float(w["end"])   - mid_rel
            new_words_b.append(nw)
        part_b["word_timings"] = new_words_b
        part_b["duration"] = dur_b
        # อัปเดต absolute start ของ part_b
        abs_start = float(item.get("start", 0))
        part_b["start"] = abs_start + mid_rel
        result.extend([part_a, part_b])
    if len(result) != len(timing_data):
        from loguru import logger
        logger.info(f"Scene split: {len(timing_data)} → {len(result)} scenes")
    return result


def _write_all_captions(run_dir: Path, title: str, platform_caps: dict):
    """บันทึก caption แยกไฟล์ต่อ platform ใน captions/"""
    cap_dir = run_dir / "captions"
    cap_dir.mkdir(parents=True, exist_ok=True)

    _FALLBACK = {
        "tiktok":    {"caption": title, "hashtags": ["#การเงิน","#ออมเงิน","#fyp","#foryoupage","#tiktokthailand","#moneytips","#personalfinance","#viral"]},
        "instagram": {"caption": title, "hashtags": ["#การเงิน","#ออมเงิน","#เก็บเงิน","#ลงทุน","#เงิน","#moneytips","#personalfinance","#financetips","#fyp","#foryoupage","#reels","#viral"]},
        "facebook":  {"caption": title, "hashtags": ["#การเงิน","#ออมเงิน","#เก็บเงิน"]},
        "youtube":   {"title": title, "description": title, "tags": ["การเงิน","ออมเงิน","money tips","personal finance"]},
    }

    sections = []

    for platform in ("tiktok", "instagram", "facebook", "youtube"):
        data = platform_caps.get(platform) or _FALLBACK[platform]
        path = cap_dir / f"{platform}.txt"

        if platform == "youtube":
            yt_title = data.get("title", title)
            yt_desc  = data.get("description", "")
            yt_tags  = ", ".join(data.get("tags", []))
            content  = f"TITLE: {yt_title}\n\nDESCRIPTION:\n{yt_desc}\n\nTAGS:\n{yt_tags}\n"
            section  = (
                f"📺  YOUTUBE SHORTS\n"
                f"{'─'*48}\n"
                f"Title:\n{yt_title}\n\n"
                f"Description:\n{yt_desc}\n\n"
                f"Tags:\n{yt_tags}\n"
            )
        else:
            caption  = data.get("caption", "")
            hashtags = " ".join(data.get("hashtags", []))
            content  = f"{caption}\n\n{hashtags}\n"
            icon = {"tiktok": "🎵  TIKTOK", "instagram": "📸  INSTAGRAM REELS", "facebook": "👥  FACEBOOK"}[platform]
            section  = (
                f"{icon}\n"
                f"{'─'*48}\n"
                f"{caption}\n\n"
                f"{hashtags}\n"
            )

        path.write_text(content, encoding="utf-8")
        sections.append(section)

    # post_kit.txt — รวมทุก platform ในไฟล์เดียว
    sep  = "═" * 52
    kit  = f"{sep}\n  📋  POST KIT — {title}\n{sep}\n\n"
    kit += f"\n\n{'━'*52}\n\n".join(sections)
    kit += f"\n\n{sep}\n"
    (cap_dir / "post_kit.txt").write_text(kit, encoding="utf-8")

    logger.info(f"Captions → {cap_dir.name}/ (post_kit + tiktok / instagram / facebook / youtube)")
