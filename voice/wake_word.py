"""
Wake-word детектор — постоянно слушает микрофон и реагирует на «Джарвис».
Использует отдельную tiny-модель Whisper — не конкурирует с основным STT.
"""

import threading
import time
from typing import Any

import numpy as np

try:
    import sounddevice as sd
    _AUDIO_OK = True
except ImportError:
    _AUDIO_OK = False

try:
    from faster_whisper import WhisperModel as _WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False

WAKE_WORDS = {
    "джарвис", "jarvis",
    "джарвиc",   # Latin c instead of Cyrillic с
    "жарвис",
    "дарвис",
    "джарвист",
    "джарвисе",
    "джервис",
    "ярвис",     # without д
    "харвис",
    "jarvis",
    "жарвас",
    "джарвиз",
    "джарвеc",
}

# Подсказка для tiny-модели — сильно улучшает распознавание wake-word
_WAKE_PROMPT = "Джарвис."


class WakeWordDetector:
    """
    Фоновый детектор wake-word.
    Пишет 1.5-секундные чанки с 50% перекрытием (каждый следующий чанк
    препендит половину предыдущего), чтобы «Джарвис» не терялся на границе.
    Использует ОТДЕЛЬНУЮ tiny-модель — не блокирует основной STT.
    """

    SAMPLE_RATE  = 16000
    CHUNK_SEC    = 1.5      # длина нового чанка
    OVERLAP_SEC  = 1.0      # сколько предыдущего аудио добавляем спереди
    RMS_THRESH   = 0.003    # ниже → тишина, пропускаем (было 0.006)

    def __init__(self, stt, on_wake):
        if not _AUDIO_OK:
            raise ImportError("Установи: pip install sounddevice")
        self._stt     = stt        # нужен только для _get_input_device()
        self._on_wake = on_wake
        self._running = False
        self._paused  = False
        self._thread: threading.Thread | None = None
        self._wake_model = None    # отдельная tiny-модель, независимо от основного STT

    # ------------------------------------------------------------------ ctrl

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="wake-word"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def pause(self):
        """Приостановить пока идёт основная запись."""
        self._paused = True

    def resume(self):
        self._paused = False

    # ------------------------------------------------------------------ loop

    def _loop(self):
        chunk_size   = int(self.SAMPLE_RATE * self.CHUNK_SEC)
        overlap_size = int(self.SAMPLE_RATE * self.OVERLAP_SEC)
        prev_audio   = np.zeros(0, dtype=np.float32)

        while self._running:
            if self._paused:
                prev_audio = np.zeros(0, dtype=np.float32)  # сбрасываем буфер при паузе
                time.sleep(0.1)
                continue

            # Записываем очередной чанк через InputStream — не зависает при смене устройства
            try:
                from voice.stt import _get_input_device
                mic = _get_input_device()
                buf: list[np.ndarray] = []
                buf_done = threading.Event()
                buf_total = 0

                def _chunk_cb(indata, frames_count, time_info, status):
                    nonlocal buf_total
                    if status:
                        buf_done.set()
                        return
                    buf.append(indata.copy())
                    buf_total += frames_count
                    if buf_total >= chunk_size:
                        buf_done.set()

                with sd.InputStream(
                    device=mic,
                    samplerate=self.SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=_chunk_cb,
                ):
                    buf_done.wait(timeout=self.CHUNK_SEC * 2 + 1.0)

                if not buf:
                    time.sleep(0.5)
                    continue
                raw = np.concatenate(buf, axis=0)[:chunk_size]
            except Exception:
                time.sleep(1.0)
                continue

            if self._paused:
                prev_audio = np.zeros(0, dtype=np.float32)
                continue

            chunk = raw.flatten()

            # Проверяем уровень только нового чанка
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms < self.RMS_THRESH:
                prev_audio = chunk[-overlap_size:] if len(chunk) >= overlap_size else chunk
                continue

            # Создаём окно с перекрытием: [хвост предыдущего] + [новый чанк]
            if len(prev_audio) > 0:
                window = np.concatenate([prev_audio[-overlap_size:], chunk])
            else:
                window = chunk

            # Сохраняем хвост для следующей итерации
            prev_audio = chunk[-overlap_size:] if len(chunk) >= overlap_size else chunk

            text = self._quick_transcribe(window)
            if not text:
                continue

            text_low = text.lower().strip()
            print(f"[Wake] слышу: «{text_low}»")

            for ww in WAKE_WORDS:
                if ww in text_low:
                    idx = text_low.find(ww)
                    remainder = text[idx + len(ww):].strip(" ,.!?—-–")
                    print(f"[Wake] *** wake-word '{ww}' обнаружен! remainder='{remainder}' ***")
                    self._paused = True
                    prev_audio = np.zeros(0, dtype=np.float32)
                    self._on_wake(remainder)
                    break

    # ------------------------------------------------------------------ model

    def _get_wake_model(self):
        """
        Лениво загружает отдельную tiny-модель для wake-word детекции.
        Всегда CPU + int8: быстро для коротких чанков, без CUDA/cublas.
        """
        if self._wake_model is not None:
            return self._wake_model
        if not _WHISPER_OK:
            return None
        print("[Wake] Загрузка tiny-модели (CPU)...")
        self._wake_model = _WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            num_workers=1,
            cpu_threads=2,
        )
        print("[Wake] Tiny-модель готова.")
        return self._wake_model

    # ------------------------------------------------------------------ transcribe

    def _quick_transcribe(self, audio: np.ndarray) -> str:
        """Быстрая транскрипция отдельной tiny-моделью — не трогает основной STT."""
        try:
            model = self._get_wake_model()
            if model is None:
                return ""

            # Нормализуем амплитуду — tiny-модель лучше работает с громким сигналом
            peak = float(np.max(np.abs(audio)))
            if peak > 0.01:
                audio = (audio / peak * 0.9).astype(np.float32)

            segments, _ = model.transcribe(
                audio,
                language="ru",
                beam_size=2,
                initial_prompt=_WAKE_PROMPT,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 100,
                    "speech_pad_ms": 100,
                },
                no_speech_threshold=0.5,
                temperature=0,
            )
            # Потребляем генератор сразу
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[Wake] ошибка транскрипции: {e}")
            return ""
