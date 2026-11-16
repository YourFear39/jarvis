"""
Система сценариев (цепочек действий) Джарвиса.

Сценарий = список шагов. Каждый шаг:
  - name   : отображаемое имя
  - fn     : callable() → str  (выполняет действие, возвращает статус)
  - say    : фраза для озвучки прогресса (None = не озвучивать)

Добавить новый сценарий: создать список шагов и зарегистрировать
через ScenarioRunner.register() или добавить в SCENARIOS.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import config


# ── Вспомогательные функции ──────────────────────────────────────────────────

def _jarvis_pids() -> set[int]:
    """
    Возвращает множество PID-ов которые НЕЛЬЗЯ убивать:
    сам процесс Джарвиса + родитель + все дочерние процессы.
    Это основная (PID-based) защита от самозакрытия.
    """
    try:
        import psutil
        my_pid = os.getpid()
        protected: set[int] = {my_pid}

        me = psutil.Process(my_pid)

        # Родительский процесс (cmd.exe / launcher / IDE)
        try:
            protected.add(me.parent().pid)
        except Exception:
            pass

        # Дочерние процессы
        try:
            for child in me.children(recursive=True):
                protected.add(child.pid)
        except Exception:
            pass

        return protected
    except Exception:
        return {os.getpid()}


def _is_whitelisted(proc) -> bool:
    """True если процесс нельзя трогать (белый список или системный владелец)."""
    # Получаем имя — если не можем, безопаснее пропустить
    try:
        name_low = (proc.name() or "").lower()
    except Exception:
        return True

    if name_low in config.PROCESS_WHITELIST:
        return True

    # Проверяем владельца — AccessDenied на username НЕ означает автоматического пропуска.
    # Системные процессы (SYSTEM / NT AUTHORITY) пропускаем, остальные — нет.
    try:
        uname = (proc.username() or "").upper()
        if any(s in uname for s in ("SYSTEM", "NT AUTHORITY", "LOCAL SERVICE", "NETWORK SERVICE")):
            return True
    except Exception:
        # Не можем прочитать username — не считаем это причиной пропустить процесс.
        # (Это нормально для процессов текущего пользователя на некоторых сборках Windows.)
        pass

    return False


def _collect_killable() -> list:
    """
    Возвращает список пользовательских процессов, которые можно закрыть.
    Исключает: белый список, системные, Джарвис (по PID).
    Пишет подробный лог в консоль для отладки.
    """
    try:
        import psutil
    except ImportError:
        print("[GameMode] ОШИБКА: psutil не установлен. Установи: pip install psutil")
        return []

    protected_pids = _jarvis_pids()
    killable = []
    skipped_whitelist = 0
    skipped_system    = 0
    skipped_protected = 0

    print(f"[GameMode] Сканирую процессы (защищённые PID: {protected_pids})...")

    for proc in psutil.process_iter(["pid", "name", "username"]):
        try:
            pid = proc.pid

            if pid in protected_pids:
                skipped_protected += 1
                continue

            try:
                name = proc.name() or "?"
            except Exception:
                continue

            name_low = name.lower()

            if name_low in config.PROCESS_WHITELIST:
                skipped_whitelist += 1
                continue

            # Проверка владельца (не бросает исключение вовне)
            is_sys = False
            try:
                uname = (proc.username() or "").upper()
                if any(s in uname for s in ("SYSTEM", "NT AUTHORITY", "LOCAL SERVICE", "NETWORK SERVICE")):
                    is_sys = True
                    skipped_system += 1
            except Exception:
                pass   # не можем прочитать username — не системный по умолчанию

            if is_sys:
                continue

            killable.append(proc)
            try:
                uname_disp = proc.username() or "?"
            except Exception:
                uname_disp = "<no access>"
            print(f"[GameMode]   + {name:<30} PID={pid:<6} user={uname_disp}")

        except Exception:
            continue

    print(
        f"[GameMode] Итого: {len(killable)} под закрытие, "
        f"пропущено: {skipped_whitelist} (whitelist) + "
        f"{skipped_system} (system) + "
        f"{skipped_protected} (jarvis PID)"
    )
    return killable


def _kill_processes(procs: list) -> tuple[int, list[str]]:
    """
    Закрывает список процессов. Возвращает (кол-во убитых, список ошибок).
    """
    killed = 0
    errors: list[str] = []
    for proc in procs:
        try:
            name = proc.name()
            proc.kill()
            killed += 1
        except Exception as e:
            errors.append(f"{name}: {e}")
    return killed, errors


def _kill_updaters() -> str:
    """Принудительно завершает все процессы-обновляльщики."""
    try:
        import psutil
    except ImportError:
        return "psutil не установлен"

    protected_pids = _jarvis_pids()
    killed = 0
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.pid in protected_pids:
                continue
            name_low = (proc.name() or "").lower()
            if "update" in name_low or "updater" in name_low:
                proc.kill()
                killed += 1
        except Exception:
            continue
    return f"Завершено {killed} процессов обновлений, сэр." if killed else "Обновляльщики не найдены."


def _launch(path: str, args: list[str] | None = None) -> str:
    """Запускает приложение по пути. Возвращает статус."""
    try:
        cmd = [path] + (args or [])
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return f"Запущено: {os.path.basename(path)}"
    except FileNotFoundError:
        return f"Файл не найден: {path}"
    except Exception as e:
        return f"Ошибка запуска {os.path.basename(path)}: {e}"


# ── Dataclass шага ───────────────────────────────────────────────────────────

@dataclass
class Step:
    name: str
    fn:   Callable[[], str]
    say:  str | None = None
    delay_after: float = 0.5   # пауза после шага (сек)


# ── Динамический поиск путей приложений ──────────────────────────────────────

def _find_steam_exe() -> str | None:
    """Ищет steam.exe: сначала стандартный путь, затем реестр."""
    default = Path(r"C:\Program Files (x86)\Steam\steam.exe")
    if default.exists():
        return str(default)
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        ) as key:
            install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            exe = Path(install_path) / "steam.exe"
            if exe.exists():
                return str(exe)
    except Exception:
        pass
    return None


def _find_rust_exe() -> str | None:
    """Ищет Rust.exe в steamapps (стандартный путь + реестр для кастомных библиотек)."""
    candidates = [Path(r"C:\Program Files (x86)\Steam\steamapps\common\Rust\Rust.exe")]
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        ) as key:
            install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            candidates.append(Path(install_path) / "steamapps" / "common" / "Rust" / "Rust.exe")
    except Exception:
        pass
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _find_discord_update_exe() -> str | None:
    """Ищет Discord Update.exe — путь меняется при каждом обновлении."""
    local_app = os.environ.get("LOCALAPPDATA", "")
    update_exe = Path(local_app) / "Discord" / "Update.exe"
    if update_exe.exists():
        return str(update_exe)
    return None


def _step_launch_steam() -> str:
    path = _find_steam_exe()
    if not path:
        return "Steam не найден. Установи Steam или добавь путь вручную."
    return _launch(path)


def _step_launch_rust() -> str:
    rust = _find_rust_exe()
    if not rust:
        return "Rust не найден в steamapps. Запусти через Steam вручную."
    return _launch(rust)


def _step_launch_discord() -> str:
    update = _find_discord_update_exe()
    if not update:
        return "Discord не найден в %LOCALAPPDATA%\\Discord."
    return _launch(update, args=["--processStart", "Discord.exe"])


def _step_launch_discord_bypass() -> str:
    """Запускает скрипт обхода Discord (zapret). Путь берётся из config."""
    path = config.DISCORD_BYPASS_PATH
    if not path:
        return "Обход Discord не настроен (задай DISCORD_BYPASS_PATH в .env). Шаг пропущен."
    if not Path(path).exists():
        return f"Файл обхода не найден: {path}. Шаг пропущен."
    return _launch(path)


# ── Игровой режим ────────────────────────────────────────────────────────────

def _step_kill_user_apps() -> str:
    procs = _collect_killable()
    if not procs:
        return "Пользовательские программы не найдены."
    killed, errs = _kill_processes(procs)
    msg = f"Закрыто {killed} программ."
    if errs:
        msg += f" Ошибки: {', '.join(errs[:3])}"
    return msg


GAME_MODE_STEPS: list[Step] = [
    Step(
        name="Закрытие пользовательских программ",
        fn=_step_kill_user_apps,
        say="Закрываю фоновые программы, сэр.",
        delay_after=1.5,
    ),
    Step(
        name="Завершение процессов обновления",
        fn=_kill_updaters,
        say="Завершаю процессы обновлений.",
        delay_after=0.5,
    ),
    Step(
        name="Запуск Steam",
        fn=_step_launch_steam,
        say="Запускаю Steam, сэр. Ожидайте загрузки.",
        delay_after=9.0,   # Steam нужно время загрузиться перед запуском игры
    ),
    Step(
        name="Запуск Rust",
        fn=_step_launch_rust,
        say="Steam готов. Запускаю Rust.",
        delay_after=3.0,
    ),
    Step(
        name="Запуск обхода Discord",
        fn=_step_launch_discord_bypass,
        say="Активирую обход Discord.",
        delay_after=3.0,
    ),
    Step(
        name="Запуск Discord",
        fn=_step_launch_discord,
        say="Запускаю Discord.",
        delay_after=0.5,
    ),
]


# ── Runner ───────────────────────────────────────────────────────────────────

class ScenarioRunner:
    """
    Выполняет сценарий шаг за шагом.
    Каждый шаг: озвучить прогресс → выполнить → пауза.
    Ошибка шага не прерывает весь сценарий.
    """

    def __init__(self, tts_fn: "Callable[[str], None] | None" = None):
        self._tts = tts_fn     # функция озвучки (принимает строку)

    def run(self, steps: list[Step], on_line: "Callable[[str], None] | None" = None) -> str:
        """
        Запускает цепочку шагов синхронно.
        on_line(text) — callback для вывода строки прогресса в UI.
        Возвращает итоговый отчёт.
        """
        results: list[str] = []

        for i, step in enumerate(steps, 1):
            header = f"[{i}/{len(steps)}] {step.name}"
            if on_line:
                on_line(header)

            if step.say and self._tts:
                self._tts(step.say)

            try:
                result = step.fn()
            except Exception as e:
                result = f"ОШИБКА: {e}"

            if on_line:
                on_line(f"  ↳ {result}")
            results.append(f"{step.name}: {result}")

            if step.delay_after > 0:
                time.sleep(step.delay_after)

        return "\n".join(results)

    def dry_run(self, steps: list[Step]) -> str:
        """
        Показывает что будет сделано, БЕЗ выполнения.
        Для игрового режима: возвращает список процессов под закрытие.
        """
        lines = ["DRY-RUN — вот что будет выполнено:\n"]
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step.name}")

        killable = _collect_killable()
        if killable:
            lines.append(f"\nПроцессы под закрытие ({len(killable)}):")
            for p in sorted(killable, key=lambda x: x.name().lower()):
                try:
                    lines.append(f"  • {p.name()}  (PID {p.pid})")
                except Exception:
                    pass
        else:
            lines.append("\nПользовательских процессов для закрытия не найдено.")

        lines.append("\nОтправь 'подтвердить игровой режим' чтобы запустить.")
        return "\n".join(lines)
