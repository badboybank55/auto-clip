"""
Channel Intro Bumper — Gold Luxury Edition
Brand: เงินงอก  |  Navy #0d1728 + Gold #C9A84C

Animation:
  0.00–0.25s  Navy cinematic overlay fades in
  0.20–0.35s  Gold ring burst explodes outward
  0.25–0.95s  Logo reveals — elastic spring + chromatic aberration
  0.30–0.80s  Gold sparkle particles shoot out
  0.80–2.20s  Hold — rays rotate, particles twinkle, ring pulses, logo bobs
  0.90–1.30s  Channel name fades in (stagger)
  1.15–1.55s  Handle fades in (stagger)
  2.20–2.80s  Gold flash burst → everything fades → video resumes
"""

import json
import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from loguru import logger

_FONTS   = Path(__file__).parent.parent / "config"
_ASSETS  = Path(__file__).parent.parent / "assets"
_PROFILE = _ASSETS / "profile.jpg"

_FPS      = 30
_DURATION = 3.2   # seconds

# Brand colors
_NAVY   = (13,  23,  40)    # #0d1728
_GOLD   = (201, 168, 76)    # #C9A84C  (logo border gold)
_BRIGHT_GOLD = (255, 215, 0)  # #FFD700  (sparkles)
_CHAMPAGNE   = (232, 212, 168)  # #E8D4A8  (soft particles)


# ─── Easing ──────────────────────────────────────────────────────────────────

def _ease_out_elastic(t: float) -> float:
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1

def _ease_in_quad(t: float) -> float:
    return t * t

def _ease_out_cubic(t: float) -> float:
    return 1 - math.pow(1 - t, 3)


# ─── Logo ─────────────────────────────────────────────────────────────────────

def _load_circle_logo(logo_path: str, size: int) -> Image.Image:
    src = logo_path if Path(logo_path).exists() else str(_PROFILE)
    img = Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    return out


# ─── Effect helpers ───────────────────────────────────────────────────────────

def _draw_rays(frame: Image.Image, cx: int, cy: int, intensity: float, angle_off: float):
    """Rotating light rays radiating from center."""
    W, H = frame.size
    ray = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d   = ImageDraw.Draw(ray)
    n   = 20
    for i in range(n):
        a     = 2 * math.pi * i / n + angle_off
        vary  = 0.5 + 0.5 * math.sin(a * 2.3)
        rlen  = int(max(W, H) * (0.55 + 0.25 * vary))
        alpha = int(22 * intensity * vary)
        if alpha < 2:
            continue
        ex = int(cx + math.cos(a) * rlen)
        ey = int(cy + math.sin(a) * rlen)
        d.line([(cx, cy), (ex, ey)], fill=(*_GOLD, alpha), width=4)
    frame.alpha_composite(ray.filter(ImageFilter.GaussianBlur(5)))


def _draw_ring(frame: Image.Image, cx: int, cy: int, radius: float, alpha: int, width: int = 3):
    """Single gold ring."""
    d = ImageDraw.Draw(frame)
    r = int(radius)
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              outline=(*_BRIGHT_GOLD, alpha), width=width)


def _draw_sparkle(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple):
    """4-point star sparkle."""
    for i in range(4):
        a  = i * math.pi / 2
        ex = int(cx + math.cos(a) * size)
        ey = int(cy + math.sin(a) * size)
        draw.line([(cx, cy), (ex, ey)], fill=color,
                  width=max(1, size // 3))
    r = max(1, size // 4)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def _chroma_shift(logo_img: Image.Image, shift: int) -> Image.Image:
    """RGB channel split: red shifts right, blue shifts left."""
    arr = np.array(logo_img, dtype=np.uint8)
    out = arr.copy()
    if shift > 0:
        out[:, shift:, 0]  = arr[:, :-shift, 0]   # red → right
        out[:, :-shift, 2] = arr[:, shift:, 2]    # blue → left
    return Image.fromarray(out)


# ─── Frame renderer ───────────────────────────────────────────────────────────

def _render_intro_frames(
    logo_path: str, channel_name: str, handle: str, W: int, H: int,
) -> str:
    """Render Gold Luxury intro. Returns path to temp MOV with RGBA alpha."""

    # Particle system (deterministic seed)
    rng = random.Random(777)
    N_BURST  = 30   # explosion particles
    N_TWINKLE = 18  # ambient twinkling particles

    burst_particles = [(
        rng.uniform(-math.pi, math.pi),   # angle
        rng.uniform(0.25, 0.90),          # speed (0–1 relative to half-width)
        rng.uniform(4, 9),                # sparkle arm size
        rng.uniform(0, 0.20),             # delay
        rng.choice([_BRIGHT_GOLD, _CHAMPAGNE]),
    ) for _ in range(N_BURST)]

    twinkle_particles = [(
        rng.randint(-W//3, W//3),   # offset x from center
        rng.randint(-H//4, H//4),   # offset y from center
        rng.uniform(2, 6),           # sparkle size
        rng.uniform(0, 2.0),         # phase offset for sin
        rng.uniform(0.5, 1.5),       # frequency
    ) for _ in range(N_TWINKLE)]

    # Logo sizes
    LOGO_MAX   = int(W * 0.68)
    LOGO_FINAL = int(W * 0.50)

    # Font
    try:
        font_name   = ImageFont.truetype(str(_FONTS / "Sarabun-Bold.ttf"),    int(H * 0.046))
        font_handle = ImageFont.truetype(str(_FONTS / "Sarabun-Regular.ttf"), int(H * 0.031))
    except Exception:
        font_name = font_handle = ImageFont.load_default()

    logo_cache: dict[int, Image.Image] = {}
    def get_logo(size: int) -> Image.Image:
        s = max(10, size)
        if s not in logo_cache:
            logo_cache[s] = _load_circle_logo(logo_path, s)
        return logo_cache[s]

    # Timings
    DARK_IN       = 0.25
    RING_BURST    = 0.22
    RING_BURST_DUR = 0.55
    LOGO_START    = 0.25
    LOGO_END      = 0.95
    PARTICLE_START = 0.28
    NAME_START    = 0.90
    NAME_END      = 1.30
    HANDLE_START  = 1.15
    HANDLE_END    = 1.55
    BOB_START     = 1.30
    BOB_END       = 2.25
    EXIT_START    = 2.25
    FLASH_PEAK    = 2.50
    FADE_END      = _DURATION

    logo_cx = W // 2
    logo_cy = int(H * 0.42)

    n_frames  = int(_DURATION * _FPS) + 2
    frame_dir = Path(tempfile.mkdtemp())
    logger.info(f"Gold Luxury intro: {n_frames} frames ({_DURATION}s @ {_FPS}fps)…")

    for idx in range(n_frames):
        t     = idx / _FPS
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        # ── 1. Navy cinematic overlay ─────────────────────────────────────────
        if t < DARK_IN:
            dark_a = int(210 * _ease_out_cubic(t / DARK_IN))
        elif t < EXIT_START:
            dark_a = 210
        elif t < FLASH_PEAK:
            # Brighten toward white for exit flash
            prog   = (t - EXIT_START) / (FLASH_PEAK - EXIT_START)
            dark_a = 210
            white  = int(255 * _ease_in_quad(prog))
            frame.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, white)))
        elif t < FADE_END:
            prog   = (t - FLASH_PEAK) / (FADE_END - FLASH_PEAK)
            dark_a = int(210 * (1 - prog))
        else:
            dark_a = 0

        if dark_a > 0:
            frame.alpha_composite(Image.new("RGBA", (W, H), (*_NAVY, dark_a)))

        # ── Content visibility ────────────────────────────────────────────────
        if t >= FADE_END:
            frame.save(str(frame_dir / f"f{idx:04d}.png"))
            continue
        if t > EXIT_START:
            content_a = max(0.0, 1.0 - (t - EXIT_START) / (FLASH_PEAK - EXIT_START))
        else:
            content_a = 1.0

        # ── 2. Light rays (rotate behind logo) ───────────────────────────────
        if LOGO_START + 0.3 < t < EXIT_START and content_a > 0:
            ray_prog = min(1.0, (t - (LOGO_START + 0.3)) / 0.5)
            ray_int  = ray_prog * content_a * 0.85
            angle_off = t * 0.35  # slow rotation
            _draw_rays(frame, logo_cx, logo_cy, ray_int, angle_off)

        # ── 3. Expanding gold rings ───────────────────────────────────────────
        # Initial burst ring (fires once)
        if RING_BURST < t < RING_BURST + RING_BURST_DUR:
            prog = (t - RING_BURST) / RING_BURST_DUR
            r    = int((LOGO_FINAL // 2 + 15) + prog * W * 0.45)
            a    = int(220 * (1 - prog) * content_a)
            w    = max(2, int(6 * (1 - prog * 0.65)))
            _draw_ring(frame, logo_cx, logo_cy, r, a, w)

        # Periodic pulse rings during hold (every 1.0s)
        if BOB_START < t < BOB_END:
            for ring_t0 in [BOB_START, BOB_START + 1.0]:
                rt = t - ring_t0
                if 0 < rt < 0.9:
                    prog = rt / 0.9
                    r = int(LOGO_FINAL // 2 + 8 + prog * W * 0.18)
                    a = int(140 * (1 - prog) * content_a)
                    _draw_ring(frame, logo_cx, logo_cy, r, a, 2)

        # ── 4. Burst sparkle particles ────────────────────────────────────────
        if t > PARTICLE_START and content_a > 0:
            spark_draw = ImageDraw.Draw(frame)
            for angle, speed, sz, delay, color in burst_particles:
                pt = t - PARTICLE_START - delay
                if pt <= 0:
                    continue
                dist  = pt * speed * (W * 0.52)
                px    = int(logo_cx + math.cos(angle) * dist)
                py    = int(logo_cy + math.sin(angle) * dist)
                fade  = max(0.0, 1.0 - pt / 1.2)
                alpha = int(255 * fade * content_a)
                if alpha < 8:
                    continue
                s = max(2, int(sz * fade))
                _draw_sparkle(spark_draw, px, py, s, (*color, alpha))

        # ── 5. Ambient twinkling particles (hold phase) ───────────────────────
        if BOB_START < t < BOB_END and content_a > 0:
            twinkle_draw = ImageDraw.Draw(frame)
            for ox, oy, sz, phase, freq in twinkle_particles:
                blink = 0.5 + 0.5 * math.sin(2 * math.pi * freq * t + phase)
                alpha = int(200 * blink * content_a)
                if alpha < 15:
                    continue
                px, py = logo_cx + ox, logo_cy + oy
                s = max(1, int(sz * blink))
                _draw_sparkle(twinkle_draw, px, py, s, (*_BRIGHT_GOLD, alpha))

        # ── 6. Logo ───────────────────────────────────────────────────────────
        if t >= LOGO_START and content_a > 0:
            # Size with elastic spring
            if t < LOGO_END:
                prog  = (t - LOGO_START) / (LOGO_END - LOGO_START)
                ease  = _ease_out_elastic(prog)
                lsize = int(LOGO_MAX + (LOGO_FINAL - LOGO_MAX) * ease)
            else:
                lsize = LOGO_FINAL

            # Bob during hold
            bob = 0
            if BOB_START < t < BOB_END:
                bob = int(math.sin(2 * math.pi * (t - BOB_START) * 0.72) * 9)

            lsize = max(12, lsize)
            lx    = logo_cx - lsize // 2
            ly    = logo_cy - lsize // 2 + bob

            # Outer glow ring behind logo
            gr = lsize + 32
            glow = Image.new("RGBA", (gr, gr), (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse([0, 0, gr, gr],
                                          fill=(*_GOLD, int(75 * content_a)))
            glow = glow.filter(ImageFilter.GaussianBlur(18))
            frame.paste(glow, (lx - 16, ly - 16), glow)

            # Shadow
            shadow_size = lsize + 20
            shadow = Image.new("RGBA", (shadow_size, shadow_size), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).ellipse([0, 0, shadow_size, shadow_size],
                                            fill=(0, 0, 0, int(80 * content_a)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(20))
            frame.paste(shadow, (lx - 10 + 14, ly - 10 + 18), shadow)

            # Logo with chromatic aberration during entry
            logo_img = get_logo(lsize).copy()
            if LOGO_START < t < LOGO_START + 0.28:
                chroma_prog = (t - LOGO_START) / 0.28    # 0→1
                shift = int((1 - chroma_prog) * 10)
                logo_img = _chroma_shift(logo_img, shift)

            # Apply content alpha to logo
            if content_a < 1.0:
                arr = np.array(logo_img)
                arr[:, :, 3] = (arr[:, :, 3] * content_a).astype(np.uint8)
                logo_img = Image.fromarray(arr)

            frame.paste(logo_img, (lx, ly), logo_img)

        # ── 7. Channel name (stagger after logo) ──────────────────────────────
        if t >= NAME_START and content_a > 0:
            name_prog = min(1.0, (t - NAME_START) / (NAME_END - NAME_START))
            name_a    = int(255 * _ease_out_cubic(name_prog) * content_a)
            bob = 0
            if BOB_START < t < BOB_END:
                bob = int(math.sin(2 * math.pi * (t - BOB_START) * 0.72) * 9)

            text_y_base = logo_cy + LOGO_FINAL // 2 + 22 + bob
            draw = ImageDraw.Draw(frame)

            # Channel name — white, bold, drop shadow
            bb = draw.textbbox((0, 0), channel_name, font=font_name)
            nx = (W - (bb[2] - bb[0])) // 2
            ny = text_y_base - bb[1]
            draw.text((nx + 3, ny + 3), channel_name, font=font_name,
                      fill=(0, 0, 0, int(name_a * 0.40)))
            draw.text((nx, ny), channel_name, font=font_name,
                      fill=(255, 255, 255, name_a))

        # ── 8. Handle (stagger slightly later) ────────────────────────────────
        if t >= HANDLE_START and content_a > 0:
            h_prog = min(1.0, (t - HANDLE_START) / (HANDLE_END - HANDLE_START))
            h_a    = int(255 * _ease_out_cubic(h_prog) * content_a)
            bob = 0
            if BOB_START < t < BOB_END:
                bob = int(math.sin(2 * math.pi * (t - BOB_START) * 0.72) * 9)

            text_y_base = logo_cy + LOGO_FINAL // 2 + 22 + bob
            draw = ImageDraw.Draw(frame)
            bb_n = draw.textbbox((0, 0), channel_name, font=font_name)
            name_h = bb_n[3] - bb_n[1]
            bb_h = draw.textbbox((0, 0), handle, font=font_handle)
            hx   = (W - (bb_h[2] - bb_h[0])) // 2
            hy   = text_y_base + name_h + 10 - bb_h[1]
            draw.text((hx, hy), handle, font=font_handle,
                      fill=(*_GOLD, h_a))

        frame.save(str(frame_dir / f"f{idx:04d}.png"))

    # Encode → lossless MOV RGBA
    out_mov = tempfile.mktemp(suffix="_gold_intro.mov")
    subprocess.run(
        ["ffmpeg", "-y",
         "-framerate", str(_FPS),
         "-i", str(frame_dir / "f%04d.png"),
         "-c:v", "png", "-pix_fmt", "rgba",
         out_mov],
        capture_output=True, check=True,
    )
    shutil.rmtree(str(frame_dir))
    return out_mov


# ─── Main function ────────────────────────────────────────────────────────────

def add_channel_intro(
    input_video: str,
    output_video: str,
    logo_path: str = "",
    channel_name: str = "เงินงอก",
    handle: str = "@NgernNgork",
    appear_at_sec: float = 3.0,
) -> str:
    """
    Composite Gold Luxury channel intro onto input_video starting at appear_at_sec.
    Navy cinematic overlay + elastic logo pop + gold particles/rings/rays.
    """
    logo_path = logo_path or str(_PROFILE)

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", input_video],
        capture_output=True, text=True,
    )
    info = json.loads(probe.stdout)
    vs   = next(s for s in info["streams"] if s["codec_type"] == "video")
    W, H = int(vs["width"]), int(vs["height"])

    logger.info(f"Channel intro at t={appear_at_sec:.1f}s on {Path(input_video).name}")
    intro_mov = _render_intro_frames(logo_path, channel_name, handle, W, H)

    esc   = intro_mov.replace("'", r"\'").replace(":", r"\:")
    ta    = appear_at_sec
    filt  = (
        f"movie={esc},setpts=PTS+{ta}/TB[intro];"
        f"[0:v][intro]overlay=x=0:y=0"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-filter_complex", filt,
        "-c:v", "h264_videotoolbox", "-b:v", "7M",
        "-c:a", "copy",
        output_video,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.warning("h264_videotoolbox → libx264")
        cmd[cmd.index("h264_videotoolbox")] = "libx264"
        i = cmd.index("-b:v")
        cmd[i:i+2] = ["-crf", "22", "-preset", "fast"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logger.error(f"FFmpeg:\n{r.stderr[-800:]}")

    Path(intro_mov).unlink(missing_ok=True)
    logger.success(f"Gold Luxury intro → {Path(output_video).name}")
    return output_video
