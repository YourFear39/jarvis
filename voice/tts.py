"""
Text-to-Speech: озвучка ответов Джарвиса через Microsoft Edge TTS.
Использует нейросетевые голоса Microsoft — бесплатно, без API-ключей.
Для воспроизведения использует playsound (встроенный Windows Media).
"""

import asyncio
import os
import re
import tempfile

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


# Лучший мужской голос на русском (нейросеть Microsoft)
VOICE_RU_MALE = "ru-RU-DmitryNeural"
VOICE_RU_FEMALE = "ru-RU-SvetlanaNeural"


class TextToSpeech:
    """Озвучка текста через edge-tts с воспроизведением через playsound."""

    def __init__(self, voice: str = VOICE_RU_MALE):
        if not _EDGE_OK:
            raise ImportError("Установи: pip install edge-tts")
        if not _PLAYSOUND_OK:
            raise ImportError("Установи: pip install playsound==1.2.2")

        self._voice = voice

    def speak(self, text: str) -> None:
        """Произносит текст вслух. Блокирует до конца воспроизведения."""
        cleaned = self._strip_markdown(text)
        if not cleaned.strip():
            return

        try:
            asyncio.run(self._speak_async(cleaned))
        except Exception as e:
            print(f"[TTS] Error: {e}")

    async def _speak_async(self, text: str) -> None:
        communicate = edge_tts.Communicate(text, self._voice)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        try:
            await communicate.save(tmp_path)
            playsound(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Убирает Markdown-разметку чтобы текст звучал естественно."""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **жирный**
        text = re.sub(r'\*(.+?)\*', r'\1', text)         # *курсив*
        text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)   # `код`
        text = re.sub(r'#{1,6}\s+', '', text)             # # Заголовки
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)  # [ссылка](url)
        text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  # - пункты
        text = re.sub(r'\n{2,}', '. ', text)             # Двойные переносы → пауза
        return text.strip()
