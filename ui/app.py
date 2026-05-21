"""
GUI-интерфейс Джарвиса в стиле JARVIS из фильма Iron Man.
customtkinter, тёмная sci-fi тема с синими акцентами.
Голосовое управление: кнопка микрофона → автозапись → TTS-ответ.
"""

import threading
import queue
from datetime import datetime

import customtkinter as ctk
import tkinter as tk

import config

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --- Цветовая схема JARVIS ---
C = {
    "bg":            "#05080f",
    "bg_panel":      "#070c15",
    "bg_input":      "#090f1a",
    "accent":        "#00c8f0",
    "accent_dim":    "#003850",
    "accent_bright": "#40e0ff",
    "text":          "#b8dce8",
    "text_dim":      "#3a6070",
    "text_jarvis":   "#00c8f0",
    "text_user":     "#7ad0e8",
    "green":         "#00e87a",
    "yellow":        "#f0c000",
    "red":           "#e83040",
    "border":        "#0d2535",
    "border_bright": "#1a4a60",
}

# Что Джарвис говорит вслух когда запускает инструмент
TOOL_PHRASES = {
    "web_search":       "Ищу в интернете, сэр...",
    "add_note":         "Записываю заметку, сэр...",
    "get_notes":        "Проверяю заметки...",
    "add_task":         "Добавляю задачу, сэр...",
    "get_tasks":        "Смотрю список задач...",
    "complete_task":    "Отмечаю задачу выполненной, сэр.",
    "read_file":        "Читаю файл...",
    "create_plan":      "Составляю план, сэр...",
    "get_plan":         "Проверяю планы...",
    "update_plan_step": "Обновляю план...",
}

FONT = "Consolas"


def _font(size=12, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


class JarvisApp(ctk.CTk):
    def __init__(self, assistant):
        super().__init__()

        self._assistant = assistant
        self._busy = False
        self._voice_active = False
        self._voice_mode = False    # True = последнее сообщение пришло голосом → озвучить ответ

        self._q: queue.Queue = queue.Queue()

        # TTS-объект и его рабочий поток (инициализируются лениво)
        self._tts = None
        self._stt = None
        self._tts_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._tts_worker, daemon=True).start()

        self._setup_window()
        self._build_ui()
        self._refresh_side_panel()
        self._poll_queue()

    # ------------------------------------------------------------------ setup

    def _setup_window(self):
        self.title("JARVIS — AI Assistant")
        self.geometry("1260x800")
        self.minsize(960, 640)
        self.configure(fg_color=C["bg"])

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        self._build_header()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        body.grid_columnconfigure(0, weight=70)
        body.grid_columnconfigure(1, weight=30)
        body.grid_rowconfigure(0, weight=1)

        self._build_chat_panel(body)
        self._build_side_panel(body)

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=C["bg_panel"], height=52, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkFrame(self, fg_color=C["accent_dim"], height=1, corner_radius=0).pack(fill="x")

        ctk.CTkLabel(hdr, text="◈ JARVIS", font=_font(20, bold=True),
                     text_color=C["accent"]).pack(side="left", padx=18)

        ctk.CTkLabel(hdr, text="PERSONAL AI ASSISTANT  //  v1.0",
                     font=_font(10), text_color=C["text_dim"]).pack(side="left", padx=4)

        self._status_lbl = ctk.CTkLabel(
            hdr, text="● ONLINE", font=_font(11, bold=True), text_color=C["green"])
        self._status_lbl.pack(side="right", padx=18)

        ctk.CTkLabel(
            hdr,
            text=f"LLM ▸ {config.LLM_PROVIDER.upper()}  |  "
                 f"ПАМЯТЬ ▸ {'ВКЛ' if self._assistant._memory.is_available else 'ВЫКЛ'}",
            font=_font(10), text_color=C["text_dim"],
        ).pack(side="right", padx=8)

    def _build_chat_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=C["bg_panel"],
                             border_color=C["border"], border_width=1, corner_radius=8)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Чат-история
        self._chat = ctk.CTkTextbox(
            frame, font=_font(13),
            fg_color=C["bg"], text_color=C["text"],
            border_width=0, wrap="word", state="disabled",
        )
        self._chat.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        tb = self._chat._textbox
        tb.tag_configure("jarvis_hdr",  foreground=C["accent"],       font=(FONT, 11, "bold"))
        tb.tag_configure("jarvis_body", foreground=C["text"])
        tb.tag_configure("user_hdr",    foreground=C["yellow"],        font=(FONT, 11, "bold"))
        tb.tag_configure("user_body",   foreground=C["text_user"])
        tb.tag_configure("system",      foreground=C["text_dim"],      font=(FONT, 10, "italic"))
        tb.tag_configure("tool",        foreground=C["accent_dim"],    font=(FONT, 11))
        tb.tag_configure("voice_in",    foreground="#aa88ff",          font=(FONT, 11, "italic"))

        # Разделитель
        ctk.CTkFrame(frame, fg_color=C["border"], height=1, corner_radius=0)\
            .grid(row=1, column=0, sticky="ew")

        # Строка ввода
        inp = ctk.CTkFrame(frame, fg_color=C["bg_input"], corner_radius=0)
        inp.grid(row=2, column=0, sticky="ew")
        inp.grid_columnconfigure(0, weight=1)

        self._input = ctk.CTkEntry(
            inp, font=_font(13),
            fg_color="transparent", text_color=C["text"],
            border_width=0,
            placeholder_text="Введи сообщение... (Enter для отправки)",
            placeholder_text_color=C["text_dim"],
            height=46,
        )
        self._input.grid(row=0, column=0, sticky="ew", padx=(14, 6))
        self._input.bind("<Return>", self._on_send)

        self._send_btn = ctk.CTkButton(
            inp, text="▶  ОТПРАВИТЬ",
            width=140, height=34, font=_font(12, bold=True),
            fg_color=C["accent"], hover_color=C["accent_bright"],
            text_color=C["bg"], corner_radius=5,
            command=self._on_send,
        )
        self._send_btn.grid(row=0, column=1, padx=(0, 6), pady=6)

        # Кнопка микрофона
        self._mic_btn = ctk.CTkButton(
            inp, text="🎤",
            width=46, height=34, font=_font(18),
            fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"], corner_radius=5,
            command=self._on_mic_click,
        )
        self._mic_btn.grid(row=0, column=2, padx=(0, 10), pady=6)

        self._append_system("СИСТЕМА ИНИЦИАЛИЗИРОВАНА  ·  ВВЕДИ СООБЩЕНИЕ ИЛИ НАЖМИ 🎤")

    def _build_side_panel(self, parent):
        side = ctk.CTkFrame(parent, fg_color=C["bg_panel"],
                            border_color=C["border"], border_width=1, corner_radius=8)
        side.grid(row=0, column=1, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(1, weight=2)
        side.grid_rowconfigure(4, weight=3)

        self._side_label(side, "◈ ЗАМЕТКИ", row=0)

        self._notes_box = ctk.CTkTextbox(
            side, font=_font(11), fg_color=C["bg"], text_color=C["text"],
            border_width=0, state="disabled",
        )
        self._notes_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            side, text="＋  Добавить заметку", height=30, font=_font(11),
            corner_radius=4, fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"], command=self._dialog_add_note,
        ).grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        ctk.CTkFrame(side, fg_color=C["border"], height=1).grid(row=3, column=0, sticky="ew")

        self._side_label(side, "◈ ЗАДАЧИ", row=3, pady_top=6)

        self._tasks_box = ctk.CTkTextbox(
            side, font=_font(11), fg_color=C["bg"], text_color=C["text"],
            border_width=0, state="disabled",
        )
        self._tasks_box.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 4))
        side.grid_rowconfigure(5, weight=0)

        ctk.CTkButton(
            side, text="＋  Добавить задачу", height=30, font=_font(11),
            corner_radius=4, fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"], command=self._dialog_add_task,
        ).grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            side, text="↻  Обновить", height=28, font=_font(10),
            corner_radius=4, fg_color="transparent", hover_color=C["border"],
            text_color=C["text_dim"], border_color=C["border"], border_width=1,
            command=self._refresh_side_panel,
        ).grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 10))

    def _side_label(self, parent, text, row, pady_top=8):
        ctk.CTkLabel(parent, text=text, font=_font(12, bold=True),
                     text_color=C["accent"]).grid(
            row=row, column=0, sticky="w", padx=12, pady=(pady_top, 4))

    # ------------------------------------------------------------------ chat display

    def _append_message(self, role: str, text: str):
        self._chat.configure(state="normal")
        tb = self._chat._textbox
        now = datetime.now().strftime("%H:%M")
        if role == "jarvis":
            tb.insert("end", f"\n◈ JARVIS  [{now}]\n", "jarvis_hdr")
            tb.insert("end", f"{text}\n", "jarvis_body")
        elif role == "user":
            tb.insert("end", f"\n▷ ВЫ  [{now}]\n", "user_hdr")
            tb.insert("end", f"{text}\n", "user_body")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _append_system(self, text: str):
        self._chat.configure(state="normal")
        self._chat._textbox.insert("end", f"\n  [ {text} ]\n", "system")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _append_tool(self, tool_name: str):
        labels = {
            "web_search":       "поиск в интернете",
            "add_note":         "сохранение заметки",
            "get_notes":        "чтение заметок",
            "add_task":         "добавление задачи",
            "get_tasks":        "чтение задач",
            "complete_task":    "завершение задачи",
            "read_file":        "чтение файла",
            "create_plan":      "создание плана",
            "get_plan":         "чтение плана",
            "update_plan_step": "обновление плана",
        }
        label = labels.get(tool_name, tool_name)
        self._chat.configure(state="normal")
        self._chat._textbox.insert("end", f"  ⚙  {label}...\n", "tool")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def _append_voice_in(self, text: str):
        """Показывает распознанный голос перед отправкой."""
        self._chat.configure(state="normal")
        self._chat._textbox.insert("end", f"  🎤 распознано: «{text}»\n", "voice_in")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    # ------------------------------------------------------------------ state

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self._send_btn.configure(
                text="⟳  ОБРАБОТКА...", state="disabled", fg_color=C["accent_dim"])
            self._input.configure(state="disabled")
            self._status_lbl.configure(text="● ОБРАБОТКА...", text_color=C["yellow"])
        else:
            self._send_btn.configure(
                text="▶  ОТПРАВИТЬ", state="normal", fg_color=C["accent"])
            self._input.configure(state="normal")
            self._status_lbl.configure(text="● ONLINE", text_color=C["green"])
            self._input.focus()

    def _set_recording(self, active: bool):
        if active:
            self._mic_btn.configure(text="⏹", fg_color=C["red"])
            self._status_lbl.configure(text="● СЛУШАЮ...", text_color=C["red"])
        else:
            self._mic_btn.configure(text="🎤", fg_color=C["accent_dim"])

    def _set_speaking(self, active: bool):
        if active:
            self._status_lbl.configure(text="● ГОВОРЮ...", text_color=C["accent"])
        else:
            if not self._busy:
                self._status_lbl.configure(text="● ONLINE", text_color=C["green"])

    # ------------------------------------------------------------------ connection errors

    def _handle_conn_error(self, err: str, user_text: str):
        """Обрабатывает ошибку подключения к LLM — сначала пробует офлайн-режим."""
        from core.offline import handle_offline, offline_help

        # Пробуем ответить без LLM
        offline_response = handle_offline(user_text)
        if offline_response:
            self._append_message("jarvis", offline_response)
            self._append_system("ОТВЕТ БЕЗ LLM (ОФЛАЙН-РЕЖИМ)")
            self._set_busy(False)
            if self._voice_mode:
                self._enqueue_tts(offline_response)
            return

        # Офлайн не справился — показываем понятную причину
        if "GEMINI_QUOTA_EXHAUSTED" in err:
            n = err.split(":")[-1]
            self._append_system(
                f"ВСЕ {n} КЛЮЧА GEMINI ИСЧЕРПАЛИ ДНЕВНОЙ ЛИМИТ  ·  "
                f"ЛИМИТ ОБНОВИТСЯ В ~03:00 МСК"
            )
        elif "GEMINI_UNAVAILABLE" in err:
            self._append_system("СЕРВЕРЫ GEMINI ПЕРЕГРУЖЕНЫ — ПОПРОБУЙ ЧЕРЕЗ МИНУТУ")
        else:
            self._append_system(f"НЕТ СВЯЗИ С LLM: {err}")

        # Показываем что доступно в офлайн
        help_text = offline_help()
        self._append_message("jarvis", help_text)
        if self._voice_mode:
            self._enqueue_tts("Нет связи с сервером, сэр. Работаю в офлайн-режиме.")

        self._set_busy(False)

    # ------------------------------------------------------------------ send / worker

    def _on_send(self, event=None, from_voice=False):
        if self._busy:
            return
        text = self._input.get().strip()
        if not text:
            return

        cmd = text.lower()
        if cmd in ("/exit", "/quit"):
            self.destroy()
            return
        if cmd in ("/memory", "/mem"):
            self._input.delete(0, "end")
            self._append_system(self._assistant.get_memory_stats())
            return
        if cmd in ("/clear", "/cls"):
            self._input.delete(0, "end")
            self._chat.configure(state="normal")
            self._chat.delete("1.0", "end")
            self._chat.configure(state="disabled")
            self._append_system("ЭКРАН ОЧИЩЕН")
            return

        self._voice_mode = from_voice
        self._input.delete(0, "end")
        self._append_message("user", text)
        self._set_busy(True)

        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text: str):
        def tool_cb(name: str):
            self._q.put(("tool", name))
            if self._voice_mode:
                phrase = TOOL_PHRASES.get(name)
                if phrase:
                    self._enqueue_tts(phrase)

        self._assistant._on_tool_use = tool_cb
        try:
            response = self._assistant.chat(text)
            self._q.put(("response", response))
        except ConnectionError as e:
            self._q.put(("conn_error", str(e), text))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    # ------------------------------------------------------------------ queue poll

    def _poll_queue(self):
        refresh = False
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]

                if kind == "response":
                    text = item[1]
                    self._append_message("jarvis", text)
                    self._set_busy(False)
                    refresh = True
                    if self._voice_mode:
                        self._enqueue_tts(text)

                elif kind == "error":
                    self._append_system(f"ОШИБКА: {item[1]}")
                    self._set_busy(False)

                elif kind == "conn_error":
                    self._handle_conn_error(item[1], item[2])

                elif kind == "tool":
                    self._append_tool(item[1])

                # --- Голос ---
                elif kind == "rec_start":
                    # Запись началась
                    self._set_recording(True)
                    self._append_system("СЛУШАЮ...")

                elif kind == "rec_done":
                    # Получен распознанный текст
                    self._set_recording(False)
                    recognized = item[1]
                    self._append_voice_in(recognized)
                    self._input.delete(0, "end")
                    self._input.insert(0, recognized)
                    self._on_send(from_voice=True)

                elif kind == "rec_empty":
                    self._set_recording(False)
                    self._status_lbl.configure(text="● ONLINE", text_color=C["green"])
                    self._append_system(item[1])
                    self._voice_active = False

                elif kind == "tts_start":
                    self._set_speaking(True)

                elif kind == "tts_done":
                    self._set_speaking(False)

        except queue.Empty:
            pass

        if refresh:
            self._refresh_side_panel()

        self.after(80, self._poll_queue)

    # ------------------------------------------------------------------ voice: STT

    def _init_voice(self) -> bool:
        """Ленивая инициализация голосовых компонентов. True = успех."""
        errors = []
        if self._stt is None:
            try:
                from voice.stt import SpeechToText
                self._stt = SpeechToText(model_size="small", language="ru")
            except ImportError as e:
                errors.append(str(e))
        if self._tts is None:
            try:
                from voice.tts import TextToSpeech
                self._tts = TextToSpeech()
            except ImportError as e:
                errors.append(str(e))
        if errors:
            self._append_system("ГОЛОСОВЫЕ ПАКЕТЫ НЕ УСТАНОВЛЕНЫ: " + "; ".join(errors))
            return False
        return True

    def _on_mic_click(self):
        if self._busy or self._voice_active:
            return
        if not self._init_voice():
            return

        self._voice_active = True
        self._q.put(("rec_start", None))
        threading.Thread(target=self._record_worker, daemon=True).start()

    def _record_worker(self):
        try:
            audio = self._stt.record_auto()

            if audio is None:
                self._q.put(("rec_empty", "НИЧЕГО НЕ УСЛЫШАЛ — ПОПРОБУЙ ЕЩЁ РАЗ"))
                return

            self._q.put(("rec_empty", "РАСПОЗНАЮ РЕЧЬ..."))   # Промежуточный статус
            text = self._stt.transcribe(audio)

            if not text:
                self._q.put(("rec_empty", "НЕ СМОГ РАСПОЗНАТЬ РЕЧЬ"))
                return

            self._q.put(("rec_done", text))

        except Exception as e:
            self._q.put(("rec_empty", f"ОШИБКА ГОЛОСА: {e}"))
        finally:
            self._voice_active = False

    # ------------------------------------------------------------------ TTS

    def _enqueue_tts(self, text: str):
        """Ставит текст в очередь на озвучку."""
        if self._tts is not None:
            self._tts_q.put(text)

    def _tts_worker(self):
        """Фоновый поток — озвучивает всё из очереди по порядку."""
        while True:
            text = self._tts_q.get()
            if text is None:
                break
            self._q.put(("tts_start", None))
            try:
                if self._tts:
                    self._tts.speak(text)
            except Exception:
                pass
            self._q.put(("tts_done", None))
            self._tts_q.task_done()

    # ------------------------------------------------------------------ dialogs

    def _dialog_add_note(self):
        d = ctk.CTkInputDialog(text="Текст заметки:", title="Новая заметка")
        result = d.get_input()
        if result and result.strip():
            from tools.notes import add_note
            add_note(title=result.strip()[:60], content=result.strip())
            self._refresh_side_panel()
            self._append_system(f"ЗАМЕТКА СОХРАНЕНА: {result.strip()[:50]}")

    def _dialog_add_task(self):
        d = ctk.CTkInputDialog(text="Название задачи:", title="Новая задача")
        result = d.get_input()
        if result and result.strip():
            from tools.notes import add_task
            add_task(title=result.strip())
            self._refresh_side_panel()
            self._append_system(f"ЗАДАЧА ДОБАВЛЕНА: {result.strip()[:50]}")

    # ------------------------------------------------------------------ side panel

    def _refresh_side_panel(self):
        from tools.notes import get_notes, get_tasks
        for box, fn in ((self._notes_box, get_notes), (self._tasks_box, get_tasks)):
            text = fn()
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", text)
            box.configure(state="disabled")


def run_gui(assistant):
    """Запускает GUI-режим Джарвиса."""
    app = JarvisApp(assistant)
    app.mainloop()
