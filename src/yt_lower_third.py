"""
YouTube / Facebook Lower Third — WOW Edition v2
Animations: Elastic spring entrance · Glow pulse · Cross-fade + scale-spring transition · Fade-out slide exit
"""

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from loguru import logger

_ASSETS  = Path(__file__).parent.parent / "assets"
_FONTS   = Path(__file__).parent.parent / "config"
_PROFILE = _ASSETS / "profile.jpg"

_FPS       = 30
_SLIDE_DUR = 0.50   # elastic slide-in seconds
_EXIT_DUR  = 0.40   # slide-out seconds
_SWITCH_T  = 2.50   # Subscribe → Subscribed moment
_FADE_DUR  = 0.25   # cross-fade duration
_GLOW_HZ   = 1.30   # glow pulse frequency (cycles/sec)


# ─── Drawing helpers ──────────────────────────────────────────────────────────

def _rounded_rect(draw, x1, y1, x2, y2, radius, fill):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def _gradient_rect(img, x1, y1, x2, y2, radius, color_l, color_r):
    w = x2 - x1
    for i in range(w):
        r = int(color_l[0] + (color_r[0] - color_l[0]) * i / w)
        g = int(color_l[1] + (color_r[1] - color_l[1]) * i / w)
        b = int(color_l[2] + (color_r[2] - color_l[2]) * i / w)
        a = color_l[3] if len(color_l) > 3 else 255
        ImageDraw.Draw(img).line([(x1 + i, y1), (x1 + i, y2)], fill=(r, g, b, a))
    mask = Image.new("L", (x2 - x1, y2 - y1), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, x2 - x1, y2 - y1], radius=radius, fill=255)
    region = img.crop((x1, y1, x2, y2))
    region.putalpha(mask)
    img.paste(region, (x1, y1), region)


def _glow_pill(canvas, cx, cy, pw, ph, radius, color, blur_r=18):
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    for spread in range(3, 0, -1):
        a = 60 // spread
        d.rounded_rectangle(
            [cx - spread*4, cy - spread*4, cx + pw + spread*4, cy + ph + spread*4],
            radius=ph//2 + spread*4, fill=(*color[:3], a),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(blur_r))
    canvas.alpha_composite(glow)


def _draw_text_centered(draw, text, font, cx, cy, w, h, fill):
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((cx + (w - tw) // 2, cy + (h - th) // 2 - bb[1]), text, font=font, fill=fill)


def _load_logo(logo_path, size):
    src = logo_path or str(_PROFILE)
    if Path(src).exists():
        logo = Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)
    else:
        logo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(logo)
        d.ellipse([0, 0, size, size], fill=(76, 175, 80, 255))
        try:
            f = ImageFont.truetype(str(_FONTS / "Sarabun-Bold.ttf"), size // 2)
        except Exception:
            f = ImageFont.load_default()
        d.text((size // 4, size // 6), "ง", font=f, fill=(255, 255, 255, 255))
        return logo
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(logo, mask=mask)
    return out


def _make_frosted_pill(
    channel_name: str, handle: str, logo_path: str,
    width: int, style: str = "youtube", state: str = "subscribe",
) -> tuple[Image.Image, Image.Image]:
    """Returns (pill_canvas RGBA, blur_mask grayscale)."""
    is_dark = (style == "facebook")
    pill_h  = 120
    pill_w  = min(560, width - 60)
    pad     = 18
    logo_d  = pill_h - pad * 2
    btn_w, btn_h = 155, 50
    margin  = 20

    canvas_h = pill_h + margin * 2
    img  = Image.new("RGBA", (width, canvas_h), (0, 0, 0, 0))
    mask = Image.new("L",    (width, canvas_h), 0)
    cx, cy = (width - pill_w) // 2, margin

    glow_color = (24, 119, 242) if is_dark else (255, 50, 50)
    _glow_pill(img, cx, cy, pill_w, pill_h, pill_h // 2, glow_color, blur_r=20)

    ImageDraw.Draw(mask).rounded_rectangle(
        [cx, cy, cx + pill_w, cy + pill_h], radius=pill_h // 2, fill=255
    )

    draw = ImageDraw.Draw(img)
    tint = (20, 22, 40, 200) if is_dark else (255, 255, 255, 210)
    _rounded_rect(draw, cx, cy, cx + pill_w, cy + pill_h, radius=pill_h // 2, fill=tint)

    border = (60, 80, 140, 160) if is_dark else (220, 220, 220, 180)
    draw.rounded_rectangle([cx, cy, cx + pill_w, cy + pill_h],
                            radius=pill_h // 2, outline=border, width=2)

    lx, ly = cx + pad, cy + pad
    logo_img = _load_logo(logo_path, logo_d)
    ring = Image.new("RGBA", (logo_d + 8, logo_d + 8), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([0, 0, logo_d + 8, logo_d + 8], fill=(*glow_color, 60))
    ring = ring.filter(ImageFilter.GaussianBlur(4))
    img.alpha_composite(ring, (lx - 4, ly - 4))
    img.paste(logo_img, (lx, ly), logo_img)

    div_x = lx + logo_d + 14
    div_color = (80, 90, 130, 150) if is_dark else (200, 200, 200, 180)
    draw.line([(div_x, cy + 20), (div_x, cy + pill_h - 20)], fill=div_color, width=1)

    tx = div_x + 16
    try:
        font_name   = ImageFont.truetype(str(_FONTS / "Sarabun-Bold.ttf"),    28)
        font_handle = ImageFont.truetype(str(_FONTS / "Sarabun-Regular.ttf"), 19)
    except Exception:
        font_name = font_handle = ImageFont.load_default()

    name_color   = (240, 240, 255, 255) if is_dark else (15, 15, 15, 255)
    handle_color = (150, 160, 200, 255) if is_dark else (110, 110, 110, 255)

    bb_n = draw.textbbox((0, 0), channel_name, font=font_name)
    bb_h = draw.textbbox((0, 0), handle,       font=font_handle)
    n_h, h_h = bb_n[3] - bb_n[1], bb_h[3] - bb_h[1]
    blk_h = n_h + 8 + h_h
    ty = cy + (pill_h - blk_h) // 2
    draw.text((tx, ty - bb_n[1]),            channel_name, font=font_name,   fill=name_color)
    draw.text((tx, ty + n_h + 8 - bb_h[1]), handle,       font=font_handle, fill=handle_color)

    bx = cx + pill_w - btn_w - pad
    by = cy + (pill_h - btn_h) // 2

    if state in ("subscribe", "follow"):
        if style == "youtube":
            _gradient_rect(img, bx, by, bx + btn_w, by + btn_h,
                           btn_h // 2, (255, 30, 30, 255), (200, 0, 60, 255))
            btn_text = "▶  Subscribe"
        else:
            _gradient_rect(img, bx, by, bx + btn_w, by + btn_h,
                           btn_h // 2, (24, 119, 242, 255), (10, 80, 200, 255))
            btn_text = "  Follow"
    else:
        _rounded_rect(ImageDraw.Draw(img), bx, by, bx + btn_w, by + btn_h,
                      radius=btn_h // 2, fill=(55, 60, 80, 220))
        btn_text = "✓  Subscribed" if style == "youtube" else "✓  Following"

    try:
        font_btn = ImageFont.truetype(str(_FONTS / "Sarabun-Bold.ttf"), 18)
    except Exception:
        font_btn = ImageFont.load_default()
    _draw_text_centered(ImageDraw.Draw(img), btn_text, font_btn, bx, by, btn_w, btn_h,
                        (255, 255, 255, 255))

    return img, mask


# ─── Animation helpers ────────────────────────────────────────────────────────

def _ease_out_elastic(t: float) -> float:
    """Spring ease-out: 0→1 with natural overshoot."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return math.pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


def _cross_fade(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    arr_a = np.array(a, dtype=np.float32)
    arr_b = np.array(b, dtype=np.float32)
    return Image.fromarray(((1 - t) * arr_a + t * arr_b).astype(np.uint8))


def _render_pill_animation(
    channel_name: str, handle: str, logo_path: str,
    W: int, canvas_h: int, cx: int, cy: int, pill_w: int, pill_h: int,
    style: str, duration_sec: float,
) -> str:
    """
    Pre-render animated pill overlay frames:
      · Glow ring pulse (breathes at _GLOW_HZ Hz)
      · Smooth cross-fade: Subscribe → Subscribed
      · Scale-spring "click" effect at transition
      · Alpha fade-in (first 0.28s) and fade-out (last 0.3s)

    Returns path to a temp MOV with RGBA (PNG codec).
    """
    is_sub  = "subscribe"  if style == "youtube" else "follow"
    is_done = "subscribed" if style == "youtube" else "following"
    glow_color = (24, 119, 242) if style == "facebook" else (255, 50, 50)

    pill_sub,  _ = _make_frosted_pill(channel_name, handle, logo_path, W, style, is_sub)
    pill_done, _ = _make_frosted_pill(channel_name, handle, logo_path, W, style, is_done)

    n_frames = int(duration_sec * _FPS) + 1

    FADE_IN_DUR = 0.28
    GLOW_START  = 0.40
    GLOW_END    = duration_sec - 0.28
    PRESS_START = _SWITCH_T - 0.12   # squish starts slightly before swap
    PRESS_PEAK  = _SWITCH_T          # minimum scale
    SPRING_END  = _SWITCH_T + 0.25   # spring fully settles
    FADE_OUT_ST = duration_sec - 0.30

    frame_dir = Path(tempfile.mkdtemp())
    logger.info(f"Rendering {n_frames} animation frames ({duration_sec:.1f}s @ {_FPS}fps)…")

    for idx in range(n_frames):
        t = idx / _FPS

        # ── Pill state (cross-fade at _SWITCH_T) ─────────────────────────────
        if t < _SWITCH_T:
            pill = pill_sub.copy()
        elif t < _SWITCH_T + _FADE_DUR:
            pill = _cross_fade(pill_sub, pill_done, (t - _SWITCH_T) / _FADE_DUR)
        else:
            pill = pill_done.copy()

        # ── Scale-spring "click" at transition ────────────────────────────────
        scale = 1.0
        if PRESS_START < t <= PRESS_PEAK:
            prog  = (t - PRESS_START) / (PRESS_PEAK - PRESS_START)
            scale = 1.0 - 0.065 * prog                         # squish → 0.935
        elif PRESS_PEAK < t <= SPRING_END:
            prog  = (t - PRESS_PEAK) / (SPRING_END - PRESS_PEAK)
            scale = 0.935 + 0.065 * _ease_out_elastic(prog)    # spring (overshoots ~1.01)

        if abs(scale - 1.0) > 0.001:
            new_w = max(1, int(pill_w * scale))
            new_h = max(1, int(pill_h * scale))
            region = pill.crop((cx, cy, cx + pill_w, cy + pill_h))
            region = region.resize((new_w, new_h), Image.LANCZOS)
            pill = Image.new("RGBA", (W, canvas_h), (0, 0, 0, 0))
            pill.paste(region,
                       (cx + (pill_w - new_w) // 2, cy + (pill_h - new_h) // 2),
                       region)

        # ── Overall alpha (fade in + fade out) ───────────────────────────────
        fade_in  = min(1.0, t / FADE_IN_DUR) if t < FADE_IN_DUR else 1.0
        fade_out = min(1.0, (duration_sec - t) / 0.30) if t > FADE_OUT_ST else 1.0
        alpha_mult = fade_in * fade_out

        # ── Compose frame ─────────────────────────────────────────────────────
        frame = Image.new("RGBA", (W, canvas_h), (0, 0, 0, 0))

        # Glow pulse ring (behind pill, only during active display)
        if GLOW_START < t < GLOW_END:
            pulse = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(2 * math.pi * t * _GLOW_HZ))
            glow = Image.new("RGBA", (W, canvas_h), (0, 0, 0, 0))
            d = ImageDraw.Draw(glow)
            for spread in [20, 13, 7]:
                a = int(100 * pulse * spread / 20)
                d.rounded_rectangle(
                    [cx - spread, cy - spread, cx + pill_w + spread, cy + pill_h + spread],
                    radius=pill_h // 2 + spread, fill=(*glow_color, a),
                )
            glow = glow.filter(ImageFilter.GaussianBlur(12))
            frame.alpha_composite(glow)

        frame.alpha_composite(pill)

        # Apply global alpha
        if alpha_mult < 0.999:
            arr = np.array(frame)
            arr[:, :, 3] = (arr[:, :, 3] * alpha_mult).astype(np.uint8)
            frame = Image.fromarray(arr)

        frame.save(str(frame_dir / f"f{idx:04d}.png"))

    # Encode frame sequence → MOV with lossless RGBA (PNG codec, always on macOS)
    out_mov = tempfile.mktemp(suffix="_lt_anim.mov")
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

def add_lower_third_to_video(
    input_video: str,
    output_video: str,
    channel_name: str = "เงินงอก",
    handle: str = "@NgernNgork",
    logo_path: str = "",
    appear_at_sec: float = None,
    duration_sec: float = 5.5,
    is_landscape: bool = False,
    position: str = "center",
    style: str = "youtube",
) -> str:
    logo_path = logo_path or str(_PROFILE)

    # ── Probe video ───────────────────────────────────────────────────────────
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", input_video],
        capture_output=True, text=True,
    )
    info     = json.loads(probe.stdout)
    vid_dur  = float(info["format"]["duration"])
    vs       = next(s for s in info["streams"] if s["codec_type"] == "video")
    W, H     = int(vs["width"]), int(vs["height"])

    if appear_at_sec is None:
        appear_at_sec = max(0, vid_dur - duration_sec - 0.3)

    # ── Pill geometry (must match _make_frosted_pill) ─────────────────────────
    pill_h   = 120
    pill_w   = min(560, W - 60)
    margin   = 20
    canvas_h = pill_h + margin * 2
    cx       = (W - pill_w) // 2
    cy       = margin

    # ── Y positions ───────────────────────────────────────────────────────────
    if position == "center":
        y_show = (H - canvas_h) // 2
    elif is_landscape:
        y_show = H - canvas_h - 50
    else:
        y_show = H - canvas_h - 130
    y_hide = H + canvas_h + 20   # safely below screen

    # ── Pre-render PIL animation ──────────────────────────────────────────────
    anim_mov = _render_pill_animation(
        channel_name, handle, logo_path, W, canvas_h,
        cx, cy, pill_w, pill_h, style, duration_sec,
    )

    # ── Elastic y expression ──────────────────────────────────────────────────
    # t_local = video time relative to animation start (appear_at_sec)
    ta  = appear_at_sec
    sd  = _SLIDE_DUR
    ext = duration_sec - _EXIT_DUR   # local time when exit begins

    tl = f"(t-{ta})"
    # elastic in: pow(2,-10*t)*sin((t*10-0.75)*2π/3) + 1  maps 0→0, 1→1 with spring
    elastic = f"(pow(2,-10*{tl}/{sd})*sin(({tl}/{sd}*10-0.75)*2*PI/3)+1)"
    y_in    = f"({y_hide}+{elastic}*({y_show}-{y_hide}))"
    # ease-in-quad exit (slides down with acceleration)
    y_out   = f"({y_show}+pow(({tl}-{ext})/{_EXIT_DUR},2)*({y_hide}-{y_show}))"

    y_expr = (
        f"if(lt({tl},0),{y_hide},"          # before: offscreen
        f"if(lt({tl},{sd}),{y_in},"         # elastic slide-in
        f"if(lt({tl},{ext}),{y_show},"      # static hold
        f"if(lt({tl},{duration_sec}),{y_out},"  # ease-in slide-out
        f"{y_hide}))))"                     # after: offscreen
    )

    # ── Frosted glass base + animated overlay ─────────────────────────────────
    # movie= filter injects the animation MOV and delays it to appear_at_sec
    anim_mov_escaped = anim_mov.replace("'", r"\'").replace(":", r"\:")
    filt = (
        # Blur full frame for frosted glass effect
        f"[0:v]boxblur=luma_radius=18:luma_power=2[blurred];"
        # Crop blurred region at pill position
        f"[blurred]crop={W}:{canvas_h}:0:{y_show}[patch];"
        # Overlay frosted patch (active only during pill display)
        f"[0:v][patch]overlay=0:{y_show}"
        f":enable='between(t,{ta+sd},{ta+duration_sec})'[glass];"
        # Load animation MOV, offset PTS to appear at appear_at_sec
        f"movie={anim_mov_escaped},setpts=PTS+{ta}/TB[anim];"
        # Composite animated pill with elastic y expression
        f"[glass][anim]overlay=x=0:y='{y_expr}'"
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
        logger.warning("h264_videotoolbox failed → libx264 fallback")
        cmd[cmd.index("h264_videotoolbox")] = "libx264"
        idx = cmd.index("-b:v")
        cmd[idx:idx + 2] = ["-crf", "22", "-preset", "fast"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logger.error(f"FFmpeg stderr:\n{r.stderr[-1200:]}")

    Path(anim_mov).unlink(missing_ok=True)

    logger.success(f"Lower third (WOW v2) → {Path(output_video).name}")
    return output_video
