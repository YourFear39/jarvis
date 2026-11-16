"""
Deep integration tests: PC interaction, file creation, router classification.
Run from C:/Projects/Jarvis: python _test_deep.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
# Force UTF-8 output so Cyrillic doesn't crash on CP1251 consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
from core.local_handler import handle_local
from core.router import classify, Level

DESKTOP = Path.home() / "Desktop"
PASS = 0
FAIL = 0
SKIP = 0

def ok(label):
    global PASS
    PASS += 1
    print(f"  [PASS] {label}")

def fail(label, got=None):
    global FAIL
    FAIL += 1
    extra = f" -> GOT: {repr(got)[:100]}" if got is not None else ""
    print(f"  [FAIL] {label}{extra}")

def skip(label, reason=""):
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {label}" + (f" ({reason})" if reason else ""))

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_local(msg, expect_not_none=True, contains=None, not_contains=None):
    """Helper: call handle_local and check result."""
    result = handle_local(msg)
    label = f"handle_local({msg!r:.60})"
    if expect_not_none:
        if result is None:
            fail(label, "None — passed to LLM")
            return None
    else:
        if result is not None:
            fail(label + " [should return None]", result)
            return result
        ok(label + " -> None (correct)")
        return None
    if contains:
        for c in (contains if isinstance(contains, list) else [contains]):
            if c.lower() not in result.lower():
                fail(label + f" [missing {c!r}]", result)
                return result
    if not_contains:
        for c in (not_contains if isinstance(not_contains, list) else [not_contains]):
            if c.lower() in result.lower():
                fail(label + f" [should not contain {c!r}]", result)
                return result
    ok(label)
    return result

def check_router(msg, expected_level, label=None):
    """Helper: check router classification."""
    got = classify(msg)
    lbl = label or f"classify({msg!r:.55})"
    if got == expected_level:
        ok(f"{lbl} -> {expected_level.name}")
    else:
        fail(f"{lbl} -> expected {expected_level.name}, got {got.name}")

# ===========================================================================
# 1. TIME & DATE
# ===========================================================================
section("1. TIME & DATE")
for q in ["который час", "сколько времени", "what time", "который сейчас час"]:
    r = check_local(q, contains=":")
for q in ["какой сегодня", "какое число", "какой день"]:
    r = check_local(q, contains="2026")

# ===========================================================================
# 2. FOLDER SHORTCUTS
# ===========================================================================
section("2. FOLDER SHORTCUTS")
for q in ["открой загрузки", "открой downloads", "открой документы",
          "открой рабочий стол", "открой desktop", "открой фото",
          "открой pictures", "открой музыку", "открой видео"]:
    check_local(q, contains="Открываю")

# ===========================================================================
# 3. APP OPEN — built-in apps that should be in PATH
# ===========================================================================
section("3. APP OPEN — built-in (always in PATH)")
builtin_apps = [
    "блокнот", "калькулятор", "проводник", "cmd",
    "powershell", "paint", "диспетчер задач", "реестр",
]
for name in builtin_apps:
    r = handle_local(f"открой {name}")
    if r and ("Запускаю" in r or "уже запущен" in r):
        ok(f"открой {name} -> {r[:50]}")
    elif r is None:
        fail(f"открой {name} -> None (no handler)")
    else:
        fail(f"открой {name} -> unexpected", r)

# These may or may not be installed — just verify handler responds
section("3b. APP OPEN — may not be installed (just verify handler runs)")
optional_apps = ["discord", "telegram", "chrome", "firefox", "steam",
                 "spotify", "vscode", "vs code", "obs", "vlc", "opera"]
for name in optional_apps:
    r = handle_local(f"открой {name}")
    if r is None:
        fail(f"открой {name} -> None (should have response)")
    elif "Запускаю" in r or "уже запущен" in r or "не нашёл" in r or "не могу найти" in r:
        ok(f"открой {name} -> handled")
    else:
        fail(f"открой {name} -> unexpected", r)

# ===========================================================================
# 4. FILE CREATION — all known extensions
# ===========================================================================
section("4. FILE CREATION — all extensions")
# Clean up test files first
test_files = []
exts = ["txt", "bat", "cmd", "ps1", "py", "html", "htm", "css", "js",
        "json", "xml", "csv", "reg", "ini", "cfg", "sh", "log", "md"]
for ext in exts:
    fname = f"_jarvis_test.{ext}"
    fpath = DESKTOP / fname
    if fpath.exists():
        fpath.unlink()
    test_files.append(fpath)

for ext in exts:
    fname = f"_jarvis_test.{ext}"
    r = handle_local(f"создай файл {fname}")
    fpath = DESKTOP / fname
    if r is None:
        fail(f"create .{ext} -> None")
    elif "создан" in r.lower() or "Файл" in r:
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8", errors="replace")
            ok(f"create .{ext} -> file exists, {len(content)} bytes")
        else:
            fail(f"create .{ext} -> response ok but file missing")
    else:
        fail(f"create .{ext}", r)

# Verify templates
section("4b. Template content correctness")
template_checks = {
    "bat": "@echo off",
    "ps1": "Set-ExecutionPolicy",
    "py":  "def main",
    "html": "<!DOCTYPE html>",
    "reg": "Windows Registry Editor",
    "json": "{}",
    "css": "body",
    "xml": "<?xml",
}
for ext, expected in template_checks.items():
    fpath = DESKTOP / f"_jarvis_test.{ext}"
    if fpath.exists():
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if expected.lower() in content.lower():
            ok(f".{ext} template contains {expected!r}")
        else:
            fail(f".{ext} template missing {expected!r}", content[:100])
    else:
        skip(f".{ext} template check", "file not created")

# BAT action creation
section("4c. BAT action creation")
bat_path = DESKTOP / "_jarvis_launch.bat"
if bat_path.exists(): bat_path.unlink()
r = handle_local("создай _jarvis_launch.bat который запускает notepad и calc")
if bat_path.exists():
    content = bat_path.read_text(encoding="utf-8", errors="replace")
    if "start" in content and ("notepad" in content.lower() or "calc" in content.lower()):
        ok(f"BAT action -> {len(content)} bytes with start commands")
    else:
        fail("BAT action -> file exists but missing start commands", content[:200])
else:
    fail("BAT action -> file not created", r)

# Create folder
section("4d. Folder creation")
test_folder = DESKTOP / "_jarvis_test_folder"
if test_folder.exists():
    import shutil; shutil.rmtree(str(test_folder))
r = check_local("создай папку _jarvis_test_folder", contains="создана")
if test_folder.exists():
    ok("folder exists on Desktop")
    import shutil; shutil.rmtree(str(test_folder))
else:
    fail("folder not found on Desktop")

# ===========================================================================
# 5. FILE OPERATIONS
# ===========================================================================
section("5. FILE OPERATIONS")

# Create a file for testing rename/delete
test_txt = DESKTOP / "_test_jarvis_orig.txt"
test_txt.write_text("test", encoding="utf-8")

# Rename
r = handle_local(f"переименуй _test_jarvis_orig.txt в _test_jarvis_renamed.txt")
renamed = DESKTOP / "_test_jarvis_renamed.txt"
if renamed.exists():
    ok("rename -> file renamed")
    renamed.unlink()
elif r and ("переименован" in r.lower() or "ошибка" in r.lower()):
    fail("rename -> response but file not found", r)
    if test_txt.exists(): test_txt.unlink()
else:
    fail("rename -> None or bad response", r)
    if test_txt.exists(): test_txt.unlink()

# Delete file
test_del = DESKTOP / "_test_jarvis_del.txt"
test_del.write_text("delete me", encoding="utf-8")
r = handle_local(f"удали файл {test_del}")
if not test_del.exists():
    ok("delete file -> file removed")
elif r and "удалён" in r.lower():
    fail("delete file -> says deleted but file still exists", r)
else:
    fail("delete file -> unexpected response", r)
    if test_del.exists(): test_del.unlink()

# Critical path protection
r = handle_local("удали папку C:\\Windows")
if r and ("отказываю" in r.lower() or "системный" in r.lower()):
    ok("critical path protection -> Windows blocked")
else:
    fail("critical path protection -> Windows NOT blocked!", r)

r = handle_local("удали папку C:\\Users")
if r and ("отказываю" in r.lower() or "системный" in r.lower()):
    ok("critical path protection -> Users root blocked")
else:
    fail("critical path protection -> C:\\Users NOT blocked!", r)

# ===========================================================================
# 6. NOTES OPERATIONS (local)
# ===========================================================================
section("6. NOTES OPERATIONS (local)")
from tools.notes import init_db, add_note, add_task
init_db()

# Add some test notes
add_note("Тестовая заметка Альфа", "Содержимое заметки про альфа-тест")
add_note("Тестовая заметка Бета", "Содержимое про бета версию")

check_local("покажи мои заметки", contains="Тестовая")
check_local("покажи заметки", contains="Тестовая")
check_local("список заметок", contains="Тестовая")
check_local("найди заметку про альфа", contains="Альфа")

# Add a note locally
r = check_local("запомни это важная информация", contains=["сохранена", "заметка"])
check_local("удали заметку альфа", contains=["удалена", "заметк"])

# ===========================================================================
# 7. TASKS OPERATIONS (local)
# ===========================================================================
section("7. TASKS OPERATIONS (local)")
add_task("Тестовая задача", priority="medium")

check_local("покажи задачи", contains="Тестовая")
check_local("мои задачи", contains="Тестовая")
check_local("что нужно сделать", contains="Тестовая")
r = check_local("добавь задачу написать отчёт", contains=["задача", "добавлена"])
check_local("удали задачу Тестовая")

# ===========================================================================
# 8. SYSTEM COMMANDS
# ===========================================================================
section("8. SYSTEM COMMANDS")
check_local("громче", contains="Громкость")
check_local("тише", contains="Громкость")
check_local("выключи звук", contains="звук")
check_local("включи звук", contains="звук")
check_local("системная информация", contains=["ОЗУ", "ЦП"])
check_local("sysinfo", contains=["ОЗУ", "ЦП"])
check_local("запущенные программы")
check_local("что сейчас запущено")

# Clipboard
check_local("скопируй текст Привет мир в буфер", contains="скопирован")
check_local("что в буфере обмена", contains=["буфере", "Привет"])

# ===========================================================================
# 9. POWER COMMANDS — SKIP shutdown/sleep/reboot (they ACTUALLY execute)
# ===========================================================================
section("9. POWER COMMANDS (shutdown/sleep/reboot SKIPPED — real execution)")
# СТРОГО ЗАПРЕЩЕНО: выключение и спящий режим реально выполняются через os,
# поэтому эти три команды полностью исключены из тестов.
skip("выключи компьютер",    "реально запускает shutdown /s — запрещено")
skip("режим сна",            "реально переводит в сон — запрещено")
skip("перезагрузи компьютер","реально запускает shutdown /r — пропускаем")

# Отмена выключения безопасна: shutdown /a тихо завершается если нет активного таймера
check_local("отмена выключения", contains="отменено")

# ===========================================================================
# 10. WEATHER (local, no LLM)
# ===========================================================================
section("10. WEATHER (local, Open-Meteo)")
r = handle_local("погода")
if r and ("°C" in r or "ошибка" in r.lower() or "не удалось" in r.lower()):
    ok(f"weather -> handled: {r[:80]}")
elif r is None:
    fail("weather -> None (sent to LLM!)")
else:
    ok(f"weather -> response: {r[:80]}")

r = handle_local("погода в Москве")
if r and r.strip():
    ok(f"weather Moscow -> {r[:80]}")
else:
    fail("weather Moscow -> empty/None", r)

# ===========================================================================
# 11. ROUTER CLASSIFICATION AUDIT
# ===========================================================================
section("11. ROUTER CLASSIFICATION AUDIT")

# These SHOULD go to SEARCH (informational, no need for LLM tool use)
search_should = [
    ("что такое блокчейн", "blockchain definition"),
    ("кто такой Илон Маск", "Elon Musk info"),
    ("где находится Байкал", "location query"),
    ("сколько стоит iPhone 15", "price query"),
    ("погода в Питере завтра", "weather query"),
    ("новости сегодня", "news query"),
    ("курс доллара сегодня", "exchange rate"),
    ("когда основали Google", "history fact"),
    ("столица Бразилии", "capital query"),
]
for msg, label in search_should:
    check_router(msg, Level.SEARCH, label)

# The BIG problem: these go to AI but SHOULD go to SEARCH
print("\n  -- Queries that CURRENTLY go to AI (may need fixing) --")
info_queries_going_to_ai = [
    ("расскажи о Python", "tell about Python"),
    ("как работает интернет", "how internet works"),
    ("почему небо синее", "why is sky blue"),
    ("как установить Python", "how to install"),
    ("расскажи про блокчейн", "tell about blockchain"),
    ("что лучше Python или Java", "comparison"),
    ("как называется столица Франции", "capital question"),
    ("объясни что такое ИИ", "explain AI"),
    ("расскажи о динозаврах", "tell about dinosaurs"),
    ("какой самый высокий горный пик", "superlative fact"),
]
for msg, label in info_queries_going_to_ai:
    got = classify(msg)
    if got == Level.SEARCH:
        ok(f"{label}: {msg!r:.45} -> SEARCH")
    else:
        fail(f"{label}: {msg!r:.45} -> AI (should be SEARCH)")

# These SHOULD stay in AI (tool calls needed)
print("\n  -- Should stay in AI --")
ai_should = [
    ("запомни купить молоко", "add note"),
    ("добавь задачу позвонить врачу", "add task"),
    ("напиши план обучения Python", "write plan"),
    ("составь план путешествия", "plan creation"),
    ("придумай рецепт супа", "creative"),
    ("помоги написать письмо", "help write"),
    ("покажи мои заметки", "show notes"),  # wait, this is handled locally
    ("удали задачу 5", "delete task"),
    ("прочитай файл C:\\notes.txt", "read file"),
]
for msg, label in ai_should:
    check_router(msg, Level.AI, label)

# ===========================================================================
# 12. MISC LOCAL COMMANDS
# ===========================================================================
section("12. MISC LOCAL COMMANDS")
check_local("что ты умеешь", contains=["умею", "команды", "МГНОВЕННО"])
check_local("помощь", contains=["умею", "команды"])
check_local("список команд", contains=["умею"])

# ===========================================================================
# 13. URL / SITE OPENING
# ===========================================================================
section("13. URL/SITE OPENING")
for query in ["открой сайт youtube.com",
              "открой https://github.com",
              "открой www.google.com"]:
    check_local(query, contains="Открываю")

# ===========================================================================
# CLEANUP
# ===========================================================================
section("CLEANUP")
import shutil
for f in DESKTOP.glob("_jarvis_test*"):
    try:
        if f.is_file(): f.unlink()
        elif f.is_dir(): shutil.rmtree(str(f))
        print(f"  Cleaned: {f.name}")
    except Exception as e:
        print(f"  Failed to clean {f.name}: {e}")
for f in [DESKTOP / "_jarvis_launch.bat", DESKTOP / "_test_jarvis_renamed.txt"]:
    if f.exists():
        try: f.unlink(); print(f"  Cleaned: {f.name}")
        except: pass

# ===========================================================================
# SUMMARY
# ===========================================================================
print(f"\n{'='*60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped")
print(f"  Total: {PASS+FAIL+SKIP}")
print(f"{'='*60}")
if FAIL > 0:
    sys.exit(1)
