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

    try:
        results = list(DDGS().text(
            query,
            max_results=config.SEARCH_MAX_RESULTS,
        ))

        if not results:
            return f"По запросу '{query}' ничего не найдено в интернете."

        # Форматируем результаты в читаемый текст для LLM
        lines = [f"Результаты поиска по запросу: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'Без названия')}")
            lines.append(f"   {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')}\n")

        return "\n".join(lines)

    except Exception as e:
        return f"Ошибка при поиске: {str(e)}. Возможно, нет подключения к интернету."
