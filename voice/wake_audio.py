"""
Мгновенные аудио-отклики на wake-word.

Фразы генерируются ОДИН РАЗ через настроенный TTS и кешируются в data/responses/.
При срабатывании wake-word — мгновенно воспроизводим готовый MP3 без API-запроса.

Использование:
    wa = WakeAudio()
    wa.prebuild_async()   # запускаем в фоне при старте
    wa.play_random()      # вызывается при wake — мгновенно
"""

from __future__ import annotations

import os
import random
import threading
from pathlib import Path

import config

# Фразы-отклики (случайный выбор при каждой активации)
_RESPONSE_TEXTS = [
    "Слушаю, сэр.",
    "Да, сэр.",
    "Слушаю.",
    "К вашим услугам, сэр.",
]

_CACHE_DIR    = config.DATA_DIR / "responses"
_ENGINE_STAMP = _CACHE_DIR / ".engine"   # хранит имя движка для detect change


class WakeAudio:
    """
    Менеджер кешированных аудио-откликов на wake-word.
    Потокобезопасен: play_random() можно вызывать из любого потока.
    """

    def __init__(self) -> None:
        self._files: list[Path] = []
        self._ready  = False
        self._lock   = threading.Lock()

    # ------------------------------------------------------------------ public

    def prebuild_async(self) -> None:
        """Запускает генерацию кеша в фоновом потоке. Не блокирует запуск UI."""
        threading.Thread(target=self._build, daemon=True, name="wake-audio-build").start()

    def play_random(self, on_done: "callable | None" = None) -> None:
        """
        Воспроизводит случайный отклик мгновенно в фоновом потоке.
        on_done вызывается в том же фоновом потоке по окончании воспроизведения.
        Если кеш ещё не готов — on_done вызывается немедленно.
        """
        with self._lock:
            files = list(self._files) if self._ready else []

        if not files:
            if on_done:
                on_done()
            return

        chosen = random.choice(files)

        def _run():
            self._play_file(chosen)
            if on_done:
                on_done()

        threading.Thread(target=_run, daemon=True, name="wake-audio-play").start()

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        """Генерирует MP3-файлы через TTS и сохраняет в кеш."""
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        engine = config.TTS_ENGINE

        # Перегенерируем если движок TTS изменился
        if _ENGINE_STAMP.exists() and _ENGINE_STAMP.read_text().strip() == engine:
            existing = sorted(_CACHE_DIR.glob("response_*.mp3"))
            if len(existing) == len(_RESPONSE_TEXTS):
                with self._lock:
                    self._files = existing
                    self._ready = True
                print(f"[WakeAudio] Кеш загружен ({len(existing)} файлов, движок={engine})")
                return

        print(f"[WakeAudio] Генерирую кеш откликов ({engine})...")
        generated: list[Path] = []

        for i, text in enumerate(_RESPONSE_TEXTS):
            out_path = _CACHE_DIR / f"response_{i:02d}.mp3"
            try:
                self._generate_one(text, out_path, engine)
                generated.append(out_path)
                print(f"[WakeAudio] [{i+1}/{len(_RESPONSE_TEXTS)}] «{text}»")
            except Exception as e:
                print(f"[WakeAudio] Ошибка генерации «{text}»: {e}")

        if generated:
            _ENGINE_STAMP.write_text(engine)
            with self._lock:
                self._files = generated
                self._ready = True
            print(f"[WakeAudio] Готово — {len(generated)} файлов в кеше.")
        else:
            print("[WakeAudio] Не удалось сгенерировать кеш. Отклик будет без звука.")

    def _generate_one(self, text: str, out_path: Path, engine: str) -> None:
        """Генерирует один MP3-файл через нужный TTS движок."""
        if engine == "elevenlabs" and config.ELEVENLABS_API_KEY:
            self._generate_elevenlabs(text, out_path)
        else:
            self._generate_edge_tts(text, out_path)

    def _generate_elevenlabs(self, text: str, out_path: Path) -> None:
        import requests
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"
        resp = requests.post(
            url,
            headers={"xi-api-key": config.ELEVENLABS_API_KEY, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": config.ELEVENLABS_STABILITY,
                    "similarity_boost": config.ELEVENLABS_SIMILARITY_BOOST,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        out_path.write_bytes(resp.content)

    def _generate_edge_tts(self, text: str, out_path: Path) -> None:
        import asyncio
        import edge_tts

        async def _gen():
            comm = edge_tts.Communicate(text, "ru-RU-DmitryNeural", rate="-8%", pitch="-10Hz")
            await comm.save(str(out_path))

        asyncio.run(_gen())

    # ------------------------------------------------------------------ play

    @staticmethod
    def _play_file(path: Path) -> None:
        """Воспроизводит MP3-файл из кеша. Пробует sounddevice → playsound."""
        try:
            import av as _av
            import numpy as np
            import sounddevice as sd

            container = _av.open(str(path))
            frames, sr = [], 24000
            for frame in container.decode(audio=0):
                sr = frame.sample_rate
                data = frame.to_ndarray()
                if data.ndim > 1:
                    data = data.mean(axis=0)
                frames.append(data.astype(np.float32))
            container.close()
            if frames:
                audio = np.concatenate(frames)
                sd.play(audio, samplerate=sr)
                sd.wait()
            return
        except Exception:
            pass

        # Фолбек: playsound
        try:
            from playsound import playsound
            playsound(str(path))
        except Exception as e:
            print(f"[WakeAudio] play error: {e}")


# Глобальный синглтон — инициализируется при импорте модуля
_instance: WakeAudio | None = None


def get_wake_audio() -> WakeAudio:
    global _instance
    if _instance is None:
        _instance = WakeAudio()
    return _instance
