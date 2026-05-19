"""
Subtitle renderer สำหรับภาษาไทย

Primary: Pango+Cairo (pangocairocffi) — Harfbuzz shaping ถูกต้อง 100%
  สระ+วรรณยุกต์ stack กันถูก เช่น นี้ ที่ ใช้
Fallback: ImageMagick -draw (ไม่มี shaping แต่ยังใช้งานได้)

Flow:
  text → fix_thai_digits → wrap → Pango PNG → ffmpeg overlay
"""

import math
import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from loguru import logger


SARABUN_BOLD_FONT    = Path(__file__).parent.parent / "config" / "Sarabun-Bold.ttf"
SARABUN_FONT         = Path(__file__).parent.parent / "config" / "Sarabun-Regular.ttf"
FALLBACK_FONT        = Path(__file__).parent.parent / "config" / "NotoSansThai-Regular.ttf"
KANIT_BOLD_FONT      = Path(__file__).parent.parent / "config" / "Kanit-Bold.ttf"

# Kanit Bold = recommended Thai font for viral content (clean, modern, highly legible on mobile)
_PRIMARY_THAI_FONT = "Kanit" if KANIT_BOLD_FONT.exists() else "Sarabun"

# ─── Thai digit → Arabic hardcode replace ─────────────────────────────────────
_THAI_PAIRS = [
    ("๐", "0"), ("๑", "1"), ("๒", "2"), ("๓", "3"), ("๔", "4"),
    ("๕", "5"), ("๖", "6"), ("๗", "7"), ("๘", "8"), ("๙", "9"),
]


def fix_thai_digits(text: str) -> str:
    """Hardcode replace ทีละตัว: ๐๑๒๓๔๕๖๗๘๙ → 0123456789"""
    for thai, arabic in _THAI_PAIRS:
        text = text.replace(thai, arabic)
    return text


def clean_text(text: str) -> str:
    """
    ทำความสะอาดข้อความก่อน render:
    1. แปลงเลขไทย → อาหรับ
    2. ลบ control characters
    3. normalize whitespace
    """
    text = fix_thai_digits(text)
    # ลบ control chars ยกเว้น newline
    text = "".join(c for c in text if c >= " " or c == "\n")
    return text.strip()


# ─── Thai-aware subtitle chunking ────────────────────────────────────────────

def _join_thai_words(words: list) -> str:
    """
    Join คำไทยโดยไม่ใส่ space ระหว่างคำ
    ใส่ space เฉพาะตรงที่คำก่อนหน้าหรือคำถัดไปเป็นตัวเลข/ภาษาอังกฤษ
    ไม่ใส่ space ก่อน symbol เช่น % . , -
    """
    if not words:
        return ""
    result = words[0]
    for w in words[1:]:
        next_is_symbol = bool(re.match(r'^[%.,;:/\-]', w))
        needs_space = (
            not next_is_symbol and (
                bool(re.search(r'[a-zA-Z0-9]$', result)) or
                bool(re.search(r'^[a-zA-Z0-9]', w))
            )
        )
        result += (" " if needs_space else "") + w
    return result


def wrap_text(text: str, max_chars: int = 26) -> list:
    """
    แบ่งเป็นสูงสุด 2 บรรทัด ตัดที่ขอบคำ (word boundary) เท่านั้น
    - ≤ max_chars → 1 บรรทัด
    - ใช้ pythainlp ตัดคำไทย แล้ว split ที่ขอบคำที่ balance ที่สุด
    - ห้ามตัดกลางคำ เช่น "ฟุ้มเฟือย" จะไม่ถูกตัดครึ่ง
    """
    text = clean_text(text)
    if len(text) <= max_chars:
        return [text]

    # ตัดคำด้วย pythainlp (รองรับภาษาไทยที่ไม่มี space)
    try:
        from pythainlp.tokenize import word_tokenize
        tok_words = [w for w in word_tokenize(text, engine="newmm", keep_whitespace=False) if w.strip()]
    except Exception:
        tok_words = text.split() or [text]

    if len(tok_words) < 2:
        return [text]

    # ลองทุก split position หา candidate ที่ fit ≤ max_chars ทั้งคู่
    fit_candidates = []
    all_candidates = []
    for i in range(1, len(tok_words)):
        part1 = _join_thai_words(tok_words[:i])
        part2 = _join_thai_words(tok_words[i:])
        diff = abs(len(part1) - len(part2))
        all_candidates.append((diff, part1, part2))
        if len(part1) <= max_chars and len(part2) <= max_chars:
            fit_candidates.append((diff, part1, part2))

    candidates = fit_candidates if fit_candidates else all_candidates
    _, l1, l2 = min(candidates, key=lambda x: x[0])

    if not l2:
        return [text]
    return [l1, l2]


# ─── Syllable counting & keyword detection ───────────────────────────────────

_NUM_RE = re.compile(r'\d')

def _count_syllables(text: str) -> int:
    """นับพยางค์ Thai (pythainlp) + 1 ต่อกลุ่มตัวเลข/อังกฤษ"""
    try:
        from pythainlp.tokenize import syllable_tokenize
        thai = re.sub(r'[^฀-๿]', '', text)
        count = len(syllable_tokenize(thai)) if thai else 0
    except Exception:
        count = max(1, len(re.sub(r'[^฀-๿]', '', text)) // 2)
    non_thai = re.sub(r'[฀-๿\s]', '', text)
    count += len(re.findall(r'\d+|[a-zA-Z]+', non_thai))
    return max(count, 1)


def _is_numeric_word(word: str) -> bool:
    """คำที่มีตัวเลข / % / ฿"""
    return bool(_NUM_RE.search(word)) or "%" in word or word.startswith("฿")


_NEG_CTX = {"เสีย", "ผิด", "น้อย", "ลด", "เตือน", "ระวัง", "ไม่มี", "หมด",
             "ขาด", "พลาด", "เสียหาย", "ผิดวิธ", "ไม่รู้", "สูญ"}
_POS_CTX = {"เพิ่ม", "ดี", "เก็บ", "ได้", "รวย", "สำเร็จ", "โต", "งอก",
             "ประหยัด", "กำไร", "ออม", "มีเงิน", "เก็บเงิน", "เพิ่มขึ้น"}


def _get_keyword_color(word_idx: int, all_words: list) -> str:
    """สีเดียวสำหรับ keyword chunks — ขาวสะอาด อ่านง่ายบนทุก background"""
    return "#FFFFFF"


# หน่วยที่ absorb เข้า numeric chunk เสมอ (currency / quantity / time-unit)
_NUM_CONNECTORS = {
    "บาท", "สตางค์",                             # currency
    "คน", "ครั้ง", "ใน", "เท่า", "เท่าตัว",        # quantity
    "เปอร์เซ็นต์", "เปอร์เซ็น", "%",               # percentage
    "ข้อ", "อันดับ",                              # ordinal
    "วัน", "เดือน", "ปี", "ชั่วโมง", "นาที",       # standalone time unit (3 วัน, 6 เดือน)
    "สัปดาห์", "อาทิตย์", "วินาที",
}

# frequency rate modifier — ไม่ absorb เข้า numeric chunk, แต่ absorb เข้า TEXT chunk
_FREQ_MODS = {
    "ต่อเดือน","ต่อปี","ต่อวัน","ต่ออาทิตย์","ต่อสัปดาห์",
    "ต่อครั้ง","ต่อคน","ต่อชั่วโมง",
    "วันละ","เดือนละ","ปีละ","ชั่วโมงละ",
}

# คำนำหน้าเลขลำดับ — ห้ามแยกจากตัวเลข
_ORDINAL_PREFIXES = {"ข้อ", "อันดับ", "ที่", "ลำดับ", "ตอน", "ช่วง"}

# คำนามการเงินที่ bond กับ adjective ถัดไป → own atomic chunk
_FIN_NOUNS = {"หนี้", "ดอกเบี้ย"}
_FIN_ADJS  = {"ดี", "เสีย", "เน่า", "ดำ", "สูง", "ต่ำ", "ถูก", "แพง"}

HARD_MAX = 6   # max syllables สำหรับ semantic extension (freq mod + text)

# ─── Thai number word → Arabic numeral (TTS reverse map) ─────────────────────
# ─── Full Thai number parser (compound words from TTS) ────────────────────────
# digit words → value
_TN_DIGIT = {
    "ศูนย์":0,"หนึ่ง":1,"สอง":2,"สาม":3,"สี่":4,
    "ห้า":5,"หก":6,"เจ็ด":7,"แปด":8,"เก้า":9,"เอ็ด":1,"ยี่":2,
}
# multiplier words → value (longest first for greedy match)
_TN_MULT = [
    ("ล้าน",1_000_000),("แสน",100_000),("หมื่น",10_000),
    ("พัน",1_000),("ร้อย",100),("สิบ",10),
]
_TN_ALL = sorted(
    list(_TN_DIGIT.keys()) + [m for m,_ in _TN_MULT],
    key=len, reverse=True,
)
_TN_MULT_VAL = {m: v for m, v in _TN_MULT}


def _thai_num_to_int(s: str):
    """Greedy tokenize + parse Thai number compound word → int, or None if not a number.
    สองหมื่นแปดพัน → 28000 | ยี่สิบห้า → 25 | สาม → 3 | สี่แสนห้าหมื่น → 450000
    """
    tokens = []
    r = s
    while r:
        for w in _TN_ALL:
            if r.startswith(w):
                tokens.append(w)
                r = r[len(w):]
                break
        else:
            return None   # non-number character found
    if not tokens:
        return None

    total, pending = 0, None
    for tok in tokens:
        if tok in _TN_DIGIT:
            if pending is not None:
                return None   # two digits in a row without multiplier
            pending = _TN_DIGIT[tok]
        else:
            mv = _TN_MULT_VAL[tok]
            total += (pending if pending is not None else 1) * mv
            pending = None
    if pending is not None:
        total += pending
    return total


_PUNCT_RE = re.compile(r'^([^฀-๿0-9]*)(.*?)([^฀-๿0-9]*)$', re.DOTALL)

# คำนำหน้า ordinal ที่อาจติดกับตัวเลขเป็น token เดียว เช่น "ขั้นสี่", "อันดับสาม"
_ORDINAL_PREFIX_LIST = sorted([
    "ขั้นที่", "ขั้น",
    "อันดับที่", "อันดับ",
    "ตอนที่", "ตอน",
    "ความเชื่อที่", "ความเชื่อ",
    "ข้อที่", "ข้อ",
    "ระดับที่", "ระดับ",
    "วันที่", "ครั้งที่", "ครั้ง",
    "ที่",
], key=len, reverse=True)   # longest first เพื่อ greedy match


def _thai_word_to_arabic(word: str) -> str:
    """แปลคำตัวเลขไทย (จาก TTS) → Arabic + % สำหรับแสดงในซับ
    สาม→3 | สามสิบเปอร์เซ็นต์!→30%! | ขั้นสี่→ขั้น4 | สามแสนแปดหมื่น→380,000
    """
    if not word:
        return word

    # แยก punctuation prefix/suffix
    m = _PUNCT_RE.match(word)
    punct_pre = m.group(1) if m else ""
    core      = m.group(2) if m else word
    punct_suf = m.group(3) if m else ""

    if not core:
        return word

    # 1. เปอร์เซ็นต์ล้วน
    if core == "เปอร์เซ็นต์":
        return punct_pre + "%" + punct_suf

    # 2a. decimal% เช่น "หนึ่งจุดห้าเปอร์เซ็นต์" → "1.5%"
    if "จุด" in core and core.endswith("เปอร์เซ็นต์"):
        base = core[:-len("เปอร์เซ็นต์")]
        parts = base.split("จุด", 1)
        if len(parts) == 2:
            int_part = _thai_num_to_int(parts[0]) if parts[0] else 0
            dec_part = _thai_num_to_int(parts[1]) if parts[1] else None
            if int_part is not None and dec_part is not None:
                return punct_pre + f"{int_part}.{dec_part}%" + punct_suf

    # 2b. integer% เช่น "สามสิบเปอร์เซ็นต์" → "30%"
    if core.endswith("เปอร์เซ็นต์"):
        base = core[:-len("เปอร์เซ็นต์")]
        n = _thai_num_to_int(base)
        if n is not None:
            return punct_pre + f"{n}%" + punct_suf

    # 3a. decimal number เช่น "หนึ่งจุดห้า" → "1.5"
    if "จุด" in core:
        parts = core.split("จุด", 1)
        if len(parts) == 2:
            int_part = _thai_num_to_int(parts[0]) if parts[0] else 0
            dec_part = _thai_num_to_int(parts[1]) if parts[1] else None
            if int_part is not None and dec_part is not None:
                return punct_pre + f"{int_part}.{dec_part}" + punct_suf

    # 3b. integer ล้วน เช่น "สามหมื่น", "ยี่สิบห้า", "สามแสนแปดหมื่น"
    n = _thai_num_to_int(core)
    if n is not None:
        converted = f"{n:,}" if n >= 1_000 else str(n)
        return punct_pre + converted + punct_suf

    # 4. Ordinal compound เช่น "ขั้นสี่"→"ขั้น4", "อันดับสาม"→"อันดับ3"
    for pfx in _ORDINAL_PREFIX_LIST:
        if core.startswith(pfx) and len(core) > len(pfx):
            num_part = core[len(pfx):]
            n = _thai_num_to_int(num_part)
            if n is not None:
                return punct_pre + pfx + str(n) + punct_suf

    return word

_SSML_TAG_RE = re.compile(r'<[^>]+>')


def _clean_ssml_word(word: str) -> str:
    """
    Strip SSML fragments จาก word token ที่ ElevenLabs alignment ส่งมา
    Cases:
      '<break time="0.2s"/>'  → ''   (complete tag)
      '<break'                → ''   (partial open tag)
      'time="0.2s"/>10'       → '10' (partial close + content after >)
      'time="0.2s"/>'         → ''   (partial close only)
    """
    # 1. ลบ complete tags เช่น <break time="0.2s"/>
    w = _SSML_TAG_RE.sub('', word)
    # 2. partial open tag ที่เหลือ: ขึ้นต้นด้วย < แต่ไม่มี >
    if re.match(r'^<[^>]*$', w):
        return ''
    # 3. มี > เหลืออยู่ → เอาเฉพาะ text หลัง > ตัวสุดท้าย
    if '>' in w:
        w = w[w.rfind('>') + 1:]
    return w.strip()


_LONG_TOKEN_THRESHOLD = 8  # พยางค์ที่ถือว่า "token ยาวเกิน" → แยกด้วย pythainlp


def _split_long_token(word: str, ws: float, we: float) -> list:
    """ElevenLabs บางครั้งส่งทั้งประโยคมาเป็น 1 word token
    ถ้ายาวเกิน threshold → ตัดด้วย pythainlp แล้ว interpolate timing ตามสัดส่วนพยางค์"""
    if _count_syllables(word) <= _LONG_TOKEN_THRESHOLD:
        return [{"word": word, "start": ws, "end": we}]
    try:
        from pythainlp.tokenize import word_tokenize
        parts = [w for w in word_tokenize(word, engine="newmm", keep_whitespace=False) if w.strip()]
    except Exception:
        parts = []
    if len(parts) <= 1:
        return [{"word": word, "start": ws, "end": we}]
    sub_syls = [max(1, _count_syllables(p)) for p in parts]
    total = sum(sub_syls)
    dur = we - ws
    result, t = [], ws
    for p, s in zip(parts, sub_syls):
        frac = (s / total) * dur
        result.append({"word": p, "start": round(t, 4), "end": round(t + frac, 4)})
        t += frac
    return result


def _make_subtitle_chunks_v2(
    word_timings: list,
    max_syllables: int = 5,
) -> list:
    """
    Semantic-aware chunking:
      - num + unit (บาท/%) → own chunk เสมอ (ไม่ merge กับ text ก่อนหน้า)
      - freq mod (ต่อเดือน/ปีละ) → absorb เข้า text chunk ถ้าไม่มี num และ ≤ HARD_MAX
      - finance pair (หนี้ดี) → own atomic chunk เสมอ
      - ordinal prefix (ข้อ 1) → ติดกับตัวเลข
      - long single token (ทั้งประโยคใน 1 token) → split ด้วย pythainlp ก่อน
    """
    _TN_WORDS_SET = set(_TN_ALL) | {"เปอร์เซ็นต์", "เปอร์เซ็น"}
    _STRIP_PUNCT_NON_NUM_COMMA = re.compile(r'(?<!\d),|,(?!\d)|[!?;:—–…"\']')

    cleaned = []
    for wt in word_timings:
        w = _clean_ssml_word(wt.get("word", ""))
        if not w:
            continue
        # ลบ comma/punctuation ที่ติดมากับคำ (เช่น "คนญี่ปุ่น,")
        w = _STRIP_PUNCT_NON_NUM_COMMA.sub('', w).strip()
        if not w:
            continue
        # ห้าม convert Thai number words ก่อน merge — ต้องให้ merge phase รวม compound ก่อน
        # ครอบคลุม: คำใน _TN_WORDS_SET ("ล้าน","พัน",...) และ compound tens ("สี่สิบ","ยี่สิบ",...)
        # ที่ไม่ได้อยู่ใน set แต่ _thai_num_to_int parse ได้ → ต้องอยู่เป็น Thai ไว้ก่อน
        if w not in _TN_WORDS_SET and _thai_num_to_int(w) is None:
            w = _thai_word_to_arabic(w)
        cleaned.extend(_split_long_token(w, float(wt["start"]), float(wt["end"])))

    # Merge consecutive Thai number syllables ที่ ElevenLabs ส่งมาแยก
    # เช่น ["หนึ่ง","พัน","เก้า","ร้อย","สี่สิบ","เก้า"] → "1,949"
    # _is_tn: ครอบคลุม _TN_WORDS_SET + compound tens/ones ("สี่สิบ","ยี่สิบ") ที่ parse ได้
    def _is_tn(w: str) -> bool:
        return w in _TN_WORDS_SET or _thai_num_to_int(w) is not None

    _ARABIC_NUM_RE = re.compile(r'^\d+(?:[.,]\d+)*$')
    _UNIT_MULT_MAP = {'ล้าน': 1_000_000, 'แสน': 100_000, 'หมื่น': 10_000, 'พัน': 1_000}

    merged = []
    i = 0
    while i < len(cleaned):
        wt = cleaned[i]
        word = wt["word"]
        if _is_tn(word):
            # รวบ consecutive Thai number/unit words
            compound = word
            j = i + 1
            while j < len(cleaned) and _is_tn(cleaned[j]["word"]):
                compound += cleaned[j]["word"]
                j += 1
            converted = _thai_word_to_arabic(compound)
            merged.append({
                "word": converted,
                "start": wt["start"],
                "end": cleaned[j - 1]["end"],
            })
            i = j
        elif _ARABIC_NUM_RE.match(word) and i + 1 < len(cleaned) and cleaned[i+1]["word"] in _UNIT_MULT_MAP:
            # Safety net: Arabic digit + Thai unit แยกกัน เช่น "2" + "ล้าน" → "2,000,000"
            unit_wt = cleaned[i + 1]
            n = float(word.replace(',', ''))
            mult = _UNIT_MULT_MAP[unit_wt["word"]]
            result = int(n * mult)
            merged.append({
                "word": f"{result:,}",
                "start": wt["start"],
                "end": unit_wt["end"],
            })
            i += 2
        else:
            merged.append(wt)
            i += 1
    valid = merged

    if not valid:
        return []

    all_words = [wt["word"] for wt in valid]
    chunks: list = []
    cur_words: list = []
    cur_syl: int = 0

    def flush():
        nonlocal cur_words, cur_syl
        if cur_words:
            chunks.append({"words": cur_words, "is_keyword": False,
                           "color": "#FFFFFF", "font_size": 52})
            cur_words, cur_syl = [], 0

    i = 0
    while i < len(valid):
        wt   = valid[i]
        word = wt["word"]
        ws, we = float(wt["start"]), float(wt["end"])

        # ── Finance bond pair: หนี้ดี, ดอกเบี้ยสูง → own chunk ─────────────
        if word in _FIN_NOUNS and i + 1 < len(valid) and valid[i+1]["word"] in _FIN_ADJS:
            flush()
            nxt = valid[i+1]
            pair = [(word, ws, we),
                    (nxt["word"], float(nxt["start"]), float(nxt["end"]))]
            chunks.append({"words": pair, "is_keyword": False,
                           "color": "#FFFFFF", "font_size": 52})
            i += 2
            continue

        # ── Numeric word → always flush text, then build own num chunk ───────
        if _is_numeric_word(word):
            # ordinal prefix ติดอยู่ใน cur chunk (ข้อ 2, อันดับ 1)
            if cur_words and cur_words[-1][0] in _ORDINAL_PREFIXES:
                cur_words.append((word, ws, we))
                cur_syl += _count_syllables(word)
                i += 1
                continue

            flush()   # text chunk ก่อนหน้าออกก่อนเสมอ

            # สะสม unit words ที่ต้องอยู่กับตัวเลข (บาท, %, เดือน, ...)
            # research: currency amount + unit = semantic unit ห้ามแยก (OpusClip / Nimdzi guidelines)
            num_words = [(word, ws, we)]
            num_syl   = _count_syllables(word)
            j = i + 1
            while j < len(valid):
                nxt, nxt_syl = valid[j]["word"], _count_syllables(valid[j]["word"])
                # exact match หรือ compound word ที่ขึ้นต้นด้วย connector (เช่น "บาทต่อวัน" ขึ้นต้นด้วย "บาท")
                is_connector = nxt in _NUM_CONNECTORS or any(
                    nxt.startswith(c) and nxt != c and len(c) >= 3
                    for c in _NUM_CONNECTORS
                )
                if is_connector:
                    num_words.append((nxt, float(valid[j]["start"]), float(valid[j]["end"])))
                    num_syl += nxt_syl
                    j += 1
                elif _is_numeric_word(nxt) and num_syl + nxt_syl <= max_syllables:
                    num_words.append((nxt, float(valid[j]["start"]), float(valid[j]["end"])))
                    num_syl += nxt_syl
                    j += 1
                else:
                    break

            color = _get_keyword_color(i, all_words)
            fsize = 64 if len(num_words) == 1 else 56
            chunks.append({"words": num_words, "is_keyword": True,
                           "color": color, "font_size": fsize})
            i = j
            continue

        # ── Frequency modifier (ต่อเดือน/ปีละ) ──────────────────────────────
        if word in _FREQ_MODS:
            word_syl = _count_syllables(word)
            cur_has_num = any(_is_numeric_word(w) for w, _, _ in cur_words)
            # absorb เข้า text chunk ถ้า: ไม่มี num ใน cur และ syl รวม ≤ HARD_MAX
            if cur_words and not cur_has_num and cur_syl + word_syl <= HARD_MAX:
                cur_words.append((word, ws, we))
                cur_syl += word_syl
            else:
                flush()
                cur_words = [(word, ws, we)]
                cur_syl = word_syl
            i += 1
            continue

        # ── Regular word ─────────────────────────────────────────────────────
        word_syl = _count_syllables(word)
        if cur_syl + word_syl > max_syllables and cur_words:
            flush()
        cur_words.append((word, ws, we))
        cur_syl += word_syl
        i += 1

    flush()
    return chunks


def _make_subtitle_chunks(word_timings: list,
                          max_duration: float = 1.5,
                          pause_threshold: float = 0.3,
                          min_words: int = 3,
                          max_chars: int = 30) -> list:
    """
    Group คำตาม ElevenLabs word timestamps:
    - รวมคำที่พูดติดกัน (gap < pause_threshold) และ chunk < max_duration
    - ตัดเมื่อ pause > threshold, เกิน duration, หรือเพิ่มคำถัดไปแล้วจะเกิน max_chars
    - แต่ละ chunk ≥ min_words คำ ยกเว้น chunk สุดท้าย
    Returns: list of (text, start_sec, end_sec)
    """
    valid = [wt for wt in word_timings if wt.get("word", "").strip()]
    if not valid:
        return []

    chunks: list = []
    cur_words = [valid[0]["word"]]
    cur_start = float(valid[0]["start"])
    cur_end   = float(valid[0]["end"])

    for wt in valid[1:]:
        gap            = float(wt["start"]) - cur_end
        chunk_duration = float(wt["end"]) - cur_start
        has_min_words  = len(cur_words) >= min_words
        over_duration  = chunk_duration > max_duration
        over_pause     = gap > pause_threshold
        # ป้องกัน 3 บรรทัด: ถ้าเพิ่มคำนี้แล้วจะยาวเกิน max_chars → ตัดก่อน
        next_joined    = _join_thai_words(cur_words + [wt["word"]])
        over_chars     = len(next_joined) > max_chars

        if has_min_words and (over_pause or over_duration or over_chars):
            chunks.append((_join_thai_words(cur_words), cur_start, cur_end))
            cur_words = [wt["word"]]
            cur_start = float(wt["start"])
        else:
            cur_words.append(wt["word"])
        cur_end = float(wt["end"])

    if cur_words:
        chunks.append((_join_thai_words(cur_words), cur_start, cur_end))
    return chunks


def _make_subtitle_chunks_words(
    word_timings: list,
    max_duration: float = 2.0,
    pause_threshold: float = 0.35,
    min_words: int = 2,
    max_chars: int = 30,
    max_words: int = 5,
) -> list:
    """
    เหมือน _make_subtitle_chunks แต่ return per-word timings ต่อ chunk
    Returns: list of chunks, แต่ละ chunk = [(word, start, end), ...]
    Post-process: merge trailing chunk ที่มีแค่ 1 คำเข้า chunk ก่อนหน้า
    """
    valid = [wt for wt in word_timings if wt.get("word", "").strip()]
    if not valid:
        return []

    chunks: list = []
    cur = [(valid[0]["word"], float(valid[0]["start"]), float(valid[0]["end"]))]
    cur_start = float(valid[0]["start"])
    cur_end   = float(valid[0]["end"])

    for wt in valid[1:]:
        word  = wt["word"]
        ws    = float(wt["start"])
        we    = float(wt["end"])
        gap            = ws - cur_end
        chunk_duration = we - cur_start
        has_min        = len(cur) >= min_words
        over_dur       = chunk_duration > max_duration
        over_pause     = gap > pause_threshold
        next_joined    = _join_thai_words([w for w, _, _ in cur] + [word])
        over_chars     = len(next_joined) > max_chars
        over_words     = len(cur) >= max_words  # hard cap: ห้ามเกิน max_words คำ

        if over_words or (has_min and (over_pause or over_dur or over_chars)):
            chunks.append(cur)
            cur = [(word, ws, we)]
            cur_start = ws
        else:
            cur.append((word, ws, we))
        cur_end = we

    if cur:
        chunks.append(cur)

    # Merge trailing 1-word chunk เข้า chunk ก่อนหน้า เฉพาะถ้าไม่เกิน max_words
    if len(chunks) >= 2 and len(chunks[-1]) == 1 and len(chunks[-2]) < max_words:
        chunks[-2] = chunks[-2] + chunks[-1]
        chunks.pop()

    return chunks


# ─── Style dataclass ──────────────────────────────────────────────────────────

@dataclass
class SubStyle:
    font_size: int = 72
    color: str = "#FFFFFF"
    stroke_color: str = "#000000"
    stroke_width: int = 8
    max_chars: int = 12
    position_pct: float = 0.75
    backdrop_opacity: float = 0.45  # semi-transparent black pill
    pad_x: int = 32                 # backdrop horizontal padding
    pad_y: int = 16                 # backdrop vertical padding
    corner_radius: int = 22         # pill corner radius

    @classmethod
    def from_config(cls, cfg: dict) -> "SubStyle":
        v = cfg.get("video", {})
        s = cfg.get("subtitle", {})
        return cls(
            font_size       = int(v.get("font_size", 72)),
            color           = s.get("color", "#FFFFFF"),
            stroke_color    = s.get("stroke_color", "#000000"),
            stroke_width    = int(s.get("stroke_width", 8)),
            max_chars       = int(s.get("max_chars_per_line", 12)),
            position_pct    = float(s.get("position_pct", 0.75)),
            backdrop_opacity= float(s.get("backdrop_opacity", 0.45)),
        )


# ─── Pango+Cairo renderer (primary) ──────────────────────────────────────────

def _hex_to_rgba_float(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)


def _rounded_rect(ctx, x: float, y: float, w: float, h: float, r: float):
    """Cairo path สำหรับ rounded rectangle"""
    ctx.new_path()
    ctx.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
    ctx.arc(x + w - r, y + r,     r, 3 * math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0,              math.pi / 2)
    ctx.arc(x + r,     y + h - r, r, math.pi / 2,   math.pi)
    ctx.close_path()


def _make_layout(ctx, text: str, font_size: float, canvas_w: int,
                 pangocffi, pangocairocffi):
    layout = pangocairocffi.create_layout(ctx)
    fd = pangocffi.FontDescription()
    fd.family = _PRIMARY_THAI_FONT
    fd.weight = pangocffi.Weight.BOLD
    fd.size = pangocffi.units_from_double(font_size)
    layout.font_description = fd
    layout.text = text
    layout.alignment = pangocffi.Alignment.CENTER
    layout.width = pangocffi.units_from_double(canvas_w)
    return layout


def _measure_natural_width(ctx, text: str, font_size: float,
                           pangocffi, pangocairocffi) -> float:
    """Unconstrained pixel width of text (no layout-width cap)"""
    if not text:
        return 0.0
    lo = pangocairocffi.create_layout(ctx)
    fd = pangocffi.FontDescription()
    fd.family = _PRIMARY_THAI_FONT
    fd.weight = pangocffi.Weight.BOLD
    fd.size = pangocffi.units_from_double(font_size)
    lo.font_description = fd
    lo.text = text
    _, lg = lo.get_extents()
    return pangocffi.units_to_double(lg.width)


def _try_pango_render(
    lines: list, canvas_w: int, canvas_h: int,
    style: SubStyle, output_path: str,
) -> bool:
    """Pango+Cairo render — Bold, backdrop pill, auto-scale"""
    try:
        import os as _os
        _os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
        import cairocffi as cairo
        import pangocffi
        import pangocairocffi

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
        ctx = cairo.Context(surface)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        fr, fg, fb, fa = _hex_to_rgba_float(style.color)
        sr, sg, sb, _  = _hex_to_rgba_float(style.stroke_color)
        sw = style.stroke_width

        # font size คงที่ตาม config — ไม่ dynamic scale
        font_size = style.font_size

        # pass 0: วัด actual extents ของแต่ละบรรทัด
        # line_gap เพิ่มจาก 0.18 → 0.50 เพื่อไม่ให้สระ/วรรณยุกต์ไทยทับกันระหว่างบรรทัด
        line_gap = font_size * 0.50
        measured = []
        for line in lines:
            layout = _make_layout(ctx, line, font_size, canvas_w, pangocffi, pangocairocffi)
            _, logical = layout.get_extents()
            lh = pangocffi.units_to_double(logical.height)
            lw = _measure_natural_width(ctx, line, font_size, pangocffi, pangocairocffi)
            measured.append((line, layout, lh, lw))

        # คำนวณ block geometry
        total_h   = sum(lh for _, _, lh, _ in measured)
        block_h   = total_h + line_gap * (len(measured) - 1)
        block_w   = max(lw for _, _, _, lw in measured)
        y_center  = canvas_h * style.position_pct
        y_start   = y_center - block_h / 2

        # backdrop pill (semi-transparent black rounded rect)
        px, py = style.pad_x, style.pad_y
        r = style.corner_radius
        bd_x = (canvas_w - block_w) / 2 - px
        bd_y = y_start - py
        bd_w = block_w + px * 2
        bd_h = block_h + py * 2
        ctx.set_source_rgba(0, 0, 0, style.backdrop_opacity)
        _rounded_rect(ctx, bd_x, bd_y, bd_w, bd_h, r)
        ctx.fill()

        # pass 1+2: render text (outline + fill)
        cur_y = y_start
        for line, layout, lh, lw in measured:
            ctx.set_source_rgba(sr, sg, sb, 1.0)
            ctx.move_to(0, cur_y)
            pangocairocffi.layout_path(ctx, layout)
            ctx.set_line_width(sw * 2)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()

            ctx.set_source_rgba(fr, fg, fb, fa)
            ctx.move_to(0, cur_y)
            pangocairocffi.show_layout(ctx, layout)

            cur_y += lh + line_gap

        surface.write_to_png(output_path)
        return True

    except Exception as e:
        logger.debug(f"Pango render failed: {e}")
        return False


def _get_font() -> Optional[str]:
    if SARABUN_FONT.exists():
        return str(SARABUN_FONT)
    if FALLBACK_FONT.exists() and FALLBACK_FONT.stat().st_size > 50_000:
        return str(FALLBACK_FONT)
    logger.warning("ไม่พบ Thai font — subtitle อาจแสดงผิด")
    return None


def render_subtitle_png(
    text: str,
    canvas_w: int,
    canvas_h: int,
    style: SubStyle,
    output_path: str,
) -> bool:
    """
    สร้าง PNG subtitle — Pango first (Thai shaping), fallback ImageMagick
    """
    lines = wrap_text(text, style.max_chars)

    # ─── Primary: Pango+Cairo ────────────────────────────────────────────────
    if _try_pango_render(lines, canvas_w, canvas_h, style, output_path):
        return True

    # ─── Fallback: ImageMagick -draw ─────────────────────────────────────────
    logger.warning("Pango unavailable → ImageMagick fallback")
    font = _get_font()
    label = "\n".join(lines)
    offset_y = int(canvas_h * (style.position_pct - 0.5))
    sw = style.stroke_width * 2
    draw_pos = f"text 0,{offset_y}"

    cmd = ["magick", "-size", f"{canvas_w}x{canvas_h}", "xc:transparent"]
    if font:
        cmd += ["-font", font]
    cmd += [
        "-pointsize", str(style.font_size), "-gravity", "Center",
        "-fill", style.stroke_color, "-stroke", style.stroke_color,
        "-strokewidth", str(sw), "-draw", f"{draw_pos} '{label}'",
        "-fill", style.color, "-stroke", "none",
        "-draw", f"{draw_pos} '{label}'",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(f"magick subtitle failed: {result.stderr[-300:]}")
        return False
    return True


# ─── Cinematic subtitle render ────────────────────────────────────────────────

_CAPCUT_WINDOW = 3  # คำที่แสดงต่อ frame


def render_capcut_png(
    words: list,
    active_idx: int,
    canvas_w: int,
    canvas_h: int,
    style: SubStyle,
    output_path: str,
) -> bool:
    """
    Cinematic subtitle: 3 คำปัจจุบัน ทั้งหมดสีเหลือง 1 บรรทัด กลางจอ
    ไม่มี dim white — แค่ข้อความสีเหลืองชัดเจน + backdrop pill พอดีข้อความ
    """
    try:
        import os as _os
        _os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
        import cairocffi as cairo
        import pangocffi
        import pangocairocffi

        # ── 1. 3-word window ──────────────────────────────────────────────────
        chunk_start = (active_idx // _CAPCUT_WINDOW) * _CAPCUT_WINDOW
        chunk_words = words[chunk_start : chunk_start + _CAPCUT_WINDOW]
        text = " ".join(chunk_words)

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
        ctx = cairo.Context(surface)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        sr, sg, sb, _ = _hex_to_rgba_float(style.stroke_color)
        sw = style.stroke_width
        font_size = style.font_size

        # auto-scale: บังคับ 1 บรรทัด ไม่เกิน 85% canvas width
        lw = _measure_natural_width(ctx, text, font_size, pangocffi, pangocairocffi)
        max_w = canvas_w * 0.85
        if lw > max_w:
            font_size = max(int(font_size * max_w / lw), 40)
            lw = _measure_natural_width(ctx, text, font_size, pangocffi, pangocairocffi)

        # ── 2. วัด height ────────────────────────────────────────────────────
        layout = _make_layout(ctx, text, font_size, canvas_w, pangocffi, pangocairocffi)
        _, logical = layout.get_extents()
        lh = pangocffi.units_to_double(logical.height)

        # ตำแหน่ง: กึ่งกลางแนวตั้งตาม position_pct
        y_center = canvas_h * style.position_pct
        y_text   = y_center - lh / 2

        # ── 3. Backdrop pill พอดีข้อความ ─────────────────────────────────────
        px, py = style.pad_x, style.pad_y
        bd_x = (canvas_w - lw) / 2 - px
        bd_y = y_text - py
        bd_w = lw + px * 2
        bd_h = lh + py * 2
        ctx.set_source_rgba(0, 0, 0, style.backdrop_opacity)
        _rounded_rect(ctx, bd_x, bd_y, bd_w, bd_h, style.corner_radius)
        ctx.fill()

        # ── 4. Render ข้อความสีเหลืองทั้งบรรทัด ────────────────────────────
        # outline ดำก่อน
        ctx.set_source_rgba(sr, sg, sb, 1.0)
        ctx.move_to(0, y_text)
        pangocairocffi.layout_path(ctx, layout)
        ctx.set_line_width(sw * 2)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()

        # fill เหลือง (#FFE033)
        ctx.set_source_rgba(1.0, 0.878, 0.2, 1.0)
        ctx.move_to(0, y_text)
        pangocairocffi.show_layout(ctx, layout)

        surface.write_to_png(output_path)
        return True

    except Exception as e:
        logger.debug(f"Cinematic subtitle render failed: {e} — fallback")
        return render_subtitle_png(" ".join(words), canvas_w, canvas_h, style, output_path)


def render_karaoke_png(
    words: list,
    active_idx: int,
    canvas_w: int,
    canvas_h: int,
    style: SubStyle,
    output_path: str,
    chunk_color: str = None,        # None=karaoke mode; set=all words this color
    font_size_override: int = None, # None=use style.font_size
) -> bool:
    """
    CapCut-style karaoke subtitle:
    - karaoke mode: active=yellow, spoken=dim, upcoming=white
    - keyword mode (chunk_color set): all words rendered in chunk_color
    - font_size_override: กำหนด size แทน style.font_size
    """
    try:
        import os as _os
        _os.environ.setdefault("DYLD_LIBRARY_PATH", "/opt/homebrew/lib")
        import cairocffi as cairo
        import pangocffi
        import pangocairocffi

        if not words:
            return False

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
        ctx = cairo.Context(surface)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        sw        = style.stroke_width
        font_size = font_size_override if font_size_override is not None else style.font_size

        full_text = _join_thai_words(words)

        # Auto-scale ให้พอดี 1 บรรทัด (ไม่ wrap)
        total_w = _measure_natural_width(ctx, full_text, font_size, pangocffi, pangocairocffi)
        max_w   = canvas_w * 0.88
        if total_w > max_w and total_w > 0:
            font_size = max(int(font_size * max_w / total_w), 34)
            total_w   = _measure_natural_width(ctx, full_text, font_size, pangocffi, pangocairocffi)

        # วัดความสูงบรรทัด
        ref = pangocairocffi.create_layout(ctx)
        rfd = pangocffi.FontDescription()
        rfd.family = _PRIMARY_THAI_FONT
        rfd.weight = pangocffi.Weight.BOLD
        rfd.size   = pangocffi.units_from_double(font_size)
        ref.font_description = rfd
        ref.text = full_text or "ก"
        _, rlg   = ref.get_extents()
        line_h   = pangocffi.units_to_double(rlg.height)

        y_center = canvas_h * style.position_pct
        y_text   = y_center - line_h / 2
        x_start  = (canvas_w - total_w) / 2

        # Backdrop pill
        px, py = style.pad_x, style.pad_y
        ctx.set_source_rgba(0, 0, 0, style.backdrop_opacity)
        _rounded_rect(ctx, x_start - px, y_text - py,
                      total_w + px * 2, line_h + py * 2, style.corner_radius)
        ctx.fill()

        # หา char offset ของแต่ละคำใน full_text (สำหรับ pixel positioning)
        word_offsets = []
        search_pos   = 0
        for w in words:
            idx = full_text.find(w, search_pos)
            word_offsets.append(idx if idx >= 0 else search_pos)
            search_pos = (idx if idx >= 0 else search_pos) + len(w)

        if chunk_color:
            # Static mode — render ทั้ง chunk เป็น 1 layout: outline+fill รอบทั้งหมด, centered
            fill_rgba = _hex_to_rgba_float(chunk_color)
            lo = _make_layout(ctx, full_text, font_size, canvas_w, pangocffi, pangocairocffi)
            ctx.set_source_rgba(0, 0, 0, 1.0)   # solid black stroke
            ctx.move_to(0, y_text)
            pangocairocffi.layout_path(ctx, lo)
            ctx.set_line_width(sw * 2)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()
            ctx.set_source_rgba(*fill_rgba)
            ctx.move_to(0, y_text)
            pangocairocffi.show_layout(ctx, lo)
        else:
            # Karaoke mode — วาดแต่ละคำ ณ ตำแหน่งที่ถูกต้อง
            for i, word in enumerate(words):
                prefix   = full_text[:word_offsets[i]]
                prefix_w = (_measure_natural_width(ctx, prefix, font_size, pangocffi, pangocairocffi)
                            if prefix else 0.0)
                x = x_start + prefix_w
                if i == active_idx:
                    fill_rgba = _hex_to_rgba_float(style.color)
                else:
                    r2, g2, b2, _ = _hex_to_rgba_float(style.color)
                    fill_rgba = (r2, g2, b2, 0.40)
                lo = pangocairocffi.create_layout(ctx)
                lfd = pangocffi.FontDescription()
                lfd.family = _PRIMARY_THAI_FONT
                lfd.weight = pangocffi.Weight.BOLD
                lfd.size   = pangocffi.units_from_double(font_size)
                lo.font_description = lfd
                lo.text = word
                ctx.set_source_rgba(0, 0, 0, 1.0)
                ctx.move_to(x, y_text)
                pangocairocffi.layout_path(ctx, lo)
                ctx.set_line_width(sw * 2)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.stroke()
                ctx.set_source_rgba(*fill_rgba)
                ctx.move_to(x, y_text)
                pangocairocffi.show_layout(ctx, lo)

        surface.write_to_png(output_path)
        return True

    except Exception as e:
        logger.debug(f"Karaoke render failed: {e} — fallback to chunk subtitle")
        return render_subtitle_png(
            _join_thai_words(words), canvas_w, canvas_h, style, output_path
        )


# ─── Overlay subtitle PNG onto video clip (ffmpeg) ───────────────────────────

def overlay_subtitle_on_clip(
    video_path: str,
    subtitle_png: str,
    output_path: str,
    vcodec: str = "libx264",
    crf: int = 18,
    encode_args: list = None,
) -> str:
    """ffmpeg overlay: subtitle PNG (RGBA) on top of video"""
    enc = encode_args if encode_args else ["-c:v", vcodec, "-crf", str(crf)]
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-loop", "1", "-i", subtitle_png,
        "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1",
        *enc,
        "-an",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"ffmpeg overlay failed:\n{result.stderr[-400:]}")
        raise RuntimeError("ffmpeg overlay subtitle failed")
    return output_path


# ─── Postprocess: fix Thai digits in .srt / .ass files ───────────────────────

def fix_subtitle_file(path: str) -> str:
    """อ่านไฟล์ subtitle แล้ว replace เลขไทย → อาหรับ ทุกบรรทัด"""
    p = Path(path)
    if not p.exists():
        return path
    original = p.read_text(encoding="utf-8-sig", errors="replace")
    fixed = fix_thai_digits(original)
    if fixed != original:
        p.write_text(fixed, encoding="utf-8-sig")
        logger.info(f"Fixed Thai digits in: {p.name}")
    return path
