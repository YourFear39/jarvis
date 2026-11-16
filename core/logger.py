"""
Централизованное логирование Джарвиса.
Файл: data/logs/jarvis.log (ротация 5 МБ × 5 файлов).
Консоль: только WARNING и выше, чтобы не дублировать Rich-вывод.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _setup() -> logging.Logger:
    logger = logging.getLogger("jarvis")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Откладываем импорт config, чтобы избежать циклических импортов
    import config
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файл — DEBUG, ротация 5 МБ × 5 копий (полный след для отладки)
    fh = RotatingFileHandler(
        log_dir / "jarvis.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Консоль — WARNING+ (не засоряем Rich-вывод, ошибки всё равно видны)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False

    return logger


_root = _setup()


def get_logger(name: str) -> logging.Logger:
    """Возвращает дочерний логгер для модуля: jarvis.<name>."""
    return logging.getLogger(f"jarvis.{name}")
