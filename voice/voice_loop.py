"""
Голосовой цикл Джарвиса.
Управляет последовательностью: запись → распознавание → ответ → озвучка.
"""

from rich.console import Console

from core.assistant import JarvisAssistant
from voice.stt import SpeechToText
from voice.tts import TextToSpeech
from ui import cli

console = Console()

# Фразы-команды для выхода из голосового режима
EXIT_PHRASES = {"выход", "пока", "выключись", "стоп", "до свидания", "exit", "quit"}


def run_voice_mode(assistant: JarvisAssistant) -> None:
    """
    Запускает голосовой режим.
    Push-to-talk: Enter → говори → Enter → ответ.
    """
    try:
        stt = SpeechToText(model_size="small", language="ru")
        tts = TextToSpeech()
    except ImportError as e:
        cli.print_error(f"Голосовые пакеты не установлены: {e}")
        return

    cli.print_system("Голосовой режим активирован")
    cli.print_info(
        "Нажми Enter → говори → нажми Enter снова чтобы остановить запись.\n"
        "Скажи 'выход' или 'пока' чтобы вернуться в текстовый режим."
    )

    # Приветствие
    greeting = "Джарвис на связи. Говори, я слушаю."
    cli.print_jarvis_response(greeting)
    tts.speak(greeting)

    while True:
        try:
            # Ждём первого Enter (начало записи)
            console.print(
                "\n[dim]Нажми [bold green]Enter[/bold green] чтобы начать говорить...[/dim]",
                end="",
            )
            input()

            # Показываем индикатор записи
            console.print("[bold red]● Запись...[/bold red] (нажми [bold]Enter[/bold] чтобы остановить)")

            audio = stt.record_until_enter()

            if audio is None:
                console.print("[dim]Ничего не услышал, попробуй ещё раз.[/dim]")
                continue

            # Транскрипция
            console.print("[dim]Распознаю речь...[/dim]")
            text = stt.transcribe(audio)

            if not text:
                console.print("[dim]Не смог распознать речь, попробуй ещё раз.[/dim]")
                continue

            # Показываем что распознали
            console.print(f"\n[bold blue]Ты:[/bold blue] {text}\n")

            # Проверяем команду выхода
            if any(phrase in text.lower() for phrase in EXIT_PHRASES):
                farewell = "До встречи, Влад!"
                cli.print_jarvis_response(farewell)
                tts.speak(farewell)
                cli.print_system("Голосовой режим отключён.")
                break

            # Получаем ответ Джарвиса
            try:
                response = assistant.chat(text)
                cli.print_jarvis_response(response)
                tts.speak(response)

            except ConnectionError as e:
                msg = "Сейчас не могу подключиться к серверу. Попробуй позже."
                cli.print_error(str(e))
                tts.speak(msg)

            except Exception as e:
                cli.print_error(f"Ошибка: {e}")
                tts.speak("Что-то пошло не так.")

        except KeyboardInterrupt:
            farewell = "Пока!"
            tts.speak(farewell)
            cli.print_system("\nГолосовой режим отключён.")
            break
