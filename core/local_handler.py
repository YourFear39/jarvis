"""
Локальный обработчик простых команд.
Выполняет их напрямую — без обращения к LLM и без квоты.

Обрабатывает:
  - Открытие приложений  ("открой discord", "запусти блокнот")
  - Открытие файлов      ("открой файл C:\\notes.txt")
  - Открытие сайтов      ("открой сайт youtube.com")
  - Создание файлов/папок("создай файл test.txt", "создай папку Проекты")
  - Удаление файлов/папок("удали файл test.txt")
  - Время и дата         ("который час", "какой сегодня день")
"""

import os
import re
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Словарь приложений: что говорит пользователь → команда для запуска
# ---------------------------------------------------------------------------
APPS: dict[str, str] = {
    # Браузеры
    "chrome":            "chrome",
    "хром":              "chrome",
    "google chrome":     "chrome",
    "firefox":           "firefox",
    "фаерфокс":          "firefox",
    "mozilla":           "firefox",
    "opera":             "opera",
    "brave":             "brave",
    "браузер":           "chrome",
    "browser":           "chrome",
    # Мессенджеры
    "discord":           "discord",
    "дискорд":           "discord",
    "telegram":          "telegram",
    "телеграм":          "telegram",
    "whatsapp":          "whatsapp",
    "вотсап":            "whatsapp",
    # Системные утилиты
    "блокнот":           "notepad",
    "notepad":           "notepad",
    "калькулятор":       "calc",
    "calculator":        "calc",
    "проводник":         "explorer",
    "explorer":          "explorer",
    "paint":             "mspaint",
    "паинт":             "mspaint",
    "cmd":               "cmd",
    "командная строка":  "cmd",
    "terminal":          "cmd",
    "терминал":          "cmd",
    "powershell":        "powershell",
    "диспетчер задач":   "taskmgr",
    "task manager":      "taskmgr",
    "реестр":            "regedit",
    "registry":          "regedit",
    # Office
    "word":              "winword",
    "excel":             "excel",
    "powerpoint":        "powerpnt",
    "outlook":           "outlook",
    # Разработка
    "vscode":            "code",
    "vs code":           "code",
    "code":              "code",
    "визуал студио":     "code",
    "visual studio code":"code",
    # Игры / медиа
    "steam":             "steam",
    "стим":              "steam",
    "spotify":           "spotify",
    "спотифай":          "spotify",
    "vlc":               "vlc",
    "obs":               "obs64",
    # Прочее
    "settings":          "ms-settings:",
    "настройки":         "ms-settings:",
    "snipping tool":     "snippingtool",
    "ножницы":           "snippingtool",
}

# Слова-вежливости перед командой ("пожалуйста открой", "можешь запустить")
_POLITE = r'(?:(?:пожалуйста|please|можешь|можно|could you|can you)\s+)?'

# Триггерные глаголы для каждого вида действий
_RE_OPEN   = re.compile(
    _POLITE + r'(открой|открыть|запусти|запустить|launch|start|open|run)\s+', re.I
)
_RE_CREATE = re.compile(_POLITE + r'(создай|создать|create|сделай|сделать|new)\s+', re.I)
_RE_DELETE = re.compile(
    _POLITE + r'(удали|удалить|delete|remove|убери|убрать|стёрти|стереть)\s+', re.I
)

# Поиск глагола внутри фразы — для "стим открой", "можешь открыть стим?"
_RE_OPEN_INNER = re.compile(
    r'\b(открой|открыть|запусти|запустить|launch|start|open|run)\s+(\S[\s\S]*?)[\?\.\!]?\s*$',
    re.I,
)

# Слова-указатели типа объекта
_RE_FILE_KW   = re.compile(r'^(файл|file)\s+', re.I)
_RE_FOLDER_KW = re.compile(r'^(папку?|folder|директорию|directory)\s+', re.I)
_RE_SITE_KW   = re.compile(r'^(сайт|site|url|ссылку?)\s+', re.I)
_RE_ADD_APP   = re.compile(
    r'^(?:добавь|add|зарегистрируй|запомни)\s+(?:приложение|app)\s+(\S+)\s+(.+)$', re.I
)
_RE_DEL_APP   = re.compile(
    r'^(?:удали|забудь|remove|delete)\s+(?:приложение|app)\s+(\S+)$', re.I
)

# ---------------------------------------------------------------------------
# Состояние — ожидание пути для неизвестного приложения
# (сбрасывается после первого же следующего сообщения)
# ---------------------------------------------------------------------------
_pending_app: str | None = None   # имя приложения, путь к которому мы ждём


def handle_local(message: str) -> str | None:
    """
    Пытается выполнить команду локально.
    Возвращает ответ-строку если справился, None если нужен LLM.
    """
    global _pending_app

    msg = message.strip()
    low = msg.lower()

    # --- Ожидаем путь к приложению (следствие предыдущего "не нашёл") ---
    if _pending_app is not None:
        name = _pending_app
        _pending_app = None                     # сбрасываем в любом случае

        path = msg.strip("'\"")
        if _looks_like_path(path) or path.lower().endswith(".exe"):
            return _register_and_launch(name, path)
        # Пользователь сказал что-то другое — продолжаем обычную обработку

    # --- Явно добавить приложение: "добавь приложение rust C:\path\to\rustdesk.exe" ---
    m = _RE_ADD_APP.match(low)
    if m:
        app_name = m.group(1)
        # берём путь из оригинального (с правильным регистром) сообщения
        orig = _RE_ADD_APP.match(msg)
        path = orig.group(2).strip().strip("'\"") if orig else m.group(2)
        return _register_and_launch(app_name, path)

    # --- Удалить пользовательское приложение: "удали приложение rust" ---
    m = _RE_DEL_APP.match(low)
    if m:
        return _unregister_app(m.group(1))

    # --- Список своих приложений: "мои приложения" ---
    if _any(low, ["мои приложения", "добавленные приложения", "my apps", "список приложений"]):
        return _list_custom_apps()

    # --- Возможности / помощь ---
    if _any(low, [
        "что ты умеешь", "что умеешь", "что можешь", "твои возможности",
        "список команд", "какие команды", "помощь", "help", "what can you do",
        "покажи команды", "как тебя использовать",
    ]):
        return _capabilities()

    # --- Время и дата ---
    if _any(low, ["который час", "сколько времени", "what time", "который сейчас час"]):
        now = datetime.now()
        return f"Сейчас {now.strftime('%H:%M')}, сэр."

    if _any(low, ["какой сегодня", "какое сегодня", "какой день", "какое число", "what date", "today"]):
        now = datetime.now()
        return f"Сегодня {_weekday(now)}, {now.strftime('%d.%m.%Y')}, сэр."

    # --- Открыть / запустить ---
    if _RE_OPEN.match(low):
        rest_low = _clean_rest(_RE_OPEN.sub("", low, count=1))
        rest_orig = _clean_rest(_RE_OPEN.sub("", msg, count=1))
        result = _try_open(rest_low, rest_orig)
        if result is not None:
            return result

    # --- Fallback: глагол НЕ в начале ("стим открой", "можешь открыть стим?") ---
    m_inner = _RE_OPEN_INNER.search(low)
    if m_inner:
        rest_low = _clean_rest(m_inner.group(2))
        m_orig = _RE_OPEN_INNER.search(msg)
        rest_orig = _clean_rest(m_orig.group(2) if m_orig else rest_low)
        result = _try_open(rest_low, rest_orig)
        if result is not None:
            return result

    # --- Создать ---
    if _RE_CREATE.match(low):
        rest_low = _RE_CREATE.sub("", low).strip()
        rest_orig = _RE_CREATE.sub("", msg).strip()

        if _RE_FILE_KW.match(rest_low):
            name = _RE_FILE_KW.sub("", rest_orig).strip().strip("'\"")
            return _create_file(name) if name else None

        if _RE_FOLDER_KW.match(rest_low):
            name = _RE_FOLDER_KW.sub("", rest_orig).strip().strip("'\"")
            return _create_folder(name) if name else None

        return None

    # --- Удалить ---
    if _RE_DELETE.match(low):
        rest_low = _RE_DELETE.sub("", low).strip()
        rest_orig = _RE_DELETE.sub("", msg).strip()

        if _RE_FILE_KW.match(rest_low):
            name = _RE_FILE_KW.sub("", rest_orig).strip().strip("'\"")
            return _delete_file(name) if name else None

        if _RE_FOLDER_KW.match(rest_low):
            name = _RE_FOLDER_KW.sub("", rest_orig).strip().strip("'\"")
            return _delete_folder(name) if name else None

        return None

    return None


# ---------------------------------------------------------------------------
# Запуск приложений
# ---------------------------------------------------------------------------

def _try_open(rest_low: str, rest_orig: str) -> str | None:
    """
    Пробует открыть цель (приложение / файл / сайт) по очищенному фрагменту.
    Возвращает ответ-строку или None если цель не распознана.
    """
    global _pending_app

    # Явно указан тип: "открой файл X"
    if _RE_FILE_KW.match(rest_low):
        path = _RE_FILE_KW.sub("", rest_orig, count=1).strip().strip("'\"")
        return _open_file(path)

    # Явно указан тип: "открой сайт X"
    if _RE_SITE_KW.match(rest_low) or _looks_like_url(rest_low):
        url = _extract_url(rest_orig) or rest_orig
        return _open_url(url)

    # Известное встроенное приложение?
    app_cmd = _match_app(rest_low)
    if app_cmd:
        return _launch_app(app_cmd, rest_low)

    # Пользовательское приложение из базы?
    custom_path = _get_custom_app(rest_low)
    if custom_path:
        return _launch_app(custom_path, rest_low)

    # Выглядит как путь к файлу?
    if _looks_like_path(rest_orig):
        return _open_file(rest_orig)

    # Приложение не найдено — спрашиваем путь
    _pending_app = rest_low
    return (
        f"Не нашёл приложение «{rest_low}», сэр.\n"
        f"Укажи путь к exe-файлу — запомню и открою."
    )


def _match_app(name: str) -> str | None:
    """Ищет команду запуска по имени (точное + частичное совпадение)."""
    name = name.lower().strip()
    if name in APPS:
        return APPS[name]
    for key, cmd in APPS.items():
        if key in name or name in key:
            return cmd
    return None


def _launch_app(cmd: str, label: str = "") -> str:
    """Запускает приложение через start — не блокирует, полностью отделяется."""
    display = label or cmd
    try:
        # "start" — встроенная команда Windows, запускает процесс отдельно
        subprocess.Popen(
            f'start "" {cmd}',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Запускаю {display}, сэр."
    except Exception as e:
        return f"Не удалось запустить {display}: {e}"


# ---------------------------------------------------------------------------
# Файлы
# ---------------------------------------------------------------------------

def _open_file(path: str) -> str:
    p = Path(path.strip("'\""))
    if not p.exists():
        return f"Файл не найден: {p}, сэр."
    try:
        os.startfile(str(p.resolve()))
        return f"Открываю {p.name}, сэр."
    except Exception as e:
        return f"Не удалось открыть {p.name}: {e}"


def _create_file(name: str) -> str:
    p = Path(name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch(exist_ok=True)
        return f"Файл «{p}» создан, сэр."
    except Exception as e:
        return f"Не удалось создать файл «{name}»: {e}"


def _create_folder(name: str) -> str:
    p = Path(name)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return f"Папка «{p}» создана, сэр."
    except Exception as e:
        return f"Не удалось создать папку «{name}»: {e}"


def _delete_file(name: str) -> str:
    p = Path(name.strip("'\""))
    if not p.exists():
        return f"Файл не найден: {p}, сэр."
    # Защита от удаления критических путей
    if _is_critical_path(p):
        return f"Отказываю: «{p}» — системный путь, сэр."
    try:
        p.unlink()
        return f"Файл «{p.name}» удалён, сэр."
    except Exception as e:
        return f"Не удалось удалить «{p.name}»: {e}"


def _delete_folder(name: str) -> str:
    p = Path(name.strip("'\""))
    if not p.exists():
        return f"Папка не найдена: {p}, сэр."
    if _is_critical_path(p):
        return f"Отказываю: «{p}» — системный путь, сэр."
    try:
        shutil.rmtree(str(p))
        return f"Папка «{p.name}» удалена, сэр."
    except Exception as e:
        return f"Не удалось удалить папку «{p.name}»: {e}"


def _is_critical_path(p: Path) -> bool:
    """Блокирует удаление системных директорий."""
    critical = {
        "windows", "program files", "program files (x86)",
        "system32", "syswow64", "users",
    }
    try:
        parts = {part.lower() for part in p.resolve().parts}
        return bool(parts & critical)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Сайты
# ---------------------------------------------------------------------------

def _open_url(url: str) -> str:
    if not re.match(r'^https?://', url, re.I):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"Открываю {url} в браузере, сэр."
    except Exception as e:
        return f"Не удалось открыть {url}: {e}"


def _extract_url(text: str) -> str | None:
    m = re.search(r'https?://\S+', text)
    if m:
        return m.group(0)
    m = re.search(r'www\.\S+', text, re.I)
    if m:
        return m.group(0)
    m = re.search(r'\b[\w-]+\.(com|ru|org|net|io|dev|рф|gg|tv)\b', text, re.I)
    if m:
        return m.group(0)
    m = re.search(r'(?:сайт|site|url|ссылку?)\s+(\S+)', text, re.I)
    if m:
        return m.group(1)
    return None


def _looks_like_path(text: str) -> bool:
    return (
        bool(re.search(r'[A-Za-z]:\\', text)) or
        text.startswith(("./", "../", "/")) or
        bool(re.search(r'\.[a-zA-Z]{2,5}$', text.split()[-1] if text.split() else ""))
    )


def _looks_like_url(text: str) -> bool:
    return bool(re.search(
        r'(https?://|www\.|\.com|\.ru|\.org|\.net|\.io|\.dev|\.gg)',
        text, re.I,
    ))


# ---------------------------------------------------------------------------
# Возможности
# ---------------------------------------------------------------------------

def _capabilities() -> str:
    apps = ", ".join(sorted({
        "discord", "telegram", "chrome", "firefox", "opera",
        "steam", "spotify", "vlc", "obs",
        "блокнот", "калькулятор", "проводник", "paint",
        "cmd", "powershell", "word", "excel", "vscode",
    }))
    return (
        "Вот что я умею, сэр:\n\n"

        "── МГНОВЕННО (без ИИ) ──────────────────────────\n"
        "  Приложения\n"
        "    открой discord / telegram / steam / chrome\n"
        "    запусти блокнот / калькулятор / проводник\n"
        "    открой vscode / word / excel / obs / vlc\n"
        f"    Все: {apps}\n\n"
        "  Файлы и папки\n"
        "    открой файл C:\\путь\\к\\файлу.txt\n"
        "    создай файл notes.txt\n"
        "    создай папку Проекты\n"
        "    удали файл notes.txt\n"
        "    удали папку Старое\n\n"
        "  Браузер\n"
        "    открой сайт youtube.com\n"
        "    открой https://github.com\n\n"
        "  Время и дата\n"
        "    который час  /  какой сегодня день\n\n"

        "── ЧЕРЕЗ ИИ (требует интернет) ─────────────────\n"
        "  Поиск        найди [что угодно] в интернете\n"
        "  Заметки      запомни / запиши / покажи заметки\n"
        "  Задачи       добавь задачу / покажи задачи\n"
        "  Планы        составь план / покажи планы\n"
        "  Файлы        прочитай файл [путь]\n"
        "  Разговор     любой вопрос, объяснение, помощь\n\n"

        "── КОМАНДЫ ─────────────────────────────────────\n"
        "  /memory   — статистика долговременной памяти\n"
        "  /clear    — очистить экран чата\n"
        "  /exit     — выключить Джарвис\n"
        "  🎤        — голосовой ввод (кнопка в интерфейсе)"
    )


# ---------------------------------------------------------------------------
# Пользовательские приложения (SQLite)
# ---------------------------------------------------------------------------

def _db_conn():
    import sqlite3
    import config
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_apps (
            name     TEXT PRIMARY KEY,
            path     TEXT NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


def _get_custom_app(name: str) -> str | None:
    """Ищет приложение по имени (нечёткое совпадение)."""
    try:
        name_low = name.lower().strip()
        with _db_conn() as conn:
            rows = conn.execute("SELECT name, path FROM custom_apps").fetchall()
        for row_name, path in rows:
            if row_name == name_low or row_name in name_low or name_low in row_name:
                return path
    except Exception:
        pass
    return None


def _save_custom_app(name: str, path: str) -> None:
    try:
        with _db_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO custom_apps (name, path) VALUES (?, ?)",
                (name.lower().strip(), path),
            )
    except Exception as e:
        print(f"[AppStore] save error: {e}")


def _unregister_app(name: str) -> str:
    try:
        with _db_conn() as conn:
            n = conn.execute(
                "DELETE FROM custom_apps WHERE name = ?", (name.lower().strip(),)
            ).rowcount
        return (
            f"Приложение «{name}» удалено из базы, сэр."
            if n else
            f"Приложение «{name}» не найдено в базе, сэр."
        )
    except Exception as e:
        return f"Ошибка: {e}"


def _list_custom_apps() -> str:
    try:
        with _db_conn() as conn:
            rows = conn.execute(
                "SELECT name, path FROM custom_apps ORDER BY name"
            ).fetchall()
        if not rows:
            return "Добавленных приложений пока нет, сэр."
        lines = ["Мои приложения, сэр:\n"]
        for name, path in rows:
            lines.append(f"  {name}  →  {path}")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка: {e}"


def _register_and_launch(name: str, path: str) -> str:
    """Сохраняет путь к приложению в базу и запускает его."""
    p = Path(path.strip("'\""))
    if not p.exists():
        return (
            f"Файл не найден: {p}, сэр.\n"
            f"Проверь путь и попробуй снова: добавь приложение {name} <правильный путь>"
        )
    _save_custom_app(name, str(p))
    result = _launch_app(f'"{p}"', name)
    return f"Запомнил «{name}», сэр. {result}"


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _clean_rest(text: str) -> str:
    """Убирает пунктуацию и хвостовые вежливые слова из хвоста команды."""
    text = text.strip().rstrip("?!., ")
    text = re.sub(r'\s+(?:пожалуйста|please|thanks|спасибо)$', '', text, flags=re.I)
    return text.strip()


def _any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _weekday(dt: datetime) -> str:
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return days[dt.weekday()]
