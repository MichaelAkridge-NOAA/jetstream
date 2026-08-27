"""
Lightweight date/time picker modal for Textual.

Usage:
    screen.app.push_screen(DateTimePickerScreen(initial_iso), callback)

The callback receives either an ISO-8601 string (e.g. "2026-06-15T14:30:00")
or None if the user cancelled.
"""

from __future__ import annotations

import calendar as _cal
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class DateTimePickerScreen(ModalScreen[str | None]):
    """Modal calendar + time picker. Returns ISO-8601 string or None."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    DateTimePickerScreen {
        align: center middle;
        background: $background 55%;
    }

    #picker-dialog {
        width: 46;
        height: 36;
        max-width: 100%;
        max-height: 100%;
        background: $surface;
        border: thick $accent;
        padding: 1 1;
        overflow-y: auto;
    }

    /* Kill the top/bottom bevel borders that render as separator lines */
    DateTimePickerScreen Button {
        border-top: none !important;
        border-bottom: none !important;
        min-width: 4;
    }

    /* Title bar */
    #title-row {
        height: 3;
        border: none;
    }
    #picker-title {
        width: 1fr;
        height: 3;
        content-align: left middle;
        text-style: bold;
        color: $accent;
    }
    #btn-close {
        width: 9;
        height: 3;
    }

    /* Month navigation */
    #month-nav {
        height: 3;
        border: none;
        margin-top: 1;
    }
    #prev-month, #next-month {
        width: 5;
        height: 3;
    }
    #month-label {
        width: 1fr;
        height: 3;
        content-align: center middle;
        text-align: center;
        color: $text;
        text-style: bold;
    }

    /* Day-of-week headers */
    #day-headers {
        height: 1;
        border: none;
        margin-top: 1;
    }
    .day-hdr {
        width: 1fr;
        height: 1;
        text-align: center;
        color: $accent;
        text-style: bold;
    }

    /* Calendar rows */
    .cal-week {
        height: 2;
        border: none;
    }
    .cal-cell {
        width: 1fr;
        height: 2;
        min-width: 0;
        border: none !important;
        padding: 0;
        color: $text;
        background: $surface;
    }
    .cal-cell.selected {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    .cal-cell.today {
        color: $success;
        text-style: bold;
    }

    /* Today shortcut */
    #today-btn {
        width: 1fr;
        height: 2;
        margin-top: 1;
    }

    /* Time section */
    #time-row {
        height: 3;
        border: none;
        margin-top: 1;
    }
    #time-lbl {
        width: 7;
        height: 3;
        content-align: left middle;
        color: $text;
    }
    .time-btn {
        width: 3;
        height: 3;
        min-width: 3;
    }
    #hour-val, #min-val {
        width: 4;
        height: 3;
        content-align: center middle;
        text-align: center;
        color: $text;
        text-style: bold;
    }
    #time-sep {
        width: 2;
        height: 3;
        content-align: center middle;
        color: $text;
    }
    #ampm-btn {
        width: 5;
        height: 3;
        min-width: 5;
        margin-left: 1;
    }
    #mode-btn {
        width: 6;
        height: 3;
        min-width: 6;
        margin-left: 1;
    }

    /* Action buttons */
    #action-row {
        height: 3;
        border: none;
        margin-top: 1;
    }
    #btn-dt-set {
        width: 1fr;
        margin-right: 1;
    }
    #btn-dt-cancel {
        width: 1fr;
    }
    """

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        try:
            dt = datetime.fromisoformat(initial.strip()) if initial.strip() else datetime.now()
        except ValueError:
            dt = datetime.now()
        self._year   = dt.year
        self._month  = dt.month
        self._day    = dt.day
        self._hour   = dt.hour
        self._minute = dt.minute
        self._use_ampm = False
        _today = datetime.now()
        self._today_year  = _today.year
        self._today_month = _today.month
        self._today_day   = _today.day

    @property
    def _ampm_str(self) -> str:
        return "PM" if self._hour >= 12 else "AM"

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):

            with Horizontal(id="title-row"):
                yield Label("📅  Pick Date & Time", id="picker-title")
                yield Button("✕ Close", id="btn-close", variant="error")

            with Horizontal(id="month-nav"):
                yield Button("◄", id="prev-month", variant="default")
                yield Label("", id="month-label")
                yield Button("►", id="next-month", variant="default")

            with Horizontal(id="day-headers"):
                for hdr in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
                    yield Label(hdr, classes="day-hdr")

            for week in range(6):
                with Horizontal(classes="cal-week"):
                    for dow in range(7):
                        yield Button(" ", id=f"cell-{week * 7 + dow}", classes="cal-cell")

            yield Button("★ Today", id="today-btn", variant="success")

            with Horizontal(id="time-row"):
                yield Label("Time:", id="time-lbl")
                yield Button("-", id="hour-dec", classes="time-btn")
                yield Label("00", id="hour-val")
                yield Button("+", id="hour-inc", classes="time-btn")
                yield Label(":", id="time-sep")
                yield Button("-", id="min-dec", classes="time-btn")
                yield Label("00", id="min-val")
                yield Button("+", id="min-inc", classes="time-btn")
                yield Button("AM", id="ampm-btn", variant="primary")
                yield Button("12h", id="mode-btn", variant="default")

            with Horizontal(id="action-row"):
                yield Button("✓  Set Date & Time", id="btn-dt-set", variant="primary")
                yield Button("Cancel", id="btn-dt-cancel", variant="default")

    def on_mount(self) -> None:
        self._refresh_calendar()
        self._refresh_time_labels()
        self.query_one("#ampm-btn", Button).display = False

    def on_input_focus(self, event) -> None:
        pass

    def _refresh_calendar(self) -> None:
        first_weekday, days_in_month = _cal.monthrange(self._year, self._month)
        self.query_one("#month-label", Label).update(
            f"{_cal.month_name[self._month]} {self._year}"
        )
        is_current_month = (
            self._year  == self._today_year and
            self._month == self._today_month
        )
        for i in range(42):
            btn = self.query_one(f"#cell-{i}", Button)
            day_num = i - first_weekday + 1
            if 1 <= day_num <= days_in_month:
                btn.label    = str(day_num)
                btn.disabled = False
                btn.set_class(day_num == self._day, "selected")
                btn.set_class(is_current_month and day_num == self._today_day, "today")
            else:
                btn.label    = " "
                btn.disabled = True
                btn.remove_class("selected", "today")

    def _advance_month(self, delta: int) -> None:
        self._month += delta
        if self._month < 1:
            self._month = 12
            self._year -= 1
        elif self._month > 12:
            self._month = 1
            self._year += 1
        self._day = min(self._day, _cal.monthrange(self._year, self._month)[1])
        self._refresh_calendar()

    def _refresh_time_labels(self) -> None:
        h_lbl = self.query_one("#hour-val", Label)
        m_lbl = self.query_one("#min-val",  Label)
        if self._use_ampm:
            display_h = self._hour % 12 or 12
            h_lbl.update(str(display_h).zfill(2))
        else:
            h_lbl.update(str(self._hour).zfill(2))
        m_lbl.update(str(self._minute).zfill(2))

    def _toggle_ampm_mode(self) -> None:
        self._use_ampm = not self._use_ampm
        ampm_btn = self.query_one("#ampm-btn", Button)
        mode_btn = self.query_one("#mode-btn", Button)
        if self._use_ampm:
            ampm_btn.label   = self._ampm_str
            ampm_btn.display = True
            mode_btn.label   = "24h"
        else:
            ampm_btn.display = False
            mode_btn.label   = "12h"
        self._refresh_time_labels()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        if bid in ("btn-close", "btn-dt-cancel"):
            self.dismiss(None)
            return

        if bid == "prev-month":
            self._advance_month(-1)
            return

        if bid == "next-month":
            self._advance_month(1)
            return

        if bid == "today-btn":
            today = datetime.now()
            self._year, self._month, self._day = today.year, today.month, today.day
            self._refresh_calendar()
            return

        if bid.startswith("cell-"):
            idx = int(bid[5:])
            first_weekday, days_in_month = _cal.monthrange(self._year, self._month)
            day_num = idx - first_weekday + 1
            if 1 <= day_num <= days_in_month:
                self._day = day_num
                self._refresh_calendar()
            return

        if bid == "hour-dec":
            self._hour = (self._hour - 1) % 24
            self._refresh_time_labels()
            if self._use_ampm:
                self.query_one("#ampm-btn", Button).label = self._ampm_str
            return
        if bid == "hour-inc":
            self._hour = (self._hour + 1) % 24
            self._refresh_time_labels()
            if self._use_ampm:
                self.query_one("#ampm-btn", Button).label = self._ampm_str
            return
        if bid == "min-dec":
            self._minute = (self._minute - 1) % 60
            self._refresh_time_labels()
            return
        if bid == "min-inc":
            self._minute = (self._minute + 1) % 60
            self._refresh_time_labels()
            return

        if bid == "ampm-btn":
            self._hour = (self._hour + 12) % 24
            self.query_one("#ampm-btn", Button).label = self._ampm_str
            self._refresh_time_labels()
            return

        if bid == "mode-btn":
            self._toggle_ampm_mode()
            return

        if bid == "btn-dt-set":
            try:
                result = datetime(self._year, self._month, self._day, self._hour, self._minute)
                self.dismiss(result.strftime("%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                pass
            return

    def action_cancel(self) -> None:
        self.dismiss(None)