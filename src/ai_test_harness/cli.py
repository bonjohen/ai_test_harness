"""CLI entry point."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from .config import get_settings, load_source
from .db import init_db
from .models import ModelRegistry

console = Console()


@click.group()
def main() -> None:
    """AI Test Harness — benchmark and evaluate local LLMs."""


@main.command()
def list_models() -> None:
    """List all models in the catalog."""
    settings = get_settings()
    source = load_source(settings.source_path)
    registry = ModelRegistry(source["LLMS"])

    table = Table(title="Model Catalog")
    table.add_column("Name", style="cyan")
    table.add_column("Size (B)", justify="right")
    table.add_column("Type")
    table.add_column("Roles")
    table.add_column("Context", justify="right")

    for m in registry.models:
        table.add_row(
            m.name,
            str(m.size_b),
            m.type,
            ", ".join(m.primary_role),
            f"{m.context_window_tokens:,}",
        )
    console.print(table)


@main.command()
def list_tests() -> None:
    """List all defined test suites."""
    settings = get_settings()
    source = load_source(settings.source_path)

    table = Table(title="Test Suites")
    table.add_column("Suite", style="cyan")
    table.add_column("Test", style="green")
    table.add_column("Metric")
    table.add_column("Description")

    for suite_name, tests in source["TEST"].items():
        for t in tests:
            metric = t["metric"] if isinstance(t["metric"], str) else ", ".join(t["metric"])
            table.add_row(suite_name, t["name"], metric, t["description"])
    console.print(table)


@main.command()
def init() -> None:
    """Initialize the results database."""
    settings = get_settings()
    conn = init_db(settings.db_path)
    conn.close()
    console.print(f"[green]Database initialized at {settings.db_path}[/green]")


if __name__ == "__main__":
    main()
