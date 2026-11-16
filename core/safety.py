"""
Система классификации безопасности операций Джарвиса.

Три уровня:
  SAFE      — выполнить немедленно, без вопросов
  CONFIRM   — показать описание + ждать "да" от пользователя
  FORBIDDEN — отказать и объяснить почему

Покрывает: PowerShell-команды, файловые операции (чтение/запись), реестр.
"""

import re
from enum import Enum
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger("safety")


# ── Уровни опасности ──────────────────────────────────────────────────────────

class SafetyLevel(Enum):
    SAFE      = "safe"
    CONFIRM   = "confirm"
    FORBIDDEN = "forbidden"


# ── Глобальный обработчик подтверждений ──────────────────────────────────────
# Регистрируется из main.py: cli_confirm_handler или voice_confirm_handler.
# Сигнатура: (description: str, details: str) -> bool

_confirm_handler: Callable[[str, str], bool] | None = None


def register_confirm_handler(fn: Callable[[str, str], bool]) -> None:
    global _confirm_handler
    _confirm_handler = fn


def request_confirmation(description: str, details: str = "") -> bool:
    """
    Запрашивает подтверждение у пользователя через зарегистрированный handler.
    По умолчанию (handler не зарегистрирован) — отказывает: безопасный фолбэк.
    """
    import config
    if not config.SAFETY_REQUIRE_CONFIRM:
        log.info(f"SAFETY_REQUIRE_CONFIRM=False: авто-подтверждение → {description}")
        return True

    if _confirm_handler is None:
        log.warning(f"Confirm handler не зарегистрирован, операция отклонена: {description}")
        return False

    result = _confirm_handler(description, details)
    log.info(f"[Подтверждение] «{description[:80]}» → {'ДА' if result else 'НЕТ'}")
    return result


# ── POWERSHELL ────────────────────────────────────────────────────────────────

# Regex-паттерны, которые запрещены при любых условиях
_PS_FORBIDDEN: list[re.Pattern] = [
    re.compile(r"format[\s\-]+volume",                         re.I),
    re.compile(r"format\s+[a-z]:",                             re.I),
    re.compile(r"disable[\s\-]+windows[\s\-]+defender",        re.I),
    re.compile(r"set[\s\-]+mppreference.+disablerealtimemon",  re.I),
    # Скачать-и-выполнить (IEX / Invoke-Expression после веб-запроса)
    re.compile(r"invoke[\s\-]+webrequest.{0,200}invoke[\s\-]+expression", re.I | re.S),
    re.compile(r"\biex\b.{0,100}(http|https|ftp)",             re.I),
    re.compile(r"invoke[\s\-]+expression\s+\(",                re.I),
    # Удаление критичных системных папок
    re.compile(r"remove[\s\-]+item.{0,60}\\windows\\system",  re.I),
    re.compile(r"remove[\s\-]+item.{0,60}-recurse.{0,60}c:\\windows", re.I),
    re.compile(r"rd\s+/s\s+/q\s+c:\\windows",                 re.I),
    re.compile(r"del\s+/[sfq]+\s+c:\\windows",                re.I),
    # Отключение защитных механизмов
    re.compile(r"bcdedit.{0,60}recoveryenabled\s+no",          re.I),
    re.compile(r"vssadmin.{0,60}delete\s+shadows",             re.I),
]

# Глаголы командлетов, которые только читают/выводят → SAFE
_PS_SAFE_VERBS = {
    "get", "find", "search", "read", "select", "where", "format",
    "out", "measure", "test", "show", "write", "convertto", "convertfrom",
    "export", "compare", "resolve", "split", "join", "sort", "group",
}

# Отдельные утилиты командной строки, безопасные по природе
_PS_SAFE_COMMANDS = {
    "systeminfo", "ipconfig", "netstat", "tasklist", "dir", "ls",
    "whoami", "hostname", "tree", "echo", "type", "ver", "set",
    "ping", "tracert", "nslookup", "arp", "route",
    "wmic", "query", "sc", "net", "netsh",  # только информационный вывод
    "get-process", "get-service", "get-childitem", "get-item",
    "get-content", "get-date", "get-location", "get-command",
    "get-computername", "get-wmiobject", "get-ciminstance",
    "get-netadapter", "get-netipaddress", "get-disk", "get-volume",
    "get-installedmodule", "get-package",
}

# Глаголы, требующие подтверждения
_PS_CONFIRM_VERBS = {
    "set", "new", "remove", "stop", "start", "restart", "suspend",
    "register", "unregister", "install", "uninstall", "clear", "reset",
    "enable", "disable", "invoke", "copy", "move", "rename", "push",
    "pop", "add", "update", "repair", "restore", "block", "unblock",
}


def classify_powershell(command: str) -> tuple[SafetyLevel, str]:
    """
    Классифицирует PowerShell-команду.
    Возвращает (SafetyLevel, human_readable_description).
    """
    cmd_stripped = command.strip()
    cmd_low = cmd_stripped.lower()

    # 1. Forbidden-паттерны — проверяем первыми
    for pattern in _PS_FORBIDDEN:
        if pattern.search(cmd_low):
            matched = pattern.pattern[:40]
            log.warning(f"[PS] FORBIDDEN паттерн «{matched}»: {cmd_stripped[:80]}")
            return SafetyLevel.FORBIDDEN, f"команда содержит запрещённую операцию ({matched})"

    # 2. Определяем первое слово (командлет или утилита)
    first_token = cmd_low.split()[0] if cmd_low.split() else ""
    # Убираем префикс модуля (Module\Verb-Noun)
    if "\\" in first_token:
        first_token = first_token.split("\\")[-1]

    # 3. Полное имя команды в safe-списке?
    if first_token in _PS_SAFE_COMMANDS:
        return SafetyLevel.SAFE, ""

    # 4. Разбираем Verb-Noun
    if "-" in first_token:
        verb = first_token.split("-")[0]
        if verb in _PS_SAFE_VERBS:
            return SafetyLevel.SAFE, ""
        if verb in _PS_CONFIRM_VERBS:
            desc = f"выполнить команду: `{cmd_stripped[:120]}`"
            return SafetyLevel.CONFIRM, desc

    # 5. Неизвестное → CONFIRM (принцип наименьших привилегий)
    log.info(f"[PS] Неизвестный командлет «{first_token}», требую подтверждения")
    return SafetyLevel.CONFIRM, f"выполнить неизвестную команду: `{cmd_stripped[:120]}`"


# ── ФАЙЛЫ — ЗАПИСЬ ────────────────────────────────────────────────────────────

# Пути автозапуска (lowercase, слэши унифицированы)
_STARTUP_FRAGMENTS = [
    r"microsoft\windows\start menu\programs\startup",
    r"appdata\roaming\microsoft\windows\start menu",
    r"appdata\roaming\microsoft\windows\start menu\programs\startup",
]

# Папки, в которые запись запрещена полностью
_FORBIDDEN_WRITE_PARTS = {
    "windows", "system32", "syswow64",
    "program files", "program files (x86)",
}

# Исполняемые расширения, опасные в Temp/AppData
_EXEC_EXTENSIONS = {".bat", ".cmd", ".ps1", ".exe", ".vbs", ".js", ".hta", ".wsf", ".msi"}

# Temp-индикаторы в пути
_TEMP_FRAGMENTS = {"\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\"}


def classify_file_write(path: str) -> tuple[SafetyLevel, str]:
    """
    Классифицирует операцию создания/записи файла.
    Возвращает (SafetyLevel, описание_для_пользователя).
    """
    try:
        resolved = Path(path).resolve()
    except Exception:
        return SafetyLevel.CONFIRM, f"не удалось проверить путь: {path}"

    parts_low = {p.lower() for p in resolved.parts}
    path_str_low = str(resolved).lower()
    ext = resolved.suffix.lower()

    # Системные папки — FORBIDDEN
    for forbidden in _FORBIDDEN_WRITE_PARTS:
        if forbidden in parts_low:
            log.warning(f"[File] FORBIDDEN запись в системную папку: {resolved}")
            return SafetyLevel.FORBIDDEN, f"запись в системную папку запрещена: {resolved}"

    # Папки автозапуска — CONFIRM
    for fragment in _STARTUP_FRAGMENTS:
        if fragment in path_str_low:
            log.info(f"[File] CONFIRM автозапуск: {resolved}")
            return SafetyLevel.CONFIRM, f"файл окажется в папке автозапуска Windows: {resolved}"

    # Исполняемые файлы в Temp — CONFIRM
    if ext in _EXEC_EXTENSIONS:
        for temp_frag in _TEMP_FRAGMENTS:
            if temp_frag in path_str_low:
                log.info(f"[File] CONFIRM исполняемый в Temp: {resolved}")
                return SafetyLevel.CONFIRM, f"исполняемый файл в папке Temp: {resolved}"

    return SafetyLevel.SAFE, ""


# ── ФАЙЛЫ — ЧТЕНИЕ ───────────────────────────────────────────────────────────

_FORBIDDEN_READ_FILES = {
    "sam", "ntds.dit", "hiberfil.sys",
    "pagefile.sys", "swapfile.sys", "system",
}


def classify_file_read(path: str) -> tuple[SafetyLevel, str]:
    """Классифицирует операцию чтения файла."""
    try:
        resolved = Path(path).resolve()
        if resolved.name.lower() in _FORBIDDEN_READ_FILES:
            # Только если это в системной папке
            parts_low = {p.lower() for p in resolved.parts}
            if parts_low & {"windows", "system32", "system volume information"}:
                log.warning(f"[File] FORBIDDEN чтение системного файла: {resolved}")
                return SafetyLevel.FORBIDDEN, f"чтение критичного системного файла запрещено: {resolved.name}"
    except Exception:
        pass
    return SafetyLevel.SAFE, ""


# ── РЕЕСТР ────────────────────────────────────────────────────────────────────

# Ветки, запись в которые может убить загрузку или систему
_FORBIDDEN_REGISTRY_BRANCHES = [
    r"hklm\system\currentcontrolset\control\session manager\bootexecute",
    r"hklm\sam",
    r"hklm\security",
    r"hklm\system\currentcontrolset\services\tcpip\parameters",
    r"hklm\system\currentcontrolset\control\lsa",
    r"hklm\system\currentcontrolset\control\safeboot",
]


def classify_registry_write(path: str) -> tuple[SafetyLevel, str]:
    """
    Классифицирует операцию записи/удаления в реестре.
    Любая запись требует подтверждения; критичные ветки — запрещены.
    """
    path_low = path.lower().replace("/", "\\").replace("hkey_local_machine", "hklm") \
                            .replace("hkey_current_user", "hkcu") \
                            .replace("hkey_classes_root", "hkcr") \
                            .replace("hkey_users", "hku") \
                            .replace("hkey_current_config", "hkcc")

    for branch in _FORBIDDEN_REGISTRY_BRANCHES:
        if branch in path_low:
            log.warning(f"[Reg] FORBIDDEN критичная ветка: {path}")
            return SafetyLevel.FORBIDDEN, (
                f"изменение критичной ветки реестра запрещено — "
                f"это может нарушить загрузку Windows: {path}"
            )

    return SafetyLevel.CONFIRM, f"изменить реестр: {path}"
