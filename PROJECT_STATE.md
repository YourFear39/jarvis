# PROJECT_STATE.md — Jarvis AI Assistant
*Снимок состояния: 2026-05-24*

---

## 1. СТРУКТУРА

```
C:\Projects\Jarvis\
│
├── main.py                  # Точка входа: --text (default) / --voice / --gui
├── config.py                # Все настройки из .env (API-ключи, модели, пути, лимиты)
├── _test_deep.py            # Глубокие интеграционные тесты [126/126 PASS]
├── _test_search.py          # Тесты поиска и качества ответа [65/65 PASS]
├── list_devices.py          # Утилита: список аудио-устройств
├── test_wake.py             # Утилита: тест wake word (не интегрировано в main.py)
├── create_icon.py           # Утилита: генерация иконки GUI
│
├── core/
│   ├── assistant.py         # Главный оркестратор: 3-уровневый роутинг, tool-loop
│   ├── local_handler.py     # Уровень 1: все локальные команды без LLM (~1990 строк)
│   ├── router.py            # Классификатор SEARCH vs AI (уровни 2 и 3)
│   ├── memory.py            # ChromaDB долговременная память (семантический поиск)
│   ├── safety.py            # Классификатор SAFE/CONFIRM/FORBIDDEN для опасных операций
│   ├── personality.py       # Генератор system prompt (JARVIS-персонаж)
│   ├── scenarios.py         # Игровой режим: закрыть фоновые проги, запустить Rust+Discord
│   ├── offline.py           # Офлайн-фолбэк когда LLM недоступен
│   └── logger.py            # Конфигурация логирования
│
├── llm/
│   ├── base.py              # Абстрактный LLM-провайдер (BaseLLMProvider, Message, ToolCall)
│   ├── gemini.py            # Gemini 2.0 Flash (rotation по нескольким ключам)
│   ├── claude.py            # Claude Sonnet (Anthropic)
│   ├── ollama.py            # Локальный Ollama (без API-ключа)
│   └── groq.py              # GroqSynthesizer: структурирует DDG → ответ (уровень 2)
│
├── tools/
│   ├── search.py            # DuckDuckGo поиск через ddgs (3 retry, 2s/4s задержки)
│   ├── notes.py             # SQLite: заметки и задачи (CRUD)
│   ├── files.py             # Чтение файлов (до FILE_MAX_CHARS символов)
│   ├── planning.py          # Планы в SQLite (create/get/update_step)
│   ├── pc_control.py        # PowerShell, создание файлов, запуск приложений/URL
│   ├── registry_ops.py      # Реестр Windows: read/list/write/delete (с CONFIRM)
│   └── registry.py          # (вспомогательный модуль реестра)
│
├── voice/
│   ├── tts.py               # TTS: edge-tts + JARVIS DSP (scipy/sounddevice/PyAV) + ElevenLabs
│   ├── stt.py               # STT: faster-whisper (локально, CUDA если есть)
│   ├── voice_loop.py        # Голосовой цикл: запись → распознавание → ответ → озвучка
│   ├── wake_word.py         # Wake word детектор (не интегрирован в основной цикл)
│   └── wake_audio.py        # Аудио для wake word
│
├── ui/
│   ├── app.py               # GUI-режим (Tkinter-based, --gui флаг)
│   └── cli.py               # Rich CLI: вывод ответов, промпт ввода
│
└── data/                    # Создаётся автоматически
    ├── jarvis.db            # SQLite: заметки, задачи, планы, custom_apps
    ├── chroma/              # ChromaDB: долговременная память
    └── registry_backups/    # .reg-бэкапы перед изменением реестра
```

---

## 2. ФУНКЦИОНАЛ (что реально работает, проверено тестами)

### Уровень 1 — LOCAL (мгновенно, без LLM, без интернета)

**Приложения**
- Открыть: chrome, discord, telegram, steam, vscode, spotify, vlc, obs, notepad, calc, explorer, paint, cmd, powershell, word, excel, regedit, настройки и др.
- Поиск неизвестных приложений: Start Menu → реестр → Program Files
- Регистрация пользовательских приложений: "добавь приложение rust C:\path\..."
- Закрыть приложение (taskkill + PowerShell fallback)
- Перезапустить приложение
- Проверка "уже запущен" перед повторным запуском

**Файлы и папки**
- Открыть файл/папку (включая ярлыки: загрузки, рабочий стол, документы, фото, музыку, видео)
- Создать файл (с шаблоном по расширению: .py, .bat, .html, .json, .ps1, .css, .xml, .reg)
- Создать .bat-файл который запускает приложения: "создай launch.bat который запускает discord и telegram"
- Удалить файл/папку (с защитой от удаления системных путей Windows)
- Переименовать файл
- Найти файл по имени (Desktop/Downloads/Documents/Home, до 5 результатов)
- Открыть URL в браузере

**Системные команды**
- Громче/тише (3 нажатия = ~6%), вкл/выкл звук
- Скриншот → PNG на рабочий стол
- Заблокировать экран
- Системная информация (RAM, CPU%)
- Список запущенных программ (топ-10 по памяти)
- Буфер обмена: прочитать / записать (base64 для корректной работы с кириллицей)
- Время и дата

**Питание** ⚠️ ОСТОРОЖНО — выполняются реально
- Выключить компьютер (shutdown /s /t 10)
- Перезагрузить (shutdown /r /t 10)
- Режим сна (rundll32 powrprof)
- Отмена выключения (shutdown /a)

**Погода**
- Текущая погода через Open-Meteo API (бесплатно, без ключа)
- Геокодинг + склонение города на русском
- По умолчанию — город из JARVIS_USER_CITY

**Заметки и задачи (SQLite, без LLM)**
- Добавить заметку / показать все / поиск по ключевому слову / удалить (по номеру, порядковому числительному, названию)
- Добавить задачу / показать / отметить выполненной / удалить

**Игровой режим**
- Закрывает фоновые процессы (кроме whitelist), запускает Rust + Discord
- По умолчанию GAME_MODE_DRY_RUN=True (показывает preview, ждёт подтверждения)

### Уровень 2 — SEARCH (интернет + Groq, без траты Gemini-квоты)

- DuckDuckGo поиск (ddgs, 5 результатов, 3 попытки с retry)
- Groq llama-3.3-70b-versatile для структурирования ответа
- Фолбэк на сырые DDG-результаты при Groq 429 / недоступности
- Передаёт последние 4 сообщения как контекст для разрешения местоимений

### Уровень 3 — AI (полный LLM с инструментами)

- Tool calls: web_search, add/get/delete notes, add/get/complete/delete tasks, create/get/update plans, read_file, create_file_with_content, list_directory, run_powershell, open_app, open_url, registry_read/list/write/delete
- Multi-round tool loop (до 5 раундов), смешанные reads+writes → сначала reads
- Долговременная память ChromaDB (Top-K=5 похожих разговоров)
- История сессии (последние 20 сообщений)
- Safety system для опасных операций (PowerShell, реестр, файловая запись)
- Офлайн-фолбэк при недоступности LLM

### Голосовой режим (`--voice` или `/voice`)

- STT: faster-whisper (medium), CUDA если доступна, иначе CPU
- TTS: edge-tts ru-RU-DmitryNeural + JARVIS DSP (High-pass 90Hz, resonance 900Hz, presence 3-5.5kHz, reverb)
- Push-to-talk: Enter → говори → тишина 1.4с → ответ
- ThinkingTimer: случайная фраза ("Секунду...", "Гляну...") если ответ идёт >1.2с
- Голосовые подтверждения для опасных операций
- ElevenLabs опциональный (British JARVIS, eleven_v3)

---

## 3. СТЕК И API

| Слой | Провайдер | Модель / Сервис | Требует ключ |
|------|-----------|-----------------|--------------|
| STT | faster-whisper | Whisper medium (локально) | Нет |
| TTS основной | edge-tts | ru-RU-DmitryNeural + DSP | Нет |
| TTS опциональный | ElevenLabs | eleven_v3, George voice | Да (платный) |
| Мозг L3 (default) | Google Gemini | gemini-2.0-flash | Да (бесплатный лимит) |
| Мозг L3 (alt) | Anthropic Claude | claude-sonnet-4-6 | Да |
| Мозг L3 (local) | Ollama | llama3.2 (настраивается) | Нет |
| Синтез L2 | Groq | llama-3.3-70b-versatile | Да (бесплатный лимит) |
| Поиск L2 | DuckDuckGo (ddgs) | — | Нет |
| Погода L1 | Open-Meteo | geocoding + forecast | Нет |
| Память | ChromaDB (локально) | DefaultEmbeddingFunction | Нет |
| Данные | SQLite (локально) | jarvis.db | Нет |

---

## 4. РОУТЕР

```
Входящее сообщение
        │
        ▼
[local_handler.handle_local()] ─── совпало → ответ немедленно (Уровень 1)
        │ None
        ▼
[router.classify()]
        │
        ├─ _AI_RE совпало (ПЕРВЫМ!) ──────────────────────► Уровень 3 (AI + tools)
        │   Паттерны: запомни, запиши, добавь задачу/заметку,
        │   придумай, напиши план/код/письмо, составь план,
        │   помоги написать, прочитай файл, подумай,
        │   объясни почему/как/зачем, разбери, вспомни
        │
        ├─ _SEARCH_RE совпало ────────────────────────────► Уровень 2 (DDG + Groq)
        │   Паттерны: погода/температура/прогноз, новости,
        │   курс валют, сколько стоит, что такое, кто такой,
        │   где находится, когда (был/родился/основали/полетел...),
        │   расскажи о/об/про, как работает, как установить,
        │   почему, что лучше, чем отличается, в чём разница,
        │   какой самый, кто изобрёл/написал/создал
        │
        └─ По умолчанию ──────────────────────────────────► Уровень 3 (AI)
            Разговорные фразы ("привет", "как дела") → LLM
```

**Важно:** AI-паттерны проверяются ПЕРВЫМИ. "Найди и запомни" → AI, не поиск.

---

## 5. ПОСЛЕДНИЕ ИЗМЕНЕНИЯ

**Тесты / критическая безопасность**
- `_test_deep.py`: shutdown/sleep/reboot переведены в PERMANENT SKIP (реально выполняются — нельзя запускать в тестах)
- `_test_search.py`: создан новый файл, 65 проверок поиска и роутера

**local_handler.py**
- Добавлен ярлык "музыку" → Music (падежная форма "музыка")
- Исправлен `_looks_like_path`: не матчит многословные предложения с расширением файла
- Исправлен `_clipboard_get/_set`: base64-обёртка для корректной кириллицы в PowerShell 5.1

**router.py**
- Добавлены паттерны SEARCH: `расскажи о`, `как работает`, `как установить`, `почему`, `что лучше`, `чем отличается`, `в чём разница`, `какой самый`, `самая (длинная|большая|...)`, `кто (изобрёл|написал|создал)`, `когда (родился|основали|полетел|...)` и другие

**tools/search.py**
- Retry-логика: 3 попытки с задержками 2s/4s при ошибке DDG

**llm/groq.py**
- Исправлен промпт: запрещено говорить "к сожалению"/"нет информации", обязан отвечать из знаний если DDG-результаты нерелевантны
- Добавлен retry при 429 (8с ожидание)
- `_format_raw`: обрезка сниппетов до 220 символов (была утечка до 2600 chars)

**voice/tts.py**
- `_pipeline`: ошибка воспроизведения одного предложения НЕ останавливает весь ответ (было `raise`, теперь `log.warning` + continue)
- `_play_array`: `sd.stop()` перед каждым `sd.play()` (сброс зависших PortAudio-потоков)
- `clean_for_tts`: удаление `[...]` паттернов — Wikipedia-сноски `[7][8]`, IPA `[ˈiːlɒn]`, редакторские `[* 1]` не попадают в edge-tts
- `_pipeline`: `asyncio.get_event_loop()` → `asyncio.get_running_loop()`

---

## 6. ИЗВЕСТНЫЕ ПРОБЛЕМЫ

**Критичные**
- ⚠️ Команды "выключи компьютер", "режим сна", "перезагрузи" РЕАЛЬНО ВЫПОЛНЯЮТСЯ — никогда не запускать в автотестах
- ❓ TTS-баг "обрывается после 3-4 букв" — три фикса применены (см. п.5), но не подтверждено живым тестом пользователем

**Groq / поиск**
- Groq free tier: 30 req/min. При прогоне тестов несколько раз подряд лимит исчерпывается, все синтезы падают в fallback на сырые DDG-результаты
- DDG иногда возвращает только YouTube-ссылки для некоторых запросов (напр. "почему небо синее") — ответ получается из raw видеозаголовков

**Голос**
- Wake word (voice/wake_word.py) реализован отдельно, но НЕ интегрирован в основной голосовой цикл — нет режима "всегда слушает"
- ElevenLabs: ~10,000 символов/месяц на бесплатном плане, быстро кончается при активном использовании

**GUI**
- `ui/app.py` существует, запускается через `--gui`, но не тестировался в рамках этих сессий — состояние неизвестно

**Память**
- ChromaDB DefaultEmbeddingFunction работает на CPU — может быть медленным при большой коллекции (>1000 записей)
- Если ChromaDB не установлена — долговременная память тихо отключается, всё продолжает работать

**Провайдеры LLM**
- Ollama: код есть, но конкретно не тестировался
- Claude: работает, но расходует платные токены
- Gemini квоты: у бесплатного плана дневной лимит; multi-key ротация помогает но не решает проблему полностью

**Мелочи**
- `GAME_MODE_DRY_RUN=True` — игровой режим всегда просит подтверждение; при переключении в False закрывает процессы без предупреждения
- Поиск файлов (`_find_file`) ищет только в Desktop/Downloads/Documents/Home, не по всему диску

---

## 7. КОНФИГ (ключевые переменные из config.py)

```
# LLM
LLM_PROVIDER          = "gemini"                    # gemini | claude | ollama
GEMINI_API_KEYS        = [...из .env, несколько через запятую...]
GEMINI_MODEL           = "models/gemini-2.0-flash"
GEMINI_MODEL_FALLBACK  = "models/gemini-2.0-flash-lite"
ANTHROPIC_API_KEY      = ...
CLAUDE_MODEL           = "claude-sonnet-4-6"
OLLAMA_BASE_URL        = "http://localhost:11434"
OLLAMA_MODEL           = "llama3.2"

# Groq (Level 2 синтез)
GROQ_API_KEY           = ...

# TTS
TTS_ENGINE             = "edge"                     # edge | elevenlabs
ELEVENLABS_API_KEY     = ...
ELEVENLABS_MODEL       = "eleven_v3"
ELEVENLABS_VOICE_ID    = "JBFqnCBsd6RMkjVDRZzb"    # George (British)
ELEVENLABS_MAX_CHARS   = 500                        # лимит на вызов

# STT
WHISPER_MODEL_SIZE     = "medium"                   # tiny|base|small|medium|large-v3
AUDIO_INPUT_DEVICE     = None                       # None = автоопределение

# Пользователь
JARVIS_USER_NAME       = "Влад"
JARVIS_USER_CITY       = "Москва"                   # город для погоды по умолчанию

# Поиск и память
SEARCH_MAX_RESULTS     = 5
MEMORY_TOP_K           = 5
SESSION_HISTORY_LIMIT  = 20
FILE_MAX_CHARS         = 50_000

# Безопасность
SAFETY_REQUIRE_CONFIRM = True                       # False = выполнять без вопросов
GAME_MODE_DRY_RUN      = True                       # False = без preview

# Пути
DB_PATH                = data/jarvis.db
CHROMA_DIR             = data/chroma
REGISTRY_BACKUPS_DIR   = data/registry_backups

# Discord zapret bypass
DISCORD_BYPASS_PATH    = ...                        # путь к bat/exe zapret
```
