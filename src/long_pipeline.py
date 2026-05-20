"""
Long-form pipeline: generates 1 long 16:9 YouTube video + 3-5 short 9:16 clips.

Output structure:
  output/TIMESTAMP_long/
    long/
      video.mp4          (16:9, 8-10 min)
      script.txt
      thumbnail.jpg
      captions/youtube.txt
    shorts/
      01/
        teaser.mp4       (9:16, ~55s, ends with "ดูต่อที่ YouTube")
        fb_complete.mp4  (9:16, ~55s, จบในตัว)
        captions/
      02/ ...
      03/ ...
"""

import copy
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from tqdm import tqdm

from .long_script_generator import (
    generate_long_form_script, extract_all_sentences,
    build_short_script, generate_long_captions,
)
from .yt_lower_third import add_lower_third_to_video
from .channel_intro import add_channel_intro
from .script_generator import ScriptGenerator
from .tts_engine import TTSEngine
from .subtitle_generator import SubtitleGenerator
from .scene_builder import SceneBuilder
from .pexels_client import PexelsClient
from .music_library import MusicLibrary
from . import thumbnail_generator
from .notifier import notify_pipeline_start, notify_pipeline_done, notify_pipeline_fail


def _split_long_scenes(timing_data, max_sec=3.0):
    """Split scenes > max_sec — reuse from pipeline.py logic"""
    from .pipeline import _split_long_scenes as _sls
    return _sls(timing_data, max_sec)


def _write_captions(cap_dir: Path, caps: dict):
    cap_dir.mkdir(parents=True, exist_ok=True)
    for platform, data in caps.items():
        if platform == "youtube":
            content = (
                f"TITLE: {data.get('title','')}\n\n"
                f"DESCRIPTION:\n{data.get('description','')}\n\n"
                f"TAGS:\n{', '.join(data.get('tags',[]))}\n"
            )
        else:
            caption = data.get("caption", "")
            hashtags = " ".join(data.get("hashtags", []))
            content = f"{caption}\n\n{hashtags}\n"
        (cap_dir / f"{platform}.txt").write_text(content, encoding="utf-8")


def _render_video(
    sentences: list,
    topic: str,
    orientation: str,  # "landscape" | "portrait"
    output_path: Path,
    run_dir: Path,
    config: dict,
    tts: TTSEngine,
    subtitle_gen: SubtitleGenerator,
    music_path: Optional[str] = None,
    label: str = "",
):
    """Render a single video from sentences. Returns timing_data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_dir = run_dir / "audio"
    sub_dir   = run_dir / "subtitles"
    bg_dir    = run_dir / "backgrounds"

    # Build config override for orientation
    cfg = copy.deepcopy(config)
    if orientation == "landscape":
        cfg["video"]["resolution"] = "1920x1080"
        cfg["video"]["font_size"]  = 56
        cfg["subtitle"]["position_pct"] = 0.82
        cfg["subtitle"]["max_chars_per_line"] = 28
        cfg["pexels"]["orientation"] = "landscape"
    else:
        cfg["video"]["resolution"] = "1080x1920"
        cfg["pexels"]["orientation"] = "portrait"

    scene_builder = SceneBuilder(cfg)

    # TTS
    logger.info(f"{label}: TTS {len(sentences)} sentences...")
    timing_data = tts.synthesize_all(sentences, str(audio_dir))
    audio_path  = audio_dir / "combined.mp3"
    TTSEngine.merge_audio(timing_data, str(audio_path))
    timing_data = _split_long_scenes(timing_data, max_sec=3.0)

    # Subtitles
    subtitle_gen.generate_srt(timing_data, str(sub_dir / "subtitles.srt"))
    subtitle_gen.generate_ass(
        timing_data, str(sub_dir / "subtitles.ass"),
        font_size=cfg["video"]["font_size"],
        resolution=cfg["video"]["resolution"],
    )

    # Pexels
    pexels_key = os.getenv("PEXELS_API_KEY", "")
    scene_videos = []
    if pexels_key:
        import random
        client = PexelsClient(pexels_key)
        # keyword จาก topic + visual pool หมุนเวียน ไม่ซ้ำเดิมทุกคลิป
        topic_words = [w for w in topic.split() if len(w) > 3
                       and w not in {"และ","หรือ","ที่","ใน","กับ","vs","—","ของ","ให้","จาก","ได้","เป็น"}]
        visual_pool = [
            "person thinking planning desk",
            "calculator budget spreadsheet",
            "graph chart growth data",
            "hands document pen signing",
            "phone screen banking app",
            "office laptop working coffee",
            "family home lifestyle happy",
            "market shopping price tag",
            "coins jar saving piggy bank",
            "city commute business people",
            "young adult smiling confident",
            "couple discussing home table",
            "wallet cash spending payment",
            "sunrise nature motivation",
            "stock market screen numbers",
            "person reading book learning",
        ]
        random.shuffle(visual_pool)
        kws = topic_words[:2] + visual_pool[:4]
        n = len(timing_data)
        scene_videos = client.fetch_scene_videos(
            keywords=kws, n_scenes=n,
            output_dir=str(bg_dir),
            quality=cfg.get("pexels", {}).get("quality", "hd"),
            orientation=orientation,
        )

    # Render
    scene_builder.build(
        timing_data=timing_data,
        scene_video_paths=scene_videos,
        audio_path=str(audio_path),
        output_path=str(output_path),
        bg_music_path=music_path,
        framework="list",
    )
    logger.success(f"{label}: rendered → {output_path.name}")
    return timing_data


class LongFormPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.tts    = TTSEngine(config)
        self.subtitle_gen = SubtitleGenerator()
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.script_gen = ScriptGenerator(config)

    def run(self, topic: str) -> dict:
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S") + "_long"
        run_dir = Path("output") / ts
        run_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"=== Long-form pipeline: {topic} ===")
        notify_pipeline_start(topic)

        # ── 1. Generate long script ───────────────────────────────────────────
        logger.info("Generating long-form script...")
        script_data = generate_long_form_script(
            topic, self.client,
            model=self.config["script"]["model"],
        )

        # Save script
        script_dir = run_dir / "long" / "scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        all_sentences = extract_all_sentences(script_data)
        (script_dir / "script.txt").write_text(
            f"TITLE: {script_data['seo_title']}\n\n" + "\n".join(all_sentences),
            encoding="utf-8",
        )

        # ── 2. Music ──────────────────────────────────────────────────────────
        music_lib  = MusicLibrary(cache_dir="input/music")
        music_path = music_lib.get("calm", duration_hint=600.0)

        # ── 3. Render LONG video (16:9) ───────────────────────────────────────
        logger.info("Rendering long 16:9 video...")
        long_video = run_dir / "long" / "videos" / "long.mp4"
        long_dir   = run_dir / "long"

        # Auto voice
        self.tts.auto_set_voice(all_sentences, framework="story")

        _render_video(
            sentences=all_sentences,
            topic=topic,
            orientation="landscape",
            output_path=long_video,
            run_dir=long_dir,
            config=self.config,
            tts=self.tts,
            subtitle_gen=self.subtitle_gen,
            music_path=music_path,
            label="LONG",
        )

        # Thumbnail for long video
        long_thumb = run_dir / "long" / "thumbnail.jpg"
        thumbnail_generator.generate(
            str(long_video), script_data["seo_title"], str(long_thumb),
            sentences=all_sentences,
        )

        # Long captions (YouTube only)
        # Estimate section timestamps from sentence count
        section_timestamps = _estimate_timestamps(script_data)
        long_yt_cap = generate_long_captions(script_data, section_timestamps)
        _write_captions(run_dir / "long" / "captions", {"youtube": long_yt_cap})

        # ── 4. Render SHORTS (9:16) ───────────────────────────────────────────
        sections     = script_data.get("sections", [])
        shorts_dir   = run_dir / "shorts"
        short_results = []

        for i, section in enumerate(sections, 1):
            label    = f"SHORT_{i:02d}"
            s_dir    = shorts_dir / f"{i:02d}"
            s_dir.mkdir(parents=True, exist_ok=True)

            logger.info(f"Rendering {label}: {section['title']}")

            logo = str(Path("assets") / "profile.jpg")

            # ── Teaser YouTube Shorts (CTA: ลิงก์ใน description) ──────────────
            yt_sentences = build_short_script(section, style="teaser", platform="youtube")
            yt_path      = s_dir / "teaser_yt.mp4"
            yt_timing    = _render_video(
                sentences=yt_sentences,
                topic=topic,
                orientation="portrait",
                output_path=yt_path,
                run_dir=s_dir / "teaser_yt_render",
                config=self.config,
                tts=self.tts,
                subtitle_gen=self.subtitle_gen,
                music_path=music_path,
                label=f"{label}_YT",
            )
            hook_end_yt = yt_timing[0]["end"] if yt_timing else 3.0
            tmp = str(s_dir / "yt_intro.mp4")
            add_channel_intro(input_video=str(yt_path), output_video=tmp,
                              logo_path=logo, appear_at_sec=hook_end_yt)
            tmp2 = str(s_dir / "yt_lt.mp4")
            add_lower_third_to_video(input_video=tmp, output_video=tmp2,
                                     logo_path=logo, is_landscape=False, style="youtube")
            yt_path.unlink(missing_ok=True)
            Path(tmp).unlink(missing_ok=True)
            Path(tmp2).rename(yt_path)

            # ── Teaser Instagram (CTA: ลิงก์ใน bio) ───────────────────────────
            ig_sentences = build_short_script(section, style="teaser", platform="instagram")
            ig_path      = s_dir / "teaser_ig.mp4"
            ig_timing    = _render_video(
                sentences=ig_sentences,
                topic=topic,
                orientation="portrait",
                output_path=ig_path,
                run_dir=s_dir / "teaser_ig_render",
                config=self.config,
                tts=self.tts,
                subtitle_gen=self.subtitle_gen,
                music_path=music_path,
                label=f"{label}_IG",
            )
            hook_end_ig = ig_timing[0]["end"] if ig_timing else 3.0
            tmp = str(s_dir / "ig_intro.mp4")
            add_channel_intro(input_video=str(ig_path), output_video=tmp,
                              logo_path=logo, appear_at_sec=hook_end_ig)
            tmp2 = str(s_dir / "ig_lt.mp4")
            add_lower_third_to_video(input_video=tmp, output_video=tmp2,
                                     logo_path=logo, is_landscape=False, style="youtube")
            ig_path.unlink(missing_ok=True)
            Path(tmp).unlink(missing_ok=True)
            Path(tmp2).rename(ig_path)

            # ── FB Complete ────────────────────────────────────────────────────
            fb_sentences = build_short_script(section, style="complete")
            fb_path      = s_dir / "fb_complete.mp4"
            fb_timing    = _render_video(
                sentences=fb_sentences,
                topic=topic,
                orientation="portrait",
                output_path=fb_path,
                run_dir=s_dir / "fb_render",
                config=self.config,
                tts=self.tts,
                subtitle_gen=self.subtitle_gen,
                music_path=music_path,
                label=f"{label}_FB",
            )
            hook_end_fb = fb_timing[0]["end"] if fb_timing else 3.0

            # Step 1: channel intro
            tmp_fb1 = str(s_dir / "fb_intro.mp4")
            add_channel_intro(
                input_video=str(fb_path),
                output_video=tmp_fb1,
                logo_path=logo,
                appear_at_sec=hook_end_fb,
            )

            # Step 2: Facebook lower third (Follow pill near end)
            tmp_fb2 = str(s_dir / "fb_lt.mp4")
            add_lower_third_to_video(
                input_video=tmp_fb1,
                output_video=tmp_fb2,
                logo_path=logo,
                is_landscape=False,
                style="facebook",
            )

            fb_path.unlink(missing_ok=True)
            Path(tmp_fb1).unlink(missing_ok=True)
            Path(tmp_fb2).rename(fb_path)

            # Captions for this short
            teaser_caps = self.script_gen.generate_all_platform_captions(
                title=section["title"],
                sentences=yt_sentences,
                topic=topic,
            )
            fb_caps = {
                "facebook": {
                    "caption": f"{section['title']}\n\n{' '.join(fb_sentences[-2:])}",
                    "hashtags": ["#การเงิน", "#ออมเงิน", "#เงินงอก", "#moneytips", "#personalfinance"],
                },
            }
            _write_captions(s_dir / "captions" / "teaser", teaser_caps)
            _write_captions(s_dir / "captions" / "fb", fb_caps)

            short_results.append({
                "section_title": section["title"],
                "teaser_yt":     str(yt_path),
                "teaser_ig":     str(ig_path),
                "fb_complete":   str(fb_path),
                "captions_dir":  str(s_dir / "captions"),
            })

        logger.success(f"=== Long-form pipeline done: {run_dir} ===")
        logger.info(f"  Long video: {long_video}")
        logger.info(f"  Shorts: {len(short_results)} × (teaser + fb_complete)")
        notify_pipeline_done(topic, str(run_dir), len(short_results))

        return {
            "run_dir":      str(run_dir),
            "long_video":   str(long_video),
            "long_thumb":   str(long_thumb),
            "long_caps":    long_yt_cap,
            "shorts":       short_results,
            "script_data":  script_data,
        }


def _estimate_timestamps(script_data: dict) -> list[dict]:
    """คาดเดา timestamp ของแต่ละ section จากจำนวน sentence"""
    SEC_PER_SENTENCE = 8.5  # measured avg
    ts = []
    current = len(script_data.get("intro", [])) * SEC_PER_SENTENCE
    ts.append({"title": "Intro", "start_sec": 0})
    for section in script_data.get("sections", []):
        ts.append({"title": section["title"], "start_sec": int(current)})
        current += len(section.get("sentences", [])) * SEC_PER_SENTENCE
    return ts
