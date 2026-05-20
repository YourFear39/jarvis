"""
Точка входа — запуск Джарвиса.
"""

import sys
import config

from tools.notes import init_db
from core.memory import JarvisMemory
from core.assistant import JarvisAssistant
from ui import cli


def create_llm_provider():
    """Создаёт LLM-провайдер в зависимости от настройки в .env."""
    provider = config.LLM_PROVIDER.lower()

    if provider == "gemini":
        from llm.gemini import GeminiProvider
        return GeminiProvider()
    elif provider == "claude":
        from llm.claude import ClaudeProvider
        return ClaudeProvider()
    elif provider == "ollama":
        from llm.ollama import OllamaProvider
        return OllamaProvider()
    else:
        raise ValueError(
            f"Неизвестный LLM_PROVIDER: '{provider}'. "
            "Допустимые значения: gemini, claude, ollama"
        )


def handle_command(command: str, assistant: JarvisAssistant) -> bool:
    """
    Обрабатывает специальные команды (/exit, /clear, /memory).
    Возвращает True если нужно продолжать, False если выйти.
    """
    cmd = command.lower().strip()

    if cmd in ("/exit", "/quit", "/q", "выход", "exit", "quit"):
        cli.print_system("До встречи! Джарвис отключается.")
        return False

    elif cmd in ("/clear", "/cls"):
        import os
        os.system("cls" if sys.platform == "win32" else "clear")
        cli.print_welcome()
        return True

    elif cmd in ("/memory", "/mem", "/remember"):
        stats = assistant.get_memory_stats()
        cli.print_info(stats)
        return True

    elif cmd in ("/help", "/?", "помощь"):
        cli.print_info(
            "Доступные команды:\n"
            "  /exit     — выйти из Джарвиса\n"
            "  /clear    — очистить экран\n"
            "  /memory   — показать статистику памяти\n"
            "  /help     — эта справка\n\n"
            "Просто пиши сообщения на русском или английском!"
        )
        return True

    return None  # Не команда — обрабатывать как обычное сообщение


def main():
    # Инициализация БД
    init_db()

    # Создаём компоненты
    try:
        llm = create_llm_provider()
    except ValueError as e:
        cli.print_error(str(e))
        sys.exit(1)
    except Exception as e:
        cli.print_error(f"Не удалось запустить LLM-провайдер ({config.LLM_PROVIDER}): {e}")
        sys.exit(1)

    memory = JarvisMemory()
    assistant = JarvisAssistant(
        llm_provider=llm,
        memory=memory,
        on_tool_use=cli.print_tool_usage,
    )

    # Приветствие
    cli.print_welcome()
    cli.print_info(f"Провайдер: {config.LLM_PROVIDER.upper()} | Память: {'включена' if memory.is_available else 'отключена'}")

    # Главный цикл
    while True:
        try:
            user_input = cli.get_user_input()
        except (KeyboardInterrupt, EOFError):
            cli.print_system("\nДо встречи!")
            break

        if not user_input:
            continue

        # Проверяем команды
        result = handle_command(user_input, assistant)
        if result is False:
            break
        elif result is True:
            continue

        # Обычное сообщение — отправляем Джарвису
        try:
            response = assistant.chat(user_input)
            cli.print_jarvis_response(response)
        except KeyboardInterrupt:
            cli.print_info("\nПрервано.")
        except ConnectionError as e:
            cli.print_error(f"Ошибка сети: {e}")
        except Exception as e:
            cli.print_error(f"Неожиданная ошибка: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
