"""
Офлайн-режим Джарвиса.
Работает без LLM — напрямую вызывает инструменты по ключевым словам.
Активируется автоматически когда API недоступен.
"""

import re
from datetime import datetime

from tools.notes import add_note, get_notes, add_task, get_tasks, complete_task, delete_note, delete_task
from tools.planning import get_plan, create_plan
from tools.search import web_search
from core.logger import get_logger

log = get_logger("offline")
_RE_ID_PREFIX = re.compile(r'^(?:номер|number|id|#|№|с\s+названием|под\s+названием)\s*', re.I)


def handle_offline(user_message: str) -> str | None:
    """
    Пытается ответить на сообщение без LLM.
    Возвращает ответ если смог обработать, None если не знает что делать.
    """
    msg = user_message.lower().strip()
    log.debug("offline INPUT: %r", user_message[:80])

    # --- Время и дата ---
    if _matches(msg, ["время", "который час", "сколько времени", "what time"]):
        now = datetime.now()
        return f"Сейчас {now.strftime('%H:%M')}, {_weekday(now)}, {now.strftime('%d.%m.%Y')}."

    if _matches(msg, ["дата", "какой день", "какое число", "what date", "today"]):
        now = datetime.now()
        return f"Сегодня {_weekday(now)}, {now.strftime('%d.%m.%Y')}."

    # --- Заметки ---
    if _matches(msg, ["покажи заметки", "мои заметки", "список заметок", "show notes"]):
        return get_notes()

    if _matches(msg, ["добавь заметку", "запиши", "сохрани заметку", "add note"]):
        for kw in ["добавь заметку", "запиши", "сохрани заметку"]:
            if kw in msg:
                content = user_message[user_message.lower().index(kw) + len(kw):].strip(" :—-")
                if content:
                    return add_note(title=content[:50], content=content)
        return "Что именно записать? Например: 'запиши купить молоко'"

    if _matches(msg, ["удали заметку", "удалить заметку", "delete note", "убери заметку"]):
        for kw in ["удали заметку", "удалить заметку", "delete note", "убери заметку"]:
            if kw in msg:
                arg = user_message[user_message.lower().index(kw) + len(kw):].strip(" :—-.,!?;:")
                arg = _RE_ID_PREFIX.sub("", arg).strip().strip(".,!?;: ")
                if arg:
                    return delete_note(arg)
        return "Укажи номер или название заметки. Например: 'удали заметку 3' или 'удали заметку список покупок'."

    # --- Задачи ---
    if _matches(msg, ["покажи задачи", "мои задачи", "список задач", "show tasks", "todo"]):
        return get_tasks()

    if _matches(msg, ["добавь задачу", "новая задача", "add task"]):
        for kw in ["добавь задачу", "новая задача", "add task"]:
            if kw in msg:
                title = user_message[user_message.lower().index(kw) + len(kw):].strip(" :—-")
                if title:
                    return add_task(title=title)
        return "Что добавить в задачи? Например: 'добавь задачу позвонить маме'"

    if _matches(msg, ["удали задачу", "delete task"]):
        for kw in ["удали задачу", "delete task"]:
            if kw in msg:
                arg = user_message[user_message.lower().index(kw) + len(kw):].strip(" :—-")
                arg = _RE_ID_PREFIX.sub("", arg).strip()
                if arg:
                    return delete_task(arg)
        return "Укажи номер задачи. Например: 'удали задачу 2'."

    if _matches(msg, ["выполни задачу", "сделал задачу", "задача выполнена", "отметь задачу", "complete task"]):
        for kw in ["выполни задачу", "сделал задачу", "задача выполнена", "отметь задачу", "complete task"]:
            if kw in msg:
                arg = user_message[user_message.lower().index(kw) + len(kw):].strip(" :—-")
                arg = _RE_ID_PREFIX.sub("", arg).strip()
                if arg:
                    return complete_task(arg)
        return "Укажи номер задачи. Например: 'выполни задачу 1'."

    # --- Планы ---
    if _matches(msg, ["покажи план", "мои планы", "планы", "show plan"]):
        return get_plan()

    # --- Поиск (без обработки LLM — сырые результаты) ---
    if _matches(msg, ["найди", "поищи", "search", "погода", "weather", "курс", "новости"]):
        results = web_search(user_message)
        return f"[Офлайн-поиск — LLM недоступен, показываю сырые результаты]\n\n{results}"

    log.debug("offline NO MATCH → None: %r", user_message[:80])
    return None  # Не смогли обработать офлайн


def offline_help() -> str:
    """Справка что доступно в офлайн-режиме."""
    now = datetime.now()
    return (
        f"API ИИ сейчас недоступен (лимит исчерпан или сервер перегружен).\n\n"
        f"Без API я могу:\n"
        f"  • Время/дата — 'который час', 'какой сегодня день'\n"
        f"  • Заметки    — 'покажи заметки', 'запиши ...', 'удали заметку 3'\n"
        f"  • Задачи     — 'покажи задачи', 'добавь задачу ...', 'выполни задачу 1', 'удали задачу 2'\n"
        f"  • Планы      — 'покажи планы'\n"
        f"  • Поиск      — 'найди ...', 'погода в ...'\n\n"
        f"Лимит Gemini обновляется в ~03:00 МСК. "
        f"Сейчас {now.strftime('%H:%M')}."
    )


def _matches(text: str, keywords: list[str]) -> bool:
    """Проверяет содержит ли текст хотя бы одно ключевое слово."""
    return any(kw in text for kw in keywords)


def _weekday(dt: datetime) -> str:
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return days[dt.weekday()]
