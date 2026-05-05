"""Job list DataTable widget."""

from __future__ import annotations

from typing import List, Optional

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Label
from textual.reactive import reactive
from rich.text import Text

from ..controller import JobVM


_STATUS_COLORS = {
    "running":   "bold cyan",
    "queued":    "bold yellow",
    "pending":   "white",
    "scheduled": "bold blue",
    "completed": "bold green",
    "failed":    "bold red",
    "cancelled": "dim",
}


def _progress_bar(pct: float, width: int = 12) -> Text:
    filled = int(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if pct >= 100 else ("cyan" if pct > 0 else "dim")
    return Text(f"{bar} {pct:>5.1f}%", style=color)


class JobTableWidget(Widget):
    """
    Scrollable DataTable showing all upload jobs.

    Emits a ``JobSelected`` message when the user moves the cursor.
    """

    COMPONENT_CLASSES = {"job-table--row-running"}

    DEFAULT_CSS = """
    JobTableWidget {
        height: 1fr;
    }
    """

    class JobSelected(Message):
        def __init__(self, job_vm: Optional[JobVM]) -> None:
            super().__init__()
            self.job_vm = job_vm

    _jobs: reactive[List[JobVM]] = reactive([], always_update=True)

    def compose(self) -> ComposeResult:
        yield DataTable(id="job-table", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "  ",        # status icon
            "Job Name",
            "Status",
            "Source",
            "Destination",
            "Progress",
            "Size",
            "Tool",
        )

    def update_jobs(self, jobs: List[JobVM]) -> None:
        self._jobs = jobs
        self._rebuild_table(jobs)

    def _rebuild_table(self, jobs: List[JobVM]) -> None:
        table = self.query_one(DataTable)
        # Preserve cursor position
        old_row = table.cursor_row

        table.clear()
        for j in jobs:
            status_color = _STATUS_COLORS.get(j.status, "white")
            source_short = j.source_path[-30:] if len(j.source_path) > 30 else j.source_path
            dest_short = j.destination[-30:] if len(j.destination) > 30 else j.destination
            table.add_row(
                Text(j.status_icon, style=status_color, justify="center"),
                Text(j.friendly_name, overflow="ellipsis"),
                Text(j.status.upper(), style=status_color),
                Text(source_short, overflow="ellipsis"),
                Text(dest_short, overflow="ellipsis"),
                _progress_bar(j.progress_percent),
                Text(j.size_display, justify="right"),
                Text(j.upload_tool),
                key=j.job_id,
            )

        # Restore cursor within bounds
        if jobs:
            row = min(old_row, len(jobs) - 1)
            table.move_cursor(row=row)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Emit JobSelected when the cursor row changes."""
        if event.row_key is not None and self._jobs:
            job_id = str(event.row_key.value)
            match = next((j for j in self._jobs if j.job_id == job_id), None)
            self.post_message(self.JobSelected(match))

    def get_selected_job(self) -> Optional[JobVM]:
        """Return the currently highlighted job, or None."""
        table = self.query_one(DataTable)
        if table.row_count == 0 or not self._jobs:
            return None
        idx = table.cursor_row
        if 0 <= idx < len(self._jobs):
            return self._jobs[idx]
        return None
