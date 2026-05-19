"""
Long-form script generator for 8-10 minute YouTube videos.
Generates structured scripts with 3-5 sections, each extractable as a standalone Short.
"""

import json
import re
from loguru import logger

# 8-10 min at 1.1 WPS = ~530-660 Thai tokens
# Intro: ~60 tokens, each section: ~100-130 tokens, outro: ~60 tokens
_SECTION_COUNT = 4  # default sections → 4 shorts

_LONG_FORM_PROMPT = """คุณคือ Content Creator ผู้เชี่ยวชาญด้านการเงินส่วนบุคคลภาษาไทย สไตล์ storytelling ไหลลื่น น่าติดตาม
สร้าง script สำหรับ YouTube video ความยาว 8-10 นาที เรื่อง: {topic}

โครงสร้างที่ต้องการ (เขียน JSON เท่านั้น ห้ามมีข้อความอื่น):

{{
  "seo_title": "หัวข้อ SEO ที่คนค้นหาบ่อย ≤60 ตัวอักษร ใส่ตัวเลขหรือปี ดึงดูด",
  "seo_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "intro": [
    "hook ช็อกสั้นๆ — ตัวเลขหรือ statement ที่คนไม่คาดคิด",
    "ขยายความ hook ให้น่าสนใจ เชื่อมกับชีวิตคนดู",
    "บอกว่าจะเปิดเผย 4 สาเหตุหลักที่คนมักไม่รู้",
    "สัญญากับคนดูว่า ถ้าดูจนจบจะรู้อะไร และชีวิตจะเปลี่ยนยังไง"
  ],
  "sections": [
    {{
      "title": "สาเหตุที่ 1: ชื่อสั้นกระชับ",
      "transition_in": "ประโยค transition นำเข้า section นี้อย่างเป็นธรรมชาติ เชื่อมจาก intro",
      "short_hook": "hook 1 ประโยคสำหรับทำ Short — ดึงดูดใน 3 วินาที",
      "cta_teaser": "CTA ที่ส่งคนไป YouTube — ต้องบอกว่า 'ยังมีอีก X ข้อที่อันตรายกว่า' ก่อน แล้วค่อยบอกให้ไปดู (ดูตัวอย่างด้านล่าง)",
      "sentences": [
        "สาเหตุที่ 1 ที่คนส่วนใหญ่ไม่รู้คือ...",
        "ขยายความ — เกิดอะไรขึ้นจริงๆ",
        "ตัวอย่างหรือสถิติที่ทำให้เห็นภาพชัด",
        "เหตุผลที่คนทำแบบนี้โดยไม่รู้ตัว",
        "ผลกระทบระยะยาวที่น่ากลัว",
        "วิธีแก้ไขที่ทำได้ทันที",
        "ประโยค cliffhanger: แต่สาเหตุที่ 2 นั้น ซ่อนอยู่ในสิ่งที่คุณทำทุกวัน..."
      ]
    }},
    {{
      "title": "สาเหตุที่ 2: ชื่อสั้นกระชับ",
      "transition_in": "transition เชื่อม section 1 กับ 2 อย่างเป็นธรรมชาติ",
      "short_hook": "hook สำหรับ Short 2",
      "sentences": [
        "สาเหตุที่ 2 คือ...",
        "...6-7 ประโยค + cliffhanger ไปข้อ 3..."
      ]
    }},
    {{
      "title": "สาเหตุที่ 3: ชื่อสั้นกระชับ",
      "transition_in": "transition เชื่อม section 2 กับ 3",
      "short_hook": "hook สำหรับ Short 3",
      "sentences": [
        "สาเหตุที่ 3 คือ...",
        "...6-7 ประโยค + cliffhanger ไปข้อ 4..."
      ]
    }},
    {{
      "title": "สาเหตุที่ 4: ชื่อสั้นกระชับ",
      "transition_in": "transition เชื่อม section 3 กับ 4",
      "short_hook": "hook สำหรับ Short 4",
      "sentences": [
        "สาเหตุที่ 4 ที่สำคัญที่สุดคือ...",
        "...6-7 ประโยค จบแบบ payoff ใหญ่..."
      ]
    }}
  ],
  "outro": [
    "สรุป 4 สาเหตุในประโยคเดียว กระชับทรงพลัง",
    "action item ที่คนดูทำได้วันนี้เลย 1 อย่าง",
    "กด Subscribe เพื่อดูคลิปการเงินใหม่ทุกวัน — บอกว่าคลิปหน้าเรื่องอะไร",
    "ปิดด้วยประโยคสร้างแรงบันดาลใจสั้นๆ ที่คนอยากแชร์"
  ]
}}

กฎสำคัญ:
- ทุก section ต้องบอกชัดว่า "สาเหตุที่ X" หรือ "ข้อที่ X" เพื่อให้คนติดตามได้
- ทุก section มี transition_in นำเข้า และ cliffhanger นำออก (ยกเว้น section สุดท้าย)
- ใส่ตัวเลข/สถิติจริงทุก section — ห้ามใช้ตัวเลขสุ่ม
- ห้ามระบุชื่อสถาบันการเงิน/ธนาคารในเชิงลบ
- แต่ละ section มี 7-8 ประโยค รวม transition + cliffhanger
- เนื้อหาต้องไหลลื่น เหมือนเพื่อนเล่าให้ฟัง ไม่ใช่อ่านตำรา
- เขียนในเชิง "ให้ความรู้/ข้อมูล" เท่านั้น — ห้ามใช้ภาษาที่เป็นคำแนะนำทางการเงินโดยตรง เช่น "คุณควรลงทุน X" หรือ "ซื้อ Y ทันที" ให้ใช้ "ผู้เชี่ยวชาญมองว่า..." / "ข้อมูลที่ควรรู้คือ..." / "สิ่งที่คนส่วนใหญ่ทำคือ..." แทน
- ประโยคสุดท้ายของ outro ต้องลงท้ายด้วย: "เนื้อหานี้เป็นข้อมูลเพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำทางการเงิน"

สำหรับ cta_teaser — ต้อง "ส่ง" ก่อน ไม่ใช่สั่งตรงๆ:
ตัวอย่างที่ดี:
✅ "นี่แค่สาเหตุที่ 1 ยังมีอีก 3 ข้อที่อันตรายกว่านี้ และข้อที่ 2 มันซ่อนอยู่ในสิ่งที่คุณทำทุกวัน — ดูคลิปเต็มได้ที่ YouTube เงินงอก ลิงก์อยู่ที่แคปชั่น"
✅ "แค่รู้ข้อนี้ยังไม่พอ เพราะข้อที่เหลือคือตัวที่ทำให้คนส่วนใหญ่ไม่มีเงินเก็บแม้ทำงาน 10 ปี — ไปดูคลิปเต็มกัน"
✅ "ข้อนี้กระทบเงินในกระเป๋าคุณอยู่แล้ว แต่ข้อต่อไปมันเลวร้ายกว่านี้อีก — ดูต่อได้ที่ YouTube เงินงอก"
❌ "ดูคลิปเต็มได้ที่ YouTube" (ไม่มีการส่ง ไม่มีเหตุผลให้คนคลิก)
❌ "กด Subscribe เพื่อดูเพิ่มเติม" (ไม่เจาะจง)

กฎ cta_teaser: 1-2 ประโยค, บอกว่า "ยังมีอะไรที่น่าสนใจ/อันตรายกว่า" + ชื่อ platform + ชื่อช่อง
- ห้ามใช้คำว่า "description" หรือ "bio" — ใช้ "ลิงก์อยู่ที่แคปชั่น" แทน
- Output เป็น JSON เท่านั้น"""


def generate_long_form_script(topic: str, client, model: str = "claude-sonnet-4-6") -> dict:
    """
    Generate structured 8-10 minute script with 4 sections.
    Returns dict with: seo_title, seo_keywords, intro, sections, outro
    Retries up to 3 times on JSON parse failure.
    """
    prompt = _LONG_FORM_PROMPT.format(topic=topic)
    required = ["seo_title", "seo_keywords", "intro", "sections", "outro"]

    for attempt in range(1, 4):
        logger.info(f"Generating long-form script (attempt {attempt}/3): {topic}")
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Extract JSON block
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logger.warning(f"Attempt {attempt}: No JSON found in response")
            continue

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            logger.warning(f"Attempt {attempt}: JSON parse error — {e}")
            continue

        missing = [k for k in required if k not in data]
        if missing:
            logger.warning(f"Attempt {attempt}: Missing keys {missing}")
            continue

        logger.success(f"Long script generated: {data['seo_title']} ({len(data['sections'])} sections)")
        return data

    raise ValueError(f"Failed to generate valid script after 3 attempts for: {topic}")


def extract_all_sentences(script_data: dict) -> list[str]:
    """รวมทุก sentence จาก intro + sections (+ transition) + outro เป็น list เดียว"""
    sentences = []
    sentences.extend(script_data.get("intro", []))
    for section in script_data.get("sections", []):
        # ใส่ transition_in ก่อน sentences ของแต่ละ section
        if section.get("transition_in"):
            sentences.append(section["transition_in"])
        sentences.extend(section.get("sentences", []))
    sentences.extend(script_data.get("outro", []))
    return sentences


def build_short_script(section: dict, style: str = "teaser",
                        youtube_url: str = "",
                        platform: str = "youtube") -> list[str]:
    """
    สร้าง sentence list สำหรับ Short จาก section
    style:    "teaser" (โยนไป YouTube/IG) | "complete" (จบในตัว FB)
    platform: "youtube" (CTA → ลิงก์ใน description)
              "instagram" (CTA → ลิงก์ใน bio)
    """
    hook      = section.get("short_hook", "")
    sentences = section.get("sentences", [])
    title     = section.get("title", "")

    result = []
    if hook:
        result.append(hook)

    if style == "teaser":
        cutoff = max(3, int(len(sentences) * 0.65))
        result.extend(sentences[:cutoff])

        cta = section.get("cta_teaser", "")

        if platform == "instagram":
            # Instagram: ลิงก์อยู่ที่หน้าโปรไฟล์
            cta = cta.replace("ลิงก์ใน description", "ลิงก์อยู่ที่หน้าโปรไฟล์")
            cta = cta.replace("ลิงก์ใน bio", "ลิงก์อยู่ที่หน้าโปรไฟล์")
            if not cta:
                cta = (
                    f"นี่แค่ {title} เดียว ยังมีอีกหลายข้อที่น่ากลัวกว่านี้ "
                    f"— ดูคลิปเต็มได้ที่ YouTube เงินงอก ลิงก์อยู่ที่หน้าโปรไฟล์"
                )
        else:
            # YouTube Shorts: ลิงก์อยู่ที่แคปชั่น
            cta = cta.replace("ลิงก์ใน bio", "ลิงก์อยู่ที่แคปชั่น")
            cta = cta.replace("ลิงก์ใน description", "ลิงก์อยู่ที่แคปชั่น")
            if not cta:
                cta = (
                    f"นี่แค่ {title} เดียว ยังมีอีกหลายข้อที่น่ากลัวกว่านี้ "
                    f"— ดูคลิปเต็มได้ที่ YouTube เงินงอก ลิงก์อยู่ที่แคปชั่น"
                )
        result.append(cta)
    else:
        # FB complete — จบครบทุก sentence
        result.extend(sentences)
        result.append("ถ้าชอบคลิปนี้ กด Follow ไว้เลย มีคลิปการเงินดีๆ มาทุกวัน")

    return result


def generate_long_captions(script_data: dict, sections_timestamps: list[dict]) -> dict:
    """
    สร้าง captions สำหรับ YouTube long-form video
    sections_timestamps: [{"title": str, "start_sec": int}]
    Returns YouTube caption dict
    """
    title = script_data["seo_title"]
    keywords = script_data.get("seo_keywords", [])

    # Build chapter markers
    chapters = "\n".join(
        f"{_sec_to_timecode(s['start_sec'])} {s['title']}"
        for s in sections_timestamps
    )

    description = f"""{title}

ในคลิปนี้คุณจะได้เรียนรู้:
{chapters}

━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 Subscribe เพื่อดูคลิปความรู้การเงินใหม่ทุกวัน
💾 Save คลิปนี้ไว้ดูทีหลัง

#เงินงอก #การเงินส่วนบุคคล #ออมเงิน #ลงทุน {' '.join('#' + k for k in keywords[:5])}
"""

    tags = ["การเงินส่วนบุคคล", "ออมเงิน", "ลงทุน", "เงินงอก", "NgernNgork"] + keywords

    return {
        "title": title,
        "description": description.strip(),
        "tags": tags[:15],
    }


def _sec_to_timecode(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
