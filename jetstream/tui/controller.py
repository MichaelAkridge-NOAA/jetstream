"""
Thin adapter/controller layer between the TUI widgets and JetStream services.

All database and service calls go through this module so widgets stay
isolated from SQLAlchemy sessions, subprocess management, and service
internals.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

# ---------------------------------------------------------------------------
# View-model dataclasses consumed by widgets
# ---------------------------------------------------------------------------

@dataclass
class JobVM:
    """Lightweight view-model for a single upload job."""
    id: int
    job_id: str
    friendly_name: str
    status: str
    source_path: str
    destination: str
    progress_percent: float
    total_files: int
    files_uploaded: int
    total_size_bytes: float
    bytes_uploaded: float
    dry_run: bool
    upload_tool: str
    error_message: Optional[str]
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    scheduled_for: Optional[datetime]
    duration_seconds: Optional[float]
    upload_output: Optional[str]
    log_path: Optional[str]

    @property
    def destination_display(self) -> str:
        return self.destination[:60] + "…" if len(self.destination) > 60 else self.destination

    @property
    def size_display(self) -> str:
        return _fmt_bytes(self.total_size_bytes)

    @property
    def speed_display(self) -> str:
        if self.duration_seconds and self.duration_seconds > 0 and self.bytes_uploaded > 0:
            bps = self.bytes_uploaded / self.duration_seconds
            return _fmt_bytes(bps) + "/s"
        return "—"

    @property
    def status_icon(self) -> str:
        return {
            "running":   "⟳",
            "queued":    "⏳",
            "pending":   "·",
            "scheduled": "⏰",
            "completed": "✓",
            "failed":    "✗",
            "cancelled": "⊘",
        }.get(self.status, "?")

    @property
    def status_color(self) -> str:
        return {
            "running":   "cyan",
            "queued":    "yellow",
            "pending":   "white",
            "scheduled": "blue",
            "completed": "green",
            "failed":    "red",
            "cancelled": "dim",
        }.get(self.status, "white")


@dataclass
class QueueStatusVM:
    running_count: int
    queued_count: int
    max_concurrent: int
    paused: bool
    running_jobs: List[str]
    queued_jobs: List[str]


@dataclass
class StatsVM:
    total: int
    running: int
    queued: int
    completed: int
    failed: int
    cancelled: int
    scheduled: int
    total_bytes_uploaded: float
    total_files_uploaded: int


@dataclass
class BucketObjectVM:
    name: str
    size_bytes: float
    updated: Optional[str]
    kind: str  # "prefix" or "object"

    @property
    def size_display(self) -> str:
        if self.kind == "prefix":
            return "—"
        return _fmt_bytes(self.size_bytes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(b: float) -> str:
    if b < 1024:
        return f"{b:.0f} B"
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KB"
    if b < 1024 ** 3:
        return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"


def _fmt_ts(ts: float) -> str:
    """Format a Unix timestamp to a readable UTC string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _job_to_vm(job) -> JobVM:
    """Convert an SQLAlchemy UploadJob row to a JobVM."""
    dest = f"gs://{job.destination_bucket}"
    if job.destination_path:
        dest += f"/{job.destination_path}"
    total_bytes = job.total_size_bytes or 0.0
    bytes_up = job.bytes_uploaded or 0.0
    progress = round((bytes_up / total_bytes * 100) if total_bytes > 0 else 0.0, 1)
    dur = None
    if job.started_at and job.completed_at:
        s = job.started_at.replace(tzinfo=timezone.utc) if job.started_at.tzinfo is None else job.started_at
        e = job.completed_at.replace(tzinfo=timezone.utc) if job.completed_at.tzinfo is None else job.completed_at
        dur = (e - s).total_seconds()
    elif job.started_at:
        s = job.started_at.replace(tzinfo=timezone.utc) if job.started_at.tzinfo is None else job.started_at
        dur = (datetime.now(timezone.utc) - s).total_seconds()

    return JobVM(
        id=job.id,
        job_id=job.job_id,
        friendly_name=job.friendly_name or job.job_id[:16],
        status=job.status,
        source_path=job.source_path,
        destination=dest,
        progress_percent=progress,
        total_files=job.total_files or 0,
        files_uploaded=job.files_uploaded or 0,
        total_size_bytes=total_bytes,
        bytes_uploaded=bytes_up,
        dry_run=bool(job.dry_run),
        upload_tool=job.upload_tool or "gcloud",
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        scheduled_for=job.scheduled_for,
        duration_seconds=dur,
        upload_output=job.upload_output,
        log_path=job.log_path,
    )


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class JetStreamController:
    """
    Wraps JetStream services and database access for TUI consumption.

    The controller is instantiated once and shared across all screens via
    ``app.controller``.  It initialises the database and scheduler on
    ``startup()`` and tears them down on ``shutdown()``.
    """

    def __init__(self) -> None:
        self._initialised = False
        self._gcs_client: Any = None  # cached GCS client (avoids repeated ADC init)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """Initialise database (synchronous, safe to call from on_ready)."""
        if self._initialised:
            return
        from ..database import init_db
        init_db()
        self._initialised = True

    async def start_scheduler(self) -> None:
        """Start the background upload scheduler."""
        from ..scheduler import scheduler
        await scheduler.start()

    async def shutdown(self) -> None:
        """Stop scheduler and close the database cleanly."""
        try:
            from ..scheduler import scheduler
            await scheduler.stop()
        except Exception:
            pass
        try:
            from ..database import close_db
            close_db()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Job queries
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        status_filter: Optional[str] = None,
        limit: int = 200,
    ) -> List[JobVM]:
        from ..database import SessionLocal, UploadJob
        db = SessionLocal()
        try:
            q = db.query(UploadJob)
            if status_filter and status_filter != "all":
                q = q.filter(UploadJob.status == status_filter)
            jobs = q.order_by(UploadJob.created_at.desc()).limit(limit).all()
            return [_job_to_vm(j) for j in jobs]
        finally:
            db.close()

    def get_job(self, job_id: str) -> Optional[JobVM]:
        from ..database import SessionLocal, UploadJob
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            return _job_to_vm(job) if job else None
        finally:
            db.close()

    def get_stats(self) -> StatsVM:
        from ..database import SessionLocal, UploadJob
        from sqlalchemy import func
        db = SessionLocal()
        try:
            rows = (
                db.query(UploadJob.status, func.count(UploadJob.id))
                .group_by(UploadJob.status)
                .all()
            )
            counts: Dict[str, int] = {r[0]: r[1] for r in rows}
            total_bytes = db.query(func.sum(UploadJob.bytes_uploaded)).scalar() or 0.0
            total_files = db.query(func.sum(UploadJob.files_uploaded)).scalar() or 0
            total = sum(counts.values())
            return StatsVM(
                total=total,
                running=counts.get("running", 0),
                queued=counts.get("queued", 0),
                completed=counts.get("completed", 0),
                failed=counts.get("failed", 0),
                cancelled=counts.get("cancelled", 0),
                scheduled=counts.get("scheduled", 0),
                total_bytes_uploaded=float(total_bytes),
                total_files_uploaded=int(total_files),
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Queue actions
    # ------------------------------------------------------------------

    def get_queue_status(self) -> QueueStatusVM:
        from ..services import queue_manager
        s = queue_manager.get_queue_status()
        return QueueStatusVM(
            running_count=s["running_count"],
            queued_count=s["queued_count"],
            max_concurrent=s["max_concurrent"],
            paused=s["paused"],
            running_jobs=s["running_jobs"],
            queued_jobs=s["queued_jobs"],
        )

    def pause_queue(self) -> None:
        from ..services import queue_manager
        queue_manager.pause()

    def resume_queue(self) -> None:
        from ..services import queue_manager
        queue_manager.resume()

    def cancel_job(self, job_id: str) -> bool:
        from ..database import SessionLocal, UploadJob
        from ..services import upload_service
        upload_service.cancel_upload(job_id)
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if job and job.status in ("running", "queued", "pending", "scheduled"):
                job.status = "cancelled"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return True
            return False
        finally:
            db.close()

    def retry_job(self, job_id: str) -> Optional[str]:
        """
        Create a clone of a failed/cancelled job and queue it.
        Returns the new job_id on success, None on failure.
        """
        from ..database import SessionLocal, UploadJob
        from ..services import generate_friendly_job_name, queue_manager
        db = SessionLocal()
        try:
            orig = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not orig or orig.status not in ("failed", "cancelled"):
                return None
            new_id = str(uuid.uuid4())
            new_job = UploadJob(
                job_id=new_id,
                friendly_name=generate_friendly_job_name(orig.source_path),
                status="queued",
                source_path=orig.source_path,
                destination_bucket=orig.destination_bucket,
                destination_path=orig.destination_path,
                total_files=orig.total_files,
                total_size_bytes=orig.total_size_bytes,
                dry_run=orig.dry_run,
                recursive=orig.recursive,
                threads=orig.threads,
                upload_tool=orig.upload_tool,
                log_path=orig.log_path,
                filters=orig.filters,
                no_clobber=orig.no_clobber,
                auto_retry=orig.auto_retry,
                auto_retry_delay_minutes=orig.auto_retry_delay_minutes,
                max_auto_retries=orig.max_auto_retries,
            )
            db.add(new_job)
            db.commit()
            db.refresh(new_job)
            queue_manager.add_to_queue(new_id)
            # Kick the scheduler to pick it up
            asyncio.get_event_loop().create_task(self._kick_queue(new_id))
            return new_id
        finally:
            db.close()

    async def _kick_queue(self, job_id: str) -> None:
        from ..routers.uploads import process_upload_job
        from ..config import settings
        await process_upload_job(job_id, settings.DATABASE_URL)

    def clear_completed(self) -> int:
        """Mark all completed jobs as cleared (hidden). Returns count cleared."""
        from ..database import SessionLocal, UploadJob
        db = SessionLocal()
        try:
            jobs = db.query(UploadJob).filter(UploadJob.status == "completed").all()
            for j in jobs:
                j.cleared = True
            db.commit()
            return len(jobs)
        finally:
            db.close()

    def delete_job(self, job_id: str) -> bool:
        from ..database import SessionLocal, UploadJob
        db = SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if job:
                db.delete(job)
                db.commit()
                return True
            return False
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------

    async def create_job(self, params: Dict[str, Any]) -> str:
        """
        Validate params, create a DB row, queue it, and kick the processor.
        Returns the new job_id.
        """
        from ..database import SessionLocal, UploadJob
        from ..models import UploadRequest
        from ..services import (
            FileFilter, FolderAnalyzer,
            generate_friendly_job_name, queue_manager,
        )
        from ..config import settings
        import logging
        log = logging.getLogger(__name__)

        # Validate via pydantic model
        req = UploadRequest(**params)

        file_filter = FileFilter(
            include_patterns=None,
            exclude_patterns=req.exclude_patterns,
            exclude_folders=req.exclude_folders,
        )
        analyzer = FolderAnalyzer(file_filter)
        try:
            stats = await asyncio.to_thread(
                analyzer.analyze, req.source_path, req.recursive
            )
        except Exception as e:
            raise ValueError(f"Folder analysis failed: {e}") from e

        user_friendly_name = params.pop("friendly_name", None)
        params.pop("custom_command", None)
        log_dir = os.path.join(os.getcwd(), "logs")
        initial_status = "scheduled" if req.scheduled_for else "queued"

        # ── Split-by-folder: one job per immediate subfolder ─────────
        if req.split_by_folder:
            subfolders = await asyncio.to_thread(analyzer.analyze_subfolders, req.source_path)
            if not subfolders:
                raise ValueError("No subfolders found — nothing to split into separate jobs.")

            job_ids = []
            for sf in subfolders:
                sf_name = sf["name"]
                sf_path = os.path.join(req.source_path, sf_name)
                base_dest = req.destination_path or ""
                sf_dest = f"{base_dest}/{sf_name}".lstrip("/") if base_dest else sf_name
                sf_job_id = str(uuid.uuid4())
                sf_friendly = generate_friendly_job_name(sf_path)
                sf_log = os.path.join(log_dir, f"{sf_friendly}.log")

                db = SessionLocal()
                try:
                    job = UploadJob(
                        job_id=sf_job_id,
                        friendly_name=sf_friendly,
                        status=initial_status,
                        source_path=sf_path,
                        destination_bucket=req.destination_bucket,
                        destination_path=sf_dest,
                        total_files=sf.get("total_files", 0),
                        total_size_bytes=sf.get("total_size_bytes", 0.0),
                        dry_run=req.dry_run,
                        recursive=req.recursive,
                        threads=req.threads,
                        split_by_folder=False,
                        upload_tool=req.upload_tool,
                        scheduled_for=req.scheduled_for,
                        log_path=sf_log,
                        filters={
                            "exclude_patterns": req.exclude_patterns,
                            "exclude_folders": req.exclude_folders,
                        },
                        no_clobber=req.no_clobber,
                        auto_retry=req.auto_retry,
                        auto_retry_delay_minutes=req.auto_retry_delay_minutes,
                        max_auto_retries=req.max_auto_retries,
                    )
                    db.add(job)
                    db.commit()
                    db.refresh(job)
                finally:
                    db.close()

                if initial_status == "queued":
                    queue_manager.add_to_queue(sf_job_id)
                    asyncio.create_task(self._kick_queue(sf_job_id))
                job_ids.append(sf_job_id)

            log.info(f"[TUI] Created {len(job_ids)} split jobs from {req.source_path}")
            return f"split_{len(job_ids)}_jobs"

        # ── Single job ───────────────────────────────────────────────
        job_id = str(uuid.uuid4())
        friendly_name = user_friendly_name or generate_friendly_job_name(req.source_path)
        log_path = os.path.join(log_dir, f"{friendly_name}.log")

        db = SessionLocal()
        try:
            job = UploadJob(
                job_id=job_id,
                friendly_name=friendly_name,
                status=initial_status,
                source_path=req.source_path,
                destination_bucket=req.destination_bucket,
                destination_path=req.destination_path or "",
                total_files=stats.get("total_files", 0),
                total_size_bytes=stats.get("total_size_bytes", 0.0),
                dry_run=req.dry_run,
                recursive=req.recursive,
                threads=req.threads,
                split_by_folder=False,
                upload_tool=req.upload_tool,
                scheduled_for=req.scheduled_for,
                log_path=log_path,
                filters={
                    "exclude_patterns": req.exclude_patterns,
                    "exclude_folders": req.exclude_folders,
                },
                no_clobber=req.no_clobber,
                auto_retry=req.auto_retry,
                auto_retry_delay_minutes=req.auto_retry_delay_minutes,
                max_auto_retries=req.max_auto_retries,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        finally:
            db.close()

        if initial_status == "queued":
            queue_manager.add_to_queue(job_id)
            asyncio.create_task(self._kick_queue(job_id))

        log.info(f"[TUI] Created job {job_id} ({friendly_name}) status={initial_status}")
        return job_id

    # ------------------------------------------------------------------
    # Folder analysis (for job creation preflight)
    # ------------------------------------------------------------------

    async def analyze_folder(self, path: str, recursive: bool = True) -> Dict[str, Any]:
        from ..services import FolderAnalyzer, FileFilter
        analyzer = FolderAnalyzer(FileFilter())
        return await asyncio.to_thread(analyzer.analyze, path, recursive)

    # ------------------------------------------------------------------
    # Bucket browsing
    # ------------------------------------------------------------------

    def _get_gcs_client(self) -> Any:
        """Return a cached GCS client, creating it on first call."""
        if self._gcs_client is None:
            try:
                from google.cloud import storage as gcs
            except ImportError:
                raise RuntimeError("google-cloud-storage is not installed.")
            self._gcs_client = gcs.Client()
        return self._gcs_client

    async def list_bucket_objects(
        self, bucket_name: str, prefix: str = ""
    ) -> List[BucketObjectVM]:
        """
        List top-level objects and prefixes in a GCS bucket path.
        Requires google-cloud-storage credentials in the environment.
        """
        try:
            from google.cloud import storage as gcs  # noqa: F401 — ensure installed
        except ImportError:
            raise RuntimeError("google-cloud-storage is not installed.")

        # Strip gs:// prefix if user pasted a full URI
        bucket_name = bucket_name.strip()
        if bucket_name.startswith("gs://"):
            bucket_name = bucket_name[5:]
        # Also strip any trailing path — only the bucket name should be here
        bucket_name = bucket_name.split("/")[0].strip("/")

        client = self._get_gcs_client()

        def _list():
            # Use the stable single-pass pattern: iterate the blobs iterator
            # to completion, then read .prefixes (populated during iteration).
            blobs_iter = client.list_blobs(
                bucket_name,
                prefix=prefix if prefix else None,
                delimiter="/",
                page_size=50,   # fetch 50 at a time — reduces first-byte latency
                max_results=500,  # hard cap to prevent scanning huge buckets
            )
            blob_results: List[BucketObjectVM] = []
            for blob in blobs_iter:
                # Skip "folder placeholder" blobs (zero-byte objects ending in /)
                if blob.name.endswith("/") and blob.size == 0:
                    continue
                blob_results.append(BucketObjectVM(
                    name=blob.name,
                    size_bytes=blob.size or 0,
                    updated=blob.updated.isoformat() if blob.updated else None,
                    kind="object",
                ))
            # Prefixes (virtual directories) are available after iteration
            prefix_results: List[BucketObjectVM] = [
                BucketObjectVM(name=p, size_bytes=0, updated=None, kind="prefix")
                for p in sorted(blobs_iter.prefixes)
            ]
            # Return prefixes first (directory-browser convention)
            return prefix_results + blob_results

        return await asyncio.to_thread(_list)

    async def get_bucket_summary(self, bucket_name: str, prefix: str = "") -> Dict[str, Any]:
        """Return rich analytics data for a bucket path.

        Parameters
        ----------
        bucket_name:
            Bare bucket name or a full ``gs://bucket/prefix`` URI.
        prefix:
            Optional GCS prefix to scope the scan (already normalised,
            ends with ``/`` or is empty).  When empty the whole bucket
            is scanned.

        Returns a dict consumed by ``BucketAnalyticsScreen``.
        """
        try:
            from google.cloud import storage as gcs  # noqa: F401
        except ImportError:
            raise RuntimeError("google-cloud-storage is not installed.")

        # Strip gs:// and path — only the bucket name goes to the API
        bucket_name = bucket_name.strip()
        if bucket_name.startswith("gs://"):
            bucket_name = bucket_name[5:]
        bucket_name = bucket_name.split("/")[0].strip("/")

        client = self._get_gcs_client()
        _prefix = prefix  # capture for closure

        def _summarize() -> Dict[str, Any]:
            from collections import defaultdict
            import os

            prefix_sizes: Dict[str, int] = defaultdict(int)
            prefix_counts: Dict[str, int] = defaultdict(int)
            ext_sizes: Dict[str, int] = defaultdict(int)
            ext_counts: Dict[str, int] = defaultdict(int)
            timeline: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "size": 0})
            size_buckets = {"<1 KB": 0, "1 KB–1 MB": 0, "1–100 MB": 0, ">100 MB": 0}
            total_size = 0
            total_objects = 0
            newest: list = []   # (updated_ts, name, size)
            oldest: list = []

            blobs_iter = client.list_blobs(
                bucket_name,
                prefix=_prefix if _prefix else None,
                page_size=500,
            )

            for blob in blobs_iter:
                sz = blob.size or 0
                total_size += sz
                total_objects += 1

                # ---- top-level folder relative to the scanned prefix ----
                rel = blob.name[len(_prefix):] if _prefix and blob.name.startswith(_prefix) else blob.name
                parts = rel.split("/")
                folder = parts[0] if len(parts) > 1 else "(root)"
                prefix_sizes[folder] += sz
                prefix_counts[folder] += 1

                # ---- extension ----
                base = os.path.basename(blob.name)
                if "." in base:
                    ext = "." + base.rsplit(".", 1)[-1].lower()
                else:
                    ext = "(no ext)"
                ext_sizes[ext] += sz
                ext_counts[ext] += 1

                # ---- size distribution ----
                if sz < 1_024:
                    size_buckets["<1 KB"] += 1
                elif sz < 1_048_576:
                    size_buckets["1 KB–1 MB"] += 1
                elif sz < 104_857_600:
                    size_buckets["1–100 MB"] += 1
                else:
                    size_buckets[">100 MB"] += 1

                # ---- timeline ----
                if blob.updated:
                    month = blob.updated.strftime("%Y-%m")
                    timeline[month]["count"] += 1
                    timeline[month]["size"] += sz

                # ---- newest / oldest ----
                if blob.updated:
                    ts = blob.updated.timestamp()
                    newest.append((ts, blob.name, sz))
                    oldest.append((ts, blob.name, sz))

            # Sort and trim
            newest.sort(key=lambda x: x[0], reverse=True)
            oldest.sort(key=lambda x: x[0])

            top_by_size = sorted(
                [{"name": k, "size": v, "count": prefix_counts[k]} for k, v in prefix_sizes.items()],
                key=lambda x: x["size"], reverse=True,
            )[:12]
            top_by_count = sorted(
                [{"name": k, "count": v, "size": prefix_sizes[k]} for k, v in prefix_counts.items()],
                key=lambda x: x["count"], reverse=True,
            )[:12]
            top_exts = sorted(
                [{"ext": k, "count": v, "size": ext_sizes[k]} for k, v in ext_counts.items()],
                key=lambda x: x["count"], reverse=True,
            )[:15]
            timeline_sorted = [
                {"month": m, "count": d["count"], "size": d["size"]}
                for m, d in sorted(timeline.items())
            ]

            return {
                "bucket": bucket_name,
                "prefix": _prefix or "",
                "total_objects": total_objects,
                "total_size_bytes": total_size,
                "avg_size_bytes": (total_size / total_objects) if total_objects else 0,
                "top_prefixes_by_size": top_by_size,
                "top_prefixes_by_count": top_by_count,
                "extension_breakdown": top_exts,
                "size_distribution": [
                    {"label": k, "count": v} for k, v in size_buckets.items()
                ],
                "timeline": timeline_sorted,
                "newest_files": [
                    {"name": n, "updated": _fmt_ts(t), "size": s}
                    for t, n, s in newest[:8]
                ],
                "oldest_files": [
                    {"name": n, "updated": _fmt_ts(t), "size": s}
                    for t, n, s in oldest[:8]
                ],
            }

        return await asyncio.to_thread(_summarize)

    # ------------------------------------------------------------------
    # Auth / settings
    # ------------------------------------------------------------------

    def check_gcs_auth(self) -> Dict[str, Any]:
        """Return a dict describing the current GCS auth state."""
        result: Dict[str, Any] = {
            "adc_available": False,
            "gcloud_account": None,
            "service_account": None,
            "error": None,
        }
        try:
            import google.auth
            creds, project = google.auth.default()
            result["adc_available"] = True
            result["project"] = project
            if hasattr(creds, "service_account_email"):
                result["service_account"] = creds.service_account_email
        except Exception as e:
            result["error"] = str(e)

        try:
            import subprocess
            out = subprocess.check_output(
                ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                timeout=5,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            result["gcloud_account"] = out.strip() or None
        except Exception:
            pass

        return result
