"""
Провайдер Anthropic Claude.
Реализует BaseLLMProvider с поддержкой tool use.
"""

import anthropic

import config
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall


class ClaudeProvider(BaseLLMProvider):
    """Провайдер Anthropic Claude с поддержкой tool use."""

    def __init__(self):
        super().__init__()

        if not config.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY не задан. Добавь ключ в файл .env"
            )

        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._claude_tools: list[dict] = []

    def register_tools(self, tools: list[dict]) -> None:
        """Конвертирует универсальные инструменты в формат Claude."""
        self._claude_tools = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],  # Claude использует input_schema
            }
            for tool in tools
        ]

    def chat(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
    ) -> LLMResponse:
        """Отправляет сообщение в Claude и возвращает ответ."""
        messages = self._build_messages(history, user_message)

        kwargs = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
        }
        if self._claude_tools:
            kwargs["tools"] = self._claude_tools

        response = self._client.messages.create(**kwargs)
        return self._parse_response(response)

    def chat_with_tool_result(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
        tool_call: ToolCall,
        tool_result: str,
    ) -> LLMResponse:
        """Отправляет результат инструмента и получает финальный ответ."""
        messages = self._build_messages(history, user_message)

        # Сначала получаем ответ с tool use от Claude
        kwargs = {
            "model": config.CLAUDE_MODEL,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
        }
        if self._claude_tools:
            kwargs["tools"] = self._claude_tools

        first_response = self._client.messages.create(**kwargs)

        # Добавляем ответ ассистента с tool use и результат инструмента
        messages.append({
            "role": "assistant",
            "content": first_response.content,
        })
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": first_response.content[0].id,
                    "content": tool_result,
                }
            ],
        })

        # Получаем финальный ответ
        final_response = self._client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=self._claude_tools if self._claude_tools else [],
        )

        return self._parse_response(final_response)

    def _build_messages(self, history: list[Message], user_message: str) -> list[dict]:
        """Конвертирует историю и новое сообщение в формат Claude."""
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in history
        ]
        messages.append({"role": "user", "content": user_message})
        return messages

    def _parse_response(self, response) -> LLMResponse:
        """Разбирает ответ Claude в универсальный формат."""
        tool_calls = []
        text = None

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(
                    ToolCall(name=block.name, arguments=block.input)
                )
            elif block.type == "text":
                text = block.text

        return LLMResponse(text=text, tool_calls=tool_calls, raw=response)
