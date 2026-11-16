"""
Точка входа — запуск Джарвиса.

Режимы запуска:
  python main.py          — текстовый чат
  python main.py --voice  — голосовой режим (push-to-talk)
"""

import sys
import io

# Принудительно UTF-8 для терминала Windows — иначе кириллица вызывает UnicodeEncodeError
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import config

from tools.notes import init_db
from core.memory import JarvisMemory
from core.assistant import JarvisAssistant
from core import safety
from ui import cli


def create_llm_provider():
    """Создаёт LLM-провайдер в зависимости от настройки в .env."""
    provider = config.LLM_PROVIDER.lower()

    if provider == "cerebras":
        from llm.cerebras import CerebrasProvider
        return CerebrasProvider()

    # DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
    # if provider == "gemini":
    #     from llm.gemini import GeminiProvider
    #     return GeminiProvider()
    # elif provider == "claude":
    #     from llm.claude import ClaudeProvider
    #     return ClaudeProvider()
    # elif provider == "ollama":
    #     from llm.ollama import OllamaProvider
    #     return OllamaProvider()

    raise ValueError(
        f"Неизвестный LLM_PROVIDER: '{provider}'. "
        "Допустимые значения: cerebras, gemini, claude, ollama"
    )


def _make_cli_confirm_handler():
    """Обработчик подтверждения для текстового режима: выводит вопрос и ждёт ввода."""
    def handler(description: str, details: str = "") -> bool:
        cli.print_confirm(description, details)
        try:
            answer = input("  Подтвердить? [да/нет]: ").strip().lower()
            return answer in ("да", "д", "yes", "y", "конечно", "подтвердить", "ок", "ok")
        except (KeyboardInterrupt, EOFError):
            return False
    return handler


def _make_voice_confirm_handler(stt, tts, console):
    """
    Обработчик подтверждения для голосового режима.
    Озвучивает вопрос и слушает 'да' / 'нет'.
    """
    from rich.console import Console as RichConsole

    def handler(description: str, details: str = "") -> bool:
        # Показываем в консоли
        cli.print_confirm(description, details)

        # Озвучиваем вопрос
        question = f"Сэр, подтвердите: {description.split(chr(10))[0]}. Скажите да или нет."
        tts.speak(question)

        # Слушаем ответ
        console.print("[bold yellow]● Говорите 'да' или 'нет'...[/bold yellow]")
        audio = stt.record_auto()

        if audio is None:
            tts.speak("Подтверждения не получено. Операция отменена, сэр.")
            return False

        answer = stt.transcribe(audio).lower().strip()
        confirmed = any(w in answer for w in (
            "да", "конечно", "подтверждаю", "выполняй", "yes", "ok", "ок"
        ))

        if confirmed:
            tts.speak("Выполняю, сэр.")
        else:
            tts.speak("Отменено, сэр.")

        return confirmed

    return handler


def handle_command(command: str, assistant: JarvisAssistant) -> bool | None:
    """
    Обрабатывает специальные команды.
    Возвращает False чтобы выйти, True чтобы продолжить, None если не команда.
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
        cli.print_info(assistant.get_memory_stats())
        return True

    elif cmd in ("/voice", "/голос"):
        _start_voice_mode(assistant)
        return True

    elif cmd in ("/help", "/?", "помощь"):
        cli.print_info(
            "Доступные команды:\n"
            "  /exit     — выйти из Джарвиса\n"
            "  /clear    — очистить экран\n"
            "  /memory   — статистика памяти\n"
            "  /voice    — включить голосовой режим\n"
            "  /help     — эта справка\n\n"
            "Просто пиши сообщения на русском или английском!"
        )
        return True

    return None


def _start_voice_mode(assistant: JarvisAssistant) -> None:
    """Запускает голосовой режим."""
    try:
        from voice.voice_loop import run_voice_mode
        run_voice_mode(assistant)
    except ImportError as e:
        cli.print_error(f"Голосовые пакеты не установлены: {e}")


def _handle_connection_error(error: ConnectionError, user_input: str) -> None:
    """
    Обрабатывает ошибки подключения к LLM.
    Пытается ответить офлайн, иначе показывает понятное сообщение.
    """
    from core.offline import handle_offline, offline_help

    err = str(error)

    offline_response = handle_offline(user_input)
    if offline_response:
        cli.print_jarvis_response(offline_response)
        cli.print_info("[Ответ без LLM]")
        return

    if "CEREBRAS_UNAVAILABLE" in err:
        cli.print_error("Серверы Cerebras недоступны. Попробуй через минуту.")
    # DISABLED 2026-05: переключились на Cerebras, вернуть при необходимости
    # elif "GEMINI_QUOTA_EXHAUSTED" in err:
    #     n = err.split(":")[-1]
    #     cli.print_error(
    #         f"Все {n} ключа Gemini исчерпали дневной лимит запросов.\n"
    #         "Лимит обновляется каждый день в ~03:00 по Москве."
    #     )
    # elif "GEMINI_UNAVAILABLE" in err:
    #     cli.print_error("Серверы Gemini перегружены. Попробуй через минуту.")
    else:
        cli.print_error(f"Нет связи с LLM: {err}")

    from core.offline import offline_help
    cli.print_info(offline_help())


def main():
    voice_mode = "--voice" in sys.argv
    gui_mode = "--gui" in sys.argv

    init_db()

    try:
        llm = create_llm_provider()
    except ValueError as e:
        cli.print_error(str(e))
        sys.exit(1)
    except Exception as e:
        cli.print_error(f"Не удалось запустить LLM-провайдер ({config.LLM_PROVIDER}): {e}")
        sys.exit(1)

    memory = JarvisMemory()

    # Регистрируем обработчик подтверждений (CLI по умолчанию,
    # голосовой регистрируется позже внутри run_voice_mode)
    safety.register_confirm_handler(_make_cli_confirm_handler())

    assistant = JarvisAssistant(
        llm_provider=llm,
        memory=memory,
        on_tool_use=cli.print_tool_usage,
    )

    # GUI-режим
    if gui_mode:
        from ui.app import run_gui
        run_gui(assistant)
        return

    cli.print_welcome()
    mode_label = "ГОЛОС" if voice_mode else "ТЕКСТ"
    cli.print_info(
        f"Провайдер: {config.LLM_PROVIDER.upper()} | "
        f"Память: {'включена' if memory.is_available else 'отключена'} | "
        f"Режим: {mode_label}"
    )

    if voice_mode:
        _start_voice_mode(assistant)
        return

    # Текстовый цикл
    while True:
        try:
            user_input = cli.get_user_input()
        except (KeyboardInterrupt, EOFError):
            cli.print_system("\nДо встречи!")
            break

        if not user_input:
            continue

        result = handle_command(user_input, assistant)
        if result is False:
            break
        elif result is True:
            continue

        try:
            response = assistant.chat(user_input)
            cli.print_jarvis_response(response)
        except KeyboardInterrupt:
            cli.print_info("\nПрервано.")
        except ConnectionError as e:
            _handle_connection_error(e, user_input)
        except Exception as e:
            cli.print_error(f"Неожиданная ошибка: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
