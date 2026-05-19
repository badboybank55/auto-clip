import json
import random
import re
import anthropic
from loguru import logger


# ─── Hook / CTA / Subtopic tracking ─────────────────────────────────────────

_HOOK_TYPE_LABELS = {
    "A": "curiosity_gap",  "B": "shocking_stat",
    "C": "direct_you",     "D": "contradiction",
    "E": "loss_aversion",  "F": "transformation",
    "G": "confession",     "H": "emotional",
    "I": "revelation",
}

# วน CTA หลากหลาย — engagement-only (bio CTAs เปิดใช้เมื่อมี affiliate พร้อม)
# research: save > share > comment > follow สำหรับ reach TikTok/YouTube 2025-2026
_CTA_SEQUENCE = ["save", "comment", "share", "save", "follow", "comment", "share", "save"]

_FINANCE_SUBTOPICS = [
    "debt", "savings", "investment", "insurance",
    "budgeting", "credit", "tax", "income", "mindset", "retirement",
]

# ─── Thai number word → Arabic converter ────────────────────────────────────

# lookup แบบ longest-match-first — compound ต้องมาก่อน single unit
_THAI_NUM_DICT: list = sorted([
    # decimal percentages
    ('หนึ่งจุดห้าเปอร์เซ็นต์','1.5%'), ('หนึ่งจุดสองเปอร์เซ็นต์','1.2%'),
    ('สองจุดห้าเปอร์เซ็นต์','2.5%'), ('สองจุดแปดเปอร์เซ็นต์','2.8%'),
    ('สามจุดห้าเปอร์เซ็นต์','3.5%'), ('สี่จุดห้าเปอร์เซ็นต์','4.5%'),
    ('หนึ่งจุดสองห้าเปอร์เซ็นต์','1.25%'), ('ศูนย์จุดห้าเปอร์เซ็นต์','0.5%'),
    # compound percentages (two+ digit)
    ('สิบแปดเปอร์เซ็นต์','18%'), ('สิบห้าเปอร์เซ็นต์','15%'),
    ('สิบสองเปอร์เซ็นต์','12%'), ('สิบเอ็ดเปอร์เซ็นต์','11%'),
    ('สิบสามเปอร์เซ็นต์','13%'), ('สิบสี่เปอร์เซ็นต์','14%'),
    ('สิบหกเปอร์เซ็นต์','16%'), ('สิบเจ็ดเปอร์เซ็นต์','17%'),
    ('สิบเก้าเปอร์เซ็นต์','19%'),
    ('ยี่สิบห้าเปอร์เซ็นต์','25%'), ('ยี่สิบเปอร์เซ็นต์','20%'),
    ('สามสิบเปอร์เซ็นต์','30%'), ('สี่สิบเปอร์เซ็นต์','40%'),
    ('ห้าสิบเปอร์เซ็นต์','50%'), ('หกสิบเปอร์เซ็นต์','60%'),
    ('เจ็ดสิบเปอร์เซ็นต์','70%'), ('แปดสิบเปอร์เซ็นต์','80%'),
    ('เก้าสิบเปอร์เซ็นต์','90%'), ('สิบเปอร์เซ็นต์','10%'),
    # single-digit percentages
    ('หนึ่งเปอร์เซ็นต์','1%'), ('สองเปอร์เซ็นต์','2%'), ('สามเปอร์เซ็นต์','3%'),
    ('สี่เปอร์เซ็นต์','4%'), ('ห้าเปอร์เซ็นต์','5%'), ('หกเปอร์เซ็นต์','6%'),
    ('เจ็ดเปอร์เซ็นต์','7%'), ('แปดเปอร์เซ็นต์','8%'), ('เก้าเปอร์เซ็นต์','9%'),
    ('ศูนย์เปอร์เซ็นต์','0%'),
    # compound large numbers
    ('สี่แสนแปดหมื่น','480,000'), ('หนึ่งแสนแปดหมื่น','180,000'),
    ('สองแสนห้าหมื่น','250,000'), ('สามแสนห้าหมื่น','350,000'),
    ('หนึ่งล้านสองแสน','1,200,000'), ('หนึ่งล้านห้าแสน','1,500,000'),
    ('หนึ่งล้านแปดแสน','1,800,000'), ('สองล้านห้าแสน','2,500,000'),
    ('หนึ่งหมื่นห้าพัน','15,000'), ('สองหมื่นห้าพัน','25,000'),
    ('สามหมื่นห้าพัน','35,000'), ('สี่หมื่นห้าพัน','45,000'),
    # millions
    ('หนึ่งล้าน','1,000,000'), ('สองล้าน','2,000,000'), ('สามล้าน','3,000,000'),
    ('สี่ล้าน','4,000,000'), ('ห้าล้าน','5,000,000'), ('สิบล้าน','10,000,000'),
    # hundred-thousands
    ('หนึ่งแสน','100,000'), ('สองแสน','200,000'), ('สามแสน','300,000'),
    ('สี่แสน','400,000'), ('ห้าแสน','500,000'), ('หกแสน','600,000'),
    ('เจ็ดแสน','700,000'), ('แปดแสน','800,000'), ('เก้าแสน','900,000'),
    # ten-thousands
    ('หนึ่งหมื่น','10,000'), ('สองหมื่น','20,000'), ('สามหมื่น','30,000'),
    ('สี่หมื่น','40,000'), ('ห้าหมื่น','50,000'), ('หกหมื่น','60,000'),
    ('เจ็ดหมื่น','70,000'), ('แปดหมื่น','80,000'), ('เก้าหมื่น','90,000'),
    # thousands
    ('หนึ่งพัน','1,000'), ('สองพัน','2,000'), ('สามพัน','3,000'),
    ('สี่พัน','4,000'), ('ห้าพัน','5,000'), ('หกพัน','6,000'),
    ('เจ็ดพัน','7,000'), ('แปดพัน','8,000'), ('เก้าพัน','9,000'),
    # hundreds
    ('หนึ่งร้อย','100'), ('สองร้อย','200'), ('สามร้อย','300'),
    ('สี่ร้อย','400'), ('ห้าร้อย','500'), ('หกร้อย','600'),
    ('เจ็ดร้อย','700'), ('แปดร้อย','800'), ('เก้าร้อย','900'),
    # decimals (no unit)
    ('หนึ่งจุดห้า','1.5'), ('หนึ่งจุดสอง','1.2'), ('สองจุดห้า','2.5'),
    ('สามจุดห้า','3.5'), ('ศูนย์จุดห้า','0.5'),
    # teens
    ('สิบเอ็ด','11'), ('สิบสอง','12'), ('สิบสาม','13'), ('สิบสี่','14'),
    ('สิบห้า','15'), ('สิบหก','16'), ('สิบเจ็ด','17'), ('สิบแปด','18'),
    ('สิบเก้า','19'),
    # tens (standalone — safe to convert in finance context)
    ('ยี่สิบห้า','25'), ('ยี่สิบ','20'), ('สามสิบ','30'), ('สี่สิบ','40'),
    ('ห้าสิบ','50'), ('หกสิบ','60'), ('เจ็ดสิบ','70'), ('แปดสิบ','80'),
    ('เก้าสิบ','90'), ('สิบ','10'),
], key=lambda x: -len(x[0]))   # longest first = no partial-match bugs


def _convert_thai_numbers(text: str) -> str:
    """แปลงคำอ่านตัวเลขไทยในสคริปต์ → ตัวเลขอาหรับ เพื่อแสดงผลที่ถูกต้องในซับไตเติ้ล
    ใช้ longest-match-first → หนึ่งจุดห้าเปอร์เซ็นต์ → 1.5% ก่อน หนึ่ง → 1
    ไม่แปลง single digit (หนึ่ง/สอง/...) เพื่อป้องกัน false positive เช่น "หนึ่งในวิธี" → "1ในวิธี"
    """
    for thai, arabic in _THAI_NUM_DICT:
        if thai in text:
            text = text.replace(thai, arabic)
    return text


_ANALOGY_RE = re.compile(
    r'เหมือน(?:กับ)?|ลองนึกภาพ|เปรียบเหมือน|เปรียบได้กับ|ก็เหมือน|คล้ายกับ|นึกถึง'
)
_VAGUE_MONEY_RE = re.compile(
    r'หลาย(?:พัน|หมื่น|แสน|ล้าน)|ไม่กี่(?:พัน|หมื่น|แสน|บาท|วัน|เดือน)'
)

STYLE_DESC = {
    "engaging":     "น่าสนใจ มีพลังงาน กระตุ้นอารมณ์ผู้ชม ใช้ภาษาพูด",
    "educational":  "ให้ความรู้ อธิบายชัดเจน มีตัวอย่าง เข้าใจง่าย",
    "entertaining": "บันเทิง ขำขัน น่าติดตาม มีเรื่องราว",
}

WORDS_PER_SECOND = 2.5

# ─── Script Frameworks ────────────────────────────────────────────────────────

FRAMEWORKS = {
    "story": {
        "weight": 18,
        "label": "STORY (เรื่องเล่าสถานการณ์จริง)",
        "body": """\
[BODY — เล่าสถานการณ์จริงในมุม first-person "ผม"] 6-8 ประโยค เล่าเป็นเรื่องเดียวไม่แบ่งข้อ
  • ❌ ห้ามสร้างตัวละครสมมติ ห้ามตั้งชื่อเช่น "พี่มิ้น" "พี่กอล์ฟ" "น้องมินต์" ทุกกรณี
  • ✅ ใช้ "ผม" (first-person) หรือ "คุณ" (second-person) หรือ "คนทำงานเงินเดือน X" (generic role ไม่มีชื่อ)
  • สถานการณ์: อาชีพ/รายได้/ปัญหาที่คนทั่วไป relate ได้ทันที
  • ปัญหา: สิ่งที่ทำผิดพลาด — ตัวเลขที่เสียไป/พลาดไป
  • MINI CLIFFHANGER กลางเรื่อง: "แต่ที่น่าตกใจกว่านั้นคือ..." แล้วเฉลยอีก 1-2 ประโยคถัดไป
  • จุดเปลี่ยน: สิ่งที่ทำให้ผลลัพธ์เปลี่ยน
  • ผลลัพธ์: ตัวเลขที่เปลี่ยนภายใน X เดือน/ปี
  เรื่องต้องฟังดูจริงและ relate ได้ ไม่ใช่โฆษณา""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟเก็บไว้เป็นแรงบันดาลใจ เผื่อวันที่ท้อ"
  Comment: "ตอนนี้คุณอยู่ฝั่ง A=รู้แล้ว หรือ B=เพิ่งรู้? คอมเมนต์มาเลยครับ"
  Share  : "ส่งคลิปนี้ให้คนที่คุณอยากเห็นเขาเปลี่ยนแปลง"
  Follow : "กด follow ไว้ก่อน มีเรื่องราวการเงินทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "confession": {
        "weight": 16,
        "label": "CONFESSION (สารภาพความผิดพลาด)",
        "body": """\
[BODY — เปิดเผยความผิดพลาดของตัวเอง] 6-8 ประโยค เล่าในมุม first-person "ฉัน/ผม"
  • สารภาพ: ความผิดพลาดด้านการเงินที่เคยทำ — ตัวเลขที่เสียไป ต้องแม่นยำ
  • ทำไมถึงผิด: ความเชื่อผิดๆ หรือข้อมูลที่ไม่ครบที่ทำให้ตัดสินใจพลาด
  • MINI CLIFFHANGER: เปิดใจว่ายังมีความผิดพลาดที่แย่กว่า — พูดตรงๆ ว่าอะไร ห้ามใช้ "แต่นั่นยังไม่ใช่ส่วนที่แย่ที่สุด..."
  • สิ่งที่เรียนรู้: วิธีที่ถูกต้อง อธิบายง่ายๆ
  • ผลลัพธ์หลังเปลี่ยน: ตัวเลขที่ดีขึ้น
  เล่าด้วยความซื่อสัตย์ อย่าทำตัวเป็น expert — เป็น "คนที่เคยผิดพลาดแล้วเรียนรู้"
  ห้ามใช้: "ผม/ฉัน" นำทุกประโยค — สลับสรรพนามบ้าง""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้เตือนตัวเองว่าอย่าทำแบบที่ผมเคยทำ"
  Comment: "คุณเคยทำแบบนี้มั้ย? A=เคย B=ไม่เคย คอมเมนต์มาเลย"
  Share  : "แชร์ให้คนที่คุณอยากป้องกันไม่ให้เขาทำพลาดแบบนี้"
  Follow : "กด follow ไว้ก่อน มีเรื่องที่เรียนรู้จากความผิดพลาดจริงทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "before_after": {
        "weight": 13,
        "label": "BEFORE/AFTER (ก่อน vs หลัง)",
        "body": """\
[BODY — เปรียบเทียบชีวิตก่อน/หลัง] 7-8 ประโยค ไม่แบ่งข้อ
  BEFORE (3 ประโยค): วาดภาพ "ชีวิตก่อน" — ตัวเลขที่น่ากลัว ความเจ็บปวดที่ relate ได้
    • "เมื่อก่อน..." / "ตอนที่ยังไม่รู้เรื่องนี้..." — ต้องเห็นภาพชัด
  TRANSITION (1-2 ประโยค): จุดเปลี่ยนที่ทำให้ชีวิตต่างออกไป
    • "จนกระทั่ง..." / "วันที่เริ่มเปลี่ยนแค่สิ่งเดียวคือ..."
  AFTER (3 ประโยค): "ชีวิตหลัง" — ตัวเลขที่น่าดีใจ ผลลัพธ์วัดได้
    • "ตอนนี้..." / "หลังจาก X เดือน..."
  เรื่องต้องฟังดูจริง ไม่ใช่โฆษณา ตัวละครเป็นคนธรรมดา""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้ก่อน ถ้าไม่อยากให้ชีวิตยังติดอยู่ใน 'ก่อน'"
  Comment: "คุณอยู่ A=ก่อน หรือ B=หลัง แล้ว? คอมเมนต์มาเลยครับ"
  Share  : "ส่งคลิปนี้ให้คนที่คุณอยากเห็นเขาเปลี่ยนแปลง"
  Follow : "กด follow ไว้ก่อน มีเรื่องราวการเปลี่ยนแปลงทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "countdown": {
        "weight": 12,
        "label": "COUNTDOWN (นับทุกอันดับครบ)",
        "body": """\
[BRIDGE — 1 ประโยคก่อนเข้า body] ❌ ห้ามเปิดด้วย "อันดับที่ 5" เลย ต้องมีบริบทก่อน 1 ประโยค
  ✅ เช่น: "วันนี้จะพาไปดู [จำนวน] อันดับที่คนไทยส่วนใหญ่ไม่รู้ว่ามีอยู่ครับ"

[BODY — นับทุกอันดับตามที่ topic ระบุ] แต่ละอันดับ 2-3 ประโยค
  ⚠ ถ้า topic บอก "5 อันดับ" → ต้องมีทุกอันดับตั้งแต่ต่ำสุดถึงสูงสุด ห้ามข้าม
  • แต่ละอันดับ: "อันดับที่ X — [ชื่อ/สิ่ง]" + ตัวเลขจริงที่บอกว่าทำไมอยู่อันดับนี้ + เหตุผล 1 ประโยค
  • อันดับ 1 = สูงสุด/สำคัญที่สุด — เป็น climax ของเรื่อง ต้องน่าตกใจที่สุด ให้รายละเอียดมากที่สุด
  • สร้างความอยากรู้ก่อนถึงอันดับ 1: "แต่อันดับ 1 คืออันที่คาดไม่ถึงที่สุด..."
  ใช้ "อันดับที่ 5" "อันดับที่ 4" ... "อันดับที่ 1" ให้ครบ""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้เตือนตัวเอง อย่าให้ทำผิดซ้ำอีก"
  Comment: "คุณรู้เรื่องนี้มาก่อนมั้ย? YES หรือ NO คอมเมนต์มาเลย"
  Share  : "แชร์ให้คนที่คุณไม่อยากให้เขาทำพลาด"
  Follow : "กด follow ไว้ก่อน มีเคล็ดลับการเงินทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "what_if": {
        "weight": 11,
        "label": "WHAT-IF (จะเกิดอะไรขึ้นถ้า...)",
        "body": """\
[BODY — สำรวจ scenario สมมติ] 6-8 ประโยค เล่าแบบ journey ไม่แบ่งข้อ
  • ตั้ง scenario: "สมมติว่าคุณ..." / "จะเป็นยังไง ถ้า..." — ต้องเป็นสถานการณ์ที่ relate ได้
  • ขยาย consequence ทีละขั้น: ปีที่ 1 → ปีที่ 5 → ปีที่ 10 (ตัวเลขชัดเจน)
  • MINI CLIFFHANGER กลาง scenario: ตั้งคำถามที่คนอยากรู้คำตอบทันที — ห้ามใช้ "แต่นี่ยังไม่ใช่..."
  • twist: ความจริงที่คนส่วนใหญ่ไม่รู้ ทำให้ผลลัพธ์ต่างจากที่คิด
  • ปิดด้วย actionable insight: สิ่งที่ทำได้เลยวันนี้จาก scenario นี้
  ใช้ตัวเลขจริง ๆ อย่าใช้ "ประมาณ" ทำให้ scenario น่าเชื่อและ relate ได้""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟ scenario นี้ไว้คิด แล้วลองคำนวณกับชีวิตตัวเอง"
  Comment: "ถ้าเป็นคุณจะเลือก A หรือ B? คอมเมนต์มาเลยครับ"
  Share  : "ส่งให้คนที่คุณอยากให้ลองคิดแบบนี้บ้าง"
  Follow : "กด follow ไว้ก่อน มีเรื่องการเงินที่ทำให้คิดใหม่ทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "myth": {
        "weight": 10,
        "label": "MYTH-BUST (ล้มความเชื่อ)",
        "body": """\
[BRIDGE — 1 ประโยค ก่อนเข้า body] ตั้งบริบทเล็กน้อยก่อนเข้าสู่ข้อมูล
  ❌ ห้ามเปิดด้วย "ความเชื่อที่ 1" เลย — ต้องมี 1 ประโยคเชื่อมก่อนเสมอ
  ✅ เช่น: "เรื่องนี้มี 3 ความเชื่อที่คนส่วนใหญ่เข้าใจผิดทั้งหมดเลยครับ"
  ✅ เช่น: "ลองมาดูกันว่า สิ่งที่คุณรู้เกี่ยวกับ [topic] นั้นถูกหรือผิด"

[BODY — ล้มความเชื่อผิด 3 ข้อ] แต่ละข้อ 2-3 ประโยค
  • "ความเชื่อที่ 1 — [สิ่งที่คนส่วนใหญ่คิดว่าจริง]"
  • ความจริงที่น่าตกใจ + ตัวเลขหรือตัวอย่างที่พิสูจน์ได้
  • MINI CLIFFHANGER ก่อนความเชื่อสุดท้าย: "และความเชื่อสุดท้ายนี้ คือที่คนทำพลาดมากที่สุด..."
  ใช้ "ความเชื่อที่ 1" "ความเชื่อที่ 2" "ความเชื่อที่ 3"
  เหมาะกับ: ความเชื่อผิดๆ เรื่องบัตรเครดิต / ประกัน / การลงทุน""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้ก่อน ก่อนที่จะเชื่อใครอีก"
  Comment: "คุณเคยเชื่อเรื่องนี้มาก่อนมั้ย? A=เคย B=ไม่เคย คอมเมนต์มาเลย"
  Share  : "แชร์ให้คนที่ยังเข้าใจผิดอยู่"
  Follow : "กด follow ไว้ก่อน มีความเชื่อผิดๆ ให้ล้มทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "deep_dive": {
        "weight": 9,
        "label": "DEEP DIVE (เจาะลึก 1 เรื่อง)",
        "body": """\
[BODY — เจาะลึก 1 concept] 7-9 ประโยค เชื่อมต่อเป็นเรื่องเดียว ไม่แบ่งข้อ
  • WHY (2 ประโยค): ทำไมเรื่องนี้ถึงสำคัญ — fact หรือตัวเลขที่คนส่วนใหญ่ไม่รู้
  • HOW (3-4 ประโยค): กลไกที่ทำให้เรื่องนี้ work ใช้ analogy จับต้องได้
    เช่น "เหมือนกับ..." / "ลองนึกภาพว่า..." — ห้ามอธิบายแบบวิชาการ
  • MINI CLIFFHANGER: "แต่สิ่งที่คนส่วนใหญ่ไม่รู้คือ..."
  • PROOF (1-2 ประโยค): ตัวอย่างจริง พร้อมตัวเลขชัดเจน
  เล่าเหมือน "ผู้รู้บอกความลับให้เพื่อนสนิท" ไม่ใช่สอนในห้องเรียน""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้อ่านซ้ำ ถ้าไม่ทำตอนนี้จะลืมแน่"
  Comment: "คุณรู้เรื่องนี้มาก่อนมั้ย? YES หรือ NO คอมเมนต์มาเลยครับ"
  Share  : "แชร์ให้คนที่คุณอยากให้รู้เรื่องนี้ก่อนสายเกินไป"
  Follow : "กด follow ไว้ก่อน มีเรื่องการเงินเจาะลึกทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "list": {
        "weight": 8,
        "label": "LIST (ข้อ 1-2-3)",
        "body": """\
[BRIDGE — 1 ประโยคก่อนเข้า body] ❌ ห้ามเปิดด้วย "ข้อ 1" เลย ต้องมีบริบทก่อน 1 ประโยค
  ✅ เช่น: "มี [จำนวน] สิ่งที่คุณทำได้เลยวันนี้ เพื่อ [ผลลัพธ์จาก topic] ครับ"

[BODY — 3 ข้อ] แต่ละข้อ 3 ประโยคสั้น
  • "ข้อ 1 — [ชื่อเทคนิค]" + ตัวอย่างที่ทำได้เลยในชีวิตจริง + ผลลัพธ์ที่วัดได้ (ตัวเลข)
  • ระหว่างข้อ 2→3 สร้างความอยากรู้: "ข้อสุดท้ายนี้ คือที่คนมักข้ามไป..."
  ใช้ "ข้อ 1" "ข้อ 2" "ข้อ 3" เท่านั้น""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟคลิปนี้ไว้เลย แล้วลองทำข้อ 1 วันนี้เลย"
  Comment: "ข้อไหนที่คุณจะลองทำวันนี้เลย? A B หรือ C คอมเมนต์มาเลย"
  Share  : "ส่งคลิปนี้ให้คนที่ยังไม่รู้เรื่องนี้"
  Follow : "กด follow ไว้ก่อน มีเคล็ดลับการเงินทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "betrayal": {
        "weight": 15,
        "label": "BETRAYAL (เปิดโปงระบบ)",
        "body": """\
[BODY — เปิดโปงระบบ/กลไกที่ถูกออกแบบมาให้คุณเสียเงิน] 6-8 ประโยค
  • ระบุกลไกจริง: "ระบบนี้ถูกสร้างขึ้นมาเพื่อ..." — ไม่ระบุชื่อองค์กร ใช้ "ระบบ" / "สถาบันการเงิน"
  • HOW (2 ประโยค): กลไกทำงานอย่างไรกันแน่ — ตัวเลขจริงว่าเงินหายไปเท่าไหร่ต่อปี/เดือน
  • MINI CLIFFHANGER: บอกตัวเลขที่น่าตกใจทันที — ห้ามใช้ "แต่นี่ยังไม่ใช่ส่วนที่น่ากลัวที่สุด..."
  • เฉลย (2 ประโยค): ส่วนที่แย่กว่าที่คนไม่รู้ + ตัวเลขที่น่าตกใจกว่า
  • วิธีหลีกเลี่ยง (1 ประโยค): action ที่ทำได้เลยวันนี้ + ผลลัพธ์วัดได้เป็นตัวเลข
  เน้น: ผู้ชมต้องรู้สึกว่า "ดีที่รู้ก่อน" ไม่ใช่แค่โกรธ ต้องมี action ชัดเจน""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้ก่อน อย่าให้ระบบดูดเงินคุณไปเงียบๆ อีกต่อไป"
  Comment: "คุณรู้จักกลไกนี้มาก่อนมั้ย? YES หรือ NO คอมเมนต์มาเลยครับ"
  Share  : "แชร์ให้คนที่คุณไม่อยากให้โดนระบบนี้หลอกต่อไป"
  Follow : "กด follow ไว้ก่อน มีเรื่องกลไกการเงินที่ต้องรู้ทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
    "comparison": {
        "weight": 3,
        "label": "COMPARISON (A vs B — อะไรดีกว่ากัน)",
        "body": """\
[BODY — เปรียบเทียบ 2 ทางเลือก] 7-9 ประโยค ไม่แบ่งข้อ
  • ตั้ง 2 ทางเลือกที่คนมักสับสน เช่น "ประกันชีวิต vs ลงทุนเอง" / "บัตรเครดิต vs เงินสด"
  • ทางเลือก A (3 ประโยค): ข้อดี + ข้อเสียจริงๆ + ตัวเลข
  • MINI CLIFFHANGER: เปิดมุมมองที่คนไม่คาดคิด — บอกตัวเลขเปรียบเทียบที่น่าตกใจทันที ห้ามใช้ "แต่นั่นยังไม่ใช่..."
  • ทางเลือก B (3 ประโยค): ข้อดี + ข้อเสียจริงๆ + ตัวเลข
  • verdict (1 ประโยค): "ดังนั้น ถ้าคุณ [สถานการณ์ A] → เลือก [ตัวนี้]"
  ห้ามให้คำตอบ "ขึ้นอยู่กับ" — ต้องมี verdict ชัดเจนพร้อมเหตุผล""",
        "cta": """\
[CTA — 1 ประโยคเดียว เลือก 1 จาก 4]:
  Save   : "เซฟไว้ก่อนตัดสินใจ อย่าเลือกผิดเพราะไม่รู้ข้อมูล"
  Comment: "คุณเลือก A หรือ B? คอมเมนต์มาเลยครับ ไม่ต้องบอกเหตุผลก็ได้"
  Share  : "ส่งให้คนที่กำลังตัดสินใจเรื่องนี้อยู่"
  Follow : "กด follow ไว้ก่อน มีเรื่องเปรียบเทียบการเงินทุกวัน"
  ห้ามใช้: คนนึง / ตัวนึง / อันนึง""",
    },
}


def _pick_framework(avoid: str = "") -> str:
    keys    = list(FRAMEWORKS.keys())
    weights = [FRAMEWORKS[k]["weight"] for k in keys]
    if avoid and avoid in keys:
        idx = keys.index(avoid)
        weights[idx] = max(1, weights[idx] // 5)   # heavily reduce last-used framework
    return random.choices(keys, weights=weights, k=1)[0]


_FRAMEWORK_PACING = {
    # เป้าหมาย 45-60 วินาที = 11-14 ประโยค (research: 30-60s → 50%+ completion rate)
    # countdown/list ขึ้นกับจำนวนข้อ ต้องครบแต่กระชับ
    "story":        "11-13 ประโยค (เล่าช้า มี arc — เป้า 50-55 วิ)",
    "confession":   "10-12 ประโยค (กระชับ confession — เป้า 45-50 วิ)",
    "before_after": "11-13 ประโยค (before 3 + transition 2 + after 3 + payoff + CTA)",
    "countdown":    "ขึ้นกับจำนวนอันดับ — แต่ละอันดับ 2 ประโยคกระชับ ครบทุกอันดับ เป้า ≤ 70 วิ",
    "what_if":      "11-13 ประโยค (scenario กระชับ — เป้า 50-55 วิ)",
    "myth":         "11-13 ประโยค (3 ความเชื่อ × 3 ประโยค + payoff + CTA — เป้า 50-60 วิ)",
    "deep_dive":    "12-14 ประโยค (เจาะลึกแต่กระชับ — เป้า 55-65 วิ)",
    "list":         "ขึ้นกับจำนวนข้อ — แต่ละข้อ 2 ประโยคกระชับ ครบทุกข้อ เป้า ≤ 65 วิ",
    "comparison":   "11-13 ประโยค (A 3 + transition + B 3 + verdict + CTA — เป้า 50-55 วิ)",
    "betrayal":     "11-13 ประโยค (reveal 2 + HOW 2 + cliffhanger + เฉลย 2 + action + CTA)",
}

# ไม่มี hard cap — ความยาวขึ้นอยู่กับเนื้อหา เนื้อหาครบแล้วค่อยจบ
_MAX_SENTENCES = 999

# แปลงเลขไทย → เลขอาหรับ (ใช้ทั่วทั้งระบบ)
_THAI_DIGIT_TABLE = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def normalize_numbers(text: str) -> str:
    """แปลงเลขไทย (๐-๙) เป็นเลขอาหรับ (0-9) ทุกตัวในข้อความ"""
    return text.translate(_THAI_DIGIT_TABLE)


# ─── Post-process sanitizer ───────────────────────────────────────────────────

_CTA_BAD = re.compile(
    r'สัก(?:คน|ตัว|อัน)นึง'      # สักคนนึง / สักตัวนึง / สักอันนึง ใน CTA
    r'|(?:คน|ตัว|อัน)นึงนะ'       # คนนึงนะ / ตัวนึงนะ
)

_COMMA_BEFORE = re.compile(
    r'(?<=[฀-๿\w])(?<!,)\s+(แต่(?!ละ)|เพราะ(?!ฉะ)|ดังนั้น|จึง(?!\w)|ทำให้|'
    r'ซึ่ง(?!กัน)|เนื่องจาก|อย่างไรก็ตาม|แม้ว่า|ถึงแม้)'
)


_ARABIC_UNIT_MULT = [
    ('ล้านล้าน', 1_000_000_000_000),
    ('ล้าน',     1_000_000),
    ('แสน',      100_000),
    ('หมื่น',     10_000),
    ('พัน',       1_000),
]
_ARABIC_UNIT_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*(ล้านล้าน|ล้าน|แสน|หมื่น|พัน)'
    r'(?=[^ล้านแสนหมื่นพัน\d]|$)'
)

def _expand_arabic_unit(m: re.Match) -> str:
    """2 ล้าน → 2,000,000 | 1.5 ล้าน → 1,500,000 | 3 แสน → 300,000"""
    n = float(m.group(1))
    unit = m.group(2)
    mult = dict(_ARABIC_UNIT_MULT)[unit]
    result = n * mult
    return f"{int(result):,} "  # trailing space — double space cleanup ด้านล่างจัดการ


_ZERO_DECIMAL_MAP = {
    '0':'ศูนย์','1':'หนึ่ง','2':'สอง','3':'สาม','4':'สี่',
    '5':'ห้า','6':'หก','7':'เจ็ด','8':'แปด','9':'เก้า',
}

def _fix_zero_decimal(s: str) -> str:
    """แปลง 0.X → ศูนย์จุดX ให้ ElevenLabs Thai TTS อ่านถูก (ไม่ตีความ "." เป็นจุดจบประโยค)"""
    def _repl(m: re.Match) -> str:
        return 'ศูนย์จุด' + ''.join(_ZERO_DECIMAL_MAP.get(d, d) for d in m.group(1))
    # (?<![.\d]) — ไม่ใช้ \b (ไม่ทำงานกับ Thai chars) ใช้ lookbehind แทน
    return re.sub(r'(?<![.\d])0\.(\d+)', _repl, s)


def _sanitize_sentence(s: str) -> str:
    """แก้ pattern ที่ Claude สร้างผิดซ้ำๆ — ทำงานโดยไม่ต้องรู้ topic"""
    # CTA: สักคนนึง / สักตัวนึง → สักข้อนึง
    s = _CTA_BAD.sub('สักข้อนึง', s)
    # "สูญ " โดด (ไม่มี เสีย/หาย/เปล่า/ไป) → "สูญเสีย " (ฟังชัดขึ้น)
    s = re.sub(r'สูญ(?!เสีย|หาย|เปล่า|ไป|สิ้น)', 'สูญเสีย', s)
    # ลบ "นะครับ/นะคะ" ซ้ำ
    s = re.sub(r'(นะครับ|นะคะ){2,}', r'\1', s)
    # เสียงชาย: "คะ" / "ค่ะ" → "ครับ"
    s = re.sub(r'นะคะ', 'นะครับ', s)
    s = re.sub(r'(?<=[฀-๿])คะ(?=[?!.,\s]|$)', 'ครับ', s)
    s = re.sub(r'(?<=[฀-๿])ค่ะ(?=[?!.,\s]|$)', 'ครับ', s)
    s = re.sub(r'จ้ะ', 'ครับ', s)
    # ตัวเลขไทย digit (๐-๙) → Arabic
    s = normalize_numbers(s)
    # "9,000-12,000" / "3,000 - 5,000" → "9,000 ถึง 12,000" ให้ TTS พูดถูก
    s = re.sub(r'(\d[\d,]*)\s*[-–—]\s*(\d[\d,]*)', r'\1 ถึง \2', s)
    # "2 ล้าน" / "1.5 แสน" → "2,000,000" / "150,000" — ก่อน _convert_thai_numbers
    s = _ARABIC_UNIT_RE.sub(_expand_arabic_unit, s)
    s = re.sub(r'  +', ' ', s)   # ลบ double space ที่อาจเกิดหลังแปลง
    # คำอ่านตัวเลขไทย → Arabic
    s = _convert_thai_numbers(s)
    # เพิ่มจุลภาคก่อน conjunction (ถ้ายังไม่มี) → ช่วย SSML breaks หยุดถูกที่
    s = _COMMA_BEFORE.sub(lambda m: f', {m.group(1)}', s)
    # "0.5" → "ศูนย์จุดห้า" — ทำสุดท้ายหลัง _convert_thai_numbers
    # (ไม่งั้น _convert_thai_numbers จะแปลงกลับ)
    s = _fix_zero_decimal(s)
    return s.strip()


class ScriptGenerator:
    def __init__(self, config: dict):
        self.config = config["script"]
        self.client = anthropic.Anthropic()

    def generate(self, topic: str, style: str = None, duration: int = None,
                 last_framework: str = "", last_hook_types: list = None,
                 last_cta: str = "", used_subtopics: list = None) -> dict:
        style    = style or self.config["style"]
        duration = duration or self.config["duration_target"]
        target_words = int(duration * WORDS_PER_SECOND)
        last_hook_types  = last_hook_types  or []
        used_subtopics   = used_subtopics   or []

        fw_key = _pick_framework(avoid=last_framework)
        fw     = FRAMEWORKS[fw_key]

        # CTA rotation: บังคับ type ถัดจาก last_cta
        forced_cta = self._next_cta_type(last_cta)
        logger.info(f"Generating: '{topic}' | {fw['label']} | hook_avoid={last_hook_types} | forced_cta={forced_cta}")

        # Subtopic context: แจ้ง AI ว่า used_subtopics ล่าสุดคืออะไร
        prompt = self._build_prompt(topic, style, target_words, duration, fw_key,
                                    forbidden_hook_types=last_hook_types,
                                    forced_cta=forced_cta,
                                    used_subtopics=used_subtopics)

        # ── A/B Hook Test — generate 2 variants, pick best hook ───────────────
        prompt_b = (prompt +
                    "\n\n[VARIANT B — STRONGER HOOK] "
                    "Hook ต้องน่าตกใจ และขัดความเชื่อมากกว่า variant ปกติ 2 เท่า "
                    "ใช้ตัวเลขที่น่าช็อกกว่า หรือความจริงที่คนไม่เคยนึกถึง "
                    "ห้าม hook เหมือนกับ variant A "
                    "ห้ามใช้ hook type เดิมกับ variant A")

        candidates = []
        for label, p in [("A", prompt), ("B", prompt_b)]:
            try:
                msg = self.client.messages.create(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                    messages=[{"role": "user", "content": p}],
                )
                data = self._parse(msg.content[0].text, topic)
                if len(data.get("sentences", [])) >= 9:
                    hook  = data["sentences"][0]
                    score = self._score_hook(hook, topic)
                    logger.info(f"Hook {label}: {score}/10 — '{hook[:45]}'")
                    candidates.append((score, data))
            except Exception as e:
                logger.warning(f"Script {label} failed: {e}")

        if not candidates:
            logger.warning("A/B both failed → single attempt fallback")
            msg  = self.client.messages.create(
                model=self.config["model"],
                max_tokens=self.config["max_tokens"],
                messages=[{"role": "user", "content": prompt}],
            )
            data = self._parse(msg.content[0].text, topic)
            data["framework"] = fw_key
            return data

        best_score, best_data = max(candidates, key=lambda x: x[0])
        winner = "A" if len(candidates) < 2 or candidates[0][0] >= candidates[1][0] else "B"
        logger.info(f"A/B winner: {winner} ({best_score}/10)")

        # ── Hook retry — ถ้า best score < 8 ให้ generate ใหม่อีกครั้ง ──────────
        if best_score < 8:
            logger.info(f"Hook {best_score}/10 < 7 → retry with stronger hook instruction...")
            retry_prompt = (prompt +
                            f"\n\n[RETRY — hook ก่อนหน้าได้แค่ {best_score}/10 ไม่พอ]"
                            " hook ต้องน่าตกใจกว่าเดิม — ใช้ตัวเลขที่น่าช็อก หรือขัดความเชื่อแรงกว่าเดิม"
                            " ห้าม hook คล้ายกับที่ผ่านมา")
            try:
                msg = self.client.messages.create(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                    messages=[{"role": "user", "content": retry_prompt}],
                )
                retry_data = self._parse(msg.content[0].text, topic)
                if len(retry_data.get("sentences", [])) >= 9:
                    retry_hook  = retry_data["sentences"][0]
                    retry_score = self._score_hook(retry_hook, topic)
                    logger.info(f"Retry hook: {retry_score}/10 — '{retry_hook[:45]}'")
                    if retry_score > best_score:
                        best_score, best_data = retry_score, retry_data
                        logger.info(f"Retry won ({retry_score}/10)")
            except Exception as e:
                logger.warning(f"Hook retry failed: {e}")

        best_data["framework"] = fw_key

        # ── Body quality score — retry ถ้า < 6 ────────────────────────────────
        body_score = self._score_body(best_data["sentences"], fw_key)
        logger.info(f"Body score: {body_score}/10")
        if body_score < 6:
            logger.info("Body score ต่ำ → retry with stronger body instruction...")
            retry_body_prompt = (prompt +
                f"\n\n[RETRY BODY — body score {body_score}/10 ไม่พอ]"
                " ต้องมี: mini-cliffhanger กลางเรื่อง + ตัวเลขจริงอย่างน้อย 3 ตัว + analogy 1 ประโยค"
                " เนื้อหาต้องดึงดูดจนต้องดูจนจบ ห้ามน่าเบื่อ")
            try:
                msg = self.client.messages.create(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                    messages=[{"role": "user", "content": retry_body_prompt}],
                )
                retry_bd = self._parse(msg.content[0].text, topic)
                if len(retry_bd.get("sentences", [])) >= 9:
                    new_score = self._score_body(retry_bd["sentences"], fw_key)
                    logger.info(f"Body retry score: {new_score}/10")
                    if new_score > body_score:
                        best_data = retry_bd
                        best_data["framework"] = fw_key
                        logger.info("Body retry ชนะ")
            except Exception as e:
                logger.warning(f"Body retry failed: {e}")

        # ── Script polish ───────────────────────────────────────────────────────
        best_data = self._polish(best_data, topic)

        # ── Fact check — ตรวจสอบตัวเลขและข้อมูลทางการเงินก่อนใช้งาน ────────────
        best_data = self._fact_check(best_data, topic)

        # ── Actionability check — คนดูได้ประโยชน์จริงไหม ──────────────────────
        action_score = self._score_actionability(best_data["sentences"], topic)
        logger.info(f"Actionability: {action_score}/10")
        if action_score < 7:
            logger.info("Actionability ต่ำ → retry เพิ่ม practical takeaway สำหรับคนไทย...")
            retry_action_prompt = (prompt +
                f"\n\n[RETRY ACTIONABILITY — score {action_score}/10 ไม่พอ]"
                "\n⚠ คนดูไทยที่ดูจบต้องได้อะไรกลับไปใช้จริงๆ:"
                "\n- ถ้ามี action: บอกชัดว่าทำอะไรได้เลย (เปิด RMF / เปลี่ยนวิธีออม / ลงทุนแบบนี้)"
                "\n- ถ้าเปรียบกับต่างประเทศ: ต้องลงท้ายด้วย insight ที่คนไทยเอาไปใช้ได้ (ไม่ใช่แค่ 'ต่างประเทศดีกว่า')"
                "\n- ประโยคก่อน CTA ต้องเป็น takeaway ชัดๆ ว่า 'สิ่งที่คุณทำได้คือ...' หรือ 'บทเรียนคือ...'")
            try:
                msg = self.client.messages.create(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                    messages=[{"role": "user", "content": retry_action_prompt}],
                )
                retry_act = self._parse(msg.content[0].text, topic)
                if len(retry_act.get("sentences", [])) >= 9:
                    new_score = self._score_actionability(retry_act["sentences"], topic)
                    logger.info(f"Actionability retry: {new_score}/10")
                    if new_score > action_score:
                        best_data = retry_act
                        best_data["framework"] = fw_key
                        logger.info("Actionability retry ชนะ")
            except Exception as e:
                logger.warning(f"Actionability retry failed: {e}")

        # ── Quality checks — แก้ปัญหาที่เหลือด้วย targeted polish ─────────────
        issues = []
        if not self._has_analogy(best_data["sentences"]):
            issues.append("no_analogy")
            logger.info("Quality: ไม่มี analogy → จะเพิ่ม")
        if self._has_vague_numbers(best_data["sentences"]):
            issues.append("vague_numbers")
            logger.info("Quality: พบตัวเลขกำกวม → จะแก้")
        if self._has_repetitive_starters(best_data["sentences"]):
            issues.append("repetitive_starters")
            logger.info("Quality: พบขึ้นต้นประโยคซ้ำ → จะแก้")
        if issues:
            best_data = self._quality_polish(best_data, issues)

        # ── Length enforcement — ตัดให้ไม่เกิน _MAX_SENTENCES ──────────────────
        sents = best_data.get("sentences", [])
        if len(sents) > _MAX_SENTENCES:
            # เก็บ hook (0), ตัด body กลาง, รักษา CTA (สุดท้าย)
            keep = sents[:_MAX_SENTENCES - 1] + [sents[-1]]
            best_data["sentences"] = keep
            best_data["full_text"] = "\n".join(keep)
            logger.info(f"Length trim: {len(sents)} → {len(keep)} sentences")

        # ── Title A/B ───────────────────────────────────────────────────────────
        best_data = self._ab_title(best_data, topic)

        # ── Numeric Harmony — hook + title ต้องใช้ตัวเลขเดียวกับ body ──────────
        best_data = self._harmonize_numbers(best_data)

        # ── Classify meta: hook_type / cta_type / subtopic ─────────────────────
        hook_type = self._detect_hook_type(best_data["sentences"][0] if best_data["sentences"] else "")
        cta_type  = self._detect_cta_type(best_data["sentences"])
        subtopic  = self._classify_subtopic(best_data["sentences"], topic)
        best_data["hook_type"] = hook_type
        best_data["cta_type"]  = cta_type
        best_data["subtopic"]  = subtopic
        logger.info(f"Meta: hook_type={hook_type} | cta_type={cta_type} | subtopic={subtopic}")

        return best_data

    def _polish(self, data: dict, topic: str) -> dict:
        """Claude Haiku ขัดเกลาภาษาเท่านั้น — ห้ามเพิ่ม/ลด/แตก sentence"""
        sentences = data.get("sentences", [])
        n = len(sentences)
        if n < 3:
            return data
        joined = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
        prompt = f"""ปรับภาษาสคริปต์วิดีโอไทยนี้ให้ฟังดูธรรมชาติขึ้น:

{joined}

กฎเข้มงวด — ห้ามละเมิด:
- ต้องคืน {n} ประโยคเท่าเดิม ห้ามเพิ่ม ห้ามลด ห้ามรวม ห้ามแตก
- ห้ามเปลี่ยน content หรือความหมาย
- แก้ได้แค่: คำเชื่อม / ประโยคที่ขึ้นต้นคำเดิมซ้ำติดกัน / ตัวเลขให้เป็นอาหรับ
- ลำดับ ขั้นแรก→ขั้นที่ 1 | ขั้นสอง→ขั้นที่ 2 | ขั้นสาม→ขั้นที่ 3 | ขั้นสี่→ขั้นที่ 4
- ห้ามเพิ่ม/ลด จำนวนของใน title เช่น ถ้า title บอก 3 ข้อ ต้องมี 3 ข้อเท่านั้น
- แทนที่ "คะ" / "ค่ะ" / "จ้ะ" / "นะคะ" ทุกที่ด้วย "ครับ" / "นะครับ" (เสียงชายเท่านั้น)

ตอบ JSON array {n} ประโยคเท่านั้น: ["ประโยค 1", ..., "ประโยค {n}"]"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if m:
                polished = json.loads(m.group())
                # ต้องได้จำนวนเท่าเดิมเป๊ะ ± 0
                if isinstance(polished, list) and len(polished) == n:
                    polished = [normalize_numbers(s.strip()) for s in polished if str(s).strip()]
                    polished = [_sanitize_sentence(s) for s in polished]
                    if len(polished) == n:   # double-check after sanitize
                        logger.info(f"Polish: {n} sentences ✓")
                        data["sentences"] = polished
                        data["full_text"] = "\n".join(polished)
                else:
                    logger.warning(f"Polish returned {len(polished)} ≠ {n} → keeping original")
        except Exception as e:
            logger.warning(f"Polish failed (keeping original): {e}")
        return data

    def _fact_check(self, data: dict, topic: str) -> dict:
        """ตรวจสอบความถูกต้องของตัวเลขและข้อมูลการเงินในสคริปต์
        ป้องกันการให้ข้อมูลผิดๆ กับผู้ชม — แก้ไขในที่เดียวก่อน TTS
        """
        sentences = data.get("sentences", [])
        if not sentences:
            return data
        n = len(sentences)
        joined = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
        prompt = f"""ตรวจสอบความถูกต้องของข้อมูลทางการเงินในสคริปต์นี้

Topic: {topic}

สคริปต์:
{joined}

━━━ ข้อมูลการเงินไทยที่ถูกต้อง (ใช้อ้างอิง) ━━━
- ดอกเบี้ยบัตรเครดิตไทย: ตาม ธปท. ไม่เกิน 16% ต่อปี
- ดอกเบี้ยสินเชื่อส่วนบุคคล: ไม่เกิน 25% ต่อปี
- ภาษีเงินได้บุคคลธรรมดา: อัตราก้าวหน้า 0-35%
- RMF: หักลดหย่อนได้ไม่เกิน 30% ของเงินได้ รวม SSF+กองทุนสำรองฯ+ประกันบำนาญ ต้องไม่เกิน 500,000 บาท/ปี
- SSF: หักได้ไม่เกิน 30% ของเงินได้ และไม่เกิน 200,000 บาท/ปี
- ประกันสังคม ม.33: ส่งเงินสมทบ 5% ของค่าจ้าง (สูงสุด 750 บาท/เดือน)
- ดอกเบี้ยออมทรัพย์ทั่วไป: 0.5-1.5% ต่อปี
- อัตราเงินเฟ้อไทยเฉลี่ย: 1.5-3% ต่อปี

━━━ งาน ━━━
1. ตรวจตัวเลขและข้อเท็จจริงทุกตัว — เทียบกับข้อมูลอ้างอิงด้านบน
2. ⚠ ตรวจ NUMERIC CONSISTENCY: ตัวเลขในประโยคต่างๆ ต้องสอดคล้องกัน
   เช่น ถ้าประโยคแรกบอก "เสีย X บาทต่อปี" แต่ตัวอย่างในเนื้อหาคำนวณได้ Y บาทต่อปี
   → แก้ให้ตัวเลขตรงกันตลอดทั้งสคริปต์ (เลือกตัวเลขที่ถูกตามบริบท)
3. ถ้าพบข้อมูลผิด → แก้เฉพาะตัวเลข/ข้อมูลนั้น ห้ามเปลี่ยน content อื่น
4. ถ้าทุกอย่างถูก → คืน JSON เหมือนเดิมทุกประโยค

กฎ:
- ต้องคืน {n} ประโยคเท่าเดิม ห้ามเพิ่ม ลด รวม แตก
- แก้เฉพาะตัวเลขที่ผิดหรือขัดแย้งกันเท่านั้น — ถ้าไม่แน่ใจ ให้คงไว้
- ตอบ JSON array {n} strings: ["ประโยค 1", ..., "ประโยค {n}"]"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if m:
                checked = json.loads(m.group())
                if isinstance(checked, list) and len(checked) == n:
                    # ลบ prefix เลข "N. " ที่ AI ติดกลับมา (เช่น "1. มีเงิน..." → "มีเงิน...")
                    checked = [re.sub(r'^\d+\.\s*', '', str(s).strip()) for s in checked if str(s).strip()]
                    checked = [_sanitize_sentence(normalize_numbers(s)) for s in checked]
                    if len(checked) == n:
                        changed = sum(1 for a, b in zip(sentences, checked) if a != b)
                        if changed:
                            logger.info(f"Fact check: แก้ {changed} ประโยค ✓")
                        else:
                            logger.info("Fact check: ข้อมูลถูกต้องทั้งหมด ✓")
                        data["sentences"] = checked
                        data["full_text"] = "\n".join(checked)
        except Exception as e:
            logger.warning(f"Fact check failed (keeping original): {e}")
        return data

    def _score_hook(self, hook: str, topic: str) -> int:
        """Claude Haiku ให้คะแนน hook 1-10 — ใช้เวลา ~1s เท่านั้น"""
        if not hook:
            return 7
        prompt = f"""คะแนน hook ประโยคนี้ 1-10 สำหรับ TikTok การเงินภาษาไทย

Hook: "{hook}"
Topic: {topic}

เกณฑ์คะแนน (ยึดผลวิจัย TikTok 2025):
9-10 = hook หยุดนิ้วทันที: ใช้ loss aversion หรือ pattern interrupt + 1 ตัวเลขชัด + ≤ 12 คำ + ทำให้รู้สึกว่าตัวเองกำลังเสีย/ขาด
7-8  = hook ดี มีบริบทชัด แต่อาจขาด emotional punch หรือยาวนิด
5-6  = บอก fact แต่ไม่ทำให้รู้สึกอะไร / generic เกินไป
1-4  = ไม่มี trigger / คำถาม / ไม่บอกว่าตัวเองได้ผลกระทบอะไร

บวกคะแนน:
+3 ถ้าใช้ loss aversion ชัดเจน — ผู้ดูรู้สึกว่ากำลังสูญเสียอยู่ตอนนี้ (Kahneman research: 2× กว่า gain)
+2 ถ้ากระชับ ≤ 10 คำ + มี 1 ตัวเลขจริงที่น่าตกใจ + บริบทชัด
+1 ถ้า hook ขัดความเชื่อ (pattern interrupt) ทำให้ต้องหยุดฟัง
+1 ถ้าบอกว่าผู้ดู "กำลังทำอยู่" ไม่ใช่คนอื่น — personal relevance

หักคะแนน:
-3 ถ้ามีตัวเลขมากกว่า 1 ตัวใน hook เดียว — สมองรับไม่ทัน คนกด scroll ก่อนอ่านจบ
-2 ถ้ามี em-dash (—) ใน hook — ตัดจังหวะเสียงพาก
-2 ถ้าขึ้นต้นด้วยคำถาม ("คุณรู้มั้ยว่า" / "รู้มั้ยว่า" / "เคยสังเกต")
-2 ถ้ามีชื่อสมมติ ("พี่มิ้น" / "พี่กอล์ฟ" / "น้องมินต์")
-2 ถ้า hook ยาวเกิน 15 คำ — คนไม่อ่านจบก่อนกด scroll
-1 ถ้า hook บอก fact แต่ไม่บอกว่า "ผู้ดูเสีย/ได้อะไร"

ตอบตัวเลขเดียวเท่านั้น ห้ามมีข้อความอื่น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            return int(msg.content[0].text.strip())
        except Exception:
            return 7  # default pass ถ้า API ล้มเหลว

    def _score_title(self, title: str, topic: str) -> int:
        """คะแนน title 1-10 — clickbait potential สำหรับ thumbnail"""
        if not title:
            return 5
        prompt = f"""คะแนน title นี้ 1-10 สำหรับ thumbnail วิดีโอการเงิน TikTok ภาษาไทย

Title: "{title}"
Topic: {topic}

เกณฑ์:
9-10 = น่าคลิกมาก มีตัวเลข หรือคำที่ทำให้สงสัย หรือ curiosity gap ชัด
7-8  = ดี กระชับ มี keyword ที่น่าสนใจ
5-6  = พอใช้ แต่ generic
1-4  = น่าเบื่อ หรือยาวเกินไป

ตอบตัวเลขเดียวเท่านั้น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            return int(msg.content[0].text.strip())
        except Exception:
            return 5

    # ─── Hook / CTA / Subtopic helpers ───────────────────────────────────────

    @staticmethod
    def _next_cta_type(last_cta: str) -> str:
        """วนลำดับ save→share→save→comment→save→follow — save มาก่อนและบ่อยที่สุด"""
        if not last_cta or last_cta not in _CTA_SEQUENCE:
            return "save"   # default เริ่มที่ save เสมอ
        return _CTA_SEQUENCE[(_CTA_SEQUENCE.index(last_cta) + 1) % len(_CTA_SEQUENCE)]

    def _detect_hook_type(self, hook: str) -> str:
        """Classify hook เป็น A-I type ด้วย Haiku"""
        if not hook:
            return ""
        prompt = f"""จัดประเภท hook TikTok ภาษาไทยนี้เป็นหนึ่งในประเภทต่อไปนี้:
Hook: "{hook}"
A=curiosity_gap  B=shocking_stat  C=direct_you  D=contradiction
E=loss_aversion  F=transformation  G=confession  H=emotional
I=revelation (เปิดด้วยคนจริง+action+ผลลัพธ์ที่ไม่คาดคิด เล่าตรงเลย ไม่ถาม)
ตอบตัวอักษรเดียว (A-I) เท่านั้น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=3,
                messages=[{"role": "user", "content": prompt}],
            )
            letter = msg.content[0].text.strip().upper()[:1]
            return _HOOK_TYPE_LABELS.get(letter, "")
        except Exception:
            return ""

    @staticmethod
    def _detect_cta_type(sentences: list) -> str:
        """Detect CTA type จากประโยคสุดท้าย"""
        last = sentences[-1].lower() if sentences else ""
        if "ไบโอ" in last or "bio" in last or "ลิงก์" in last:
            return "bio_hard" if any(w in last for w in ["เลย", "ได้เลย", "วันนี้", "ตอนนี้"]) else "bio_soft"
        if "เซฟ" in last or "save" in last:
            return "save"
        if "คอมเมนต์" in last or "comment" in last:
            return "comment"
        if "แชร์" in last or "share" in last:
            return "share"
        if "follow" in last or "ติดตาม" in last:
            return "follow"
        return ""

    def _classify_subtopic(self, sentences: list, topic: str) -> str:
        """จัดหมวดหมู่ subtopic ด้วย Haiku"""
        text = topic + " " + " ".join(sentences[:4])
        prompt = f"""จัดหมวดหมู่เนื้อหาการเงินนี้เป็น 1 หมวดจากรายการนี้:
{text}

หมวด: debt|savings|investment|insurance|budgeting|credit|tax|income|mindset|retirement
ตอบชื่อหมวดภาษาอังกฤษคำเดียวเท่านั้น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=15,
                messages=[{"role": "user", "content": prompt}],
            )
            result = msg.content[0].text.strip().lower()
            for st in _FINANCE_SUBTOPICS:
                if st in result:
                    return st
        except Exception:
            pass
        return ""

    # ─── Body quality helpers ─────────────────────────────────────────────────

    def _score_body(self, sentences: list, framework: str) -> int:
        """Score body ของสคริปต์ 1-10"""
        if len(sentences) < 5:
            return 7
        early = "\n".join(sentences[:4])   # hook + tease + 2 body ประโยคแรก
        body  = "\n".join(sentences[2:-1])  # ข้าม hook/tease และ CTA
        mid   = sentences[4] if len(sentences) > 4 else ""
        prompt = f"""ให้คะแนน body สคริปต์ TikTok การเงินภาษาไทย 1-10

=== ประโยคทั้งหมด ===
{body}

=== ประโยคแรก 4 ประโยค (ตรวจตัวเลข) ===
{early}

=== ประโยคที่ 5 (ตรวจ micro-hook) ===
{mid}

เกณฑ์หลัก (ต้องผ่านทุกข้อจึงจะได้ 9-10):
9-10: มี mini-cliffhanger + ตัวเลขจริง ≥3 ตัว + analogy + payoff ที่คาดไม่ถึง
      + เนื้อหาเป็น insight ที่คนส่วนใหญ่ยังไม่รู้ (ไม่ใช่ "ออมก่อนใช้" หรือ advice ธรรมดา)
7-8:  ข้อมูลดี มีตัวเลข แต่อาจขาด cliffhanger หรือ analogy
5-6:  ข้อมูลพอใช้ แต่ generic เกินไป — คนอาจรู้อยู่แล้ว
1-4:  น่าเบื่อ / ไม่มีตัวเลขจริง / เป็น advice ที่ทุกคนรู้แล้ว

บทลงโทษเพิ่มเติม (หักคะแนนตรงๆ):
-2 ถ้า 4 ประโยคแรกไม่มีตัวเลขจริงเลย (คนดูจะเบื่อก่อนครึ่งคลิป)
-2 ถ้าประโยคที่ 5 ไม่มี retention hook ("แต่ที่น่าตกใจ..." / "และนี่คือส่วนที่..." / "รู้มั้ยว่าทำไม")
-1 ถ้าอธิบายแค่ว่า "ดอกเบี้ยสูง/ค่าธรรมเนียมเยอะ" โดยไม่บอก mechanism ว่าทำงานอย่างไร

ตอบตัวเลขเดียวเท่านั้น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            return int(msg.content[0].text.strip())
        except Exception:
            return 7

    def _score_actionability(self, sentences: list, topic: str) -> int:
        """ตรวจว่าคนดูได้ประโยชน์จริงๆ — ไม่ใช่แค่ trivia น่าสนใจ"""
        body = "\n".join(sentences)
        prompt = f"""ให้คะแนน "practical value" สคริปต์ TikTok การเงินไทยนี้ 1-10

Topic: {topic}
Script:
{body}

เกณฑ์: คนไทยที่ดูคลิปนี้จบแล้ว "ได้อะไรกลับไปใช้ในชีวิตจริง"?

9-10: มี action ที่ชัดที่คนดูทำได้เลย (เปิด RMF / ลดหนี้วิธีนี้ / ลงทุนแบบนี้)
      หรือเปลี่ยน mindset เรื่องเงินที่ส่งผลต่อการตัดสินใจจริงๆ
7-8:  ให้ insight ดีที่ทำให้คิดต่างออกไป แม้ไม่มี action ตรงๆ
5-6:  น่าสนใจแต่เป็นแค่ trivia — รู้แล้วก็ไม่ได้ทำอะไรได้
1-4:  ข้อมูลที่คนดูไทยไม่สามารถนำไปใช้ได้เลย (เช่น เปรียบประเทศอื่นแต่ไม่มี takeaway สำหรับคนไทย)

ตอบตัวเลขเดียวเท่านั้น"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=5,
                messages=[{"role": "user", "content": prompt}],
            )
            return int(msg.content[0].text.strip())
        except Exception:
            return 7

    def _harmonize_numbers(self, data: dict) -> dict:
        """ตรวจว่าตัวเลขใน hook และ title ตรงกับที่คำนวณในเนื้อหา body
        ป้องกัน hook บอก 62 แต่ body คำนวณได้ 41 — แก้ hook/title ให้ตรงกัน
        """
        sentences = data.get("sentences", [])
        title = data.get("title", "")
        if len(sentences) < 5:
            return data

        hook = sentences[0]
        body_sentences = sentences[2:-1]   # ข้าม hook, tease, CTA
        body_text = " ".join(body_sentences)

        # ดึงตัวเลขจาก body (source of truth — คำนวณจริงอยู่ที่นี่)
        body_nums = set(re.findall(r'\d[\d,]*(?:\.\d+)?', body_text))
        # กรองเฉพาะตัวเลขที่มีนัยสำคัญ (≥2 หลัก)
        body_nums = {n for n in body_nums if len(n.replace(',', '').replace('.', '')) >= 2}

        hook_nums  = set(re.findall(r'\d[\d,]*(?:\.\d+)?', hook))
        title_nums = set(re.findall(r'\d[\d,]*(?:\.\d+)?', title))

        # ตัวเลขที่เป็น % ใน hook/title — ห้าม harmonize
        # เพราะ "เงินหาย 40%" กับ "ค่าธรรมเนียม 150% ของเบี้ยปีแรก" คือ context คนละเรื่องกัน
        hook_pct_nums  = set(re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*%', hook))
        title_pct_nums = set(re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*%', title))

        # หาตัวเลขที่อยู่ใน hook/title แต่ไม่อยู่ใน body (ยกเว้น % เสมอ)
        hook_conflicts  = {n for n in hook_nums  if n not in body_nums
                           and n not in hook_pct_nums
                           and len(n.replace(',','').replace('.','')) >= 2}
        title_conflicts = {n for n in title_nums if n not in body_nums
                           and n not in title_pct_nums
                           and len(n.replace(',','').replace('.','')) >= 2}

        if not hook_conflicts and not title_conflicts:
            return data

        logger.info(f"Numeric harmony: hook conflicts={hook_conflicts} title conflicts={title_conflicts}")

        body_nums_list = ", ".join(sorted(body_nums, key=lambda x: -len(x))[:10])
        prompt = f"""แก้ hook และ title ให้ตัวเลขตรงกับที่คำนวณในเนื้อหา

เนื้อหาจริง (source of truth):
{body_text}

ตัวเลขที่ถูกต้องจากเนื้อหา: {body_nums_list}

Hook ปัจจุบัน: {hook}
Title ปัจจุบัน: {title}

กฎ:
- แก้เฉพาะตัวเลขที่ขัดแย้งกับเนื้อหา — ใช้ตัวเลขจาก body เท่านั้น
- ห้ามเปลี่ยน structure ของประโยค เปลี่ยนแค่ตัวเลข
- ถ้าตัวเลขใน hook/title ตรงแล้ว ให้คงไว้
ตอบ JSON เท่านั้น: {{"hook": "...", "title": "..."}}"""

        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            m = re.search(r'\{.*?\}', msg.content[0].text.strip(), re.DOTALL)
            if m:
                result = json.loads(m.group())
                new_hook  = result.get("hook", hook).strip()
                new_title = result.get("title", title).strip()
                if new_hook and new_hook != hook:
                    sentences[0] = new_hook
                    data["sentences"] = sentences
                    logger.info(f"Harmony fixed hook: '{hook[:40]}' → '{new_hook[:40]}'")
                if new_title and new_title != title:
                    data["title"] = new_title
                    logger.info(f"Harmony fixed title: '{title[:40]}' → '{new_title[:40]}'")
        except Exception as e:
            logger.warning(f"Numeric harmony failed: {e}")
        return data

    @staticmethod
    def _has_analogy(sentences: list) -> bool:
        return bool(_ANALOGY_RE.search(" ".join(sentences)))

    @staticmethod
    def _has_vague_numbers(sentences: list) -> bool:
        return bool(_VAGUE_MONEY_RE.search(" ".join(sentences)))

    @staticmethod
    def _has_repetitive_starters(sentences: list) -> bool:
        def first_word(s):
            parts = s.split()
            return parts[0] if parts else ""
        fw = [first_word(s) for s in sentences]
        return any(fw[i] and fw[i] == fw[i + 1] for i in range(len(fw) - 1))

    def _quality_polish(self, data: dict, issues: list) -> dict:
        """Targeted polish สำหรับปัญหาที่ตรวจพบ — ห้ามเปลี่ยนจำนวน sentence"""
        sentences = data.get("sentences", [])
        n = len(sentences)
        joined = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))

        rules = []
        if "no_analogy" in issues:
            rules.append("- เพิ่ม analogy 1 ครั้งในประโยคที่เหมาะสม: 'เหมือนกับ...' / 'ลองนึกภาพ...' / 'เปรียบเหมือน...'")
        if "vague_numbers" in issues:
            rules.append("- แทนที่คำกำกวม (หลายพัน/หลายหมื่น/ไม่กี่บาท) ด้วยตัวเลขจริงที่น่าเชื่อถือ")
        if "repetitive_starters" in issues:
            rules.append("- เปลี่ยนคำขึ้นต้นประโยคที่ซ้ำติดกัน ให้ต่างกัน (ห้ามขึ้นต้นด้วยคำเดิมติดกัน 2 ประโยค)")

        rule_text = "\n".join(rules)
        prompt = f"""แก้ปัญหาต่อไปนี้ในสคริปต์ภาษาไทย:

{joined}

ปัญหาที่ต้องแก้:
{rule_text}

กฎเข้มงวด:
- ต้องคืน {n} ประโยคเท่าเดิม ห้ามเพิ่ม ห้ามลด
- ห้ามเปลี่ยนประโยคที่ 1 (hook) และประโยคสุดท้าย (CTA)
- แก้เฉพาะปัญหาที่ระบุเท่านั้น ห้ามเปลี่ยน content อื่น
ตอบ JSON array {n} ประโยค: ["ประโยค 1", ..., "ประโยค {n}"]"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            m = re.search(r'\[.*\]', raw, re.DOTALL)
            if m:
                fixed = json.loads(m.group())
                if isinstance(fixed, list) and len(fixed) == n:
                    fixed = [normalize_numbers(s.strip()) for s in fixed if str(s).strip()]
                    if len(fixed) == n:
                        data["sentences"] = fixed
                        data["full_text"] = "\n".join(fixed)
                        logger.info(f"Quality polish fixed: {issues}")
        except Exception as e:
            logger.warning(f"Quality polish failed: {e}")
        return data

    def _ab_title(self, data: dict, topic: str) -> dict:
        """Generate title B แล้วเลือกที่ score ดีกว่า"""
        title_a = data.get("title", "")
        score_a = self._score_title(title_a, topic)
        prompt = f"""สร้าง title วิดีโอ TikTok การเงินภาษาไทยแบบใหม่สำหรับ topic นี้

Topic: {topic}
Title A (ที่มีอยู่): {title_a}

กฎ: ≤60 ตัวอักษร | มีตัวเลขหรือ curiosity gap | ต้องต่างจาก Title A อย่างชัดเจน
ตอบแค่ title เดียวเท่านั้น ไม่มีเครื่องหมายคำพูด"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            title_b = msg.content[0].text.strip().strip('"').strip("'")
            score_b = self._score_title(title_b, topic)
            logger.info(f"Title A: {score_a}/10 '{title_a[:40]}' | B: {score_b}/10 '{title_b[:40]}'")
            if score_b > score_a:
                data["title"] = title_b
                logger.info("Title B ชนะ")
        except Exception as e:
            logger.warning(f"Title A/B failed: {e}")
        return data

    def _build_prompt(self, topic: str, style: str, target_words: int,
                      duration: int, fw_key: str = "list",
                      forbidden_hook_types: list = None,
                      forced_cta: str = "",
                      used_subtopics: list = None) -> str:
        style_text = STYLE_DESC.get(style, STYLE_DESC["engaging"])
        fw   = FRAMEWORKS[fw_key]
        body = fw["body"].replace("{end}", str(duration - 10))
        cta  = fw["cta"]

        pacing = _FRAMEWORK_PACING.get(fw_key, "10-13 ประโยค")

        # Hook avoidance notice
        hook_avoid_note = ""
        if forbidden_hook_types:
            labels = [next((k for k,v in _HOOK_TYPE_LABELS.items() if v == t), "") for t in forbidden_hook_types]
            labels = [l for l in labels if l]
            if labels:
                hook_avoid_note = f"\n  ⚠ ห้ามใช้ hook type: {', '.join(labels)} ({', '.join(forbidden_hook_types)}) — ใช้ไปแล้วในคลิปล่าสุด"

        # CTA override instruction
        # CTA research-backed (TikTok algorithm 2025-2026):
        # Save > Share > Comment > Like (อย่าขอ Like — ไม่มีผลต่อ reach)
        # Comment A/B = response rate สูงสุด เพราะ low-friction
        # Share ต้องระบุ WHO = share rate สูงขึ้น
        _CTA_FORCED_TEXT = {
            "save": (
                "SAVE — research: Save = highest intent signal ให้ algorithm\n"
                "  ต้องบอก WHEN/WHY ให้ specific กับ topic นี้:\n"
                "  ✅ 'เซฟไว้เลย เปิดดูตอน [situation specific กับ topic] จะได้ไม่พลาด'\n"
                "  ✅ 'เซฟเก็บไว้ก่อน [ระบุว่า topic นี้จะ useful ตอนไหน]'\n"
                "  ✅ 'ถ้าไม่เซฟตอนนี้ คุณจะลืมแน่ๆ และ [ผลเสียที่จะตาม]'\n"
                "  ❌ ห้าม: 'เซฟไว้ก่อน' เปล่าๆ — ต้องบอกว่าเปิดดูตอนไหน"
            ),
            "comment": (
                "COMMENT — research: Binary A/B question = comment rate สูงสุด (low friction)\n"
                "  เลือก 1 format:\n"
                "  ✅ Binary: 'คุณอยู่แบบ A หรือ B? คอมเมนต์มาเลยครับ' (low effort, high response)\n"
                "     เช่น: 'ตอนนี้คุณเป็น: A=เก็บก่อนใช้ หรือ B=ใช้ก่อนเก็บ คอมเมนต์มาเลย'\n"
                "  ✅ YES/NO: 'คุณรู้เรื่องนี้มาก่อนมั้ย? คอมเมนต์ YES หรือ NO มาเลยครับ'\n"
                "  ✅ Keyword trigger: 'คอมเมนต์ [keyword] แล้วผมจะส่งข้อมูลเพิ่มให้'\n"
                "  ❌ ห้าม: 'คอมเมนต์บอกว่าคิดยังไง' — open-ended เกินไป คนไม่ตอบ"
            ),
            "share": (
                "SHARE — research: ระบุ WHO + WHY = share rate สูงขึ้นชัดเจน\n"
                "  ✅ 'ส่งให้ [คนที่ relate กับ topic นี้] — เขาต้องรู้เรื่องนี้ก่อนสาย'\n"
                "     เช่น: 'ส่งให้เพื่อนที่เพิ่งเริ่มทำงาน ก่อนที่เขาจะทำพลาดแบบนี้'\n"
                "  ✅ 'แชร์ให้คนที่คุณรัก ถ้าไม่อยากให้เขาเจอ [ปัญหาจาก topic]'\n"
                "  ✅ 'ส่งให้คนที่ยังคิดว่า [ความเชื่อผิดจาก topic]'\n"
                "  ❌ ห้าม: 'แชร์ให้เพื่อน' เปล่าๆ — ต้องบอก WHO และ WHY"
            ),
            "follow": (
                "FOLLOW — บอก next piece of value ที่จะได้ถ้า follow:\n"
                "  ✅ 'กด follow ไว้ก่อน พรุ่งนี้มีเรื่อง [topic ต่อเนื่องจากวันนี้] มาอีก'\n"
                "  ✅ 'follow ไว้นะครับ ยังมีอีก [เรื่องเกี่ยวกับ topic] ที่คนส่วนใหญ่ไม่รู้'\n"
                "  ❌ ห้าม: 'กด follow ไว้ก่อน มีเรื่องการเงินทุกวัน' — generic ไม่บอก next value"
            ),
            "bio_soft": (
                "BIO SOFT — ชี้ลิงก์ในไบโอแบบเป็นธรรมชาติ ไม่ hard sell:\n"
                "  เป้าหมาย: คนที่สนใจจริงๆ จะไปดูเอง — ไม่กดดันคนที่ไม่พร้อม\n"
                "  ✅ 'ถ้าอยากเริ่ม [action ที่ตรงกับ topic] จริงๆ มีข้อมูลเพิ่มเติมในไบโอครับ'\n"
                "  ✅ 'ผมทิ้งลิงก์เริ่มต้น [เรื่องที่เกี่ยวกับ topic] ไว้ในไบโอด้วยนะครับ'\n"
                "  ✅ 'รายละเอียดเพิ่มเติมและวิธีเริ่มต้นอยู่ในไบโอเลยครับ'\n"
                "  ❌ ห้าม: hard sell / 'คลิกเลย' / 'อย่ารอช้า' — ต้องดูเป็นคำแนะนำ ไม่ใช่โฆษณา\n"
                "  ❌ ห้าม: generic — ต้องอ้างอิง topic/insight จากคลิปนี้โดยตรง"
            ),
            "bio_hard": (
                "BIO HARD — CTA ตรงไปที่ลิงก์ในไบโอ ชัดเจน มั่นใจ:\n"
                "  เป้าหมาย: convert คนที่ดูจบแล้วและพร้อมลงมือ\n"
                "  ✅ 'ถ้าคุณพร้อมจะ [action จาก topic] วันนี้เลย ลิงก์ในไบโอครับ — ผมใช้เองอยู่'\n"
                "  ✅ 'อย่าปล่อยให้ [ปัญหาจาก topic] เกิดขึ้นกับคุณอีก — เริ่มได้เลยที่ลิงก์ในไบโอ'\n"
                "  ✅ 'ลิงก์ในไบโอเลยครับ ใช้เวลาแค่ [X นาที] ก็เริ่มได้แล้ว'\n"
                "  ❌ ห้าม: เว่อร์เกิน / สัญญาว่ารวยแน่ / อ้างตัวเลขผลตอบแทนที่ไม่มีหลักฐาน\n"
                "  ❌ ห้าม: generic — ต้องอ้างอิง pain point / insight จากคลิปนี้โดยตรง"
            ),
        }
        # เมื่อมี forced_cta → ใช้ dynamic CTA section แทน framework template
        # CTA ต้องอ้างถึง insight/ตัวเลขจากคลิปนี้โดยตรง ไม่ใช่ template สำเร็จรูป
        if forced_cta:
            cta_section = f"""[CTA — ประโยคสุดท้าย 1 ประโยค — FORCED TYPE: {forced_cta.upper()}]
{_CTA_FORCED_TEXT.get(forced_cta, '')}

⚠ กฎ CTA ที่ไหลลื่น (สำคัญมาก):
- ต้องอ้างถึง insight / ตัวเลข / สถานการณ์จาก TOPIC นี้โดยตรง — ไม่ใช่ generic
- transition จาก PAYOFF ก่อนหน้าอย่างธรรมชาติ เหมือนเป็นประโยคเดียวกัน
- ✅ "นั่นแหละครับ ทำไมคุณถึงควรเซฟคลิปนี้ไว้ดูทุกครั้งที่ [situation จาก topic]"
- ✅ "ถ้าคุณไม่อยากเจอกับ [ปัญหาจาก topic] ส่งคลิปนี้ให้ [คนที่ relate กับ topic] ด้วยครับ"
- ❌ ห้าม: "เซฟคลิปนี้ไว้เลย" / "กด follow ไว้ก่อน" ล้วนๆ โดยไม่อ้างอิง topic"""
        else:
            cta_section = cta
        cta_override = ""

        # Subtopic avoidance
        subtopic_note = ""
        if used_subtopics:
            subtopic_note = f"\n\n━━━ CONTENT VARIETY ━━━\nหมวดที่ทำไปแล้วใน 5 คลิปล่าสุด: {', '.join(used_subtopics)}\nให้เลือก angle ที่ต่างออกไป — ไม่ต้องเปลี่ยน topic แต่ให้เข้าจาก perspective ที่ต่างกัน"

        return f"""You are a Thai short-form video scriptwriter for a finance channel "เงินงอก". Write a vertical video script (TikTok/Reels/Shorts) in natural spoken Thai.

TOPIC: {topic}
STYLE: {style_text}
FRAMEWORK: {fw["label"]}
ความยาว: {pacing}
⚠ ห้ามตัดเนื้อหาเพื่อให้สั้น — ความยาวคลิปถูกกำหนดโดยเนื้อหา ไม่ใช่เวลา
⚠ ถ้า topic ระบุจำนวน เช่น "5 สกุลเงิน" / "3 ข้อ" → ต้องครบทุกรายการ อธิบายแต่ละข้อ 2-3 ประโยค

━━━ SURPRISE VALUE — ตรวจก่อนเขียน (สำคัญที่สุด) ━━━
เนื้อหาต้องผ่านโจทย์ "คนที่ฟังจบแล้ว จะรู้อะไรที่ตัวเองยังไม่รู้มาก่อน?"
ถ้าตอบไม่ได้ → ให้หา angle ใหม่ทันที

❌ ห้ามใช้ advice ที่ทุกคนรู้อยู่แล้ว (ถ้าเขียน = คลิปนี้ไร้คุณค่า):
  - "ออมก่อนใช้" / "pay yourself first"
  - "ลดค่าใช้จ่าย" / "จดบัญชีรายรับรายจ่าย"
  - "กระจายความเสี่ยง" / "ไม่ควรไข่ทุกใบไว้ในตะกร้าใบเดียว"
  - "ลงทุนในตัวเอง" / "อ่านหนังสือทุกวัน"
  - "ทบต้นทำให้เงินงอก" (ถ้าอธิบายแค่ว่า "ดอกเบี้ยทบต้น" โดยไม่มี twist)
  - คำแนะนำทั่วไปที่มีในทุกบทความการเงิน

✅ เนื้อหาที่มีคุณค่าจริง — เลือก 1 angle นี้:
  1. กลไกที่ซ่อนอยู่: "ทำไม X ถึงเกิดขึ้น" ในระดับที่คนไม่เคยรู้จริง
     เช่น: ทำไมขั้นต่ำบัตรเครดิตถึงถูกออกแบบมาเพื่อทำให้คุณจ่ายนานขึ้น
  2. ตัวเลขที่น่าตกใจเฉพาะ: ข้อมูลจริงที่คนไทยส่วนใหญ่ไม่รู้
     เช่น: ค่าธรรมเนียมประกันที่ซ่อนอยู่ใน unit-linked ว่าหายไปกี่เปอร์เซ็นต์ใน 3 ปีแรก
  3. ความเชื่อผิดที่ทำให้เสียเงิน: ความเชื่อที่ดูถูกแต่ผิดจริงพร้อมหลักฐาน
     เช่น: ทำไมการออมในบัญชีออมทรัพย์ทำให้จนลงจริงๆ (เพราะอัตราเงินเฟ้อ)
  4. ขั้นตอน/กลยุทธ์ที่คนทั่วไปไม่รู้ว่ามี: เทคนิคเฉพาะทางที่ practical
     เช่น: วิธีต่อรองอัตราดอกเบี้ยบ้านให้ลดลง 0.5% ด้วยตัวเอง
  5. ผลกระทบระยะยาวที่ไม่มีใครเตือน: consequence ที่เห็นช้า แต่ใหญ่มาก
     เช่น: การไม่มีกองทุนฉุกเฉินทำให้ต้นทุนชีวิตสูงขึ้นอย่างไร

ตัวอย่าง hook+เนื้อหาระดับ 9/10 ที่ผ่านโจทย์ข้างต้น:
  ✅ "ใครบอกว่าดอลลาร์สหรัฐแข็งที่สุดในโลก? ผิดเลยครับ ดอลลาร์ไม่ติดแม้แต่ Top 5"
     → เนื้อหา: 5 สกุลเงินที่แข็งกว่า พร้อมตัวเลขจริง (1 ดีนาร์คูเวต = 110 บาท) + เหตุผลว่าทำไม
  ✅ "บ้าน 3 ล้านบาท ราคาจริงที่คุณจ่ายคือ 5.2 ล้าน เพราะดอกเบี้ยที่ซ่อนอยู่"
     → เนื้อหา: กลไก reducing balance ที่คนส่วนใหญ่ไม่รู้ พร้อมตัวอย่างจริง ตัวเลขจริง
  ❌ "ออมก่อนใช้ เหลือแล้วค่อยออม ทำแบบนี้ได้เลยครับ" — ทุกคนรู้แล้ว ไม่มีคุณค่า

━━━ VIRAL SCRIPT STRUCTURE ━━━

[HOOK — 0-3 วินาที] 1 ประโยค กระชับ ≤ 12 คำ หยุดนิ้วได้ทันที

━━━ HOOK FORMULA — ยึดผลวิจัย TikTok จริง ━━━

  ⚠ กฎเหล็ก: ใช้ trigger เดียวที่แรงที่สุด อย่าใส่หลาย fact พร้อมกัน
  ⚠ ห้ามใส่ตัวเลขเกิน 1 ตัวใน hook — มากกว่า 1 ทำให้สมองตามไม่ทัน หยุดอ่านก่อนจบ
  ⚠ ห้ามมี em-dash (—) ใน hook — ตัดจังหวะเสียงพาก

  TRIGGER 1 (แรงที่สุด) — LOSS AVERSION: ทำให้ผู้ดูรู้สึกว่ากำลังสูญเสียอยู่ตอนนี้
    Research: การสูญเสียรู้สึกเจ็บปวด 2× กว่าการได้รับสิ่งเดียวกัน (Kahneman)
    สูตร: "[สิ่งที่คนทำอยู่] กำลังทำให้คุณเสีย [X บาท/โอกาส] โดยไม่รู้ตัว"
    ✅ "จ่ายขั้นต่ำบัตรเครดิตทุกเดือน คุณกำลังจ่ายดอกเกิน 100,000 บาทโดยไม่รู้ตัว"
    ✅ "ฝากออมทรัพย์ปีที่แล้ว คุณจนลง 8,000 บาทโดยไม่รู้ตัว"
    ✅ "กองทุนค่าธรรมเนียม 1.5% กินเงินเกษียณคุณไปครึ่งหนึ่ง"

  TRIGGER 2 — PATTERN INTERRUPT: เริ่มด้วยสิ่งที่ขัดกับสิ่งที่คนเชื่ออยู่ทันที
    สูตร: "[สิ่งที่คนทำกันทั่วไป] ผิดหมดเลยครับ" หรือ "[ความจริงที่น่าตกใจ] — ไม่ใช่ [สิ่งที่คิด]"
    ✅ "ดอลลาร์สหรัฐไม่ใช่สกุลเงินที่แข็งที่สุดในโลก ไม่ติดแม้แต่ Top 5"
    ✅ "คนที่ออมเงินทุกเดือนอาจกำลังจนลง ไม่ใช่รวยขึ้น"

  TRIGGER 3 — CURIOSITY GAP: ตั้งคำถามที่ต้องรู้คำตอบ พร้อมบอกว่าสำคัญกับ "คุณ" ยังไง
    สูตร: "[ข้อเท็จจริงที่น่าแปลกใจ] — คุณอยู่ฝั่งไหน?"
    ✅ "คนรวยยืมเงินเพื่อสร้างกำไร คนธรรมดาก็ทำได้ ถ้ารู้วิธีนี้"
    ✅ "วิกฤต 2540 ทำคนไทยสูญ 4.2 ล้านล้านบาท สัญญาณเดิมกำลังเกิดขึ้นอีกครั้ง"

  ❌ ห้าม: ตัวเลข 2 ตัวขึ้นไปใน hook เดียวกัน ("ยืม 3% ได้ 8% กำไร 5%")
  ❌ ห้าม: คำถามที่ไม่บอก value ("รู้มั้ยว่า..." / "เคยสังเกตมั้ย...")
  ❌ ห้าม: ตัวละครสมมติมีชื่อ ("พี่หนุ่ม" "น้องแป้ง")
  ❌ ห้าม: Hook ที่อ่านแล้วยังไม่รู้ว่าตัวเองจะเสียหรือได้อะไร
  → เลือก 1 trigger เท่านั้น → 1 ประโยค → ≤ 12 คำ{hook_avoid_note}

[ASPIRATION PROMISE — 3-6 วินาที] 1 ประโยค — บอกชีวิตที่ดีขึ้นที่ผู้ดูจะได้ ถ้าดูจนจบ
  Research: value promise ที่เป็น aspiration (ชีวิตดีขึ้น) ดีกว่า process (อธิบายว่าทำงานยังไง)
  ✅ "ดูจนจบ แล้วคุณจะปิดหนี้บัตรได้เร็วขึ้น 10 ปี ประหยัดดอกเบี้ยได้อีก 100,000 บาท"
  ✅ "วันนี้จะพาดูว่า ทำไมคนที่รู้เรื่องนี้ เกษียณได้เร็วกว่าคนที่ไม่รู้ถึง 7 ปี"
  ✅ "ถ้าดูจบ คุณจะรู้วิธีทำให้เงินทำงานแทนตัวเอง โดยไม่ต้องทำงานหนักขึ้น"
  ❌ ห้าม: "คลิปนี้จะอธิบายว่า X ทำงานยังไง" — process ไม่ใช่ aspiration
  ❌ ห้าม: "คลิปนี้จะบอกว่า..." แบบที่ไม่ระบุ BENEFIT ชัดเจนว่าชีวิตดีขึ้นยังไง

{body}

[PAYOFF] 1 ประโยค — insight ที่คนไม่เคยนึกถึง รู้แล้วรู้สึกว่า "ดีที่รู้"

{cta_section}

━━━ RETENTION MECHANICS — ยึดผลวิจัย TikTok จริง ━━━

  STRUCTURE ที่ใช้: PSP (Problem → Solution → Proof) — research พิสูจน์ว่าดีกว่า AIDA สำหรับ short-form
    P — Problem (Hook + pain): ทำให้ผู้ดูรู้สึกว่า "นี่คือปัญหาของฉัน" (ประโยค 1-3)
    S — Solution (วิธีแก้): อธิบายสิ่งที่ทำได้จริง ≤ 3 วิธี (ประโยค 4-9)
    P — Proof (ผลลัพธ์จริง): ตัวเลขจริงที่พิสูจน์ว่าใช้ได้ (ประโยค 10-12)

  PATTERN INTERRUPT ทุก 4 วินาที = ทุก 1-2 ประโยค (research: เพิ่ม retention 58%)
    - เปลี่ยน angle / มุมมอง ทุก 2 ประโยค
    - อย่าให้ผู้ดูรู้ว่าประโยคถัดไปจะพูดอะไร → ต้องฟังต่อ

  ❌ ห้ามใช้: "แต่นี่ยังไม่ใช่ส่วนที่น่าสนใจที่สุด" / "แต่นั่นยังไม่ใช่ส่วนที่น่ากลัวที่สุด"
  ❌ ห้ามใช้ LIST FORMAT: "ข้อ 1... ข้อ 2... ข้อ 3..." โดยไม่มีการเล่าเรื่องนำ
    → ถ้าจะใช้ list ต้องมีปัญหาที่ relate ได้ก่อน แล้วค่อยแสดง solution เป็นข้อ
  ✅ ใช้แทน: บอกตัวเลขที่น่าตกใจทันที / ตั้งคำถามที่ต้องรู้คำตอบ / เล่าผลลัพธ์ก่อนแสดงวิธี

  ⚠ ประโยคที่ 5-6 = จุดที่คนมักกดออก → ต้องมี tension หรือ twist ที่ทำให้ต้องอยู่ต่อ
  ⚠ ประโยคสุดท้ายก่อน CTA: ต้องให้ผู้ดูรู้สึก "คุ้มมากที่ดูจนจบ" หรือ "ต้องบอกเพื่อน"
  ⚠ Payoff ต้องอยู่ใน 15 วินาทีแรก (research: เพิ่ม retention 20%)

━━━ AUDIENCE ━━━
มือใหม่ด้านการเงิน ไม่มีความรู้พื้นฐานเลย วัยทำงาน 22-35 ปี อยู่ในกรุงเทพหรือเมืองใหญ่
→ อธิบายทุกคำศัพท์เฉพาะด้วยภาษาพูดทันทีหลังพูดถึง เช่น "ระยะรอคอย คือช่วงเวลาหลังซื้อที่ยังเคลมไม่ได้"
→ ใช้ภาษาง่ายที่สุดเท่าที่เป็นไปได้ — เหมือนคุยกับเพื่อนที่ไม่รู้เรื่องการเงินเลย
→ ทุกประโยคต้องเข้าใจได้ทันทีโดยไม่ต้องคิด — ถ้าต้องหยุดคิดแปลความ = ยากเกินไป
→ ใช้คำสั้นกระชับ ภาษาพูดธรรมดา: "จ่าย" แทน "ชำระ" | "หนี้" แทน "ภาระหนี้สิน" | "ได้เงิน" แทน "ได้รับผลตอบแทน"
→ เวลาพูดถึงการสูญเสียเงิน: ใช้ "สูญเสีย" เสมอ ห้ามใช้ "สูญ" โดด (ฟังแล้วไม่ชัด) เช่น "สูญเสีย 4.2 ล้านล้านบาท" ไม่ใช่ "สูญ 4.2 ล้านล้านบาท"
→ จังหวะการเล่า: ประโยคสั้น → หยุดหายใจ → ประโยคถัดไป ไม่รีบ ไม่ยัดข้อมูลพร้อมกัน
→ เว้นจังหวะดี: ข้อมูล 1 อย่าง = 1 ประโยค ห้ามยัดหลาย fact ในประโยคเดียว

━━━ LANGUAGE RULES (ห้ามละเมิด) ━━━
- ❌ ห้ามสร้างตัวละครสมมติ ห้ามตั้งชื่อสมมติ เช่น "พี่มิ้น" "พี่กอล์ฟ" "น้องมินต์" "พี่ต้อม" ทุกกรณี
  → ใช้ "ผม" (first-person) หรือ "คุณ" (second-person) หรือ role ทั่วไป เช่น "คนทำงาน" "มนุษย์เงินเดือน" "นักลงทุนมือใหม่" เท่านั้น
- ห้ามใช้ศัพท์อังกฤษการเงิน: cashflow, portfolio, compound, yield, asset, liability, leverage, hedge, diversify, ROI, ETF, DCA
- แปลเป็นภาษาไทย: cashflow→เงินหมุนเวียน | portfolio→กลุ่มลงทุน | compound→ดอกเบี้ยทบต้น | DCA→ลงทุนสม่ำเสมอทุกเดือน
- คำทับศัพท์ที่ใช้ได้: podcast, app, save, follow
- อธิบายเหมือนสอนเพื่อน ไม่ใช่บรรยายในห้องเรียน
- ต้องมี analogy อย่างน้อย 1 ครั้ง: 'เหมือนกับ...' / 'ลองนึกภาพ...' / 'เปรียบเหมือน...' — ทำให้ concept เข้าใจง่ายขึ้น
- ตัวเลขต้องจริงและชัดเจน ห้ามใช้คำกำกวม: หลายพัน / หลายหมื่น / ไม่กี่บาท / ประมาณ
- กฎหมาย/ความปลอดภัย: ห้ามระบุชื่อสถาบันการเงิน ธนาคาร บริษัทประกัน กองทุน หรือองค์กรใดในเชิงลบหรือที่อาจทำให้เสื่อมชื่อเสียง — ใช้ "ธนาคาร" / "สถาบันการเงิน" ทั่วไปแทน
- เสียงชาย: ใช้ "ครับ" เท่านั้น ห้ามใช้ "คะ" "ค่ะ" "จ้ะ" หรือคำลงท้ายเสียงหญิงทุกรูปแบบ
- ความเข้าใจ: ทุก point/ข้อ ต้องมีครบ 3 ส่วน → (1) ชื่อปัญหาพร้อมอธิบายในภาษาพูด (2) ผลกระทบเป็นเงิน/ตัวเลขที่ชัดเจน (3) วิธีเช็คหรือ action ที่ทำได้เลย
- ห้ามพูดศัพท์เทคนิคลอยๆ โดยไม่อธิบาย — ต้องมีคำอธิบายภาษาง่ายตามทันที
- ฟังจบแล้วต้องรู้ว่า "ต้องทำอะไร" ไม่ใช่แค่ "รู้ว่ามีปัญหา"

━━━ CONVERSATION RULES ━━━
- ภาษาพูดธรรมชาติ ใช้คำเชื่อม: "แต่", "เพราะ", "จริงๆ แล้ว", "ที่น่าสนใจคือ"
- ⚠ จังหวะเสียงพาก: ใส่จุลภาค (,) ที่จุดหายใจธรรมชาติ เพื่อให้เสียงพักถูกที่
  เช่น "ดอกเบี้ย flat rate, คือการคิดดอกจากยอดเต็มตลอด, ไม่ใช่ยอดที่เหลือ"
  ใส่จุลภาคก่อน: แต่ / เพราะ / ดังนั้น / จึง / ซึ่ง / ทำให้
- แต่ละ sentence ไม่เกิน 8 คำ — ถ้ายาวกว่าให้แบ่ง 2 ประโยคใน array
- ตัวเลขต้องเป็นอาหรับ (0-9) เท่านั้น
- แต่ละ sentence ไม่เกิน 6 คำ — ถ้ายาวกว่าให้แบ่ง 2 ประโยคใน array (ช่วยให้ scene cut บ่อยขึ้น)
- ⚠ ตัวเลขต้องอยู่กับหน่วยในประโยคเดียวกันเสมอ ห้ามแยกคนละประโยค:
  "50,000 บาท" ต้องอยู่ประโยคเดียว | "ข้อ 1" ต้องอยู่ประโยคเดียว | "18% ต่อปี" ต้องอยู่ประโยคเดียว
  ห้าม: [...เสีย 50,000"] + ["บาท ต่อปี..."] — บาท/% ต้องอยู่กับตัวเลขเสมอ
- ⚠ ตัวเลขต้องมี comma: 50,000 / 163,000 / 1,500 — ห้ามเขียนชิดติดกันไม่มีจุลภาค เช่น 50000
- ⚠ เนื้อหาต้องใช้ได้กับคนทั้งประเทศ ไม่ใช่เฉพาะกรุงเทพฯ:
  ห้ามอ้างชื่อย่าน/พื้นที่เฉพาะเจาะจง เช่น "ย่านวัฒนา" "ทองหล่อ" "อโศก" — ใช้ "ที่ดินในเมืองใหญ่" หรือ "ทำเลดี" แทน
  ถ้า topic เป็นเรื่องอสังหา ให้ยกตัวอย่างที่ relate ได้กับคนทั่วประเทศ (ราคา %, ผลตอบแทน) ไม่ใช่ชื่อสถานที่เฉพาะ
- ห้ามขึ้นต้นประโยคซ้ำกันเกิน 1 ครั้ง
- keyword หลักของ topic ต้องปรากฏบนหน้าจอ (ใน sentence) อย่างน้อย 3 ครั้งตลอดคลิป — ช่วย TikTok SEO
- Comment CTA: ต้องถามคำถาม specific ที่คนอยากตอบทันที เช่น "คอมเมนต์บอก ตอนนี้คุณออมเงินกี่เปอร์เซ็นต์ของเงินเดือน?"
- NUMBER CONSISTENCY (สำคัญมาก): ถ้า topic หรือ hook ระบุตัวเลข เช่น "5 สกุลเงิน" / "3 ข้อ" / "4 อันดับ"
  ต้องครบทุกรายการ อธิบายแต่ละรายการ 2-3 ประโยค — ห้ามข้าม ห้ามรวม ห้ามกล่าวถึงแค่บางส่วน
  ถ้า "5 สกุลเงิน" → ต้องมีทั้ง 5 สกุล ชื่อ + อัตรา + เหตุผลทุกตัว
- sentence_keywords: 4-6 คำภาษาอังกฤษ เป็น visual stock footage description สำหรับ Pexels
  ✅ ดี (finance visuals ที่ค้นหาเจอจริงๆ):
    "Asian man reviewing investment portfolio on laptop screen"
    "hands stacking Thai baht coins on wooden table"
    "person checking banking app on smartphone close up"
    "financial chart going up on computer monitor"
    "calculator and documents on office desk with coins"
    "young Asian professional looking worried at credit card bill"
    "piggy bank with coins falling in"
    "stock market graph on tablet screen"
  ❌ ไม่ดี:
    "money tips" / "finance concept" / "saving money" — abstract, ไม่ค้นเจอ
    "call center scripts" / "business meeting" / "office" — ไม่เกี่ยวกับการเงิน
    ชื่อโปรแกรม/แอป เฉพาะ (RMF, Finnomena ฯลฯ) — ไม่มีใน stock
  กฎ: ต้องมี ใคร/อะไร (person/hands/chart) + action + context — ห้ามแค่ concept word

OUTPUT JSON เท่านั้น ห้ามมีข้อความอื่น:
{{
  "title": "ชื่อน่าดึงดูด ≤ 60 ตัวอักษร",
  "voice": "male หรือ female",
  "sentences": ["ประโยค 1", "ประโยค 2", "...รวม 10-13 ประโยค"],
  "sentence_keywords": ["keyword 1", "keyword 2", "...ตรงกับ sentences 1:1"]
}}{subtopic_note}{cta_override}"""

    def generate_all_platform_captions(self, title: str, sentences: list,
                                       topic: str, framework: str = "list") -> dict:
        """สร้าง caption แยกสำหรับ TikTok / Instagram / Facebook / YouTube"""
        script_summary = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(sentences))

        prompt = f"""สร้าง caption สำหรับ 4 platform สำหรับวิดีโอการเงินภาษาไทย

ชื่อวิดีโอ: {title}
Topic: {topic}

เนื้อหาจริงในคลิป (ใช้สรุปตรงๆ จากนี้ — ห้ามเพิ่มเนื้อหาที่ไม่มีในคลิป):
{script_summary}

กฎแต่ละ platform:
TikTok — ≤150 ตัวอักษร เริ่มด้วย keyword ไม่ใช่ emoji | hashtags 15 อัน | จบด้วยคำถาม specific
Instagram Reels — 3-4 ประโยค personal | hashtags 28-30 อัน | จบด้วย "💾 save ไว้ก่อนเลย"
Facebook — 4-5 ประโยค conversational | hashtags 3-5 อัน | จบด้วยคำถามกระตุ้น comment
YouTube — title SEO ≤60 ตัวอักษร | description 2-3 ประโยค | tags 15 อัน | ใส่ #Shorts

สำคัญมาก: OUTPUT เป็น 4 บรรทัด แต่ละบรรทัดคือ JSON object เดียว ห้ามมีบรรทัดว่างหรือข้อความอื่น
บรรทัดที่ 1 (tiktok)   : {{"platform":"tiktok","caption":"...","hashtags":["#tag1",...]}}
บรรทัดที่ 2 (instagram): {{"platform":"instagram","caption":"...","hashtags":["#tag1",...]}}
บรรทัดที่ 3 (facebook) : {{"platform":"facebook","caption":"...","hashtags":["#tag1",...]}}
บรรทัดที่ 4 (youtube)  : {{"platform":"youtube","title":"...","description":"...","tags":["tag1",...]}}"""

        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            result = self._extract_platform_jsons(raw)
            if result:
                logger.info(f"Platform captions: {list(result.keys())}")
            else:
                logger.warning("Platform captions: no valid JSON objects found")
            return result
        except Exception as e:
            logger.warning(f"Platform captions failed: {e}")
        return {}

    @staticmethod
    def _extract_platform_jsons(raw: str) -> dict:
        """Extract platform JSON objects from raw text — handles multi-line objects and ``` fences"""
        result = {}
        # collect JSON objects using brace-depth counting
        buf, depth, in_str, esc = [], 0, False, False
        for ch in raw:
            if esc:
                buf.append(ch); esc = False; continue
            if ch == '\\' and in_str:
                buf.append(ch); esc = True; continue
            if ch == '"':
                in_str = not in_str
            if not in_str:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
            buf.append(ch)
            if depth == 0 and buf and buf[0] == '{':
                candidate = ''.join(buf).strip()
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    # escape literal newlines inside string values then retry
                    fixed, inside, esc2 = [], False, False
                    for c in candidate:
                        if esc2:
                            fixed.append(c); esc2 = False
                        elif c == '\\' and inside:
                            fixed.append(c); esc2 = True
                        elif c == '"':
                            inside = not inside; fixed.append(c)
                        elif c in ('\n', '\r') and inside:
                            fixed.append('\\n')
                        else:
                            fixed.append(c)
                    try:
                        obj = json.loads(''.join(fixed))
                    except json.JSONDecodeError:
                        buf, in_str, esc = [], False, False
                        continue
                platform = obj.pop("platform", None)
                if platform in ("tiktok", "instagram", "facebook", "youtube"):
                    result[platform] = obj
                buf, in_str, esc = [], False, False
            elif depth == 0:
                buf = []
        return result

    def generate_caption(self, title: str, sentences: list, topic: str) -> dict:
        """สร้าง TikTok caption + hashtag ด้วย Claude Haiku"""
        hook = sentences[0] if sentences else ""
        prompt = f"""สร้าง TikTok caption สำหรับวิดีโอการเงินภาษาไทย

ชื่อวิดีโอ: {title}
Hook: {hook}
Topic: {topic}

สร้าง:
1. caption 2-3 ประโยค — น่าสนใจ กระตุ้นให้ comment หรือ save
   (เขียนเป็นภาษาพูด ไม่ต้องการ emoji มากเกินไป)
2. hashtag 15 อัน — ผสม Thai + English เรียงจากเฉพาะไปกว้าง
   ภาษาไทยจำเป็น: #การเงิน #ออมเงิน #ลงทุน #เก็บเงิน #เงิน
   ภาษาอังกฤษ: #moneytips #personalfinance #financetips #tiktokfinance
   Viral: #fyp #foryoupage #viral #tiktokthailand

OUTPUT JSON เท่านั้น:
{{"caption": "...", "hashtags": ["#tag1", "#tag2", ...]}}"""
        try:
            msg = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            m = re.search(r'\{.*?\}', raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
                return {
                    "caption": data.get("caption", ""),
                    "hashtags": data.get("hashtags", []),
                }
        except Exception as e:
            logger.warning(f"Caption generation failed: {e}")
        return {"caption": title, "hashtags": []}

    def _parse(self, raw: str, topic: str) -> dict:
        # ดึง JSON block ออกจาก response (Claude อาจแนบ ```json ... ```)
        json_text = raw.strip()
        if "```" in json_text:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_text, re.DOTALL)
            if m:
                json_text = m.group(1)
        else:
            # หา { ... } block แรก
            start = json_text.find("{")
            end   = json_text.rfind("}") + 1
            if start != -1 and end > start:
                json_text = json_text[start:end]

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed ({e}) — fallback empty script")
            data = {}

        title    = normalize_numbers(data.get("title", topic))
        voice_v  = str(data.get("voice", "")).lower()
        voice_gender = "female" if "female" in voice_v else "male"

        raw_sentences = data.get("sentences", [])
        sentences = [normalize_numbers(s.strip()) for s in raw_sentences if str(s).strip()]
        sentences = [_sanitize_sentence(s) for s in sentences]

        raw_kws = data.get("sentence_keywords", [])
        sentence_keywords = [str(k).strip() for k in raw_kws]

        # align lengths
        while len(sentence_keywords) < len(sentences):
            sentence_keywords.append(topic.split()[0].lower())
        sentence_keywords = sentence_keywords[:len(sentences)]

        pexels_keywords = list(dict.fromkeys(k for k in sentence_keywords if k))[:5] or [topic.split()[0].lower()]

        logger.info(f"Script: {len(sentences)} sentences | voice={voice_gender} | keywords: {pexels_keywords[:3]}")
        return {
            "title": title,
            "description": "",
            "tags": [],
            "pexels_keywords": pexels_keywords,
            "sentence_keywords": sentence_keywords,
            "voice_gender": voice_gender,
            "sentences": sentences,
            "full_text": "\n".join(sentences),
        }
