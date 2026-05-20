"""
Инструменты для работы с заметками и задачами.
Хранение в SQLite (файл data/jarvis.db).
"""

import sqlite3
from datetime import datetime
from contextlib import contextmanager

import config


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
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notes (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
            (title, content, tags, datetime.now().isoformat()),
        )
    return f"Заметка '{title}' сохранена."


def get_notes(search: str = "") -> str:
    """Показывает заметки, опционально фильтруя по ключевому слову."""
    with get_db() as conn:
        if search:
            rows = conn.execute(
                "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY created_at DESC LIMIT 10",
                (f"%{search}%", f"%{search}%", f"%{search}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC LIMIT 10"
            ).fetchall()

    if not rows:
        msg = f"Заметок по запросу '{search}' не найдено." if search else "Заметок пока нет."
        return msg

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
    """Отмечает задачу как выполненную."""
    try:
        tid = int(task_id)
    except ValueError:
        return f"Ошибка: task_id должен быть числом, получено: {task_id}"

    with get_db() as conn:
        row = conn.execute("SELECT title FROM tasks WHERE id = ?", (tid,)).fetchone()
        if not row:
            return f"Задача с ID {tid} не найдена."
        conn.execute(
            "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
            (datetime.now().isoformat(), tid),
        )

    return f"Задача '{row['title']}' отмечена как выполненная. ✅"
