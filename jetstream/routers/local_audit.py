"""Local filesystem audit endpoints."""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import settings
from ..database import LocalAuditFinding, LocalAuditRun, get_db
from ..services import LocalAuditService
from .. import database as db_module

router = APIRouter()


class LocalAuditScanRequest(BaseModel):
    """Request model for local filesystem scan."""
    path: str = Field(..., description="Windows local drive/folder path (example: T:\\)")
    recursive: bool = Field(True, description="Whether to recursively scan subfolders")


class StartLocalAuditResponse(BaseModel):
    """Response model for asynchronous local audit startup."""
    run_id: str
    status: str
    message: str


class ReRunRequest(BaseModel):
    """Optional rerun override payload."""
    path: str | None = Field(None, description="Optional override path")
    recursive: bool | None = Field(None, description="Optional override recursive flag")


def _create_run_record(db: Session, request: LocalAuditScanRequest) -> LocalAuditRun:
    """Create and persist a local audit run record before execution."""
    normalized_path = LocalAuditService.validate_windows_local_path(request.path)

    run = LocalAuditRun(
        run_id=str(uuid.uuid4()),
        status="queued",
        target_path=normalized_path,
        recursive=request.recursive,
        max_detailed_files=int(settings.LOCAL_AUDIT_MAX_DETAILED_FILES),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _build_type_breakdown(file_types: dict, total_files: int) -> list[dict]:
    """Build extension count, percentage, and category rows."""
    safe_total = max(int(total_files or 0), 1)
    sorted_types = sorted((file_types or {}).items(), key=lambda item: int(item[1] or 0), reverse=True)
    return [
        {
            "extension": extension,
            "count": int(count or 0),
            "percent_of_total": round((int(count or 0) / safe_total) * 100, 2),
            "category": LocalAuditService.categorize_extension(extension),
        }
        for extension, count in sorted_types[:50]
    ]


def _execute_local_scan(run_id: str):
    """Execute local filesystem scan in a dedicated DB session."""
    if db_module.SessionLocal is None:
        return

    db = db_module.SessionLocal()
    try:
        run = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
        if not run:
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        results = LocalAuditService.run_scan(run.target_path, recursive=bool(run.recursive))

        db.query(LocalAuditFinding).filter(LocalAuditFinding.run_id == run_id).delete(synchronize_session=False)

        findings = []
        for item in results.get("detailed_findings", []):
            findings.append(
                LocalAuditFinding(
                    run_id=run_id,
                    top_level_folder=item.get("top_level_folder", "(root)"),
                    relative_path=item.get("relative_path", ""),
                    file_name=item.get("file_name", ""),
                    extension=item.get("extension", ""),
                    file_category=item.get("file_category", "other"),
                    size_bytes=float(item.get("size_bytes", 0.0)),
                    modified_at=item.get("modified_at"),
                    age_days=int(item.get("age_days", 0)),
                    is_temp=bool(item.get("is_temp", False)),
                )
            )

        if findings:
            db.bulk_save_objects(findings)

        summary = results.get("summary", {})
        run.status = "completed"
        run.scan_mode = summary.get("scan_mode", "detailed")
        run.total_files = int(summary.get("total_files", 0))
        run.total_size_bytes = float(summary.get("total_size_bytes", 0.0))
        run.subfolder_count = int(summary.get("subfolder_count", 0))
        run.file_types = summary.get("file_types", {})
        run.top_level_folders = results.get("top_level_folders", [])
        run.recommendations = results.get("recommendations", [])
        run.max_detailed_files = int(results.get("max_detailed_files", settings.LOCAL_AUDIT_MAX_DETAILED_FILES))
        run.detailed_truncated = bool(results.get("detailed_truncated", False))
        run.skip_permission_count = int(results.get("skip_permission_count", 0))
        run.scan_duration_seconds = float(results.get("scan_duration_seconds", 0.0))
        run.completed_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as exc:
        run = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.post("/scan/start", response_model=StartLocalAuditResponse)
async def start_local_scan(
    request: LocalAuditScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a local audit run and execute asynchronously."""
    try:
        run = _create_run_record(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    background_tasks.add_task(_execute_local_scan, run.run_id)

    return StartLocalAuditResponse(
        run_id=run.run_id,
        status="queued",
        message="Local audit scan queued and running in background",
    )


@router.get("/runs")
async def list_local_audit_runs(limit: int = 20, db: Session = Depends(get_db)):
    """List recent local audit runs."""
    rows = db.query(LocalAuditRun).order_by(LocalAuditRun.created_at.desc()).limit(limit).all()
    return {"runs": [row.to_dict() for row in rows]}


@router.get("/runs/{run_id}")
async def get_local_audit_run(run_id: str, db: Session = Depends(get_db)):
    """Get a local audit run by ID."""
    row = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Local audit run not found")
    return row.to_dict()


@router.get("/runs/{run_id}/summary")
async def get_local_audit_summary(run_id: str, db: Session = Depends(get_db)):
    """Return aggregate summary suitable for dashboard cards and tables."""
    run = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Local audit run not found")

    top_types = _build_type_breakdown(run.file_types or {}, int(run.total_files or 0))

    return {
        "run": run.to_dict(),
        "top_file_types": top_types,
        "recommendations": run.recommendations or [],
    }


@router.delete("/runs/clear")
async def clear_local_audit_runs(scope: str = "finished", db: Session = Depends(get_db)):
    """Clear local audit runs and associated findings.

    scope:
    - finished: completed/failed/cancelled runs
    - failed: failed only
    - all: all runs
    """
    normalized_scope = (scope or "finished").strip().lower()
    allowed = {"finished", "failed", "all"}
    if normalized_scope not in allowed:
        raise HTTPException(status_code=400, detail=f"scope must be one of: {', '.join(sorted(allowed))}")

    query = db.query(LocalAuditRun)
    if normalized_scope == "finished":
        query = query.filter(LocalAuditRun.status.in_(["completed", "failed", "cancelled"]))
    elif normalized_scope == "failed":
        query = query.filter(LocalAuditRun.status == "failed")

    runs = query.all()
    if not runs:
        return {
            "scope": normalized_scope,
            "deleted_runs": 0,
            "deleted_findings": 0,
            "message": "No local audit runs matched clear scope",
        }

    run_ids = [run.run_id for run in runs]
    deleted_findings = (
        db.query(LocalAuditFinding)
        .filter(LocalAuditFinding.run_id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(LocalAuditRun)
        .filter(LocalAuditRun.run_id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    return {
        "scope": normalized_scope,
        "deleted_runs": int(deleted_runs or 0),
        "deleted_findings": int(deleted_findings or 0),
        "message": "Local audit runs cleared",
    }


@router.post("/runs/{run_id}/rerun", response_model=StartLocalAuditResponse)
async def rerun_local_audit(
    run_id: str,
    payload: ReRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Queue a new run based on a previous run's parameters."""
    existing = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Local audit run not found")

    target_path = payload.path if payload.path else existing.target_path
    recursive = existing.recursive if payload.recursive is None else bool(payload.recursive)

    try:
        request = LocalAuditScanRequest(path=target_path, recursive=recursive)
        new_run = _create_run_record(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    background_tasks.add_task(_execute_local_scan, new_run.run_id)

    return StartLocalAuditResponse(
        run_id=new_run.run_id,
        status="queued",
        message="Local audit re-run queued and running in background",
    )


@router.get("/runs/{run_id}/folders")
async def get_local_audit_folders(run_id: str, db: Session = Depends(get_db)):
    """Return top-level folder breakdown for a run."""
    run = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Local audit run not found")

    return {
        "run_id": run_id,
        "folders": run.top_level_folders or [],
    }


@router.get("/runs/{run_id}/details")
async def get_local_audit_details(
    run_id: str,
    folder: str | None = None,
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "size_bytes",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
):
    """Return paginated detailed file rows for a run, optionally filtered by top-level folder."""
    run = db.query(LocalAuditRun).filter(LocalAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Local audit run not found")

    query = db.query(LocalAuditFinding).filter(LocalAuditFinding.run_id == run_id)
    if folder:
        query = query.filter(LocalAuditFinding.top_level_folder == folder)

    safe_limit = min(max(limit, 1), 500)

    sort_columns = {
        "size_bytes": LocalAuditFinding.size_bytes,
        "age_days": LocalAuditFinding.age_days,
        "file_name": LocalAuditFinding.file_name,
        "modified_at": LocalAuditFinding.modified_at,
    }
    column = sort_columns.get(sort_by, LocalAuditFinding.size_bytes)
    if (sort_order or "desc").lower() == "asc":
        query = query.order_by(column.asc())
    else:
        query = query.order_by(column.desc())

    total = query.count()
    rows = query.offset(skip).limit(safe_limit).all()

    return {
        "run_id": run_id,
        "folder": folder,
        "total": total,
        "skip": skip,
        "limit": safe_limit,
        "findings": [row.to_dict() for row in rows],
    }
