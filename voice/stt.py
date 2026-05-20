"""
Speech-to-Text: запись голоса с микрофона и транскрипция через Whisper.
Работает полностью локально, без интернета и API-ключей.
"""

import os
import tempfile
import threading

import numpy as np

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_OK = True
except ImportError:
    _AUDIO_OK = False

try:
    from faster_whisper import WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False


class SpeechToText:
    """
    Запись с микрофона и распознавание речи через faster-whisper.
    Модель загружается один раз при первом использовании (~460 МБ).
    """

    def __init__(self, model_size: str = "small", language: str = "ru"):
        if not _AUDIO_OK:
            raise ImportError("Установи: pip install sounddevice soundfile")
        if not _WHISPER_OK:
            raise ImportError("Установи: pip install faster-whisper")

        self._model_size = model_size
        self._language = language
        self._sample_rate = 16000  # Whisper требует 16 кГц
        self._model = None         # Ленивая загрузка при первом вызове

    def _load_model(self):
        """Загружает модель Whisper (только при первом вызове)."""
        if self._model is None:
            print(f"[Whisper] Loading '{self._model_size}' model (first time, please wait)...")
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",  # Быстрее и экономит память
            )
            print("[Whisper] Model loaded.")

    def record_until_enter(self) -> np.ndarray | None:
        """
        Записывает аудио с микрофона.
        Запись идёт пока пользователь не нажмёт Enter.
        Возвращает массив float32 с аудиоданными или None если ничего не записано.
        """
        frames = []
        stop_event = threading.Event()

        def callback(indata, frames_count, time_info, status):
            if not stop_event.is_set():
                frames.append(indata.copy())

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        )

        with stream:
            input()  # Блокируем до нажатия Enter
            stop_event.set()

        if not frames:
            return None

        audio = np.concatenate(frames, axis=0).flatten()

        # Проверяем что запись не пустая (тишина)
        if np.max(np.abs(audio)) < 0.01:
            return None

        return audio

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Транскрибирует аудио в текст через Whisper.
        При первом вызове загружает модель.
        """
        self._load_model()

        # Сохраняем аудио во временный WAV-файл
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name

        try:
            sf.write(tmp_path, audio, self._sample_rate)

            segments, _ = self._model.transcribe(
                tmp_path,
                language=self._language,
                beam_size=5,
                vad_filter=True,         # Автоматически убирает тишину
                vad_parameters={"min_silence_duration_ms": 500},
            )

            text = " ".join(seg.text.strip() for seg in segments)
            return text.strip()

        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
