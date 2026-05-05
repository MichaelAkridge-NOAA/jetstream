"""Host system metrics widget (CPU, memory, disk, and network rates)."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from time import monotonic

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from ..controller import _fmt_bytes

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


class SystemMetricsWidget(Widget):
    """Compact host metrics panel for quick machine health checks."""

    DEFAULT_CSS = """
    SystemMetricsWidget {
        height: 5;
        background: $panel-darken-2;
        padding: 0 2;
        color: $text;
    }
    #system-metrics-text {
        height: 5;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._last_t: float | None = None
        self._last_net = None
        self._last_disk = None
        self._up_hist: deque[float] = deque(maxlen=28)
        self._down_hist: deque[float] = deque(maxlen=28)
        self._diskw_hist: deque[float] = deque(maxlen=28)

    def compose(self) -> ComposeResult:
        yield Static("", id="system-metrics-text")

    def on_mount(self) -> None:
        self._refresh_metrics()
        self.set_interval(1.5, self._refresh_metrics)

    def _rate_value(self, current: int, previous: int, elapsed: float) -> float:
        if elapsed <= 0:
            return 0.0
        return max(0.0, (current - previous) / elapsed)

    def _fmt_rate(self, value: float) -> str:
        return f"{_fmt_bytes(value)}/s"

    def _sparkline(self, values: deque[float], width: int = 18) -> str:
        """Render a compact sparkline using block characters."""
        if not values:
            return "-" * width

        chars = "▁▂▃▄▅▆▇█"
        vals = list(values)
        if len(vals) < width:
            vals = [0.0] * (width - len(vals)) + vals
        else:
            vals = vals[-width:]

        vmax = max(vals)
        if vmax <= 0:
            return chars[0] * width

        out: list[str] = []
        for v in vals:
            idx = int((v / vmax) * (len(chars) - 1))
            out.append(chars[idx])
        return "".join(out)

    def _refresh_metrics(self) -> None:
        label = self.query_one("#system-metrics-text", Static)

        if psutil is None:
            label.update("[dim]Host metrics unavailable (install psutil for CPU/NET/DISK rates).[/dim]")
            return

        now = monotonic()
        elapsed = 0.0 if self._last_t is None else now - self._last_t

        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        disk_path = Path.cwd().anchor or "/"
        disk = psutil.disk_usage(disk_path)
        net = psutil.net_io_counters()
        disk_io = psutil.disk_io_counters()

        if self._last_net is None or self._last_disk is None or elapsed <= 0:
            up_value = 0.0
            down_value = 0.0
            read_value = 0.0
            write_value = 0.0
        else:
            up_value = self._rate_value(net.bytes_sent, self._last_net.bytes_sent, elapsed)
            down_value = self._rate_value(net.bytes_recv, self._last_net.bytes_recv, elapsed)
            read_value = self._rate_value(disk_io.read_bytes, self._last_disk.read_bytes, elapsed)
            write_value = self._rate_value(disk_io.write_bytes, self._last_disk.write_bytes, elapsed)

        self._up_hist.append(up_value)
        self._down_hist.append(down_value)
        self._diskw_hist.append(write_value)

        up_rate = self._fmt_rate(up_value)
        down_rate = self._fmt_rate(down_value)
        read_rate = self._fmt_rate(read_value)
        write_rate = self._fmt_rate(write_value)

        badges: list[str] = []
        if cpu >= 85:
            badges.append("[bold yellow]CPU HOT[/bold yellow]")
        if disk.percent >= 90:
            badges.append("[bold red]DISK HIGH[/bold red]")
        if up_value < 128 * 1024 and down_value < 128 * 1024:
            badges.append("[dim]NET IDLE[/dim]")
        badge_text = "  ".join(badges) if badges else "[green]HEALTHY[/green]"

        text = (
            f"[bold]Host:[/bold] CPU {cpu:>4.0f}%  MEM {mem:>4.0f}%  "
            f"Disk {disk.percent:>4.0f}% ({_fmt_bytes(disk.free)} free)\n"
            f"[bold]Net:[/bold] Up {up_rate:<10} Down {down_rate:<10}  "
            f"[bold]Disk I/O:[/bold] R {read_rate:<10} W {write_rate}\n"
            f"[cyan]U[/cyan] {self._sparkline(self._up_hist)}  "
            f"[blue]D[/blue] {self._sparkline(self._down_hist)}  "
            f"[yellow]W[/yellow] {self._sparkline(self._diskw_hist)}  {badge_text}"
        )
        label.update(text)

        self._last_t = now
        self._last_net = net
        self._last_disk = disk_io
