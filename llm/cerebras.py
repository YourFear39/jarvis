"""
Провайдер Cerebras (OpenAI-совместимый API).
Модель: llama-3.3-70b через Cerebras Cloud.
Документация: https://inference-docs.cerebras.ai
"""

import json
import time

from openai import OpenAI

import config
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall
from core.logger import get_logger

log = get_logger("cerebras")


class CerebrasProvider(BaseLLMProvider):
    """Провайдер Cerebras — OpenAI-совместимый endpoint, llama-3.3-70b."""

    def __init__(self):
        super().__init__()

        if not config.CEREBRAS_API_KEY:
            raise ValueError(
                "CEREBRAS_API_KEY не задан. Добавь ключ в файл .env"
            )

        self._client = OpenAI(
            base_url="https://api.cerebras.ai/v1",
            api_key=config.CEREBRAS_API_KEY,
        )
        self._model = config.CEREBRAS_MODEL
        self._openai_tools: list[dict] = []

    def register_tools(self, tools: list[dict]) -> None:
        """Конвертирует универсальные инструменты в формат OpenAI function calling."""
        self._openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ]

    def chat(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
    ) -> LLMResponse:
        """Отправляет сообщение в Cerebras и возвращает ответ."""
        messages = self._build_messages(system_prompt, history, user_message)
        response = self._generate(messages)
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
        """Строит полную цепочку tool-вызовов и отправляет в Cerebras."""
        messages = self._build_messages(system_prompt, history, user_message)

        # Предыдущие раунды (multi-round tool-loop)
        for round_idx, (prev_calls, prev_results) in enumerate(previous_rounds or []):
            messages.append(self._make_assistant_tool_message(prev_calls, round_idx))
            for i, (tc, result) in enumerate(zip(prev_calls, prev_results)):
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id or f"call_r{round_idx}_{i}",
                    "content": result,
                })

        # Текущий раунд
        cur_round = len(previous_rounds) if previous_rounds else 0
        messages.append(self._make_assistant_tool_message(tool_calls, cur_round))
        for i, (tc, result) in enumerate(zip(tool_calls, tool_results)):
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id or f"call_r{cur_round}_{i}",
                "content": result,
            })

        response = self._generate(messages)
        return self._parse_response(response)

    # ── Вспомогательные методы ──────────────────────────────────────────────

    def _make_assistant_tool_message(self, calls: list[ToolCall], round_idx: int) -> dict:
        """Синтезирует assistant-сообщение с tool_calls для истории диалога."""
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id or f"call_r{round_idx}_{i}",
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(calls)
            ],
        }

    def _build_messages(
        self, system_prompt: str, history: list[Message], user_message: str
    ) -> list[dict]:
        """Строит список сообщений в формате OpenAI."""
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role = msg.role if msg.role in ("user", "assistant") else "user"
            messages.append({"role": role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _generate(self, messages: list[dict]):
        """Отправляет запрос к Cerebras API. При временных ошибках делает до 3 попыток."""
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
        }
        if self._openai_tools:
            kwargs["tools"] = self._openai_tools
            kwargs["tool_choice"] = "auto"

        for attempt in range(3):
            try:
                return self._client.chat.completions.create(**kwargs)
            except Exception as e:
                err = str(e)
                is_rate   = "429" in err or "rate_limit" in err.lower()
                is_server = "503" in err or "502" in err or "unavailable" in err.lower()

                if (is_rate or is_server) and attempt < 2:
                    wait = 10 * (attempt + 1)
                    log.warning(
                        "Cerebras %s, повтор через %ds (попытка %d/3)",
                        "rate limit" if is_rate else "503",
                        wait, attempt + 1,
                    )
                    time.sleep(wait)
                    continue

                if is_server:
                    raise ConnectionError("CEREBRAS_UNAVAILABLE") from e
                raise

        raise ConnectionError("CEREBRAS_UNAVAILABLE")

    def _parse_response(self, response) -> LLMResponse:
        """Разбирает ответ OpenAI-формата в универсальный LLMResponse."""
        message = response.choices[0].message

        text = message.content  # None когда LLM запрашивает tool calls

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {}
                tool_calls.append(ToolCall(
                    name=tc.function.name,
                    arguments=args,
                    id=tc.id,
                ))

        return LLMResponse(text=text, tool_calls=tool_calls, raw=response)
