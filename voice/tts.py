"""
Text-to-Speech: озвучка ответов Джарвиса.

Пайплайн:
  edge-tts → MP3 → PyAV decode → scipy DSP (JARVIS-эффект) → sounddevice

JARVIS-эффект: высокочастотный акцент, лёгкое насыщение, присутствие зала —
достигается фильтрацией и свёрткой в scipy.
Fallback: если scipy/av недоступны — воспроизводим MP3 через playsound.
"""

import asyncio
import os
import re
import tempfile
import threading
import time

import numpy as np
import config
from core.logger import get_logger

log = get_logger("tts")

try:
    import edge_tts
    _EDGE_OK = True
except ImportError:
    _EDGE_OK = False

try:
    import av as _av
    _AV_OK = True
except ImportError:
    _AV_OK = False

try:
    import sounddevice as sd
    _SD_OK = True
except ImportError:
    _SD_OK = False

try:
    from scipy import signal as _signal
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

try:
    from playsound import playsound
    _PLAYSOUND_OK = True
except ImportError:
    _PLAYSOUND_OK = False

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False


VOICE_RU_MALE   = "ru-RU-DmitryNeural"
VOICE_RU_FEMALE = "ru-RU-SvetlanaNeural"

# Полноценный DSP доступен когда есть av + scipy + sounddevice
_DSP_OK = _AV_OK and _SCIPY_OK and _SD_OK


# ---------------------------------------------------------------------------
# JARVIS DSP — делает голос похожим на ИИ из фильма Iron Man
# ---------------------------------------------------------------------------

def _jarvis_dsp(audio: np.ndarray, sr: int) -> np.ndarray:
    """
    Цепочка обработки сигнала для голоса JARVIS:
    1. High-pass 90Hz        — убирает низкочастотный рокот (4th order Butterworth)
    2. Resonance peak 900Hz  — грудной резонанс, добавляет глубину (mix 15%)
    3. Presence boost 3-5.5kHz — чёткость без резкости (mix 18%)
    4. Очень мягкая сатурация — минимум искажений
    5. Ранние отражения      — короткий, тонкий зал (mix 12%)
    6. Нормализация
    """
    # Нормализуем входной сигнал
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-7:
        return audio.astype(np.float32)
    audio = (audio / peak).astype(np.float64)

    nyq = sr / 2.0

    # 1. High-pass filter 90Hz — убираем низкочастотный рокот (4th order Butterworth)
    sos_hp = _signal.butter(4, 90 / nyq, btype="high", output="sos")
    audio = _signal.sosfilt(sos_hp, audio)

    # 2. Resonance peak 900Hz — грудной/комнатный резонанс (bandpass Q=2.0, mix 15%)
    res_lo = 900 / nyq * 0.75   # ~675Hz lower edge
    res_hi = 900 / nyq * 1.33   # ~1197Hz upper edge
    if res_lo < 1.0 and res_hi < 1.0:
        sos_res = _signal.butter(2, [res_lo, res_hi], btype="band", output="sos")
        resonance = _signal.sosfilt(sos_res, audio)
        audio = audio + 0.15 * resonance

    # 3. Presence boost 3000–5500Hz — чёткость речи без резкости (Q=0.9, mix 18%)
    lo, hi = 3000 / nyq, 5500 / nyq
    if lo < 1.0 and hi < 1.0:
        sos_pres = _signal.butter(2, [lo, hi], btype="band", output="sos")
        presence = _signal.sosfilt(sos_pres, audio)
        audio = audio + 0.18 * presence

    # 4. Очень мягкая сатурация — минимум дисторшена, лёгкая теплота
    audio = np.tanh(audio * 1.25) / 1.15

    # 5. Ранние отражения — короткий, тонкий JARVIS-зал
    if sr >= 8000:
        ir = np.zeros(int(sr * 0.040))
        ir[0] = 1.0
        ir[int(sr * 0.007)] = 0.18   # 7ms первое отражение
        ir[int(sr * 0.018)] = 0.09   # 18ms второе
        ir[int(sr * 0.032)] = 0.04   # 32ms третье
        reverb = _signal.fftconvolve(audio, ir, mode="full")[:len(audio)]
        audio = audio * 0.88 + reverb * 0.12

    # 6. Финальная нормализация
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = audio / peak * 0.88

    return audio.astype(np.float32)


def _decode_mp3(path: str) -> tuple[np.ndarray, int]:
    """Декодирует MP3 в numpy float32 через PyAV."""
    container = _av.open(path)
    frames = []
    sr = 24000
    try:
        for frame in container.decode(audio=0):
            sr = frame.sample_rate
            data = frame.to_ndarray()          # (channels, samples) float
            if data.ndim > 1:
                data = data.mean(axis=0)        # стерео → моно
            frames.append(data.astype(np.float32))
    finally:
        container.close()

    if not frames:
        return np.zeros(0, dtype=np.float32), sr
    return np.concatenate(frames), sr


def _decode_and_process(path: str) -> tuple[np.ndarray, int]:
    """Декодирует MP3 и применяет JARVIS DSP. Гарантированно удаляет temp-файл."""
    try:
        audio, sr = _decode_mp3(path)
    finally:
        # Удаляем файл даже если PyAV упал при открытии
        try:
            os.unlink(path)
        except OSError:
            pass
    if audio.size == 0:
        return audio, sr
    if _SCIPY_OK:
        audio = _jarvis_dsp(audio, sr)
    return audio, sr


def _play_array(audio: np.ndarray, sr: int) -> None:
    """Воспроизводит numpy-массив через sounddevice (синхронно)."""
    if audio.size == 0:
        return
    try:
        sd.stop()  # сбрасываем любой зависший поток перед новым воспроизведением
    except Exception:
        pass
    sd.play(audio, samplerate=sr)
    sd.wait()


# ---------------------------------------------------------------------------
# TextToSpeech
# ---------------------------------------------------------------------------

class TextToSpeech:
    """
    Озвучка текста через edge-tts → JARVIS DSP → sounddevice.
    Пайплайн: генерация следующего предложения идёт пока воспроизводится текущее.
    """

    def __init__(
        self,
        voice: str = VOICE_RU_MALE,
        rate: str  = "-8%",     # чуть медленнее — естественный темп JARVIS
        pitch: str = "-10Hz",   # слегка ниже — тонкое углубление без искусственности
    ):
        if not _EDGE_OK:
            raise ImportError("Установи: pip install edge-tts")
        if not _DSP_OK and not _PLAYSOUND_OK:
            raise ImportError("Установи: pip install playsound==1.2.2")

        self._voice = voice
        self._rate  = rate
        self._pitch = pitch

        # Персистентный event loop для edge-tts (устраняет ~100ms оверхед)
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
        log.debug("EdgeTTS → %r (%d chars)", cleaned[:50], len(cleaned))
        t0 = time.perf_counter()
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._pipeline(cleaned), self._loop
            )
            future.result(timeout=90)
            log.info("EdgeTTS done (%.2fs)", time.perf_counter() - t0)
        except Exception as e:
            log.error("EdgeTTS error (%.2fs): %s", time.perf_counter() - t0, e)

    # ------------------------------------------------------------------ pipeline

    async def _pipeline(self, text: str) -> None:
        """
        Пайплайн:
        - Генерируем MP3 предложения N+1 пока декодируем/играем N
        - DSP + воспроизведение — в threadpool (не блокирует event loop)
        """
        loop = asyncio.get_running_loop()
        sentences = split_sentences(text)
        if not sentences:
            return

        # Генерируем первое предложение
        path = await self._gen(sentences[0])

        for i in range(len(sentences)):
            # Запускаем генерацию следующего в фоне
            next_task = None
            if i + 1 < len(sentences):
                next_task = asyncio.create_task(self._gen(sentences[i + 1]))

            try:
                if _DSP_OK:
                    # Decode + DSP в executor (_decode_and_process удаляет path)
                    audio, sr = await loop.run_in_executor(
                        None, _decode_and_process, path
                    )
                    # Воспроизводим
                    await loop.run_in_executor(None, _play_array, audio, sr)
                else:
                    # Fallback: playsound (без JARVIS-эффекта)
                    await loop.run_in_executor(None, _play_fallback, path)
            except Exception as e:
                # Ошибка воспроизведения — логируем, но НЕ останавливаем весь ответ
                log.warning("TTS sentence %d playback error: %s — continuing", i, e)

            if next_task is not None:
                try:
                    path = await next_task
                except Exception as e:
                    log.error("TTS sentence %d generation failed: %s — stopping", i + 1, e)
                    return

    async def _gen(self, text: str) -> str:
        """Генерирует MP3 через edge-tts и возвращает путь к temp-файлу."""
        communicate = edge_tts.Communicate(
            text, self._voice, rate=self._rate, pitch=self._pitch
        )
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        await communicate.save(tmp_path)
        return tmp_path


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _play_fallback(path: str) -> None:
    """Playsound fallback (без DSP). Удаляет temp-файл после воспроизведения."""
    try:
        playsound(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def split_sentences(text: str) -> list[str]:
    """Разбивает на предложения, объединяет короткие части (≥70 символов)."""
    raw = re.split(r'(?<=[.!?])\s+', text)
    result: list[str] = []
    buf = ""
    for part in raw:
        buf = (buf + " " + part).strip() if buf else part
        if len(buf) >= 70:
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)
    return result or [text]


def create_tts() -> "ElevenLabsTTS | TextToSpeech":
    """
    Фабрика: создаёт TTS-движок по TTS_ENGINE из config.
    Если ElevenLabs выбран, но ключ не задан — тихо откатывается на edge-tts.
    """
    if config.TTS_ENGINE == "elevenlabs":
        if config.ELEVENLABS_API_KEY:
            log.info("TTS engine: ElevenLabs (voice=%s, model=%s)", config.ELEVENLABS_VOICE_ID, config.ELEVENLABS_MODEL)
            return ElevenLabsTTS()
        log.warning("TTS_ENGINE=elevenlabs но ELEVENLABS_API_KEY не задан → edge-tts")
    log.info("TTS engine: EdgeTTS")
    return TextToSpeech()


# ---------------------------------------------------------------------------
# ElevenLabs TTS
# ---------------------------------------------------------------------------

class ElevenLabsTTS:
    """
    Озвучка через ElevenLabs API — реалистичный British JARVIS-голос.

    Модель: eleven_v3 (самая выразительная, 70+ языков).
    Fallback: при ошибке ДО начала воспроизведения откатывается на edge-tts.
    """

    _API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    def __init__(self) -> None:
        self._fallback: TextToSpeech | None = None

    def speak(self, text: str) -> None:
        """Произносит текст. При ошибке ElevenLabs до начала воспроизведения — edge-tts."""
        cleaned = clean_for_tts(text)
        if not cleaned.strip():
            return

        if len(cleaned) > config.ELEVENLABS_MAX_CHARS:
            cleaned = cleaned[:config.ELEVENLABS_MAX_CHARS].rsplit(" ", 1)[0]

        log.debug("ElevenLabs → %r (%d chars)", cleaned[:50], len(cleaned))
        played = self._speak_api(cleaned)
        if not played:
            log.warning("ElevenLabs failed → fallback EdgeTTS")
            if _SD_OK:
                try:
                    sd.stop()
                except Exception:
                    pass
            self._get_fallback().speak(cleaned)

    def _speak_api(self, text: str) -> bool:
        """
        Вызывает ElevenLabs API и воспроизводит результат.
        Возвращает True если аудио успешно воспроизведено, False при любой ошибке.
        """
        if not config.ELEVENLABS_API_KEY:
            log.warning("ElevenLabs: API key не задан")
            return False
        if not _REQUESTS_OK:
            log.warning("ElevenLabs: requests не установлен")
            return False

        url = self._API_URL.format(voice_id=config.ELEVENLABS_VOICE_ID)
        t0 = time.perf_counter()
        try:
            resp = _requests.post(
                url,
                headers={
                    "xi-api-key": config.ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": config.ELEVENLABS_MODEL,
                    "voice_settings": {
                        "stability":        config.ELEVENLABS_STABILITY,
                        "similarity_boost": config.ELEVENLABS_SIMILARITY_BOOST,
                        "style":            config.ELEVENLABS_STYLE,
                        "speed":            config.ELEVENLABS_SPEED,
                        "use_speaker_boost": config.ELEVENLABS_USE_SPEAKER_BOOST,
                    },
                },
                timeout=30,
            )
            resp.raise_for_status()
            log.debug("ElevenLabs API %.2fs, %d bytes", time.perf_counter() - t0, len(resp.content))
        except Exception as e:
            log.error("ElevenLabs API error (%.2fs): %s", time.perf_counter() - t0, e)
            return False

        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        t1 = time.perf_counter()
        try:
            with open(tmp_path, "wb") as f:
                f.write(resp.content)

            if _DSP_OK:
                audio, sr = _decode_mp3(tmp_path)
                _play_array(audio, sr)
                log.info("ElevenLabs done (api=%.2fs play=%.2fs, %d bytes)",
                         t1 - t0, time.perf_counter() - t1, len(resp.content))
                return True
            elif _PLAYSOUND_OK:
                _play_fallback(tmp_path)
                tmp_path = None
                log.info("ElevenLabs done via playsound (%.2fs total)", time.perf_counter() - t0)
                return True
            else:
                log.warning("ElevenLabs: нет аудио-плеера")
                return False
        except Exception as e:
            log.error("ElevenLabs playback error: %s", e)
            return False
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _get_fallback(self) -> TextToSpeech:
        """Ленивая инициализация edge-tts как запасного движка."""
        if self._fallback is None:
            self._fallback = TextToSpeech()
        return self._fallback


def clean_for_tts(text: str) -> str:
    """Очищает текст от markdown, URL, эмодзи и символов интерфейса перед озвучкой."""
    # Эмодзи и спецсимволы Unicode (включая ✅ 🔴 📝 и прочие)
    text = re.sub(
        r'[\U0001F300-\U0001FFFF'   # misc symbols and pictographs, emoticons, transport…
        r'\U00002600-\U000027BF'    # misc symbols, dingbats
        r'\U0000FE00-\U0000FE0F'    # variation selectors
        r'\U00002B50-\U00002B55'    # stars / circles
        r'\U000025A0-\U000025FF'    # geometric shapes
        r'\U00002700-\U000027BF]+', # dingbats
        '',
        text,
    )
    text = re.sub(r'[◈▷▶◄►●⟳⚙◦■□▪▫─═]', '', text)
    text = re.sub(r'\[\d{1,2}:\d{2}\]', '', text)
    text = re.sub(r'\[[^\]\n]{0,80}\]', '', text)  # [7][8], [* 1], [ˈiːlɒn 'mʌsk] и пр.
    text = re.sub(r'^JARVIS\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`\n]+`', '', text)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r'^[─═\-]{2,}.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+[.)]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[A-Za-z]:\\[^\s,;]+', '', text)
    text = re.sub(r'\b[a-f0-9]{8,}\b', '', text)
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\n', ', ', text)
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    text = re.sub(r'[,\s]{2,}', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    return text.strip()
