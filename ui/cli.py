"""
Терминальный интерфейс Джарвиса.
Использует библиотеку rich для красивого вывода.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from rich import box

console = Console(encoding="utf-8")


def print_welcome():
    """Приветственный экран при запуске."""
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]ДЖАРВИС[/bold cyan] — Персональный ИИ-ассистент\n"
            "[dim]Введи сообщение для начала. Команды: /exit, /clear, /memory[/dim]"
        ),
        box=box.DOUBLE_EDGE,
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


def print_jarvis_response(text: str):
    """Выводит ответ Джарвиса с форматированием Markdown."""
    # Пробуем отрендерить как Markdown (для списков, кода, заголовков)
    try:
        md = Markdown(text)
        console.print(Panel(
            md,
            border_style="green",
            title="[bold green]Джарвис[/bold green]",
            title_align="left",
            padding=(0, 1),
        ))
    except Exception:
        console.print(Panel(
            text,
            border_style="green",
            title="[bold green]Джарвис[/bold green]",
            title_align="left",
        ))
    console.print()


def print_tool_usage(tool_name: str):
    """Показывает что Джарвис использует инструмент (пока думает)."""
    tool_labels = {
        "web_search": "поиск в интернете",
        "add_note": "сохранение заметки",
        "get_notes": "чтение заметок",
        "add_task": "добавление задачи",
        "get_tasks": "чтение задач",
        "complete_task": "выполнение задачи",
        "read_file": "чтение файла",
        "create_plan": "создание плана",
        "get_plan": "чтение плана",
        "update_plan_step": "обновление плана",
    }
    label = tool_labels.get(tool_name, tool_name)
    console.print(f"[dim cyan]  ⚙ {label}...[/dim cyan]")


def print_error(message: str):
    """Выводит сообщение об ошибке."""
    console.print(f"\n[bold red]Ошибка:[/bold red] {message}\n")


def print_info(message: str):
    """Выводит информационное сообщение."""
    console.print(f"\n[dim]{message}[/dim]\n")


def print_system(message: str):
    """Выводит системное сообщение."""
    console.print(f"[bold yellow]{message}[/bold yellow]\n")


def get_user_input() -> str:
    """Считывает ввод пользователя."""
    try:
        return Prompt.ask("[bold blue]Ты[/bold blue]").strip()
    except (KeyboardInterrupt, EOFError):
        return "/exit"
