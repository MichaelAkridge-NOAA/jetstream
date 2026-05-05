"""Queue status bar widget (sits above the job table)."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from ..controller import QueueStatusVM, StatsVM, _fmt_bytes


class QueueStatusBar(Widget):
    """
    Compact one-line summary of queue and overall stats shown above the job table.
    """

    DEFAULT_CSS = """
    QueueStatusBar {
        height: 3;
        background: $panel-darken-1;
        padding: 1 2;
        color: $text;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="queue-bar-text")

    def update_status(self, q: QueueStatusVM, s: StatsVM) -> None:
        pause_tag = " [bold yellow]⏸ PAUSED[/bold yellow]" if q.paused else ""
        text = (
            f"[bold cyan]Running:[/bold cyan] {q.running_count}/{q.max_concurrent}"
            f"  [bold yellow]Queued:[/bold yellow] {q.queued_count}"
            f"  [bold green]Done:[/bold green] {s.completed}"
            f"  [bold red]Failed:[/bold red] {s.failed}"
            f"  [bold blue]Scheduled:[/bold blue] {s.scheduled}"
            f"  [dim]Total uploaded: {_fmt_bytes(s.total_bytes_uploaded)}[/dim]"
            + pause_tag
        )
        self.query_one("#queue-bar-text", Static).update(text)
