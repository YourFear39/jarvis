"""
Провайдер Google Gemini.
Использует актуальный пакет google-genai (не устаревший google-generativeai).
"""

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
            return self._parse_response(response)
        except Exception as e:
            err = str(e)
            # Модель не найдена → пробуем запасную
            if "not found" in err.lower() or "404" in err:
                self._model_name = config.GEMINI_MODEL_FALLBACK
                response = self._generate(system_prompt, contents)
                return self._parse_response(response)
            # Временная перегрузка сервера
            if "503" in err or "unavailable" in err.lower() or "429" in err:
                raise ConnectionError(
                    "Серверы Gemini сейчас перегружены. Попробуй ещё раз через несколько секунд."
                ) from e
            raise

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

        try:
            response = self._generate(system_prompt, contents)
        except Exception as e:
            err = str(e)
            if "503" in err or "unavailable" in err.lower() or "429" in err or "resource_exhausted" in err.lower():
                raise ConnectionError(
                    "Серверы Gemini перегружены или исчерпан дневной лимит запросов. "
                    "Попробуй через несколько секунд."
                ) from e
            raise
        return self._parse_response(response)

    def _generate(self, system_prompt: str, contents: list):
        """Отправляет запрос к Gemini API."""
        config_kwargs = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=self._gemini_tools if self._gemini_tools else None,
        )

        return self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=config_kwargs,
        )

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
