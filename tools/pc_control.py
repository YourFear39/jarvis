"""
Инструменты управления ПК — доступны LLM через tool_use.
Создание файлов с содержимым, просмотр директорий, выполнение команд.

Безопасность: все операции проходят через core/safety.py.
  SAFE      → выполняется сразу
  CONFIRM   → показывается пользователю, ждёт "да"
  FORBIDDEN → отказано с объяснением
"""

import os
import subprocess
from pathlib import Path

import config
from core.logger import get_logger
from core.safety import (
    SafetyLevel,
    classify_powershell,
    classify_file_write,
    classify_file_read,
    request_confirmation,
)

log = get_logger("pc_control")


def create_file_with_content(path: str, content: str) -> str:
    """
    Создаёт файл по указанному пути с заданным содержимым.
    Поддерживает: txt, md, bat, ps1, py, js, html, json, csv, ini, reg и любые текстовые форматы.
    Для .docx — использует python-docx если установлен, иначе сохраняет как txt.
    """
    p = Path(path.strip('"\''))

    # Классификация безопасности пути
    level, reason = classify_file_write(str(p))

    if level == SafetyLevel.FORBIDDEN:
        log.warning(f"[File] FORBIDDEN запись: {p}")
        return f"Отказано: {reason}, сэр."

    if level == SafetyLevel.CONFIRM:
        desc = f"создать файл: {p}"
        if not request_confirmation(desc, reason):
            return "Создание файла отменено, сэр."

    log.info(f"[File] Создание файла: {p}")

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        ext = p.suffix.lower()

        if ext == ".docx":
            try:
                from docx import Document
                doc = Document()
                for line in content.split("\n"):
                    doc.add_paragraph(line)
                doc.save(str(p))
                return f"Документ Word «{p.name}» создан, сэр."
            except ImportError:
                p = p.with_suffix(".txt")
                p.write_text(content, encoding="utf-8")
                return f"python-docx не установлен — сохранил как «{p.name}» (txt), сэр."

        elif ext == ".xlsx":
            try:
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                for row_text in content.split("\n"):
                    ws.append(row_text.split(","))
                wb.save(str(p))
                return f"Таблица Excel «{p.name}» создана, сэр."
            except ImportError:
                p = p.with_suffix(".csv")
                p.write_text(content, encoding="utf-8")
                return f"openpyxl не установлен — сохранил как «{p.name}» (csv), сэр."

        else:
            p.write_text(content, encoding="utf-8")
            return f"Файл «{p.name}» создан по пути {p.parent}, сэр."

    except PermissionError:
        return f"Нет прав на запись в «{p.parent}», сэр."
    except Exception as e:
        return f"Ошибка при создании файла «{path}»: {e}"


def list_directory(path: str = "") -> str:
    """
    Показывает содержимое директории.
    Если path не указан — показывает домашнюю папку.
    """
    if not path or path.strip() in ("", ".", "~"):
        p = Path.home()
    else:
        p = Path(path.strip('"\''))

    if not p.exists():
        return f"Директория не найдена: {p}, сэр."
    if not p.is_dir():
        return f"«{p}» — это файл, не папка, сэр."

    try:
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        dirs  = [i for i in items if i.is_dir()]
        files = [i for i in items if i.is_file()]

        lines = [f"Содержимое «{p}» ({len(dirs)} папок, {len(files)} файлов):"]
        for d in dirs[:30]:
            lines.append(f"  [папка]  {d.name}/")
        for f in files[:50]:
            size = f.stat().st_size
            sz = f"{size/1024:.0f} КБ" if size > 1024 else f"{size} Б"
            lines.append(f"  [файл]   {f.name}  ({sz})")
        if len(dirs) > 30 or len(files) > 50:
            lines.append(f"  ... и ещё {max(0,len(dirs)-30)} папок, {max(0,len(files)-50)} файлов")
        return "\n".join(lines)
    except PermissionError:
        return f"Нет доступа к «{p}», сэр."
    except Exception as e:
        return f"Ошибка при чтении директории: {e}"


def run_powershell(command: str) -> str:
    """
    Выполняет команду PowerShell и возвращает результат.
    Безопасность определяется через систему уровней (core/safety.py):
      SAFE      — выполняется сразу
      CONFIRM   — показывается команда и ждёт подтверждения
      FORBIDDEN — отклоняется с объяснением
    """
    level, reason = classify_powershell(command)

    if level == SafetyLevel.FORBIDDEN:
        log.warning(f"[PS] FORBIDDEN: {command[:80]}")
        return f"Отказано: {reason}, сэр."

    if level == SafetyLevel.CONFIRM:
        desc = f"выполнить PowerShell-команду"
        details = f"`{command[:200]}`"
        if not request_confirmation(desc, details):
            return "Команда отменена, сэр."

    log.info(f"[PS] Выполняю [{level.value}]: {command[:80]}")

    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace",
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            return "Команда выполнена, вывода нет, сэр."
        return output[:3000]
    except subprocess.TimeoutExpired:
        return "Команда выполнялась слишком долго (>30с), принудительно остановлена, сэр."
    except Exception as e:
        return f"Ошибка выполнения команды: {e}"


def open_app(name: str) -> str:
    """
    Открывает приложение по имени. Ищет в базе известных приложений,
    затем на всём ПК (Start Menu, реестр, Program Files).
    """
    from core.local_handler import _try_open
    result = _try_open(name.lower(), name)
    return result or f"Не удалось найти и открыть «{name}», сэр."


def open_url(url: str) -> str:
    """Открывает URL или сайт в браузере по умолчанию."""
    import webbrowser
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"Открываю {url} в браузере, сэр."
    except Exception as e:
        return f"Ошибка: {e}"
