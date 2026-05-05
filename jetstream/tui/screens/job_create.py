"""
Job creation screen — guided form for queuing a new upload.

Fields map directly to UploadRequest so validation happens through
the existing Pydantic model before the job hits the DB.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, Switch, TextArea

from ..controller import JetStreamController, _fmt_bytes
from .datetime_picker import DateTimePickerScreen

# ── GCS destination quick-fill presets ──────────────────────────────────────
_GCS_BUCKETS = [
    ("PIFSC",  "nmfs_odp_pifsc/"),
    ("AFSC",   "nmfs_odp_afsc/"),
    ("SWFSC",  "nmfs_odp_swfsc/"),
    ("NEFSC",  "nmfs_odp_nefsc/"),
    ("NWFSC",  "nmfs_odp_nwfsc/"),
]

# ── Exclude pattern quick presets ────────────────────────────────────────────
_EXCLUDE_PRESETS: Dict[str, Dict[str, list]] = {
    "temp":   {"patterns": ["*.tmp", "*.temp", "*.bak", "*.swp", "~$*", "Thumbs.db", "desktop.ini"], "folders": []},
    "system": {"patterns": ["*.DS_Store", "desktop.ini", "Thumbs.db", ".git", ".svn", "__pycache__"], "folders": [".git", ".svn", "__pycache__"]},
    "noraw":  {"patterns": ["*.ARW", "*.NEF", "*.CR2", "*.CR3", "*.RAF", "*.ORF", "*.RW2", "*.DNG", "*.RAW"], "folders": []},
    "pifsc":  {"patterns": ["*.tmp", "Thumbs.db", "desktop.ini", "*.DS_Store"], "folders": ["_archive", "MISC", "DARK", "Products"]},
}


class JobCreateScreen(Screen):
    """Form screen for creating a new upload job."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("f5", "analyze", "Analyze Folder", show=True),
    ]

    CSS = """
    JobCreateScreen {
        layout: vertical;
    }

    /* ── Three-column top area ─────────────────────────────── */
    #main-cols {
        height: 1fr;
        layout: horizontal;
    }
    #col-left, #col-mid, #col-right {
        width: 1fr;
        height: 100%;
        overflow-y: auto;
        padding: 0 1;
    }
    #col-left {
        border-right: tall $panel-darken-2;
    }
    #col-mid {
        border-right: tall $panel-darken-2;
    }

    /* ── Column section headers ────────────────────────────── */
    .col-head {
        height: 1;
        color: $accent;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 1;
    }

    /* ── Standard label + widget stack ────────────────────── */
    .field-row {
        height: auto;
        margin-bottom: 1;
    }
    .field-label {
        height: 1;
        color: $text-muted;
    }
    .field-row > Input,
    .field-row > Select {
        height: 3;
    }

    /* ── 2-up switch / mixed rows ──────────────────────────── */
    .switch-pair {
        height: 5;
        layout: horizontal;
        margin-bottom: 1;
    }
    .switch-pair > Vertical {
        width: 1fr;
        height: 5;
    }
    .switch-pair > Vertical > Label {
        height: 1;
    }
    .switch-pair > Vertical > Switch,
    .switch-pair > Vertical > Input {
        height: 3;
    }

    /* ── Quick-fill / preset button rows ───────────────────── */
    #quickfill-row {
        height: 3;
        layout: horizontal;
        margin-bottom: 1;
    }
    .qf-btn {
        min-width: 7;
        margin-right: 1;
        height: 3;
    }
    #preset-row {
        height: 3;
        layout: horizontal;
        margin-bottom: 1;
    }
    .preset-btn {
        min-width: 9;
        margin-right: 1;
        height: 3;
    }

    /* ── Misc widgets ──────────────────────────────────────── */
    #gcs-preview {
        height: 1;
        color: $success;
        text-style: italic;
        margin-bottom: 1;
    }
    #analysis-result {
        height: 2;
        background: $panel-darken-1;
        padding: 0 1;
        color: $text;
        margin-bottom: 1;
    }

    /* ── Command preview (full-width bottom band) ──────────── */
    #cmd-section {
        height: auto;
        padding: 0 1 0 1;
        border-top: tall $panel-darken-2;
    }
    #cmd-display {
        height: 3;
        padding: 0 1;
        background: $panel-darken-2;
        border: tall $accent;
        color: $success;
        margin-bottom: 1;
    }
    #cmd-override {
        height: 5;
        border: tall $warning;
        margin-bottom: 1;
    }
    #cmd-copy-row {
        height: 3;
        layout: horizontal;
        margin-bottom: 1;
    }
    /* ── Schedule field with picker button ─── */
    .dt-input-row {
        height: 3;
        layout: horizontal;
    }
    .dt-input-row > Input {
        width: 1fr;
        height: 3;
    }
    #btn-pick-dt {
        width: 5;
        height: 3;
        margin-left: 1;
    }

    /* ── Bottom button bar ─────────────────────────────────── */
    #btn-row {
        height: 5;
        layout: horizontal;
        padding: 1 1;
        align: left middle;
    }
    #btn-submit {
        margin-right: 2;
    }
    #error-msg {
        height: auto;
        color: red;
        padding: 0 1;
    }
    """

    def __init__(self, controller: JetStreamController) -> None:
        super().__init__()
        self.controller = controller
        self._analyzing = False

    def compose(self) -> ComposeResult:
        yield Header()

        # ── Three columns ────────────────────────────────────────────
        with Horizontal(id="main-cols"):

            # Left: Source & Destination
            with ScrollableContainer(id="col-left"):
                yield Label("─ SOURCE & DESTINATION ─", classes="col-head")

                with Vertical(classes="field-row"):
                    yield Label("Job Name (optional)", classes="field-label")
                    yield Input(placeholder="e.g. 2026-survey-tow-data", id="job-name")

                with Vertical(classes="field-row"):
                    yield Label("Source Path *", classes="field-label")
                    yield Input(placeholder=r"C:\data\survey2026", id="source-path")

                with Vertical(classes="field-row"):
                    yield Label("GCS Destination *", classes="field-label")
                    yield Input(placeholder="nmfs_odp_pifsc/PIFSC/ESD/ARP/data", id="gcs-dest")

                yield Static("", id="gcs-preview")

                with Horizontal(id="quickfill-row"):
                    for label, _ in _GCS_BUCKETS:
                        yield Button(label, id=f"qf-{label.lower()}", classes="qf-btn", variant="default")

                yield Static(
                    "[dim]Press F5 or 'Analyze' to scan the source folder.[/dim]",
                    id="analysis-result",
                )

            # Middle: Upload Settings
            with ScrollableContainer(id="col-mid"):
                yield Label("─ UPLOAD SETTINGS ─", classes="col-head")

                with Vertical(classes="field-row"):
                    yield Label("Upload Tool", classes="field-label")
                    yield Select(
                        [
                            ("gcloud storage (recommended)", "gcloud"),
                            ("gsutil (legacy)", "gsutil"),
                        ],
                        value="gcloud",
                        id="upload-tool",
                        allow_blank=False,
                    )

                with Vertical(classes="field-row"):
                    yield Label("Parallel Threads", classes="field-label")
                    yield Input("4", id="threads", restrict=r"[0-9]*", max_length=2)

                yield Label("─ FLAGS ─", classes="col-head")

                with Horizontal(classes="switch-pair"):
                    with Vertical():
                        yield Label("Dry Run", classes="field-label")
                        yield Switch(value=False, id="dry-run")
                    with Vertical():
                        yield Label("Recursive", classes="field-label")
                        yield Switch(value=True, id="recursive")

                with Horizontal(classes="switch-pair"):
                    with Vertical():
                        yield Label("No-Clobber", classes="field-label")
                        yield Switch(value=False, id="no-clobber")
                    with Vertical():
                        yield Label("Split by Folder", classes="field-label")
                        yield Switch(value=False, id="split-folder")

            # Right: Scheduling + File Filtering
            with ScrollableContainer(id="col-right"):
                yield Label("─ SCHEDULING & AUTO-RETRY ─", classes="col-head")

                with Vertical(classes="field-row"):
                    yield Label("Schedule For (optional)", classes="field-label")
                    with Horizontal(classes="dt-input-row"):
                        yield Input(placeholder="2026-05-10T14:00:00", id="scheduled-for")
                        yield Button("📅", id="btn-pick-dt", variant="default")

                with Horizontal(classes="switch-pair"):
                    with Vertical():
                        yield Label("Auto-Retry on Failure", classes="field-label")
                        yield Switch(value=False, id="auto-retry")
                    with Vertical():
                        yield Label("Retry Delay (min)", classes="field-label")
                        yield Input("30", id="retry-delay", restrict=r"[0-9]*", max_length=4)

                with Vertical(classes="field-row"):
                    yield Label("Max Retries", classes="field-label")
                    yield Input("3", id="max-retries", restrict=r"[0-9]*", max_length=2)

                yield Label("─ FILE FILTERING ─", classes="col-head")

                with Horizontal(id="preset-row"):
                    yield Button("🗑️ Temp",    id="preset-temp",   classes="preset-btn", variant="default")
                    yield Button("💻 System",  id="preset-system", classes="preset-btn", variant="default")
                    yield Button("🐟 PIFSC",   id="preset-pifsc",  classes="preset-btn", variant="default")
                    yield Button("🚫 No RAW",  id="preset-noraw",  classes="preset-btn", variant="default")
                    yield Button("❌ Clear",   id="preset-clear",  classes="preset-btn", variant="error")

                with Vertical(classes="field-row"):
                    yield Label("Exclude Patterns (comma-separated)", classes="field-label")
                    yield Input(placeholder="*.tmp, *.bak, Thumbs.db", id="exclude-patterns")

                with Vertical(classes="field-row"):
                    yield Label("Exclude Folders (comma-separated)", classes="field-label")
                    yield Input(placeholder="_archive, MISC, DARK", id="exclude-folders")

        # ── Command Preview — spans full width ───────────────────────
        with Vertical(id="cmd-section"):
            yield Label("─ COMMAND PREVIEW ─", classes="col-head")
            yield Label("Live preview — updates as you fill in the form above", classes="field-label")
            yield Static("", id="cmd-display")
            yield Label(
                "Command Override  [dim](optional — edit to run a custom command instead)[/dim]",
                classes="field-label",
            )
            yield TextArea("", id="cmd-override", show_line_numbers=False)
            with Horizontal(id="cmd-copy-row"):
                yield Button("↺ Copy from Preview", id="btn-copy-cmd", variant="default")
                yield Button("× Clear Override",    id="btn-clear-cmd", variant="default")
            yield Static("", id="error-msg")

        with Horizontal(id="btn-row"):
            yield Button("Submit", variant="primary", id="btn-submit")
            yield Button("Analyze (F5)", variant="default", id="btn-analyze")
            yield Button("Cancel (Esc)", variant="error", id="btn-cancel")

        yield Footer()

    # ------------------------------------------------------------------
    # Input change — live GCS preview
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in ("gcs-dest", "source-path"):
            self._update_gcs_preview()
        if event.input.id != "cmd-override":
            self._rebuild_preview()

    def _update_gcs_preview(self) -> None:
        import os
        src_raw  = self.query_one("#source-path", Input).value.strip()
        dest_raw = self.query_one("#gcs-dest",    Input).value.strip()
        preview  = self.query_one("#gcs-preview", Static)

        if not dest_raw:
            preview.update("")
            return

        # Normalise destination to gs://bucket/prefix/
        if dest_raw.startswith("gs://"):
            dest_base = dest_raw
        else:
            dest_base = "gs://" + dest_raw.lstrip("/")
        dest_base = dest_base.rstrip("/")

        if src_raw:
            # Show where the source folder will land inside the destination
            # e.g.  src=C:\data\survey2026  dest=gs://bucket/path
            #       → gs://bucket/path/survey2026/
            folder_name = os.path.basename(src_raw.rstrip("/\\"))
            if folder_name:
                final = f"{dest_base}/{folder_name}/"
                preview.update(
                    f"[dim]→[/dim] [green]{final}[/green]  "
                    f"[dim]([italic]{src_raw}[/italic] uploaded into this prefix)[/dim]"
                )
                return

        # No valid source yet — just show the normalised dest
        preview.update(f"[dim]→[/dim] [green]{dest_base}/[/green]")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._rebuild_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._rebuild_preview()

    def _build_preview_command(self) -> str:
        """Build upload command string from current form values (mirrors services.py)."""
        src_raw  = self.query_one("#source-path", Input).value.strip()
        dest_raw = self.query_one("#gcs-dest",    Input).value.strip()
        if not src_raw or not dest_raw:
            return ""

        gcs_dest = dest_raw if dest_raw.startswith("gs://") else "gs://" + dest_raw.lstrip("/")

        tool_sel   = self.query_one("#upload-tool", Select)
        tool       = str(tool_sel.value) if tool_sel.value else "gcloud"
        dry_run    = self.query_one("#dry-run",    Switch).value
        recursive  = self.query_one("#recursive",  Switch).value
        no_clobber = self.query_one("#no-clobber", Switch).value

        pat_raw  = self.query_one("#exclude-patterns", Input).value.strip()
        fold_raw = self.query_one("#exclude-folders",  Input).value.strip()
        patterns = [p.strip() for p in pat_raw.split(",")  if p.strip()]
        folders  = [f.strip() for f in fold_raw.split(",") if f.strip()]

        def glob_to_regex(pattern: str) -> str:
            if any(c in pattern for c in ('|', '(', ')', '^', '$', '{', '[')):
                return pattern
            if pattern.startswith('*.'):
                return '.*' + re.escape(pattern[1:]) + '$'
            if '*' in pattern:
                return re.escape(pattern).replace('\\*', '.*')
            return re.escape(pattern)

        all_exclude = [glob_to_regex(p) for p in patterns]
        for folder in folders:
            folder_esc = re.escape(folder)
            all_exclude.append(f'.*/{folder_esc}/.*')
            all_exclude.append(f'^{folder_esc}/.*')

        if tool == "gsutil":
            parts = ["gsutil", "-m", "rsync"]
            if dry_run:    parts.append("-n")
            if recursive:  parts.append("-r")
            if all_exclude:
                combined = "|".join(f"({p})" for p in all_exclude)
                parts += ["-x", f'"{combined}"']
        else:
            parts = ["gcloud", "storage", "rsync"]
            if dry_run:    parts.append("--dry-run")
            if recursive:  parts.append("--recursive")
            parts.append("--checksums-only")
            if no_clobber: parts.append("--no-clobber")
            if all_exclude:
                combined = "|".join(f"({p})" for p in all_exclude)
                parts.append(f'--exclude="{combined}"')

        def _q(s: str) -> str:
            return f'"{s}"' if (' ' in s or '\\' in s) else s

        parts.extend([_q(src_raw), _q(gcs_dest)])
        return " ".join(parts)

    def _rebuild_preview(self) -> None:
        """Update the read-only command display Static."""
        try:
            cmd = self._build_preview_command()
            display = self.query_one("#cmd-display", Static)
            if cmd:
                display.update(f"[bold green]{cmd}[/bold green]")
            else:
                display.update("[dim]Fill in source path and GCS destination above…[/dim]")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Folder analysis
    # ------------------------------------------------------------------

    def action_analyze(self) -> None:
        asyncio.get_event_loop().call_soon(lambda: self._run_analysis())

    def _run_analysis(self) -> None:
        self.run_worker(self._do_analyze(), exclusive=True, name="analyze")

    async def _do_analyze(self) -> None:
        src = self.query_one("#source-path", Input).value.strip()
        result = self.query_one("#analysis-result", Static)
        if not src:
            result.update("[red]Enter a source path first.[/red]")
            return
        result.update("[yellow]Analysing…[/yellow]")
        try:
            stats = await self.controller.analyze_folder(src)
            size = _fmt_bytes(stats.get("total_size_bytes", 0))
            files = stats.get("total_files", 0)
            folders = stats.get("subfolder_count", 0)
            result.update(
                f"[green]Found {files:,} files in {folders} subfolders — {size} total[/green]"
            )
        except Exception as e:
            result.update(f"[red]Analysis failed: {e}[/red]")

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        # GCS quick-fill
        for label, path in _GCS_BUCKETS:
            if bid == f"qf-{label.lower()}":
                inp = self.query_one("#gcs-dest", Input)
                inp.value = path
                inp.focus()
                return

        # Exclude pattern presets
        if bid.startswith("preset-"):
            self._apply_preset(bid[7:])
            return

        if bid == "btn-cancel":
            self.action_cancel()
        elif bid == "btn-analyze":
            self._run_analysis()
        elif bid == "btn-submit":
            self.run_worker(self._do_submit(), exclusive=True, name="submit")
        elif bid == "btn-pick-dt":
            current = self.query_one("#scheduled-for", Input).value
            self.app.push_screen(DateTimePickerScreen(current), self._on_datetime_picked)
        elif bid == "btn-copy-cmd":
            cmd = self._build_preview_command()
            self.query_one("#cmd-override", TextArea).load_text(cmd)
        elif bid == "btn-clear-cmd":
            self.query_one("#cmd-override", TextArea).load_text("")

    def _on_datetime_picked(self, result: str | None) -> None:
        """Callback from DateTimePickerScreen — fill in the schedule input."""
        if result:
            self.query_one("#scheduled-for", Input).value = result

    def _apply_preset(self, key: str) -> None:
        """Merge a named preset into the exclude pattern/folder inputs."""
        pat_input   = self.query_one("#exclude-patterns", Input)
        fold_input  = self.query_one("#exclude-folders",  Input)

        if key == "clear":
            pat_input.value  = ""
            fold_input.value = ""
            return

        preset = _EXCLUDE_PRESETS.get(key)
        if not preset:
            return

        # Merge: keep any user-typed values, append new ones
        def _merge(current: str, additions: list) -> str:
            existing = {v.strip() for v in current.split(",") if v.strip()}
            for a in additions:
                existing.add(a)
            return ", ".join(sorted(existing))

        pat_input.value  = _merge(pat_input.value,  preset["patterns"])
        fold_input.value = _merge(fold_input.value, preset["folders"])
        self.notify(f"Preset '{key}' applied.", severity="information")

    def action_cancel(self) -> None:
        self.app.pop_screen()

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _do_submit(self) -> None:
        error_widget = self.query_one("#error-msg", Static)
        error_widget.update("")

        def _val(widget_id: str) -> str:
            return self.query_one(f"#{widget_id}", Input).value.strip()

        def _switch(widget_id: str) -> bool:
            return self.query_one(f"#{widget_id}", Switch).value

        source     = _val("source-path")
        gcs_dest   = _val("gcs-dest")
        job_name   = _val("job-name")
        custom_cmd = self.query_one("#cmd-override", TextArea).text.strip()

        if not source or not gcs_dest:
            error_widget.update("[red]Source path and GCS destination are required.[/red]")
            return

        try:
            threads = int(_val("threads") or "4")
        except ValueError:
            threads = 4

        try:
            retry_delay  = int(_val("retry-delay")  or "30")
            max_retries  = int(_val("max-retries")   or "3")
        except ValueError:
            retry_delay, max_retries = 30, 3

        def _split_csv(val: str) -> list | None:
            items = [v.strip() for v in val.split(",") if v.strip()]
            return items if items else None

        exclude_patterns = _split_csv(_val("exclude-patterns"))
        exclude_folders  = _split_csv(_val("exclude-folders"))

        scheduled_raw = _val("scheduled-for")
        scheduled_for = None
        if scheduled_raw:
            try:
                from datetime import datetime
                scheduled_for = datetime.fromisoformat(scheduled_raw)
            except ValueError:
                error_widget.update(
                    "[red]Invalid schedule datetime. Use ISO 8601, e.g. 2026-05-10T14:00:00[/red]"
                )
                return

        tool_select = self.query_one("#upload-tool", Select)
        tool = str(tool_select.value) if tool_select.value else "gcloud"

        params: Dict[str, Any] = {
            "source_path":              source,
            "gcs_destination":          gcs_dest,
            "upload_tool":              tool,
            "threads":                  threads,
            "dry_run":                  _switch("dry-run"),
            "recursive":                _switch("recursive"),
            "no_clobber":               _switch("no-clobber"),
            "split_by_folder":          _switch("split-folder"),
            "auto_retry":               _switch("auto-retry"),
            "auto_retry_delay_minutes": retry_delay,
            "max_auto_retries":         max_retries,
            "exclude_patterns":         exclude_patterns,
            "exclude_folders":          exclude_folders,
        }
        if scheduled_for:
            params["scheduled_for"] = scheduled_for
        if job_name:
            params["friendly_name"] = job_name
        if custom_cmd:
            params["custom_command"] = custom_cmd

        try:
            job_id = await self.controller.create_job(params)
            if job_id.startswith("split_"):
                n = job_id.split("_")[1]
                self.notify(f"Created {n} split jobs (one per subfolder).", severity="information")
            else:
                self.notify(f"Job queued: {job_id[:8]}…", severity="information")
            self.app.pop_screen()
        except Exception as e:
            error_widget.update(f"[red]Failed to create job: {e}[/red]")
