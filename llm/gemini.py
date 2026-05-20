"""
Провайдер Google Gemini.
Использует актуальный пакет google-genai (не устаревший google-generativeai).
"""

import re
import time

from google import genai
from google.genai import types

import config
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall


class GeminiProvider(BaseLLMProvider):
    """Провайдер Google Gemini с поддержкой function calling."""

    def __init__(self):
        super().__init__()

        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY не задан. Добавь ключ в файл .env"
            )

        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._model_name = config.GEMINI_MODEL
        self._gemini_tools: list = []

    def register_tools(self, tools: list[dict]) -> None:
        """Конвертирует универсальные инструменты в формат Gemini."""
        declarations = []

        for tool in tools:
            params = tool["parameters"]

            # Конвертируем JSON Schema properties в формат Gemini
            gemini_props = {}
            for param_name, param_info in params.get("properties", {}).items():
                type_str = param_info.get("type", "string").upper()
                # Маппинг типов JSON Schema → Gemini
                type_map = {
                    "STRING": "STRING",
                    "INTEGER": "INTEGER",
                    "NUMBER": "NUMBER",
                    "BOOLEAN": "BOOLEAN",
                    "ARRAY": "ARRAY",
                    "OBJECT": "OBJECT",
                }
                gemini_type = type_map.get(type_str, "STRING")

                gemini_props[param_name] = types.Schema(
                    type=gemini_type,
                    description=param_info.get("description", ""),
                )

            declarations.append(
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters=types.Schema(
                        type="OBJECT",
                        properties=gemini_props,
                        required=params.get("required", []),
                    ),
                )
            )

        self._gemini_tools = [types.Tool(function_declarations=declarations)] if declarations else []

    def chat(
        self,
        system_prompt: str,
        history: list[Message],
        user_message: str,
    ) -> LLMResponse:
        """Отправляет сообщение в Gemini и возвращает ответ."""
        contents = self._build_contents(history, user_message)

        try:
            response = self._generate(system_prompt, contents)
        except ConnectionError:
            raise
        except Exception as e:
            # Модель не найдена → пробуем запасную
            if "not found" in str(e).lower() or "404" in str(e):
                self._model_name = config.GEMINI_MODEL_FALLBACK
                response = self._generate(system_prompt, contents)
            else:
                raise
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
        contents = self._build_contents(history, user_message)

        # Ответ модели с function call
        contents.append(types.Content(
            role="model",
            parts=[types.Part(
                function_call=types.FunctionCall(
                    name=tool_call.name,
                    args=tool_call.arguments,
                )
            )],
        ))

        # Результат выполнения инструмента
        contents.append(types.Content(
            role="user",
            parts=[types.Part(
                function_response=types.FunctionResponse(
                    name=tool_call.name,
                    response={"result": tool_result},
                )
            )],
        ))

        response = self._generate(system_prompt, contents)
        return self._parse_response(response)

    def _generate(self, system_prompt: str, contents: list):
        """
        Отправляет запрос к Gemini API.
        При ошибке 429 (rate limit) ждёт нужное время и повторяет автоматически.
        """
        cfg = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=self._gemini_tools if self._gemini_tools else None,
        )

        for attempt in range(3):
            try:
                return self._client.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=cfg,
                )
            except Exception as e:
                err = str(e)
                is_rate_limit = "429" in err or "resource_exhausted" in err.lower()
                is_unavailable = "503" in err or "unavailable" in err.lower()

                if (is_rate_limit or is_unavailable) and attempt < 2:
                    # Пробуем вытащить время ожидания из сообщения об ошибке
                    match = re.search(r'retry[^\d]*(\d+)', err, re.IGNORECASE)
                    wait = int(match.group(1)) + 2 if match else 30
                    print(f"\n  [Gemini] Квота. Жду {wait} сек и повторяю...")
                    time.sleep(wait)
                    continue

                # Дневной лимит исчерпан — нет смысла повторять
                if is_rate_limit:
                    raise ConnectionError(
                        "Исчерпан дневной лимит запросов Gemini (бесплатный тариф). "
                        "Лимит обновляется каждый день в ~03:00 по Москве."
                    ) from e

                if is_unavailable:
                    raise ConnectionError(
                        "Серверы Gemini временно недоступны. Попробуй через минуту."
                    ) from e

                raise

    def _build_contents(self, history: list[Message], user_message: str) -> list:
        """Конвертирует историю и новое сообщение в формат Gemini."""
        contents = []

        for msg in history:
            role = "user" if msg.role == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part(text=msg.content)],
            ))

        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=user_message)],
        ))

        return contents

    def _parse_response(self, response) -> LLMResponse:
        """Разбирает ответ Gemini в универсальный формат."""
        tool_calls = []
        text = None

        try:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call and part.function_call.name:
                    tool_calls.append(
                        ToolCall(
                            name=part.function_call.name,
                            arguments=dict(part.function_call.args or {}),
                        )
                    )
                elif hasattr(part, "text") and part.text:
                    text = part.text
        except Exception:
            try:
                text = response.text
            except Exception:
                text = "(Ошибка получения ответа)"

        return LLMResponse(text=text, tool_calls=tool_calls, raw=response)
