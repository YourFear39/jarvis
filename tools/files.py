"""
Инструмент чтения файлов с компьютера пользователя.
Поддерживает: txt, md, pdf, docx, и файлы с кодом.
"""

from pathlib import Path

import config
from core.safety import SafetyLevel, classify_file_read


def read_file(path: str) -> str:
    """
    Читает содержимое файла.

    :param path: путь к файлу (абсолютный или относительный)
    :return: содержимое файла или сообщение об ошибке
    """
    file_path = Path(path).expanduser().resolve()

    # Защита от чтения критичных системных файлов
    level, reason = classify_file_read(str(file_path))
    if level == SafetyLevel.FORBIDDEN:
        return f"Отказано: {reason}, сэр."

    if not file_path.exists():
        return f"Файл не найден: {path}"

    if not file_path.is_file():
        return f"Это не файл: {path}"

    suffix = file_path.suffix.lower()

    try:
        if suffix == ".pdf":
            return _read_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            return _read_docx(file_path)
        else:
            return _read_text(file_path)

    except Exception as e:
        return f"Ошибка при чтении файла '{path}': {str(e)}"


def _read_text(path: Path) -> str:
    """Читает текстовый файл (txt, md, py, js, и т.д.)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1251")  # Кириллица в Windows

    if len(text) > config.FILE_MAX_CHARS:
        text = text[:config.FILE_MAX_CHARS]
        return f"[Файл обрезан до {config.FILE_MAX_CHARS} символов]\n\n{text}"

    return f"Содержимое файла '{path.name}':\n\n{text}"


def _read_pdf(path: Path) -> str:
    """Читает PDF файл."""
    try:
        import PyPDF2
    except ImportError:
        return "Ошибка: для чтения PDF нужна библиотека PyPDF2. Запусти: pip install PyPDF2"

    text_parts = []
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                text_parts.append(f"[Страница {i+1}]\n{text}")

    full_text = "\n\n".join(text_parts)

    if len(full_text) > config.FILE_MAX_CHARS:
        full_text = full_text[:config.FILE_MAX_CHARS]
        return f"[PDF обрезан до {config.FILE_MAX_CHARS} символов]\n\n{full_text}"

    return f"Содержимое PDF '{path.name}':\n\n{full_text}"


def _read_docx(path: Path) -> str:
    """Читает Word документ."""
    try:
        from docx import Document
    except ImportError:
        return "Ошибка: для чтения DOCX нужна библиотека python-docx. Запусти: pip install python-docx"

    doc = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)

    if len(full_text) > config.FILE_MAX_CHARS:
        full_text = full_text[:config.FILE_MAX_CHARS]
        return f"[Документ обрезан до {config.FILE_MAX_CHARS} символов]\n\n{full_text}"

    return f"Содержимое документа '{path.name}':\n\n{full_text}"
