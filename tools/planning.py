"""
Инструменты для планирования задач.
Хранение в SQLite (таблицы plans и plan_steps).
"""

from tools.notes import get_db


def create_plan(title: str, steps: str) -> str:
    """
    Создаёт план с шагами.

    :param steps: шаги через символ |, например "Шаг 1|Шаг 2|Шаг 3"
    """
    step_list = [s.strip() for s in steps.split("|") if s.strip()]

    if not step_list:
        return "Ошибка: список шагов пуст."

    from datetime import datetime
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO plans (title, created_at) VALUES (?, ?)",
            (title, datetime.now().isoformat()),
        )
        plan_id = cursor.lastrowid

        for i, step in enumerate(step_list, 1):
            conn.execute(
                "INSERT INTO plan_steps (plan_id, step_number, description) VALUES (?, ?, ?)",
                (plan_id, i, step),
            )

    lines = [f"✅ План '{title}' создан (ID: {plan_id})\n"]
    for i, step in enumerate(step_list, 1):
        lines.append(f"  {i}. {step}")

    return "\n".join(lines)


def get_plan(plan_id: str = "") -> str:
    """Показывает план и прогресс по шагам."""
    with get_db() as conn:
        if plan_id:
            try:
                pid = int(plan_id)
            except ValueError:
                return f"Ошибка: plan_id должен быть числом."

            plan = conn.execute("SELECT * FROM plans WHERE id = ?", (pid,)).fetchone()
            if not plan:
                return f"План с ID {pid} не найден."
            plans = [plan]
        else:
            plans = conn.execute(
                "SELECT p.* FROM plans p "
                "WHERE EXISTS (SELECT 1 FROM plan_steps s WHERE s.plan_id = p.id AND s.completed = 0) "
                "ORDER BY p.created_at DESC"
            ).fetchall()

        if not plans:
            return "Активных планов нет."

        result = []
        for plan in plans:
            steps = conn.execute(
                "SELECT * FROM plan_steps WHERE plan_id = ? ORDER BY step_number",
                (plan["id"],),
            ).fetchall()

            done = sum(1 for s in steps if s["completed"])
            total = len(steps)
            progress = int(done / total * 100) if total else 0

            result.append(f"📋 [{plan['id']}] {plan['title']} — {done}/{total} шагов ({progress}%)")
            for step in steps:
                icon = "✅" if step["completed"] else "⬜"
                result.append(f"  {icon} {step['step_number']}. {step['description']}")
            result.append("")

    return "\n".join(result)


def update_plan_step(plan_id: str, step_number: str) -> str:
    """Отмечает шаг плана как выполненный."""
    try:
        pid = int(plan_id)
        step_num = int(step_number)
    except ValueError:
        return "Ошибка: plan_id и step_number должны быть числами."

    with get_db() as conn:
        step = conn.execute(
            "SELECT * FROM plan_steps WHERE plan_id = ? AND step_number = ?",
            (pid, step_num),
        ).fetchone()

        if not step:
            return f"Шаг {step_num} в плане {pid} не найден."

        conn.execute(
            "UPDATE plan_steps SET completed = 1 WHERE plan_id = ? AND step_number = ?",
            (pid, step_num),
        )

    return f"Шаг {step_num} отмечен как выполненный. ✅"
