"""
Full-screen GCS bucket analytics dashboard.

Layout:
  ┌─ status bar ──────────────────────────────────────────────────────────┐
  │ 📁 Files  │  💾 Total Size  │  📊 Avg Size  │  🔤 Top File Type      │  ← stat cards
  ├───────────────────────────┬───────────────────────────────────────────┤
  │  TOP FOLDERS (by size)    │  FILE TYPE BREAKDOWN                      │
  │  ████████ bar chart       │  ██░░▒▒▓▓ stacked % bar + legend         │
  ├───────────────────────────┤  + individual bar chart                   │
  │  SIZE DISTRIBUTION        │                                           │
  │  ████ distribution bars   │                                           │
  ├───────────────────────────┴───────────────────────────────────────────┤
  │  ACTIVITY TIMELINE  ▁▂▃▄▅▆▇█ sparkline  +  monthly bars              │
  ├───────────────────────────────────┬───────────────────────────────────┤
  │  NEWEST FILES                     │  OLDEST FILES                     │
  └───────────────────────────────────┴───────────────────────────────────┘
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from ..controller import JetStreamController, _fmt_bytes

# ──────────────────────────────────────────────────────────────────────────
# Chart / rendering helpers
# ──────────────────────────────────────────────────────────────────────────

_BLOCKS = " ▏▎▍▌▋▊▉█"

# Per-type colour palette (fg for labels, bg for stacked bar segments)
_PALETTE_FG = ["#63b3ed", "#68d391", "#f6ad55", "#fc8181", "#b794f4", "#76e4f7", "#fefcbf"]
_PALETTE_BG = ["#1d5f94", "#166a30", "#7a4010", "#5a1060", "#3a3a00", "#0a5060", "#701010"]


def _bar(value: float, max_value: float, color: str = "cyan", width: int = 24) -> str:
    if max_value <= 0:
        return f"[dim]{'─' * width}[/dim]"
    fraction = min(value / max_value, 1.0)
    filled_f = fraction * width
    full = int(filled_f)
    partial = int((filled_f - full) * 8)
    b = "█" * full
    if partial and full < width:
        b += _BLOCKS[partial]
    return f"[{color}]{b.ljust(width)}[/{color}]"


def _pct(value: float, total: float) -> str:
    if total <= 0:
        return " 0.0%"
    return f"{value / total * 100:4.1f}%"


def _sparkline(values: List[float], width: int = 50) -> str:
    SPARKS = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    mx = max(values) or 1
    return "".join(SPARKS[min(int(v / mx * 7), 7)] for v in values[-width:])


def _stacked_bar(items: List[Tuple[str, float]], bar_width: int = 54) -> str:
    """Horizontal stacked bar — items is [(label, proportion 0–1), ...]."""
    out = ""
    used = 0
    for i, (_, prop) in enumerate(items):
        w = int(prop * bar_width) if i < len(items) - 1 else bar_width - used
        w = max(w, 0)
        used += w
        col = _PALETTE_BG[i % len(_PALETTE_BG)]
        out += f"[on {col}]{' ' * w}[/on {col}]"
    return out


def _stacked_legend(items: List[Tuple[str, float]]) -> str:
    parts = []
    for i, (label, prop) in enumerate(items):
        fg = _PALETTE_FG[i % len(_PALETTE_FG)]
        bg = _PALETTE_BG[i % len(_PALETTE_BG)]
        parts.append(f"[on {bg}] [/on {bg}][{fg}]{label} {_pct(prop, 1.0).strip()}[/{fg}]")
    return " ".join(parts)


def _head(title: str) -> str:
    return f"[bold cyan] {title} [/bold cyan]"


# ──────────────────────────────────────────────────────────────────────────
# Screen
# ──────────────────────────────────────────────────────────────────────────


class BucketAnalyticsScreen(Screen):
    """Multi-panel analytics dashboard for a GCS bucket or prefix."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    CSS = """
    BucketAnalyticsScreen {
        layout: vertical;
    }

    #status-bar {
        height: 1;
        padding: 0 1;
        background: $panel-darken-2;
        color: $text-muted;
    }

    /* ── stat cards row ── */
    #stats-row {
        height: auto;
        min-height: 7;
        layout: horizontal;
        padding: 0 1;
    }
    .stat-card {
        width: 1fr;
        height: 5;
        border: round $accent;
        margin: 1 1;
        content-align: center middle;
        text-align: center;
    }

    /* ── two-column panel area ── */
    #panels-row {
        height: 1fr;
        layout: horizontal;
        min-height: 18;
    }
    #left-col {
        width: 1fr;
        layout: vertical;
    }
    #right-col {
        width: 1fr;
        layout: vertical;
        border-left: tall $panel-darken-1;
    }
    #panel-folders {
        height: 2fr;
        border-bottom: dashed $panel-darken-1;
        padding: 0 1;
    }
    #panel-sizedist {
        height: 1fr;
        padding: 0 1;
    }
    #panel-types {
        height: 1fr;
        padding: 0 1;
    }

    /* ── full-width timeline ── */
    #timeline-row {
        height: 14;
        border-top: tall $panel-darken-1;
    }
    #panel-timeline {
        width: 1fr;
        padding: 0 1;
    }

    /* ── newest / oldest files row ── */
    #files-row {
        height: 10;
        layout: horizontal;
        border-top: tall $panel-darken-1;
    }
    #panel-newest {
        width: 1fr;
        padding: 0 1;
    }
    #panel-oldest {
        width: 1fr;
        padding: 0 1;
        border-left: tall $panel-darken-1;
    }

    /* Responsive adjustments */
    BucketAnalyticsScreen.-hide-cards #stats-row {
        display: none;
    }
    BucketAnalyticsScreen.-vertical-panels #panels-row {
        layout: vertical;
        height: auto;
    }
    BucketAnalyticsScreen.-vertical-panels #left-col,
    BucketAnalyticsScreen.-vertical-panels #right-col {
        width: 100%;
        height: auto;
        border-left: none;
    }
    BucketAnalyticsScreen.-vertical-panels #panel-folders,
    BucketAnalyticsScreen.-vertical-panels #panel-sizedist,
    BucketAnalyticsScreen.-vertical-panels #panel-types {
        height: 15;
    }

    BucketAnalyticsScreen.-vertical-files #files-row {
        layout: vertical;
        height: auto;
    }
    BucketAnalyticsScreen.-vertical-files #panel-newest,
    BucketAnalyticsScreen.-vertical-files #panel-oldest {
        width: 100%;
        height: 10;
        border-left: none;
        border-top: dashed $panel-darken-1;
    }
    """

    def __init__(
        self,
        controller: JetStreamController,
        bucket: str,
        prefix: str = "",
    ) -> None:
        super().__init__()
        self.controller = controller
        self._bucket = bucket
        self._prefix = prefix

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status-bar")
        with Horizontal(id="stats-row"):
            yield Static("", classes="stat-card", id="card-files")
            yield Static("", classes="stat-card", id="card-size")
            yield Static("", classes="stat-card", id="card-avg")
            yield Static("", classes="stat-card", id="card-type")
        with Horizontal(id="panels-row"):
            with Vertical(id="left-col"):
                yield RichLog(id="panel-folders", markup=True, highlight=False, wrap=False)
                yield RichLog(id="panel-sizedist", markup=True, highlight=False, wrap=False)
            with Vertical(id="right-col"):
                yield RichLog(id="panel-types", markup=True, highlight=False, wrap=False)
        with Horizontal(id="timeline-row"):
            yield RichLog(id="panel-timeline", markup=True, highlight=False, wrap=False)
        with Horizontal(id="files-row"):
            yield RichLog(id="panel-newest", markup=True, highlight=False, wrap=False)
            yield RichLog(id="panel-oldest", markup=True, highlight=False, wrap=False)
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle / actions
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._set_status("[yellow]⟳ Scanning…[/yellow]")
        self.run_worker(self._fetch(), exclusive=True, name="analytics")
        self._update_responsive_classes()

    def on_resize(self) -> None:
        self._update_responsive_classes()

    def _update_responsive_classes(self) -> None:
        width, height = self.size
        self.set_class(height < 30, "-hide-cards")
        self.set_class(width < 100, "-vertical-panels")
        self.set_class(width < 100, "-vertical-files")

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._clear_panels()
        self._set_status("[yellow]⟳ Re-scanning…[/yellow]")
        self.run_worker(self._fetch(), exclusive=True, name="analytics")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, markup: str) -> None:
        self.query_one("#status-bar", Static).update(markup)

    def _clear_panels(self) -> None:
        for pid in (
            "panel-folders", "panel-sizedist", "panel-types",
            "panel-timeline", "panel-newest", "panel-oldest",
        ):
            self.query_one(f"#{pid}", RichLog).clear()

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    async def _fetch(self) -> None:
        try:
            data = await self.controller.get_bucket_summary(
                self._bucket, prefix=self._prefix
            )
            self._draw_all(data)
            path = (
                f"gs://{data['bucket']}/{data['prefix']}"
                if data["prefix"]
                else f"gs://{data['bucket']}"
            )
            self._set_status(
                f"[green]✓  {path}  ·  {data['total_objects']:,} files"
                f"  ·  {_fmt_bytes(data['total_size_bytes'])}[/green]"
                f"  [dim]R=refresh  Esc=back[/dim]"
            )
        except Exception as exc:
            self._set_status(f"[red bold]✗  Error: {exc}[/red bold]")

    # ------------------------------------------------------------------
    # Draw helpers — one method per panel
    # ------------------------------------------------------------------

    def _draw_all(self, d: Dict[str, Any]) -> None:
        self._draw_stat_cards(d)
        self._draw_folders(d)
        self._draw_sizedist(d)
        self._draw_types(d)
        self._draw_timeline(d)
        self._draw_files(d)

    # ── Stat cards ────────────────────────────────────────────────────

    def _draw_stat_cards(self, d: Dict[str, Any]) -> None:
        top_ext = d["extension_breakdown"][0] if d["extension_breakdown"] else None
        self.query_one("#card-files", Static).update(
            f"[bold cyan]📁 FILES[/bold cyan]\n"
            f"[bold white]{d['total_objects']:,}[/bold white]"
        )
        self.query_one("#card-size", Static).update(
            f"[bold cyan]💾 TOTAL SIZE[/bold cyan]\n"
            f"[bold white]{_fmt_bytes(d['total_size_bytes'])}[/bold white]"
        )
        self.query_one("#card-avg", Static).update(
            f"[bold cyan]📊 AVG FILE[/bold cyan]\n"
            f"[bold white]{_fmt_bytes(d['avg_size_bytes'])}[/bold white]"
        )
        if top_ext:
            type_body = (
                f"[bold white]{top_ext['ext']}[/bold white]\n"
                f"[dim]{top_ext['count']:,} files[/dim]"
            )
        else:
            type_body = "[dim]—[/dim]"
        self.query_one("#card-type", Static).update(
            f"[bold cyan]🔤 TOP TYPE[/bold cyan]\n{type_body}"
        )

    # ── Top folders by size ───────────────────────────────────────────

    def _draw_folders(self, d: Dict[str, Any]) -> None:
        log = self.query_one("#panel-folders", RichLog)
        rows = d["top_prefixes_by_size"]
        total_sz = d["total_size_bytes"]
        log.write(_head("TOP FOLDERS  ·  SIZE"))
        if not rows:
            log.write("[dim]No sub-folder data.[/dim]")
            return
        max_sz = rows[0]["size"] or 1
        nw = min(max(len(r["name"]) for r in rows), 22)
        for r in rows:
            nm = r["name"][:nw].ljust(nw)
            b = _bar(r["size"], max_sz, "cyan")
            log.write(
                f" [dim]{nm}[/dim] {b}"
                f" [cyan]{_fmt_bytes(r['size']):>9}[/cyan]"
                f" [dim]{_pct(r['size'], total_sz)}[/dim]"
            )

    # ── Size distribution ─────────────────────────────────────────────

    def _draw_sizedist(self, d: Dict[str, Any]) -> None:
        log = self.query_one("#panel-sizedist", RichLog)
        dist = d["size_distribution"]
        total = d["total_objects"]
        log.write(_head("SIZE DISTRIBUTION"))
        if not dist:
            log.write("[dim]No data.[/dim]")
            return
        max_ct = max(b["count"] for b in dist) or 1
        COLORS = ["#63b3ed", "#68d391", "#f6ad55", "#fc8181"]
        for i, b in enumerate(dist):
            col = COLORS[i % len(COLORS)]
            nm = b["label"].ljust(11)
            bar = _bar(b["count"], max_ct, col, 18)
            log.write(
                f" [dim]{nm}[/dim] {bar}"
                f" [bold]{b['count']:>6,}[/bold]"
                f" [dim]{_pct(b['count'], total)}[/dim]"
            )

    # ── File type breakdown with stacked bar ──────────────────────────

    def _draw_types(self, d: Dict[str, Any]) -> None:
        log = self.query_one("#panel-types", RichLog)
        exts = d["extension_breakdown"]
        total_obj = d["total_objects"]
        log.write(_head("FILE TYPE BREAKDOWN"))
        if not exts:
            log.write("[dim]No file type data.[/dim]")
            return

        # stacked percentage bar + legend
        total_count = sum(e["count"] for e in exts) or 1
        top = exts[:6]
        rest_count = sum(e["count"] for e in exts[6:])
        segments: List[Tuple[str, float]] = [
            (e["ext"], e["count"] / total_count) for e in top
        ]
        if rest_count:
            segments.append(("other", rest_count / total_count))
        log.write(f" {_stacked_bar(segments, bar_width=54)}")
        log.write(f" {_stacked_legend(segments)}")
        log.write("")

        # individual bars
        max_ct = top[0]["count"] if top else 1
        nw = min(max(len(e["ext"]) for e in exts), 12)
        for i, e in enumerate(exts):
            col = _PALETTE_FG[i % len(_PALETTE_FG)]
            nm = e["ext"][:nw].ljust(nw)
            b = _bar(e["count"], max_ct, col, 18)
            log.write(
                f" [dim]{nm}[/dim] {b}"
                f" [bold]{e['count']:>6,}[/bold]"
                f" [dim]{_fmt_bytes(e['size']):>9}[/dim]"
                f" [dim]{_pct(e['count'], total_obj)}[/dim]"
            )

    # ── Activity timeline ─────────────────────────────────────────────

    def _draw_timeline(self, d: Dict[str, Any]) -> None:
        log = self.query_one("#panel-timeline", RichLog)
        tl = d["timeline"]
        log.write(_head("ACTIVITY TIMELINE  ·  FILES MODIFIED PER MONTH"))
        if not tl:
            log.write("[dim]No modification timestamps available.[/dim]")
            return
        counts = [m["count"] for m in tl]
        spark = _sparkline(counts, width=52)
        log.write(f" [blue]{spark}[/blue]  [dim]{len(tl)} months[/dim]")
        log.write("")
        max_ct = max(counts) or 1
        for m in tl[-16:]:
            b = _bar(m["count"], max_ct, "blue", 22)
            log.write(
                f" [dim]{m['month']}[/dim] {b}"
                f" [bold]{m['count']:>5,}[/bold]"
                f" [dim]{_fmt_bytes(m['size']):>9}[/dim]"
            )
        if len(tl) > 16:
            log.write(f"  [dim]…{len(tl) - 16} earlier months omitted[/dim]")

    # ── Newest / oldest files ─────────────────────────────────────────

    def _draw_files(self, d: Dict[str, Any]) -> None:
        newest_log = self.query_one("#panel-newest", RichLog)
        oldest_log = self.query_one("#panel-oldest", RichLog)

        newest_log.write(_head("RECENTLY MODIFIED"))
        for f in d["newest_files"]:
            nm = (f["name"].split("/")[-1] or f["name"])[:28].ljust(28)
            newest_log.write(
                f" [green]{nm}[/green]  [dim]{f['updated']}[/dim]"
                f"  [cyan]{_fmt_bytes(f['size']):>8}[/cyan]"
            )

        oldest_log.write(_head("OLDEST FILES"))
        for f in d["oldest_files"]:
            nm = (f["name"].split("/")[-1] or f["name"])[:28].ljust(28)
            oldest_log.write(
                f" [dim]{nm}[/dim]  [dim]{f['updated']}[/dim]"
                f"  [dim]{_fmt_bytes(f['size']):>8}[/dim]"
            )
