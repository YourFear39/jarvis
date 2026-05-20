"""
Главный оркестратор Джарвиса.
Принимает сообщение пользователя, взаимодействует с LLM,
вызывает инструменты и возвращает финальный ответ.
"""

from llm.base import BaseLLMProvider, Message, ToolCall
from core.memory import JarvisMemory
from core.personality import get_system_prompt
from tools.registry import TOOL_DEFINITIONS

import config


# Импорты всех инструментов
from tools.search import web_search
from tools.notes import add_note, get_notes, add_task, get_tasks, complete_task
from tools.files import read_file
from tools.planning import create_plan, get_plan, update_plan_step


# Маршрутизатор: имя инструмента → функция
TOOL_HANDLERS = {
    "web_search": lambda args: web_search(**args),
    "add_note": lambda args: add_note(**args),
    "get_notes": lambda args: get_notes(**args),
    "add_task": lambda args: add_task(**args),
    "get_tasks": lambda args: get_tasks(**args),
    "complete_task": lambda args: complete_task(**args),
    "read_file": lambda args: read_file(**args),
    "create_plan": lambda args: create_plan(**args),
    "get_plan": lambda args: get_plan(**args),
    "update_plan_step": lambda args: update_plan_step(**args),
}

# Сообщения-заглушки когда LLM недоступен, но инструмент уже отработал
_TOOL_FALLBACK_INTRO = {
    "web_search": "Нашёл в интернете (LLM временно недоступен для обработки):\n\n",
    "add_note": "",
    "get_notes": "",
    "add_task": "",
    "get_tasks": "",
    "complete_task": "",
    "read_file": "Содержимое файла (LLM временно недоступен):\n\n",
    "create_plan": "",
    "get_plan": "",
    "update_plan_step": "",
}


class JarvisAssistant:
    """
    Центральный класс — мозг Джарвиса.
    Связывает LLM-провайдер, память, инструменты и личность в единую систему.
    """

    def __init__(self, llm_provider: BaseLLMProvider, memory: JarvisMemory, on_tool_use=None):
        self._llm = llm_provider
        self._memory = memory
        self._history: list[Message] = []  # История текущей сессии
        self._on_tool_use = on_tool_use  # Callback для показа "использую инструмент..."

        # Регистрируем инструменты в LLM-провайдере
        self._llm.register_tools(TOOL_DEFINITIONS)

    def chat(self, user_message: str) -> str:
        """
        Основной метод: принимает сообщение и возвращает ответ Джарвиса.

        Цикл:
        1. Подгружаем релевантные воспоминания
        2. Отправляем в LLM
        3. Если LLM хочет инструмент — вызываем его и отправляем результат обратно
        4. Если второй вызов LLM упал — показываем сырые результаты инструмента
        5. Получаем финальный ответ, сохраняем в память
        """
        memories = self._memory.get_relevant_memories(user_message)
        system_prompt = get_system_prompt(memories if memories else None)

        # Первый запрос к LLM
        response = self._llm.chat(
            system_prompt=system_prompt,
            history=self._history[-config.SESSION_HISTORY_LIMIT:],
            user_message=user_message,
        )

        # Если LLM хочет вызвать инструмент
        if response.tool_calls:
            tool_call = response.tool_calls[0]

            if self._on_tool_use:
                self._on_tool_use(tool_call.name)

            tool_result = self._execute_tool(tool_call)

            # Отправляем результат инструмента обратно в LLM
            # Если LLM временно недоступен — показываем результат напрямую
            try:
                response = self._llm.chat_with_tool_result(
                    system_prompt=system_prompt,
                    history=self._history[-config.SESSION_HISTORY_LIMIT:],
                    user_message=user_message,
                    tool_call=tool_call,
                    tool_result=tool_result,
                )
            except ConnectionError:
                # LLM упал на втором запросе, но инструмент уже дал результат
                # Возвращаем сырые данные — лучше чем ничего
                intro = _TOOL_FALLBACK_INTRO.get(tool_call.name, "")
                final_text = intro + tool_result
                self._save_to_history(user_message, final_text)
                return final_text

        final_text = response.text or "(Нет ответа)"
        self._save_to_history(user_message, final_text)
        return final_text

    def _save_to_history(self, user_message: str, response_text: str) -> None:
        """Сохраняет обмен в историю сессии и долговременную память."""
        self._history.append(Message(role="user", content=user_message))
        self._history.append(Message(role="assistant", content=response_text))
        self._memory.save_exchange(user_message, response_text)

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """Выполняет вызов инструмента и возвращает результат."""
        handler = TOOL_HANDLERS.get(tool_call.name)

        if not handler:
            return f"Ошибка: инструмент '{tool_call.name}' не найден."

        try:
            result = handler(tool_call.arguments)
            return str(result)
        except TypeError as e:
            return f"Ошибка вызова инструмента '{tool_call.name}': неверные аргументы. {e}"
        except Exception as e:
            return f"Ошибка при выполнении '{tool_call.name}': {str(e)}"

    def clear_session_history(self) -> None:
        """Очищает историю текущей сессии (не затрагивает долговременную память)."""
        self._history.clear()

    def get_memory_stats(self) -> str:
        """Возвращает информацию о том, что Джарвис помнит."""
        return self._memory.get_memory_stats()
