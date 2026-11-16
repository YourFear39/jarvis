"""
GUI-интерфейс Джарвиса — JARVIS STARK HUD.
"""

import math
import threading
import queue
import random
from datetime import datetime

import customtkinter as ctk
import tkinter as tk

import config

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Цветовая палитра ──────────────────────────────────────────────────────────
C = {
    "bg":             "#020609",
    "bg_panel":       "#030d14",
    "bg_msg_jarvis":  "#04101a",
    "bg_msg_user":    "#060e06",
    "bg_input":       "#030c12",
    "accent":         "#00c8ff",
    "accent_dim":     "#00253a",
    "accent_bright":  "#55e8ff",
    "text":           "#a0d0e4",
    "text_dim":       "#1c4258",
    "text_jarvis":    "#00c8ff",
    "text_user":      "#58b868",
    "text_system":    "#184860",
    "green":          "#00e87a",
    "yellow":         "#ff9500",
    "red":            "#e02840",
    "border":         "#061c28",
    "border_bright":  "#0e4458",
    "border_jarvis":  "#004460",
    "border_user":    "#164010",
}

_STATE_COLOR = {
    "idle":      "#00c8ff",
    "listening": "#00e87a",
    "thinking":  "#ff9500",
    "speaking":  "#e8f8ff",
}
_STATE_DIM = {
    "idle":      "#003850",
    "listening": "#004030",
    "thinking":  "#3a2800",
    "speaking":  "#2a3840",
}

TOOL_PHRASES = {
    "web_search":       "Ищу в интернете, сэр...",
    "add_note":         "Записываю заметку, сэр...",
    "get_notes":        "Проверяю заметки...",
    "add_task":         "Добавляю задачу, сэр...",
    "get_tasks":        "Смотрю список задач...",
    "complete_task":    "Отмечаю задачу выполненной, сэр.",
    "delete_task":      "Удаляю задачу, сэр.",
    "delete_note":      "Удаляю заметку, сэр.",
    "read_file":        "Читаю файл...",
    "create_plan":      "Составляю план, сэр...",
    "get_plan":         "Проверяю планы...",
    "update_plan_step": "Обновляю план...",
}

FONT = "Consolas"

_RAIN_CHARS = (
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホ"
    "マミムメモヤユヨラリルレロワヲン"
    "0123456789ABCDEFabcdef"
    "><[]{}|\\/#@!$%01"
)


def _font(size=12, bold=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


# ── Главный класс ─────────────────────────────────────────────────────────────

class JarvisApp(ctk.CTk):

    def __init__(self, assistant):
        super().__init__()

        self._assistant      = assistant
        self._busy           = False
        self._voice_active   = False
        self._voice_mode     = False
        self._voice_output   = False
        self._wake_active    = False
        self._wake_detector  = None
        self._thinking_frame = None
        self._history: list[str] = []
        self._hist_idx: int = -1

        self._q:     queue.Queue = queue.Queue()
        self._tts    = None
        self._stt    = None
        self._tts_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._tts_worker, daemon=True).start()

        # Splash animation state
        self._splash_canvas: tk.Canvas | None = None
        self._rain_running    = False
        self._rain_cols_data: list = []
        self._splash_dots     = 0
        self._loading_text_id = None

        # HUD animation state
        self._minimized       = False
        self._state           = "idle"
        self._reactor_angle   = 0.0
        self._wave_phase      = 0.0
        self._reactor_canvas: tk.Canvas | None = None
        self._wave_canvas:    tk.Canvas | None = None
        self._status_lbl:     ctk.CTkLabel | None = None
        self._cpu_lbl:        ctk.CTkLabel | None = None
        self._ram_lbl:        ctk.CTkLabel | None = None
        self._cpu_bar:        ctk.CTkProgressBar | None = None
        self._ram_bar:        ctk.CTkProgressBar | None = None

        self._setup_window()
        self._show_splash()

    # ── window ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.title("JARVIS — AI Assistant")
        self.geometry("1300x820")
        self.minsize(1000, 660)
        self.configure(fg_color=C["bg"])
        try:
            import os
            ico = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "jarvis.ico")
            self.iconbitmap(ico)
        except Exception:
            pass

    # ════════════════════════════════════════════════════════════════════════
    # SPLASH SCREEN
    # ════════════════════════════════════════════════════════════════════════

    def _show_splash(self):
        self._splash_canvas = tk.Canvas(self, bg="#030810", highlightthickness=0)
        self._splash_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.update_idletasks()
        self.after(80, self._init_splash_content)

    def _init_splash_content(self):
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 200:
            self.after(80, self._init_splash_content)
            return
        self._rain_w = w
        self._rain_h = h
        self._init_code_rain(w, h)
        self._rain_running = True
        self._animate_code_rain()
        cx = w // 2
        cy = h // 2 - 35
        r  = int(min(w, h) * 0.27)
        self._draw_ironman_mask(cx, cy, r)
        self.after(4400, self._launch_main)

    def _init_code_rain(self, w: int, h: int):
        col_w = 22
        num_cols = w // col_w + 2
        self._rain_cols_data = [
            {
                "x":      i * col_w + col_w // 2,
                "y":      random.randint(-h, 0),
                "speed":  random.uniform(3.5, 12.0),
                "length": random.randint(10, 34),
            }
            for i in range(num_cols)
        ]

    def _animate_code_rain(self):
        if not self._rain_running or self._splash_canvas is None:
            return
        canvas = self._splash_canvas
        canvas.delete("rain")
        h = self._rain_h

        for col in self._rain_cols_data:
            col["y"] += col["speed"]
            if col["y"] > h + col["length"] * 18:
                col["y"]      = random.randint(-400, -30)
                col["speed"]  = random.uniform(3.5, 12.0)
                col["length"] = random.randint(10, 34)

            for j in range(col["length"]):
                cy_char = col["y"] - j * 18
                if cy_char < -20 or cy_char > h + 20:
                    continue
                if j == 0:
                    color, sz = "#d0ffff", 14
                elif j < 3:
                    color, sz = "#55e8ff", 13
                elif j < 8:
                    color, sz = "#00d4ff", 13
                elif j < 16:
                    color, sz = "#005870", 13
                elif j < 25:
                    color, sz = "#002535", 12
                else:
                    color, sz = "#001020", 12
                canvas.create_text(
                    col["x"], cy_char,
                    text=random.choice(_RAIN_CHARS),
                    font=("Consolas", sz),
                    fill=color,
                    tags="rain",
                )

        canvas.tag_lower("rain")
        self.after(52, self._animate_code_rain)

    def _draw_ironman_mask(self, cx: int, cy: int, r: int):
        cv = self._splash_canvas

        def pt(dx: float, dy: float) -> tuple[float, float]:
            return cx + r * dx, cy + r * dy

        glow_cols = ["#001525", "#002035", "#002f4a", "#003d60", "#004d78", "#005d8e"]
        for i, gc in enumerate(glow_cols, start=1):
            pad = (len(glow_cols) - i + 1) * 5
            cv.create_oval(
                cx - r - pad, cy - r - pad,
                cx + r + pad, cy + r + pad,
                outline=gc, width=2, tags="mask",
            )

        cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                       fill="#04090f", outline="#00d4ff", width=3, tags="mask")
        cv.create_oval(cx - r + 7, cy - r + 7, cx + r - 7, cy + r - 7,
                       outline="#003850", width=1, fill="", tags="mask")

        face = [
            *pt(0,     -0.88), *pt(0.52,  -0.66), *pt(0.74,  -0.24),
            *pt(0.68,   0.30), *pt(0.42,   0.67), *pt(0,      0.80),
            *pt(-0.42,  0.67), *pt(-0.68,  0.30), *pt(-0.74, -0.24),
            *pt(-0.52, -0.66),
        ]
        cv.create_polygon(face, fill="#030810", outline="#0a1e2e", width=1, tags="mask")

        forehead = [
            *pt(0,     -0.88), *pt(0.33,  -0.70), *pt(0.28,  -0.40),
            *pt(0,     -0.36), *pt(-0.28, -0.40), *pt(-0.33, -0.70),
        ]
        cv.create_polygon(forehead, fill="#030c1c", outline="#004060", width=1, tags="mask")
        cv.create_line(*pt(0, -0.88), *pt(0, -0.36), fill="#005070", width=2, tags="mask")
        for y_frac, x_frac in [(-0.74, 0.10), (-0.60, 0.20), (-0.47, 0.26)]:
            cv.create_line(cx - r * x_frac, cy + r * y_frac,
                           cx + r * x_frac, cy + r * y_frac,
                           fill="#003050", width=1, tags="mask")

        lc = [
            *pt(-0.28, -0.40), *pt(-0.52, -0.66), *pt(-0.74, -0.24),
            *pt(-0.68,  0.14), *pt(-0.42, -0.06), *pt(-0.30, -0.18),
        ]
        cv.create_polygon(lc, fill="#030a14", outline="#003850", width=1, tags="mask")
        cv.create_line(*pt(-0.43, -0.20), *pt(-0.70,  0.06), fill="#005070", width=1, tags="mask")
        cv.create_line(*pt(-0.44,  0.04), *pt(-0.66,  0.26), fill="#003850", width=1, tags="mask")

        rc = [
            *pt(0.28, -0.40), *pt(0.52, -0.66), *pt(0.74, -0.24),
            *pt(0.68,  0.14), *pt(0.42, -0.06), *pt(0.30, -0.18),
        ]
        cv.create_polygon(rc, fill="#030a14", outline="#003850", width=1, tags="mask")
        cv.create_line(*pt(0.43, -0.20), *pt(0.70,  0.06), fill="#005070", width=1, tags="mask")
        cv.create_line(*pt(0.44,  0.04), *pt(0.66,  0.26), fill="#003850", width=1, tags="mask")

        ey = cy - r * 0.20
        ew = r * 0.28
        eh = r * 0.10

        def _draw_eye(ex: float):
            for expand, gc in [(7, "#001a28"), (4, "#003d5a"), (2, "#006080")]:
                cv.create_polygon(
                    [ex - ew - expand, ey + eh * 0.4,
                     ex - ew * 0.55,   ey - eh - expand,
                     ex + ew * 0.55,   ey - eh - expand,
                     ex + ew + expand, ey + eh * 0.4,
                     ex + ew * 0.55,   ey + eh + expand,
                     ex - ew * 0.55,   ey + eh + expand],
                    fill="", outline=gc, width=1, tags="mask",
                )
            eye_pts = [
                ex - ew,       ey + eh * 0.4,
                ex - ew * 0.5, ey - eh,
                ex + ew * 0.5, ey - eh,
                ex + ew,       ey + eh * 0.4,
                ex + ew * 0.5, ey + eh,
                ex - ew * 0.5, ey + eh,
            ]
            cv.create_polygon(eye_pts, fill="#00b0d8", outline="#55e8ff", width=2, tags="mask")
            cv.create_oval(ex - ew * 0.28, ey - eh * 0.42,
                           ex + ew * 0.28, ey + eh * 0.42,
                           fill="white", outline="", tags="mask")

        _draw_eye(cx - r * 0.31)
        _draw_eye(cx + r * 0.31)

        cv.create_line(*pt(0, -0.06), *pt(0, 0.23), fill="#003850", width=3, tags="mask")

        for y_frac, w_frac, col, thick in [
            (0.30, 0.40, "#005878", 2), (0.38, 0.36, "#004060", 1),
            (0.44, 0.30, "#003050", 1), (0.49, 0.24, "#002540", 1),
        ]:
            cv.create_line(cx - r * w_frac, cy + r * y_frac,
                           cx + r * w_frac, cy + r * y_frac,
                           fill=col, width=thick, tags="mask")

        chin = [
            *pt(-0.38, 0.53), *pt(0, 0.74), *pt(0.38, 0.53),
            *pt(0.42,  0.67), *pt(0, 0.82), *pt(-0.42, 0.67),
        ]
        cv.create_polygon(chin, fill="#030c18", outline="#003850", width=1, tags="mask")
        cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                       outline="#00d4ff", width=2, fill="", tags="mask")

        cv.create_text(cx, cy + r + 36, text="J.A.R.V.I.S",
                       font=("Consolas", 22, "bold"), fill="#00d4ff", tags="mask")
        cv.create_text(cx, cy + r + 62, text="ЛИЧНЫЙ ИИ-АССИСТЕНТ",
                       font=("Consolas", 12), fill="#005870", tags="mask")

        self._loading_text_id = cv.create_text(
            cx, cy + r + 88, text="●  ○  ○",
            font=("Consolas", 14), fill="#003850", tags="mask",
        )
        self._animate_splash_dots()

    def _animate_splash_dots(self):
        if self._splash_canvas is None or self._loading_text_id is None:
            return
        patterns = ["●  ○  ○", "○  ●  ○", "○  ○  ●", "○  ●  ○"]
        self._splash_dots = (self._splash_dots + 1) % 4
        try:
            self._splash_canvas.itemconfig(
                self._loading_text_id, text=patterns[self._splash_dots]
            )
        except Exception:
            return
        self.after(460, self._animate_splash_dots)

    def _launch_main(self):
        self._rain_running = False
        if self._splash_canvas:
            self._splash_canvas.destroy()
            self._splash_canvas = None
        self._build_ui()
        self._refresh_side_panel()
        self._update_clock()
        self._poll_queue()
        self._tick_reactor()
        self._tick_wave()
        self._poll_sysmon()
        from voice.wake_audio import get_wake_audio
        get_wake_audio().prebuild_async()

    # ════════════════════════════════════════════════════════════════════════
    # MAIN UI
    # ════════════════════════════════════════════════════════════════════════

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=C["bg_panel"], height=60, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkFrame(self, fg_color=C["accent"], height=1, corner_radius=0).pack(fill="x")
        ctk.CTkFrame(self, fg_color=C["border_jarvis"], height=1, corner_radius=0).pack(fill="x")

        row = ctk.CTkFrame(hdr, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 0))

        ctk.CTkLabel(
            row, text="◈  J.A.R.V.I.S",
            font=_font(20, bold=True), text_color=C["accent"],
        ).pack(side="left")
        ctk.CTkLabel(
            row, text="  //  PERSONAL AI  v2.1",
            font=_font(9), text_color=C["text_dim"],
        ).pack(side="left")

        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right")

        self._clock_lbl = ctk.CTkLabel(
            right, text="00:00:00",
            font=_font(14, bold=True), text_color=C["accent"],
        )
        self._clock_lbl.pack(side="right", padx=14)

        self._wake_btn = ctk.CTkButton(
            right, text="○  WAKE",
            width=90, height=26, font=_font(10),
            fg_color="transparent",
            border_color=C["text_dim"], border_width=1,
            text_color=C["text_dim"],
            hover_color=C["border"],
            corner_radius=4,
            command=self._on_wake_toggle,
        )
        self._wake_btn.pack(side="right", padx=4)

        self._info_lbl = ctk.CTkLabel(
            hdr, text=self._info_text(),
            font=_font(9), text_color=C["text_dim"], anchor="w",
        )
        self._info_lbl.pack(fill="x", padx=14, pady=(2, 4))

    def _info_text(self) -> str:
        mem  = "ВКЛ" if self._assistant._memory.is_available else "ВЫКЛ"
        wake = "ВКЛ ◉" if self._wake_active else "ВЫКЛ"
        tts  = "ВКЛ ♪" if self._voice_output else "ВЫКЛ"
        return (
            f"LLM ▸ {config.LLM_PROVIDER.upper()}  "
            f"·  ПАМЯТЬ ▸ {mem}  "
            f"·  WAKE ▸ {wake}  "
            f"·  ГОЛОС ▸ {tts}"
        )

    def _update_info_strip(self):
        self._info_lbl.configure(text=self._info_text())

    def _update_clock(self):
        self._clock_lbl.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self._update_clock)

    def _build_ui(self):
        from core.local_handler import set_tts_callback
        set_tts_callback(self._scenario_tts)
        self._build_header()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        body.grid_columnconfigure(0, minsize=190, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, minsize=220, weight=0)
        body.grid_rowconfigure(0, weight=1)

        self._build_left_panel(body)
        self._build_chat_panel(body)
        self._build_right_panel(body)

        self.bind("<Unmap>", self._on_win_unmap)
        self.bind("<Map>",   self._on_win_map)

    # ── left panel: arc reactor + waveform ───────────────────────────────────

    def _build_left_panel(self, parent):
        panel = ctk.CTkFrame(
            parent,
            fg_color=C["bg_panel"],
            border_color=C["border"], border_width=1,
            corner_radius=8,
        )
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel, text="◈  ARC REACTOR",
            font=_font(9, bold=True), text_color=C["accent"],
        ).grid(row=0, column=0, pady=(10, 4))

        self._reactor_canvas = tk.Canvas(
            panel, width=160, height=150,
            bg=C["bg"], highlightthickness=0,
        )
        self._reactor_canvas.grid(row=1, column=0, pady=(0, 4))

        self._status_lbl = ctk.CTkLabel(
            panel, text="● ONLINE",
            font=_font(11, bold=True), text_color=C["green"],
        )
        self._status_lbl.grid(row=2, column=0, pady=(0, 6))

        ctk.CTkFrame(panel, fg_color=C["border"], height=1).grid(
            row=3, column=0, sticky="ew", padx=8, pady=2,
        )

        ctk.CTkLabel(
            panel, text="◈  SIGNAL",
            font=_font(9, bold=True), text_color=C["text_dim"],
        ).grid(row=4, column=0, pady=(4, 2))

        self._wave_canvas = tk.Canvas(
            panel, width=164, height=44,
            bg=C["bg"], highlightthickness=0,
        )
        self._wave_canvas.grid(row=5, column=0, pady=(0, 8))

    # ── chat panel ────────────────────────────────────────────────────────────

    def _build_chat_panel(self, parent):
        frame = ctk.CTkFrame(
            parent,
            fg_color=C["bg_panel"],
            border_color=C["border"], border_width=1,
            corner_radius=8,
        )
        frame.grid(row=0, column=1, sticky="nsew", padx=4)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self._chat_scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=C["bg"],
            scrollbar_fg_color=C["bg_panel"],
            scrollbar_button_color=C["accent_dim"],
            scrollbar_button_hover_color=C["border_bright"],
            corner_radius=0,
        )
        self._chat_scroll.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self._chat_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(frame, fg_color=C["border"], height=1, corner_radius=0)\
            .grid(row=1, column=0, sticky="ew")

        inp = ctk.CTkFrame(frame, fg_color=C["bg_input"], corner_radius=0)
        inp.grid(row=2, column=0, sticky="ew")
        inp.grid_columnconfigure(0, weight=1)

        self._input = ctk.CTkEntry(
            inp,
            font=_font(13),
            fg_color="transparent", text_color=C["text"],
            border_width=0,
            placeholder_text="Введи сообщение... (Enter — отправить, ↑↓ — история)",
            placeholder_text_color=C["text_dim"],
            height=48,
        )
        self._input.grid(row=0, column=0, sticky="ew", padx=(16, 6))
        self._input.bind("<Return>", self._on_send)
        self._input.bind("<Up>",     self._history_up)
        self._input.bind("<Down>",   self._history_down)

        self._send_btn = ctk.CTkButton(
            inp, text="▶  ОТПРАВИТЬ",
            width=148, height=36, font=_font(12, bold=True),
            fg_color=C["accent"], hover_color=C["accent_bright"],
            text_color=C["bg"], corner_radius=5,
            command=self._on_send,
        )
        self._send_btn.grid(row=0, column=1, padx=(0, 6), pady=6)

        self._mic_btn = ctk.CTkButton(
            inp, text="🎤",
            width=48, height=36, font=_font(18),
            fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"], corner_radius=5,
            command=self._on_mic_click,
        )
        self._mic_btn.grid(row=0, column=2, padx=(0, 4), pady=6)

        self._voice_out_btn = ctk.CTkButton(
            inp, text="🔇",
            width=48, height=36, font=_font(18),
            fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text_dim"], corner_radius=5,
            command=self._on_voice_output_toggle,
        )
        self._voice_out_btn.grid(row=0, column=3, padx=(0, 12), pady=6)

        self._append_system("СИСТЕМА ИНИЦИАЛИЗИРОВАНА  ·  ВВЕДИ СООБЩЕНИЕ ИЛИ НАЖМИ 🎤")

    # ── right panel: sysmon + notes + tasks ───────────────────────────────────

    def _build_right_panel(self, parent):
        side = ctk.CTkFrame(
            parent,
            fg_color=C["bg_panel"],
            border_color=C["border"], border_width=1,
            corner_radius=8,
        )
        side.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(5, weight=2)   # notes box
        side.grid_rowconfigure(9, weight=3)   # tasks box

        # ── sys monitor ──────────────────────────────────────────────────────
        self._side_label(side, "◈  СИСТЕМА", row=0)

        cpu_row = ctk.CTkFrame(side, fg_color="transparent")
        cpu_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 3))
        cpu_row.grid_columnconfigure(1, weight=1)

        self._cpu_lbl = ctk.CTkLabel(
            cpu_row, text="CPU  ---%",
            font=_font(9), text_color=C["accent"], width=64, anchor="w",
        )
        self._cpu_lbl.grid(row=0, column=0, padx=(0, 4))
        self._cpu_bar = ctk.CTkProgressBar(
            cpu_row, height=6,
            fg_color=C["border"], progress_color=C["accent"],
            corner_radius=3,
        )
        self._cpu_bar.grid(row=0, column=1, sticky="ew")
        self._cpu_bar.set(0)

        ram_row = ctk.CTkFrame(side, fg_color="transparent")
        ram_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        ram_row.grid_columnconfigure(1, weight=1)

        self._ram_lbl = ctk.CTkLabel(
            ram_row, text="RAM  ---%",
            font=_font(9), text_color=C["yellow"], width=64, anchor="w",
        )
        self._ram_lbl.grid(row=0, column=0, padx=(0, 4))
        self._ram_bar = ctk.CTkProgressBar(
            ram_row, height=6,
            fg_color=C["border"], progress_color=C["yellow"],
            corner_radius=3,
        )
        self._ram_bar.grid(row=0, column=1, sticky="ew")
        self._ram_bar.set(0)

        ctk.CTkFrame(side, fg_color=C["border"], height=1)\
            .grid(row=3, column=0, sticky="ew", padx=0)

        # ── notes ─────────────────────────────────────────────────────────────
        self._side_label(side, "◈  ЗАМЕТКИ", row=4)

        self._notes_box = ctk.CTkTextbox(
            side, font=_font(11), fg_color=C["bg"],
            text_color=C["text"], border_width=0, state="disabled",
        )
        self._notes_box.grid(row=5, column=0, sticky="nsew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            side, text="＋  Добавить заметку",
            height=28, font=_font(11), corner_radius=4,
            fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"],
            command=self._dialog_add_note,
        ).grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 4))

        ctk.CTkFrame(side, fg_color=C["border"], height=1)\
            .grid(row=7, column=0, sticky="ew", padx=0)

        # ── tasks ─────────────────────────────────────────────────────────────
        self._side_label(side, "◈  ЗАДАЧИ", row=8, pady_top=6)

        self._tasks_box = ctk.CTkTextbox(
            side, font=_font(11), fg_color=C["bg"],
            text_color=C["text"], border_width=0, state="disabled",
        )
        self._tasks_box.grid(row=9, column=0, sticky="nsew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            side, text="＋  Добавить задачу",
            height=28, font=_font(11), corner_radius=4,
            fg_color=C["accent_dim"], hover_color=C["border_bright"],
            text_color=C["text"],
            command=self._dialog_add_task,
        ).grid(row=10, column=0, sticky="ew", padx=8, pady=(0, 4))

        ctk.CTkButton(
            side, text="↻  Обновить",
            height=26, font=_font(10), corner_radius=4,
            fg_color="transparent", hover_color=C["border"],
            text_color=C["text_dim"],
            border_color=C["border"], border_width=1,
            command=self._refresh_side_panel,
        ).grid(row=11, column=0, sticky="ew", padx=8, pady=(0, 10))

    def _side_label(self, parent, text, row, pady_top=8):
        ctk.CTkLabel(
            parent, text=text,
            font=_font(11, bold=True), text_color=C["accent"],
        ).grid(row=row, column=0, sticky="w", padx=14, pady=(pady_top, 4))

    # ════════════════════════════════════════════════════════════════════════
    # HUD ANIMATIONS
    # ════════════════════════════════════════════════════════════════════════

    def _on_win_unmap(self, event):
        if event.widget is self:
            self._minimized = True

    def _on_win_map(self, event):
        if event.widget is self:
            self._minimized = False

    # ── arc reactor ───────────────────────────────────────────────────────────

    def _tick_reactor(self):
        self._draw_reactor()
        delay = 2000 if self._minimized else 50
        self.after(delay, self._tick_reactor)

    def _draw_reactor(self):
        cv = self._reactor_canvas
        if cv is None:
            return
        cv.delete("all")
        cx, cy = 80, 75
        color = _STATE_COLOR.get(self._state, "#00c8ff")
        dim   = _STATE_DIM.get(self._state, "#003850")

        # Outer glow rings
        for pad, gc in [(18, "#000e18"), (12, "#001220"), (6, "#001c2e")]:
            cv.create_oval(cx - 54 - pad, cy - 54 - pad,
                           cx + 54 + pad, cy + 54 + pad,
                           outline=gc, width=1)

        # Main outer ring
        cv.create_oval(cx - 54, cy - 54, cx + 54, cy + 54,
                       outline=color, width=2, fill=C["bg"])

        # 6 rotating arc segments
        for k in range(6):
            start = self._reactor_angle + k * 60
            cv.create_arc(cx - 46, cy - 46, cx + 46, cy + 46,
                          start=start, extent=28,
                          outline=color, width=2, style="arc")

        # Middle ring
        cv.create_oval(cx - 30, cy - 30, cx + 30, cy + 30,
                       outline=dim, width=1, fill=C["bg"])

        # Inner hex (counter-rotating slowly)
        hex_r = 16
        hex_a = -self._reactor_angle * 0.5
        hex_pts = []
        for k in range(6):
            a = math.radians(hex_a + k * 60)
            hex_pts.extend([cx + hex_r * math.cos(a), cy + hex_r * math.sin(a)])
        cv.create_polygon(hex_pts, fill=dim, outline=color, width=1)

        # Pulsing core
        pulse  = 0.85 + 0.15 * math.sin(math.radians(self._reactor_angle * 3))
        r_core = max(6, int(10 * pulse))
        cv.create_oval(cx - r_core, cy - r_core, cx + r_core, cy + r_core,
                       fill=color, outline="")
        r_bright = max(3, r_core // 2)
        cv.create_oval(cx - r_bright, cy - r_bright, cx + r_bright, cy + r_bright,
                       fill="white", outline="")

        self._reactor_angle = (self._reactor_angle + 1.8) % 360

    # ── waveform ──────────────────────────────────────────────────────────────

    def _tick_wave(self):
        if not self._minimized:
            self._draw_waveform()
        delay = 2000 if self._minimized else 60
        self.after(delay, self._tick_wave)

    def _draw_waveform(self):
        cv = self._wave_canvas
        if cv is None:
            return
        cv.delete("all")
        W, H = 164, 44
        N    = 14
        bar_w = max(4, (W - N - 2) // N)
        color = _STATE_COLOR.get(self._state, "#00c8ff")
        dim   = _STATE_DIM.get(self._state, "#003850")

        for i in range(N):
            if self._state == "listening":
                h_frac = 0.3 + 0.6 * abs(math.sin(self._wave_phase + i * 0.7))
                h_frac += random.uniform(-0.1, 0.1)
            elif self._state == "speaking":
                h_frac = 0.2 + 0.65 * abs(math.sin(self._wave_phase * 1.3 + i * 0.5))
            elif self._state == "thinking":
                h_frac = 0.08 + 0.06 * abs(math.sin(self._wave_phase * 0.4 + i * 0.8))
            else:
                h_frac = 0.07

            h_frac = max(0.04, min(0.95, h_frac))
            bar_h  = max(2, int(H * h_frac))
            x0 = i * (bar_w + 1) + 2
            x1 = x0 + bar_w
            y0 = (H - bar_h) // 2
            y1 = y0 + bar_h
            cv.create_rectangle(x0, y0, x1, y1,
                                 fill=(color if h_frac > 0.25 else dim), outline="")

        self._wave_phase = (self._wave_phase + 0.12) % (math.pi * 200)

    # ── sysmon ────────────────────────────────────────────────────────────────

    def _poll_sysmon(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None) / 100.0
            ram = psutil.virtual_memory().percent / 100.0
            if self._cpu_bar:
                self._cpu_bar.set(cpu)
            if self._ram_bar:
                self._ram_bar.set(ram)
            if self._cpu_lbl:
                self._cpu_lbl.configure(text=f"CPU  {cpu*100:.0f}%")
            if self._ram_lbl:
                self._ram_lbl.configure(text=f"RAM  {ram*100:.0f}%")
        except Exception:
            pass
        delay = 10000 if self._minimized else 2000
        self.after(delay, self._poll_sysmon)

    # ════════════════════════════════════════════════════════════════════════
    # MESSAGE DISPLAY
    # ════════════════════════════════════════════════════════════════════════

    def _append_message(self, role: str, text: str, animate: bool = False):
        now = datetime.now().strftime("%H:%M")

        if role == "jarvis":
            bubble = ctk.CTkFrame(
                self._chat_scroll,
                fg_color=C["bg_msg_jarvis"],
                border_color=C["border_jarvis"],
                border_width=1,
                corner_radius=7,
            )
            bubble.pack(fill="x", padx=(6, 72), pady=(3, 1))

            hdr_row = ctk.CTkFrame(bubble, fg_color="transparent")
            hdr_row.pack(fill="x", padx=14, pady=(8, 3))

            ctk.CTkLabel(
                hdr_row,
                text=f"◈  JARVIS   [{now}]",
                font=_font(11, bold=True),
                text_color=C["accent"],
                anchor="w",
            ).pack(side="left")

            def _copy_text(t=text):
                self.clipboard_clear()
                self.clipboard_append(t)

            ctk.CTkButton(
                hdr_row, text="⎘",
                width=26, height=20, font=_font(11),
                fg_color="transparent",
                hover_color=C["border"],
                text_color=C["text_dim"],
                corner_radius=3,
                command=_copy_text,
            ).pack(side="right")

            body_lbl = ctk.CTkLabel(
                bubble,
                text="" if animate else text,
                font=_font(13),
                text_color=C["text"],
                anchor="w",
                justify="left",
                wraplength=700,
            )
            body_lbl.pack(fill="x", padx=14, pady=(0, 10))
            bubble.bind(
                "<Configure>",
                lambda e, b=body_lbl: b.configure(wraplength=max(80, e.width - 28)),
                add=True,
            )

            ctx = tk.Menu(self, tearoff=0, bg=C["bg_panel"], fg=C["text"],
                          activebackground=C["accent_dim"], activeforeground=C["accent"],
                          bd=0, relief="flat")
            ctx.add_command(label="  Копировать ответ  ", command=_copy_text)

            def _show_ctx(e, m=ctx):
                m.tk_popup(e.x_root, e.y_root)

            for widget in (bubble, hdr_row, body_lbl):
                widget.bind("<Button-3>", _show_ctx)

            if animate:
                self._animate_typing(body_lbl, text)

        elif role == "user":
            bubble = ctk.CTkFrame(
                self._chat_scroll,
                fg_color=C["bg_msg_user"],
                border_color=C["border_user"],
                border_width=1,
                corner_radius=7,
            )
            bubble.pack(fill="x", padx=(72, 6), pady=(3, 1))

            ctk.CTkLabel(
                bubble,
                text=f"[{now}]   ВЫ  ▷",
                font=_font(11, bold=True),
                text_color=C["yellow"],
                anchor="e",
            ).pack(fill="x", padx=14, pady=(8, 3))

            body_lbl = ctk.CTkLabel(
                bubble,
                text=text,
                font=_font(13),
                text_color=C["text_user"],
                anchor="e",
                justify="right",
                wraplength=700,
            )
            body_lbl.pack(fill="x", padx=14, pady=(0, 10))
            bubble.bind(
                "<Configure>",
                lambda e, b=body_lbl: b.configure(wraplength=max(80, e.width - 28)),
                add=True,
            )

        self._scroll_bottom()

    def _animate_typing(self, label, text: str, delay: int = 0):
        words = text.split()
        if not words:
            label.configure(text=text)
            return
        if len(words) > 60:
            delay = 12
        elif len(words) > 25:
            delay = 20
        else:
            delay = 30

        def _reveal(i: int):
            if i > len(words):
                return
            label.configure(text=" ".join(words[:i]))
            if i < len(words):
                self.after(delay, lambda: _reveal(i + 1))
        _reveal(1)

    def _append_system(self, text: str):
        f = ctk.CTkFrame(self._chat_scroll, fg_color="transparent")
        f.pack(fill="x", pady=3)
        ctk.CTkLabel(
            f,
            text=f"  [ {text} ]",
            font=_font(10),
            text_color=C["text_system"],
        ).pack(anchor="center")
        self._scroll_bottom()

    def _append_tool(self, tool_name: str):
        labels = {
            "web_search":       "поиск в интернете",
            "add_note":         "сохранение заметки",
            "get_notes":        "чтение заметок",
            "add_task":         "добавление задачи",
            "get_tasks":        "чтение задач",
            "complete_task":    "завершение задачи",
            "delete_task":      "удаление задачи",
            "delete_note":      "удаление заметки",
            "read_file":        "чтение файла",
            "create_plan":      "создание плана",
            "get_plan":         "чтение плана",
            "update_plan_step": "обновление плана",
        }
        f = ctk.CTkFrame(self._chat_scroll, fg_color="transparent")
        f.pack(fill="x", pady=1)
        ctk.CTkLabel(
            f,
            text=f"  ⚙  {labels.get(tool_name, tool_name)}...",
            font=_font(11),
            text_color=C["accent_dim"],
        ).pack(anchor="w", padx=20)
        self._scroll_bottom()

    def _append_voice_in(self, text: str):
        f = ctk.CTkFrame(self._chat_scroll, fg_color="transparent")
        f.pack(fill="x", pady=1)
        ctk.CTkLabel(
            f,
            text=f"  🎤  «{text}»",
            font=_font(11),
            text_color="#9977ee",
        ).pack(anchor="e", padx=20)
        self._scroll_bottom()

    def _scroll_bottom(self):
        self.after(30, lambda: self._chat_scroll._parent_canvas.yview_moveto(1.0))

    # ── thinking indicator ────────────────────────────────────────────────────

    def _show_thinking(self):
        f = ctk.CTkFrame(
            self._chat_scroll,
            fg_color=C["bg_msg_jarvis"],
            border_color=C["border_jarvis"], border_width=1,
            corner_radius=7,
        )
        f.pack(fill="x", padx=(6, 72), pady=(3, 1))

        ctk.CTkLabel(
            f, text="◈  JARVIS  ·  ОБРАБОТКА",
            font=_font(11, bold=True), text_color=C["accent"], anchor="w",
        ).pack(fill="x", padx=14, pady=(8, 2))

        self._dots_lbl = ctk.CTkLabel(
            f, text="●  ○  ○",
            font=_font(13), text_color=C["accent_dim"], anchor="w",
        )
        self._dots_lbl.pack(fill="x", padx=14, pady=(0, 10))

        self._thinking_frame = f
        self._scroll_bottom()
        self._animate_dots(0)

    def _animate_dots(self, step: int):
        if not self._thinking_frame:
            return
        patterns = ["●  ○  ○", "○  ●  ○", "○  ○  ●", "○  ●  ○"]
        try:
            self._dots_lbl.configure(text=patterns[step % 4])
            self.after(380, lambda: self._animate_dots(step + 1))
        except Exception:
            pass

    def _hide_thinking(self):
        if self._thinking_frame:
            try:
                self._thinking_frame.destroy()
            except Exception:
                pass
            self._thinking_frame = None

    # ── state ─────────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self._state = "thinking"
            self._send_btn.configure(
                text="⟳  ОБРАБОТКА...", state="disabled",
                fg_color=C["accent_dim"],
            )
            self._input.configure(state="disabled")
            self._status_lbl.configure(text="● ОБРАБОТКА...", text_color=C["yellow"])
            self._show_thinking()
        else:
            self._state = "idle"
            self._hide_thinking()
            self._send_btn.configure(
                text="▶  ОТПРАВИТЬ", state="normal",
                fg_color=C["accent"],
            )
            self._input.configure(state="normal")
            self._status_lbl.configure(text="● ONLINE", text_color=C["green"])
            self._input.focus()
            if self._wake_active and self._wake_detector:
                self._wake_detector.resume()

    def _set_recording(self, active: bool):
        if active:
            self._state = "listening"
            self._mic_btn.configure(text="⏹", fg_color=C["red"])
            self._status_lbl.configure(text="● СЛУШАЮ...", text_color=C["red"])
        else:
            if not self._busy:
                self._state = "idle"
            self._mic_btn.configure(text="🎤", fg_color=C["accent_dim"])

    def _set_speaking(self, active: bool):
        if active:
            self._state = "speaking"
            self._status_lbl.configure(text="● ГОВОРЮ...", text_color=C["accent"])
        else:
            if not self._busy:
                self._state = "idle"
                self._status_lbl.configure(text="● ONLINE", text_color=C["green"])

    # ── connection error ──────────────────────────────────────────────────────

    def _handle_conn_error(self, err: str, user_text: str):
        from core.offline import handle_offline, offline_help

        offline_response = handle_offline(user_text)
        if offline_response:
            self._append_message("jarvis", offline_response, animate=True)
            self._append_system("ОТВЕТ БЕЗ LLM  ·  ОФЛАЙН-РЕЖИМ")
            self._set_busy(False)
            if self._voice_mode:
                self._enqueue_tts(offline_response)
            return

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

        msg = offline_help()
        self._append_message("jarvis", msg)
        if self._voice_mode:
            self._enqueue_tts("Нет связи с сервером, сэр. Работаю в офлайн-режиме.")
        self._set_busy(False)

    # ── send / worker ─────────────────────────────────────────────────────────

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
            for widget in self._chat_scroll.winfo_children():
                widget.destroy()
            self._append_system("ЭКРАН ОЧИЩЕН")
            return

        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._hist_idx = -1

        self._voice_mode = from_voice or self._voice_output
        self._input.delete(0, "end")
        self._append_message("user", text)
        self._set_busy(True)

        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text: str):
        # Захватываем флаг активности — если окно закроется пока работаем,
        # callback не будет обращаться к уже уничтоженным виджетам
        app_ref = self

        def tool_cb(name: str):
            try:
                app_ref._q.put(("tool", name))
                if app_ref._voice_mode:
                    phrase = TOOL_PHRASES.get(name)
                    if phrase:
                        app_ref._enqueue_tts(phrase)
            except Exception:
                pass  # окно уже уничтожено — игнорируем

        self._assistant._on_tool_use = tool_cb
        try:
            response = self._assistant.chat(text)
            self._q.put(("response", response))
        except ConnectionError as e:
            self._q.put(("conn_error", str(e), text))
        except Exception as e:
            self._q.put(("error", f"{type(e).__name__}: {e}"))

    # ── history navigation ────────────────────────────────────────────────────

    def _history_up(self, event=None):
        if not self._history:
            return
        self._hist_idx = max(0, (len(self._history) - 1) if self._hist_idx < 0
                             else self._hist_idx - 1)
        self._input.delete(0, "end")
        self._input.insert(0, self._history[self._hist_idx])

    def _history_down(self, event=None):
        if not self._history or self._hist_idx < 0:
            return
        self._hist_idx += 1
        if self._hist_idx >= len(self._history):
            self._hist_idx = -1
            self._input.delete(0, "end")
        else:
            self._input.delete(0, "end")
            self._input.insert(0, self._history[self._hist_idx])

    # ── queue poll ────────────────────────────────────────────────────────────

    def _poll_queue(self):
        refresh = False
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]

                if kind == "response":
                    self._append_message("jarvis", item[1], animate=True)
                    self._set_busy(False)
                    refresh = True
                    if self._voice_mode:
                        self._enqueue_tts(item[1])

                elif kind == "error":
                    self._append_system(f"ОШИБКА: {item[1]}")
                    self._set_busy(False)

                elif kind == "conn_error":
                    self._handle_conn_error(item[1], item[2])

                elif kind == "tool":
                    self._append_tool(item[1])

                elif kind == "rec_start":
                    self._set_recording(True)
                    self._append_system("СЛУШАЮ...")
                    if self._wake_active and self._wake_detector:
                        self._wake_detector.pause()

                elif kind == "rec_status":
                    self._append_system(item[1])

                elif kind == "rec_done":
                    self._set_recording(False)
                    recognized = item[1]
                    self._append_voice_in(recognized)
                    self._input.delete(0, "end")
                    self._input.insert(0, recognized)
                    self._on_send(from_voice=True)

                elif kind == "rec_empty":
                    self._set_recording(False)
                    self._state = "idle"
                    self._status_lbl.configure(text="● ONLINE", text_color=C["green"])
                    self._append_system(item[1])
                    self._voice_active = False
                    if self._wake_active and self._wake_detector:
                        self._wake_detector.resume()

                elif kind == "tts_start":
                    self._set_speaking(True)

                elif kind == "tts_done":
                    self._set_speaking(False)

                elif kind == "wake_command":
                    cmd = item[1]
                    self._append_voice_in(f"Джарвис, {cmd}")
                    self._enqueue_tts("Понял, сэр.")
                    self._input.delete(0, "end")
                    self._input.insert(0, cmd)
                    self._on_send(from_voice=True)

                elif kind == "wake_ready":
                    try:
                        from voice.wake_word import WakeWordDetector
                        self._wake_detector = WakeWordDetector(
                            self._stt, self._on_wake_word
                        )
                        self._wake_detector.start()
                        self._wake_btn.configure(
                            text="◉  WAKE", text_color=C["accent"],
                            border_color=C["accent"], fg_color=C["accent_dim"],
                        )
                        self._append_system(
                            "WAKE-WORD АКТИВИРОВАН  ·  СКАЖИ «ДЖАРВИС»"
                        )
                    except Exception as e:
                        self._wake_active = False
                        self._wake_btn.configure(
                            text="○  WAKE", text_color=C["text_dim"],
                            border_color=C["text_dim"], fg_color="transparent",
                        )
                        self._append_system(f"WAKE-WORD ОШИБКА: {e}")
                    self._update_info_strip()

                elif kind == "wake_fail":
                    self._wake_active = False
                    self._wake_btn.configure(
                        text="○  WAKE", text_color=C["text_dim"],
                        border_color=C["text_dim"], fg_color="transparent",
                    )
                    self._append_system(f"WAKE-WORD ОШИБКА ЗАГРУЗКИ: {item[1]}")
                    self._update_info_strip()

                elif kind == "wake_listen":
                    self._append_system("ДЖАРВИС СЛУШАЕТ...")
                    if not self._voice_active and not self._busy:
                        from voice.wake_audio import get_wake_audio
                        get_wake_audio().play_random(
                            on_done=lambda: self.after(200, self._start_wake_recording)
                        )

                elif kind == "model_ready":
                    self._append_system("МОДЕЛЬ ЗАГРУЖЕНА  ·  СЛУШАЮ...")
                    self._voice_active = True
                    self._q.put(("rec_start", None))
                    threading.Thread(target=self._record_worker, daemon=True).start()

        except queue.Empty:
            pass

        if refresh:
            self._refresh_side_panel()

        self.after(80, self._poll_queue)

    # ── wake word ─────────────────────────────────────────────────────────────

    def _on_wake_toggle(self):
        if self._wake_active:
            if self._wake_detector:
                self._wake_detector.stop()
                self._wake_detector = None
            self._wake_active = False
            self._wake_btn.configure(
                text="○  WAKE",
                text_color=C["text_dim"], border_color=C["text_dim"],
                fg_color="transparent",
            )
            self._append_system("ДЕТЕКТОР WAKE-WORD ВЫКЛЮЧЕН")
            self._update_info_strip()
        else:
            if not self._init_voice():
                return
            self._wake_active = True
            self._wake_btn.configure(
                text="⟳  WAKE", text_color=C["yellow"],
                border_color=C["yellow"], fg_color="transparent",
            )
            self._append_system("ЗАГРУЗКА МОДЕЛИ ДЛЯ WAKE-WORD...")
            threading.Thread(target=self._load_wake_model, daemon=True).start()

    def _load_wake_model(self):
        try:
            self._stt._load_model()
            self._q.put(("wake_ready", None))
        except Exception as e:
            self._q.put(("wake_fail", str(e)))

    def _on_wake_word(self, remainder: str):
        if self._busy or self._voice_active:
            if self._wake_detector:
                self._wake_detector.resume()
            return

        if remainder.strip():
            self._q.put(("wake_command", remainder.strip()))
        else:
            self._q.put(("wake_listen", None))

    # ── voice: STT ────────────────────────────────────────────────────────────

    def _init_voice(self) -> bool:
        errors = []
        if self._stt is None:
            try:
                from voice.stt import SpeechToText
                self._stt = SpeechToText(model_size=config.WHISPER_MODEL_SIZE, language="ru")
            except ImportError as e:
                errors.append(str(e))
        if self._tts is None:
            try:
                from voice.tts import create_tts
                self._tts = create_tts()
            except ImportError as e:
                errors.append(str(e))
        if errors:
            self._append_system("ГОЛОСОВЫЕ ПАКЕТЫ НЕ УСТАНОВЛЕНЫ: " + "; ".join(errors))
            return False
        return True

    def _start_wake_recording(self):
        if not self._busy and not self._voice_active:
            self._on_mic_click()

    def _on_mic_click(self):
        if self._busy or self._voice_active:
            return
        if not self._init_voice():
            return
        self._voice_active = True
        if self._stt._model is None:
            self._append_system("ЗАГРУЗКА ГОЛОСОВОЙ МОДЕЛИ...")
            threading.Thread(target=self._preload_model, daemon=True).start()
            return
        self._q.put(("rec_start", None))
        threading.Thread(target=self._record_worker, daemon=True).start()

    def _preload_model(self):
        import traceback
        try:
            self._stt._load_model()
            self._q.put(("model_ready", None))
        except Exception as e:
            traceback.print_exc()
            self._q.put(("rec_empty", f"ОШИБКА ЗАГРУЗКИ МОДЕЛИ: {e}"))

    def _record_worker(self):
        import traceback
        try:
            audio = self._stt.record_auto()
            if audio is None:
                self._q.put(("rec_empty", "НИЧЕГО НЕ УСЛЫШАЛ — ПОПРОБУЙ ЕЩЁ РАЗ"))
                return
            self._q.put(("rec_status", "РАСПОЗНАЮ РЕЧЬ..."))
            text = self._stt.transcribe(audio)
            if not text:
                self._q.put(("rec_empty", "НЕ СМОГ РАСПОЗНАТЬ РЕЧЬ"))
                return
            self._q.put(("rec_done", text))
        except Exception as e:
            traceback.print_exc()
            self._q.put(("rec_empty", f"ОШИБКА ГОЛОСА: {type(e).__name__}: {e}"))
        finally:
            self._voice_active = False

    # ── voice: TTS ────────────────────────────────────────────────────────────

    def _on_voice_output_toggle(self):
        self._voice_output = not self._voice_output
        if self._voice_output:
            if not self._init_voice():
                self._voice_output = False
                return
            self._voice_out_btn.configure(
                text="🔊", text_color=C["accent"], fg_color=C["accent_dim"],
            )
            self._append_system("ГОЛОСОВОЙ ВЫВОД ВКЛЮЧЁН")
        else:
            self._voice_out_btn.configure(
                text="🔇", text_color=C["text_dim"], fg_color=C["accent_dim"],
            )
            self._append_system("ГОЛОСОВОЙ ВЫВОД ВЫКЛЮЧЕН")
        self._update_info_strip()

    def _enqueue_tts(self, text: str):
        if self._tts is not None:
            self._tts_q.put(text)

    def _scenario_tts(self, text: str) -> None:
        if self._voice_output and self._tts:
            self._enqueue_tts(text)

    def _tts_worker(self):
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

    # ── dialogs ───────────────────────────────────────────────────────────────

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

    # ── side panel refresh ────────────────────────────────────────────────────

    def _refresh_side_panel(self):
        from tools.notes import get_notes, get_tasks
        for box, fn in ((self._notes_box, get_notes), (self._tasks_box, get_tasks)):
            text = fn()
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", text)
            box.configure(state="disabled")


def run_gui(assistant):
    app = JarvisApp(assistant)

    def _on_close():
        # Очищаем callback чтобы он не обращался к уничтоженным виджетам
        # при следующем использовании assistant (например в CLI)
        assistant._on_tool_use = None
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", _on_close)
    app.mainloop()
