"""
Провайдер Anthropic Claude.
Реализует BaseLLMProvider с поддержкой tool use и retry при временных ошибках.
"""

import time

import anthropic

import config
from core.logger import get_logger
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall

log = get_logger("claude")


class ClaudeProvider(BaseLLMProvider):
    """Провайдер Anthropic Claude с поддержкой tool use и retry."""

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
                "input_schema": tool["parameters"],
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

        response = self._call_api(**kwargs)
        return self._parse_response(response)

    def chat_with_tool_result(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
        tool_calls: list[ToolCall],
        tool_results: list[str],
        previous_rounds: list[tuple[list[ToolCall], list[str]]] | None = None,
    ) -> LLMResponse:
        """Отправляет результаты всех инструментов и получает финальный ответ."""
        messages = self._build_messages(history, user_message)

        # Предыдущие раунды (multi-round tool calling)
        if previous_rounds:
            for prev_calls, prev_results in previous_rounds:
                messages.append({
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": tc.id or f"toolu_{tc.name}",
                         "name": tc.name, "input": tc.arguments}
                        for tc in prev_calls
                    ],
                })
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": tc.id or f"toolu_{tc.name}",
                         "content": result}
                        for tc, result in zip(prev_calls, prev_results)
                    ],
                })

        # Текущий раунд: один ход ассистента со всеми tool_use блоками
        messages.append({
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tc.id or f"toolu_{tc.name}",
                 "name": tc.name, "input": tc.arguments}
                for tc in tool_calls
            ],
        })

        # Один ход пользователя со всеми tool_result блоками
        messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc.id or f"toolu_{tc.name}",
                 "content": result}
                for tc, result in zip(tool_calls, tool_results)
            ],
        })

        response = self._call_api(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=self._claude_tools if self._claude_tools else [],
        )

        return self._parse_response(response)

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _call_api(self, **kwargs):
        """
        Вызывает Claude API с retry при временных ошибках.
        3 попытки с паузами 15/30/45 с при 529 (overloaded) / 503 / 429.
        """
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                return self._client.messages.create(**kwargs)

            except Exception as e:
                last_exc = e
                err = str(e)
                is_overloaded  = "529" in err or "overloaded" in err.lower()
                is_unavailable = "503" in err or "unavailable" in err.lower()
                is_rate_limit  = "429" in err or "rate_limit" in err.lower()
                is_auth_error  = "401" in err or "403" in err or "authentication" in err.lower()

                if is_auth_error:
                    raise ConnectionError("CLAUDE_AUTH_ERROR") from e

                if (is_overloaded or is_unavailable or is_rate_limit) and attempt < 2:
                    wait = 15 * (attempt + 1)
                    log.warning(f"Claude: временная ошибка, retry через {wait}с (попытка {attempt+1}/3)")
                    time.sleep(wait)
                    continue

                raise

        raise ConnectionError("CLAUDE_UNAVAILABLE") from last_exc

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
                    ToolCall(name=block.name, arguments=block.input, id=block.id)
                )
            elif block.type == "text":
                text = block.text

        return LLMResponse(text=text, tool_calls=tool_calls, raw=response)
