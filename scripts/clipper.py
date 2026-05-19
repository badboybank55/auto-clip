from pathlib import Path
from loguru import logger
from moviepy.editor import VideoFileClip


class Clipper:
    def __init__(self, config: dict):
        self.config = config
        self.duration = config["clip"]["duration"]
        self.output_format = config["clip"]["format"]

    def clip(self, input_path: str, output_dir: str, start: float = 0, duration: float = None) -> str:
        duration = duration or self.duration
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = f"{input_path.stem}_{int(start)}s.{self.output_format}"
        output_path = output_dir / output_name

        logger.info(f"Clipping: {input_path.name} [{start}s — {start + duration}s]")

        with VideoFileClip(str(input_path)) as video:
            end = min(start + duration, video.duration)
            clip = video.subclip(start, end)
            clip.write_videofile(str(output_path), logger=None)

        logger.success(f"Saved: {output_path}")
        return str(output_path)

    def clip_all(self, input_path: str, output_dir: str) -> list[str]:
        input_path = Path(input_path)
        outputs = []

        with VideoFileClip(str(input_path)) as video:
            total = video.duration
            logger.info(f"Total duration: {total:.1f}s — splitting every {self.duration}s")

        start = 0
        while start < total:
            out = self.clip(input_path, output_dir, start=start)
            outputs.append(out)
            start += self.duration

        return outputs
