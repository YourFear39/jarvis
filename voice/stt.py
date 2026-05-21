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

    def record_auto(
        self,
        silence_sec: float = 1.4,
        max_sec: float = 30.0,
    ) -> np.ndarray | None:
        """
        Записывает аудио и автоматически останавливается после тишины.
        Ждёт начала речи до 5 секунд; если молчание — возвращает None.

        silence_sec  — сколько секунд тишины считается концом фразы
        max_sec      — максимальная длина записи
        """
        CHUNK_SEC = 0.05           # 50 мс чанки
        CHUNK_SIZE = int(self._sample_rate * CHUNK_SEC)
        THRESHOLD = 0.018          # RMS ниже этого = тишина
        SILENCE_LIMIT = int(silence_sec / CHUNK_SEC)
        WAIT_LIMIT = int(5.0 / CHUNK_SEC)   # ждём начала речи не дольше 5 с
        MAX_CHUNKS = int(max_sec / CHUNK_SEC)

        frames: list[np.ndarray] = []
        speech_chunks = 0
        silence_count = 0
        done = threading.Event()

        def _cb(indata, n, t, status):
            nonlocal speech_chunks, silence_count
            frames.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))

            if rms > THRESHOLD:
                speech_chunks += 1
                silence_count = 0
            else:
                if speech_chunks > 0:
                    silence_count += 1
                    if silence_count >= SILENCE_LIMIT:
                        done.set()
                elif len(frames) >= WAIT_LIMIT:
                    done.set()   # Так и не начал говорить

            if len(frames) >= MAX_CHUNKS:
                done.set()

        with sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=_cb,
            blocksize=CHUNK_SIZE,
        ):
            done.wait(timeout=max_sec + 6)

        if not frames or speech_chunks < 3:   # < ~150 мс реальной речи
            return None

        return np.concatenate(frames, axis=0).flatten()

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
