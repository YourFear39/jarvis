"""
Голосовой цикл Джарвиса.
Управляет последовательностью: запись → распознавание → ответ → озвучка.
"""

import random
import re
import threading
import time

from rich.console import Console

import config
from core.logger import get_logger

log = get_logger("voice")
from core import safety
from core.assistant import JarvisAssistant
from voice.stt import SpeechToText
from voice.tts import create_tts
from ui import cli

console = Console()

EXIT_PHRASES = {"выход", "пока", "выключись", "стоп", "до свидания", "exit", "quit"}

# Символы-разделители pseudo-графики в local_handler ответах
_RE_STRIP_IDS    = re.compile(r'\[\d+\]\s*')         # [37], [12]
_RE_STRIP_PSEUDO = re.compile(r'[─━═┼│┤├┬┴┐└┘┌╗╔╝╚╠╣╦╩╬─]+')  # псевдографика
_RE_STRIP_EMOJI  = re.compile(
    "[\U00010000-\U0010FFFF"   # supplementary planes (emoji)
    "\U00002600-\U000027BF"    # misc symbols
    "\U0001F300-\U0001F9FF"    # emoji block
    "\U00002702-\U000027B0"
    "]+",
    re.UNICODE,
)
_RE_MULTI_SPACE  = re.compile(r'[ \t]{2,}')
_RE_MULTI_NL     = re.compile(r'\n{3,}')


def _tts_clean(text: str) -> str:
    """Убирает из текста элементы форматирования которые плохо звучат вслух.
    📝 [37] → "", ── РАЗДЕЛ ── → "", приоритетные иконки → "".
    """
    text = _RE_STRIP_EMOJI.sub("", text)
    text = _RE_STRIP_IDS.sub("", text)
    text = _RE_STRIP_PSEUDO.sub("", text)
    text = _RE_MULTI_SPACE.sub(" ", text)
    text = _RE_MULTI_NL.sub("\n\n", text)
    return text.strip()

# Фразы-заглушки пока Джарвис "думает" (выбираются случайно)
_THINKING_PHRASES = [
    "Секунду...",
    "Гляну...",
    "Момент...",
    "Сейчас...",
    "Так...",
    "Щас гляну...",
    "Одну секунду...",
    "Минутку...",
]

# Вариативные приветствия и прощания
_GREETINGS = [
    f"На связи, {config.JARVIS_USER_NAME}.",
    f"Слушаю тебя, {config.JARVIS_USER_NAME}.",
    f"Готов, {config.JARVIS_USER_NAME}.",
    f"Джарвис на связи. Говори.",
]

_FAREWELLS = [
    f"До встречи, {config.JARVIS_USER_NAME}.",
    "Пока.",
    "Отключаюсь.",
    "Хорошо. Буду здесь.",
    f"Удачи, {config.JARVIS_USER_NAME}.",
]


class _ThinkingTimer:
    """
    Проигрывает короткую фразу-реакцию если ответ занимает дольше порогового времени.
    Устраняет мёртвую тишину при долгом запросе к LLM.

    Lock гарантирует строгую последовательность: thinking-фраза всегда заканчивается
    ДО начала основного ответа, независимо от порядка потоков.
    """

    def __init__(self, tts, delay: float = 1.2):
        self._tts = tts
        self._delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()   # Сериализует TTS-вызовы между потоками
        self._cancelled = False

    def start(self) -> None:
        self._cancelled = False
        self._timer = threading.Timer(self._delay, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        """Запрещает будущее срабатывание (не прерывает уже начавшуюся речь)."""
        self._cancelled = True
        if self._timer:
            self._timer.cancel()

    def speak(self, text: str) -> None:
        """
        Произносит ответ. Блокируется если thinking-фраза ещё звучит.
        Вызывать из главного потока вместо tts.speak(response).
        """
        clean = _tts_clean(text)
        log.debug("ThinkingTimer.speak: %r", clean[:50])
        with self._lock:
            self._tts.speak(clean)

    def _fire(self) -> None:
        """Срабатывает из потока таймера — говорит thinking-фразу под Lock."""
        with self._lock:
            # Повторная проверка после захвата Lock: за время ожидания могли отменить
            if self._cancelled:
                return
            phrase = random.choice(_THINKING_PHRASES)
            log.debug("ThinkingTimer fired: %r", phrase)
            self._tts.speak(phrase)


def run_voice_mode(assistant: JarvisAssistant) -> None:
    """
    Запускает голосовой режим.
    Enter → говори → тишина 1.4с → автостоп → ответ.
    """
    try:
        stt = SpeechToText(model_size=config.WHISPER_MODEL_SIZE, language="ru")
        tts = create_tts()
    except ImportError as e:
        cli.print_error(f"Голосовые пакеты не установлены: {e}")
        return

    # Регистрируем голосовой обработчик подтверждений для опасных операций
    def _voice_confirm(description: str, details: str = "") -> bool:
        cli.print_confirm(description, details)
        question = f"Сэр, подтвердите: {description.split(chr(10))[0]}. Скажите да или нет."
        tts.speak(question)
        console.print("[bold yellow]● Говорите 'да' или 'нет'...[/bold yellow]")
        audio = stt.record_auto()
        if audio is None:
            tts.speak("Подтверждения не получено. Операция отменена, сэр.")
            return False
        answer = stt.transcribe(audio).lower().strip()
        confirmed = any(w in answer for w in (
            "да", "конечно", "подтверждаю", "выполняй", "yes", "ok", "ок"
        ))
        tts.speak("Выполняю, сэр." if confirmed else "Отменено, сэр.")
        return confirmed

    safety.register_confirm_handler(_voice_confirm)

    cli.print_system("Голосовой режим активирован")
    cli.print_info(
        "Нажми Enter → говори → остановись (тишина = конец записи).\n"
        "Скажи 'выход' или 'пока' чтобы вернуться в текстовый режим."
    )

    greeting = random.choice(_GREETINGS)
    cli.print_jarvis_response(greeting)
    tts.speak(greeting)

    while True:
        try:
            console.print(
                "\n[dim]Нажми [bold green]Enter[/bold green] чтобы начать говорить...[/dim]",
                end="",
            )
            input()

            console.print("[bold red]● Слушаю...[/bold red] (тишина = конец)")
            t_record = time.perf_counter()
            audio = stt.record_auto()
            log.debug("record: %.2fs", time.perf_counter() - t_record)

            if audio is None:
                console.print("[dim]Ничего не услышал, попробуй ещё раз.[/dim]")
                continue

            console.print("[dim]Распознаю речь...[/dim]")
            t_stt = time.perf_counter()
            text = stt.transcribe(audio)
            log.debug("stt: %.2fs → %r", time.perf_counter() - t_stt, text[:60])

            if not text:
                console.print("[dim]Не смог распознать речь, попробуй ещё раз.[/dim]")
                continue

            console.print(f"\n[bold blue]Ты:[/bold blue] {text}\n")

            if any(phrase in text.lower() for phrase in EXIT_PHRASES):
                farewell = random.choice(_FAREWELLS)
                cli.print_jarvis_response(farewell)
                tts.speak(farewell)
                cli.print_system("Голосовой режим отключён.")
                break

            thinking = _ThinkingTimer(tts, delay=1.2)
            try:
                # Запускаем таймер: если ответ идёт дольше 1.2с — звучит короткая реакция
                thinking.start()
                t_llm = time.perf_counter()
                try:
                    response = assistant.chat(text)
                finally:
                    thinking.cancel()
                log.info("cycle: stt=%.2fs llm=%.2fs text=%r", time.perf_counter() - t_stt, time.perf_counter() - t_llm, text[:40])

                cli.print_jarvis_response(response)
                thinking.speak(response)  # Lock гарантирует: после thinking-фразы, не параллельно

            except ConnectionError as e:
                from core.offline import handle_offline, offline_help
                offline_response = handle_offline(text)
                if offline_response:
                    cli.print_jarvis_response(offline_response)
                    cli.print_info("[Ответ без LLM]")
                    thinking.speak(offline_response)
                else:
                    err = str(e)
                    if "GEMINI_QUOTA_EXHAUSTED" in err:
                        msg = "Все ключи Gemini исчерпали лимит. Работаю в офлайн-режиме."
                    elif "GEMINI_UNAVAILABLE" in err:
                        msg = "Серверы Gemini перегружены. Попробуй через минуту."
                    else:
                        msg = "Нет связи с сервером. Работаю в офлайн-режиме."
                    cli.print_info(offline_help())
                    thinking.speak(msg)

            except Exception as e:
                cli.print_error(f"{type(e).__name__}: {e}")
                thinking.speak("Что-то пошло не так.")

        except KeyboardInterrupt:
            tts.speak("Пока!")
            cli.print_system("\nГолосовой режим отключён.")
            break
