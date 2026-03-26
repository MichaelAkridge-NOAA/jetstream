"""Upload endpoints for creating and managing upload jobs."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid
from datetime import datetime, timezone
import os

from ..database import get_db, UploadJob
from ..models import (
    UploadRequest, UploadResponse, JobStatusResponse, JobStatus
)
from ..services import (
    FileFilter, FolderAnalyzer, upload_service, queue_manager, generate_friendly_job_name
)

router = APIRouter()

async def process_upload_job(job_id: str, db_path: str):
    """Background task to process upload job."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from ..config import settings
    
    # Create new session for background task
    engine = create_engine(settings.DATABASE_URL, 
                          connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {})
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
        if not job:
            return
        
        # Check if can start (queue management)
        if not queue_manager.can_start_job():
            job.status = "queued"
            queue_manager.add_to_queue(job_id)
            db.commit()
            return
        
        # Start job
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        queue_manager.start_job(job_id)
        db.commit()
        
        # Perform upload
        success, output = await upload_service.upload_to_gcs(
            job_id=job_id,
            source_path=job.source_path,
            destination_bucket=job.destination_bucket,
            destination_path=job.destination_path or "",
            dry_run=job.dry_run,
            recursive=job.recursive,
            threads=job.threads,
            log_path=job.log_path,
            upload_tool=getattr(job, 'upload_tool', None) or "gcloud",
            exclude_patterns=job.filters.get('exclude_patterns') if job.filters else None,
            exclude_folders=job.filters.get('exclude_folders') if job.filters else None
        )
        
        # Update job status
        if success:
            job.status = "completed"
            job.files_uploaded = job.total_files
            job.bytes_uploaded = job.total_size_bytes
        else:
            job.status = "failed"
            job.error_message = "Upload failed - check logs"
        
        # Save upload output to database
        job.upload_output = output
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        
        # Complete job in queue
        queue_manager.complete_job(job_id)
        
        # Check if there's a next job to process
        next_job_id = queue_manager.get_next_job()
        if next_job_id:
            # Trigger next job
            import asyncio
            asyncio.create_task(process_upload_job(next_job_id, db_path))
        
    except Exception as e:
        print(f"Error processing job {job_id}: {str(e)}")
        if job:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        queue_manager.complete_job(job_id)
    finally:
        db.close()

@router.post("/", response_model=UploadResponse)
async def create_upload(
    request: UploadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Create a new upload job.
    
    If split_by_folder is True, creates separate jobs for each immediate subfolder.
    """
    # Analyze folder first (note: include_patterns not used since rsync doesn't support it)
    file_filter = FileFilter(
        include_patterns=None,  # Not using include patterns for analysis since rsync won't filter by them
        exclude_patterns=request.exclude_patterns,
        exclude_folders=request.exclude_folders
    )
    analyzer = FolderAnalyzer(file_filter)
    
    try:
        stats = analyzer.analyze(request.source_path, recursive=request.recursive)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    created_jobs = []
    
    # Check if we should split by folder
    if request.split_by_folder and stats['subfolder_count'] > 0:
        # Create separate job for each subfolder
        subfolders = analyzer.analyze_subfolders(request.source_path)
        
        for subfolder in subfolders:
            job_id = str(uuid.uuid4())
            friendly_name = generate_friendly_job_name(subfolder['path'])
            
            # Construct subfolder destination path
            subfolder_dest_path = request.destination_path or ""
            if subfolder_dest_path:
                subfolder_dest_path = f"{subfolder_dest_path}/{subfolder['name']}"
            else:
                subfolder_dest_path = subfolder['name']
            
            # Create log path using friendly name
            log_dir = os.path.join(os.getcwd(), "logs")
            log_path = os.path.join(log_dir, f"{friendly_name}.log")
            
            # Create job in database
            job = UploadJob(
                job_id=job_id,
                friendly_name=friendly_name,
                status="pending",
                source_path=subfolder['path'],
                destination_bucket=request.destination_bucket,
                destination_path=subfolder_dest_path,
                total_files=subfolder['total_files'],
                total_size_bytes=subfolder['total_size_bytes'],
                dry_run=request.dry_run,
                recursive=request.recursive,
                threads=request.threads,
                split_by_folder=False,
                upload_tool=request.upload_tool,
                scheduled_for=request.scheduled_for,
                log_path=log_path,
                filters={
                    'exclude_patterns': request.exclude_patterns,
                    'exclude_folders': request.exclude_folders
                }
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            
            # Check if job is scheduled for later
            if request.scheduled_for and request.scheduled_for > datetime.now(timezone.utc):
                # Set status to scheduled - will be picked up by scheduler
                job.status = "scheduled"
                db.commit()
            else:
                # Add to background tasks for immediate processing
                background_tasks.add_task(process_upload_job, job_id, "")
            
            created_jobs.append(job)
        
        # Determine response status and message
        if request.scheduled_for and request.scheduled_for > datetime.now(timezone.utc):
            status = JobStatus.SCHEDULED
            message = f"Created {len(created_jobs)} upload jobs (one per subfolder), scheduled for {request.scheduled_for.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        else:
            status = JobStatus.PENDING
            message = f"Created {len(created_jobs)} upload jobs (one per subfolder)"
        
        return UploadResponse(
            job_id=f"split_{len(created_jobs)}_jobs",
            status=status,
            message=message,
            source_path=request.source_path,
            destination=f"gs://{request.destination_bucket}/{request.destination_path or ''}"
        )
    
    else:
        # Create single job
        job_id = str(uuid.uuid4())
        friendly_name = generate_friendly_job_name(request.source_path)
        
        # Create log path using friendly name
        log_dir = os.path.join(os.getcwd(), "logs")
        log_path = os.path.join(log_dir, f"{friendly_name}.log")
        
        # Create job in database
        job = UploadJob(
            job_id=job_id,
            friendly_name=friendly_name,
            status="pending",
            source_path=request.source_path,
            destination_bucket=request.destination_bucket,
            destination_path=request.destination_path or "",
            total_files=stats['total_files'],
            total_size_bytes=stats['total_size_bytes'],
            dry_run=request.dry_run,
            recursive=request.recursive,
            threads=request.threads,
            split_by_folder=request.split_by_folder,
            upload_tool=request.upload_tool,
            scheduled_for=request.scheduled_for,
            log_path=log_path,
            filters={
                'exclude_patterns': request.exclude_patterns,
                'exclude_folders': request.exclude_folders
            }
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        # Check if job is scheduled for later
        if request.scheduled_for and request.scheduled_for > datetime.now(timezone.utc):
            # Set status to scheduled - will be picked up by scheduler
            job.status = "scheduled"
            db.commit()
            
            return UploadResponse(
                job_id=job_id,
                status=JobStatus.SCHEDULED,
                message=f"Upload scheduled for {request.scheduled_for.strftime('%Y-%m-%d %H:%M:%S')} UTC",
                source_path=request.source_path,
                destination=f"gs://{request.destination_bucket}/{request.destination_path or ''}"
            )
        
        # Add to background tasks for immediate processing
        background_tasks.add_task(process_upload_job, job_id, "")
        
        return UploadResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message="Upload job created successfully",
            source_path=request.source_path,
            destination=f"gs://{request.destination_bucket}/{request.destination_path or ''}"
        )

@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_upload_status(job_id: str, db: Session = Depends(get_db)):
    """Get status of a specific upload job."""
    job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(**job.to_dict())

@router.get("/", response_model=List[JobStatusResponse])
async def list_uploads(
    status: str = None,
    limit: int = 50,
    include_cleared: bool = False,
    db: Session = Depends(get_db)
):
    """List all upload jobs, optionally filtered by status."""
    query = db.query(UploadJob)
    
    if status:
        query = query.filter(UploadJob.status == status)
    
    # Exclude cleared jobs by default
    if not include_cleared:
        query = query.filter((UploadJob.cleared == False) | (UploadJob.cleared == None))
    
    jobs = query.order_by(UploadJob.created_at.desc()).limit(limit).all()
    
    return [JobStatusResponse(**job.to_dict()) for job in jobs]

@router.post("/clear-completed")
async def clear_completed_jobs(db: Session = Depends(get_db)):
    """Clear all completed jobs from the recent list (mark as hidden)."""
    result = db.query(UploadJob).filter(
        UploadJob.status.in_(["completed", "failed", "cancelled"]),
        (UploadJob.cleared == False) | (UploadJob.cleared == None)
    ).update({"cleared": True}, synchronize_session=False)
    db.commit()
    return {"message": f"Cleared {result} job(s) from recent list"}

@router.delete("/{job_id}")
async def delete_upload(job_id: str, db: Session = Depends(get_db)):
    """Delete an upload job from the database."""
    job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # If job is running or queued, cancel it first
    if job.status in ["running", "queued", "pending"]:
        if job.status == "running":
            upload_service.cancel_upload(job_id)
        queue_manager.complete_job(job_id)
    
    # Delete the job from database
    db.delete(job)
    db.commit()
    
    return {"message": "Job deleted successfully", "job_id": job_id}

@router.post("/{job_id}/cancel")
async def cancel_upload(job_id: str, db: Session = Depends(get_db)):
    """Cancel a running, queued, or scheduled upload job."""
    job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in ["running", "queued", "pending", "scheduled"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status: {job.status}")
    
    # Cancel the upload if running
    if job.status == "running":
        upload_service.cancel_upload(job_id)
    
    # Update status
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    
    # Remove from queue
    queue_manager.complete_job(job_id)
    
    return {"message": "Job cancelled successfully", "job_id": job_id}

@router.post("/{job_id}/retry")
async def retry_upload(
    job_id: str,
    background_tasks: BackgroundTasks,
    remove_dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """Retry a failed, cancelled, or completed upload job. Optionally remove dry_run flag."""
    job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in ["failed", "cancelled", "completed"]:
        raise HTTPException(status_code=400, detail=f"Cannot retry job with status: {job.status}")
    
    # Reset job
    job.status = "pending"
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.files_uploaded = 0
    job.bytes_uploaded = 0
    job.upload_output = None
    
    # Remove dry_run flag if requested (converts dry-run preview to actual upload)
    if remove_dry_run:
        job.dry_run = False
    
    db.commit()
    
    # Add to background tasks
    background_tasks.add_task(process_upload_job, job_id, "")
    
    message = "Job queued for actual upload" if remove_dry_run else "Job queued for retry"
    return {"message": message, "job_id": job_id}
