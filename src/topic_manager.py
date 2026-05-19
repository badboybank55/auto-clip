import json
import re
from datetime import datetime
from pathlib import Path

import anthropic
from loguru import logger

DATA_FILE = Path("data/topics.json")

_MIN_TOPIC_LEN = 10   # topic สั้นกว่านี้ = corrupted / ไม่มีคุณค่า
_MIN_SCORE     = 7    # คะแนน surprise factor ขั้นต่ำก่อนเข้าคิว

_PROMPT_TEMPLATE = """\
สร้าง {n} หัวข้อวิดีโอสั้น TikTok สำหรับช่องการเงิน "เงินงอก" — ผู้ชมคนไทย อายุ 20-40 ปี

━━━ สูตรหัวข้อที่ดี (บังคับ) ━━━
ทุกหัวข้อต้องมีทั้ง 2 ส่วน:
  [สิ่งที่น่าตกใจหรือไม่รู้] + [ตัวเลข/fact จริงที่พิสูจน์ได้]

━━━ FORMAT ต้องหลากหลาย — ห้ามใช้ "ทำไม..." หรือ "กับดัก..." เกิน 3 หัวข้อใน batch ━━━
บังคับมีแต่ละ format อย่างน้อย 1 หัวข้อ:

  [เปรียบเทียบ] "X vs Y — ใน 10 ปี ต่างกัน Z บาท"
    ตัวอย่าง: "ฝากออมทรัพย์ vs กองทุนตลาดเงิน 10 ปี — ต่างกันถึง 185,000 บาท"
    ตัวอย่าง: "หุ้นไทย SET vs หุ้นสหรัฐ S&P500 ย้อนหลัง 20 ปี ต่างกัน 3 เท่า"
    ตัวอย่าง: "เช่าบ้าน vs ผ่อนบ้าน 30 ปี — คณิตศาสตร์บอกอะไร"

  [จัดอันดับ] "5 อันดับ X ที่ Y มากที่สุด"
    ตัวอย่าง: "5 สกุลเงินแข็งที่สุดในโลก — อันดับ 1 ไม่ใช่ดอลลาร์"
    ตัวอย่าง: "3 กองทุนรวมไทยที่ค่าธรรมเนียมถูกที่สุดในหมวดเดียวกัน"
    ตัวอย่าง: "4 ประเทศที่ภาษีเงินได้ต่ำที่สุดในอาเซียน — ไทยอยู่อันดับไหน"

  [เรื่องโลก/ประวัติศาสตร์] "เหตุการณ์จริง + ตัวเลขผลกระทบ"
    ตัวอย่าง: "วิกฤต 2540 คนไทยสูญเงินรวม 4 ล้านล้านบาท — ทุกวันนี้ยังเกิดซ้ำได้"
    ตัวอย่าง: "สิงคโปร์ปี 1965 จน = ไทย แต่วันนี้รวยกว่า 7 เท่า เพราะตัดสินใจเรื่องนี้"
    ตัวอย่าง: "ญี่ปุ่นดอกเบี้ย 0% มา 20 ปี ทำให้คนออมเงินจนลงจริงอย่างไร"

  [สกุลเงิน/ค่าเงิน] "เปรียบเทียบสกุลเงินกับบาท + เหตุผลเบื้องหลัง"
    ตัวอย่าง: "1 ดีนาร์คูเวต = 110 บาท — ทำไมสกุลเงินเล็กๆ แพงกว่าดอลลาร์ 3 เท่า"
    ตัวอย่าง: "บาทอ่อนค่า 15% ใน 3 ปี — ของที่คุณซื้อแพงขึ้นเท่าไหร่จริงๆ"
    ตัวอย่าง: "ทำไมเงินเยนอ่อนค่าที่สุดในรอบ 30 ปี แต่คนญี่ปุ่นยังรวยกว่าไทย"

  [หุ้น/การลงทุน] "เปรียบเทียบการลงทุนด้วยตัวเลขจริง"
    ตัวอย่าง: "ซื้อ SET ETF ทุกเดือน 3,000 บาท นาน 20 ปี — เงินออกมาเท่าไหร่จริง"
    ตัวอย่าง: "หุ้น Apple vs ทองคำ vs บ้าน ใน 10 ปีที่แล้ว — อะไรชนะ"

  [fact น่าตกใจ] "คนส่วนใหญ่ไม่รู้ว่า... + ตัวเลข"
    ตัวอย่าง: "คนไทย 70% ไม่มีเงินออมเกิน 3 เดือน — ตัวเลขที่ทุกคนควรรู้"
    ตัวอย่าง: "Warren Buffett ทำเงิน 99% ของความมั่งคั่งหลังอายุ 50 — เพราะกฎข้อนี้"

✅ category ที่ต้องใช้ใน batch นี้ (ห้ามซ้ำ category เกิน 1):
สกุลเงินโลก | จิตวิทยาเงิน | เปรียบเทียบประเทศ | ประวัติศาสตร์การเงิน |
เงินเดือน/รายได้ | ภาษีและสิทธิ์ไทย | หุ้น/SET/ETF | ทอง/สินทรัพย์ | บ้าน/รถ/อสังหา |
ธุรกิจขนาดเล็ก | กองทุนรวม | บัตรเครดิต/หนี้ | เงินเฟ้อ/ค่าเสื่อม |
เกษียณอายุ | ประกันภัย | เศรษฐกิจโลก | คริปโต | Freelance/รายได้เสริม |
จัดอันดับสินทรัพย์ | เปรียบเทียบการลงทุน

❌ ห้าม:
- ขึ้นต้น "ทำไม..." หรือ "กับดัก..." เกิน 3 หัวข้อ
- หัวข้อ generic: "5 วิธีออมเงิน" / "นิสัยคนรวย" / "ข้อผิดพลาดทางการเงิน"
- ระบุชื่อธนาคาร/บริษัทประกันในเชิงลบหรือที่อาจทำให้เสื่อมชื่อเสียง

หัวข้อที่ทำไปแล้ว (ห้ามซ้ำ):
{used_text}

ตอบ JSON array เท่านั้น ห้ามมีข้อความอื่น:
["หัวข้อ 1", "หัวข้อ 2", ...]"""


class TopicManager:
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model
        self.client = anthropic.Anthropic()
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    # ─── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if DATA_FILE.exists():
            try:
                data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                # ล้าง corrupted topics (สั้นเกินไป) ออกจาก pending อัตโนมัติ
                before = len(data.get("pending", []))
                data["pending"] = [
                    t for t in data.get("pending", [])
                    if isinstance(t, str) and len(t.strip()) >= _MIN_TOPIC_LEN
                ]
                removed = before - len(data["pending"])
                if removed:
                    logger.info(f"Queue cleanup: ลบ {removed} topics เสีย (สั้นเกินไป)")
                return data
            except Exception:
                pass
        return {"used": [], "pending": []}

    def _save(self):
        DATA_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ─── Dedup ────────────────────────────────────────────────────────────────

    def _tokenize(self, text: str) -> set:
        return set(re.findall(r"[฀-๿]+|\w+", text.lower()))

    def _is_duplicate(self, candidate: str, against: list = None, threshold: float = 0.65) -> bool:
        """Fuzzy word-overlap check. against defaults to used + pending."""
        cw = self._tokenize(candidate)
        if not cw:
            return False
        if against is None:
            against = [u["topic"] for u in self._data["used"]] + self._data.get("pending", [])
        for existing in against:
            ew = self._tokenize(existing)
            if not ew:
                continue
            overlap = len(cw & ew) / max(len(cw), len(ew))
            if overlap >= threshold:
                logger.debug(f"Dedup skip '{candidate}' ≈ '{existing}' ({overlap:.0%})")
                return True
        return False

    # ─── Scoring ──────────────────────────────────────────────────────────────

    def _score_topics_batch(self, topics: list) -> list:
        """Score topics ทั้ง batch ใน 1 Haiku call — คืน list of int scores"""
        if not topics:
            return []
        numbered = "\n".join(f"{i+1}. \"{t}\"" for i, t in enumerate(topics))
        prompt = f"""ให้คะแนน "surprise factor" หัวข้อ TikTok การเงินไทยเหล่านี้ (1-10 ต่อข้อ)

{numbered}

เกณฑ์:
9-10: มี insight + ตัวเลขจริง ที่คนส่วนใหญ่ไม่รู้ → หยุดนิ้วทันที
7-8:  มี insight ชัด แต่อาจขาดตัวเลขหรือ mechanism เฉพาะ
5-6:  หัวข้อดี แต่ generic หรือคนรู้อยู่แล้ว
1-4:  ธรรมดามาก ไม่มี insight ใหม่

ตอบ JSON array ของคะแนนเท่านั้น เช่น [8, 6, 9, ...]:"""
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            m = re.search(r'\[[\d\s,]+\]', raw)
            if m:
                scores = json.loads(m.group())
                if len(scores) == len(topics):
                    return [int(s) for s in scores]
        except Exception as e:
            logger.warning(f"Topic scoring failed: {e}")
        return [7] * len(topics)   # default pass ถ้า API ล้มเหลว

    # ─── Generate ─────────────────────────────────────────────────────────────

    # ─── Category detection ───────────────────────────────────────────────────
    # ครอบคลุม 16 หมวด — เพิ่ม keyword ให้ตรวจได้แม่นขึ้น

    _CATEGORY_KEYWORDS = {
        "สกุลเงินโลก":           ["สกุลเงิน", "เงินเยน", "ดีนาร์", "ดอลลาร์", "ปอนด์", "ยูโร",
                                   "ค่าเงิน", "แลกเงิน", "บาทอ่อน", "บาทแข็ง", "wise",
                                   "โอนเงินต่างประเทศ", "forex", "ริงกิต", "ด่อง"],
        "เงินเดือน/รายได้":      ["เงินเดือน", "ค่าแรง", "ค่าจ้าง", "งานประจำ",
                                   "เงินเดือนขั้นต่ำ", "เงินเดือนขึ้น", "ค่าแรงขั้นต่ำ",
                                   "กำลังซื้อ", "รายได้ต่อหัว"],
        "หุ้น/SET/ETF":          ["หุ้น", " set ", "etf", "ดัชนี", "ตลาดหลักทรัพย์",
                                   "apple", "s&p", "dca", "ดีซีเอ", "nasdaq", "nikkei"],
        "กองทุนรวม":             ["กองทุน", "rmf", "ssf", "ltf", "กองทุนตลาดเงิน",
                                   "กองทุนรวม", "nav"],
        "บัตรเครดิต/หนี้":       ["บัตรเครดิต", "หนี้สิน", "หนี้บัตร", "ดอกเบี้ยบัตร",
                                   "ผ่อนชำระ", "ขั้นต่ำ", "สินเชื่อ", "กู้ยืม",
                                   "สหกรณ์", "กู้เงิน", "ผ่อน 0%", "ผ่อนศูนย์",
                                   "หนี้ครัวเรือน", "หนี้ท่วม", "คนไทย.*หนี้"],
        "ประกันภัย":              ["ประกันชีวิต", "ประกันภัย", "unit-linked", "เบี้ยประกัน",
                                   "ประกันสุขภาพ", "ประกันรถ", "ประกันสังคม", "ม.39", "ม.40",
                                   "มาตรา 39", "มาตรา 40", "ประกันสังคม"],
        "ภาษีและสิทธิ์ไทย":     ["ภาษี", "ลดหย่อน", "สรรพากร", "ภาษีมรดก",
                                   "ภาษีเงินได้", "ภาษีนิติบุคคล", "vat", "กรมสรรพากร"],
        "เปรียบเทียบประเทศ":     ["สิงคโปร์", "ญี่ปุ่น", "มาเลเซีย", "เวียดนาม",
                                   "อาเซียน", "เปรียบเทียบประเทศ", "เกาหลี", "จีน.*vs",
                                   "ไทย vs", "gdp.*ประเทศ", "สวัสดิการ.*ประเทศ"],
        "ประวัติศาสตร์การเงิน":  ["2540", "วิกฤต", "ประวัติศาสตร์", "1997", "วิกฤตต้มยำ",
                                   "great depression", "lehman"],
        "เงินเฟ้อ/ค่าเสื่อม":    ["เงินเฟ้อ", "inflation", "ค่าเสื่อม",
                                   "lifestyle inflation", "ราคาสินค้าขึ้น"],
        "บ้าน/รถ/อสังหา":        ["บ้าน", "คอนโด", "รถ", "อสังหา", "ผ่อนบ้าน",
                                   "เช่าบ้าน", "ซื้อบ้าน", "ที่ดิน", "ดาวน์บ้าน"],
        "ทอง/สินทรัพย์":         ["ทองคำ", "ทอง", "gold", "สินทรัพย์ทางเลือก",
                                   "คริปโต", "crypto", "bitcoin", "บิตคอยน์"],
        "เกษียณอายุ":             ["เกษียณ", "pension", "กองทุนสำรองเลี้ยงชีพ",
                                   "ออมเงินเกษียณ", "สวัสดิการเกษียณ", "provident fund"],
        "จิตวิทยาเงิน":          ["จิตวิทยา", "นิสัย", "mindset", "buffett", "warren",
                                   "แต่งงาน", "มีลูก", "ค่าใช้จ่ายชีวิต", "ค่าเลี้ยงลูก",
                                   "คนรวย.*เวลา", "lifestyle"],
        "เศรษฐกิจโลก":           ["เศรษฐกิจโลก", "เฟด", " fed ", "จีนชะลอ",
                                   "วิกฤตโลก", "recession", "ดอกเบี้ยโลก",
                                   "เศรษฐกิจจีน", "เศรษฐกิจสหรัฐ", "ธนาคารกลาง"],
        "Freelance/รายได้เสริม": ["ขายของออนไลน์", "ขายออนไลน์", "รายได้เสริม",
                                   "อาชีพเสริม", "passive income", "รายได้แฝง",
                                   "รายได้ passive", "income stream", "freelance.*ภาษี"],
    }

    def _detect_categories(self, topics: list) -> list:
        """คืน category ที่พบใน topics (ตรวจ keyword + regex บางส่วน)"""
        import re as _re
        found = set()
        for t in topics:
            tl = t.lower()
            for cat, kws in self._CATEGORY_KEYWORDS.items():
                for kw in kws:
                    if '.*' in kw:
                        if _re.search(kw, tl):
                            found.add(cat)
                            break
                    elif kw in tl:
                        found.add(cat)
                        break
        return list(found)

    def _interleave_by_category(self, topics: list) -> list:
        """จัดเรียง topics แบบ round-robin ตาม category — ไม่มี category เดิม 2 ครั้งติดกัน"""
        from collections import defaultdict
        buckets: dict = defaultdict(list)
        for t in topics:
            cats = self._detect_categories([t])
            key = cats[0] if cats else "_other_"
            buckets[key].append(t)
        result = []
        all_keys = list(buckets.keys())
        while any(buckets[k] for k in all_keys):
            for k in all_keys:
                if buckets[k]:
                    result.append(buckets[k].pop(0))
        return result

    def generate_batch(self, n: int = 20) -> list:
        """สร้าง topic ใหม่ n รายการ → dedup → score → เก็บเฉพาะ ≥ _MIN_SCORE"""
        used_list = [u["topic"] for u in self._data["used"]]
        used_text = "\n".join(f"- {t}" for t in used_list[-40:]) if used_list else "(ยังไม่มี)"

        # ตรวจ category ที่ใช้ใน 5 คลิปล่าสุด → ห้ามซ้ำใน batch นี้
        recent_topics = [u["topic"] for u in self._data["used"][-5:]]
        recent_cats = self._detect_categories(recent_topics)
        avoid_note = ""
        if recent_cats:
            avoid_note = f"\n\n⛔ category ที่ทำใน 5 คลิปล่าสุด — ห้ามสร้างซ้ำใน batch นี้เด็ดขาด:\n"
            avoid_note += ", ".join(recent_cats)

        base_prompt = _PROMPT_TEMPLATE.format(n=n, used_text=used_text)
        prompt = base_prompt + avoid_note
        msg = self.client.messages.create(
            model=self.model, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not m:
            logger.warning("Topic generation: ไม่พบ JSON array")
            return []
        try:
            topics = json.loads(m.group())
        except json.JSONDecodeError as e:
            logger.warning(f"Topic JSON parse error: {e}")
            return []

        # dedup + length filter
        fresh = [
            t for t in topics
            if isinstance(t, str) and len(t.strip()) >= _MIN_TOPIC_LEN
            and not self._is_duplicate(t)
        ]

        # batch score → filter ≥ _MIN_SCORE
        scores = self._score_topics_batch(fresh)
        passed, rejected = [], []
        for t, s in zip(fresh, scores):
            if s >= _MIN_SCORE:
                passed.append(t)
            else:
                rejected.append((s, t))
        if rejected:
            logger.info(f"Topic filter: ปฏิเสธ {len(rejected)} หัวข้อ (score < {_MIN_SCORE})")
            for s, t in rejected[:3]:
                logger.debug(f"  ✗ {s}/10 '{t[:60]}'")
        logger.info(f"Generated {len(topics)} → dedup {len(fresh)} → scored {len(passed)} topics ✓")
        return passed

    # ─── Queue management ─────────────────────────────────────────────────────

    def get_next_topic(self) -> str:
        """
        คืน topic ถัดไป — category rotation เข้ม:
        ห้ามซ้ำ category กับ 10 clip ล่าสุด (ถ้าเป็นไปได้)
        """
        used_list = [u["topic"] for u in self._data.get("used", [])]
        pending = [t for t in self._data.get("pending", []) if not self._is_duplicate(t, against=used_list)]

        if not pending:
            logger.info("Pending topics หมด → generate batch ใหม่...")
            pending = self.generate_batch(30)
            if not pending:
                raise RuntimeError("ไม่สามารถ generate topic ได้ — ตรวจ API key หรือลองใหม่")
            pending = self._interleave_by_category(pending)

        # ── เช็ค 10 clip ล่าสุด ห้ามซ้ำ category ──────────────────────
        recent_cats = set()
        for u in self._data.get("used", [])[-10:]:
            recent_cats.update(self._detect_categories([u["topic"]]))

        chosen_idx = 0
        skipped_cats: list = []
        if recent_cats:
            for i, t in enumerate(pending):
                t_cats = set(self._detect_categories([t]))
                # ผ่านถ้า: ไม่มี category ซ้ำ หรือ topic ไม่มี category (other)
                if not t_cats or not (t_cats & recent_cats):
                    chosen_idx = i
                    break
                skipped_cats.append(t_cats)
            else:
                # ทุก topic ในคิวซ้ำ category — เลือก topic ที่ category ซ้ำน้อยที่สุด
                logger.warning("Category pool หมด — เลือก topic ที่ซ้ำ category น้อยสุด")
                chosen_idx = 0

        if chosen_idx > 0:
            logger.info(f"Category rotate: ข้าม {chosen_idx} topic → เลือก idx {chosen_idx} "
                        f"(หลีกเลี่ยง {len(recent_cats)} cat จาก 10 clip ล่าสุด)")

        topic = pending.pop(chosen_idx)
        self._data["pending"] = pending
        self._save()
        logger.info(f"Next topic: '{topic}' | คงเหลือในคิว: {len(pending)}")
        return topic

    def mark_used(self, topic: str, title: str = "", video_path: str = "",
                  framework: str = "", hook_type: str = "", cta_type: str = "", subtopic: str = ""):
        """บันทึก topic หลัง pipeline สำเร็จ"""
        entry = {
            "topic": topic,
            "title": title,
            "video_path": video_path,
            "framework": framework,
            "hook_type": hook_type,
            "cta_type": cta_type,
            "subtopic": subtopic,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self._data.setdefault("used", []).append(entry)
        self._data["pending"] = [t for t in self._data.get("pending", []) if t != topic]
        self._save()
        logger.info(f"Topic บันทึกสำเร็จ: '{topic}' | hook={hook_type} cta={cta_type} subtopic={subtopic}")

    def last_framework(self) -> str:
        used = self._data.get("used", [])
        return used[-1].get("framework", "") if used else ""

    def last_hook_types(self, n: int = 3) -> list:
        """คืน hook types ที่ใช้ใน n คลิปล่าสุด — สำหรับ hook rotation"""
        used = self._data.get("used", [])
        return [u.get("hook_type", "") for u in used[-n:] if u.get("hook_type")]

    def last_cta_type(self) -> str:
        """คืน CTA type ล่าสุด — สำหรับ CTA rotation"""
        used = self._data.get("used", [])
        for u in reversed(used):
            if u.get("cta_type"):
                return u["cta_type"]
        return ""

    def recent_subtopics(self, n: int = 5) -> list:
        """คืน subtopics ใน n คลิปล่าสุด — สำหรับ content variety"""
        used = self._data.get("used", [])
        return [u.get("subtopic", "") for u in used[-n:] if u.get("subtopic")]

    def generate_series(self, main_topic: str, n: int = 3) -> list:
        """สร้าง n topics series ต่อเนื่อง — แต่ละตอนมี insight + ตัวเลขของตัวเอง"""
        prompt = f"""สร้าง {n} หัวข้อวิดีโอ TikTok series เกี่ยวกับ: {main_topic}

กฎสำคัญ:
- แต่ละตอนมี insight + ตัวเลขจริงของตัวเอง (ไม่ใช่แค่บอกว่าจะสอนเรื่องอะไร)
- ตอนที่ 1: ปัญหา/กับดักที่คนส่วนใหญ่ไม่รู้ว่าตัวเองติดอยู่ + ตัวเลขผลกระทบ
- ตอนที่ 2: mechanism ที่ซ่อนอยู่เบื้องหลัง + ตัวเลขจริงของการเสียเงิน
- ตอนที่ 3: วิธีที่ถูกต้องพร้อมตัวเลขผลลัพธ์ที่ชัดเจน
(ถ้า n>3: ตอนที่ 4=กรณีศึกษาจริง, ตอนที่ 5=checklist + สิ่งที่ต้องทำทันที)
- format: "[insight ที่น่าตกใจ] (ตอน X/{n})"

ตัวอย่างที่ดี (main_topic = บัตรเครดิต):
- "ทำไมขั้นต่ำ 10% ถูกออกแบบให้คุณติดหนี้นาน 6 ปีแทน 1 ปี (ตอน 1/3)"
- "วิธีที่ดอกเบี้ย 18% คูณตัวเองทุกเดือนโดยที่คุณมองไม่เห็น (ตอน 2/3)"

ตอบ JSON array เท่านั้น: ["หัวข้อ 1", "หัวข้อ 2", ...]"""

        msg = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        m   = re.search(r'\[.*?\]', raw, re.DOTALL)
        if not m:
            logger.warning("Series generation: ไม่พบ JSON array")
            return []
        try:
            topics = json.loads(m.group())
        except Exception:
            return []

        fresh = [t for t in topics if isinstance(t, str) and t.strip()
                 and not self._is_duplicate(t)]
        self._data.setdefault("pending", []).extend(fresh)
        self._save()
        logger.info(f"Series '{main_topic}': เพิ่ม {len(fresh)} ตอนเข้าคิว")
        return fresh

    def add_to_queue(self, topics: list, skip_scoring: bool = False):
        """เพิ่ม topic เข้า pending queue — score ก่อนเสมอ ยกเว้น skip_scoring=True"""
        clean = [
            t for t in topics
            if isinstance(t, str) and len(t.strip()) >= _MIN_TOPIC_LEN
            and not self._is_duplicate(t)
        ]
        if not skip_scoring and clean:
            scores = self._score_topics_batch(clean)
            passed = [t for t, s in zip(clean, scores) if s >= _MIN_SCORE]
            rejected = [(s, t) for t, s in zip(clean, scores) if s < _MIN_SCORE]
            if rejected:
                logger.info(f"add_to_queue: ปฏิเสธ {len(rejected)} หัวข้อ score ต่ำ")
                for s, t in rejected:
                    logger.info(f"  ✗ {s}/10 '{t[:60]}'")
            clean = passed
        self._data.setdefault("pending", []).extend(clean)
        # Re-interleave ทุกครั้งที่เพิ่ม topic — รักษา category rotation
        self._data["pending"] = self._interleave_by_category(self._data["pending"])
        self._save()
        logger.info(f"เพิ่ม {len(clean)} topics เข้าคิว (จาก {len(topics)} ที่ส่งมา) — re-interleaved")
        return clean

    # ─── Info ─────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "used": len(self._data.get("used", [])),
            "pending": len(self._data.get("pending", [])),
        }

    def list_used(self) -> list:
        return self._data.get("used", [])

    def list_pending(self) -> list:
        return self._data.get("pending", [])
