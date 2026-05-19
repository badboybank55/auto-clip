import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import PIL.Image
# Pillow 10+ removed ANTIALIAS — patch before moviepy imports it
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

import numpy as np
from loguru import logger
from moviepy.editor import ColorClip, VideoFileClip, ImageClip
from PIL import Image, ImageDraw, ImageFont


VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
FONT_PATH  = Path(__file__).parent.parent / "config" / "NotoSansThai-Regular.ttf"

# แปลงเลขไทย → อาหรับ (ใช้ทุกจุดที่แสดงผลซับ)
_THAI_DIGIT_TABLE = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


# ─── Subtitle style dataclass ────────────────────────────────────────────────

@dataclass
class SubtitleStyle:
    max_chars: int = 25
    color: Tuple[int, ...] = (255, 255, 255, 255)      # ขาว
    stroke_color: Tuple[int, ...] = (0, 0, 0, 255)     # ขอบดำ
    stroke_width: int = 4
    position_pct: float = 0.58    # 0=บนสุด 1=ล่างสุด (0.58 = ใต้กึ่งกลางเล็กน้อย)
    bg_opacity: int = 0           # 0 = ไม่มีพื้นหลัง

    @classmethod
    def from_config(cls, cfg: dict) -> "SubtitleStyle":
        sub = cfg.get("subtitle", {})
        raw_color  = sub.get("color", "#FFFFFF")
        raw_stroke = sub.get("stroke_color", "#000000")
        return cls(
            max_chars    = int(sub.get("max_chars_per_line", 25)),
            color        = _hex_to_rgba(raw_color),
            stroke_color = _hex_to_rgba(raw_stroke),
            stroke_width = int(sub.get("stroke_width", 4)),
            position_pct = float(sub.get("position_pct", 0.58)),
            bg_opacity   = int(sub.get("bg_opacity", 0)),
        )


def _hex_to_rgba(h: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return (r, g, b, alpha)


# ─── Subtitle text helpers ────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """เลขไทย → อาหรับ ทุกตัวก่อน render"""
    return text.translate(_THAI_DIGIT_TABLE)


def _wrap(text: str, max_chars: int) -> list:
    """
    ตัดข้อความให้ไม่เกิน max_chars ต่อบรรทัด
    ตัดที่ช่องว่างก่อน ถ้าไม่มีก็ตัดตรง
    คืน list ของบรรทัด
    """
    text = _normalize(text).strip()
    if len(text) <= max_chars:
        return [text]

    lines = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        lines.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        lines.append(text)
    return lines


# ─── Core renderer ────────────────────────────────────────────────────────────

def _render_subtitle_on_frame(
    frame: np.ndarray,
    text: str,
    font: ImageFont.FreeTypeFont,
    canvas_w: int,
    style: SubtitleStyle,
) -> np.ndarray:
    """
    วาดซับไตเติ้ลลงบนเฟรม
    - normalize เลขไทย → อาหรับ
    - word-wrap ≤ max_chars
    - stroke ขอบดำชัดเจน
    - วางตำแหน่งตาม position_pct
    - background box เสริม (ถ้า bg_opacity > 0)
    """
    lines = _wrap(text, style.max_chars)
    canvas_h = frame.shape[0]

    img = Image.fromarray(frame, "RGB").convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ── วัดขนาดทุกบรรทัด ──────────────────────────────────────────────────────
    line_gap = 10
    sizes = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        sizes.append((bb[2] - bb[0], bb[3] - bb[1]))

    max_w = max(w for w, _ in sizes) if sizes else 0
    total_h = sum(h for _, h in sizes) + line_gap * (len(lines) - 1)
    pad_x, pad_y = 24, 14

    # ── ตำแหน่ง Y กึ่งกลางแนวตั้งตาม position_pct ────────────────────────────
    block_h = total_h + pad_y * 2
    block_w = max_w + pad_x * 2
    bx = (canvas_w - block_w) // 2
    by = int(canvas_h * style.position_pct) - block_h // 2

    # clamp ไม่ให้เกินขอบ
    by = max(20, min(by, canvas_h - block_h - 20))

    # ── พื้นหลัง (optional) ────────────────────────────────────────────────────
    if style.bg_opacity > 0:
        draw.rounded_rectangle(
            [bx, by, bx + block_w, by + block_h],
            radius=12,
            fill=(0, 0, 0, style.bg_opacity),
        )

    # ── วาดข้อความพร้อม stroke ────────────────────────────────────────────────
    ty = by + pad_y
    sw = style.stroke_width

    for (tw, th), line in zip(sizes, lines):
        tx = bx + (block_w - tw) // 2  # กึ่งกลางแต่ละบรรทัด

        # stroke: วนรอบทุกจุดใน radius sw
        for dx in range(-sw, sw + 1):
            for dy in range(-sw, sw + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((tx + dx, ty + dy), line,
                          font=font, fill=style.stroke_color)

        # ข้อความหลัก
        draw.text((tx, ty), line, font=font, fill=style.color)
        ty += th + line_gap

    return np.array(Image.alpha_composite(img, overlay).convert("RGB"))


# ─── VideoBuilder (single-video mode) ────────────────────────────────────────

class VideoBuilder:
    def __init__(self, config: dict):
        cfg = config["video"]
        w, h = cfg["resolution"].split("x")
        self.width  = int(w)
        self.height = int(h)
        self.fps    = cfg.get("fps", 30)
        self.bg_color = _hex_to_rgb(cfg.get("background_color", "#0d0d1a"))
        export = config.get("export", {})
        self.vcodec = export.get("video_codec", "libx264")
        self.acodec = export.get("audio_codec", "aac")
        self.crf    = export.get("crf", 20)
        self.bg_music_vol = config.get("audio", {}).get("bg_music_volume", 0.12)
        self.font_size = cfg.get("font_size", 72)
        self.style = SubtitleStyle.from_config(config)

        if FONT_PATH.exists():
            self._font = ImageFont.truetype(str(FONT_PATH), self.font_size)
        else:
            logger.warning(f"Thai font not found: {FONT_PATH}")
            self._font = ImageFont.load_default()

    def build(
        self,
        timing_data: list,
        ass_path: str,
        audio_path: str,
        output_path: str,
        background_path: Optional[str] = None,
        bg_music_path: Optional[str] = None,
    ) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_duration = timing_data[-1]["end"] + 0.5

        tmp_bg  = output_path.with_stem(output_path.stem + "_tmp_bg")
        tmp_mux = output_path.with_stem(output_path.stem + "_tmp_mux")

        try:
            self._make_background(total_duration, tmp_bg, background_path)
            self._mux_audio(str(tmp_bg), audio_path, str(tmp_mux),
                            total_duration, bg_music_path)
            self._render_subtitles(str(tmp_mux), timing_data, str(output_path))
        finally:
            for f in [tmp_bg, tmp_mux]:
                if Path(str(f)).exists():
                    Path(str(f)).unlink()

        logger.success(f"Video ready → {output_path}")
        return str(output_path)

    def _make_background(self, duration: float, output: Path,
                         bg_path: Optional[str]):
        size = (self.width, self.height)
        if bg_path and Path(bg_path).exists():
            suffix = Path(bg_path).suffix.lower()
            if suffix in VIDEO_EXTS:
                clip = _fit_and_crop(VideoFileClip(bg_path), size)
                if clip.duration < duration:
                    from moviepy.editor import concatenate_videoclips
                    reps = int(duration / clip.duration) + 2
                    clip = concatenate_videoclips([clip] * reps)
                clip = clip.subclip(0, duration)
            elif suffix in IMAGE_EXTS:
                clip = ImageClip(bg_path).resize(size).set_duration(duration)
            else:
                clip = ColorClip(size=size, color=self.bg_color, duration=duration)
        else:
            clip = ColorClip(size=size, color=self.bg_color, duration=duration)

        clip.write_videofile(str(output), fps=self.fps, audio=False, logger=None)

    def _mux_audio(self, video: str, voice: str, output: str,
                   duration: float, music: Optional[str]):
        if music and Path(music).exists():
            vol = self.bg_music_vol
            cmd = [
                "ffmpeg", "-y", "-i", video, "-i", voice,
                "-stream_loop", "-1", "-i", music,
                "-filter_complex",
                f"[1:a]volume=1.0[v];[2:a]volume={vol}[m];"
                f"[v][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", self.acodec, "-t", str(duration), output,
            ]
        else:
            cmd = ["ffmpeg", "-y", "-i", video, "-i", voice,
                   "-c:v", "copy", "-c:a", self.acodec, "-t", str(duration), output]
        _run(cmd, "mux")

    def _render_subtitles(self, video_path: str, timing_data: list, output_path: str):
        segments = [(d["start"], d["end"], d["text"]) for d in timing_data]
        font  = self._font
        style = self.style
        w     = self.width

        def _active(t):
            for s, e, txt in segments:
                if s <= t <= e:
                    return txt
            return None

        def _draw(get_frame, t):
            frame = get_frame(t)
            text = _active(t)
            if not text:
                return frame
            return _render_subtitle_on_frame(frame, text, font, w, style)

        logger.info("Rendering subtitles (PIL)…")
        video = VideoFileClip(video_path)
        video.fl(_draw, apply_to=["video"]).write_videofile(
            output_path, fps=self.fps, codec=self.vcodec,
            audio_codec=self.acodec,
            ffmpeg_params=["-crf", str(self.crf), "-movflags", "+faststart"],
            logger=None,
        )


# ─── Shared helpers (imported by scene_builder) ───────────────────────────────

def _fit_and_crop(clip: VideoFileClip, size: tuple) -> VideoFileClip:
    tw, th = size
    vw, vh = clip.size
    scale = max(tw / vw, th / vh)
    nw, nh = int(vw * scale), int(vh * scale)
    clip = clip.resize((nw, nh))
    return clip.crop(x1=(nw - tw) // 2, y1=(nh - th) // 2,
                     x2=(nw - tw) // 2 + tw, y2=(nh - th) // 2 + th)


def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _run(cmd: list, label: str, check: bool = True):
    logger.debug(f"ffmpeg [{label}]")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        logger.error(f"ffmpeg error:\n{result.stderr[-600:]}")
        raise RuntimeError(f"ffmpeg failed: {label}")
    return result
