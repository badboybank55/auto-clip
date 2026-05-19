"""
Scene-based video builder (ImageMagick subtitle edition)
- แต่ละประโยค = 1 ฉาก มี Pexels video ของตัวเอง
- subtitle render ด้วย ImageMagick (รองรับ Thai font ถูกต้อง)
- ไม่ใช้ PIL per-frame rendering อีกต่อไป
"""

import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# ─── Stat callout detection ───────────────────────────────────────────────────
_STAT_RE = re.compile(
    r'\d{1,3}(?:,\d{3})+(?:\.\d+)?%?'   # comma numbers: 60,000 / 1,500,000
    r'|\d+(?:\.\d+)?\s*%'                # percent: 80% / 4.5%
    r'|\d{2,}(?:\.\d+)?\s*(?:ล้าน|แสน|หมื่น|พัน)(?:บาท)?'  # Thai units
)
_STAT_FONT = Path(__file__).parent.parent / "config" / "Kanit-Bold.ttf"
if not _STAT_FONT.exists():
    _STAT_FONT = Path(__file__).parent.parent / "config" / "Sarabun-Bold.ttf"


def _extract_stat(text: str) -> str:
    """คืนตัวเลขสำคัญแรกในประโยค — ถ้าไม่มีคืน ''"""
    m = _STAT_RE.search(text)
    return m.group().strip() if m else ""

from loguru import logger

from .subtitle_renderer import (
    SubStyle, render_subtitle_png, render_karaoke_png,
    overlay_subtitle_on_clip, fix_thai_digits,
    _make_subtitle_chunks_words,
    _make_subtitle_chunks_v2,
)
from .video_builder import _run, _hex_to_rgb


class SceneBuilder:
    def __init__(self, config: dict):
        cfg = config["video"]
        w, h = cfg["resolution"].split("x")
        self.width    = int(w)
        self.height   = int(h)
        self.fps      = cfg.get("fps", 30)
        self.bg_color_hex = cfg.get("background_color", "#0d0d1a")
        self.bg_color = _hex_to_rgb(self.bg_color_hex)
        export = config.get("export", {})
        requested_codec = export.get("video_codec", "libx264")
        self.vcodec   = self._resolve_codec(requested_codec)
        self.acodec   = export.get("audio_codec", "aac")
        self.crf      = export.get("crf", 18)
        self.is_gpu   = "videotoolbox" in self.vcodec
        self.bg_music_vol = config.get("audio", {}).get("bg_music_volume", 0.15)
        self.style    = SubStyle.from_config(config)

    @staticmethod
    def _resolve_codec(requested: str) -> str:
        """ลอง GPU codec ก่อน — fallback libx264 ถ้าไม่รองรับ"""
        if requested == "libx264":
            return "libx264"
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
             "-c:v", requested, "-f", "null", "-"],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            logger.info(f"Codec: {requested} (GPU) ✓")
            return requested
        logger.warning(f"Codec {requested} ไม่รองรับ → fallback libx264")
        return "libx264"

    def _encode_args(self) -> list:
        """คืน ffmpeg quality args ตาม codec — GPU ใช้ bitrate, CPU ใช้ CRF"""
        if self.is_gpu:
            return ["-c:v", self.vcodec, "-b:v", "8000k", "-maxrate", "10000k"]
        return ["-c:v", self.vcodec, "-crf", str(self.crf)]

    # music volume by framework — ปรับขึ้นให้ได้ยินชัด (voice -18.7 LUFS, music target -24 to -26 LUFS = 25-35%)
    _FRAMEWORK_MUSIC_VOL: dict = {
        "confession":   0.25,   # intimate — softer
        "story":        0.27,
        "before_after": 0.28,
        "deep_dive":    0.28,
        "what_if":      0.30,
        "comparison":   0.30,
        "list":         0.32,
        "myth":         0.32,
        "countdown":    0.35,   # energetic — louder
    }

    # ─── Public ──────────────────────────────────────────────────────────────

    def build(
        self,
        timing_data: list,
        scene_video_paths: list,
        audio_path: str,
        output_path: str,
        bg_music_path: Optional[str] = None,
        framework: str = "",
    ) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = output_path.parent / f".tmp_{output_path.stem}"
        tmp_dir.mkdir(exist_ok=True)

        try:
            # ปรับ music volume ตาม framework
            if framework and framework in self._FRAMEWORK_MUSIC_VOL:
                self.bg_music_vol = self._FRAMEWORK_MUSIC_VOL[framework]
                logger.info(f"Music vol: {framework} → {self.bg_music_vol}")

            # 1. เขียนแต่ละฉาก (silent video + subtitle burned in)
            scene_files = self._write_all_scenes(timing_data, scene_video_paths, tmp_dir)

            # 2. concat ด้วย ffmpeg
            tmp_concat = tmp_dir / "concat.mp4"
            self._ffmpeg_concat(scene_files, str(tmp_concat))

            # 3. ใส่เสียงพากย์
            tmp_voiced = tmp_dir / "voiced.mp4"
            self._add_audio(str(tmp_concat), audio_path, str(tmp_voiced))

            # 4. mix background music
            tmp_mixed = tmp_dir / "mixed.mp4"
            if bg_music_path and Path(bg_music_path).exists():
                self._mix_music(str(tmp_voiced), bg_music_path, str(tmp_mixed))
            else:
                shutil.copy(str(tmp_voiced), str(tmp_mixed))

            # 5. brand card ท้ายวิดีโอ (1.5 วินาที)
            tmp_card = tmp_dir / "with_card.mp4"
            self._append_brand_card(str(tmp_mixed), str(tmp_card))
            src_for_wm = str(tmp_card) if tmp_card.exists() else str(tmp_mixed)

            # 6. watermark overlay
            wm_path = Path(__file__).parent.parent / "assets" / "watermark.png"
            if wm_path.exists():
                self._add_watermark(src_for_wm, str(wm_path), str(output_path))
            else:
                shutil.copy(src_for_wm, str(output_path))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.success(f"Scene video → {output_path}")
        return str(output_path)

    # ─── Scene writing ────────────────────────────────────────────────────────

    def _write_all_scenes(self, timing_data: list, video_paths: list,
                          tmp_dir: Path) -> list:
        # Hard cuts — ไม่มี xfade เพื่อให้ subtitle sync สมบูรณ์ (ไม่มี accumulated drift)
        paths = []
        n = len(timing_data)
        bad_scenes = []
        for i, item in enumerate(timing_data):
            bg = video_paths[i % len(video_paths)] if video_paths else None
            out = str(tmp_dir / f"scene_{i:04d}.mp4")
            dur = self._scene_duration(timing_data, i)
            text = fix_thai_digits(item["text"])
            word_timings = item.get("word_timings", [])
            logger.info(f"  Scene {i+1}/{n}: «{text[:30]}» ({dur:.2f}s | {len(word_timings)} words)")
            all_valid = [vp for vp in (video_paths or []) if vp and Path(vp).exists()]
            alt_pool  = [vp for vp in all_valid if vp != bg]
            scene_role = "hook" if i == 0 else ("cta" if i == n - 1 else "body")
            self._write_scene(text, bg, dur, out, tmp_dir,
                              word_timings=word_timings,
                              alt_video_paths=alt_pool, scene_role=scene_role)

            out_path = Path(out)
            if not out_path.exists() or out_path.stat().st_size < 80_000:
                logger.error(f"  QC FAIL scene {i+1}: ไฟล์เสีย — ลอง video อื่น")
                alt_bg = next((vp for vp in (video_paths or []) if vp and vp != bg
                               and Path(vp).exists()), None)
                self._write_scene(text, alt_bg, dur, out, tmp_dir,
                                  word_timings=word_timings, scene_role=scene_role)
                if not Path(out).exists() or Path(out).stat().st_size < 10_000:
                    self._prepare_bg(None, dur, out)
                bad_scenes.append(i + 1)

            paths.append(out)

        if bad_scenes:
            logger.warning(f"QC: rebuilt {len(bad_scenes)} bad scenes: {bad_scenes}")
        else:
            logger.success(f"QC: ทุก scene ผ่าน ({n}/{n})")
        return paths

    def _scene_duration(self, timing_data: list, i: int) -> float:
        if i < len(timing_data) - 1:
            return timing_data[i + 1]["start"] - timing_data[i]["start"]
        return timing_data[i]["duration"] + 0.5

    def _write_scene(self, text: str, bg_path: Optional[str],
                     duration: float, output: str, tmp_dir: Path,
                     word_timings: list = None,
                     alt_video_paths: list = None, scene_role: str = "body") -> bool:
        """Returns True ถ้าได้ real video, False ถ้า solid color"""
        tmp_bg = str(tmp_dir / f"bg_{Path(output).stem}.mp4")
        video_ok = self._prepare_bg(bg_path, duration, tmp_bg)

        # ถ้าล้มเหลว → ลอง alt videos จาก pool ทั้งหมด
        if not video_ok and alt_video_paths:
            for alt in alt_video_paths:
                if alt and Path(alt).exists():
                    video_ok = self._prepare_bg(alt, duration, tmp_bg)
                    if video_ok:
                        logger.info(f"  ↳ bg fallback: {Path(alt).name}")
                        break

        if not video_ok:
            logger.warning(f"  ⚠ solid color — ทุก video ใน pool ล้มเหลว")

        # Hook = ใหญ่ขึ้น 10%, CTA = สีเหลืองทอง, body = ปกติ
        from dataclasses import replace as _dc_replace
        if scene_role == "hook":
            scene_style = _dc_replace(self.style, font_size=int(self.style.font_size * 1.1))
        elif scene_role == "cta":
            scene_style = _dc_replace(self.style, color="#FFD700")
        else:
            scene_style = self.style

        if word_timings and len(word_timings) >= 1:
            self._overlay_word_sync(word_timings, tmp_bg, output, tmp_dir,
                                    duration,
                                    style=scene_style,
                                    full_text=text, is_hook=(scene_role == "hook"))
        else:
            # ไม่มี timing → subtitle คงที่
            sub_png = str(tmp_dir / f"sub_{Path(output).stem}.png")
            ok = render_subtitle_png(text, self.width, self.height, scene_style, sub_png)
            if ok and Path(sub_png).exists():
                overlay_subtitle_on_clip(tmp_bg, sub_png, output, encode_args=self._encode_args())
            else:
                shutil.copy(tmp_bg, output)
            if Path(sub_png).exists():
                os.unlink(sub_png)

        if Path(tmp_bg).exists():
            os.unlink(tmp_bg)

        # Stat callout removed — ตัวเลขซ้ำกับซับไตเติ้ล ทำให้สับสน

        return video_ok

    def _overlay_word_sync(self, word_timings: list, bg_path: str,
                           output: str, tmp_dir: Path, duration: float,
                           style=None, full_text: str = "", is_hook: bool = False):
        """
        @peatudrink style subtitle:
        - chunk ≤ 5 พยางค์
        - ตัวเลข/% → keyword chunk: สีตาม context (red/green/yellow), 72px static
        - normal chunk: karaoke word-by-word highlight, 58px
        - is_hook=True: แสดง full text 2 บรรทัดที่ t=0 สำหรับ thumbnail
        """
        stem = Path(output).stem

        active_style = style if style is not None else self.style
        chunks = _make_subtitle_chunks_v2(word_timings, max_syllables=5)
        if not chunks:
            shutil.copy(bg_path, output)
            return

        all_overlays = []  # [(png_path, show_start, show_end)]

        for c_idx, chunk in enumerate(chunks):
            chunk_words = chunk["words"]
            words       = [w for w, _, _ in chunk_words]
            is_keyword  = chunk["is_keyword"]
            kw_color    = chunk["color"] if is_keyword else None
            fsize       = chunk["font_size"]

            # adj_start = word relative time ภายใน scene (ไม่มี xfade offset)
            adj_start = float(chunk_words[0][1])
            # scene 0 (hook) chunk แรก: เริ่ม subtitle ไม่เร็วกว่า 0.07s → thumbnail สะอาด
            if is_hook and c_idx == 0:
                adj_start = max(adj_start, 0.07)
            adj_start = min(adj_start, max(0.0, duration - 0.05))

            # adj_end: chunk นี้แสดงจนถึง chunk ถัดไปเริ่ม (ต่อเนื่อง ไม่มี dead air)
            if c_idx < len(chunks) - 1:
                next_word_start = float(chunks[c_idx + 1]["words"][0][1])
                adj_end = min(next_word_start, duration)
            else:
                adj_end = duration

            if adj_start >= adj_end or adj_end <= 0:
                adj_start = max(0.0, adj_end - 0.1)
            if adj_start >= adj_end:
                continue

            # ทุก chunk ใช้ static white เหมือนกันหมด: 1 layout, 1 outline, 1 backdrop
            png = str(tmp_dir / f"karaoke_{stem}_{len(all_overlays):04d}.png")
            ok  = render_karaoke_png(words, 0, self.width, self.height, active_style, png,
                                     chunk_color="#FFFFFF", font_size_override=fsize)
            if ok and Path(png).exists():
                all_overlays.append((png, adj_start, adj_end))

        if not all_overlays:
            shutil.copy(bg_path, output)
            return

        cmd = ["ffmpeg", "-y", "-i", bg_path]
        for png, _, _ in all_overlays:
            cmd += ["-loop", "1", "-t", str(duration), "-i", png]

        filters, prev = [], "0:v"
        for i, (_, start, end) in enumerate(all_overlays):
            out_v = f"cv{i}"
            filters.append(
                f"[{prev}][{i+1}:v]overlay=0:0:"
                f"enable='gte(t,{start:.3f})*lt(t,{end:.3f})'[{out_v}]"
            )
            prev = out_v

        cmd += [
            "-filter_complex", ";".join(filters),
            "-map", f"[{prev}]",
            "-t", str(duration),
            *self._encode_args(),
            "-an", output,
        ]
        _run(cmd, "karaoke subtitle overlay")

        for png, _, _ in all_overlays:
            if Path(png).exists():
                os.unlink(png)

    def _prepare_bg(self, bg_path: Optional[str], duration: float, output: str):
        """ffmpeg: scale+crop+Ken Burns → fallback simple scale → fallback solid color"""
        w, h, fps = self.width, self.height, self.fps
        frames = max(int(duration * fps), 1)

        if bg_path and Path(bg_path).exists():
            src_size = Path(bg_path).stat().st_size
            src_has_video = self._has_video_stream(bg_path)
            if src_size < 500_000 or not src_has_video:
                logger.warning(f"bg source เล็กเกิน ({src_size//1024}KB) หรือไม่มี video stream → ข้าม")
            else:
                # ใช้ natural video motion — ไม่มี zoompan (ทำให้ดูเหมือนภาพนิ่งซูม)
                grade = (
                    "format=yuv420p,"
                    "eq=contrast=1.08:saturation=1.12:gamma=0.98,"
                    "colorbalance=rm=0.02:gm=0.01:bm=-0.02,"
                    "vignette=PI/9,"
                    "unsharp=3:3:0.3:3:3:0.1"
                )
                vf_primary = (
                    f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{h},fps={fps},{grade}"
                )
                vf_raw  = f"scale={w}:{h},fps={fps},{grade}"
                vf_bare = f"scale={w}:{h},fps={fps},format=yuv420p"

                for vf, label in [
                    (vf_primary, "natural"),
                    (vf_raw,     "raw-scale"),
                    (vf_bare,    "bare-scale"),
                ]:
                    cmd = [
                        "ffmpeg", "-y",
                        "-stream_loop", "-1", "-i", bg_path,
                        "-t", str(duration),
                        "-vf", vf,
                        "-pix_fmt", "yuv420p",
                        *self._encode_args(),
                        "-an", output,
                    ]
                    res = _run(cmd, f"bg ({label})", check=False)
                    out_ok = (res.returncode == 0
                              and Path(output).exists()
                              and Path(output).stat().st_size > 80_000
                              and self._get_duration(output) >= duration * 0.4)
                    if out_ok:
                        return True
                    logger.warning(f"bg {label} failed → next")

        # solid color fallback (ไม่มีวิดีโอ หรือทุก attempt ล้มเหลว)
        r, g, b = self.bg_color
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x{r:02x}{g:02x}{b:02x}:s={w}x{h}:r={fps}",
            "-t", str(duration),
            *self._encode_args(),
            "-an", output,
        ], "prepare bg (color)")
        return False  # solid color = ไม่มีวิดีโอจริง

    # ─── ffmpeg pipeline ──────────────────────────────────────────────────────

    def _render_stat_callout(self, stat_text: str, output_png: str) -> bool:
        """สร้าง PNG ตัวเลขใหญ่สีทอง สำหรับ overlay บนหน้าจอ"""
        font_arg = ["-font", str(_STAT_FONT)] if _STAT_FONT.exists() else []
        cmd = [
            "convert",
            "-size", f"{self.width}x200",
            "xc:transparent",
            *font_arg,
            "-pointsize", "110",
            "-fill", "#d4a843",
            "-stroke", "#000000",
            "-strokewidth", "4",
            "-gravity", "Center",
            "-annotate", "+0+0", stat_text,
            output_png,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return r.returncode == 0 and Path(output_png).exists()

    def _add_stat_callout_to_scene(self, scene_path: str, stat_text: str,
                                   duration: float, tmp_dir: Path, output: str):
        """Overlay stat callout บนครึ่งบนของฉาก — แสดงช่วง 0.3-2.5 วินาที"""
        png = str(tmp_dir / f"stat_{Path(scene_path).stem}.png")
        if not self._render_stat_callout(stat_text, png):
            shutil.copy(scene_path, output)
            return

        show_end = min(2.5, duration - 0.1)
        y_pos    = int(self.height * 0.18)   # 18% จากบนลงมา

        cmd = [
            "ffmpeg", "-y",
            "-i", scene_path,
            "-loop", "1", "-t", str(duration), "-i", png,
            "-filter_complex",
            f"[1:v]format=rgba[stat];"
            f"[0:v][stat]overlay=(W-w)/2:{y_pos}:"
            f"enable='between(t,0.3,{show_end:.2f})'",
            *self._encode_args(),
            "-an", output,
        ]
        r = _run(cmd, "stat callout overlay", check=False)
        if r.returncode != 0 or not Path(output).exists():
            shutil.copy(scene_path, output)
        if Path(png).exists():
            os.unlink(png)

    def _append_brand_card(self, video: str, output: str, duration: float = 1.5):
        """ต่อท้ายวิดีโอด้วย brand card สีดำ 1.5 วินาที — โลโก้ + follow text"""
        font_cfg = Path(__file__).parent.parent / "config"
        font_path = next(
            (str(p) for p in [font_cfg / "Kanit-Bold.ttf", font_cfg / "Sarabun-Bold.ttf"]
             if p.exists()), None
        )
        wm = Path(__file__).parent.parent / "assets" / "watermark.png"

        # สร้าง card video (silent black + text)
        card_tmp = output.replace(".mp4", "_card_raw.mp4")
        vf_parts = [
            f"color=c=black:s={self.width}x{self.height}:d={duration}:r={self.fps}[base]",
        ]
        overlays = "[base]"
        inputs = []

        if wm.exists():
            inputs += ["-i", str(wm)]
            overlays += f"[{len(inputs)//2}:v]overlay=(W-w)/2:(H-h)/2-120[v1]"
            vf_parts.append(overlays)
            overlays = "[v1]"
        else:
            vf_parts.append(f"{overlays}copy[v1]")
            overlays = "[v1]"

        font_arg = f":fontfile={font_path}" if font_path else ""
        vf_parts.append(
            f"{overlays}drawtext=text='กด Follow ไว้ก่อน'"
            f"{font_arg}:fontsize=52:fontcolor=white:x=(w-text_w)/2:y=(h+200)/2,"
            f"drawtext=text='มีเรื่องการเงินทุกวัน'"
            f"{font_arg}:fontsize=36:fontcolor=#d4a843:x=(w-text_w)/2:y=(h+300)/2[out]"
        )

        card_cmd = ["ffmpeg", "-y",
                    "-f", "lavfi", "-i", f"color=c=black:s={self.width}x{self.height}:d={duration}:r={self.fps}",
                    *inputs,
                    "-filter_complex", "; ".join(vf_parts) if inputs else
                        f"[0:v]drawtext=text='กด Follow ไว้ก่อน'"
                        f"{font_arg}:fontsize=52:fontcolor=white:x=(w-text_w)/2:y=(h-120)/2,"
                        f"drawtext=text='มีเรื่องการเงินทุกวัน'"
                        f"{font_arg}:fontsize=36:fontcolor=#d4a843:x=(w-text_w)/2:y=(h+20)/2[out]",
                    "-map", "[out]" if not inputs else "[out]",
                    "-an", *self._encode_args(),
                    "-t", str(duration), card_tmp]
        # simplify: always use no-image version (reliable)
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={self.width}x{self.height}:d={duration}:r={self.fps}",
            "-vf",
            f"drawtext=text='กด Follow ไว้ก่อน'{font_arg}"
            f":fontsize=56:fontcolor=white:x=(w-text_w)/2:y=(h/2)-60,"
            f"drawtext=text='เงินงอก — มีเรื่องการเงินทุกวัน'{font_arg}"
            f":fontsize=34:fontcolor=#d4a843:x=(w-text_w)/2:y=(h/2)+20",
            "-an", *self._encode_args(),
            "-t", str(duration), card_tmp,
        ], "brand card", check=False)

        if not Path(card_tmp).exists():
            return  # ล้มเหลว → ข้ามได้

        # concat main + card
        concat_list = output.replace(".mp4", "_concat.txt")
        with open(concat_list, "w") as f:
            f.write(f"file '{Path(video).resolve()}'\n")
            f.write(f"file '{Path(card_tmp).resolve()}'\n")

        r = _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy", output,
        ], "append brand card", check=False)

        Path(concat_list).unlink(missing_ok=True)
        Path(card_tmp).unlink(missing_ok=True)

        if not Path(output).exists() or Path(output).stat().st_size < 10_000:
            shutil.copy(video, output)   # fallback

    def _add_watermark(self, video: str, watermark_png: str, output: str,
                       margin: int = 30, opacity: float = 0.6):
        """Overlay watermark PNG มุมขวาบน — opacity 60%, margin 30px"""
        _run([
            "ffmpeg", "-y",
            "-i", video,
            "-i", watermark_png,
            "-filter_complex",
            f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];"
            f"[0:v][wm]overlay={margin}:{margin}:format=auto",
            *self._encode_args(),
            "-c:a", "copy",
            output,
        ], "add watermark")

    def _ffmpeg_concat(self, scene_files: list, output: str):
        """Hard cut concat — ไม่มี xfade เพื่อให้ subtitle sync สมบูรณ์"""
        if len(scene_files) == 1:
            shutil.copy(scene_files[0], output)
            return

        # เขียน concat list แล้วใช้ -c copy (fast, no re-encode)
        concat_list = output.replace(".mp4", "_concat_list.txt")
        with open(concat_list, "w") as f:
            for sf in scene_files:
                f.write(f"file '{Path(sf).resolve()}'\n")

        try:
            r = _run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:v", "copy",
                "-an", output,
            ], "hard cut concat (copy)", check=False)

            ok = (r.returncode == 0
                  and Path(output).exists()
                  and Path(output).stat().st_size > 100_000)
            if not ok:
                # fallback: re-encode (slower แต่ reliable กว่า)
                logger.warning("concat copy ล้มเหลว → re-encode")
                _run([
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_list,
                    *self._encode_args(),
                    "-an", output,
                ], "hard cut concat (re-encode)")
        finally:
            Path(concat_list).unlink(missing_ok=True)

    def _add_audio(self, video: str, audio: str, output: str):
        _run([
            "ffmpeg", "-y",
            "-i", video, "-i", audio,
            "-c:v", "copy", "-c:a", self.acodec,
            "-shortest", output,
        ], "add audio")

    def _get_duration(self, path: str) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        try:
            return float(result.stdout.strip())
        except Exception:
            return 60.0

    def _has_video_stream(self, path: str) -> bool:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        return "video" in result.stdout

    def _mix_music(self, video: str, music: str, output: str):
        vol = self.bg_music_vol
        dur = self._get_duration(video)
        fade_out_start = max(0.0, dur - 2.0)
        # Simple amix — normalize=0 รักษา relative volume ระหว่าง voice และ music
        # ไม่ใช้ loudnorm (มันกด music ให้หายไป) ไม่ใช้ sidechaincompress (ซับซ้อนเกิน)
        _run([
            "ffmpeg", "-y",
            "-i", video,
            "-stream_loop", "-1", "-i", music,
            "-filter_complex",
            f"[0:a]volume=1.0[voice];"
            f"[1:a]volume={vol},"
            f"afade=t=in:st=0:d=1.5,"
            f"afade=t=out:st={fade_out_start:.3f}:d=2.0[music];"
            f"[voice][music]amix=inputs=2:duration=first:normalize=0[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", self.acodec, output,
        ], "mix music")
