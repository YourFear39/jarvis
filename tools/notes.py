"""
Инструменты для работы с заметками и задачами.
Хранение в SQLite (файл data/jarvis.db).
"""

import sqlite3
from datetime import datetime
from contextlib import contextmanager

import config
from core.logger import get_logger

log = get_logger("notes")


@contextmanager
def get_db():
    """Контекстный менеджер для работы с SQLite."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row  # Возвращает строки как словари
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы если их нет. Вызывается при старте."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT DEFAULT 'medium',
                due_date TEXT,
                completed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plan_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL,
                description TEXT NOT NULL,
                completed INTEGER DEFAULT 0,
                FOREIGN KEY (plan_id) REFERENCES plans(id)
            );
        """)


# --- Заметки ---

def add_note(title: str, content: str, tags: str = "") -> str:
    """Сохраняет новую заметку."""
    log.debug("add_note: title=%r", title[:60])
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO notes (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
            (title, content, tags, datetime.now().isoformat()),
        )
    log.info("note added (id=%d): %r", cur.lastrowid, title[:60])
    return f"Заметка '{title}' сохранена."


def _note_matches(keyword: str, row) -> bool:
    """
    Проверяет совпадение ключевого слова с заметкой.
    Поддерживает русскую морфологию: срезает до 2 падежных окончаний.
    SQLite LIKE не поддерживает кириллицу без учёта регистра — фильтруем в Python.
    """
    kw = keyword.lower()
    text = (row["title"] + " " + row["content"] + " " + (row["tags"] or "")).lower()
    if kw in text:
        return True
    # Стриппим падежные окончания (встречу→встреч, покупки→покупк)
    for n in (2, 1):
        stem = kw[:-n] if len(kw) > 4 + n else None
        if stem and stem in text:
            return True
    return False


def get_notes(search: str = "") -> str:
    """Показывает заметки, опционально фильтруя по ключевому слову."""
    log.debug("get_notes(search=%r)", search)
    with get_db() as conn:
        if search:
            # Python-сторонняя фильтрация: SQLite LIKE регистрозависим для кириллицы
            all_rows = conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC"
            ).fetchall()
            rows = [r for r in all_rows if _note_matches(search, r)][:10]
        else:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

    if not rows:
        msg = f"Заметок по запросу '{search}' не найдено." if search else "Заметок пока нет."
        log.info("get_notes → 0 results (search=%r)", search)
        return msg

    log.info("get_notes → %d results (search=%r)", len(rows), search)
    lines = [f"Найдено заметок: {len(rows)}\n"]
    for row in rows:
        date = row["created_at"][:10]
        tags = f" [#{row['tags']}]" if row["tags"] else ""
        lines.append(f"📝 [{row['id']}] {row['title']}{tags} ({date})")
        lines.append(f"   {row['content'][:200]}{'...' if len(row['content']) > 200 else ''}\n")

    return "\n".join(lines)


# --- Задачи ---

def add_task(title: str, priority: str = "medium", due_date: str = "") -> str:
    """Добавляет задачу в список дел."""
    priority = priority.lower() if priority in ("high", "medium", "low") else "medium"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO tasks (title, priority, due_date, created_at) VALUES (?, ?, ?, ?)",
            (title, priority, due_date or None, datetime.now().isoformat()),
        )
    return f"Задача '{title}' добавлена (приоритет: {priority})."


def get_tasks(show_completed: str = "false") -> str:
    """Показывает список задач."""
    show_all = show_completed.lower() == "true"

    with get_db() as conn:
        if show_all:
            rows = conn.execute("SELECT * FROM tasks ORDER BY completed, priority DESC, created_at").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE completed = 0 ORDER BY priority DESC, created_at"
            ).fetchall()

    if not rows:
        return "Список задач пуст." if show_all else "Невыполненных задач нет. Отлично!"

    priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = []

    for row in rows:
        icon = "✅" if row["completed"] else priority_icon.get(row["priority"], "⚪")
        due = f" (до {row['due_date']})" if row["due_date"] else ""
        lines.append(f"{icon} [{row['id']}] {row['title']}{due}")

    return "\n".join(lines)


def complete_task(task_id: str) -> str:
    """Отмечает задачу как выполненную по ID или ключевому слову."""
    task_id = task_id.strip().strip(".,!?;: ")
    log.debug("complete_task(%r)", task_id)
    try:
        tid = int(task_id)
        with get_db() as conn:
            row = conn.execute("SELECT title FROM tasks WHERE id = ?", (tid,)).fetchone()
            if not row:
                return f"Задача с ID {tid} не найдена."
            conn.execute(
                "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), tid),
            )
        return f"Задача '{row['title']}' выполнена."
    except ValueError:
        pass

    keyword = task_id.lower()
    with get_db() as conn:
        all_rows = conn.execute(
            "SELECT id, title FROM tasks WHERE completed = 0 ORDER BY created_at DESC"
        ).fetchall()
    rows = [r for r in all_rows if keyword in r["title"].lower()]

    if not rows:
        return f"Невыполненная задача по запросу '{task_id}' не найдена."
    if len(rows) == 1:
        with get_db() as conn:
            conn.execute(
                "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), rows[0]["id"]),
            )
        return f"Задача '{rows[0]['title']}' выполнена."
    lines = [f"Нашёл {len(rows)} задач с «{task_id}». Скажи номер:"]
    for r in rows[:5]:
        lines.append(f"  [{r['id']}] {r['title']}")
    if len(rows) > 5:
        lines.append(f"  ... и ещё {len(rows) - 5}")
    return "\n".join(lines)


def delete_task(task_id: str) -> str:
    """Удаляет задачу по ID или ключевому слову."""
    task_id = task_id.strip().strip(".,!?;: ")
    log.debug("delete_task(%r)", task_id)
    try:
        tid = int(task_id)
        with get_db() as conn:
            row = conn.execute("SELECT title FROM tasks WHERE id = ?", (tid,)).fetchone()
            if not row:
                return f"Задача с ID {tid} не найдена."
            conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        return f"Задача '{row['title']}' удалена."
    except ValueError:
        pass

    keyword = task_id.lower()
    with get_db() as conn:
        all_rows = conn.execute(
            "SELECT id, title FROM tasks ORDER BY created_at DESC"
        ).fetchall()
    rows = [r for r in all_rows if keyword in r["title"].lower()]

    if not rows:
        return f"Задача по запросу '{task_id}' не найдена."
    if len(rows) == 1:
        with get_db() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (rows[0]["id"],))
        return f"Задача '{rows[0]['title']}' удалена."
    lines = [f"Нашёл {len(rows)} задач с «{task_id}». Скажи номер:"]
    for r in rows[:5]:
        lines.append(f"  [{r['id']}] {r['title']}")
    if len(rows) > 5:
        lines.append(f"  ... и ещё {len(rows) - 5}")
    return "\n".join(lines)


def delete_note(note_id: str) -> str:
    """Удаляет заметку по ID или по ключевому слову/названию."""
    note_id = note_id.strip().strip(".,!?;: ")
    log.debug("delete_note(%r)", note_id)
    # Сначала пробуем как числовой ID
    try:
        nid = int(note_id)
        with get_db() as conn:
            row = conn.execute("SELECT title FROM notes WHERE id = ?", (nid,)).fetchone()
            if not row:
                log.info("delete_note: id=%d not found", nid)
                return f"Заметка с ID {nid} не найдена."
            conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
        log.info("delete_note: deleted id=%d %r", nid, row["title"])
        return f"Заметка '{row['title']}' удалена."
    except ValueError:
        pass

    # Ищем по ключевому слову с поддержкой русской морфологии
    with get_db() as conn:
        all_rows = conn.execute(
            "SELECT id, title, content, tags, created_at FROM notes ORDER BY created_at DESC"
        ).fetchall()
    rows = [r for r in all_rows if _note_matches(note_id, r)]

    if not rows:
        return f"Заметка по запросу '{note_id}' не найдена."

    if len(rows) == 1:
        with get_db() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (rows[0]["id"],))
        return f"Заметка '{rows[0]['title']}' удалена."

    lines = [f"Нашёл {len(rows)} заметок с «{note_id}». Уточни по номеру или названию:"]
    for r in rows[:5]:
        date = r["created_at"][:10]
        lines.append(f"  [{r['id']}] {r['title']} ({date})")
    if len(rows) > 5:
        lines.append(f"  ... и ещё {len(rows) - 5}")
    return "\n".join(lines)
