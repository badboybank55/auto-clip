import sys
from pathlib import Path
import yaml
from loguru import logger


def load_config(config_path: str = "config/settings.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logger(config: dict):
    log_file = config["logging"]["file"]
    level = config["logging"]["level"]
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(log_file, level=level, rotation="10 MB", encoding="utf-8")
