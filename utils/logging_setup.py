import logging
from datetime import datetime
from pathlib import Path


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> Path:
    """配置根 logger：同时写控制台与带时间戳的日志文件；返回日志路径。
    Configure root logger (console + timestamped file); return log file path."""
    logs_path = Path(log_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_path / f"run_{timestamp}.log"

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return log_file
