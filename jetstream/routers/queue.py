"""Queue management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import asyncio

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
    """Pause queue — no new jobs will start until resumed."""
    queue_manager.pause()
    return {"message": "Queue paused", "status": "paused", "paused": True}

@router.post("/resume")
async def resume_queue():
    """Resume queue processing and trigger the next waiting job if any."""
    queue_manager.resume()
    # Kick off the next queued job if one is waiting
    next_job_id = queue_manager.get_next_job()
    if next_job_id:
        from ..routers.uploads import process_upload_job
        asyncio.create_task(process_upload_job(next_job_id, ""))
    return {"message": "Queue resumed", "status": "active", "paused": False}

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
