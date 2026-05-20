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
]

# Словарь name -> definition для быстрого поиска
TOOLS_BY_NAME = {t["name"]: t for t in TOOL_DEFINITIONS}
