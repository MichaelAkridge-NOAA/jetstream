"""
Main dashboard screen — job queue, controls, and detail panel.

Layout (landscape):
┌──────────────────────────────────────────────────────────┐
│ LogoWidget │       QueueStatusBar                        │
├───────────────────────────────────┬──────────────────────┤
│  JobTableWidget (left, 60%)       │  JobDetailWidget     │
│  ↑↓ navigate · Enter detail       │  (right, 40%)        │
│                                   │                      │
├───────────────────────────────────┴──────────────────────┤
│ Footer — key bindings                                    │
└──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static

from ..controller import JobVM, JetStreamController
from ..widgets.job_detail import JobDetailWidget
from ..widgets.job_table import JobTableWidget
from ..widgets.logo import LogoWidget
from ..widgets.queue_status import QueueStatusBar
from ..widgets.system_metrics import SystemMetricsWidget


_REFRESH_INTERVAL = 3.0  # seconds between auto-refresh


class DashboardScreen(Screen):
    """Primary screen — queue dashboard with job details."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("n", "new_job", "New Job", show=True),
        Binding("b", "bucket_browser", "Buckets", show=True),
        Binding("p", "pause_resume", "Pause/Resume", show=True),
        Binding("c", "cancel_job", "Cancel", show=True),
        Binding("t", "retry_job", "Retry", show=True),
        Binding("x", "clear_completed", "Clear Done", show=True),
        Binding("d", "delete_job", "Delete", show=True),
        Binding("f1", "filter_all", "All", show=True),
        Binding("f2", "filter_running", "Running", show=False),
        Binding("f3", "filter_failed", "Failed", show=False),
        Binding("ctrl+c", "quit", "Quit", show=True),
    ]

    CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #header-row {
        height: 8;
        layout: horizontal;
    }
    #logo-area {
        width: 26;
        height: 8;
    }
    #status-area {
        width: 1fr;
        height: 8;
    }
    #main-row {
        height: 1fr;
        layout: horizontal;
    }
    #left-panel {
        width: 60%;
        layout: vertical;
    }
    #right-panel {
        width: 40%;
        border-left: tall $accent;
    }
    #filter-bar {
        height: 3;
        background: $panel;
        padding: 1 2;
        color: $text-muted;
    }
    """

    def __init__(self, controller: JetStreamController) -> None:
        super().__init__()
        self.controller = controller
        self._status_filter: Optional[str] = None
        self._selected_job: Optional[JobVM] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="header-row"):
            with Vertical(id="logo-area"):
                yield LogoWidget()
            with Vertical(id="status-area"):
                yield QueueStatusBar()
                yield SystemMetricsWidget()
        with Horizontal(id="main-row"):
            with Vertical(id="left-panel"):
                yield Static("Filter: [bold]ALL[/bold]  F1=All F2=Running F3=Failed", id="filter-bar")
                yield JobTableWidget()
            with Vertical(id="right-panel"):
                yield JobDetailWidget()
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh_data)
        self._refresh_data()

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def _refresh_data(self) -> None:
        jobs = self.controller.list_jobs(status_filter=self._status_filter)
        q = self.controller.get_queue_status()
        s = self.controller.get_stats()

        self.query_one(JobTableWidget).update_jobs(jobs)
        self.query_one(QueueStatusBar).update_status(q, s)

        # Refresh selected job detail if one is active
        if self._selected_job:
            fresh = self.controller.get_job(self._selected_job.job_id)
            self.query_one(JobDetailWidget).show_job(fresh)

    # ------------------------------------------------------------------
    # Job selection
    # ------------------------------------------------------------------

    def on_job_table_widget_job_selected(self, message: JobTableWidget.JobSelected) -> None:
        self._selected_job = message.job_vm
        self.query_one(JobDetailWidget).show_job(message.job_vm)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        self._refresh_data()
        self.notify("Refreshed.", timeout=1)

    def action_new_job(self) -> None:
        from .job_create import JobCreateScreen
        self.app.push_screen(JobCreateScreen(self.controller))

    def action_bucket_browser(self) -> None:
        from .bucket import BucketBrowserScreen
        self.app.push_screen(BucketBrowserScreen(self.controller))

    def action_pause_resume(self) -> None:
        q = self.controller.get_queue_status()
        if q.paused:
            self.controller.resume_queue()
            self.notify("Queue resumed.", severity="information")
        else:
            self.controller.pause_queue()
            self.notify("Queue paused.", severity="warning")
        self._refresh_data()

    def _get_cursor_job(self) -> Optional[JobVM]:
        return self.query_one(JobTableWidget).get_selected_job()

    def action_cancel_job(self) -> None:
        job = self._get_cursor_job()
        if not job:
            self.notify("No job selected.", severity="error")
            return
        ok = self.controller.cancel_job(job.job_id)
        msg = f"Cancelled {job.friendly_name}." if ok else "Cannot cancel that job (wrong state)."
        self.notify(msg, severity="information" if ok else "warning")
        self._refresh_data()

    def action_retry_job(self) -> None:
        job = self._get_cursor_job()
        if not job:
            self.notify("No job selected.", severity="error")
            return
        new_id = self.controller.retry_job(job.job_id)
        if new_id:
            self.notify(f"Retrying as new job {new_id[:8]}…", severity="information")
        else:
            self.notify("Only failed/cancelled jobs can be retried.", severity="warning")
        self._refresh_data()

    def action_clear_completed(self) -> None:
        n = self.controller.clear_completed()
        self.notify(f"Cleared {n} completed job(s).", severity="information")
        self._refresh_data()

    def action_delete_job(self) -> None:
        job = self._get_cursor_job()
        if not job:
            self.notify("No job selected.", severity="error")
            return
        if job.status == "running":
            self.notify("Cannot delete a running job — cancel it first.", severity="error")
            return
        self.controller.delete_job(job.job_id)
        self.notify(f"Deleted {job.friendly_name}.", severity="information")
        self._refresh_data()

    def action_filter_all(self) -> None:
        self._status_filter = None
        self.query_one("#filter-bar", Static).update(
            "Filter: [bold]ALL[/bold]  F1=All F2=Running F3=Failed"
        )
        self._refresh_data()

    def action_filter_running(self) -> None:
        self._status_filter = "running"
        self.query_one("#filter-bar", Static).update(
            "Filter: [bold cyan]RUNNING[/bold cyan]  F1=All F2=Running F3=Failed"
        )
        self._refresh_data()

    def action_filter_failed(self) -> None:
        self._status_filter = "failed"
        self.query_one("#filter-bar", Static).update(
            "Filter: [bold red]FAILED[/bold red]  F1=All F2=Running F3=Failed"
        )
        self._refresh_data()
