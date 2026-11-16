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
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import config
from core.logger import get_logger

log = get_logger("local")


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
_RE_NOTE_KW   = re.compile(r'(заметк[уаи]?|note)\b\s*', re.I)
_RE_TASK_KW   = re.compile(r'(задач[уаеию]?|task)\b\s*', re.I)
_RE_ID_PREFIX = re.compile(r'^(?:номер|number|id|#|№|с\s+названием|под\s+названием)\s*', re.I)

# Порядковые числительные → позиция в списке (отрицательные = с конца)
_ORDINALS: dict[str, int] = {
    "первую": 1, "первой": 1, "первый": 1, "первое": 1, "первого": 1,
    "вторую": 2, "второй": 2, "второй": 2, "второе": 2, "второго": 2,
    "третью": 3, "третьей": 3, "третий": 3, "третье": 3, "третьего": 3,
    "четвёртую": 4, "четвертую": 4, "четвёртой": 4, "четвертой": 4,
    "пятую": 5, "пятой": 5, "пятого": 5,
    "последнюю": -1, "последней": -1, "последний": -1, "последнее": -1,
}
_RE_ADD_APP   = re.compile(
    r'^(?:добавь|add|зарегистрируй|запомни)\s+(?:приложение|app)\s+(\S+)\s+(.+)$', re.I
)
_RE_DEL_APP   = re.compile(
    r'^(?:удали|забудь|remove|delete)\s+(?:приложение|app)\s+(\S+)$', re.I
)

# Системные команды
_RE_CLOSE     = re.compile(
    _POLITE + r'(закрой|закрыть|завершить|завершь|close|kill|выключи|stop)\s+', re.I
)
_RE_VOL_UP    = re.compile(r'\b(громче|прибавь\s+громкость|увеличь\s+громкость|volume\s+up)\b', re.I)
_RE_VOL_DOWN  = re.compile(r'\b(тише|убавь\s+громкость|уменьши\s+громкость|volume\s+down)\b', re.I)
_RE_VOL_MUTE  = re.compile(
    r'\b(выключи\s+звук|включи\s+звук|mute|unmute|заглуши|без\s+звука|отключи\s+звук)\b', re.I
)
_RE_SCREENSHOT = re.compile(r'\b(скриншот|screenshot|снимок\s+экрана|сделай\s+снимок)\b', re.I)
_RE_LOCK      = re.compile(
    r'\b(заблокируй\s+(?:компьютер|экран|пк|pc)|lock\s+(?:screen|pc|computer))\b', re.I
)
_RE_SYSINFO   = re.compile(
    r'\b(системная\s+информация|sysinfo|system\s+info|сколько\s+памяти|инфо\s+о\s+системе)\b', re.I
)

# Сценарии
_RE_GAME_MODE = re.compile(
    r'\b(игровой\s+режим|game\s+mode|запускай\s+игровой|включи\s+игровой|запусти\s+игровой'
    r'|gaming\s+mode|game\s+on)\b', re.I
)
_RE_GAME_CONFIRM = re.compile(
    r'\b(подтверди?(?:ть)?\s+игровой|да\s+запускай|confirm\s+game|подтверждаю|запускай\s+всё)\b', re.I
)

# Смена пути: "поменяй путь discord [на C:\path]"
_RE_UPDATE_PATH = re.compile(
    r'^(?:поменяй|измени|обнови|смени|исправь|update|change)\s+(?:путь|path)\s+(\S+)'
    r'(?:\s+(?:на|to|=)\s*(.+))?$',
    re.I,
)

# Перезапуск приложения
_RE_RESTART = re.compile(
    _POLITE + r'(перезапусти|перезапустить|restart|relaunch)\s+', re.I
)

# Разделитель "имя файла | его содержимое" в пользовательском запросе
_RE_CONTENT_SEP = re.compile(
    r'\s+(?:с\s+(?:содержимым|текстом|кодом|данными|содержанием|контентом)'
    r'|содержащий|containing|with\s+(?:content|text|code))\s+',
    re.I,
)

# "создай test.bat который/для/что запускает X и Y"
_RE_BAT_ACTION = re.compile(
    r'(\S+\.bat)\s+(?:который|что|для|that|to|which)\s+'
    r'(?:открыва|запуска|запустит|открывает|запускает|запустить|открыть|launch|start|open|run|execute)\w*\s+(.+)',
    re.I,
)

_KNOWN_EXTENSIONS = {
    "txt", "bat", "cmd", "ps1", "py", "html", "htm", "css", "js",
    "json", "xml", "csv", "reg", "ini", "cfg", "sh", "log", "md",
    "docx", "xlsx",
}

# Быстрые папки-ярлыки
_FOLDER_SHORTCUTS: dict[str, Path] = {
    "рабочий стол":  Path.home() / "Desktop",
    "desktop":       Path.home() / "Desktop",
    "загрузки":      Path.home() / "Downloads",
    "downloads":     Path.home() / "Downloads",
    "документы":     Path.home() / "Documents",
    "documents":     Path.home() / "Documents",
    "фото":          Path.home() / "Pictures",
    "pictures":      Path.home() / "Pictures",
    "музыка":        Path.home() / "Music",
    "музыку":        Path.home() / "Music",
    "music":         Path.home() / "Music",
    "видео":         Path.home() / "Videos",
    "videos":        Path.home() / "Videos",
    "программы":     Path("C:/Program Files"),
    "program files": Path("C:/Program Files"),
}

# Питание
_RE_SHUTDOWN = re.compile(
    r'\b(выключи\s+(?:компьютер|пк|pc|windows)|shutdown|завершить\s+работу|выключить\s+пк)\b', re.I
)
_RE_REBOOT = re.compile(
    r'\b(перезагрузи(?:\s+(?:компьютер|пк|pc))?|перезагрузить\s+(?:компьютер|пк)?'
    r'|reboot|restart\s+(?:computer|pc|windows))\b', re.I
)
_RE_SLEEP = re.compile(
    r'\b(режим\s+сна|спящий\s+режим|усыпи(?:\s+(?:компьютер|пк))?'
    r'|sleep\s+(?:mode|computer|pc)?|hibernate)\b', re.I
)
_RE_ABORT_SHUTDOWN = re.compile(
    r'\b(отмен[аи]\s+(?:выключения?|перезагрузки?)|abort\s+shutdown|не\s+выключай)\b', re.I
)

# Процессы
_RE_PROCS = re.compile(
    r'\b(запущенные\s+(?:программы|приложения|процессы)|что\s+(?:сейчас\s+)?запущено'
    r'|running\s+(?:apps?|processes?)|покажи\s+(?:процессы|приложения|программы))\b', re.I
)

# Буфер обмена
_RE_CLIP_GET = re.compile(
    r'\b(что\s+в\s+буфере(?:\s+обмена)?|прочитай\s+буфер|clipboard|буфер\s+обмена)\b', re.I
)
_RE_CLIP_SET = re.compile(
    r'(?:скопируй|скопировать|помести|copy)\s+(?:в\s+буфер(?:\s+обмена)?\s+)?'
    r'(?:текст\s+|слово\s+)?["\']?(.+?)["\']?\s*(?:в\s+буфер(?:\s+обмена)?)?$',
    re.I,
)

# Переименовать файл
_RE_RENAME = re.compile(
    r'(?:переименуй|переименовать|rename)\s+(?:файл\s+)?(.+?)\s+(?:в|to|→|как)\s+(\S+)\s*$',
    re.I,
)

# Найти файл на компьютере
_RE_FIND_FILE = re.compile(
    r'(?:найди|найти|поищи|find)\s+(?:файл\s+|файлы\s+)?(.+?)(?:\s+на\s+(?:компьютере|пк|диске))?\s*$',
    re.I,
)
# Расширение файла в query (config.json, notes.txt — но не "заметку.")
_RE_FILE_EXT = re.compile(r'\.\w{1,5}(?:\s|$)')
# Заметки / задачи (локальные операции без LLM)
_RE_SHOW_NOTES = re.compile(
    r'\b(?:покажи|посмотри|выведи|show|list)\s+(?:мои\s+)?(?:все\s+)?(?:заметки|заметок|notes?)\b'
    r'|\bмои\s+заметки\b|\bсписок\s+заметок\b',
    re.I,
)
_RE_SEARCH_NOTES = re.compile(
    r'\b(?:найди|поищи|search)\b[^.]*\bзаметк[аиу]?\b'
    r'|\bзаметк[аиу]?\s+(?:про|о|об|с|по|где)\b',
    re.I,
)
_RE_ADD_NOTE = re.compile(
    r'\b(?:запомни|запомнить|добавь\s+заметку|сохрани\s+заметку|add\s+note)\b',
    re.I,
)
_RE_SHOW_TASKS = re.compile(
    r'\b(?:покажи|посмотри|выведи|show|list)\s+(?:мои\s+)?(?:все\s+)?(?:задачи|задач|tasks?|todo)\b'
    r'|\bмои\s+задачи\b|\bсписок\s+задач\b|\bчто\s+(?:нужно|надо)\s+сделать\b',
    re.I,
)
_RE_ADD_TASK = re.compile(
    r'\b(?:добавь|создай|add)\s+задачу?\b|\bновая\s+задача\b',
    re.I,
)
_RE_COMPLETE_TASK_CMD = re.compile(
    r'\b(?:выполни|выполнил|сделал|отметь|завершил|закончил|complete|done)\s+задачу?\b'
    r'|\bзадача\s+(?:выполнена|готова|сделана)\b',
    re.I,
)

# Погодные запросы
_RE_WEATHER = re.compile(
    r'\b(погода|weather|температур[аы]|temperature|'
    r'сколько\s+градусов|какой\s+(?:мороз|холод|жар))\b',
    re.I,
)

# WMO-коды → русское описание
_WMO_RU: dict[int, str] = {
    0: "ясно",
    1: "малооблачно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь",
    51: "лёгкая морось", 53: "морось", 55: "сильная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег",
    77: "снежная крупа",
    80: "ливень", 81: "сильный ливень", 82: "очень сильный ливень",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}

# Маркеры информационного запроса — передавать в AI, не в _find_file
_INFO_SEARCH_MARKERS = {
    "запиши", "в заметку", "в заметки", "в интернете", "в сети",
    "запомни", "и добавь", "погоду", "новости", "курс", "цену",
    "информацию", "расскажи", "объясни",
}

# ---------------------------------------------------------------------------
# Состояние — ожидание пути для неизвестного приложения /
#             ожидание подтверждения сценария
# (сбрасывается после первого же следующего сообщения)
# ---------------------------------------------------------------------------
_pending_app: str | None = None   # имя приложения, путь к которому мы ждём
_pending_op:  str        = "register"  # "register" | "update"
_pending_scenario: str | None = None   # название сценария ожидающего подтверждения
_state_lock = threading.Lock()         # защита глобального состояния для GUI-режима

# Глобальный TTS-callback — устанавливается из app.py / voice_loop
_tts_callback: "callable | None" = None


def set_tts_callback(fn) -> None:
    """Регистрирует функцию озвучки для использования в сценариях."""
    global _tts_callback
    _tts_callback = fn


def handle_local(message: str) -> str | None:
    """
    Пытается выполнить команду локально.
    Возвращает ответ-строку если справился, None если нужен LLM.
    """
    global _pending_app, _pending_op, _pending_scenario

    msg = message.strip()
    low = msg.lower()
    log.debug("handle_local INPUT: %r", msg[:80])

    with _state_lock:
        # --- Подтверждение ожидающего сценария ---
        if _pending_scenario is not None:
            _pending_scenario = None

            if _RE_GAME_CONFIRM.search(low) or low in ("да", "yes", "ok", "ок", "подтверждаю"):
                return _run_game_mode()
            return "Игровой режим отменён, сэр."

        # --- Игровой режим ---
        if _RE_GAME_MODE.search(low):
            if config.GAME_MODE_DRY_RUN:
                from core.scenarios import ScenarioRunner, GAME_MODE_STEPS
                runner = ScenarioRunner()
                preview = runner.dry_run(GAME_MODE_STEPS)
                _pending_scenario = "game_mode"
                return preview
            else:
                return _run_game_mode()

        # --- Ожидаем путь к приложению (следствие "не нашёл" или "поменяй путь") ---
        pending_app_snapshot  = _pending_app
        pending_op_snapshot   = _pending_op
        if _pending_app is not None:
            _pending_app = None
            _pending_op  = "register"

    if pending_app_snapshot is not None:
        name = pending_app_snapshot
        op   = pending_op_snapshot

        path = msg.strip("'\"")
        if _looks_like_path(path) or path.lower().endswith(".exe") or Path(path).is_dir():
            if op == "update":
                return _update_app_path(name, path)
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

    # --- Изменить путь приложения: "поменяй путь discord [на C:\path]" ---
    m = _RE_UPDATE_PATH.match(low)
    if m:
        app_name = m.group(1).strip()
        orig = _RE_UPDATE_PATH.match(msg)
        inline_path = (orig.group(2) or "").strip() if orig else ""
        if inline_path:
            return _update_app_path(app_name, inline_path)
        _pending_app = app_name
        _pending_op  = "update"
        return f"Пришли новый путь для «{app_name}», сэр."

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
        log.info("MATCH time: %r", msg[:60])
        now = datetime.now()
        return f"Сейчас {now.strftime('%H:%M')}, сэр."

    if _any(low, ["какой сегодня", "какое сегодня", "какой день", "какое число", "what date", "today"]):
        log.info("MATCH date: %r", msg[:60])
        now = datetime.now()
        return f"Сегодня {_weekday(now)}, {now.strftime('%d.%m.%Y')}, сэр."

    # --- Заметки (локально, без LLM) ---
    if _RE_SHOW_NOTES.search(low):
        log.info("MATCH notes/show: %r", msg[:60])
        from tools.notes import get_notes
        return get_notes()

    if _RE_SEARCH_NOTES.search(low) and not _RE_DELETE.match(low):
        # Извлекаем ключевое слово: "найди заметку про кофе" → "кофе"
        _preps = r'(?:про|о|об|с|по|где|about|containing)\s+'
        kw = re.search(
            r'\bзаметк[аиу]?\s+' + _preps + r'(.+)'
            r'|(?:найди|поищи)\s+(?:в\s+)?заметк[аиу]?\s+' + _preps + r'?(.+)',
            low, re.I,
        )
        keyword = (kw.group(1) or kw.group(2) or "").strip().strip(".,!?;: ") if kw else ""
        log.info("MATCH notes/search: keyword=%r", keyword)
        from tools.notes import get_notes
        return get_notes(search=keyword)

    if _RE_ADD_NOTE.search(low) and not _RE_OPEN.match(low) and not _RE_CREATE.match(low):
        m = _RE_ADD_NOTE.search(low)
        content = msg[m.end():].strip(" :—-.,")
        if content:
            log.info("MATCH notes/add: content=%r", content[:60])
            from tools.notes import add_note
            title = re.split(r'[.!?\n]', content)[0].strip()[:60] or content[:60]
            return add_note(title=title, content=content)
        return None  # нет контента — пусть LLM разберётся

    # --- Задачи (локально, без LLM) ---
    if _RE_SHOW_TASKS.search(low):
        log.info("MATCH tasks/show: %r", msg[:60])
        from tools.notes import get_tasks
        show_all = any(w in low for w in ("выполнен", "completed", "все", "all"))
        return get_tasks(show_completed="true" if show_all else "false")

    if _RE_ADD_TASK.search(low) and not _RE_DELETE.match(low):
        m = _RE_ADD_TASK.search(low)
        title = msg[m.end():].strip(" :—-.,")
        if title:
            log.info("MATCH tasks/add: title=%r", title[:60])
            from tools.notes import add_task
            priority = "high" if any(w in low for w in ("срочно", "срочная", "важно", "важная")) else "medium"
            return add_task(title=title, priority=priority)
        return None

    if _RE_COMPLETE_TASK_CMD.search(low):
        m = _RE_COMPLETE_TASK_CMD.search(low)
        arg = _RE_ID_PREFIX.sub("", low[m.end():]).strip().strip(".,!?;: ")
        log.info("MATCH tasks/complete: arg=%r", arg)
        if arg:
            from tools.notes import complete_task
            return complete_task(arg)
        from tools.notes import get_tasks
        return "Какую задачу отметить выполненной?\n\n" + get_tasks()

    # --- Погода (Open-Meteo, без API-ключа) ---
    # Исключаем команды удаления: "удали заметку погода" не должно триггерить погоду
    if _RE_WEATHER.search(low) and not _RE_DELETE.match(low):
        city = _extract_weather_city(msg)
        log.info("MATCH weather: city=%r", city or "(default)")
        return _weather(city)

    # --- Перезапустить приложение ---
    if _RE_RESTART.match(low):
        rest_low = _clean_rest(_RE_RESTART.sub("", low, count=1))
        if _match_app(rest_low) or _get_custom_app(rest_low):
            return _restart_app(rest_low)

    # --- Закрыть приложение ---
    if _RE_CLOSE.match(low):
        rest_low = _clean_rest(_RE_CLOSE.sub("", low, count=1))
        if _match_app(rest_low) or _get_custom_app(rest_low):
            return _close_app(rest_low)

    # --- Системные команды ---
    if _RE_VOL_MUTE.search(low):
        return _vol_mute()
    if _RE_VOL_UP.search(low):
        return _vol_change(+1)
    if _RE_VOL_DOWN.search(low):
        return _vol_change(-1)
    if _RE_SCREENSHOT.search(low):
        return _screenshot()
    if _RE_LOCK.search(low):
        return _lock_screen()
    if _RE_SYSINFO.search(low):
        return _system_info()

    # --- Питание ---
    if _RE_ABORT_SHUTDOWN.search(low):
        return _abort_shutdown()
    if _RE_SHUTDOWN.search(low):
        return _shutdown_pc()
    if _RE_REBOOT.search(low):
        return _reboot_pc()
    if _RE_SLEEP.search(low):
        return _sleep_pc()

    # --- Запущенные программы ---
    if _RE_PROCS.search(low):
        return _list_processes()

    # --- Буфер обмена ---
    if _RE_CLIP_GET.search(low):
        return _clipboard_get()
    m = _RE_CLIP_SET.match(low)
    if m and not _RE_OPEN.match(low) and not _RE_CREATE.match(low):
        m_orig = _RE_CLIP_SET.match(msg)
        text = (m_orig.group(1) if m_orig else m.group(1)).strip().strip("'\"")
        if text:
            return _clipboard_set(text)

    # --- Открыть / запустить ---
    if _RE_OPEN.match(low):
        rest_low = _clean_rest(_RE_OPEN.sub("", low, count=1))
        rest_orig = _clean_rest(_RE_OPEN.sub("", msg, count=1))
        log.debug("MATCH open: rest=%r", rest_low[:60])
        result = _try_open(rest_low, rest_orig)
        if result is not None:
            log.info("MATCH open → handled: %r", rest_low[:60])
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

        if _RE_FOLDER_KW.match(rest_low):
            name = _RE_FOLDER_KW.sub("", rest_orig).strip().strip("'\"")
            return _create_folder(name) if name else None

        if _RE_FILE_KW.match(rest_low):
            rest_low2 = _RE_FILE_KW.sub("", rest_low).strip()
            rest_orig2 = _RE_FILE_KW.sub("", rest_orig).strip()
            return _create_file_smart(rest_low2, rest_orig2)

        # Прямо имя файла с расширением без слова "файл"
        if _has_known_extension(rest_low):
            return _create_file_smart(rest_low, rest_orig)

        return None

    # --- Удалить ---
    if _RE_DELETE.match(low):
        log.debug("MATCH delete: %r", msg[:60])
        rest_low = _RE_DELETE.sub("", low).strip()
        rest_orig = _RE_DELETE.sub("", msg).strip()

        if _RE_FILE_KW.match(rest_low):
            name = _RE_FILE_KW.sub("", rest_orig).strip().strip("'\"")
            return _delete_file(name) if name else None

        if _RE_FOLDER_KW.match(rest_low):
            name = _RE_FOLDER_KW.sub("", rest_orig).strip().strip("'\"")
            return _delete_folder(name) if name else None

        m_note = _RE_NOTE_KW.search(rest_low)
        if m_note:
            # "удали первую заметку" → before="первую", after=""
            # "удали заметку купить" → before="",       after="купить"
            after_kw  = rest_low[m_note.end():].strip().strip(".,!?;: ")
            before_kw = rest_low[:m_note.start()].strip().strip(".,!?;: ")
            arg = _RE_ID_PREFIX.sub("", after_kw or before_kw).strip().strip(".,!?;: ")

            # Порядковые числительные: "первую" → позиция 1
            pos = _ORDINALS.get(arg.lower())
            if pos is not None:
                return _delete_note_at(pos)

            if not arg:
                from tools.notes import get_notes
                return "Какую заметку удалить? Укажи номер или название:\n\n" + get_notes()
            from tools.notes import delete_note
            return delete_note(arg)

        m_task = _RE_TASK_KW.search(rest_low)
        if m_task:
            after_kw  = rest_low[m_task.end():].strip().strip(".,!?;: ")
            before_kw = rest_low[:m_task.start()].strip().strip(".,!?;: ")
            arg = _RE_ID_PREFIX.sub("", after_kw or before_kw).strip().strip(".,!?;: ")

            pos = _ORDINALS.get(arg.lower())
            if pos is not None:
                return _delete_task_at(pos)

            if not arg:
                return "Укажи номер задачи, сэр. Например: 'удали задачу 2'."
            from tools.notes import delete_task
            return delete_task(arg)

        return None

    # --- Переименовать ---
    m = _RE_RENAME.match(low)
    if m:
        m_orig = _RE_RENAME.match(msg)
        old_name = (m_orig.group(1) if m_orig else m.group(1)).strip().strip("'\"")
        new_name = (m_orig.group(2) if m_orig else m.group(2)).strip().strip("'\"")
        return _rename_file(old_name, new_name)

    # --- Найти файл ---
    m = _RE_FIND_FILE.match(low)
    if m:
        query = m.group(1).strip().strip("'\"")
        query_clean = query.rstrip(".!?,;: ")

        is_info = any(marker in low for marker in _INFO_SEARCH_MARKERS)
        has_file_ext = bool(_RE_FILE_EXT.search(query_clean))
        is_short = len(query_clean.split()) <= 3

        if (has_file_ext or is_short) and not is_info:
            log.info("MATCH find_file: query=%r", query_clean[:60])
            m_orig = _RE_FIND_FILE.match(msg)
            query_orig = (m_orig.group(1) if m_orig else query).strip().strip("'\"").rstrip(".!?,;: ")
            return _find_file(query_orig)

    log.debug("handle_local NO MATCH → forwarding to LLM: %r", msg[:80])
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

    # Составная команда ("открой блокнот и запиши туда текст",
    # "открой discord и telegram") — передаём AI, не обрабатываем локально
    if re.search(r'\s+(?:и|and)\s+', rest_low):
        return None

    # Явно указан тип: "открой файл X"
    if _RE_FILE_KW.match(rest_low):
        path = _RE_FILE_KW.sub("", rest_orig, count=1).strip().strip("'\"")
        return _open_file_smart(path)

    # Явно указан тип: "открой папку X"
    if _RE_FOLDER_KW.match(rest_low):
        name = _RE_FOLDER_KW.sub("", rest_orig, count=1).strip().strip("'\"")
        return _open_folder(name)

    # Папки-ярлыки: "открой загрузки", "открой рабочий стол"
    shortcut = _FOLDER_SHORTCUTS.get(rest_low)
    if shortcut is None:
        for key, path in _FOLDER_SHORTCUTS.items():
            if rest_low == key or rest_low in key or key in rest_low:
                shortcut = path
                break
    if shortcut is not None:
        return _open_folder(str(shortcut))

    # Явно указан тип: "открой сайт X"
    if _RE_SITE_KW.match(rest_low) or _looks_like_url(rest_low):
        url = _extract_url(rest_orig) or rest_orig
        return _open_url(url)

    # Пользовательское приложение из базы — у него всегда полный путь, сразу запускаем
    custom_path = _get_custom_app(rest_low)
    if custom_path:
        proc = Path(custom_path).name
        if _is_running(proc):
            return f"«{rest_low.capitalize()}» уже запущен, сэр."
        return _launch_app(custom_path, rest_low)

    # Известное встроенное приложение — проверяем что реально запустится
    app_cmd = _match_app(rest_low)
    if app_cmd:
        if _is_launchable(app_cmd):
            proc = _get_proc_name(rest_low)
            if proc and _is_running(proc):
                return f"«{rest_low.capitalize()}» уже запущен, сэр."
            return _launch_app(app_cmd, rest_low)
        # Команда есть в словаре, но не найдена в PATH/файловой системе.
        # Сохраняем под каноническим cmd-ключом ("steam" а не "стим"),
        # чтобы любой alias ("стим"/"steam") находил запись в БД.
        _pending_app = app_cmd
        return (
            f"Знаю «{rest_low}», но не могу найти его на компьютере, сэр.\n"
            f"Укажи путь к exe-файлу или папке — запомню и открою."
        )

    # Выглядит как путь к файлу?
    if _looks_like_path(rest_orig):
        return _open_file_smart(rest_orig)

    # Ищем по всему ПК: Start Menu → реестр → Program Files
    log.info("App search on PC: %r", rest_low)
    found = _find_app_on_pc(rest_low)
    if found:
        _save_custom_app(rest_low, found)
        log.info("App found: %r → %s", rest_low, found)
        return f"Нашёл «{rest_low}» на ПК, запомнил. " + _launch_app(found, rest_low)

    log.warning("App not found: %r", rest_low)
    _pending_app = rest_low
    return (
        f"Поискал «{rest_low}» везде — не нашёл, сэр.\n"
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


def _is_launchable(cmd: str) -> bool:
    """Проверяет можно ли реально запустить команду (есть в PATH или абс. путь существует)."""
    import shutil
    if os.path.isabs(cmd):
        return os.path.exists(cmd)
    return shutil.which(cmd) is not None


def _find_app_on_pc(name: str) -> str | None:
    """Searches the entire PC for an app by name. Returns exe path or None."""
    name_low = name.lower().strip()

    # 1. Start Menu .lnk shortcuts
    sm_dirs = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
        Path.home() / "Desktop",
    ]
    for sm_dir in sm_dirs:
        if not sm_dir.exists():
            continue
        for lnk in sm_dir.rglob("*.lnk"):
            if name_low in lnk.stem.lower():
                target = _resolve_lnk(lnk)
                if target and Path(target).exists():
                    return target

    # 2. Windows Registry App Paths
    try:
        import winreg
        for hive, rpath in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        ]:
            try:
                with winreg.OpenKey(hive, rpath) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        sub_name = winreg.EnumKey(key, i)
                        if name_low in sub_name.lower():
                            with winreg.OpenKey(key, sub_name) as sub:
                                try:
                                    val, _ = winreg.QueryValueEx(sub, "")
                                    if val and Path(val).exists():
                                        return val
                                except Exception:
                                    pass
            except Exception:
                pass
    except Exception:
        pass

    # 3. Program Files directory scan (top level only for speed)
    for search_root in [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path(os.environ.get("LOCALAPPDATA", "")),
    ]:
        if not search_root.exists():
            continue
        for sub in search_root.iterdir():
            if not sub.is_dir():
                continue
            if name_low in sub.name.lower():
                exe, _ = _resolve_exe_path(str(sub), app_name=name)
                if exe:
                    return str(exe)

    return None


def _resolve_lnk(lnk_path: Path) -> str | None:
    """Resolves Windows .lnk shortcut to its target path via PowerShell."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}'); $s.TargetPath"],
            capture_output=True, text=True, timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        target = result.stdout.strip()
        if target and Path(target).exists():
            return target
    except Exception:
        pass
    return None


def _resolve_exe_path(raw: str, app_name: str = "") -> tuple[Path | None, str | None]:
    """
    Принимает путь к файлу ИЛИ папке, возвращает (exe_path, error).
    Для папки:
      1. Ищет {папка}/{имя_папки}.exe или {app_name}.exe
      2. Ищет в подпапках (один уровень) — для Discord, Teams и т.п.
      3. Ищет единственный .exe в корне, фильтруя вспомогательные
    """
    _skip = {"uninstall", "update", "crash", "setup", "helper", "service",
             "installer", "unins"}

    p = Path(raw.strip("'\" "))
    if not p.exists():
        return None, f"Путь не найден: {p}"

    if p.is_file():
        return p, None

    if p.is_dir():
        # 1. Прямые кандидаты в корне папки
        candidates = [p / (p.name + ".exe"), p / (p.name.lower() + ".exe")]
        if app_name:
            candidates += [p / (app_name + ".exe"), p / (app_name.lower() + ".exe")]
        for c in candidates:
            if c.exists():
                return c, None

        # 2. Подпапки — Discord хранит app-x.y.z\Discord.exe
        for sub in sorted(p.iterdir(), reverse=True):   # newer versions first
            if not sub.is_dir():
                continue
            sub_candidates = [
                sub / (p.name + ".exe"),
                sub / (p.name.lower() + ".exe"),
            ]
            if app_name:
                sub_candidates += [
                    sub / (app_name + ".exe"),
                    sub / (app_name.lower() + ".exe"),
                ]
            for c in sub_candidates:
                if c.exists():
                    return c, None
            # Единственный не-вспомогательный exe в подпапке
            sub_exes = [e for e in sub.glob("*.exe")
                        if not any(s in e.stem.lower() for s in _skip)]
            if len(sub_exes) == 1:
                return sub_exes[0], None

        # 3. Корень: единственный не-вспомогательный exe
        exes = sorted(p.glob("*.exe"))
        main = [e for e in exes if not any(s in e.stem.lower() for s in _skip)]
        if len(main) == 1:
            return main[0], None
        if len(exes) == 1:
            return exes[0], None
        if main:
            return main[0], None   # берём первый, если несколько

        names = ", ".join(e.name for e in exes[:6])
        return None, (
            f"В папке несколько .exe: {names}.\n"
            f"Укажи точный файл или папку с приложением."
        )

    return None, f"Неизвестный тип пути: {p}"


def _launch_app(cmd: str, label: str = "") -> str:
    """Запускает приложение. cmd — имя команды или абсолютный путь."""
    import shutil
    display = label or Path(cmd).stem if os.path.isabs(cmd) else label or cmd

    # Оборачиваем путь в кавычки если есть пробелы
    launch = f'"{cmd}"' if " " in cmd and not cmd.startswith('"') else cmd
    try:
        subprocess.Popen(
            f'start "" {launch}',
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


def _open_file_smart(path: str) -> str:
    """Открывает файл — ищет на Desktop если путь не абсолютный."""
    p = Path(path.strip("'\""))
    if not p.is_absolute() and not p.exists():
        desktop_candidate = Path.home() / "Desktop" / p.name
        if desktop_candidate.exists():
            p = desktop_candidate
    return _open_file(str(p))


def _open_folder(name_or_path: str) -> str:
    """Открывает папку — поддерживает ярлыки и прямые пути."""
    name_low = name_or_path.lower().strip()

    # Сначала ищем по ярлыкам
    folder = _FOLDER_SHORTCUTS.get(name_low)
    if folder is None:
        for key, path in _FOLDER_SHORTCUTS.items():
            if name_low == key or name_low in key or key in name_low:
                folder = path
                break

    if folder is None:
        folder = Path(name_or_path.strip("'\""))

    if not folder.exists():
        return f"Папка не найдена: {folder}, сэр."
    try:
        os.startfile(str(folder.resolve()))
        label = folder.name or str(folder)
        return f"Открываю {label}, сэр."
    except Exception as e:
        return f"Не удалось открыть папку: {e}"


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
    on_desktop = not p.is_absolute()
    if on_desktop:
        p = Path.home() / "Desktop" / p
    try:
        p.mkdir(parents=True, exist_ok=True)
        suffix = " на рабочем столе" if on_desktop else f" в {p.parent}"
        return f"Папка «{p.name}» создана{suffix}, сэр."
    except Exception as e:
        return f"Не удалось создать папку «{name}»: {e}"


def _has_known_extension(text: str) -> bool:
    first = text.split()[0] if text.split() else ""
    ext = first.rsplit(".", 1)[-1].lower() if "." in first else ""
    return ext in _KNOWN_EXTENSIONS


def _parse_file_name_and_content(rest_low: str, rest_orig: str) -> tuple[str, str | None]:
    """Извлекает имя файла и инлайн-содержимое из фрагмента запроса."""
    parts_orig = _RE_CONTENT_SEP.split(rest_orig, maxsplit=1)
    fname = parts_orig[0].strip().strip("'\"").split()[0]
    content = parts_orig[1].strip() if len(parts_orig) > 1 else None
    return fname, content


def _get_file_template(ext: str, fname: str = "") -> str:
    """Возвращает шаблон содержимого файла по расширению."""
    stem = Path(fname).stem if fname else "script"
    ext = ext.lower()

    if ext in ("bat", "cmd"):
        return f"@echo off\nchcp 65001 >nul\nrem {stem}\n\npause\n"

    if ext == "ps1":
        return f"# {stem}\nSet-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass\n\n"

    if ext == "py":
        return (
            f'"""\n{stem}\n"""\n\n\n'
            "def main():\n    pass\n\n\n"
            'if __name__ == "__main__":\n    main()\n'
        )

    if ext in ("html", "htm"):
        return (
            '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'    <title>{stem}</title>\n'
            '</head>\n<body>\n\n</body>\n</html>\n'
        )

    if ext == "reg":
        return "Windows Registry Editor Version 5.00\n\n"

    if ext == "json":
        return "{}\n"

    if ext == "css":
        return f"/* {stem} */\n\nbody {{\n    margin: 0;\n    padding: 0;\n}}\n"

    if ext == "xml":
        return '<?xml version="1.0" encoding="UTF-8"?>\n<root>\n\n</root>\n'

    return ""


def _create_bat_from_action(fname: str, action_text: str) -> str:
    """Генерирует содержимое .bat-файла который запускает указанные приложения."""
    targets_raw = re.split(r'\s+(?:и|and|,|&|\+)\s+', action_text.strip(), flags=re.I)
    lines = ["@echo off", "chcp 65001 >nul", f"rem {fname}", ""]
    for tgt in targets_raw:
        tgt = tgt.strip().strip("'\"")
        if not tgt:
            continue
        if _looks_like_path(tgt):
            lines.append(f'start "" "{tgt}"')
        else:
            cp = _get_custom_app(tgt.lower())
            if cp:
                lines.append(f'start "" "{cp}"')
            else:
                cmd = _match_app(tgt.lower()) or tgt
                lines.append(f"start {cmd}")
    lines += ["", "pause"]
    return "\n".join(lines)


def _create_file_smart(rest_low: str, rest_orig: str) -> str:
    """Создаёт файл локально: bat-action / инлайн-содержимое / шаблон по расширению."""
    desktop = Path.home() / "Desktop"

    # bat-action: "launch.bat который запускает discord и telegram"
    m_bat = _RE_BAT_ACTION.search(rest_low)
    if m_bat:
        m_orig = _RE_BAT_ACTION.search(rest_orig)
        fname_raw  = (m_orig.group(1) if m_orig else m_bat.group(1))
        action_txt = (m_orig.group(2) if m_orig else m_bat.group(2))
        p = Path(fname_raw)
        if not p.is_absolute():
            p = desktop / p.name
        content = _create_bat_from_action(p.name, action_txt)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Файл «{p.name}» создан, сэр."
        except Exception as e:
            return f"Не удалось создать «{p.name}»: {e}"

    # Парсим имя + опциональное инлайн-содержимое
    fname, inline_content = _parse_file_name_and_content(rest_low, rest_orig)
    if not fname:
        return None

    p = Path(fname)
    if not p.is_absolute():
        p = desktop / p.name

    ext = p.suffix.lstrip(".")
    content = inline_content if inline_content is not None else _get_file_template(ext, p.name)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Файл «{p.name}» создан, сэр."
    except Exception as e:
        return f"Не удалось создать «{p.name}»: {e}"


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
    """Блокирует удаление системных директорий Windows."""
    # Только сами системные директории — не их содержимое.
    # "users" убран из set: C:\Users\Vlad\Desktop\file.txt — пользовательский файл,
    # его удалять можно. Блокируем только C:\Users\ саму по себе.
    sys_dirs = {"windows", "program files", "program files (x86)", "system32", "syswow64"}
    try:
        resolved = p.resolve()
        parts = [part.lower() for part in resolved.parts]
        # Блокируем если цель находится ВНУТРИ системной папки Windows
        for i, part in enumerate(parts):
            if part in sys_dirs:
                return True
        # Блокируем C:\Users саму по себе (но не C:\Users\Vlad\...)
        if len(parts) <= 3 and any(part == "users" for part in parts):
            return True
    except Exception:
        return False
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
    if bool(re.search(r'[A-Za-z]:\\', text)) or text.startswith(("./", "../", "/")):
        return True
    # Only match by extension if text is a single token (not a command sentence)
    words = text.split()
    if len(words) == 1:
        return bool(re.search(r'\.[a-zA-Z]{2,5}$', words[0]))
    return False


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
        "  Быстрые папки\n"
        "    открой загрузки / документы / рабочий стол / фото\n"
        "    открой папку C:\\MyFolder\n\n"
        "  Файлы\n"
        "    открой файл C:\\путь\\к\\файлу.txt\n"
        "    создай файл notes.txt  /  создай index.html\n"
        "    создай launch.bat который запускает discord\n"
        "    удали файл notes.txt  /  удали папку Старое\n"
        "    переименуй notes.txt в ideas.txt\n"
        "    найди файл config.json\n\n"
        "  Системные команды\n"
        "    громче / тише\n"
        "    выключи звук / включи звук\n"
        "    скриншот\n"
        "    заблокируй компьютер\n"
        "    системная информация\n"
        "    запущенные программы\n"
        "    что в буфере обмена\n"
        "    скопируй текст [текст] в буфер\n"
        "    закрой discord / закрой стим / закрой chrome\n"
        "    выключи компьютер / перезагрузи / режим сна\n\n"

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
# Системные команды Windows
# ---------------------------------------------------------------------------

_KEYEVENTF_KEYUP = 0x0002
_VK_VOLUME_MUTE  = 0xAD
_VK_VOLUME_DOWN  = 0xAE
_VK_VOLUME_UP    = 0xAF


def _press_key(vk: int, times: int = 1) -> None:
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _vol_change(direction: int) -> str:
    """direction: +1 = громче, -1 = тише. 3 нажатия ≈ 6% громкости."""
    _press_key(_VK_VOLUME_UP if direction > 0 else _VK_VOLUME_DOWN, times=3)
    return f"Громкость {'увеличена' if direction > 0 else 'уменьшена'}, сэр."


def _vol_mute() -> str:
    _press_key(_VK_VOLUME_MUTE)
    return "Переключил звук, сэр."


def _screenshot() -> str:
    from datetime import datetime as _dt
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    filename = f"screenshot_{_dt.now():%Y%m%d_%H%M%S}.png"
    save_path = desktop / filename
    # Пути с обратными слэшами — заменяем на прямые для PowerShell
    ps_path = str(save_path).replace("\\", "/")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
        f"$b.Save('{ps_path}')"
    )
    try:
        subprocess.run(
            ["powershell", "-Command", ps],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        return f"Ошибка скриншота: {e}"
    if save_path.exists():
        return f"Скриншот сохранён на рабочем столе: {filename}, сэр."
    return "Не удалось сделать скриншот, сэр."


def _is_running(proc_name: str) -> bool:
    """Проверяет запущен ли процесс по имени (через tasklist)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/NH"],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return proc_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _update_app_path(name: str, path: str) -> str:
    """Обновляет путь к сохранённому приложению без его запуска."""
    exe, err = _resolve_exe_path(path, app_name=name)
    if err:
        return f"{err}, сэр.\nПроверь путь и попробуй снова."
    _save_custom_app(name, str(exe))
    return f"Путь к «{name}» обновлён → {exe.name}, сэр."


def _extract_app_name(phrase: str) -> str:
    """
    Извлекает короткое название приложения из фразы.
    "калькулятор на моём компьютере" → "калькулятор"
    Ищет первое слово/словосочетание из APPS или PROCESS_NAME_MAP.
    """
    import config as _cfg
    phrase_low = phrase.lower().strip()
    # Ищем самое длинное совпадающее ключевое слово
    best = ""
    for key in list(APPS.keys()) + list(_cfg.PROCESS_NAME_MAP.keys()):
        if key in phrase_low and len(key) > len(best):
            best = key
    return best if best else phrase_low.split()[0] if phrase_low.split() else phrase_low


def _get_proc_name(app_label: str) -> str | None:
    """Возвращает реальное имя процесса Windows по разговорному названию приложения."""
    import config as _cfg
    name_low = app_label.lower().strip()

    # 1. PROCESS_NAME_MAP — точный маппинг разговорных названий → exe (приоритет)
    if name_low in _cfg.PROCESS_NAME_MAP:
        return _cfg.PROCESS_NAME_MAP[name_low]
    # Частичное совпадение в PROCESS_NAME_MAP (для фраз типа "калькулятор на пк")
    for key, proc in _cfg.PROCESS_NAME_MAP.items():
        if key in name_low:
            return proc

    # 2. Кастомное приложение — берём имя exe из сохранённого пути
    custom_path = _get_custom_app(app_label)
    if custom_path:
        return Path(custom_path).name  # → "Steam.exe"

    # 3. Стандартный маппинг через APPS
    cmd = _match_app(app_label)
    if not cmd or ":" in cmd:          # ms-settings: и URI-протоколы — пропускаем
        return None
    if cmd == "explorer":              # никогда не убиваем проводник
        return None

    return cmd + ".exe"


def _restart_app(app_label: str) -> str:
    """Закрывает приложение и запускает снова."""
    proc = _get_proc_name(app_label)
    if proc and _is_running(proc):
        subprocess.run(
            ["taskkill", "/IM", proc, "/F"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        import time
        time.sleep(0.8)

    # Ищем путь для запуска
    custom_path = _get_custom_app(app_label)
    if custom_path:
        return f"Перезапускаю {app_label}, сэр. " + _launch_app(custom_path, app_label)

    app_cmd = _match_app(app_label)
    if app_cmd and _is_launchable(app_cmd):
        return f"Перезапускаю {app_label}, сэр. " + _launch_app(app_cmd, app_label)

    return f"Не знаю как запустить «{app_label}» после закрытия, сэр."


def _close_app(app_label: str) -> str:
    proc = _get_proc_name(app_label)
    label = _extract_app_name(app_label).capitalize() or app_label.capitalize()
    if not proc:
        return f"Не знаю как закрыть «{label}», сэр."
    # taskkill — работает для обычных и большинства UWP приложений
    try:
        result = subprocess.run(
            ["taskkill", "/IM", proc, "/F"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return f"«{label}» закрыт, сэр."
    except Exception:
        pass
    # PowerShell фолбек — для UWP и процессов которые сопротивляются taskkill
    stem = proc.rsplit(".", 1)[0]  # "CalculatorApp.exe" → "CalculatorApp"
    try:
        ps_result = subprocess.run(
            ["powershell", "-Command",
             f"Stop-Process -Name '{stem}' -Force -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if ps_result.returncode == 0:
            return f"«{label}» закрыт, сэр."
    except Exception:
        pass
    return f"«{label}» не запущен или не удалось закрыть, сэр."


def _lock_screen() -> str:
    try:
        subprocess.Popen(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Компьютер заблокирован, сэр."
    except Exception as e:
        return f"Не удалось заблокировать: {e}"


def _system_info() -> str:
    import ctypes

    class _MEMSTAT(ctypes.Structure):
        _fields_ = [
            ("dwLength",                ctypes.c_ulong),
            ("dwMemoryLoad",            ctypes.c_ulong),
            ("ullTotalPhys",            ctypes.c_ulonglong),
            ("ullAvailPhys",            ctypes.c_ulonglong),
            ("ullTotalPageFile",        ctypes.c_ulonglong),
            ("ullAvailPageFile",        ctypes.c_ulonglong),
            ("ullTotalVirtual",         ctypes.c_ulonglong),
            ("ullAvailVirtual",         ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = _MEMSTAT()
    stat.dwLength = ctypes.sizeof(stat)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))

    total_gb = stat.ullTotalPhys / (1024 ** 3)
    avail_gb = stat.ullAvailPhys / (1024 ** 3)
    used_gb  = total_gb - avail_gb

    try:
        res = subprocess.run(
            ["powershell", "-Command",
             "(Get-CimInstance Win32_Processor).LoadPercentage"],
            capture_output=True, text=True, timeout=6,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        cpu = res.stdout.strip() + "%"
    except Exception:
        cpu = "N/A"

    return (
        f"ОЗУ: {used_gb:.1f} / {total_gb:.1f} ГБ  ({stat.dwMemoryLoad}% загружено)\n"
        f"ЦП: {cpu} загружен, сэр."
    )


# ---------------------------------------------------------------------------
# Питание
# ---------------------------------------------------------------------------

def _shutdown_pc() -> str:
    try:
        subprocess.Popen(
            ["shutdown", "/s", "/t", "10"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Выключаю компьютер через 10 секунд, сэр. Скажите «отмена выключения» чтобы остановить."
    except Exception as e:
        return f"Ошибка выключения: {e}"


def _reboot_pc() -> str:
    try:
        subprocess.Popen(
            ["shutdown", "/r", "/t", "10"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Перезагружаю компьютер через 10 секунд, сэр. Скажите «отмена» чтобы остановить."
    except Exception as e:
        return f"Ошибка перезагрузки: {e}"


def _sleep_pc() -> str:
    try:
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Перевожу в режим сна, сэр."
    except Exception as e:
        return f"Ошибка: {e}"


def _abort_shutdown() -> str:
    try:
        subprocess.run(
            ["shutdown", "/a"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Выключение отменено, сэр."
    except Exception as e:
        return f"Ошибка: {e}"


# ---------------------------------------------------------------------------
# Запущенные программы
# ---------------------------------------------------------------------------

def _list_processes() -> str:
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
             "Sort-Object WorkingSet64 -Descending | Select-Object -First 10 | "
             "ForEach-Object { '{0,-25} {1,5} MB' -f $_.ProcessName, "
             "[math]::Round($_.WorkingSet64/1MB, 0) }"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines = [l.rstrip() for l in (result.stdout or "").strip().splitlines() if l.strip()]
        if not lines:
            return "Нет запущенных программ с окнами, сэр."
        return "Запущенные программы, сэр:\n" + "\n".join(f"  {l}" for l in lines)
    except Exception as e:
        return f"Ошибка: {e}"


# ---------------------------------------------------------------------------
# Буфер обмена
# ---------------------------------------------------------------------------

def _clipboard_get() -> str:
    import base64
    # Read clipboard via base64 to avoid PowerShell output encoding issues with Cyrillic
    script = (
        "$c = Get-Clipboard; "
        "if ($null -ne $c -and $c -ne '') { "
        "  $bytes = [System.Text.Encoding]::UTF8.GetBytes($c); "
        "  [Convert]::ToBase64String($bytes) "
        "} else { '' }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=5,
            encoding="ascii", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        b64 = (result.stdout or "").strip()
        if not b64:
            return "Буфер обмена пуст, сэр."
        text = base64.b64decode(b64).decode("utf-8", errors="replace")
        short = text[:300] + ("..." if len(text) > 300 else "")
        return f"В буфере обмена: {short}"
    except Exception as e:
        return f"Ошибка чтения буфера: {e}"


def _clipboard_set(text: str) -> str:
    import base64
    # Base64 избегает инъекции через '@ или спецсимволы PowerShell
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = (
        f"$bytes = [System.Convert]::FromBase64String('{encoded}');"
        "$text = [System.Text.Encoding]::UTF8.GetString($bytes);"
        "Set-Clipboard -Value $text"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Скопировано в буфер обмена, сэр."
    except Exception as e:
        return f"Ошибка: {e}"


# ---------------------------------------------------------------------------
# Поиск и переименование файлов
# ---------------------------------------------------------------------------

def _find_file(query: str) -> str:
    search_dirs = [
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path.home(),
    ]
    found: list[Path] = []
    for d in search_dirs:
        if not d.exists():
            continue
        try:
            for p in d.rglob(f"*{query}*"):
                if p.is_file():
                    found.append(p)
                    if len(found) >= 5:
                        break
        except Exception:
            continue
        if len(found) >= 5:
            break

    if not found:
        return f"Файл «{query}» не найден в стандартных папках, сэр."
    lines = [f"Нашёл {len(found)} файл(ов), сэр:"]
    for p in found:
        lines.append(f"  {p}")
    return "\n".join(lines)


def _rename_file(old: str, new: str) -> str:
    desktop = Path.home() / "Desktop"
    p_old = Path(old)
    if not p_old.is_absolute() and not p_old.exists():
        candidate = desktop / p_old.name
        if candidate.exists():
            p_old = candidate
    if not p_old.exists():
        return f"Файл «{old}» не найден, сэр."
    p_new = Path(new)
    if not p_new.is_absolute():
        p_new = p_old.parent / p_new.name
    try:
        p_old.rename(p_new)
        return f"Файл «{p_old.name}» переименован в «{p_new.name}», сэр."
    except Exception as e:
        return f"Не удалось переименовать: {e}"


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
    """Ищет приложение по имени (нечёткое совпадение + кросс-скрипт через APPS)."""
    try:
        name_low = name.lower().strip()
        with _db_conn() as conn:
            rows = conn.execute("SELECT name, path FROM custom_apps").fetchall()
        # Прямое совпадение
        for row_name, path in rows:
            if row_name == name_low or row_name in name_low or name_low in row_name:
                return path
        # Кросс-скрипт: "стим" и "steam" оба маппятся на "steam" → тот же путь
        cmd_query = _match_app(name_low)
        if cmd_query:
            for row_name, path in rows:
                if _match_app(row_name) == cmd_query:
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
        log.error("AppStore save error: %s", e)


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
    exe, err = _resolve_exe_path(path, app_name=name)
    if err:
        return f"{err}, сэр.\nПроверь путь и попробуй снова."
    _save_custom_app(name, str(exe))
    result = _launch_app(str(exe), name)
    return f"Запомнил «{name}» → {exe.name}, сэр. {result}"


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _extract_weather_city(query: str) -> str:
    """Извлекает название города из погодного запроса (оригинальный регистр)."""
    m = re.search(
        r'\b(?:в|in|для|for)\s+([А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z\-]{1,})',
        query, re.I,
    )
    return m.group(1) if m else ""


def _normalize_city_geo(city: str) -> str:
    """Убирает русские падежные окончания для передачи в геокодинг."""
    # -ве → -ва (Москве → Москва, Варшаве → Варшава)
    if city.endswith('ве') and len(city) > 4:
        return city[:-2] + 'ва'
    # -е → '' (Лондоне → Лондон, Берлине → Берлин, Калининграде → Калининград)
    if city.endswith('е') and len(city) > 4:
        return city[:-1]
    # -и → -ь (Казани → Казань, Перми → Пермь)
    if city.endswith('и') and len(city) > 4:
        return city[:-1] + 'ь'
    return city


def _city_prep(name: str) -> str:
    """Приблизительный предложный падеж для 'в {город}' (95%+ городов)."""
    if not name:
        return name
    last = name[-1].lower()
    # Несклоняемые: -о, -е, -у, -ю, -и, -ы
    if last in 'оеуюиы':
        return name
    # -ва: Москва→Москве, Варшава→Варшаве
    if name.lower().endswith('ва'):
        return name[:-1] + 'е'
    # -а (не -ва): Рига→Риге, Прага→Праге, Вена→Вене
    if last == 'а':
        return name[:-1] + 'е'
    # -я: rare for cities, just try
    if last == 'я':
        return name[:-1] + 'е'
    # -ь: Казань→Казани, Пермь→Перми
    if last == 'ь':
        return name[:-1] + 'и'
    # Согласная: Лондон→Лондоне, Берлин→Берлине
    return name + 'е'


def _weather(city: str = "") -> str:
    """Получает текущую погоду через Open-Meteo API (без API-ключа)."""
    import urllib.request
    import urllib.parse
    import json

    raw   = city.strip() or config.JARVIS_USER_CITY
    target = _normalize_city_geo(raw)  # снимаем падежные окончания

    # 1. Геокодирование: название → координаты
    geo_url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode(
            {"name": target, "count": 1, "language": "ru", "format": "json"}
        )
    )
    try:
        with urllib.request.urlopen(geo_url, timeout=6) as r:
            geo = json.loads(r.read())
    except Exception as e:
        return f"Нет связи с сервером погоды, сэр. ({e})"

    results = geo.get("results")
    if not results:
        return f"Город «{raw}» не найден, сэр."

    loc       = results[0]
    lat       = loc["latitude"]
    lon       = loc["longitude"]
    city_name = loc.get("name", target)       # каноническое имя от API
    city_disp = _city_prep(city_name)         # в предложном падеже

    # 2. Текущая погода
    wx_url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode({
            "latitude":         lat,
            "longitude":        lon,
            "current":          "temperature_2m,apparent_temperature,weathercode,windspeed_10m",
            "timezone":         "auto",
            "wind_speed_unit":  "kmh",
        })
    )
    try:
        with urllib.request.urlopen(wx_url, timeout=6) as r:
            wx = json.loads(r.read())
    except Exception as e:
        return f"Не могу получить погоду, сэр. ({e})"

    curr     = wx.get("current", {})
    temp     = curr.get("temperature_2m")
    feels    = curr.get("apparent_temperature")
    wmo      = curr.get("weathercode", 0)
    wind_kmh = curr.get("windspeed_10m", 0)

    def _fmt_t(t) -> str:
        if t is None:
            return "—"
        t = round(t)
        return f"плюс {t}" if t > 0 else (f"минус {abs(t)}" if t < 0 else "ноль")

    condition = _WMO_RU.get(wmo, "переменная облачность")

    if wind_kmh < 10:
        wind_str = "ветер тихий"
    elif wind_kmh < 30:
        wind_str = "ветер слабый"
    elif wind_kmh < 50:
        wind_str = "ветер умеренный"
    else:
        wind_str = "ветер сильный"

    line = f"В {city_disp} {condition}, {_fmt_t(temp)} градусов."
    if feels is not None and abs(feels - (temp or 0)) >= 3:
        line += f" Ощущается как {_fmt_t(feels)}."
    line += f" {wind_str.capitalize()}."

    return line


def _clean_rest(text: str) -> str:
    """Убирает пунктуацию и хвостовые вежливые слова из хвоста команды."""
    text = text.strip().rstrip("?!., ")
    text = re.sub(r'\s+(?:пожалуйста|please|thanks|спасибо)$', '', text, flags=re.I)
    return text.strip()


def _any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _delete_note_at(pos: int) -> str:
    """Удаляет заметку по позиции (1=первая/новейшая, -1=последняя/старейшая)."""
    from tools.notes import get_db, delete_note
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title FROM notes ORDER BY created_at DESC"
            ).fetchall()
    except Exception as e:
        return f"Ошибка чтения заметок: {e}"
    if not rows:
        return "Заметок нет, сэр."
    idx = (pos - 1) if pos > 0 else (len(rows) + pos)
    if not (0 <= idx < len(rows)):
        return f"Заметки с позицией {pos} не существует (всего заметок: {len(rows)}), сэр."
    return delete_note(str(rows[idx]["id"]))


def _delete_task_at(pos: int) -> str:
    """Удаляет задачу по позиции (1=первая в списке, -1=последняя)."""
    from tools.notes import get_db, delete_task
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title FROM tasks ORDER BY created_at DESC"
            ).fetchall()
    except Exception as e:
        return f"Ошибка чтения задач: {e}"
    if not rows:
        return "Задач нет, сэр."
    idx = (pos - 1) if pos > 0 else (len(rows) + pos)
    if not (0 <= idx < len(rows)):
        return f"Задачи с позицией {pos} не существует (всего задач: {len(rows)}), сэр."
    return delete_task(str(rows[idx]["id"]))


def _weekday(dt: datetime) -> str:
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return days[dt.weekday()]


# ---------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------

def _run_game_mode() -> str:
    """
    Запускает игровой режим в фоновом потоке — не блокирует UI/CLI на 17 секунд.
    """
    from core.scenarios import ScenarioRunner, GAME_MODE_STEPS

    def _bg():
        runner = ScenarioRunner(tts_fn=_tts_callback)
        runner.run(GAME_MODE_STEPS)

    threading.Thread(target=_bg, daemon=True, name="game-mode").start()
    return "Игровой режим запущен в фоне, сэр. Закрываю программы и запускаю Rust с Discord."
