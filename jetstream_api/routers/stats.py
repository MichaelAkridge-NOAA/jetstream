"""Statistics and analytics endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta

from ..database import get_db, UploadJob
from ..models import StatsResponse

router = APIRouter()

@router.get("/", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db)):
    """Get overall system statistics."""
    
    # Total jobs
    total_jobs = db.query(func.count(UploadJob.id)).scalar()
    
    # Jobs by status
    status_counts = db.query(
        UploadJob.status, func.count(UploadJob.id)
    ).group_by(UploadJob.status).all()
    
    jobs_by_status = {status: count for status, count in status_counts}
    
    # Total uploaded data
    total_uploaded = db.query(
        func.sum(UploadJob.bytes_uploaded)
    ).filter(UploadJob.status == "completed").scalar() or 0
    
    # Total files uploaded
    total_files = db.query(
        func.sum(UploadJob.files_uploaded)
    ).filter(UploadJob.status == "completed").scalar() or 0
    
    # Active jobs
    active_jobs = db.query(func.count(UploadJob.id)).filter(
        UploadJob.status.in_(["running", "pending", "queued"])
    ).scalar()
    
    # Queue length
    queue_length = db.query(func.count(UploadJob.id)).filter(
        UploadJob.status == "queued"
    ).scalar()
    
    return StatsResponse(
        total_jobs=total_jobs,
        jobs_by_status=jobs_by_status,
        total_uploaded_bytes=total_uploaded,
        total_uploaded_gb=round(total_uploaded / (1024**3), 2),
        total_files_uploaded=total_files,
        active_jobs=active_jobs,
        queue_length=queue_length
    )

@router.get("/recent")
async def get_recent_activity(limit: int = 10, db: Session = Depends(get_db)):
    """Get recent upload activity."""
    recent_jobs = db.query(UploadJob).order_by(
        UploadJob.created_at.desc()
    ).limit(limit).all()
    
    return {
        "recent_jobs": [job.to_dict() for job in recent_jobs]
    }

@router.get("/summary")
async def get_summary(db: Session = Depends(get_db)):
    """Get summary statistics for dashboard."""
    # Get completed jobs in last 24 hours
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    
    recent_completed = db.query(func.count(UploadJob.id)).filter(
        UploadJob.status == "completed",
        UploadJob.completed_at >= yesterday
    ).scalar()
    
    recent_failed = db.query(func.count(UploadJob.id)).filter(
        UploadJob.status == "failed",
        UploadJob.completed_at >= yesterday
    ).scalar()
    
    # Average upload size
    avg_size = db.query(func.avg(UploadJob.total_size_bytes)).filter(
        UploadJob.status == "completed"
    ).scalar() or 0
    
    return {
        "recent_completed": recent_completed,
        "recent_failed": recent_failed,
        "average_upload_size_gb": round(avg_size / (1024**3), 2),
        "success_rate": round(
            (recent_completed / (recent_completed + recent_failed) * 100) 
            if (recent_completed + recent_failed) > 0 else 0, 
            2
        )
    }
