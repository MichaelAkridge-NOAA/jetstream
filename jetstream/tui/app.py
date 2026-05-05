"""
JetStream TUI — main Textual application.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding

from .controller import JetStreamController
from .screens.dashboard import DashboardScreen


class JetStreamApp(App):
    """
    NOAA JetStream terminal user interface.

    Boots the existing JetStream services in-process (same SQLite DB,
    same queue/scheduler) and presents them through a Textual TUI.
    """

    TITLE = "NOAA JetStream TUI"
    SUB_TITLE = "Cloud Data Manager"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+p", "command_palette", "Commands", show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.theme = "dracula"
        self.controller = JetStreamController()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        """Initialise DB, start scheduler, then push the dashboard."""
        # DB init must happen before the dashboard screen mounts so that
        # the first _refresh_data() call finds SessionLocal ready.
        self.controller.startup()
        await self.controller.start_scheduler()
        await self.push_screen(DashboardScreen(self.controller))

    async def on_unmount(self) -> None:
        """Tear down gracefully on exit."""
        await self.controller.shutdown()


def run() -> None:
    """Entry point called by the CLI."""
    app = JetStreamApp()
    app.run()
