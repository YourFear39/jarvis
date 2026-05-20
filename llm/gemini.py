"""
Провайдер Google Gemini.
Использует актуальный пакет google-genai (не устаревший google-generativeai).
Поддерживает несколько API-ключей: при исчерпании квоты переключается на следующий.
"""

import re
import time

from google import genai
from google.genai import types

import config
from llm.base import BaseLLMProvider, LLMResponse, Message, ToolCall


class GeminiProvider(BaseLLMProvider):
    """Провайдер Google Gemini с поддержкой function calling и ротации ключей."""

    def __init__(self):
        super().__init__()

        if not config.GEMINI_API_KEYS:
            raise ValueError(
                "GEMINI_API_KEYS не задан. Добавь ключ(и) в файл .env"
            )

        # Список всех ключей и текущий индекс
        self._api_keys = config.GEMINI_API_KEYS
        self._key_index = 0
        self._client = genai.Client(api_key=self._current_key)

        self._model_name = config.GEMINI_MODEL
        self._gemini_tools: list = []

    @property
    def _current_key(self) -> str:
        return self._api_keys[self._key_index]

    def _switch_key(self) -> bool:
        """
        Переключается на следующий ключ.
        Возвращает True если переключение удалось, False если ключи кончились.
        """
        next_index = self._key_index + 1
        if next_index >= len(self._api_keys):
            return False

        self._key_index = next_index
        self._client = genai.Client(api_key=self._current_key)
        print(f"\n  [Gemini] switching to key #{self._key_index + 1} of {len(self._api_keys)}")
        return True

    def register_tools(self, tools: list[dict]) -> None:
        """Конвертирует универсальные инструменты в формат Gemini."""
        declarations = []

        for tool in tools:
            params = tool["parameters"]

            gemini_props = {}
            for param_name, param_info in params.get("properties", {}).items():
                type_str = param_info.get("type", "string").upper()
                type_map = {
                    "STRING": "STRING", "INTEGER": "INTEGER",
                    "NUMBER": "NUMBER", "BOOLEAN": "BOOLEAN",
                    "ARRAY": "ARRAY", "OBJECT": "OBJECT",
                }
                gemini_props[param_name] = types.Schema(
                    type=type_map.get(type_str, "STRING"),
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

        contents.append(types.Content(
            role="model",
            parts=[types.Part(
                function_call=types.FunctionCall(
                    name=tool_call.name,
                    args=tool_call.arguments,
                )
            )],
        ))

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
        При исчерпании квоты на текущем ключе — переключается на следующий.
        При временной перегрузке — ждёт и повторяет.
        """
        cfg = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=self._gemini_tools if self._gemini_tools else None,
        )

        # Внешний цикл: перебор ключей
        while True:
            # Внутренний цикл: retry при временных ошибках (503, краткий 429)
            for attempt in range(3):
                try:
                    return self._client.models.generate_content(
                        model=self._model_name,
                        contents=contents,
                        config=cfg,
                    )
                except Exception as e:
                    err = str(e)
                    is_quota = "429" in err or "resource_exhausted" in err.lower()
                    is_unavailable = "503" in err or "unavailable" in err.lower()

                    if is_unavailable:
                        if attempt < 2:
                            wait = 15 * (attempt + 1)
                            print(f"\n  [Gemini] 503, retrying in {wait}s...")
                            time.sleep(wait)
                            continue
                        raise ConnectionError("GEMINI_UNAVAILABLE") from e

                    if is_quota:
                        # Проверяем: это per-minute лимит (есть retryDelay) или дневной (limit: 0)?
                        has_retry_delay = bool(re.search(r'"retryDelay"', err))
                        match = re.search(r'retry[^\d]*(\d+)', err, re.IGNORECASE)
                        wait = int(match.group(1)) + 2 if match else 0

                        if has_retry_delay and wait <= 120 and attempt == 0:
                            print(f"\n  [Gemini] rate limit, waiting {wait}s...")
                            time.sleep(wait)
                            continue

                        # Дневной лимит этого ключа исчерпан — пробуем следующий
                        if self._switch_key():
                            cfg = types.GenerateContentConfig(
                                system_instruction=system_prompt,
                                tools=self._gemini_tools if self._gemini_tools else None,
                            )
                            break  # Выходим из внутреннего цикла → внешний попробует новый ключ

                        # Все ключи исчерпаны
                        raise ConnectionError(
                            f"GEMINI_QUOTA_EXHAUSTED:{len(self._api_keys)}"
                        ) from e

                    raise  # Любая другая ошибка — пробрасываем
            else:
                continue  # Внутренний цикл завершился нормально → выходим из while

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
