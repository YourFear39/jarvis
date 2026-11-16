"""Тест wake word — записывает голос и показывает что слышит tiny-модель."""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from voice.stt import _get_input_device

SR = 16000
DURATION = 3.0

print("Загрузка tiny модели (CPU)...")
model = WhisperModel("tiny", device="cpu", compute_type="int8", num_workers=1)
print("Готово.")
print()

# Показываем доступные микрофоны
print("Доступные микрофоны:")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(f"  [{i}] {d['name']}")

mic = _get_input_device()
print(f"\nВыбранный микрофон: [{mic}] {sd.query_devices(mic)['name']}")
print()

input(">>> Нажми Enter, потом говори 'Джарвис'...")

print(f"Запись {DURATION}с...")
audio = sd.rec(int(SR * DURATION), samplerate=SR, channels=1, dtype="float32", device=mic)
sd.wait()
audio = audio.flatten()

rms = float(np.sqrt(np.mean(audio**2)))
print(f"RMS уровень: {rms:.4f}")

if rms < 0.003:
    print("СЛИШКОМ ТИХО — микрофон не слышит")
    print("Попробуй: задай AUDIO_INPUT_DEVICE=<номер> в .env и перезапусти тест")
else:
    segments, info = model.transcribe(
        audio, language="ru", beam_size=2,
        initial_prompt="Джарвис.",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 100},
    )
    texts = [s.text for s in segments]
    print(f"Распознано: {texts}")
    combined = " ".join(texts).lower()
    WAKE_WORDS = {"джарвис","jarvis","жарвис","дарвис","джарвист","джарвисе","джервис","ярвис","харвис"}
    found = [w for w in WAKE_WORDS if w in combined]
    print(f"Wake word найден: {found if found else 'НЕТ'}")
    if not found:
        print(f"Полный текст: '{combined}'")
        print("Добавь этот вариант в WAKE_WORDS в wake_word.py")
