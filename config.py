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
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "claude" | "ollama"

# --- Настройки Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"        # Актуальная модель с function calling
GEMINI_MODEL_FALLBACK = "gemini-1.5-flash"  # Запасной вариант

# --- Настройки Claude ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

# --- Настройки Ollama ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

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
