"""สร้าง thumbnail จาก frame วิดีโอ + centered text block"""

import json
import math
import re
import subprocess
from pathlib import Path
from loguru import logger


def _ai_thumbnail_text(title: str, sentences: list = None) -> tuple:
    """
    Viral thumbnail formula 2025-2026:
    - main (ใหญ่มาก): ≤4 คำ hook — อ่านได้ใน <1 วินาที
    - sub  (กลาง):    ≤5 คำ payoff — ตัวเลข/ผลลัพธ์ที่ทำให้ต้องคลิก
    รับ sentences จาก script เพื่อให้ AI เห็นตัวเลขจริงในคลิป
    """
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        script_excerpt = ""
        if sentences:
            # ส่ง 8 ประโยคกลางๆ — มักมีตัวเลข/fact สำคัญ
            mid = sentences[2:10]
            script_excerpt = "\n\nScript excerpt (ใช้ตัวเลขจากนี้ใน thumbnail_sub):\n" + "\n".join(f"- {s}" for s in mid)

        prompt = f"""สร้างข้อความ thumbnail TikTok การเงินภาษาไทย ตาม viral formula 2025-2026

Title: {title}{script_excerpt}

FORMAT:
- thumbnail_main: ≤4 คำ — บอก topic/การเปรียบเทียบให้ชัด อ่านแล้วรู้ทันทีว่าคลิปเกี่ยวกับอะไร
- thumbnail_sub:  ≤5 คำ — payoff พร้อมตัวเลขจริงจาก script

กฎเหล็ก:
- ⚠ thumbnail_main ≤4 คำเท่านั้น — นับคำ: "หุ้น vs พันธบัตร" = 3 คำ ✅ | "หุ้น vs พันธบัตรรัฐบาล" = 4 คำ ✅ | "หุ้น vs พันธบัตรรัฐบาลไทย" = เกิน ❌
- ⚠ main ต้องบอก TOPIC ชัด อ่านแล้วรู้ทันทีว่าคลิปเกี่ยวกับอะไร
- ⚠ "vs" ใช้เฉพาะเมื่อ title มีการเปรียบเทียบ 2 ฝั่งจริงๆ เช่น หุ้น vs พันธบัตร, ภาษีไทย vs มาเลเซีย
  ❌ ห้ามแต่งเติม "vs" เข้าไปเองถ้า title ไม่ได้เปรียบเทียบ 2 ฝั่ง
  ❌ "จ่ายขั้นต่ำ vs หนี้เต็ม" (title ไม่ได้เปรียบเทียบ — เป็น revelation ว่าหนี้ไม่หมด)
- ⚠ สำหรับ topic แบบ revelation/list/trap: ใช้ประโยคบอกความจริงที่น่าตกใจโดยตรง
  ✅ "จ่ายขั้นต่ำ ต้นไม่ลด" | "ดอกกินต้น 5 ปี" | "ขั้นต่ำบัตร = กับดัก"
- ⚠ thumbnail_sub ต้องเป็นประโยคที่อ่านแล้วเข้าใจทันที บอก outcome/ผลลัพธ์ที่น่าตกใจ
- ⚠ ถ้า main เป็น "A vs B" — sub ต้องบอก SUBJECT ชัด ว่าใครชนะ/ดีกว่า
  ❌ "รวยกว่า 8 เท่า" (ใครรวยกว่า?) ✅ "สิงคโปร์รวยกว่า 8 เท่า"
- sub ต้องบอก CONCLUSION ชัดๆ ห้ามตัดคำกลาง

ตัวอย่างดี (vs — มีการเปรียบเทียบ 2 ฝั่งจริง):
title: "หุ้น SET vs พันธบัตรรัฐบาล 15 ปี"
→ {{"thumbnail_main": "หุ้น vs พันธบัตร", "thumbnail_sub": "หุ้นชนะ 4.2 เท่าใน 15 ปี"}}

title: "ภาษีไทย 10% vs มาเลเซีย 0%"
→ {{"thumbnail_main": "ภาษีไทย vs มาเลเซีย", "thumbnail_sub": "ต่างกัน 1.2 ล้านใน 10 ปี"}}

ตัวอย่างดี (trap/กับดัก — hook word ขึ้นหน้าก่อน):
title: "ซื้อ iPhone ผ่อน 0% ดีจริงหรือกับดัก"
→ {{"thumbnail_main": "กับดัก ผ่อน iPhone 0%", "thumbnail_sub": ""}}

title: "ผ่อนบ้าน 30 ปี กับดักที่ธนาคารไม่บอก"
→ {{"thumbnail_main": "กับดัก ผ่อนบ้าน 30 ปี", "thumbnail_sub": ""}}

title: "Unit-Linked ประกันที่ทำให้เสียเงินโดยไม่รู้"
→ {{"thumbnail_main": "กับดัก Unit-Linked", "thumbnail_sub": ""}}

ตัวอย่างดี (revelation/fact — topic ขึ้นหน้า):
title: "จ่ายบัตรเครดิตขั้นต่ำ 5 ปี ต้นไม่ลด"
→ {{"thumbnail_main": "จ่ายขั้นต่ำ ต้นไม่ลด", "thumbnail_sub": ""}}

title: "5 จุดที่ทำให้เงินเดือน 30,000 หายหมด"
→ {{"thumbnail_main": "เงินเดือน 30,000 หาย", "thumbnail_sub": ""}}

title: "3 สกุลเงินแข็งที่สุดในโลก"
script: "...1 ดีนาร์คูเวต แลกได้ 115 บาท..."
→ {{"thumbnail_main": "สกุลเงินแข็งสุดในโลก", "thumbnail_sub": "1 ดีนาร์ = 115 บาท"}}

⚠ กฎ hook word ก่อน:
ถ้า title มีคำว่า กับดัก / ระวัง / อย่าโดน / อย่าทำ / ไม่บอก / ซ่อนอยู่ / คนไม่รู้
→ เอา hook word นั้นขึ้นหน้าก่อน แล้วตามด้วย topic
✅ "กับดัก ผ่อน 0%" | "ระวัง ประกัน Unit-Linked" | "ซ่อนอยู่ ค่าธรรมเนียม"
❌ "ผ่อน 0% กับดัก" (hook อยู่หลัง — คนไม่หยุดดู)

ตอบ JSON เท่านั้น: {{"thumbnail_main": "...", "thumbnail_sub": "..."}}"""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            main = str(data.get("thumbnail_main", "")).strip()
            sub  = str(data.get("thumbnail_sub",  "")).strip()
            # enforce word limits — ตัดถ้าเกิน
            main_words = main.split()
            if len(main_words) > 5:
                main = " ".join(main_words[:5])
            if main:
                logger.info(f"AI thumbnail: main='{main}'")
                return main, ""   # 1 บรรทัดเท่านั้น — ง่าย อ่านได้ทันที
    except Exception as e:
        logger.debug(f"AI thumbnail fallback: {e}")
    return "", ""

_CONFIG = Path(__file__).parent.parent / "config"
_FONT_CANDIDATES = [
    _CONFIG / "Sarabun-Bold.ttf",       # สระไม่ทับกัน, Bold, อ่านง่ายบน thumbnail
    _CONFIG / "NotoSansThai-Regular.ttf", # fallback — สระชัดแต่ Regular weight
    _CONFIG / "Kanit-Bold.ttf",           # อาจมีสระทับกันที่ขนาดใหญ่มาก
]


def _find_font() -> str:
    for f in _FONT_CANDIDATES:
        if f.exists() and f.stat().st_size > 10_000:
            return str(f)
    return ""


def _get_duration(video_path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip() or 5)
    except Exception:
        return 5.0


def _extract_big_number(title: str) -> str:
    """ดึงตัวเลขที่ใหญ่/น่าสนใจที่สุดจาก title"""
    patterns = [
        r'(\d+(?:\.\d+)?\s*ล้าน(?:\s*บาท)?)',
        r'(\d+(?:\.\d+)?%)',
        r'(\d{1,3}(?:,\d{3})+(?:\s*บาท)?)',
        r'(\d+\s*เท่า)',
        r'(\d+\s*ปี)',
    ]
    for pat in patterns:
        m = re.search(pat, title)
        if m:
            return m.group(1).strip()
    return ""


_MODIFIER_WORDS = {
    "ที่แล้ว", "ปีที่แล้ว", "เดือนที่แล้ว", "ที่ผ่านมา",
    "นั้น", "นี้", "แบบนี้", "จริงๆ", "ก็",
}


def _short_wrap(text: str, max_chars: int = 16) -> list:
    """ตัด text เป็นบรรทัดสั้นๆ ≤ max_chars ตัด word-boundary"""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) > max_chars and cur:
            lines.append(cur)
            if len(lines) >= 2:
                break
            cur = w
        else:
            cur = cand
    if cur and len(lines) < 2:
        lines.append(cur)
    return lines


def _extract_vs_entities(part_a: str) -> str:
    """ดึง 'X vs Y' จาก subject — ตัด modifier/number ออก เหลือแค่ entity names"""
    words = part_a.split()
    if "vs" not in words:
        return ""
    vi = words.index("vs")
    lhs_words = [w for w in words[:vi]
                 if not re.match(r'^\d', w) and w not in _MODIFIER_WORDS]
    rhs_words = [w for w in words[vi+1:]
                 if not re.match(r'^\d', w) and w not in _MODIFIER_WORDS]
    lhs = lhs_words[-1] if lhs_words else ""
    rhs = rhs_words[0] if rhs_words else ""
    if lhs and rhs:
        result = f"{lhs} vs {rhs}"
        return result if len(result) <= 18 else rhs
    return ""


def _wrap_words(text: str, max_chars: int = 18, max_lines: int = 3) -> list:
    """แบ่ง text เป็น ≤ max_lines บรรทัด ≤ max_chars ต่อบรรทัด ตัดที่ขอบ space"""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) > max_chars and cur:
            lines.append(cur)
            if len(lines) >= max_lines:
                break
            cur = w
        else:
            cur = cand
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines] if lines else [text[:max_chars]]


def _make_hook_lines(title: str, big_num: str) -> list:
    """
    VALUE CLARITY layout — อ่านแล้วเข้าใจทันทีว่าคลิปนี้เกี่ยวกับอะไร

    Layout:
      Line 1 (orange): Context / Topic — บอกว่าเรื่องนี้เกี่ยวกับอะไร (ไม่ใช่ตัวเลขลอยๆ)
      Line 2 (white):  Fact + Number — ตัวเลขที่มีบริบท อ่านแล้วรู้ว่าหมายถึงอะไร
      Line 3 (white):  Insight — ดูจบแล้วจะรู้อะไร / ผลลัพธ์
    """
    clean = re.sub(r'\s*[-—]\s*', ' — ', title)
    clean = re.sub(r'\(.*?\)', '', clean).strip()
    clean = re.sub(r'\s*=\s*', ' ', clean)  # แทน = ด้วย space
    clean = re.sub(r'\s+', ' ', clean).strip()

    has_dash = ' — ' in clean
    if has_dash:
        parts = clean.split(' — ', 1)
        part_a = parts[0].strip()
        part_b = parts[1].strip()
    else:
        part_a = clean
        part_b = ""

    if has_dash:
        # แบ่ง part_a เป็น 2 บรรทัด balanced — _short_wrap ใช้ pythainlp หาจุดตัดที่สมดุลที่สุด
        # เช่น "ยืม 3% ลงทุน 8%" → ["ยืม 3%", "ลงทุน 8%"] | "2540 สูญ 4.2 ล้านล้าน" → ["2540 สูญ 4.2", "ล้านล้าน"]
        a_lines = _short_wrap(part_a, max_chars=12)
        line1 = a_lines[0] if a_lines else part_a
        line2 = a_lines[1] if len(a_lines) > 1 else ""

        # Line 3: ดึงจาก part_b (insight / consequence)
        b_lines = _short_wrap(part_b, max_chars=14)
        line3 = b_lines[0] if b_lines else ""

        lines = [line1]
        if line2:
            lines.append(line2)
        if line3 and len(lines) < 3:
            lines.append(line3)
        return lines[:3]

    else:
        # No dash: หา transition word ก่อน ("แต่" / "versus" / "vs") แล้ว split เหมือน has-dash
        _TRANS = re.compile(r'\s+(แต่(?!ละ)|versus|vs|เทียบ|หรือ|กับ)\s+', re.IGNORECASE)
        m = _TRANS.search(part_a)
        if m:
            # treat transition word as em-dash: part before = topic, part after = insight
            p_a = part_a[:m.start()].strip()
            p_b = part_a[m.end():].strip()
            a_lines = _short_wrap(p_a, max_chars=12)
            line1 = a_lines[0] if a_lines else p_a
            line2 = a_lines[1] if len(a_lines) > 1 else ""
            b_lines = _short_wrap(p_b, max_chars=14)
            line3 = b_lines[0] if b_lines else ""
            lines_out = [line1]
            if line2: lines_out.append(line2)
            if line3 and len(lines_out) < 3: lines_out.append(line3)
            return lines_out[:3]
        # fallback: wrap ทั้ง title เป็น 3 บรรทัด max 18 chars
        return _wrap_words(part_a, max_chars=18, max_lines=3)


def _best_early_frame(video_path: str) -> float:
    """
    ดึง frame จาก t=0.01-0.06s — ก่อนเสียงพากและ subtitle ทุกอย่างเริ่ม
    word_timings[0] เริ่มหลัง 0.08s ขึ้นไปเสมอ → t=0.01-0.06s ได้ background สะอาด
    """
    import tempfile, os
    # t=0.03s อยู่ก่อน subtitle (scene 0 เริ่มที่ 0.07s) → ได้ background สะอาด
    candidates = [0.03, 0.04, 0.05, 0.06]
    best_ts, best_score = 0.04, float("inf")
    with tempfile.TemporaryDirectory() as tmpdir:
        for ts in candidates:
            fp = os.path.join(tmpdir, f"f{ts:.2f}.jpg")
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", str(ts), "-i", video_path,
                 "-vframes", "1", "-q:v", "5", fp],
                capture_output=True, timeout=15,
            )
            if r.returncode != 0 or not os.path.exists(fp):
                continue
            r2 = subprocess.run(
                ["convert", fp, "-colorspace", "gray",
                 "-format", "%[fx:mean]", "info:"],
                capture_output=True, text=True, timeout=10,
            )
            try:
                mean = float(r2.stdout.strip())
                score = abs(mean - 0.38)      # target ไม่สว่างเกิน
                if score < best_score:
                    best_score, best_ts = score, ts
            except ValueError:
                pass
    return best_ts


def _render_thai_text_png(
    text: str, font_pt: int, color_rgb: tuple, width_px: int, out_png: str
) -> int:
    """
    Render Thai text via Pango+HarfBuzz (ไม่มีสระทับกัน).
    color_rgb = (r, g, b) floats 0-1.
    Returns canvas height in pixels, 0 on failure.
    """
    try:
        import os
        os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
        import cairocffi as cairo
        import pangocffi
        import pangocairocffi

        UNITS = pangocffi.units_from_double(1)  # 1024

        def _make_lo(ctx):
            pango_ctx = pangocairocffi.create_context(ctx)
            pangocairocffi.set_resolution(pango_ctx, 72.0)  # match ImageMagick DPI
            lo = pangocffi.Layout(pango_ctx)
            fd = pangocffi.FontDescription()
            fd.family = "Sarabun"
            fd.weight = pangocffi.Weight.BOLD
            fd.size = pangocffi.units_from_double(font_pt)
            lo.font_description = fd
            lo.width = pangocffi.units_from_double(width_px)
            lo.alignment = pangocffi.Alignment.CENTER
            lo.text = text
            return lo

        # Pass 1: measure
        _surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width_px, font_pt * 5)
        _ctx = cairo.Context(_surf)
        lo_m = _make_lo(_ctx)
        _, h_units = lo_m.get_size()
        h_px = h_units // UNITS
        top_pad = max(15, int(font_pt * 0.15))
        bot_pad = max(8, int(font_pt * 0.08))
        canvas_h = h_px + top_pad + bot_pad

        # Pass 2: render
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width_px, canvas_h)
        ctx = cairo.Context(surf)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        lo = _make_lo(ctx)

        r, g, b = color_rgb
        # outline ดำเพื่อให้อ่านได้บนทุก background
        ctx.set_source_rgba(0, 0, 0, 0.85)
        ctx.move_to(0, top_pad)
        pangocairocffi.layout_path(ctx, lo)
        ctx.set_line_width(5)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
        # fill สี
        ctx.set_source_rgba(r, g, b, 1.0)
        ctx.move_to(0, top_pad)
        pangocairocffi.show_layout(ctx, lo)

        surf.write_to_png(out_png)
        return canvas_h
    except Exception as e:
        logger.debug(f"Pango text render failed: {e}")
        return 0


def _render_logo_png(png_path: str) -> bool:
    """Render 'เงินงอก' logo with Pango+Cairo for correct Thai vowel shaping (no สระทับ)"""
    try:
        import os
        os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
        import cairocffi as cairo
        import pangocffi
        import pangocairocffi

        w, h = 280, 72
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        ctx = cairo.Context(surface)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        lo = pangocairocffi.create_layout(ctx)
        fd = pangocffi.FontDescription()
        fd.family = "Sarabun"
        fd.weight = pangocffi.Weight.BOLD
        fd.size = pangocffi.units_from_double(34)
        lo.font_description = fd
        lo.text = "เงินงอก"
        lo.alignment = pangocffi.Alignment.LEFT

        # outline ดำ
        ctx.set_source_rgba(0, 0, 0, 0.85)
        ctx.move_to(2, 8)
        pangocairocffi.layout_path(ctx, lo)
        ctx.set_line_width(5)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()

        # fill ทอง #d4a843
        ctx.set_source_rgba(0.831, 0.659, 0.263, 1.0)
        ctx.move_to(2, 8)
        pangocairocffi.show_layout(ctx, lo)

        surface.write_to_png(png_path)
        return True
    except Exception:
        return False


def generate(video_path: str, title: str, output_path: str, sentences: list = None) -> bool:
    """
    Thumbnail formula — Centered block layout:

    ┌─────────────────────────┐
    │ เงินงอก  (top-left)     │
    │                         │
    │    [dark overlay]       │
    │                         │
    │   ┌─────────────┐       │
    │   │  BIG NUMBER │  ←orange│
    │   │  line 2     │  ←white│
    │   │  line 3     │  ←white│
    │   └─────────────┘       │
    │                         │
    └─────────────────────────┘

    - text ทั้งหมดอยู่กลางจอเป็น block เดียว
    - dark overlay ทั้งภาพ (ไม่ครึ่งล่าง) → text อ่านง่ายบนทุก background
    - BIG NUMBER สีส้มตัวใหญ่ — stop-scroll
    - description สีขาว bold ด้านล่าง
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame_tmp = str(output_path.with_suffix(".frame.jpg"))

    ts = _best_early_frame(video_path)

    # 1. Extract frame
    r = subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(ts), "-i", video_path,
        "-vframes", "1",
        "-vf", "eq=contrast=1.05:saturation=1.05",
        "-q:v", "2", frame_tmp,
    ], capture_output=True, timeout=30)

    if r.returncode != 0 or not Path(frame_tmp).exists():
        logger.warning("Thumbnail: frame extraction failed")
        return False

    font    = _find_font()
    clean_title = re.sub(r'\s*\(.*?\)\s*', ' ', title).strip()

    # Primary: AI-generated thumbnail text — 2 บรรทัด (main + sub)
    main_text, sub_text = _ai_thumbnail_text(clean_title, sentences=sentences)
    if not main_text:
        # Fallback: rule-based
        big_num = _extract_big_number(clean_title)
        fallback = _make_hook_lines(clean_title, big_num)
        main_text = fallback[0] if fallback else clean_title[:20]
        sub_text  = " ".join(fallback[1:]) if len(fallback) > 1 else ""

    # 2. Build ImageMagick command  (IMv7: magick, ไม่ใช่ convert)
    cmd = ["magick", frame_tmp,

           # overlay เบาๆ ทั้งภาพ — พอให้ภาพพื้นหลังเห็นได้ชัด ไม่มืดจนเกินไป
           "-fill", "rgba(0,0,0,0.28)",
           "-draw", "rectangle 0,0 1080,1920",
    ]

    # logo ไม่ต้องเพิ่มซ้ำ — frame จากวิดีโอมี watermark burn-in อยู่แล้ว

    # ─── Viral thumbnail layout 2025-2026 ────────────────────────────
    # main (ใหญ่มาก สีส้ม): hook ≤4 คำ — อ่านได้ใน <1 วินาที
    # sub  (กลาง สีขาว):    payoff ≤5 คำ — ตัวเลขชัดเจน ทำให้ต้องคลิก
    # จัดกลางจอ (y=960) ไม่ชิดขอบ

    pango_tmp_files = []

    if main_text:
        # ── font size ────────────────────────────────────────────────
        n_main = len(main_text)
        font_main = max(90, min(160, int(1100 / max(n_main, 7))))

        n_sub = len(sub_text) if sub_text else 1
        font_sub = max(64, min(90, int(1080 / max(n_sub, 10))))

        # ── Pango render (HarfBuzz shaping — ไม่มีสระทับกัน) ────────
        tmp_main_png = str(output_path.with_suffix(".main.png"))
        pango_main_h = _render_thai_text_png(
            main_text, font_main, (1.0, 0.584, 0.0), 960, tmp_main_png
        )
        if pango_main_h:
            pango_tmp_files.append(tmp_main_png)
            main_box_h = pango_main_h
        else:
            chars_per_line_main = max(3, int(960 / (font_main * 0.62)))
            n_lines_main = max(1, math.ceil(n_main / chars_per_line_main))
            main_box_h = n_lines_main * int(font_main * 1.35) + 10

        pango_sub_h = 0
        if sub_text:
            tmp_sub_png = str(output_path.with_suffix(".sub.png"))
            pango_sub_h = _render_thai_text_png(
                sub_text, font_sub, (1.0, 1.0, 1.0), 960, tmp_sub_png
            )
            if pango_sub_h:
                pango_tmp_files.append(tmp_sub_png)
                sub_box_h = pango_sub_h
            else:
                chars_per_line_sub = max(3, int(960 / (font_sub * 0.62)))
                n_lines_sub = max(1, math.ceil(n_sub / chars_per_line_sub))
                sub_box_h = n_lines_sub * int(font_sub * 1.35) + 10
        else:
            sub_box_h = 0

        gap = 20
        block_h = main_box_h + (gap + sub_box_h if sub_text else 0)
        y_top = 960 - block_h // 2   # center กลางจอ

        # dark pill หลัง text block
        pill_pad_x, pill_pad_y = 40, 30
        pill_x1 = 60 - pill_pad_x
        pill_y1 = y_top - pill_pad_y
        pill_x2 = 60 + 960 + pill_pad_x
        pill_y2 = y_top + block_h + pill_pad_y
        cmd += [
            "-fill", "rgba(0,0,0,0.58)",
            "-draw", f"roundrectangle {pill_x1},{pill_y1} {pill_x2},{pill_y2} 28,28",
        ]

        # main — composite Pango PNG หรือ fallback caption:
        if pango_main_h:
            cmd += [
                "(", tmp_main_png, ")",
                "-gravity", "NorthWest",
                "-geometry", f"+60+{y_top}",
                "-composite",
            ]
        else:
            if font:
                cmd += ["-font", font]
            cmd += [
                "(",
                "-size", f"960x{main_box_h}", "-background", "none",
                "-font", font or "Helvetica",
                "-pointsize", str(font_main),
                "-fill", "#FF9500", "-gravity", "Center",
                f"caption:{main_text}",
                ")",
                "-gravity", "NorthWest",
                "-geometry", f"+60+{y_top}",
                "-composite",
            ]

        # sub (ถ้ามี)
        if sub_text:
            y_sub = y_top + main_box_h + gap
            if pango_sub_h:
                cmd += [
                    "(", tmp_sub_png, ")",
                    "-gravity", "NorthWest",
                    "-geometry", f"+60+{y_sub}",
                    "-composite",
                ]
            else:
                if font:
                    cmd += ["-font", font]
                cmd += [
                    "(",
                    "-size", f"960x{sub_box_h}", "-background", "none",
                    "-font", font or "Helvetica",
                    "-pointsize", str(font_sub),
                    "-fill", "white", "-gravity", "Center",
                    f"caption:{sub_text}",
                    ")",
                    "-gravity", "NorthWest",
                    "-geometry", f"+60+{y_sub}",
                    "-composite",
                ]

    cmd += [str(output_path)]

    r = subprocess.run(cmd, capture_output=True, timeout=30)
    Path(frame_tmp).unlink(missing_ok=True)
    for _f in pango_tmp_files:
        Path(_f).unlink(missing_ok=True)

    ok = (r.returncode == 0
          and output_path.exists()
          and output_path.stat().st_size > 5_000)
    if ok:
        logger.info(f"Thumbnail → {output_path.name} ({output_path.stat().st_size // 1024}KB)")
    else:
        logger.warning(f"Thumbnail failed: {r.stderr.decode()[:200]}")
    return ok
