"""
Инструменты работы с реестром Windows.

Безопасные операции (SAFE):   registry_read, registry_list
С подтверждением (CONFIRM):   registry_write, registry_delete_value

Перед любой записью автоматически создаётся .reg-бэкап в data/registry_backups/.
"""

import subprocess
import winreg
from datetime import datetime
from pathlib import Path

import config
from core.logger import get_logger
from core.safety import SafetyLevel, classify_registry_write, request_confirmation

log = get_logger("registry")


# ── Вспомогательные функции ───────────────────────────────────────────────────

_HIVE_MAP: dict[str, int] = {
    "hkey_local_machine": winreg.HKEY_LOCAL_MACHINE,
    "hklm":               winreg.HKEY_LOCAL_MACHINE,
    "hkey_current_user":  winreg.HKEY_CURRENT_USER,
    "hkcu":               winreg.HKEY_CURRENT_USER,
    "hkey_classes_root":  winreg.HKEY_CLASSES_ROOT,
    "hkcr":               winreg.HKEY_CLASSES_ROOT,
    "hkey_users":         winreg.HKEY_USERS,
    "hku":                winreg.HKEY_USERS,
    "hkey_current_config": winreg.HKEY_CURRENT_CONFIG,
    "hkcc":               winreg.HKEY_CURRENT_CONFIG,
}

_TYPE_MAP: dict[str, int] = {
    "reg_sz":        winreg.REG_SZ,
    "reg_dword":     winreg.REG_DWORD,
    "reg_qword":     winreg.REG_QWORD,
    "reg_expand_sz": winreg.REG_EXPAND_SZ,
    "reg_multi_sz":  winreg.REG_MULTI_SZ,
    "reg_binary":    winreg.REG_BINARY,
    # Короткие алиасы
    "sz":     winreg.REG_SZ,
    "dword":  winreg.REG_DWORD,
    "qword":  winreg.REG_QWORD,
    "expand": winreg.REG_EXPAND_SZ,
    "string": winreg.REG_SZ,
}

_TYPE_NAMES: dict[int, str] = {v: k.upper() for k, v in _TYPE_MAP.items() if k.startswith("reg_")}


def _parse_path(path: str) -> tuple[int, str]:
    """
    Разбирает путь реестра вида 'HKCU\\Software\\MyApp' на (hive, subkey).
    Поднимает ValueError если корневой куст не распознан.
    """
    normalized = path.strip().replace("/", "\\")
    parts = normalized.split("\\", 1)
    hive_name = parts[0].lower()
    subkey = parts[1] if len(parts) > 1 else ""

    hive = _HIVE_MAP.get(hive_name)
    if hive is None:
        raise ValueError(
            f"Неизвестный корневой куст: «{parts[0]}». "
            f"Используй HKCU, HKLM, HKCR, HKU или полные имена."
        )
    return hive, subkey


def _backup_key(path: str) -> str:
    """
    Создаёт .reg-бэкап ветки реестра через reg.exe.
    Возвращает путь к файлу бэкапа или описание ошибки.
    """
    backup_dir = config.DATA_DIR / "registry_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = path.replace("\\", "_").replace(":", "").replace("/", "_")[:60]
    backup_file = backup_dir / f"backup_{safe_name}_{ts}.reg"

    try:
        result = subprocess.run(
            ["reg", "export", path, str(backup_file), "/y"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            log.info(f"[Reg] Бэкап создан: {backup_file}")
            return str(backup_file)
        log.warning(f"[Reg] Бэкап не создан (код {result.returncode}): {result.stderr[:100]}")
        return f"(бэкап не удался: {result.stderr[:60]})"
    except Exception as e:
        log.warning(f"[Reg] Ошибка бэкапа: {e}")
        return f"(бэкап не удался: {e})"


# ── Публичные инструменты ─────────────────────────────────────────────────────

def registry_read(path: str, value_name: str = "") -> str:
    """
    Читает значение из реестра. Уровень: SAFE (выполняется сразу).

    :param path:       путь к ветке, например HKCU\\Software\\MyApp
    :param value_name: имя значения (пусто = Default)
    """
    log.info(f"[Reg] read: {path} → «{value_name or '(Default)'}»")
    try:
        hive, subkey = _parse_path(path)
    except ValueError as e:
        return f"Ошибка пути реестра: {e}"

    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
            data, reg_type = winreg.QueryValueEx(key, value_name or None)
            type_name = _TYPE_NAMES.get(reg_type, str(reg_type))
            return (
                f"Реестр: {path}\n"
                f"Значение: «{value_name or '(Default)'}»\n"
                f"Тип: {type_name}\n"
                f"Данные: {data}"
            )
    except FileNotFoundError:
        return f"Ветка или значение не найдены: {path} → «{value_name or '(Default)'}»"
    except PermissionError:
        return f"Нет доступа к ветке: {path}"
    except Exception as e:
        return f"Ошибка чтения реестра: {e}"


def registry_list(path: str) -> str:
    """
    Показывает содержимое ветки реестра (подветки + значения). Уровень: SAFE.

    :param path: путь к ветке, например HKLM\\SOFTWARE\\Microsoft\\Windows
    """
    log.info(f"[Reg] list: {path}")
    try:
        hive, subkey = _parse_path(path)
    except ValueError as e:
        return f"Ошибка пути реестра: {e}"

    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
            lines = [f"Ветка реестра: {path}\n"]

            # Подветки
            subkeys = []
            idx = 0
            while True:
                try:
                    subkeys.append(winreg.EnumKey(key, idx))
                    idx += 1
                except OSError:
                    break

            if subkeys:
                lines.append(f"  Подветки ({len(subkeys)}):")
                for sk in subkeys[:30]:
                    lines.append(f"    [{sk}]")
                if len(subkeys) > 30:
                    lines.append(f"    ... ещё {len(subkeys) - 30}")

            # Значения
            values = []
            idx = 0
            while True:
                try:
                    values.append(winreg.EnumValue(key, idx))
                    idx += 1
                except OSError:
                    break

            if values:
                lines.append(f"  Значения ({len(values)}):")
                for name, data, reg_type in values[:40]:
                    type_name = _TYPE_NAMES.get(reg_type, str(reg_type))
                    display_name = f"«{name}»" if name else "(Default)"
                    data_str = str(data)[:80]
                    lines.append(f"    {display_name} [{type_name}] = {data_str}")
                if len(values) > 40:
                    lines.append(f"    ... ещё {len(values) - 40}")

            if not subkeys and not values:
                lines.append("  (ветка пуста)")

            return "\n".join(lines)

    except FileNotFoundError:
        return f"Ветка не найдена: {path}"
    except PermissionError:
        return f"Нет доступа к ветке: {path}"
    except Exception as e:
        return f"Ошибка чтения реестра: {e}"


def registry_write(path: str, value_name: str, value: str, value_type: str = "REG_SZ") -> str:
    """
    Записывает значение в реестр. Уровень: CONFIRM + автобэкап перед записью.

    :param path:       путь к ветке, например HKCU\\Software\\MyApp
    :param value_name: имя значения
    :param value:      новое значение (строка; для DWORD — числовая строка)
    :param value_type: тип: REG_SZ, REG_DWORD, REG_EXPAND_SZ и др. (по умолч. REG_SZ)
    """
    log.info(f"[Reg] write request: {path} → «{value_name}» = {str(value)[:40]} [{value_type}]")

    # Проверка запрещённых веток
    level, reason = classify_registry_write(path)
    if level == SafetyLevel.FORBIDDEN:
        return f"Отказано: {reason}, сэр."

    # Запрос подтверждения
    desc = f"записать в реестр {path}\n  «{value_name}» = {str(value)[:60]} [{value_type}]"
    if not request_confirmation(desc):
        return "Операция отменена, сэр."

    # Проверка типа
    type_key = value_type.lower().replace("-", "_")
    reg_type = _TYPE_MAP.get(type_key)
    if reg_type is None:
        return (
            f"Неизвестный тип «{value_type}». "
            f"Допустимые: REG_SZ, REG_DWORD, REG_QWORD, REG_EXPAND_SZ."
        )

    try:
        hive, subkey = _parse_path(path)
    except ValueError as e:
        return f"Ошибка пути реестра: {e}"

    # Конвертация значения
    try:
        if reg_type == winreg.REG_DWORD:
            typed_value = int(value)
        elif reg_type == winreg.REG_QWORD:
            typed_value = int(value)
        else:
            typed_value = str(value)
    except (ValueError, TypeError) as e:
        return f"Не удалось конвертировать значение для типа {value_type}: {e}"

    # Бэкап перед записью
    backup_path = _backup_key(path)
    log.info(f"[Reg] Бэкап: {backup_path}")

    # Запись
    try:
        with winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value_name, 0, reg_type, typed_value)
        log.info(f"[Reg] Записано: {path} → «{value_name}» = {typed_value}")
        return (
            f"Записано в реестр, сэр.\n"
            f"  Ветка: {path}\n"
            f"  Значение: «{value_name}» = {typed_value} [{value_type}]\n"
            f"  Бэкап: {backup_path}"
        )
    except PermissionError:
        return f"Нет прав на запись в ветку: {path}, сэр."
    except Exception as e:
        return f"Ошибка записи в реестр: {e}"


def registry_delete_value(path: str, value_name: str) -> str:
    """
    Удаляет значение из реестра. Уровень: CONFIRM + автобэкап.

    :param path:       путь к ветке
    :param value_name: имя удаляемого значения
    """
    log.info(f"[Reg] delete request: {path} → «{value_name}»")

    level, reason = classify_registry_write(path)
    if level == SafetyLevel.FORBIDDEN:
        return f"Отказано: {reason}, сэр."

    desc = f"удалить из реестра {path}\n  значение: «{value_name}»"
    if not request_confirmation(desc):
        return "Операция отменена, сэр."

    try:
        hive, subkey = _parse_path(path)
    except ValueError as e:
        return f"Ошибка пути реестра: {e}"

    backup_path = _backup_key(path)

    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
        log.info(f"[Reg] Удалено: {path} → «{value_name}»")
        return (
            f"Значение «{value_name}» удалено из {path}, сэр.\n"
            f"  Бэкап: {backup_path}"
        )
    except FileNotFoundError:
        return f"Значение «{value_name}» не найдено в {path}, сэр."
    except PermissionError:
        return f"Нет прав на изменение ветки: {path}, сэр."
    except Exception as e:
        return f"Ошибка удаления из реестра: {e}"
