"""Rich console UI helpers for the painter-cli CLI."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from painter_cli.drawing.models import Point, StrokePlan

console = Console()


def print_plan_summary(plan: StrokePlan) -> None:
    """Display a summary of the drawing plan."""
    table = Table(title=f"Drawing Plan: {plan.description}", show_lines=True)
    table.add_column("Stroke", justify="center", style="cyan")
    table.add_column("Points", justify="center", style="green")
    table.add_column("Start", justify="center")
    table.add_column("End", justify="center")

    for i, stroke in enumerate(plan.strokes, 1):
        table.add_row(
            str(i),
            str(len(stroke)),
            str(stroke.start),
            str(stroke.end),
        )

    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{plan.total_points}[/bold]",
        "",
        "",
    )
    console.print(table)


def create_drawing_progress() -> tuple[Progress, object]:
    """Create a Rich progress bar for drawing execution."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.fields[point_info]}"),
        TimeElapsedColumn(),
        console=console,
    )
    task_id = progress.add_task(
        "Drawing",
        total=100,
        point_info="(0, 0)",
    )
    return progress, task_id


def print_error(message: str) -> None:
    """Print an error message in red."""
    console.print(f"[bold red]Error:[/bold red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def print_success(message: str) -> None:
    """Print a success message in green."""
    console.print(f"[bold green]{message}[/bold green]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[dim]{message}[/dim]")
