"""Cloud Storage Analyzer - On-demand GCS bucket analysis."""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime, timezone
import asyncio
import subprocess
import threading
import uuid
import shutil
from sqlalchemy.orm import Session

from ..database import UploadJob, get_db
from ..services import redact_sensitive_text

# Lazy import for Google Cloud Storage to avoid startup crashes
# Will be imported only when actually needed
def get_storage_client():
    """Lazy import and initialize Google Cloud Storage client."""
    try:
        from google.cloud import storage
        return storage.Client()
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Google Cloud Storage library not installed. Install with: pip install google-cloud-storage"
        )
    except Exception as e:
        detail = redact_sensitive_text(str(e))
        raise HTTPException(
            status_code=401,
            detail=(
                "Authentication failed. Please run 'gcloud auth application-default login' "
                "or set GOOGLE_APPLICATION_CREDENTIALS environment variable. "
                f"Error: {detail}"
            )
        )

router = APIRouter()

# Store for tracking cloud transfer jobs (in-memory for simplicity)
cloud_transfer_jobs = {}

class CloudAnalysisRequest(BaseModel):
    """Request model for cloud storage analysis."""
    bucket_name: str = Field(..., description="GCS bucket name")
    prefix: str = Field("", description="Folder prefix to analyze (optional)")
    max_depth: int = Field(3, description="Maximum folder depth to analyze")

class CloudTransferRequest(BaseModel):
    """Request model for cloud-to-cloud transfer."""
    source_path: str = Field(..., description="Source GCS path (gs://bucket/path or bucket/path)")
    dest_path: str = Field(..., description="Destination GCS path (gs://bucket/path or bucket/path)")
    recursive: bool = Field(True, description="Include subfolders")
    dry_run: bool = Field(True, description="Preview without actually transferring")
    no_clobber: bool = Field(False, description="Skip objects that already exist at destination")
    exclude_patterns: Optional[List[str]] = Field(None, description="Patterns to exclude")

class CloudTransferResponse(BaseModel):
    """Response model for cloud transfer."""
    job_id: str
    status: str
    message: str
    command: str
    
class FolderStats(BaseModel):
    """Folder statistics model."""
    path: str
    file_count: int
    folder_count: int
    total_size_bytes: int
    total_size_gb: float
    earliest_created: Optional[str]
    latest_updated: Optional[str]

@router.post("/analyze-bucket")
async def analyze_bucket(request: CloudAnalysisRequest):
    """
    Analyze a GCS bucket and return statistics.
    This can be a long-running operation for large buckets.
    """
    try:
        def analyze_sync():
            """Synchronous analysis function to run in thread."""
            # Use lazy-loaded storage client
            client = get_storage_client()
            
            bucket = client.bucket(request.bucket_name)
            
            # Check if bucket exists
            if not bucket.exists():
                raise HTTPException(status_code=404, detail=f"Bucket '{request.bucket_name}' not found")
            
            folder_stats = {}
            
            # List all blobs with the given prefix
            blobs = bucket.list_blobs(prefix=request.prefix)
            
            total_blobs = 0
            for blob in blobs:
                total_blobs += 1
                
                # Extract folder path
                if blob.name.endswith('/'):
                    # It's a folder marker
                    folder_path = blob.name
                    if folder_path not in folder_stats:
                        folder_stats[folder_path] = {
                            'files': [],
                            'subfolders': set(),
                            'total_size': 0
                        }
                else:
                    # It's a file
                    parts = blob.name.split('/')
                    
                    # Track file in its immediate folder
                    if len(parts) > 1:
                        folder_path = '/'.join(parts[:-1]) + '/'
                    else:
                        folder_path = '/'
                    
                    if folder_path not in folder_stats:
                        folder_stats[folder_path] = {
                            'files': [],
                            'subfolders': set(),
                            'total_size': 0
                        }
                    
                    folder_stats[folder_path]['files'].append({
                        'name': blob.name,
                        'size': blob.size or 0,
                        'created': blob.time_created.isoformat() if blob.time_created else None,
                        'updated': blob.updated.isoformat() if blob.updated else None
                    })
                    folder_stats[folder_path]['total_size'] += blob.size or 0
                
                # Stop after reasonable amount for quick preview
                if total_blobs > 10000:
                    break
            
            # Calculate statistics
            results = []
            for path, stats in folder_stats.items():
                files = stats['files']
                results.append({
                    'path': path,
                    'file_count': len(files),
                    'folder_count': len(stats['subfolders']),
                    'total_size_bytes': stats['total_size'],
                    'total_size_gb': round(stats['total_size'] / (1024**3), 4),
                    'earliest_created': min((f['created'] for f in files if f['created']), default=None),
                    'latest_updated': max((f['updated'] for f in files if f['updated']), default=None)
                })
            
            # Sort by size descending
            results.sort(key=lambda x: x['total_size_bytes'], reverse=True)
            
            return {
                'bucket_name': request.bucket_name,
                'prefix': request.prefix,
                'total_folders_analyzed': len(results),
                'total_blobs_scanned': total_blobs,
                'folders': results[:50],  # Return top 50 folders
                'analysis_time': datetime.now(timezone.utc).isoformat()
            }
        
        # Run analysis in thread pool to avoid blocking
        result = await asyncio.to_thread(analyze_sync)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@router.get("/bucket-summary/{bucket_name}")
async def get_bucket_summary(bucket_name: str):
    """Get quick summary of a GCS bucket."""
    try:
        def get_summary():
            # Use lazy-loaded storage client
            client = get_storage_client()
            
            bucket = client.bucket(bucket_name)
            
            if not bucket.exists():
                raise HTTPException(status_code=404, detail=f"Bucket '{bucket_name}' not found")
            
            # Get bucket metadata
            bucket.reload()
            
            # Count objects (limited sample for speed)
            blobs = list(bucket.list_blobs(max_results=1000))
            sample_size = len(blobs)
            total_size = sum(blob.size for blob in blobs if blob.size)
            
            return {
                'bucket_name': bucket_name,
                'location': bucket.location,
                'storage_class': bucket.storage_class,
                'created': bucket.time_created.isoformat() if bucket.time_created else None,
                'sample_object_count': sample_size,
                'sample_total_size_gb': round(total_size / (1024**3), 2),
                'note': 'Limited to first 1000 objects for quick preview'
            }
        
        result = await asyncio.to_thread(get_summary)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bucket summary: {str(e)}")


def normalize_gcs_path(path: str) -> str:
    """Normalize a GCS path to gs:// format."""
    path = path.strip().rstrip('/')
    if path.startswith('gs://'):
        return path
    return f"gs://{path}"


def split_gcs_path(path: str) -> tuple[str, str]:
    """Split a normalized GCS path into bucket and object prefix."""
    normalized = normalize_gcs_path(path)[5:]
    bucket, _, prefix = normalized.partition('/')
    return bucket, prefix


def make_cloud_sync_name(job_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')
    return f"cloud-sync-{timestamp}-{job_id}"


def update_cloud_sync_job(job_id: str, status: str, output: str = None, error: str = None):
    """Persist cloud sync background status into the shared jobs table."""
    from .. import database

    if database.SessionLocal is None:
        return

    db = database.SessionLocal()
    try:
        job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
        if not job:
            return
        job.status = status
        if output is not None:
            job.upload_output = output
        if error is not None:
            job.error_message = error
        if status in ("completed", "failed", "cancelled"):
            job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def is_cloud_sync_job(job: UploadJob) -> bool:
    filters = job.filters or {}
    return filters.get("job_type") == "cloud_sync" or filters.get("transfer_direction") == "cloud_to_cloud"


def cloud_sync_job_to_transfer(job: UploadJob) -> dict:
    filters = job.filters or {}
    destination = f"gs://{job.destination_bucket}"
    if job.destination_path:
        destination += f"/{job.destination_path.strip('/')}"

    return {
        "job_id": job.job_id,
        "status": job.status,
        "source_path": job.source_path,
        "dest_path": destination,
        "dry_run": job.dry_run,
        "recursive": job.recursive,
        "no_clobber": job.no_clobber or False,
        "command": filters.get("display_command"),
        "output": job.upload_output or "",
        "created_at": job.to_dict().get("created_at"),
        "completed_at": job.to_dict().get("completed_at"),
        "error": job.error_message,
    }


def resolve_gcloud_executable() -> Optional[str]:
    """Resolve gcloud executable path from PATH on all platforms."""
    return shutil.which("gcloud") or shutil.which("gcloud.cmd")


def format_display_command(cmd: list) -> str:
    """Build a clean display command while preserving quoted paths/options."""
    display_cmd = cmd.copy()
    display_cmd[0] = "gcloud"

    parts = []
    for index, arg in enumerate(display_cmd):
        value = str(arg)
        if index >= len(display_cmd) - 2 or " " in value or "\\" in value:
            parts.append(f'"{value}"')
        else:
            parts.append(value)
    return " ".join(parts)


@router.post("/transfer", response_model=CloudTransferResponse)
async def start_cloud_transfer(
    request: CloudTransferRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Start a cloud-to-cloud transfer using gcloud storage rsync.
    """
    job_id = str(uuid.uuid4())[:8]
    
    source = normalize_gcs_path(request.source_path)
    dest = normalize_gcs_path(request.dest_path)

    gcloud_exe = resolve_gcloud_executable()
    if not gcloud_exe:
        raise HTTPException(
            status_code=503,
            detail=(
                "Cloud Sync requires the Google Cloud CLI ('gcloud') but it was not found on PATH. "
                "Install/repair Google Cloud SDK and verify with 'gcloud --version'. "
                "If JetStream was already running, restart it after PATH updates."
            )
        )
    
    # Build command
    cmd = [gcloud_exe, "storage", "rsync"]
    
    if request.recursive:
        cmd.append("--recursive")
    
    if request.dry_run:
        cmd.append("--dry-run")
    
    cmd.append("--checksums-only")

    if request.no_clobber:
        cmd.append("--no-clobber")

    # Combine exclude patterns into a single regex (gcloud accepts one --exclude flag)
    if request.exclude_patterns:
        patterns = [p.strip() for p in request.exclude_patterns if p.strip()]
        if patterns:
            combined = "|".join(f"({p})" for p in patterns)
            cmd.append(f"--exclude={combined}")

    cmd.extend([source, dest])
    
    # Keep the absolute executable path for process launch reliability, but
    # show a clean command in UI to match other pages.
    command_str = format_display_command(cmd)
    dest_bucket, dest_prefix = split_gcs_path(dest)

    job = UploadJob(
        job_id=job_id,
        friendly_name=make_cloud_sync_name(job_id),
        status="running",
        source_path=source,
        destination_bucket=dest_bucket,
        destination_path=dest_prefix,
        total_files=0,
        total_size_bytes=0,
        files_uploaded=0,
        bytes_uploaded=0,
        dry_run=request.dry_run,
        recursive=request.recursive,
        threads=1,
        split_by_folder=False,
        upload_tool="gcloud",
        started_at=datetime.now(timezone.utc),
        filters={
            "job_type": "cloud_sync",
            "transfer_direction": "cloud_to_cloud",
            "display_command": command_str,
            "exclude_patterns": request.exclude_patterns or []
        },
        no_clobber=request.no_clobber,
    )
    db.add(job)
    db.commit()
    
    # Initialize job status
    cloud_transfer_jobs[job_id] = {
        "status": "running",
        "source_path": source,
        "dest_path": dest,
        "dry_run": request.dry_run,
        "command": command_str,
        "output": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None
    }
    
    # Run transfer in background
    background_tasks.add_task(run_cloud_transfer, job_id, cmd)
    
    return CloudTransferResponse(
        job_id=job_id,
        status="running",
        message="Cloud sync started" + (" (dry run)" if request.dry_run else ""),
        command=command_str
    )


async def run_cloud_transfer(job_id: str, cmd: list):
    """Execute the cloud transfer command."""
    try:
        def run_sync():
            print(f"Cloud Transfer: {redact_sensitive_text(' '.join(cmd))}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout_lines = []
            stderr_lines = []

            def _read_stdout():
                for line in process.stdout:
                    stdout_lines.append(line)

            def _read_stderr():
                for line in process.stderr:
                    stderr_lines.append(line)
                    print(redact_sensitive_text(line.rstrip()))

            t1 = threading.Thread(target=_read_stdout, daemon=True)
            t2 = threading.Thread(target=_read_stderr, daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            process.wait()

            return process.returncode, "".join(stdout_lines), "".join(stderr_lines)

        returncode, stdout, stderr = await asyncio.to_thread(run_sync)

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout}\n\n"
        if stderr:
            output += f"STDERR:\n{stderr}"
        output = redact_sensitive_text(output)

        if returncode == 0:
            cloud_transfer_jobs[job_id]["status"] = "completed"
            cloud_transfer_jobs[job_id]["output"] = output
            update_cloud_sync_job(job_id, "completed", output=output)
        else:
            cloud_transfer_jobs[job_id]["status"] = "failed"
            cloud_transfer_jobs[job_id]["output"] = output
            cloud_transfer_jobs[job_id]["error"] = redact_sensitive_text(stderr.strip() or "Unknown error")
            update_cloud_sync_job(
                job_id,
                "failed",
                output=output,
                error=cloud_transfer_jobs[job_id]["error"]
            )

        cloud_transfer_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    except FileNotFoundError:
        error = (
            "Cloud Sync failed: Google Cloud CLI ('gcloud') executable was not found. "
            "Install/repair Google Cloud SDK, ensure gcloud is on PATH, then restart JetStream."
        )
        cloud_transfer_jobs[job_id]["status"] = "failed"
        cloud_transfer_jobs[job_id]["error"] = error
        cloud_transfer_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        update_cloud_sync_job(job_id, "failed", error=error)
    except Exception as e:
        error = redact_sensitive_text(str(e))
        cloud_transfer_jobs[job_id]["status"] = "failed"
        cloud_transfer_jobs[job_id]["error"] = error
        cloud_transfer_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        update_cloud_sync_job(job_id, "failed", error=error)


@router.get("/transfer/{job_id}")
async def get_transfer_status(job_id: str, db: Session = Depends(get_db)):
    """Get status of a cloud transfer job."""
    if job_id in cloud_transfer_jobs:
        job = cloud_transfer_jobs[job_id].copy()
        job["job_id"] = job_id
        return job

    persisted_job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
    if persisted_job and is_cloud_sync_job(persisted_job):
        return cloud_sync_job_to_transfer(persisted_job)

    raise HTTPException(status_code=404, detail="Transfer job not found")


@router.get("/transfers")
async def list_transfers(db: Session = Depends(get_db)):
    """List recent cloud transfer jobs."""
    persisted_jobs = db.query(UploadJob).order_by(UploadJob.created_at.desc()).all()
    jobs = []
    seen_job_ids = set()

    for persisted_job in persisted_jobs:
        if persisted_job.cleared or not is_cloud_sync_job(persisted_job):
            continue
        transfer = cloud_sync_job_to_transfer(persisted_job)
        if persisted_job.job_id in cloud_transfer_jobs:
            transfer.update(cloud_transfer_jobs[persisted_job.job_id])
            transfer["job_id"] = persisted_job.job_id
        jobs.append(transfer)
        seen_job_ids.add(persisted_job.job_id)

    for job_id, job_data in cloud_transfer_jobs.items():
        if job_id in seen_job_ids:
            continue
        job = job_data.copy()
        job["job_id"] = job_id
        jobs.append(job)

    return jobs


@router.post("/transfers/clear-completed")
async def clear_completed_transfers(db: Session = Depends(get_db)):
    """Clear completed cloud transfer jobs from the recent transfers list."""
    cleared = 0
    jobs = db.query(UploadJob).filter(
        UploadJob.status.in_(["completed", "failed", "cancelled"]),
        (UploadJob.cleared == False) | (UploadJob.cleared == None)
    ).all()

    for job in jobs:
        if not is_cloud_sync_job(job):
            continue
        job.cleared = True
        cleared += 1
        cloud_transfer_jobs.pop(job.job_id, None)

    for job_id, job_data in list(cloud_transfer_jobs.items()):
        if job_data.get("status") in ("completed", "failed", "cancelled"):
            cloud_transfer_jobs.pop(job_id, None)
            cleared += 1

    db.commit()
    return {"message": f"Cleared {cleared} transfer(s) from recent list"}
