import re
from pathlib import Path
from loguru import logger
from .subtitle_renderer import fix_thai_digits, fix_subtitle_file, _thai_word_to_arabic


def _srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    ms = int(round((s % 1) * 1000))
    if ms >= 1000:   # rounding overflow (0.9995 × 1000 → 1000)
        ms = 0
        sec += 1
        if sec >= 60:
            sec = 0
            m += 1
            if m >= 60:
                m = 0
                h += 1
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


class SubtitleGenerator:
    def generate_srt(self, timing_data: list, output_path: str) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Dedup: merge adjacent items ที่มีข้อความเดิม (เกิดจาก _split_long_scenes)
        merged = []
        for item in timing_data:
            if merged and merged[-1]["text"] == item["text"]:
                merged[-1] = dict(merged[-1], end=item["end"])
            else:
                merged.append(dict(item))

        blocks = []
        for i, item in enumerate(merged, 1):
            text = fix_thai_digits(item["text"])
            text = " ".join(_thai_word_to_arabic(w) for w in text.split())
            text = re.sub(r'(?<!\d),|,(?!\d)', '', text)  # ลบ comma pause แต่รักษา 160,000
            blocks.append(
                f"{i}\n"
                f"{_srt_time(item['start'])} --> {_srt_time(item['end'])}\n"
                f"{text}\n"
            )

        output_path.write_text("\n".join(blocks), encoding="utf-8-sig")
        # postprocess อีกรอบ (belt-and-suspenders)
        fix_subtitle_file(str(output_path))
        logger.info(f"SRT → {output_path} ({len(timing_data)} lines)")
        return str(output_path)

    def generate_ass(self, timing_data: list, output_path: str,
                     font_size: int = 80, resolution: str = "1080x1920") -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        w, h = resolution.split("x")

        header = (
            "[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,Sarabun,{font_size},&H0033E0FF,&H00000000,"
            "&H80000000,1,0,0,1,4,1,2,30,30,100,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )

        def ass_t(s: float) -> str:
            h2 = int(s // 3600)
            m2 = int((s % 3600) // 60)
            return f"{h2}:{m2:02d}:{s % 60:05.2f}"

        lines = [header]
        for item in timing_data:
            text = fix_thai_digits(item["text"])
            lines.append(
                f"Dialogue: 0,{ass_t(item['start'])},{ass_t(item['end'])},"
                f"Default,,0,0,0,,{text}"
            )

        output_path.write_text("\n".join(lines), encoding="utf-8-sig")
        fix_subtitle_file(str(output_path))
        logger.info(f"ASS → {output_path}")
        return str(output_path)
