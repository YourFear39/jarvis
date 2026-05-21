"""
Text-to-Speech: озвучка ответов Джарвиса через Microsoft Edge TTS.

Улучшения по сравнению с v1:
- Персистентный asyncio event loop — нет ~100ms оверхеда на asyncio.run()
- Пайплайн: пока играет предложение N, уже генерируется предложение N+1
- Комплексная очистка текста — нет "домик звёздочка" и прочего мусора
"""

import asyncio
import os
import re
import tempfile
import threading

try:
    import edge_tts
    _EDGE_OK = True
except ImportError:
    _EDGE_OK = False

try:
    from playsound import playsound
    _PLAYSOUND_OK = True
except ImportError:
    _PLAYSOUND_OK = False


VOICE_RU_MALE   = "ru-RU-DmitryNeural"
VOICE_RU_FEMALE = "ru-RU-SvetlanaNeural"


class TextToSpeech:
    """
    Озвучка текста через edge-tts с воспроизведением через playsound.
    Использует пайплайн: генерация предложения N+1 идёт параллельно воспроизведению N.
    """

    def __init__(self, voice: str = VOICE_RU_MALE):
        if not _EDGE_OK:
            raise ImportError("Установи: pip install edge-tts")
        if not _PLAYSOUND_OK:
            raise ImportError("Установи: pip install playsound==1.2.2")

        self._voice = voice

        # Персистентный event loop в отдельном потоке.
        # asyncio.run() создаёт/разрушает loop при каждом вызове — это ~100ms.
        # Один долгоживущий loop убирает этот оверхед полностью.
        self._loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="tts-loop",
        ).start()

    def speak(self, text: str) -> None:
        """Произносит текст. Блокирует до конца воспроизведения."""
        cleaned = clean_for_tts(text)
        if not cleaned.strip():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._pipeline(cleaned), self._loop
            )
            future.result(timeout=60)
        except Exception as e:
            print(f"[TTS] {e}")

    # ------------------------------------------------------------------ async pipeline

    async def _pipeline(self, text: str) -> None:
        """
        Пайплайн: генерируем аудио предложения N+1
        пока воспроизводится предложение N.
        """
        loop = asyncio.get_event_loop()
        sentences = split_sentences(text)

        if not sentences:
            return

        # Генерируем первое предложение
        current_path = await self._gen(sentences[0])

        for i in range(len(sentences)):
            # Запускаем генерацию следующего предложения фоново
            next_task = None
            if i + 1 < len(sentences):
                next_task = asyncio.create_task(self._gen(sentences[i + 1]))

            # Воспроизводим текущее предложение (в threadpool, не блокирует loop)
            await loop.run_in_executor(None, _play, current_path)

            # Берём следующее (к этому моменту уже готово или почти готово)
            if next_task is not None:
                current_path = await next_task

    async def _gen(self, text: str) -> str:
        """Генерирует MP3 и возвращает путь к temp-файлу."""
        communicate = edge_tts.Communicate(text, self._voice)
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        await communicate.save(tmp_path)
        return tmp_path


# ---------------------------------------------------------------------------
# Вспомогательные функции (вынесены — используются и в GUI)
# ---------------------------------------------------------------------------

def _play(path: str) -> None:
    """Воспроизводит MP3 и удаляет temp-файл."""
    try:
        playsound(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def split_sentences(text: str) -> list[str]:
    """
    Разбивает текст на фрагменты для пайплайна.
    Короткие части объединяет чтобы edge-tts не делал запрос на 3 слова.
    """
    # Режем по концу предложения
    raw = re.split(r'(?<=[.!?])\s+', text)

    result: list[str] = []
    buf = ""
    for part in raw:
        buf = (buf + " " + part).strip() if buf else part
        if len(buf) >= 70:      # Минимальный фрагмент ~70 символов
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)

    return result or [text]


def clean_for_tts(text: str) -> str:
    """
    Очищает текст от всего что TTS читает плохо:
    markdown, символы интерфейса, URL, пути, хеши, эмодзи-буллеты.
    """
    # Символы и метки интерфейса Джарвиса
    text = re.sub(r'[◈▷▶◄►●⟳⚙◦■□▪▫─═]', '', text)
    # Временны́е метки GUI вида [15:30]
    text = re.sub(r'\[\d{1,2}:\d{2}\]', '', text)
    # Метки типа "JARVIS" в начале строк от GUI (не нужны вслух)
    text = re.sub(r'^JARVIS\s*', '', text, flags=re.MULTILINE)

    # Блоки кода (несколько строк)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Инлайн код
    text = re.sub(r'`[^`\n]+`', '', text)

    # Markdown-форматирование — убираем теги, оставляем текст
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)  # **жирный** / *курсив*
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)    # __текст__
    text = re.sub(r'#{1,6}\s+', '', text)                     # # Заголовок
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)    # [текст](url)

    # URL
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # Строки-разделители типа ── ЗАГОЛОВОК ──
    text = re.sub(r'^[─═\-]{2,}.*$', '', text, flags=re.MULTILINE)

    # Буллеты и нумерованные списки
    text = re.sub(r'^\s*[-*+•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+[.)]\s+', '', text, flags=re.MULTILINE)

    # Пути Windows (C:\...) — длинные технические строки не нужны вслух
    text = re.sub(r'[A-Za-z]:\\[^\s,;]+', '', text)

    # Хеши и ID (a3f9b2... и т.п.)
    text = re.sub(r'\b[a-f0-9]{8,}\b', '', text)

    # Переводы строк → паузы
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\n', ', ', text)

    # Двойные пробелы и "плавающие" знаки препинания
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    text = re.sub(r'[,\s]{2,}', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)

    return text.strip()
