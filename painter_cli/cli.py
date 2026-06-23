"""CLI entry point for painter-cli.

A pure command-line tool that accepts coordinate plans as JSON and
executes them on a Schneider PLC/HMI via Modbus TCP. Designed to be
called by external agents (openclaw, Claude, etc.).

Commands:
    draw    - Execute a coordinate plan on the PLC
    status  - Show PLC connection status
    center  - Pen up, move to origin (0, 0)
    config  - Print current settings
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from painter_cli import __version__
from painter_cli.config import Settings
from painter_cli.drawing.executor import DrawingExecutor
from painter_cli.drawing.models import Point, StrokePlan
from painter_cli.drawing.parser import ParseError, parse_plan
from painter_cli.modbus.client import ModbusClient, ModbusError
from painter_cli.ui.console import (
    console,
    create_drawing_progress,
    print_error,
    print_info,
    print_plan_summary,
    print_success,
    print_warning,
)

logger = logging.getLogger(__name__)


def _resolve_input(source: str | None) -> str:
    """Resolve input from argument, file path, or stdin.

    Priority:
    1. If source is a valid file path, read the file
    2. If source is a non-empty string, treat as inline JSON
    3. If stdin is piped, read from stdin

    Returns the raw JSON string.
    """
    if source is not None:
        # Check if it's a file path
        path = Path(source)
        if path.is_file():
            print_info(f"Reading plan from file: {path}")
            return path.read_text(encoding="utf-8")
        # Otherwise treat as inline JSON
        return source

    # Read from stdin if piped
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data

    print_error("No input provided. Pass JSON as argument, file path, or pipe via stdin.")
    raise click.Abort()


@click.group()
@click.version_option(version=__version__, prog_name="painter-cli")
def cli() -> None:
    """painter-cli: Draw coordinate plans on an HMI via Modbus TCP.

    Accepts a JSON coordinate plan and sends it point-by-point to a
    Schneider PLC that controls a physical drawing arm on the HMI screen.
    """
    pass


@cli.command()
@click.argument("source", required=False)
@click.option("--host", default=None, help="Override PLC host address")
@click.option("--port", default=None, type=int, help="Override PLC port")
@click.option("--dry-run", is_flag=True, help="Parse and show plan without drawing")
@click.option("--step", default=None, type=int, help="Max distance between points (0=off, default=5)")
def draw(source: str | None, host: str | None, port: int | None, dry_run: bool, step: int | None) -> None:
    """Execute a coordinate plan on the PLC.

    SOURCE can be:

    - A JSON string: painter-cli draw '{"strokes": [...]}'

    - A file path:   painter-cli draw plan.json

    - Stdin pipe:    echo '{...}' | painter-cli draw
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    settings = Settings()
    if host:
        settings.plc_host = host
    if port:
        settings.plc_port = port
    if step is not None:
        settings.max_step = step

    # Parse input
    raw = _resolve_input(source)
    try:
        plan = parse_plan(raw)
    except ParseError as e:
        print_error(f"Invalid plan: {e}")
        sys.exit(1)

    # Show plan summary
    print_plan_summary(plan)

    if dry_run:
        print_success("Dry run complete. Plan is valid.")
        return

    # Connect to PLC
    modbus = ModbusClient(host=settings.plc_host, port=settings.plc_port)
    try:
        modbus.connect()
    except ModbusError as e:
        print_error(f"PLC connection failed: {e}")
        sys.exit(1)

    # Execute drawing
    _execute_drawing(plan, modbus, settings)


@cli.command()
@click.option("--host", default=None, help="Override PLC host address")
@click.option("--port", default=None, type=int, help="Override PLC port")
def status(host: str | None, port: int | None) -> None:
    """Show PLC connection status."""
    settings = Settings()
    if host:
        settings.plc_host = host
    if port:
        settings.plc_port = port

    modbus = ModbusClient(host=settings.plc_host, port=settings.plc_port, retries=1, retry_delay=1.0)
    try:
        modbus.connect()
        print_success(f"PLC: {modbus.address} — Connected")
        modbus.disconnect()
    except ModbusError:
        print_error(f"PLC: {modbus.address} — Not reachable")
        sys.exit(1)


@cli.command()
@click.option("--host", default=None, help="Override PLC host address")
@click.option("--port", default=None, type=int, help="Override PLC port")
def center(host: str | None, port: int | None) -> None:
    """Pen up, move to origin (0, 0)."""
    settings = Settings()
    if host:
        settings.plc_host = host
    if port:
        settings.plc_port = port

    modbus = ModbusClient(host=settings.plc_host, port=settings.plc_port)
    try:
        modbus.connect()
        modbus.write_position(0, 0, pen=False)
        print_success("Pen raised, moved to center (0, 0)")
        modbus.disconnect()
    except ModbusError as e:
        print_error(f"Failed: {e}")
        sys.exit(1)


@cli.command()
def config() -> None:
    """Print current settings."""
    settings = Settings()
    console.print(f"PLC Host:     {settings.plc_host}")
    console.print(f"PLC Port:     {settings.plc_port}")
    console.print(f"Interval:     {settings.write_interval_ms}ms")
    console.print(f"Max Step:     {settings.max_step} (0=off)")
    console.print(f"Coord Range:  [-{settings.coord_range}, {settings.coord_range}]")


def _execute_drawing(plan: StrokePlan, modbus: ModbusClient, settings: Settings) -> None:
    """Execute a drawing plan with progress display."""
    progress, task_id = create_drawing_progress()

    def on_progress(
        stroke_idx: int,
        total_strokes: int,
        point_idx: int,
        total_points: int,
        point: Point,
    ) -> None:
        total_plan_points = plan.total_points
        completed = sum(len(s) for s in plan.strokes[:stroke_idx]) + point_idx
        overall_pct = (completed / total_plan_points) * 100 if total_plan_points > 0 else 0

        progress.update(
            task_id,
            completed=overall_pct,
            description=f"Stroke {stroke_idx + 1}/{total_strokes}",
            point_info=f"Point {point_idx + 1}/{total_points} | {point}",
        )

    executor = DrawingExecutor(
        modbus=modbus,
        interval_s=settings.write_interval_s,
        max_step=settings.max_step,
        on_progress=on_progress,
    )

    with progress:
        try:
            executor.execute(plan)
        except ModbusError as e:
            print_error(f"Drawing failed: {e}")
            sys.exit(1)

    if not executor.aborted:
        print_success(f"Done! Drew: {plan.description}")
    else:
        print_warning("Drawing was aborted.")

    modbus.disconnect()


def main() -> None:
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
