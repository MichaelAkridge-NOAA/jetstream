"""Cloud bucket audit and safe quarantine endpoints."""

from collections import defaultdict
from datetime import datetime, timezone
import csv
import io
import json
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import CloudAuditFinding, CloudAuditRun, get_db
from .. import database as db_module
from .cloud_analyzer import get_storage_client

router = APIRouter()


class CloudAuditScanRequest(BaseModel):
    """Request model for GCS junk scan."""
    bucket_name: str = Field(..., description="GCS bucket name")
    prefix: str = Field("", description="Optional object prefix")
    max_objects: int = Field(0, description="Override max objects to scan; 0 uses default")
    junk_regex_patterns: list[str] | None = Field(None, description="Regex patterns to flag junk")
    dry_run: bool = Field(True, description="Scan is always read-only; this is tracked for intent")


class QuarantineRequest(BaseModel):
    """Request model for quarantine move operation."""
    confirm_text: str = Field(..., description="Must be MOVE_TO_QUARANTINE to run")
    quarantine_bucket: str | None = Field(None, description="Override quarantine bucket")
    quarantine_prefix: str = Field("quarantine", description="Destination namespace prefix")
    dry_run: bool = Field(True, description="Preview move without changing objects")
    limit: int = Field(500, ge=1, le=5000, description="Max findings to process")


class StartScanResponse(BaseModel):
    """Response model for asynchronous scan startup."""
    run_id: str
    status: str
    message: str


def _compile_patterns(patterns: list[str]) -> list[tuple[str, re.Pattern]]:
    compiled: list[tuple[str, re.Pattern]] = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern, re.IGNORECASE)))
        except re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid regex '{pattern}': {exc}")
    return compiled


def _compute_destination_name(quarantine_prefix: str, source_bucket_name: str, object_name: str) -> str:
    """Build deterministic quarantine object destination."""
    normalized_prefix = quarantine_prefix.strip("/")
    if normalized_prefix:
        return f"{normalized_prefix}/{source_bucket_name}/{object_name}"
    return f"{source_bucket_name}/{object_name}"


def _create_run_record(db: Session, request: CloudAuditScanRequest) -> CloudAuditRun:
    """Create and persist an audit run record before execution."""
    configured_patterns = request.junk_regex_patterns or settings.GCS_JUNK_REGEX_PATTERNS
    _compile_patterns(configured_patterns)

    scan_limit = request.max_objects if request.max_objects > 0 else settings.GCS_AUDIT_SCAN_MAX_OBJECTS

    audit_run = CloudAuditRun(
        run_id=str(uuid.uuid4()),
        status="queued",
        bucket_name=request.bucket_name,
        prefix=request.prefix,
        dry_run=request.dry_run,
        scan_limit=scan_limit,
        regex_patterns=configured_patterns,
        quarantine_bucket=settings.GCS_QUARANTINE_BUCKET,
    )
    db.add(audit_run)
    db.commit()
    db.refresh(audit_run)
    return audit_run


def _is_cancel_requested(db: Session, run_id: str) -> bool:
    """Check if a run has been asked to cancel."""
    row = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not row:
        return True
    return row.status == "cancel_requested"


def _execute_scan(run_id: str):
    """Execute scan in a dedicated DB session for background execution."""
    if db_module.SessionLocal is None:
        return

    db = db_module.SessionLocal()
    try:
        audit_run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
        if not audit_run:
            return

        audit_run.status = "running"
        audit_run.started_at = datetime.now(timezone.utc)
        db.commit()

        configured_patterns = audit_run.regex_patterns or settings.GCS_JUNK_REGEX_PATTERNS
        compiled_patterns = _compile_patterns(configured_patterns)

        client = get_storage_client()
        bucket = client.bucket(audit_run.bucket_name)
        if not bucket.exists():
            raise HTTPException(status_code=404, detail=f"Bucket '{audit_run.bucket_name}' not found")

        scanned_objects = 0
        scanned_bytes = 0.0
        junk_objects = 0
        junk_bytes = 0.0
        findings_to_insert: list[CloudAuditFinding] = []

        for blob in bucket.list_blobs(prefix=audit_run.prefix):
            if scanned_objects > 0 and scanned_objects % 250 == 0 and _is_cancel_requested(db, run_id):
                audit_run.status = "cancelled"
                audit_run.completed_at = datetime.now(timezone.utc)
                db.commit()
                return

            scanned_objects += 1
            size = float(blob.size or 0)
            scanned_bytes += size

            matched_pattern = None
            for raw_pattern, compiled in compiled_patterns:
                if compiled.search(blob.name):
                    matched_pattern = raw_pattern
                    break

            if matched_pattern:
                junk_objects += 1
                junk_bytes += size
                findings_to_insert.append(
                    CloudAuditFinding(
                        run_id=run_id,
                        bucket_name=audit_run.bucket_name,
                        object_name=blob.name,
                        size_bytes=size,
                        updated_at=blob.updated,
                        matched_pattern=matched_pattern,
                        suggested_action="quarantine",
                        action_status="pending",
                    )
                )

            if len(findings_to_insert) >= 500:
                db.bulk_save_objects(findings_to_insert)
                db.commit()
                findings_to_insert.clear()

            if (audit_run.scan_limit or 0) > 0 and scanned_objects >= audit_run.scan_limit:
                audit_run.reached_scan_limit = True
                break

        if findings_to_insert:
            db.bulk_save_objects(findings_to_insert)
            db.commit()

        audit_run.status = "completed"
        audit_run.scanned_objects = scanned_objects
        audit_run.scanned_bytes = scanned_bytes
        audit_run.junk_objects = junk_objects
        audit_run.junk_bytes = junk_bytes
        audit_run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except HTTPException as exc:
        run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
        if run:
            run.status = "failed"
            run.error_message = exc.detail
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as exc:
        run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.post("/scan/start", response_model=StartScanResponse)
async def start_bucket_scan(
    request: CloudAuditScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a run and execute the bucket scan asynchronously."""
    audit_run = _create_run_record(db, request)
    background_tasks.add_task(_execute_scan, audit_run.run_id)

    return StartScanResponse(
        run_id=audit_run.run_id,
        status="queued",
        message="Scan queued and running in background",
    )


@router.post("/scan")
async def run_bucket_scan(request: CloudAuditScanRequest, db: Session = Depends(get_db)):
    """Run a synchronous bucket scan and persist junk findings."""
    audit_run = _create_run_record(db, request)
    _execute_scan(audit_run.run_id)
    db.refresh(audit_run)

    return {
        "message": "Scan completed",
        "run": audit_run.to_dict(),
    }


@router.get("/runs")
async def list_audit_runs(limit: int = 20, db: Session = Depends(get_db)):
    """List recent audit runs."""
    rows = db.query(CloudAuditRun).order_by(CloudAuditRun.created_at.desc()).limit(limit).all()
    return {"runs": [row.to_dict() for row in rows]}


@router.delete("/runs/clear-failed")
async def clear_failed_runs(db: Session = Depends(get_db)):
    """Delete failed audit runs and their findings."""
    failed_runs = db.query(CloudAuditRun).filter(CloudAuditRun.status == "failed").all()
    if not failed_runs:
        return {
            "deleted_runs": 0,
            "deleted_findings": 0,
            "message": "No failed runs to clear",
        }

    run_ids = [run.run_id for run in failed_runs]

    deleted_findings = (
        db.query(CloudAuditFinding)
        .filter(CloudAuditFinding.run_id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(CloudAuditRun)
        .filter(CloudAuditRun.run_id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    return {
        "deleted_runs": int(deleted_runs or 0),
        "deleted_findings": int(deleted_findings or 0),
        "message": "Failed audit runs cleared",
    }


@router.get("/runs/{run_id}")
async def get_audit_run(run_id: str, db: Session = Depends(get_db)):
    """Get one audit run by ID."""
    row = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Audit run not found")
    return row.to_dict()


@router.get("/runs/{run_id}/findings")
async def list_run_findings(
    run_id: str,
    action_status: str | None = None,
    skip: int = 0,
    limit: int = settings.GCS_AUDIT_FINDINGS_PAGE_SIZE,
    db: Session = Depends(get_db),
):
    """List findings for an audit run with optional status filtering."""
    run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Audit run not found")

    query = db.query(CloudAuditFinding).filter(CloudAuditFinding.run_id == run_id)
    if action_status:
        query = query.filter(CloudAuditFinding.action_status == action_status)

    total = query.count()
    findings = query.order_by(CloudAuditFinding.id.asc()).offset(skip).limit(limit).all()

    return {
        "run_id": run_id,
        "total": total,
        "skip": skip,
        "limit": limit,
        "findings": [f.to_dict() for f in findings],
    }


@router.get("/runs/{run_id}/summary")
async def get_run_summary(run_id: str, db: Session = Depends(get_db)):
    """Return aggregate stats suitable for dashboard charts."""
    run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Audit run not found")

    by_pattern_rows = (
        db.query(
            CloudAuditFinding.matched_pattern,
            func.count(CloudAuditFinding.id),
            func.sum(CloudAuditFinding.size_bytes),
        )
        .filter(CloudAuditFinding.run_id == run_id)
        .group_by(CloudAuditFinding.matched_pattern)
        .all()
    )

    prefix_counter: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "bytes": 0.0})
    findings = db.query(CloudAuditFinding.object_name, CloudAuditFinding.size_bytes).filter(CloudAuditFinding.run_id == run_id).all()
    for object_name, size_bytes in findings:
        top_prefix = (object_name.split("/", 1)[0] if "/" in object_name else "(root)") or "(root)"
        prefix_counter[top_prefix]["count"] += 1
        prefix_counter[top_prefix]["bytes"] += float(size_bytes or 0)

    top_prefixes = sorted(
        [
            {"prefix": p, "count": int(v["count"]), "bytes": float(v["bytes"])}
            for p, v in prefix_counter.items()
        ],
        key=lambda item: item["bytes"],
        reverse=True,
    )[:15]

    return {
        "run": run.to_dict(),
        "by_pattern": [
            {
                "pattern": pattern,
                "count": int(count or 0),
                "bytes": float(total_bytes or 0),
            }
            for pattern, count, total_bytes in by_pattern_rows
        ],
        "top_prefixes": top_prefixes,
    }


@router.get("/runs/{run_id}/manifest")
async def export_run_manifest(
    run_id: str,
    format: str = "csv",
    action_status: str | None = None,
    db: Session = Depends(get_db),
):
    """Export findings for a run as CSV or JSONL manifest."""
    run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Audit run not found")

    query = db.query(CloudAuditFinding).filter(CloudAuditFinding.run_id == run_id)
    if action_status:
        query = query.filter(CloudAuditFinding.action_status == action_status)
    findings = query.order_by(CloudAuditFinding.id.asc()).all()

    export_format = (format or "csv").strip().lower()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if export_format == "jsonl":
        buffer = io.StringIO()
        for finding in findings:
            payload = finding.to_dict()
            payload["quarantine_target"] = finding.quarantine_object_name
            buffer.write(json.dumps(payload) + "\n")

        filename = f"cloud_audit_{run_id}_{timestamp}.jsonl"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    if export_format != "csv":
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'jsonl'")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "run_id",
        "bucket_name",
        "object_name",
        "size_bytes",
        "matched_pattern",
        "action_status",
        "suggested_action",
        "quarantine_object_name",
        "updated_at",
        "error_message",
    ])

    for finding in findings:
        writer.writerow([
            finding.run_id,
            finding.bucket_name,
            finding.object_name,
            finding.size_bytes,
            finding.matched_pattern,
            finding.action_status,
            finding.suggested_action,
            finding.quarantine_object_name,
            finding.updated_at.isoformat() if finding.updated_at else "",
            finding.error_message or "",
        ])

    output.seek(0)
    filename = f"cloud_audit_{run_id}_{timestamp}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: Session = Depends(get_db)):
    """Request cancellation for queued/running audit runs."""
    run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Audit run not found")

    if run.status in {"completed", "failed", "cancelled"}:
        return {
            "run_id": run_id,
            "status": run.status,
            "message": "Run already finished",
        }

    run.status = "cancel_requested"
    db.commit()

    return {
        "run_id": run_id,
        "status": run.status,
        "message": "Cancellation requested",
    }


@router.post("/runs/{run_id}/quarantine")
async def quarantine_findings(run_id: str, request: QuarantineRequest, db: Session = Depends(get_db)):
    """Move flagged objects to quarantine bucket using copy-then-delete."""
    if request.confirm_text != "MOVE_TO_QUARANTINE":
        raise HTTPException(status_code=400, detail="confirm_text must be MOVE_TO_QUARANTINE")

    run = db.query(CloudAuditRun).filter(CloudAuditRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Audit run not found")

    quarantine_bucket_name = request.quarantine_bucket or run.quarantine_bucket
    if not quarantine_bucket_name:
        raise HTTPException(status_code=400, detail="No quarantine bucket configured")

    findings = (
        db.query(CloudAuditFinding)
        .filter(CloudAuditFinding.run_id == run_id, CloudAuditFinding.action_status == "pending")
        .order_by(CloudAuditFinding.id.asc())
        .limit(request.limit)
        .all()
    )

    if not findings:
        return {
            "run_id": run_id,
            "message": "No pending findings to quarantine",
            "processed": 0,
            "quarantined": 0,
            "skipped": 0,
            "errors": 0,
            "dry_run": request.dry_run,
        }

    protected_prefixes = settings.GCS_PROTECTED_PREFIXES or []
    client = get_storage_client()
    source_bucket = client.bucket(run.bucket_name)
    quarantine_bucket = client.bucket(quarantine_bucket_name)

    quarantined_count = 0
    skipped_count = 0
    error_count = 0
    moved_bytes = 0.0

    for finding in findings:
        if any(finding.object_name.startswith(pfx) for pfx in protected_prefixes):
            finding.action_status = "skipped"
            finding.error_message = "Protected prefix"
            skipped_count += 1
            continue

        destination_name = _compute_destination_name(
            request.quarantine_prefix,
            run.bucket_name,
            finding.object_name,
        )
        finding.quarantine_object_name = destination_name

        if request.dry_run:
            # Keep pending in dry-run mode so the same findings can be acted on later.
            finding.error_message = None
            continue

        try:
            source_blob = source_bucket.blob(finding.object_name)
            source_blob.reload()
            source_size = int(source_blob.size or 0)
            source_crc32c = source_blob.crc32c
            source_generation = source_blob.generation

            dest_blob = source_bucket.copy_blob(source_blob, quarantine_bucket, new_name=destination_name)
            dest_blob.reload()

            # Safety check: verify copied object before deleting source.
            if int(dest_blob.size or 0) != source_size or dest_blob.crc32c != source_crc32c:
                raise RuntimeError("Copy verification failed (size or crc32c mismatch)")

            if source_generation is not None:
                source_blob.delete(if_generation_match=source_generation)
            else:
                source_blob.delete()

            finding.action_status = "quarantined"
            finding.error_message = None
            quarantined_count += 1
            moved_bytes += float(source_size)
        except Exception as exc:
            finding.action_status = "error"
            finding.error_message = str(exc)
            error_count += 1

    if not request.dry_run:
        run.quarantined_objects = (run.quarantined_objects or 0) + quarantined_count
        run.quarantined_bytes = (run.quarantined_bytes or 0.0) + moved_bytes

    db.commit()

    return {
        "run_id": run_id,
        "quarantine_bucket": quarantine_bucket_name,
        "processed": len(findings),
        "quarantined": quarantined_count,
        "skipped": skipped_count,
        "errors": error_count,
        "dry_run": request.dry_run,
    }
