"""
Bucket browser screen — explore GCS bucket contents and get summaries.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, RichLog, Static

from ..controller import BucketObjectVM, JetStreamController, _fmt_bytes
from .bucket_analytics import BucketAnalyticsScreen


class BucketBrowserScreen(Screen):
    """Browse a GCS bucket's contents and view aggregate statistics."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("enter", "drill_down", "Open Prefix", show=True),
        Binding("backspace", "go_up", "Up", show=True),
    ]

    CSS = """
    BucketBrowserScreen {
        layout: vertical;
    }
    #nav-row {
        height: 5;
        layout: horizontal;
        padding: 1 2;
        background: $panel-darken-1;
    }
    #bucket-input {
        width: 1fr;
        margin-right: 1;
    }
    #prefix-label {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        text-style: italic;
    }
    #main-row {
        height: 1fr;
        layout: horizontal;
    }
    #left-browser {
        width: 65%;
    }
    #right-info {
        width: 35%;
        border-left: tall $accent;
        padding: 0 1;
    }
    #summary-log {
        height: 1fr;
    }
    #status-bar {
        height: 3;
        background: $panel-darken-2;
        padding: 1 2;
    }
    """

    def __init__(self, controller: JetStreamController) -> None:
        super().__init__()
        self.controller = controller
        self._current_bucket = ""
        self._current_prefix = ""
        self._prefix_stack: List[str] = []
        self._objects: List[BucketObjectVM] = []

    @staticmethod
    def _parse_gs_uri(uri: str) -> tuple:
        """Split a full gs://bucket/path or bare bucket name into (bucket, prefix).

        Returns:
            (bucket_name, prefix)  where prefix is '' for root, or ends with '/'.
        """
        uri = uri.strip().rstrip("/")
        if uri.startswith("gs://"):
            uri = uri[5:]
        parts = uri.split("/", 1)
        bucket = parts[0]
        prefix = (parts[1].strip("/") + "/") if len(parts) > 1 and parts[1] else ""
        return bucket, prefix

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="nav-row"):
            yield Input(placeholder="my-bucket-name", id="bucket-input")
            yield Button("Browse", variant="primary", id="btn-browse", tooltip="Scan and list bucket contents")
            yield Button("Summary", variant="default", id="btn-summary", tooltip="View aggregate analytics for this path")
        yield Static("[dim]No bucket loaded — enter a bucket name and press Browse.[/dim]", id="prefix-label")
        with Horizontal(id="main-row"):
            with Vertical(id="left-browser"):
                yield DataTable(id="object-table", zebra_stripes=True, cursor_type="row")
            with Vertical(id="right-info"):
                yield Label("[bold]Info[/bold]")
                yield RichLog(id="summary-log", highlight=True, markup=True, wrap=True)
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#object-table", DataTable)
        table.add_columns("Type", "Name", "Size", "Updated")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_go_up(self) -> None:
        if self._prefix_stack:
            self._current_prefix = self._prefix_stack.pop()
            self._load_objects()
        elif self._current_prefix:
            self._current_prefix = ""
            self._load_objects()

    def action_refresh(self) -> None:
        self._load_objects()

    def action_drill_down(self) -> None:
        table = self.query_one("#object-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._objects):
            obj = self._objects[idx]
            if obj.kind == "prefix":
                self._prefix_stack.append(self._current_prefix)
                self._current_prefix = obj.name
                self._load_objects()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Pressing Enter in the bucket input triggers a browse."""
        if event.input.id == "bucket-input":
            self._start_browse(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-browse":
            raw = self.query_one("#bucket-input", Input).value
            self._start_browse(raw)
        elif event.button.id == "btn-summary":
            raw = self.query_one("#bucket-input", Input).value.strip() or self._current_bucket
            if not raw:
                self.notify("Enter a bucket name or gs:// path first.", severity="warning")
                return
            bucket, input_prefix = self._parse_gs_uri(raw)
            # Prefer the deeper of the two: prefix from the input URI, or
            # wherever the user has already navigated to in the browser.
            effective_prefix = self._current_prefix or input_prefix
            self.app.push_screen(BucketAnalyticsScreen(self.controller, bucket, effective_prefix))

    def _start_browse(self, raw: str) -> None:
        """Parse raw input (may be a full gs:// URI) and start browsing."""
        raw = raw.strip()
        if not raw:
            self.notify("Enter a bucket name or gs:// path first.", severity="warning")
            return
        bucket, initial_prefix = self._parse_gs_uri(raw)
        self._current_bucket = bucket
        self._current_prefix = initial_prefix
        self._prefix_stack = []
        self._load_objects()

    def _load_objects(self) -> None:
        if not self._current_bucket:
            return
        self.run_worker(
            self._do_list(self._current_bucket, self._current_prefix),
            exclusive=True,
            name="list",
        )

    # ------------------------------------------------------------------
    # Async workers
    # ------------------------------------------------------------------

    async def _do_list(self, bucket: str, prefix: str) -> None:
        status = self.query_one("#status-bar", Static)
        prefix_label = self.query_one("#prefix-label", Static)
        status.update("[yellow]Loading…[/yellow]")
        prefix_label.update(
            f"[bold]{bucket}[/bold] / [dim]{prefix or '(root)'}[/dim]"
        )
        try:
            objects = await self.controller.list_bucket_objects(bucket, prefix)
            self._objects = objects
            self._rebuild_table(objects)
            status.update(
                f"[green]{len(objects)} item(s) in gs://{bucket}/{prefix}[/green]"
            )
        except Exception as e:
            status.update(f"[red]Error: {e}[/red]")
            log = self.query_one("#summary-log", RichLog)
            log.clear()
            log.write(f"[red]{e}[/red]")

    def _rebuild_table(self, objects: List[BucketObjectVM]) -> None:
        table = self.query_one("#object-table", DataTable)
        table.clear()
        for obj in objects:
            icon = "📁" if obj.kind == "prefix" else "📄"
            name = obj.name
            if obj.kind == "prefix" and self._current_prefix:
                # Show relative name
                name = name[len(self._current_prefix):]
            table.add_row(icon, name, obj.size_display, obj.updated or "—")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#object-table", DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._objects):
            obj = self._objects[idx]
            log = self.query_one("#summary-log", RichLog)
            log.clear()
            log.write(f"[bold]Name:[/bold] {obj.name}")
            log.write(f"[bold]Kind:[/bold] {obj.kind}")
            log.write(f"[bold]Size:[/bold] {obj.size_display}")
            if obj.updated:
                log.write(f"[bold]Updated:[/bold] {obj.updated}")
            if obj.kind == "prefix":
                log.write("[dim]Press Enter to browse this prefix.[/dim]")
