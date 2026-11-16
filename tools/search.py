"""
Инструмент веб-поиска через DuckDuckGo (бесплатно, без API-ключа).
Используется пакет ddgs (переименованный duckduckgo-search).
"""

import config

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


def web_search(query: str) -> str:
    """
    Ищет информацию в интернете через DuckDuckGo.

    :param query: поисковый запрос
    :return: строка с результатами для передачи в LLM
    """
    if not DDGS_AVAILABLE:
        return "Ошибка: библиотека ddgs не установлена. Запусти: pip install ddgs"

    import time as _time

    last_exc: str = ""
    for attempt in range(3):
        if attempt:
            _time.sleep(2 * attempt)   # 2s, 4s перед повторными попытками
        try:
            results = list(DDGS().text(
                query,
                max_results=config.SEARCH_MAX_RESULTS,
            ))
        except Exception as e:
            last_exc = str(e)
            continue

        if not results:
            last_exc = "No results"
            continue

        # Форматируем для LLM: только данные, без URL и встроенных инструкций
        lines = [f"[Результаты поиска по запросу: «{query}»]"]
        for r in results:
            title = r.get("title", "").strip()
            body  = r.get("body",  "").strip()
            if body:
                lines.append(f"• {title}: {body}")

        return "\n".join(lines)

    return f"Ошибка при поиске: {last_exc}. Возможно, нет подключения к интернету."
