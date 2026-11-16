"""
Главный оркестратор Джарвиса.
Принимает сообщение пользователя, взаимодействует с LLM,
вызывает инструменты и возвращает финальный ответ.
"""

from llm.base import BaseLLMProvider, Message, ToolCall
from core.memory import JarvisMemory
from core.personality import get_system_prompt
from core.logger import get_logger
from tools.registry import TOOL_DEFINITIONS

import config

log = get_logger("assistant")

# Импорты всех инструментов
from tools.search import web_search
from tools.notes import add_note, get_notes, add_task, get_tasks, complete_task, delete_task, delete_note
from tools.files import read_file
from tools.planning import create_plan, get_plan, update_plan_step
from tools.pc_control import (
    create_file_with_content, list_directory,
    run_powershell, open_app, open_url,
)
from tools.registry_ops import (
    registry_read, registry_list,
    registry_write, registry_delete_value,
)


_READ_ONLY_TOOLS = {
    "web_search", "get_notes", "get_tasks", "read_file",
    "list_directory", "registry_read", "registry_list", "get_plan",
}
MAX_TOOL_ROUNDS = 5

# Маршрутизатор: имя инструмента → функция
TOOL_HANDLERS = {
    "web_search":               lambda args: web_search(**args),
    "add_note":                 lambda args: add_note(**args),
    "get_notes":                lambda args: get_notes(**args),
    "add_task":                 lambda args: add_task(**args),
    "get_tasks":                lambda args: get_tasks(**args),
    "complete_task":            lambda args: complete_task(**args),
    "delete_task":              lambda args: delete_task(**args),
    "delete_note":              lambda args: delete_note(**args),
    "read_file":                lambda args: read_file(**args),
    "create_plan":              lambda args: create_plan(**args),
    "get_plan":                 lambda args: get_plan(**args),
    "update_plan_step":         lambda args: update_plan_step(**args),
    "create_file_with_content": lambda args: create_file_with_content(**args),
    "list_directory":           lambda args: list_directory(**args),
    "run_powershell":           lambda args: run_powershell(**args),
    "open_app":                 lambda args: open_app(**args),
    "open_url":                 lambda args: open_url(**args),
    "registry_read":            lambda args: registry_read(**args),
    "registry_list":            lambda args: registry_list(**args),
    "registry_write":           lambda args: registry_write(**args),
    "registry_delete_value":    lambda args: registry_delete_value(**args),
}

# Сообщения-заглушки когда LLM недоступен, но инструмент уже отработал
_TOOL_FALLBACK_INTRO = {
    "web_search": "Нашёл в интернете (LLM временно недоступен для обработки):\n\n",
    "read_file":  "Содержимое файла (LLM временно недоступен):\n\n",
}


class JarvisAssistant:
    """
    Центральный класс — мозг Джарвиса.
    Связывает LLM-провайдер, память, инструменты и личность в единую систему.
    """

    def __init__(self, llm_provider: BaseLLMProvider, memory: JarvisMemory, on_tool_use=None):
        self._llm = llm_provider
        self._memory = memory
        self._history: list[Message] = []
        self._on_tool_use = on_tool_use

        self._llm.register_tools(TOOL_DEFINITIONS)

    def chat(self, user_message: str) -> str:
        """
        Основной метод: принимает сообщение и возвращает ответ Джарвиса.

        Уровни обработки:
        1. Локальные команды (local_handler) — без ИИ, мгновенно
        2. Поиск + Groq — информационные вопросы (дёшево, без Gemini)
        3. Полный LLM (Gemini/Claude) — сложные задачи, заметки, планы
        """
        # Уровень 1: локальный обработчик (без LLM, без квоты)
        from core.local_handler import handle_local
        local_response = handle_local(user_message)
        if local_response is not None:
            log.info(f"[Router] Level.LOCAL: {user_message[:60]!r}")
            self._save_to_history(user_message, local_response)
            return local_response

        # Уровень 2: поиск + Groq (информационные запросы)
        from core.router import classify, Level
        level = classify(user_message)
        log.info(f"[Router] {user_message[:60]!r} → Level.{level.name}")

        if level == Level.SEARCH:
            return self._chat_search(user_message)

        # Уровень 3: полный LLM с инструментами
        memories = self._memory.get_relevant_memories(user_message)
        system_prompt = get_system_prompt(memories if memories else None)

        response = self._llm.chat(
            system_prompt=system_prompt,
            history=self._history[-config.SESSION_HISTORY_LIMIT:],
            user_message=user_message,
        )

        # Если LLM хочет вызвать инструмент(ы) — multi-round loop
        if response.tool_calls:
            all_rounds: list[tuple[list[ToolCall], list[str]]] = []

            for _round in range(MAX_TOOL_ROUNDS):
                if not response.tool_calls:
                    break

                call_names = {tc.name for tc in response.tool_calls}
                reads  = call_names & _READ_ONLY_TOOLS
                writes = call_names - _READ_ONLY_TOOLS

                # Round 0: при смешанных вызовах — сначала только reads,
                # чтобы LLM получил реальные данные перед записью.
                if _round == 0 and reads and writes:
                    to_execute = [tc for tc in response.tool_calls if tc.name in _READ_ONLY_TOOLS]
                    log.info(f"[Tool] Round 0 mixed — executing reads only: {[tc.name for tc in to_execute]}")
                else:
                    to_execute = response.tool_calls

                round_results: list[str] = []
                for tc in to_execute:
                    log.info(f"[Tool] {tc.name}({str(tc.arguments)[:60]})")
                    if self._on_tool_use:
                        self._on_tool_use(tc.name)
                    round_results.append(self._execute_tool(tc))

                try:
                    response = self._llm.chat_with_tool_result(
                        system_prompt=system_prompt,
                        history=self._history[-config.SESSION_HISTORY_LIMIT:],
                        user_message=user_message,
                        tool_calls=to_execute,
                        tool_results=round_results,
                        previous_rounds=all_rounds if all_rounds else None,
                    )
                except ConnectionError:
                    # LLM упал, но инструменты уже дали результаты
                    intro = _TOOL_FALLBACK_INTRO.get(to_execute[0].name, "")
                    final_text = intro + "\n\n".join(round_results)
                    self._save_to_history(user_message, final_text)
                    return final_text

                all_rounds.append((to_execute, round_results))

        final_text = response.text or "(Нет ответа)"
        self._save_to_history(user_message, final_text)
        return final_text

    def _chat_search(self, user_message: str) -> str:
        """
        Уровень 2: поиск DuckDuckGo + Groq для структурирования.
        Не тратит лимиты Gemini. Откат на сырые результаты если Groq недоступен.
        """
        from tools.search import web_search
        from llm.groq import GroqSynthesizer

        if self._on_tool_use:
            self._on_tool_use("web_search")

        recent = self._history[-4:]
        context = "\n".join(f"{m.role}: {m.content[:200]}" for m in recent) if recent else ""

        raw_results = web_search(user_message)
        log.info(f"[Search] {len(raw_results)} символов результатов")

        response = GroqSynthesizer().synthesize(user_message, raw_results, context=context)
        log.info(f"[Groq] Ответ {len(response)} символов")

        self._save_to_history(user_message, response)
        return response

    def _save_to_history(self, user_message: str, response_text: str) -> None:
        """Сохраняет обмен в историю сессии и долговременную память."""
        self._history.append(Message(role="user", content=user_message))
        self._history.append(Message(role="assistant", content=response_text))
        self._memory.save_exchange(user_message, response_text)

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """Выполняет вызов инструмента и возвращает результат."""
        handler = TOOL_HANDLERS.get(tool_call.name)

        if not handler:
            log.warning(f"[Tool] Неизвестный инструмент: {tool_call.name}")
            return f"Ошибка: инструмент '{tool_call.name}' не найден."

        try:
            result = handler(tool_call.arguments)
            return str(result)
        except TypeError as e:
            log.error(f"[Tool] Неверные аргументы для {tool_call.name}: {e}")
            return f"Ошибка вызова инструмента '{tool_call.name}': неверные аргументы. {e}"
        except Exception as e:
            log.error(f"[Tool] Ошибка в {tool_call.name}: {e}")
            return f"Ошибка при выполнении '{tool_call.name}': {str(e)}"

    def clear_session_history(self) -> None:
        """Очищает историю текущей сессии (не затрагивает долговременную память)."""
        self._history.clear()

    def get_memory_stats(self) -> str:
        """Возвращает информацию о том, что Джарвис помнит."""
        return self._memory.get_memory_stats()
