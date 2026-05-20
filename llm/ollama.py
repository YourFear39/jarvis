"""
Провайдер Ollama (локальные модели).
Реализует BaseLLMProvider через OpenAI-совместимый API Ollama.
Примечание: поддержка function calling зависит от конкретной модели.
"""

import json
import requests

import config
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall


class OllamaProvider(BaseLLMProvider):
    """Провайдер Ollama для локальных LLM-моделей."""

    def __init__(self):
        super().__init__()
        self._base_url = config.OLLAMA_BASE_URL
        self._model = config.OLLAMA_MODEL
        self._tools_json: list[dict] = []

        self._check_connection()

    def _check_connection(self):
        """Проверяет что Ollama запущена и доступна."""
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except Exception:
            raise ConnectionError(
                f"Не могу подключиться к Ollama по адресу {self._base_url}. "
                "Убедись что Ollama запущена: https://ollama.ai"
            )

    def register_tools(self, tools: list[dict]) -> None:
        """Конвертирует инструменты в формат OpenAI (который поддерживает Ollama)."""
        self._tools_json = [
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
        """Отправляет сообщение в Ollama и возвращает ответ."""
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        if self._tools_json:
            payload["tools"] = self._tools_json

        response = requests.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def chat_with_tool_result(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
        tool_call: ToolCall,
        tool_result: str,
    ) -> LLMResponse:
        """Отправляет результат инструмента и получает финальный ответ."""
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in history]
        messages.append({"role": "user", "content": user_message})
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "content": tool_result,
            "name": tool_call.name,
        })

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }

        response = requests.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        """Разбирает ответ Ollama в универсальный формат."""
        tool_calls = []
        text = None

        message = data.get("message", {})
        text = message.get("content") or None

        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            tool_calls.append(ToolCall(name=func["name"], arguments=args))

        return LLMResponse(text=text, tool_calls=tool_calls, raw=data)
