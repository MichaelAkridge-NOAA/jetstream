"""Job detail + log panel widget (right panel)."""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from rich.table import Table
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static

from ..controller import JobVM, _fmt_bytes


class JobDetailWidget(Widget):
    """
    Right-hand panel showing metadata and captured logs for the selected job.
    """

    DEFAULT_CSS = """
    JobDetailWidget {
        height: 1fr;
        border: tall $accent;
        padding: 0 1;
    }
    #detail-header {
        height: auto;
        background: $panel-darken-1;
        padding: 0 1;
        margin-bottom: 1;
    }
    #detail-log {
        height: 1fr;
        border: solid $surface-darken-1;
    }
    """

    _job: reactive[Optional[JobVM]] = reactive(None, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-header")
        yield RichLog(id="detail-log", highlight=True, markup=True, wrap=True)

    def show_job(self, job: Optional[JobVM]) -> None:
        self._job = job
        self._refresh_content(job)

    def _refresh_content(self, job: Optional[JobVM]) -> None:
        header = self.query_one("#detail-header", Static)
        log_widget = self.query_one("#detail-log", RichLog)
        log_widget.clear()

        if job is None:
            header.update("[dim]No job selected — use ↑↓ to navigate the queue.[/dim]")
            return

        # Build metadata table
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold dim", min_width=16)
        table.add_column("Value")

        def row(k: str, v: str) -> None:
            table.add_row(k, v)

        status_color = {
            "running": "cyan", "queued": "yellow", "pending": "white",
            "scheduled": "blue", "completed": "green",
            "failed": "red", "cancelled": "dim",
        }.get(job.status, "white")

        row("Job ID", job.job_id)
        row("Name", job.friendly_name)
        row("Status", f"[{status_color}]{job.status.upper()}[/{status_color}]")
        row("Source", job.source_path)
        row("Destination", job.destination)
        row("Tool", job.upload_tool + (" [dry-run]" if job.dry_run else ""))
        row("Files", f"{job.files_uploaded:,} / {job.total_files:,}")
        row("Bytes", f"{_fmt_bytes(job.bytes_uploaded)} / {_fmt_bytes(job.total_size_bytes)}")
        row("Progress", f"{job.progress_percent:.1f}%")
        if job.duration_seconds:
            mins = int(job.duration_seconds // 60)
            secs = int(job.duration_seconds % 60)
            row("Duration", f"{mins}m {secs}s")
        if job.scheduled_for:
            row("Scheduled", str(job.scheduled_for))
        if job.error_message:
            row("Error", f"[red]{job.error_message}[/red]")

        header.update(table)

        # Show captured output / logs
        if job.upload_output:
            log_widget.write("[bold dim]── Upload Output ──[/bold dim]")
            # Show last ~200 lines to keep it snappy
            lines = job.upload_output.splitlines()
            if len(lines) > 200:
                log_widget.write(f"[dim]… {len(lines)-200} earlier lines omitted …[/dim]")
                lines = lines[-200:]
            for line in lines:
                log_widget.write(line)
        elif job.log_path:
            _pre_start = job.status in ("pending", "queued", "scheduled")
            if _pre_start:
                log_widget.write(f"[dim]Log will appear here once the job starts.[/dim]")
                log_widget.write(f"[dim]Log path: {job.log_path}[/dim]")
            else:
                log_widget.write(f"[dim]Log file: {job.log_path}[/dim]")
                try:
                    with open(job.log_path, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    if not content.strip():
                        log_widget.write("[dim]Log file is empty — job may still be starting.[/dim]")
                    else:
                        lines = content.splitlines()
                        if len(lines) > 200:
                            log_widget.write(f"[dim]… {len(lines)-200} earlier lines omitted …[/dim]")
                            lines = lines[-200:]
                        for line in lines:
                            log_widget.write(line)
                except FileNotFoundError:
                    if job.status == "running":
                        log_widget.write("[dim]Log file not yet written — job is starting…[/dim]")
                    else:
                        log_widget.write(f"[dim]Log file not found: {job.log_path}[/dim]")
                except OSError as e:
                    log_widget.write(f"[red]Could not read log file: {e}[/red]")
        else:
            log_widget.write("[dim]No output captured yet.[/dim]")
