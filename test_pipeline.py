"""
ทดสอบ pipeline เต็มรูปแบบ ไม่ต้องใช้ ANTHROPIC_API_KEY
ครอบคลุม: normalize_numbers · Pexels scene pool · ambient music · TTS · SceneBuilder
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from pathlib import Path
from loguru import logger

from dotenv import load_dotenv
load_dotenv()

from src.utils import load_config, setup_logger
from src.script_generator import normalize_numbers
from src.tts_engine import TTSEngine
from src.subtitle_generator import SubtitleGenerator
from src.scene_builder import SceneBuilder
from src.pexels_client import PexelsClient
from src.music_library import MusicLibrary


SAMPLE_SCRIPT = {
    "title": "5 เคล็ดลับออมเงิน ที่ทำได้ตั้งแต่วันนี้",
    "pexels_keywords": ["money saving", "piggy bank", "finance"],
    "sentences": [
        "อยากมีเงินเก็บ แต่ไม่รู้จะเริ่มยังไง",
        "วันนี้มี 5 เคล็ดลับที่ทำได้ทันที",
        "ข้อที่ 1 ตั้งเป้าออมก่อนใช้",
        "พอรับเงินเดือน โอนออมทันที 20 เปอร์เซ็นต์",
        "ข้อที่ 2 จดรายจ่ายทุกบาท",
        "รู้ว่าเงินหายไปไหน แก้ได้ตรงจุด",
        "ข้อที่ 3 ลด subscription ที่ไม่ได้ใช้",
        "เดือนละ 1,000 ถึง 2,000 บาท บวกกันแล้วเยอะนะ",
        "ข้อที่ 4 ทำอาหารกินเองสัปดาห์ละ 3 วัน",
        "ประหยัดได้หลาย 100 บาทต่อสัปดาห์",
        "ข้อที่ 5 ลงทุนในตัวเอง",
        "ความรู้ที่ได้คือสินทรัพย์ที่ไม่มีวันหมด",
        "เริ่มวันนี้เลย ชีวิตการเงินดีขึ้นแน่นอน",
    ],
}


def test_normalize():
    cases = [
        ("ข้อ ๑ ออมเงิน ๕ เปอร์เซ็นต์", "ข้อ 1 ออมเงิน 5 เปอร์เซ็นต์"),
        ("๒,๕๐๐ บาท วันที่ ๓๑", "2,500 บาท วันที่ 31"),
        ("no thai digits here", "no thai digits here"),
    ]
    passed = True
    for src, expected in cases:
        got = normalize_numbers(src)
        ok = got == expected
        passed = passed and ok
        logger.info(f"  normalize {'✓' if ok else '✗'}: '{src}' → '{got}'")
    assert passed, "normalize_numbers failed"


def run_test():
    config = load_config("config/settings.yaml")
    setup_logger(config)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("output") / f"test_{ts}"

    logger.info("=" * 58)
    logger.info("AUTO-CLIP FULL TEST")
    logger.info("=" * 58)

    # ── 0. normalize numbers ──────────────────────────────────────────────────
    logger.info("[0] ทดสอบ normalize_numbers…")
    test_normalize()
    logger.success("  normalize_numbers ✓")

    # ── 1. Pexels scene videos ────────────────────────────────────────────────
    pexels_key = os.getenv("PEXELS_API_KEY")
    scene_video_paths = []
    n_scenes = len(SAMPLE_SCRIPT["sentences"])

    if pexels_key:
        logger.info(f"[1] ดึง scene videos จาก Pexels ({n_scenes} ฉาก)…")
        client = PexelsClient(pexels_key)
        bg_dir = run_dir / "backgrounds"
        scene_video_paths = client.fetch_scene_videos(
            keywords=SAMPLE_SCRIPT["pexels_keywords"],
            n_scenes=n_scenes,
            output_dir=str(bg_dir),
            quality=config.get("pexels", {}).get("quality", "4k"),
        )
        unique = len(set(scene_video_paths))
        logger.success(f"  {unique} unique videos → {n_scenes} scenes")
    else:
        logger.info("[1] ข้าม Pexels (ไม่มี PEXELS_API_KEY) — ใช้สีพื้นหลัง")

    # ── 2. Background music ───────────────────────────────────────────────────
    logger.info("[2] เตรียม background music…")
    music_lib = MusicLibrary(cache_dir="input/music")
    music_path = music_lib.get("calm", duration_hint=60.0)
    if music_path:
        logger.success(f"  Music: {Path(music_path).name}")
    else:
        logger.warning("  ไม่มี background music")

    # ── 3. TTS ───────────────────────────────────────────────────────────────
    logger.info("[3] แปลงข้อความเป็นเสียงพากย์…")
    tts = TTSEngine(config)
    timing_data = tts.synthesize_all(
        SAMPLE_SCRIPT["sentences"], str(run_dir / "audio")
    )
    audio_path = run_dir / "audio" / "combined.mp3"
    TTSEngine.merge_audio(timing_data, str(audio_path))
    logger.success(f"  {len(timing_data)} ประโยค, รวม {timing_data[-1]['end']:.1f}s")

    # ── 4. Subtitles ──────────────────────────────────────────────────────────
    logger.info("[4] สร้างซับไตเติ้ล…")
    sub = SubtitleGenerator()
    srt_path = sub.generate_srt(timing_data, str(run_dir / "subtitles" / "subtitles.srt"))
    ass_path = sub.generate_ass(
        timing_data, str(run_dir / "subtitles" / "subtitles.ass"),
        font_size=config["video"]["font_size"],
        resolution=config["video"]["resolution"],
    )

    # ── 5. Scene-based video ─────────────────────────────────────────────────
    logger.info(f"[5] ประกอบวิดีโอ {n_scenes} ฉาก…")
    builder = SceneBuilder(config)
    video_path = run_dir / "videos" / f"test_{ts}.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    builder.build(
        timing_data=timing_data,
        scene_video_paths=scene_video_paths,
        audio_path=str(audio_path),
        output_path=str(video_path),
        bg_music_path=music_path,
    )

    # ── Result ────────────────────────────────────────────────────────────────
    size_mb = video_path.stat().st_size / 1024 / 1024
    unique_bg = len(set(scene_video_paths)) if scene_video_paths else 0
    logger.info("=" * 58)
    logger.success("TEST PASSED!")
    logger.info(f"  วิดีโอ      : {video_path}")
    logger.info(f"  ขนาด        : {size_mb:.1f} MB")
    logger.info(f"  ความยาว     : {timing_data[-1]['end']:.1f} วินาที")
    logger.info(f"  ฉาก         : {n_scenes} scenes")
    logger.info(f"  Pexels pool : {unique_bg} unique videos")
    logger.info(f"  Music       : {Path(music_path).name if music_path else 'ไม่มี'}")
    logger.info("=" * 58)
    print(f"\nไฟล์วิดีโอ: {video_path.absolute()}\n")
    return str(video_path)


if __name__ == "__main__":
    run_test()
