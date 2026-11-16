"""
Абстрактный интерфейс LLM-провайдера.
Все провайдеры (Gemini, Claude, Ollama) реализуют этот класс,
поэтому остальной код не зависит от конкретного ИИ.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """Одно сообщение в истории разговора."""
    role: str          # "user" или "assistant"
    content: str


@dataclass
class ToolCall:
    """Запрос LLM на вызов инструмента."""
    name: str                          # Имя инструмента
    arguments: dict[str, Any]          # Аргументы
    id: str | None = None              # ID вызова (нужен для Claude tool_result)


@dataclass
class LLMResponse:
    """Ответ от LLM-провайдера."""
    text: str | None                   # Текстовый ответ (если есть)
    tool_calls: list[ToolCall] = field(default_factory=list)  # Вызовы инструментов
    raw: Any = None                    # Сырой ответ провайдера (для отладки)


class BaseLLMProvider(ABC):
    """
    Базовый класс для всех LLM-провайдеров.
    Чтобы добавить нового провайдера — создай класс, унаследованный от этого,
    и реализуй методы register_tools и chat.
    """

    def __init__(self):
        self._tools: list[dict] = []    # Зарегистрированные инструменты

    @abstractmethod
    def register_tools(self, tools: list[dict]) -> None:
        """
        Регистрирует список инструментов в провайдере.
        У каждого провайдера свой формат — конвертация происходит здесь.

        :param tools: список инструментов в универсальном формате
        """
        pass

    @abstractmethod
    def chat(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
    ) -> LLMResponse:
        """
        Отправляет сообщение и получает ответ.

        :param system_prompt: системный промпт с личностью Джарвиса
        :param history: история разговора в текущей сессии
        :param user_message: новое сообщение пользователя
        :return: ответ провайдера (текст и/или вызовы инструментов)
        """
        pass

    @abstractmethod
    def chat_with_tool_result(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
        tool_calls: list[ToolCall],
        tool_results: list[str],
        previous_rounds: list[tuple[list[ToolCall], list[str]]] | None = None,
    ) -> LLMResponse:
        """
        Отправляет результаты выполненных инструментов и получает следующий ответ LLM.

        :param tool_calls:      вызовы инструментов текущего раунда
        :param tool_results:    результаты (1:1 с tool_calls)
        :param previous_rounds: предыдущие раунды [(calls, results), ...] для многораундового диалога
        """
        pass


# --- Универсальный формат описания инструмента ---
# Все инструменты описываются в этом формате,
# а каждый провайдер сам конвертирует его в свой синтаксис.

def make_tool_definition(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
) -> dict:
    """
    Создаёт описание инструмента в универсальном формате.

    :param name: уникальное имя инструмента (snake_case)
    :param description: что делает инструмент (для LLM)
    :param parameters: параметры в формате JSON Schema properties
    :param required: список обязательных параметров
    """
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": parameters,
            "required": required or [],
        },
    }
