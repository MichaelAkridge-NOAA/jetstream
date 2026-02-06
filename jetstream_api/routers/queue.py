"""Queue management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db, UploadJob
from ..services import queue_manager

router = APIRouter()

@router.get("/status")
async def get_queue_status():
    """Get current queue status."""
    return queue_manager.get_queue_status()

@router.get("/running")
async def get_running_jobs(db: Session = Depends(get_db)):
    """Get all currently running jobs."""
    running = db.query(UploadJob).filter(
        UploadJob.status == "running"
    ).all()
    
    return {
        "running_jobs": [job.to_dict() for job in running],
        "count": len(running)
    }

@router.get("/queued")
async def get_queued_jobs(db: Session = Depends(get_db)):
    """Get all queued jobs."""
    queued = db.query(UploadJob).filter(
        UploadJob.status == "queued"
    ).order_by(UploadJob.created_at).all()
    
    return {
        "queued_jobs": [job.to_dict() for job in queued],
        "count": len(queued)
    }

@router.post("/pause")
async def pause_queue():
    """Pause queue processing (stop accepting new jobs)."""
    # TODO: Implement queue pause logic
    return {"message": "Queue paused", "status": "paused"}

@router.post("/resume")
async def resume_queue():
    """Resume queue processing."""
    # TODO: Implement queue resume logic
    return {"message": "Queue resumed", "status": "active"}

@router.get("/history")
async def get_queue_history(limit: int = 50, db: Session = Depends(get_db)):
    """Get queue processing history."""
    completed = db.query(UploadJob).filter(
        UploadJob.status.in_(["completed", "failed", "cancelled"])
    ).order_by(UploadJob.completed_at.desc()).limit(limit).all()
    
    return {
        "history": [job.to_dict() for job in completed],
        "count": len(completed)
    }
