import base64
import os
import time
import requests
from pathlib import Path
from loguru import logger
from pydub import AudioSegment


ELEVEN_MODEL = "eleven_v3"  # most expressive, confirmed Thai support + timestamps

# ─── Thai number conversion ───────────────────────────────────────────────────

_TH_ONES = ['', 'หนึ่ง', 'สอง', 'สาม', 'สี่', 'ห้า', 'หก', 'เจ็ด', 'แปด', 'เก้า']


def _int_to_thai(n: int) -> str:
    """แปลงจำนวนเต็มเป็นคำอ่านภาษาไทย
    เพิ่ม space ระหว่าง component เพื่อให้ ElevenLabs อ่านแต่ละหน่วยถูกต้อง
    เช่น 210,000 → 'สอง แสน หนึ่ง หมื่น' แทน 'สองแสนหนึ่งหมื่น'
    """
    if n == 0:
        return 'ศูนย์'
    if n < 0:
        return 'ลบ ' + _int_to_thai(-n)
    parts = []
    for value, unit in [
        (1_000_000, 'ล้าน'), (100_000, 'แสน'),
        (10_000, 'หมื่น'), (1_000, 'พัน'), (100, 'ร้อย'),
    ]:
        if n >= value:
            parts.append(_int_to_thai(n // value))
            parts.append(unit)
            n %= value
    if n >= 10:
        tens, ones = divmod(n, 10)
        tens_word = ('ยี่สิบ' if tens == 2 else ('สิบ' if tens == 1 else _TH_ONES[tens] + 'สิบ'))
        if ones == 1:
            parts.append(tens_word + 'เอ็ด')
        elif ones > 0:
            parts.append(tens_word + _TH_ONES[ones])
        else:
            parts.append(tens_word)
    elif n > 0:
        parts.append(_TH_ONES[n])
    return ' '.join(parts)


def _normalize_numbers_for_tts(text: str) -> str:
    """
    แปลงตัวเลขเป็นคำอ่านไทยก่อนส่ง TTS:
    - 30,000 → สามหมื่น  |  1,500 → หนึ่งพันห้าร้อย
    - 4.5%   → สี่จุดห้าเปอร์เซ็นต์
    - ข้อ 1 / อันดับ 3 / ที่ 1 → ไม่แปลง (ordinal context)
    """
    import re as _re

    # 1. ป้องกัน ordinal context — wrap ด้วย ⟦...⟧ ก่อน
    text = _re.sub(
        r'((?:ข้อ|อันดับ|ที่|ลำดับ)\s*)(\d+)',
        lambda m: m.group(1) + '⟦' + m.group(2) + '⟧',
        text,
    )

    # 2a. range% → Thai  e.g. 5-10% → ห้าถึงสิบเปอร์เซ็นต์
    def _range_pct(m):
        a = float(m.group(1))
        b = float(m.group(2))
        def _num(v):
            if v == int(v):
                return _int_to_thai(int(v))
            i, d = str(v).split('.')
            return _int_to_thai(int(i)) + 'จุด' + _int_to_thai(int(d))
        return _num(a) + 'ถึง' + _num(b) + 'เปอร์เซ็นต์'
    text = _re.sub(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\s*%', _range_pct, text)

    # 2b. decimal% → Thai
    def _dec_pct(m):
        return (_int_to_thai(int(m.group(1))) + 'จุด'
                + _int_to_thai(int(m.group(2))) + 'เปอร์เซ็นต์')
    text = _re.sub(r'(\d+)\.(\d+)\s*%', _dec_pct, text)

    # 3. integer% → Thai
    text = _re.sub(r'(\d+)\s*%',
                   lambda m: _int_to_thai(int(m.group(1))) + 'เปอร์เซ็นต์', text)

    # 4. comma-numbers ≥ 1,000 → Thai
    text = _re.sub(r'\b\d{1,3}(?:,\d{3})+\b',
                   lambda m: _int_to_thai(int(m.group(0).replace(',', ''))), text)

    # 4b. plain integers ≥ 1,000 (4+ digits, no commas) → Thai
    # ยกเว้น ปีพ.ศ. (2480-2600) และ ปี ค.ศ. (1800-2100) — ElevenLabs อ่านได้เองถูกต้อง
    # การแปลงปีเป็น Thai ทำให้ token count ไม่ตรง → subtitle realign พัง
    def _maybe_thai(m):
        n = int(m.group(1))
        if (1800 <= n <= 2100) or (2480 <= n <= 2600):
            return m.group(1)   # year → คงไว้เป็น Arabic
        return _int_to_thai(n)

    text = _re.sub(r'\b(\d{4,})\b', _maybe_thai, text)

    # 5. restore ordinals
    text = _re.sub(r'⟦(\d+)⟧', r'\1', text)

    return text


def _realign_display_words(original: str, word_timings: list) -> list:
    """
    แทนที่ text ใน word_timings ด้วย original tokens เพื่อให้ซับไตเติ้ลแสดง Arabic numbers
    1.5%/163,000 แทน หนึ่งจุดห้าเปอร์เซ็นต์/หนึ่งแสนหกหมื่นสามพัน

    Fuzzy realign: _normalize_numbers_for_tts ขยาย 1 orig token → N TTS tokens
    เช่น "163,000" → "หนึ่ง แสน หก หมื่น สาม พัน" (6 tokens)
    จับคู่โดยนับ expansion ของแต่ละ token แล้ว merge timing
    """
    if not word_timings:
        return word_timings
    orig_tokens = original.split()

    # fast path: exact match
    if len(orig_tokens) == len(word_timings):
        return [dict(wt, word=tok) for wt, tok in zip(word_timings, orig_tokens)]

    # fuzzy path: count how many TTS tokens each orig token expands to
    tts_counts = []
    for tok in orig_tokens:
        tts_tok = _normalize_numbers_for_tts(tok)
        tts_counts.append(len(tts_tok.split()))

    if sum(tts_counts) != len(word_timings):
        # Greedy char-match: TTS splits Thai tokens differently (no spaces)
        # e.g. orig "กรมการปกครองบอกว่า" → TTS gives ["กรมการปกครองบอก","ว่า"]
        # Merge TTS tokens until concatenation contains orig_token
        result = []
        wt_idx = 0
        ok = True
        for orig_tok in orig_tokens:
            target = orig_tok.replace(",", "")  # strip commas for matching
            accumulated = ""
            group_start = wt_idx
            while wt_idx < len(word_timings):
                accumulated += word_timings[wt_idx]["word"]
                wt_idx += 1
                if target in accumulated or accumulated in target:
                    break
            if group_start == wt_idx:
                ok = False
                break
            combined_start = word_timings[group_start]["start"]
            combined_end   = word_timings[wt_idx - 1]["end"]
            result.append({"word": orig_tok, "start": combined_start, "end": combined_end})
        if ok and wt_idx == len(word_timings):
            return result
        return word_timings  # can't reconcile → safe fallback

    result = []
    wt_idx = 0
    for tok, count in zip(orig_tokens, tts_counts):
        if count == 1:
            result.append(dict(word_timings[wt_idx], word=tok))
        else:
            # N TTS tokens → merge timing, show original Arabic display
            combined_start = word_timings[wt_idx]["start"]
            combined_end   = word_timings[wt_idx + count - 1]["end"]
            result.append({"word": tok, "start": combined_start, "end": combined_end})
        wt_idx += count
    return result


def _clean_tts_text(text: str) -> str:
    """ทำความสะอาด text ก่อนส่ง ElevenLabs — ลบทุกอย่างที่อาจทำให้เสียงเพี้ยน"""
    import re
    # ลบ emoji (unicode ranges)
    text = re.sub(r'[\U0001F300-\U0001FFFF]', '', text)
    text = re.sub(r'[☀-➿]', '', text)
    # em dash/en dash → จุลภาค (สร้าง pause)
    text = text.replace("—", ", ").replace("–", ", ")
    # ellipsis → จุด
    text = text.replace("…", ".")
    # ลบวงเล็บและเครื่องหมายพิเศษ (ยกเว้น <> เพราะจะใส่ SSML หลังจากนี้)
    text = re.sub(r'[«»\[\]{}()|\\^~`#@$*=+&]', '', text)
    # ลบ single/double quote
    text = re.sub(r"[\"\'']", '', text)
    # normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _add_ssml_breaks(text: str) -> str:
    """
    เพิ่ม SSML <break> ที่จุดหายใจธรรมชาติในภาษาไทย
    ทำให้เสียงพากหยุดถูกที่ ฟังแล้วได้ใจความ
    """
    import re

    # 1. หลังจุลภาค — pause กลาง (วลีเชื่อม)
    text = re.sub(r',\s*', ', <break time="0.30s"/>', text)

    # 2. ก่อน conjunctions ที่เริ่มวลีใหม่ — pause กลาง
    _CONJ = re.compile(
        r'(?<=[฀-๿\w])\s+'
        r'(แต่(?!ละ)|เพราะ(?!ฉะ)|ดังนั้น|จึง|ทำให้|ซึ่ง(?!กัน)|โดยที่|'
        r'แม้ว่า|ถึงแม้|เนื่องจาก|จนกระทั่ง|ทั้งที่|อย่างไรก็ตาม)'
    )
    text = _CONJ.sub(lambda m: f' <break time="0.35s"/>{m.group(1)}', text)

    # 3. ก่อนตัวเลข (เน้นตัวเลขสำคัญ เช่น 97%, 1,000,000 บาท)
    text = re.sub(r'(?<=[฀-๿ ])(\d)', r'<break time="0.20s"/>\1', text)

    # 4. ก่อน "คือ" ที่ขึ้นต้นคำอธิบาย
    text = re.sub(r'(?<=[฀-๿])\s+(คือ(?!\w))', r' <break time="0.25s"/>\1', text)

    return text

# Voice ที่ผ่านการทดสอบว่าออกเสียงภาษาไทยได้ชัดเจนและเป็นธรรมชาติ
THAI_VOICES: dict = {
    # ── ชาย ─────────────────────────────────────────────────────────────────
    "daniel": "onwK4e9ZLuTAKqWW03F9",   # Steady Broadcaster — ชัด สงบ ดูน่าเชื่อถือ
    "roger":  "CwhRBWXzGAHq8TQ4Fs17",   # Laid-back, Resonant — เป็นธรรมชาติ กันเอง
    "george": "JBFqnCBsd6RMkjVDRZzb",   # Warm Storyteller — อบอุ่น น่าฟัง
    # ── หญิง ────────────────────────────────────────────────────────────────
    "sarah":  "EXAVITQu4vr4xnSDxMaL",   # Mature, Reassuring — สุขุม น่าเชื่อถือ
    "jessica":"cgSgspJ2msm6clMCkdW9",   # Playful, Bright — สดใส เป็นกันเอง
    "alice":  "Xb7hH8MSUJpSbSDYk0k2",   # Clear, Engaging — ชัดเจน น่าฟัง
}

# Default สำหรับแต่ละเพศ
DEFAULT_MALE_VOICE   = "roger"    # Laid-back, Resonant — นุ่ม กันเอง เป็นธรรมชาติ
DEFAULT_FEMALE_VOICE = "jessica"  # Playful, Bright — สดใส นุ่ม เป็นกันเอง


# ─── ตรวจ gender จากคำลงท้ายในสคริปต์ ──────────────────────────────────────

def detect_voice_gender(sentences: list) -> str:
    """
    ตรวจจับเพศผู้พูดจากคำลงท้ายในสคริปต์
    - "ครับ" / "นะครับ" → male
    - "ค่ะ" / "นะคะ" / "คะ" → female
    คืนค่า "male" หรือ "female"
    """
    text = " ".join(sentences)
    male_hits   = sum(text.count(w) for w in ["ครับ", "นะครับ", "ล่ะครับ"])
    female_hits = sum(text.count(w) for w in ["ค่ะ", "นะคะ", "คะ", "จ้ะ", "น่ะคะ"])

    gender = "female" if female_hits > male_hits else "male"
    logger.info(f"Voice gender detect: male={male_hits} female={female_hits} → {gender}")
    return gender


# ─── ElevenLabs backend ──────────────────────────────────────────────────────

class ElevenLabsTTS:
    TS_URL  = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

    def __init__(self, api_key: str, voice_id: str = None):
        self.api_key = api_key
        self.voice_id = THAI_VOICES.get(voice_id or "", voice_id) or THAI_VOICES[DEFAULT_MALE_VOICE]

    def set_gender(self, gender: str):
        alias = DEFAULT_FEMALE_VOICE if gender == "female" else DEFAULT_MALE_VOICE
        self.voice_id = THAI_VOICES[alias]
        logger.info(f"ElevenLabs voice set: {gender} → {alias} ({self.voice_id[:20]})")

    def synthesize(self, text: str, output_path: Path) -> dict:
        """เรียก with-timestamps endpoint → คืน {duration, word_timings} (retry 3 ครั้ง)"""
        clean = _clean_tts_text(text)
        clean = _normalize_numbers_for_tts(clean)  # 30,000→สามหมื่น, 4.5%→สี่จุดห้าฯ
        # หมายเหตุ: ไม่ใช้ _add_ssml_breaks — SSML tags ใน eleven_v3 ทำให้ alignment chars
        # มี space ภายใน tag → _parse_word_timings split token เกิน → fuzzy realign พัง
        # → "หนึ่ง"+"ล้าน" แยกกัน → "1 1,000,000" ใน subtitle / <break> โผล่ในซับ
        # ElevenLabs v3 handle pause ที่ comma/period ได้เองแล้ว
        payload = {
            "text": clean,
            "model_id": ELEVEN_MODEL,
            "voice_settings": {
                "stability": 0.22,       # ลดลง = น้ำเสียงมีพลัง ขึ้นลงตามอารมณ์ (finance hook ต้องดึงดูด)
                "similarity_boost": 0.88,
                "style": 0.65,           # เพิ่มขึ้น = เสียงชัด มีอารมณ์ ไม่แข็งทื่อ
                "use_speaker_boost": True,
            },
        }
        payload["language_code"] = "th"  # eleven_v3 + eleven_turbo support Thai
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_err = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    self.TS_URL.format(voice_id=self.voice_id),
                    headers=headers, json=payload, timeout=60,
                )
                resp.raise_for_status()
                break
            except requests.HTTPError as e:
                last_err = e
                wait = 2 ** attempt
                logger.warning(f"ElevenLabs HTTP {resp.status_code} (attempt {attempt+1}/3) — retry in {wait}s")
                time.sleep(wait)
        else:
            raise last_err
        data = resp.json()

        audio_bytes = base64.b64decode(data["audio_base64"])
        output_path.write_bytes(audio_bytes)
        duration = len(AudioSegment.from_mp3(str(output_path))) / 1000.0

        word_timings = self._parse_word_timings(
            data.get("alignment", {}),
            data.get("normalized_alignment", {}),
        )
        return {"duration": duration, "word_timings": word_timings}

    # ─── word timing parser ────────────────────────────────────────────────────

    def _parse_word_timings(self, alignment: dict, normalized: dict) -> list:
        """
        Group ElevenLabs character-level timestamps → word-level โดยแบ่งที่ space
        สำคัญ: ใช้ alignment.characters เสมอ (ตัวอักษรไทยที่ส่งไป)
        normalized_alignment.characters = romanized IPA — ห้ามใช้เป็นข้อความแสดงผล
        """
        orig_chars = alignment.get("characters", [])
        if not orig_chars:
            return []

        # timing จาก normalized แม่นยำกว่า — ใช้ถ้ามี
        starts = (normalized.get("character_start_times_seconds")
                  or alignment.get("character_start_times_seconds", []))
        ends   = (normalized.get("character_end_times_seconds")
                  or alignment.get("character_end_times_seconds", []))

        import re as _re
        _PUNCT = _re.compile(r'^[,.\-!?;:—–…\'"()\[\]]+$')

        words, cur, c_start, c_end = [], "", None, None
        in_tag = False   # skip chars inside SSML <tag> — belt-and-suspenders
        for i, ch in enumerate(orig_chars):
            s = starts[i] if i < len(starts) else 0.0
            e = ends[i]   if i < len(ends)   else 0.0
            # SSML tag guard: skip <...> entirely (ไม่ให้ <break> โผล่ใน subtitle)
            if ch == "<":
                in_tag = True
                continue
            if in_tag:
                if ch == ">":
                    in_tag = False
                continue
            if ch == " ":
                if cur and not _PUNCT.match(cur):
                    words.append({"word": cur, "start": c_start, "end": c_end})
                cur, c_start = "", None
            else:
                cur += ch
                if c_start is None:
                    c_start = s
                c_end = e
        if cur and not _PUNCT.match(cur):
            words.append({"word": cur, "start": c_start, "end": c_end})
        return words


# ─── gTTS fallback ───────────────────────────────────────────────────────────

class GTTSEngine:
    def __init__(self, language: str = "th", slow: bool = False):
        self.language = language
        self.slow = slow

    def synthesize(self, text: str, output_path: Path) -> float:
        from gtts import gTTS
        gTTS(text=text, lang=self.language, slow=self.slow).save(str(output_path))
        return len(AudioSegment.from_mp3(str(output_path))) / 1000.0


# ─── Unified TTSEngine ────────────────────────────────────────────────────────

class TTSEngine:
    def __init__(self, config: dict):
        cfg = config["tts"]
        self.pause_ms = int(cfg.get("pause_between", 0.3) * 1000)

        eleven_key = os.getenv("ELEVENLABS_API_KEY")
        want_eleven = cfg.get("engine") == "elevenlabs"

        if want_eleven and eleven_key:
            # Custom voice cloning: ELEVENLABS_VOICE_ID ใน .env override ทุกอย่าง
            voice_id = os.getenv("ELEVENLABS_VOICE_ID") or cfg.get("voice_id") or ""
            self._custom_voice = bool(os.getenv("ELEVENLABS_VOICE_ID"))
            self._backend = ElevenLabsTTS(eleven_key, voice_id)
            source = "custom/cloned" if self._custom_voice else "default"
            logger.info(f"TTS: ElevenLabs {ELEVEN_MODEL} | voice={self._backend.voice_id[:20]} ({source})")
        else:
            if want_eleven and not eleven_key:
                logger.warning("ELEVENLABS_API_KEY ไม่ได้ตั้งค่า → fallback gTTS")
            self._backend = GTTSEngine(cfg.get("language", "th"), cfg.get("slow", False))
            logger.info("TTS: gTTS (th)")

    def auto_set_voice(self, sentences: list, framework: str = ""):
        """ใช้เสียงชายเสมอ (roger) — fixed ไม่เปลี่ยนตาม framework หรือสคริปต์"""
        if not isinstance(self._backend, ElevenLabsTTS):
            return
        if getattr(self, "_custom_voice", False):
            logger.info("Voice: cloned voice active → skip")
            return
        self._backend.set_gender("male")
        logger.info("Voice: male (fixed)")

    @staticmethod
    def _split_long_sentence(sentence: str, max_len: int = 80) -> list:
        """แยกประโยคที่ยาวเกิน max_len ออกเป็น 2 ที่จุดที่เป็นธรรมชาติ"""
        if len(sentence) <= max_len:
            return [sentence]
        # หา space ใกล้กึ่งกลาง
        mid = len(sentence) // 2
        for offset in range(0, mid):
            for pos in (mid + offset, mid - offset):
                if 0 < pos < len(sentence) and sentence[pos] == " ":
                    return [sentence[:pos].strip(), sentence[pos+1:].strip()]
        return [sentence]  # ตัดไม่ได้ → ส่งทั้งประโยค

    # ─── ElevenLabs safety filter ────────────────────────────────────────────
    _RISKY_PATTERNS = [
        # direct investment commands
        r"ซื้อ\s*(หุ้น|กองทุน|คริปโต|บิตคอย)",
        r"ลงทุนใน\w+ทันที",
        r"คุณควร(ซื้อ|ขาย|ลงทุน)",
        r"แนะนำให้(ซื้อ|ขาย|โอน|ลงทุน)",
        r"รับประกัน(ผลตอบแทน|กำไร|รายได้)",
        r"(ผลตอบแทน|กำไร).{0,10}(แน่นอน|รับประกัน|การันตี)",
    ]

    @staticmethod
    def _educational_disclaimer() -> str:
        return "เนื้อหานี้เป็นข้อมูลเพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำทางการเงิน"

    def _safe_sentences(self, sentences: list) -> list:
        """ตรวจ + softens ประโยคที่อาจ trigger ElevenLabs content policy"""
        import re
        safe = []
        for s in sentences:
            flagged = any(re.search(p, s) for p in self._RISKY_PATTERNS)
            if flagged:
                logger.warning(f"TTS safety: softened → {s[:50]}")
                s = re.sub(r"คุณควร(ซื้อ|ขาย|ลงทุน)", r"ผู้เชี่ยวชาญมองว่าการ\1", s)
                s = re.sub(r"แนะนำให้(ซื้อ|ขาย|โอน|ลงทุน)", r"ข้อมูลที่ควรรู้คือการ\1", s)
                s = re.sub(r"รับประกัน(ผลตอบแทน|กำไร|รายได้)", r"มีโอกาสได้\1", s)
            safe.append(s)
        # ต่อท้ายด้วย disclaimer ถ้ายังไม่มี
        disclaimer = self._educational_disclaimer()
        if safe and disclaimer not in safe[-1]:
            safe.append(disclaimer)
        return safe

    def synthesize_all(self, sentences: list, audio_dir: str) -> list:
        audio_dir = Path(audio_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Safety filter ก่อน TTS
        sentences = self._safe_sentences(sentences)

        # แยกประโยคยาว > 80 chars ก่อน TTS
        expanded = []
        for s in sentences:
            expanded.extend(self._split_long_sentence(s, max_len=80))

        timing_data, cursor = [], 0.0
        for i, sentence in enumerate(expanded):
            path = audio_dir / f"s{i:04d}.mp3"
            result = self._backend.synthesize(sentence, path)

            # รองรับทั้ง dict (ElevenLabs with-timestamps) และ float (gTTS)
            if isinstance(result, dict):
                duration    = result["duration"]
                word_timings = result.get("word_timings", [])
                # คืนค่า display text กลับเป็น original (1.5% แทน หนึ่งจุดห้าเปอร์เซ็นต์)
                word_timings = _realign_display_words(sentence, word_timings)
            else:
                duration    = float(result)
                word_timings = []

            timing_data.append({
                "index": i,
                "text": sentence,   # original sentence (Arabic numbers) — ใช้สำหรับ SRT + fallback subtitle
                "audio_path": str(path),
                "start": cursor, "end": cursor + duration, "duration": duration,
                "word_timings": word_timings,
            })
            cursor += duration + (self.pause_ms / 1000.0)
            logger.debug(f"  [{i:02d}] {duration:.2f}s ({len(word_timings)} words): {sentence[:40]}")

        total = timing_data[-1]["end"] if timing_data else 0
        logger.info(f"TTS done: {len(expanded)} sentences | {total:.1f}s")
        return timing_data

    @staticmethod
    def merge_audio(timing_data: list, output_path: str) -> str:
        total_ms = int((timing_data[-1]["end"] + 0.5) * 1000)
        combined = AudioSegment.silent(duration=total_ms)
        for item in timing_data:
            seg = AudioSegment.from_mp3(item["audio_path"])
            combined = combined.overlay(seg, position=int(item["start"] * 1000))
        combined.export(str(output_path), format="mp3")
        logger.info(f"Audio merged → {output_path}")
        return str(output_path)
