"""Animated JetStream logo widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


# ASCII art frames — enhanced animation with wave flow and directional energy
# Each frame cycles through wave patterns to suggest streaming data motion
_FRAMES = [
    (
        " ╭──────────────────────╮\n"
        " │ ≈≋ NOAA JETSTREAM ≋≈ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ≋≈ NOAA JETSTREAM ≈≋ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ~≋ NOAA JETSTREAM ≋~ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ≈~ NOAA JETSTREAM ~≈ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ∿≈ NOAA JETSTREAM ≈∿ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ≋∿ NOAA JETSTREAM ∿≋ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ~∿ NOAA JETSTREAM ∿~ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
    (
        " ╭──────────────────────╮\n"
        " │ ∿~ NOAA JETSTREAM ~∿ │\n"
        " │    Optics SI · GCS   │\n"
        " ╰──────────────────────╯\n"
        "   Cloud Storage Manager"
    ),
]

# Cycle through a blue→cyan→green palette to suggest data flow and energy
_COLORS = [
    "#63b3ed",  # light blue
    "#4299e1",  # medium blue
    "#38a169",  # green (cloud/data)
    "#00b4d8",  # cyan (flow)
    "#0096c7",  # deeper cyan
    "#2b6cb0",  # dark blue
    "#006d9d",  # navy (flow)
    "#00a896",  # teal (data)
]


class LogoWidget(Widget):
    """
    A compact animated brand widget for the TUI header.

    Displays "NOAA JETSTREAM" with Optics SI center affiliation and
    a "  Cloud Storage Manager" tagline. Cycles through wave patterns
    with a vibrant blue→cyan→green palette to suggest streaming data
    movement. Animation is smooth and subtle.
    """

    DEFAULT_CSS = """
    LogoWidget {
        height: 8;
        width: 26;
        background: $panel;
        padding: 1 0 0 0;
    }
    """

    _frame: reactive[int] = reactive(0)

    def on_mount(self) -> None:
        # 8 frames at 600ms per frame = 4.8s full cycle (smooth without distraction)
        self.set_interval(0.6, self._advance_frame)

    def _advance_frame(self) -> None:
        self._frame = (self._frame + 1) % len(_FRAMES)

    def render(self):  # type: ignore[override]
        color = _COLORS[self._frame % len(_COLORS)]
        text = _FRAMES[self._frame]
        from rich.text import Text as RichText
        rt = RichText(text, style=f"bold {color}")
        return rt
