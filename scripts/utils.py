from pathlib import Path
import yaml


SUPPORTED_FORMATS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def load_config(config_path: str = "config/settings.yaml") -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def find_videos(input_dir: str) -> list[Path]:
    input_dir = Path(input_dir)
    return [p for p in input_dir.iterdir() if p.suffix.lower() in SUPPORTED_FORMATS]
