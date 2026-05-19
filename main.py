#!/usr/bin/env python3
"""Auto-Clip — ระบบสร้างคลิปอัตโนมัติด้วย AI"""

import argparse
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from src.utils import load_config, setup_logger
from src.pipeline import AutoClipPipeline
from src.topic_manager import TopicManager


def parse_args():
    p = argparse.ArgumentParser(
        description="Auto-Clip — สร้างคลิปวิดีโอภาษาไทยอัตโนมัติด้วย AI",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--topic", "-t", default=None,
                   help="หัวข้อวิดีโอ เช่น 'วิธีออมเงิน 10 เคล็ดลับ'")
    p.add_argument("--auto", "-a", action="store_true",
                   help="เลือก topic อัตโนมัติจาก AI topic queue (ไม่ต้องใส่ --topic)")
    p.add_argument("--count", "-n", type=int, default=1,
                   help="จำนวนคลิปที่จะสร้างติดกัน (ใช้กับ --auto เท่านั้น)")
    p.add_argument("--series", type=str, default="",
                   help="สร้าง series 3-5 ตอนจาก topic นี้ แล้วเพิ่มเข้า queue เช่น 'วิธีออมเงิน'")
    p.add_argument("--series-count", type=int, default=3,
                   help="จำนวนตอนใน series (default: 3)")
    p.add_argument("--style", "-s",
                   choices=["engaging", "educational", "entertaining"],
                   help="สไตล์เนื้อหา (default: ตามใน settings.yaml)")
    p.add_argument("--duration", "-d", type=int,
                   help="ความยาววิดีโอ วินาที (default: ตามใน settings.yaml)")
    p.add_argument("--background", "-b",
                   help="ไฟล์ภาพ/วิดีโอพื้นหลัง (jpg/png/mp4)")
    p.add_argument("--upload", "-u", action="store_true",
                   help="อัปโหลดโซเชียลมีเดียอัตโนมัติหลัง export")
    p.add_argument("--preview", "-p", action="store_true",
                   help="แสดงสคริปต์และรอ confirm ก่อนสร้างวิดีโอ")
    p.add_argument("--config", "-c", default="config/settings.yaml",
                   help="path ของไฟล์ตั้งค่า")
    return p.parse_args()


def check_env():
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        logger.error(f"กรุณาตั้งค่า environment variables ใน .env: {', '.join(missing)}")
        sys.exit(1)


def _resolve_topic(args) -> tuple:
    """คืน (topic, topic_manager_or_None) — topic_manager ใช้สำหรับ mark_used หลังรัน"""
    if args.auto:
        tm = TopicManager()
        st = tm.status()
        logger.info(f"Topic queue: {st['used']} ใช้แล้ว | {st['pending']} รอคิว")
        topic = tm.get_next_topic()
        return topic, tm

    if not args.topic:
        logger.error("ต้องระบุ --topic หรือใช้ --auto")
        sys.exit(1)

    return args.topic, None


def _auto_open(result: dict):
    """เปิดวิดีโอ + post_kit.txt อัตโนมัติหลัง pipeline เสร็จ"""
    import subprocess as _sp
    from pathlib import Path
    video = result.get("video_path", "")
    kit   = str(Path(result.get("captions_dir", "")) / "post_kit.txt")
    if video and Path(video).exists():
        _sp.Popen(["open", video])
    if Path(kit).exists():
        _sp.Popen(["open", kit])


def print_result(result: dict):
    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  ชื่อวิดีโอ  : {result['title']}")
    print(f"  Framework   : {result.get('framework', 'list')}")
    print(f"  ความยาว    : {result['duration']} วินาที ({result['sentences']} ประโยค)")
    print(f"  ไฟล์วิดีโอ  : {result['video_path']}")
    if result.get("thumbnail_path"):
        print(f"  Thumbnail   : {result['thumbnail_path']}")
    print(f"  สคริปต์    : {result['script_path']}")
    print(f"  Captions    : {result.get('captions_dir', '')}/")
    print(f"  ซับไตเติ้ล : {result['srt_path']}")
    if result.get("uploads"):
        print("  อัปโหลด    :")
        for platform, url in result["uploads"].items():
            print(f"    {platform}: {url}")
    print(f"{sep}\n")


def main():
    load_dotenv()
    args = parse_args()
    config = load_config(args.config)
    setup_logger(config)
    check_env()

    # ── Series mode: generate topic queue จาก main topic แล้วรัน --auto ──────
    if args.series:
        from src.topic_manager import TopicManager
        tm = TopicManager()
        topics = tm.generate_series(args.series, n=args.series_count)
        if topics:
            logger.info(f"Series '{args.series}': {len(topics)} ตอนอยู่ในคิวแล้ว")
            for i, t in enumerate(topics, 1):
                logger.info(f"  {i}. {t}")
            logger.info("รัน 'python main.py --auto' เพื่อสร้างคลิปตามคิว")
        sys.exit(0)

    pipeline = AutoClipPipeline(config)
    count = args.count if args.auto else 1

    for i in range(count):
        if count > 1:
            logger.info(f"=== คลิปที่ {i+1}/{count} ===")

        topic, topic_manager = _resolve_topic(args)
        logger.info(f"เริ่มสร้างวิดีโอ: {topic}")

        # ── ดึง history context จาก topic_manager ──────────────────────────────
        last_framework  = topic_manager.last_framework()       if topic_manager else ""
        last_hook_types = topic_manager.last_hook_types(n=3)   if topic_manager else []
        last_cta        = topic_manager.last_cta_type()        if topic_manager else ""
        used_subtopics  = topic_manager.recent_subtopics(n=5)  if topic_manager else []

        if args.preview and i == 0:
            logger.info("กำลังสร้างสคริปต์...")
            script_data = pipeline.script_gen.generate(
                topic, args.style, args.duration,
                last_framework=last_framework,
                last_hook_types=last_hook_types,
                last_cta=last_cta,
                used_subtopics=used_subtopics,
            )
            sep = "─" * 52
            print(f"\n{sep}")
            print(f"  TITLE: {script_data['title']}")
            print(f"  VOICE: {script_data.get('voice_gender','auto')}")
            print(sep)
            for j, s in enumerate(script_data["sentences"], 1):
                print(f"  {j:2d}. {s}")
            print(f"{sep}\n")
            ans = input("พอใจสคริปต์ไหม? (Enter=ดำเนินต่อ / n=ยกเลิก): ").strip().lower()
            if ans == "n":
                print("ยกเลิก")
                sys.exit(0)
        else:
            script_data = None

        result = pipeline.run(
            topic=topic,
            style=args.style,
            duration=args.duration,
            background_path=args.background,
            upload=args.upload,
            prefetched_script=script_data,
            last_framework=last_framework,
            last_hook_types=last_hook_types,
            last_cta=last_cta,
            used_subtopics=used_subtopics,
        )

        if topic_manager:
            topic_manager.mark_used(
                topic,
                result.get("title", ""),
                result.get("video_path", ""),
                result.get("framework", ""),
                hook_type=result.get("hook_type", ""),
                cta_type=result.get("cta_type", ""),
                subtopic=result.get("subtopic", ""),
            )

        print_result(result)
        _auto_open(result)


if __name__ == "__main__":
    main()
