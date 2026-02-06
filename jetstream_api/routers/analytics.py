"""Analytics endpoints for upload statistics and cloud storage analysis."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from typing import Dict, List
from datetime import datetime, timezone, timedelta

from ..database import get_db, UploadJob
from ..models import CloudAnalysisRequest

router = APIRouter()

@router.get("/upload-trends")
async def get_upload_trends(days: int = 30, db: Session = Depends(get_db)):
    """Get upload job trends over time."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Group by date
    jobs = db.query(
        func.date(UploadJob.created_at).label('date'),
        func.count(UploadJob.id).label('total_jobs'),
        func.sum(UploadJob.total_size_bytes).label('total_bytes'),
        func.sum(case((UploadJob.status == 'completed', 1), else_=0)).label('completed'),
        func.sum(case((UploadJob.status == 'failed', 1), else_=0)).label('failed')
    ).filter(
        UploadJob.created_at >= cutoff_date
    ).group_by(
        func.date(UploadJob.created_at)
    ).order_by(
        func.date(UploadJob.created_at)
    ).all()
    
    return {
        "trends": [
            {
                "date": str(job.date),
                "total_jobs": job.total_jobs,
                "total_gb": round(job.total_bytes / (1024**3), 2) if job.total_bytes else 0,
                "completed": job.completed,
                "failed": job.failed
            }
            for job in jobs
        ]
    }

@router.get("/success-rate")
async def get_success_rate(db: Session = Depends(get_db)):
    """Get job success rate statistics."""
    status_counts = db.query(
        UploadJob.status,
        func.count(UploadJob.id).label('count')
    ).group_by(UploadJob.status).all()
    
    total = sum(s.count for s in status_counts)
    
    return {
        "total_jobs": total,
        "by_status": [
            {
                "status": s.status,
                "count": s.count,
                "percentage": round((s.count / total * 100) if total > 0 else 0, 1)
            }
            for s in status_counts
        ]
    }

@router.get("/performance-metrics")
async def get_performance_metrics(db: Session = Depends(get_db)):
    """Get performance metrics for uploads."""
    completed_jobs = db.query(UploadJob).filter(
        UploadJob.status == 'completed',
        UploadJob.started_at.isnot(None),
        UploadJob.completed_at.isnot(None)
    ).all()
    
    if not completed_jobs:
        return {
            "avg_duration_seconds": 0,
            "avg_speed_mbps": 0,
            "total_data_transferred_gb": 0,
            "fastest_upload_mbps": 0,
            "slowest_upload_mbps": 0
        }
    
    durations = []
    speeds = []
    total_bytes = 0
    
    for job in completed_jobs:
        duration = (job.completed_at - job.started_at).total_seconds()
        if duration > 0:
            durations.append(duration)
            # Calculate speed in Mbps
            speed_mbps = (job.bytes_uploaded * 8) / (duration * 1_000_000)
            speeds.append(speed_mbps)
        total_bytes += job.bytes_uploaded
    
    return {
        "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else 0,
        "avg_speed_mbps": round(sum(speeds) / len(speeds), 2) if speeds else 0,
        "total_data_transferred_gb": round(total_bytes / (1024**3), 2),
        "fastest_upload_mbps": round(max(speeds), 2) if speeds else 0,
        "slowest_upload_mbps": round(min(speeds), 2) if speeds else 0,
        "completed_jobs": len(completed_jobs)
    }

@router.get("/top-sources")
async def get_top_sources(limit: int = 10, db: Session = Depends(get_db)):
    """Get most frequently used source paths."""
    sources = db.query(
        UploadJob.source_path,
        func.count(UploadJob.id).label('count'),
        func.sum(UploadJob.total_size_bytes).label('total_bytes')
    ).group_by(
        UploadJob.source_path
    ).order_by(
        func.count(UploadJob.id).desc()
    ).limit(limit).all()
    
    return {
        "sources": [
            {
                "path": s.source_path,
                "job_count": s.count,
                "total_gb": round(s.total_bytes / (1024**3), 2) if s.total_bytes else 0
            }
            for s in sources
        ]
    }

@router.get("/top-destinations")
async def get_top_destinations(limit: int = 10, db: Session = Depends(get_db)):
    """Get most frequently used destination buckets."""
    destinations = db.query(
        UploadJob.destination_bucket,
        func.count(UploadJob.id).label('count'),
        func.sum(UploadJob.total_size_bytes).label('total_bytes')
    ).group_by(
        UploadJob.destination_bucket
    ).order_by(
        func.count(UploadJob.id).desc()
    ).limit(limit).all()
    
    return {
        "destinations": [
            {
                "bucket": d.destination_bucket,
                "job_count": d.count,
                "total_gb": round(d.total_bytes / (1024**3), 2) if d.total_bytes else 0
            }
            for d in destinations
        ]
    }

@router.get("/job-type-breakdown")
async def get_job_type_breakdown(db: Session = Depends(get_db)):
    """Get breakdown of job types (dry-run, split, recursive)."""
    total = db.query(func.count(UploadJob.id)).scalar()
    
    dry_run = db.query(func.count(UploadJob.id)).filter(UploadJob.dry_run == True).scalar()
    split = db.query(func.count(UploadJob.id)).filter(UploadJob.split_by_folder == True).scalar()
    recursive = db.query(func.count(UploadJob.id)).filter(UploadJob.recursive == True).scalar()
    scheduled = db.query(func.count(UploadJob.id)).filter(UploadJob.scheduled_for.isnot(None)).scalar()
    
    return {
        "total_jobs": total,
        "dry_run_jobs": dry_run,
        "dry_run_percentage": round((dry_run / total * 100) if total > 0 else 0, 1),
        "split_jobs": split,
        "split_percentage": round((split / total * 100) if total > 0 else 0, 1),
        "recursive_jobs": recursive,
        "recursive_percentage": round((recursive / total * 100) if total > 0 else 0, 1),
        "scheduled_jobs": scheduled,
        "scheduled_percentage": round((scheduled / total * 100) if total > 0 else 0, 1)
    }
