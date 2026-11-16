"""
Центральный файл конфигурации Джарвиса.
Все настройки читаются из .env и задаются здесь.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- Пути ---
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "jarvis.db"
CHROMA_DIR = DATA_DIR / "chroma"

# Создаём папку data/ если её нет
DATA_DIR.mkdir(exist_ok=True)

# --- LLM провайдер ---
# DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
# LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "claude" | "ollama"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "cerebras")  # "cerebras" | "gemini" | "claude" | "ollama"

# DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
# --- Настройки Gemini ---
# _raw_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
# _raw_keys = _raw_keys.lstrip('﻿')
# GEMINI_API_KEYS: list[str] = [
#     k.strip() for k in _raw_keys.split(",")
#     if k.strip() and k.strip().startswith("AIza") and k.strip().isascii()
# ]
# GEMINI_MODEL = "models/gemini-2.0-flash"
# GEMINI_MODEL_FALLBACK = "models/gemini-2.0-flash-lite"

# DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
# --- Настройки Claude ---
# ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# CLAUDE_MODEL = "claude-sonnet-4-6"

# DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
# --- Настройки Ollama ---
# OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# --- Настройки Cerebras ---
CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
CEREBRAS_MODEL: str = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")

# --- Память ---
# Сколько похожих воспоминаний подгружать при каждом запросе
MEMORY_TOP_K = 5
# Сколько последних сообщений хранить в контексте текущей сессии
SESSION_HISTORY_LIMIT = 20

# --- Поиск ---
# Сколько результатов возвращать при поиске в интернете
SEARCH_MAX_RESULTS = 5

# --- Чтение файлов ---
# Максимальный размер файла для чтения (в символах)
FILE_MAX_CHARS = 50_000

# --- Аудио-устройства ---
# Индекс микрофона для записи (None = автоопределение).
# Узнать индекс: python -c "import sounddevice as sd; print(sd.query_devices())"
AUDIO_INPUT_DEVICE: int | None = None

# --- Голосовые настройки ---
# Размер модели Whisper: "tiny" / "base" / "small" / "medium" / "large-v3"
# "small" — хорошая точность для русского + быстро. "medium" — лучше, но медленнее.
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "medium")

# --- Настройки пользователя ---
JARVIS_USER_NAME: str = os.getenv("JARVIS_USER_NAME", "Влад")
JARVIS_USER_CITY: str = os.getenv("JARVIS_USER_CITY", "Москва")

# --- TTS движок ---
# "edge"       — бесплатно, Microsoft Neural + JARVIS DSP-обработка (по умолчанию)
# "elevenlabs" — реалистичный British JARVIS-голос, ~10 000 символов/мес бесплатно
TTS_ENGINE: str = os.getenv("TTS_ENGINE", "edge")

# --- ElevenLabs TTS (активируется при TTS_ENGINE="elevenlabs") ---
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

# Модель ElevenLabs. Самые выразительные модели с поддержкой русского:
#   eleven_multilingual_v2  — стабильная, проверенная (по умолчанию)
#   eleven_v3               — самая выразительная ("dramatic delivery"), 70+ языков
#   eleven_turbo_v2_5       — быстрая, меньше задержка, хорошее качество
#   eleven_flash_v2_5       — ультра-быстрая, минимальное качество
ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_v3")

# Голос. Мужские British/нейтральные голоса, подходящие для Джарвиса:
#   onwK4e9ZLuTAKqWW03F9 — Daniel  (глубокий авторитетный британский, текущий)
#   JBFqnCBsd6RMkjVDRZzb — George  (тёплый британский — рекомендуется)
#   TX3LPaxmHKxFdv7VOQHJ — Liam    (нейтральный, чёткий, ИИ-ассистент)
#   N2lVS1w4EtoT3dr4eOWO — Callum  (интенсивный британский с характером)
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")

# Настройки голоса — ПОДКРУЧИВАЙ ПОД СВОЙ ВКУС:
#   stability (0–1):        ниже → живее/вариативнее (0.3=много вариаций, 0.6=стабильно)
#   similarity_boost (0–1): выше → точнее воспроизводит оригинальный голос
#   style (0–1):            усиление стиля/экспрессивности (0=нейтрально, 0.5=выразительно)
#   speed (0.7–1.3):        1.0=нормально, 0.9=чуть медленнее и весомее, 1.1=быстрее
#   use_speaker_boost:      буст похожести на оригинальный голос (небольшая доп. нагрузка)
ELEVENLABS_STABILITY: float        = float(os.getenv("ELEVENLABS_STABILITY", "0.35"))
ELEVENLABS_SIMILARITY_BOOST: float = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.80"))
ELEVENLABS_STYLE: float            = float(os.getenv("ELEVENLABS_STYLE", "0.45"))
ELEVENLABS_SPEED: float            = float(os.getenv("ELEVENLABS_SPEED", "0.95"))
ELEVENLABS_USE_SPEAKER_BOOST: bool = os.getenv("ELEVENLABS_USE_SPEAKER_BOOST", "true").lower() in ("1", "true", "yes")

# Лимит символов за один вызов (бесплатный план ≈ 10 000 символов/мес)
ELEVENLABS_MAX_CHARS: int = 500

# --- Groq API (Level 2: структурирование результатов поиска) ---
# Бесплатный быстрый LLM. Получи ключ на: https://console.groq.com
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

# --- Безопасность ---

# True  — опасные операции (реестр, PS-команды изменяющие систему) требуют подтверждения
# False — всё выполняется без вопросов (только для тестирования)
SAFETY_REQUIRE_CONFIRM: bool = True

# --- Реестр ---
# Папка для .reg-бэкапов перед изменением реестра
REGISTRY_BACKUPS_DIR = DATA_DIR / "registry_backups"

# --- Игровой режим / Сценарии ---

# True  — показать список процессов и ждать подтверждения перед закрытием
# False — закрывать сразу (после первой проверки поменяй на False)
GAME_MODE_DRY_RUN: bool = True

# Путь к скрипту обхода Discord (батник/exe для zapret).
# Задай в .env: DISCORD_BYPASS_PATH=C:\fix_dc_1.9.8с\general (ALT11).bat
# Если пусто или файл не существует — шаг в игровом режиме пропускается.
DISCORD_BYPASS_PATH: str = os.getenv("DISCORD_BYPASS_PATH", "")

# Процессы которые НИКОГДА не закрываются в игровом режиме.
# Дополняй по необходимости (все имена — lowercase).
PROCESS_WHITELIST: set[str] = {
    # ── Критичные системные (kill = BSOD / черный экран) ──────────────────
    "system", "registry", "idle", "secure system",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "lsass.exe", "lsaiso.exe", "services.exe", "svchost.exe",
    "dwm.exe", "fontdrvhost.exe",

    # ── Рабочий стол и оболочка Windows ────────────────────────────────────
    "explorer.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "searchui.exe", "searchindexer.exe",
    "textinputhost.exe", "ctfmon.exe",
    "applicationframehost.exe",  # хост UWP-окон
    "sihost.exe",                # Shell Infrastructure Host (убийство = краш taskbar)
    "systemsettingsbroker.exe",  # брокер системных настроек Windows

    # ── Системные службы ────────────────────────────────────────────────────
    "audiodg.exe", "conhost.exe", "dllhost.exe", "taskhostw.exe",
    "runtimebroker.exe", "wmiprvse.exe", "spoolsv.exe",
    "sgrmbroker.exe", "lsaiso.exe",
    "unsecapp.exe",              # WMI sink

    # ── Безопасность Windows ────────────────────────────────────────────────
    "msmpeng.exe",               # Windows Defender
    "nissrv.exe",                # Defender Network Inspection
    "securityhealthsystray.exe", "securityhealthservice.exe",
    "mssense.exe",               # Defender for Endpoint

    # ── Антивирусы (распространённые — уточни свой) ─────────────────────────
    # Kaspersky
    "avp.exe", "avpui.exe", "klnagent.exe", "kavfs.exe", "kavfsgt.exe",
    # ESET
    "ekrn.exe", "egui.exe", "eplgbrep.exe",
    # Avast / AVG
    "avastsvc.exe", "avastui.exe", "aswidsagenta.exe",
    "avgsvc.exe", "avgui.exe", "avgcsrva.exe",
    # Bitdefender
    "bdagent.exe", "vsserv.exe", "updatesrv.exe", "bdredline.exe",
    # Norton / Symantec
    "ns.exe", "nortonsecurity.exe", "ccsvchst.exe",
    # McAfee
    "mcshield.exe", "mcuicnt.exe", "mfefire.exe",
    # Malwarebytes
    "mbamservice.exe", "mbamtray.exe", "mbam.exe",
    # Dr.Web
    "drweb32w.exe", "spideragent.exe", "dwnetfilter.exe",
    # Trend Micro
    "tmlisten.exe", "pccntmon.exe",

    # ── Steam (нужен для запуска Rust) ──────────────────────────────────────
    "steam.exe", "steamwebhelper.exe", "steamservice.exe",
    "gameoverlayui.exe", "streaming_client.exe", "steambootstrapper.exe",

    # ── Джарвис (python) — дополнительная защита по имени ──────────────────
    # Основная защита — по PID (см. core/scenarios.py)
    "python.exe", "pythonw.exe",
}

# --- Маппинг названий приложений → реальные имена процессов Windows ---
# Используется при закрытии приложений командой "закрой X".
# Значение None = никогда не закрывать (системные).
# Дополняй по необходимости: "моё_приложение": "MyApp.exe"
PROCESS_NAME_MAP: dict[str, str | None] = {
    # UWP-приложения Windows 10/11 (имя процесса отличается от команды запуска)
    "calc":               "CalculatorApp.exe",
    "calculator":         "CalculatorApp.exe",
    "калькулятор":        "CalculatorApp.exe",

    # Браузеры
    "chrome":             "chrome.exe",
    "хром":               "chrome.exe",
    "google chrome":      "chrome.exe",
    "firefox":            "firefox.exe",
    "фаерфокс":           "firefox.exe",
    "mozilla":            "firefox.exe",
    "opera":              "opera.exe",
    "brave":              "brave.exe",
    "edge":               "msedge.exe",
    "microsoft edge":     "msedge.exe",
    "браузер":            "chrome.exe",

    # Мессенджеры
    "discord":            "Discord.exe",
    "дискорд":            "Discord.exe",
    "telegram":           "Telegram.exe",
    "телеграм":           "Telegram.exe",
    "whatsapp":           "WhatsApp.exe",
    "вотсап":             "WhatsApp.exe",
    "slack":              "slack.exe",
    "teams":              "Teams.exe",

    # Системные утилиты
    "notepad":            "notepad.exe",
    "блокнот":            "notepad.exe",
    "paint":              "mspaint.exe",
    "паинт":              "mspaint.exe",
    "cmd":                "cmd.exe",
    "командная строка":   "cmd.exe",
    "powershell":         "powershell.exe",
    "terminal":           "WindowsTerminal.exe",
    "терминал":           "WindowsTerminal.exe",
    "taskmgr":            "Taskmgr.exe",
    "диспетчер задач":    "Taskmgr.exe",

    # Медиа
    "spotify":            "Spotify.exe",
    "спотифай":           "Spotify.exe",
    "vlc":                "vlc.exe",
    "obs":                "obs64.exe",
    "winamp":             "winamp.exe",

    # Разработка
    "vscode":             "Code.exe",
    "code":               "Code.exe",
    "vs code":            "Code.exe",
    "visual studio code": "Code.exe",
    "визуал студио":      "Code.exe",
    "pycharm":            "pycharm64.exe",
    "idea":               "idea64.exe",

    # Игры / лаунчеры
    "steam":              "steam.exe",
    "стим":               "steam.exe",
    "epicgames":          "EpicGamesLauncher.exe",
    "epic":               "EpicGamesLauncher.exe",
    "origin":             "Origin.exe",
    "uplay":              "upc.exe",
    "battle.net":         "Battle.net.exe",

    # Office
    "word":               "WINWORD.EXE",
    "excel":              "EXCEL.EXE",
    "powerpoint":         "POWERPNT.EXE",
    "outlook":            "OUTLOOK.EXE",

    # Системные — НИКОГДА не закрывать
    "explorer":           None,
    "проводник":          None,
}
