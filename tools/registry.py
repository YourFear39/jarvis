"""
Реестр инструментов Джарвиса.
Все инструменты регистрируются здесь и передаются в LLM-провайдер.
"""

from llm.base import make_tool_definition


# --- Описания инструментов (что LLM видит и понимает) ---

TOOL_DEFINITIONS = [
    make_tool_definition(
        name="web_search",
        description="Поиск актуальной информации в интернете через DuckDuckGo. "
                    "Используй когда нужны свежие новости, цены, факты или любая информация, "
                    "которой может не быть в базе знаний.",
        parameters={
            "query": {
                "type": "string",
                "description": "Поисковый запрос на любом языке",
            }
        },
        required=["query"],
    ),

    make_tool_definition(
        name="add_note",
        description="Сохраняет заметку для последующего использования. "
                    "Используй когда пользователь просит что-то записать или запомнить.",
        parameters={
            "title": {
                "type": "string",
                "description": "Заголовок заметки",
            },
            "content": {
                "type": "string",
                "description": "Содержимое заметки",
            },
            "tags": {
                "type": "string",
                "description": "Теги через запятую (необязательно), например: работа, идеи",
            },
        },
        required=["title", "content"],
    ),

    make_tool_definition(
        name="get_notes",
        description="Показывает сохранённые заметки. "
                    "Можно искать по ключевому слову или показать все.",
        parameters={
            "search": {
                "type": "string",
                "description": "Ключевое слово для поиска (необязательно). "
                               "Если не указано — показывает последние 10 заметок.",
            }
        },
        required=[],
    ),

    make_tool_definition(
        name="add_task",
        description="Добавляет задачу в список дел (to-do).",
        parameters={
            "title": {
                "type": "string",
                "description": "Название задачи",
            },
            "priority": {
                "type": "string",
                "description": "Приоритет: high, medium, low (по умолчанию medium)",
            },
            "due_date": {
                "type": "string",
                "description": "Дата дедлайна в формате ГГГГ-ММ-ДД (необязательно)",
            },
        },
        required=["title"],
    ),

    make_tool_definition(
        name="get_tasks",
        description="Показывает список задач. По умолчанию только невыполненные.",
        parameters={
            "show_completed": {
                "type": "string",
                "description": "Показывать выполненные задачи? true/false (по умолчанию false)",
            }
        },
        required=[],
    ),

    make_tool_definition(
        name="complete_task",
        description="Отмечает задачу как выполненную.",
        parameters={
            "task_id": {
                "type": "string",
                "description": "ID задачи (число). "
                               "Если не знаешь ID — сначала вызови get_tasks.",
            }
        },
        required=["task_id"],
    ),

    make_tool_definition(
        name="delete_task",
        description="Удаляет задачу из списка дел.",
        parameters={
            "task_id": {
                "type": "string",
                "description": "ID задачи (число). "
                               "Если не знаешь ID — сначала вызови get_tasks.",
            }
        },
        required=["task_id"],
    ),

    make_tool_definition(
        name="delete_note",
        description="Удаляет заметку по ID или по ключевому слову/названию. "
                    "Передай числовой ID если знаешь его, иначе передай название или ключевое слово — "
                    "инструмент найдёт нужную заметку сам. "
                    "Если найдено несколько — вернёт список для уточнения.",
        parameters={
            "note_id": {
                "type": "string",
                "description": "ID заметки (число) или ключевое слово/название для поиска.",
            }
        },
        required=["note_id"],
    ),

    make_tool_definition(
        name="read_file",
        description="Читает содержимое файла на компьютере пользователя. "
                    "Поддерживает .txt, .md, .pdf, .docx и файлы с кодом.",
        parameters={
            "path": {
                "type": "string",
                "description": "Абсолютный или относительный путь к файлу",
            }
        },
        required=["path"],
    ),

    make_tool_definition(
        name="create_plan",
        description="Создаёт план выполнения задачи с конкретными шагами.",
        parameters={
            "title": {
                "type": "string",
                "description": "Название плана",
            },
            "steps": {
                "type": "string",
                "description": "Шаги через символ |, например: Шаг 1|Шаг 2|Шаг 3",
            },
        },
        required=["title", "steps"],
    ),

    make_tool_definition(
        name="get_plan",
        description="Показывает план и текущий прогресс по шагам.",
        parameters={
            "plan_id": {
                "type": "string",
                "description": "ID плана. Если не указан — показывает все активные планы.",
            }
        },
        required=[],
    ),

    make_tool_definition(
        name="update_plan_step",
        description="Отмечает шаг плана как выполненный.",
        parameters={
            "plan_id": {
                "type": "string",
                "description": "ID плана",
            },
            "step_number": {
                "type": "string",
                "description": "Номер шага (начиная с 1)",
            },
        },
        required=["plan_id", "step_number"],
    ),

    make_tool_definition(
        name="create_file_with_content",
        description=(
            "Создаёт файл на компьютере с указанным содержимым. "
            "Используй когда пользователь просит создать любой файл: "
            "txt, bat, ps1, reg, py, html, json, csv, md, docx и т.д. "
            "Ты сам генерируешь содержимое файла согласно запросу."
        ),
        parameters={
            "path": {
                "type": "string",
                "description": "Полный путь к файлу, например C:\\Users\\Vlad\\Desktop\\script.bat",
            },
            "content": {
                "type": "string",
                "description": "Содержимое файла (текст, код, разметка — зависит от типа файла)",
            },
        },
        required=["path", "content"],
    ),

    make_tool_definition(
        name="list_directory",
        description="Показывает содержимое папки на компьютере (файлы и подпапки).",
        parameters={
            "path": {
                "type": "string",
                "description": "Путь к папке. Если не указан — показывает домашнюю папку.",
            }
        },
        required=[],
    ),

    make_tool_definition(
        name="run_powershell",
        description=(
            "Выполняет команду PowerShell на компьютере пользователя. "
            "Используй для: получения системной информации, управления процессами, "
            "настройки ОС, работы с реестром, сетевых команд и других системных задач. "
            "НЕ используй для удаления системных файлов."
        ),
        parameters={
            "command": {
                "type": "string",
                "description": "PowerShell команда или скрипт для выполнения",
            }
        },
        required=["command"],
    ),

    make_tool_definition(
        name="open_app",
        description=(
            "Открывает приложение на компьютере пользователя. "
            "Используй только если local_handler не справился — "
            "это резервный инструмент для нестандартных запросов открытия приложений."
        ),
        parameters={
            "name": {
                "type": "string",
                "description": "Название приложения для открытия",
            }
        },
        required=["name"],
    ),

    make_tool_definition(
        name="open_url",
        description="Открывает веб-сайт или URL в браузере по умолчанию.",
        parameters={
            "url": {
                "type": "string",
                "description": "URL или домен сайта, например: youtube.com или https://github.com",
            }
        },
        required=["url"],
    ),

    # ── Реестр Windows ───────────────────────────────────────────────────────

    make_tool_definition(
        name="registry_read",
        description=(
            "Читает значение из реестра Windows. Выполняется сразу без подтверждения. "
            "Используй для проверки настроек системы, параметров приложений и т.д."
        ),
        parameters={
            "path": {
                "type": "string",
                "description": (
                    "Путь к ветке реестра, например: HKCU\\Software\\MyApp "
                    "или HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
                ),
            },
            "value_name": {
                "type": "string",
                "description": "Имя значения для чтения. Пусто = значение по умолчанию (Default).",
            },
        },
        required=["path"],
    ),

    make_tool_definition(
        name="registry_list",
        description=(
            "Показывает содержимое ветки реестра Windows: все подветки и значения. "
            "Выполняется сразу без подтверждения."
        ),
        parameters={
            "path": {
                "type": "string",
                "description": "Путь к ветке реестра, например: HKCU\\Software или HKLM\\SOFTWARE",
            },
        },
        required=["path"],
    ),

    make_tool_definition(
        name="registry_write",
        description=(
            "Записывает или изменяет значение в реестре Windows. "
            "ВНИМАНИЕ: требует подтверждения пользователя. "
            "Перед записью автоматически создаётся .reg-бэкап. "
            "Используй для изменения настроек приложений и системы."
        ),
        parameters={
            "path": {
                "type": "string",
                "description": "Путь к ветке реестра, например: HKCU\\Software\\MyApp",
            },
            "value_name": {
                "type": "string",
                "description": "Имя значения для записи",
            },
            "value": {
                "type": "string",
                "description": "Новое значение (для REG_DWORD укажи число как строку, например '1')",
            },
            "value_type": {
                "type": "string",
                "description": (
                    "Тип значения: REG_SZ (строка, по умолчанию), REG_DWORD (32-bit число), "
                    "REG_QWORD (64-bit число), REG_EXPAND_SZ (строка с переменными среды)"
                ),
            },
        },
        required=["path", "value_name", "value"],
    ),

    make_tool_definition(
        name="registry_delete_value",
        description=(
            "Удаляет значение из ветки реестра Windows. "
            "Требует подтверждения пользователя. Перед удалением создаётся .reg-бэкап."
        ),
        parameters={
            "path": {
                "type": "string",
                "description": "Путь к ветке реестра",
            },
            "value_name": {
                "type": "string",
                "description": "Имя значения для удаления",
            },
        },
        required=["path", "value_name"],
    ),
]

# Словарь name -> definition для быстрого поиска
TOOLS_BY_NAME = {t["name"]: t for t in TOOL_DEFINITIONS}
