"""
Groq API — быстрый бесплатный LLM для структурирования результатов поиска.

Используется ТОЛЬКО в Level 2 (информационные запросы):
  web_search → сырые результаты → GroqSynthesizer → красивый ответ

При недоступности Groq (нет ключа, ошибка сети, лимит) — возвращает
аккуратно отформатированные сырые результаты без исключений.
"""

from __future__ import annotations

import config

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False


class GroqSynthesizer:
    """
    Превращает сырые результаты DuckDuckGo в связный ответ в стиле JARVIS.
    Stateless — можно создавать на каждый вызов.
    """

    _API_URL = "https://api.groq.com/openai/v1/chat/completions"
    _MODEL   = "llama-3.3-70b-versatile"

    def synthesize(self, query: str, search_results: str, context: str = "") -> str:
        """
        Структурирует результаты поиска в ответ JARVIS.
        context — последние сообщения разговора для разрешения местоимений.
        При любой ошибке возвращает форматированные сырые данные.
        """
        if not config.GROQ_API_KEY or not _REQUESTS_OK:
            print("[Groq] Ключ не задан или requests недоступен — сырые результаты")
            return self._format_raw(search_results)

        context_block = f"Контекст разговора:\n{context}\n\n" if context else ""
        prompt = (
            "Ты — JARVIS, интеллектуальный ИИ-ассистент Тони Старка. "
            "Отвечай на русском языке, умно и по делу. "
            "Никаких вступлений вроде «Конечно!», «Отличный вопрос» или «Согласно поиску».\n\n"
            f"{context_block}"
            f"Вопрос пользователя: «{query}»\n\n"
            f"Результаты поиска:\n{search_results}\n\n"
            "Инструкция: ответь на вопрос пользователя, используя результаты поиска как опору. "
            "Если в результатах есть конкретные данные (температура, цены, даты, имена) — обязательно приведи их. "
            "Если результаты поиска нерелевантны или не содержат ответа — всё равно дай ответ из собственных знаний. "
            "ЗАПРЕЩЕНО говорить: «результаты не содержат ответа», «к сожалению», «нет информации», «не могу ответить». "
            "Длина ответа: 1-4 предложения. Можешь обращаться «сэр»."
        )

        import time as _time
        for attempt in range(2):
            try:
                resp = _requests.post(
                    self._API_URL,
                    headers={
                        "Authorization": f"Bearer {config.GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 512,
                        "temperature": 0.3,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()

            except _requests.exceptions.HTTPError as e:
                if resp.status_code == 429 and attempt == 0:
                    print("[Groq] Rate limit 429 — жду 8с и повторяю")
                    _time.sleep(8)
                    continue
                print(f"[Groq] HTTP ошибка: {e} — показываю сырые результаты")
                return self._format_raw(search_results)
            except Exception as e:
                print(f"[Groq] Ошибка: {e} — показываю сырые результаты")
                return self._format_raw(search_results)

        return self._format_raw(search_results)

    @staticmethod
    def _format_raw(search_results: str) -> str:
        """Форматирует сырые результаты поиска когда Groq недоступен."""
        lines = []
        for line in search_results.splitlines():
            stripped = line.strip()
            # Пропускаем служебные строки из tools/search.py
            if not stripped or stripped.startswith("["):
                continue
            if stripped.startswith("•"):
                content = stripped[1:].strip()
                if content:
                    # Обрезаем каждый сниппет чтобы не раздувать ответ
                    lines.append(content[:220] + ("…" if len(content) > 220 else ""))

        if not lines:
            return search_results[:1200]

        header = "Нашёл следующее, сэр:\n\n"
        return header + "\n\n".join(lines[:3])
