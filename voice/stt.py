"""
Speech-to-Text: запись голоса с микрофона и транскрипция через Whisper.
Работает полностью локально, без интернета и API-ключей.
"""

import threading
import time

import numpy as np
from core.logger import get_logger

log = get_logger("stt")

try:
    import sounddevice as sd
    _AUDIO_OK = True
except ImportError:
    _AUDIO_OK = False

try:
    from faster_whisper import WhisperModel
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False


_INITIAL_PROMPT = (
    "Джарвис, открой Discord, Steam, Telegram, Chrome, Firefox, "
    "запусти, найди в интернете, добавь задачу, создай заметку, запомни, "
    "который час, какой сегодня день, погода, скриншот, "
    "громче, тише, выключи звук, заблокируй компьютер, "
    "системная информация, закрой программу, поменяй путь, перезапусти."
)

_cached_device: int | None = -1


def _get_input_device() -> int | None:
    """
    Возвращает индекс лучшего доступного микрофона.
    Приоритет: AUDIO_INPUT_DEVICE из config → системный дефолт → первый реальный.
    """
    global _cached_device
    if _cached_device != -1:
        return _cached_device

    import config
    if config.AUDIO_INPUT_DEVICE is not None:
        _cached_device = config.AUDIO_INPUT_DEVICE
        return _cached_device

    _skip = {
        "переназначение", "remapping", "стерео микшер", "stereo mix",
        "первичный", "primary driver", "loopback", "output", "что выводит",
    }

    try:
        # 1) Пробуем системный дефолт Windows
        default_idx = sd.default.device[0]
        if default_idx is not None and default_idx >= 0:
            d = sd.query_devices(default_idx)
            if d["max_input_channels"] > 0:
                name_low = d["name"].lower()
                if not any(w in name_low for w in _skip):
                    _cached_device = default_idx
                    log.info("Mic (default): [%d] %s", default_idx, d["name"])
                    return _cached_device

        # 2) Ищем по имени
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d["max_input_channels"] <= 0:
                continue
            name_low = d["name"].lower()
            if any(w in name_low for w in _skip):
                continue
            if "микрофон" in name_low or "microphone" in name_low:
                _cached_device = i
                log.info("Mic: [%d] %s", i, d["name"])
                return _cached_device

        # 3) Первый доступный
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                name_low = d["name"].lower()
                if not any(w in name_low for w in _skip):
                    _cached_device = i
                    log.info("Mic (fallback): [%d] %s", i, d["name"])
                    return _cached_device
    except Exception:
        pass

    _cached_device = None
    return None


def _detect_device() -> tuple[str, str]:
    """GPU (CUDA) даёт 5–10× ускорение. Если недоступна — CPU."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _cpu_threads() -> int:
    """Оптимальное число потоков CPU для ctranslate2."""
    import os as _os
    cores = _os.cpu_count() or 4
    return min(8, max(4, cores))


class SpeechToText:
    """
    Запись с микрофона и распознавание речи через faster-whisper.
    Потокобезопасна: _load_lock предотвращает двойную загрузку,
    _model_lock сериализует вызовы transcribe().
    Автоматически откатывается на CPU если CUDA даёт ошибку cublas.
    """

    def __init__(self, model_size: str = "small", language: str = "ru"):
        if not _AUDIO_OK:
            raise ImportError("Установи: pip install sounddevice")
        if not _WHISPER_OK:
            raise ImportError("Установи: pip install faster-whisper")

        self._model_size  = model_size
        self._language    = language
        self._sample_rate = 16000
        self._model       = None
        self._device      = "cpu"
        # _load_lock: только один поток грузит модель
        self._load_lock   = threading.Lock()
        # _model_lock: ctranslate2 не реентерабелен — сериализуем transcribe()
        self._model_lock  = threading.Lock()

    # ------------------------------------------------------------------ model

    def _load_model(self):
        with self._load_lock:
            if self._model is not None:
                return
            self._device, compute_type = _detect_device()
            log.info("Loading Whisper '%s' on %s (%s)...", self._model_size, self._device.upper(), compute_type)
            threads = _cpu_threads()
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=compute_type,
                    num_workers=1,
                    cpu_threads=threads,
                )
                log.info("Whisper ready (%s, %d CPU threads).", self._device.upper(), threads)
            except Exception as e:
                # CUDA недоступна или неправильная версия — откатываемся на CPU
                log.warning("Whisper load failed on %s: %s", self._device.upper(), e)
                log.info("Whisper: falling back to CPU...")
                self._device = "cpu"
                self._model = WhisperModel(
                    self._model_size,
                    device="cpu",
                    compute_type="int8",
                    num_workers=1,
                    cpu_threads=threads,
                )
                log.info("Whisper ready (CPU).")

    def _reload_on_cpu(self):
        """Перезагружает модель на CPU после ошибки CUDA."""
        log.warning("Whisper CUDA error during transcription. Switching to CPU...")
        self._device = "cpu"
        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
            num_workers=1,
            cpu_threads=_cpu_threads(),
        )
        log.info("Whisper switched to CPU.")

    # ------------------------------------------------------------------ record

    def record_auto(
        self,
        silence_sec: float = 1.4,
        max_sec: float = 30.0,
    ) -> np.ndarray | None:
        """
        Записывает аудио автоматически — останавливается после тишины.
        Ждёт речи до 5 секунд. Если молчание — возвращает None.
        """
        t0 = time.perf_counter()
        CHUNK_SEC   = 0.05
        CHUNK_SIZE  = int(self._sample_rate * CHUNK_SEC)
        THRESHOLD   = 0.010
        SILENCE_LIM = int(silence_sec / CHUNK_SEC)
        WAIT_LIM    = int(5.0 / CHUNK_SEC)
        MAX_CHUNKS  = int(max_sec / CHUNK_SEC)

        frames: list[np.ndarray] = []
        speech_chunks = 0
        silence_count = 0
        done = threading.Event()

        def _cb(indata, n, t, status):
            nonlocal speech_chunks, silence_count
            # При ошибке устройства (отключение, переключение) — сразу выходим
            if status:
                done.set()
                return
            frames.append(indata.copy())
            rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))

            if rms > THRESHOLD:
                speech_chunks += 1
                silence_count = 0
            else:
                if speech_chunks > 0:
                    silence_count += 1
                    if silence_count >= SILENCE_LIM:
                        done.set()
                elif len(frames) >= WAIT_LIM:
                    done.set()

            if len(frames) >= MAX_CHUNKS:
                done.set()

        mic = _get_input_device()
        with sd.InputStream(
            device=mic,
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=_cb,
            blocksize=CHUNK_SIZE,
        ):
            done.wait(timeout=max_sec + 6)

        if not frames or speech_chunks < 2:
            log.debug("record_auto: no speech (%.2fs, speech_chunks=%d)", time.perf_counter() - t0, speech_chunks)
            return None

        audio = np.concatenate(frames, axis=0).flatten()
        log.info("record_auto: %.2fs, speech_chunks=%d, samples=%d", time.perf_counter() - t0, speech_chunks, len(audio))
        return audio

    # ------------------------------------------------------------------ transcribe

    def transcribe(self, audio: np.ndarray) -> str:
        """Транскрибирует аудио в текст (потокобезопасно, автооткат на CPU)."""
        t0 = time.perf_counter()
        self._load_model()

        peak = float(np.max(np.abs(audio)))
        if peak > 0.005:
            audio = (audio / peak * 0.95).astype(np.float32)

        with self._model_lock:
            result = self._run_transcribe(audio)
        log.info("transcribe done (%.2fs): %r", time.perf_counter() - t0, result[:80])
        return result

    def _run_transcribe(self, audio: np.ndarray) -> str:
        """Вызывает модель, при CUDA-ошибке перезагружает на CPU и повторяет."""
        try:
            segments, _ = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=5,
                temperature=0,
                condition_on_previous_text=False,
                initial_prompt=_INITIAL_PROMPT,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 200,
                },
                no_speech_threshold=0.60,
                word_timestamps=False,
            )
            # Генератор потребляем здесь, пока держим lock
            return " ".join(seg.text.strip() for seg in segments).strip()

        except RuntimeError as e:
            err = str(e).lower()
            if "cublas" in err or ("cuda" in err and "load" in err):
                # cublas64_12.dll не найден — грузимся заново на CPU
                self._reload_on_cpu()
                segments, _ = self._model.transcribe(
                    audio,
                    language=self._language,
                    beam_size=5,
                    temperature=0,
                    condition_on_previous_text=False,
                    initial_prompt=_INITIAL_PROMPT,
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 300,
                        "speech_pad_ms": 200,
                    },
                    no_speech_threshold=0.60,
                    word_timestamps=False,
                )
                return " ".join(seg.text.strip() for seg in segments).strip()
            raise
