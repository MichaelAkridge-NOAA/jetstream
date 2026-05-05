"""Background scheduler for processing scheduled upload jobs."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .database import SessionLocal, UploadJob
import logging

logger = logging.getLogger(__name__)

class UploadScheduler:
    """Manages scheduled upload jobs."""
    
    def __init__(self):
        self.running = False
        self.task = None
        
    async def start(self):
        """Start the scheduler background task."""
        if self.running:
            logger.warning("Scheduler already running")
            return
            
        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info("[OK] Upload scheduler started")
        
    async def stop(self):
        """Stop the scheduler background task."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("[OK] Upload scheduler stopped")
        
    async def _scheduler_loop(self):
        """Main scheduler loop - checks for scheduled jobs every minute."""
        # Import here to avoid circular imports
        from .services import upload_service, queue_manager
        from . import database
        
        # Wait a bit for everything to initialize
        await asyncio.sleep(2)
        
        while self.running:
            try:
                # Check if database is ready
                if database.SessionLocal is None:
                    logger.warning("Database not ready, skipping check")
                    await asyncio.sleep(5)
                    continue
                    
                await self._check_scheduled_jobs(upload_service, queue_manager)
                # Sleep for 30 seconds before next check
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Scheduler error: {str(e)}", exc_info=True)
                await asyncio.sleep(30)
                
    async def _check_scheduled_jobs(self, upload_service, queue_manager):
        """Check for jobs scheduled to run now and trigger them."""
        from . import database
        
        if database.SessionLocal is None:
            logger.warning("SessionLocal not initialized, skipping scheduled job check")
            return
            
        db: Session = database.SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            
            # Find jobs scheduled for now or earlier that are still in 'scheduled' status
            scheduled_jobs = db.query(UploadJob).filter(
                UploadJob.status == "scheduled",
                UploadJob.scheduled_for <= now
            ).all()
            
            if scheduled_jobs:
                logger.info(f"Found {len(scheduled_jobs)} scheduled jobs ready to run")
            
            for job in scheduled_jobs:
                try:
                    # Move to queued status - they'll be picked up by the queue processor
                    job.status = "queued"
                    queue_manager.add_to_queue(job.job_id)
                    db.commit()
                    logger.info(f"Scheduled job {job.job_id} moved to queue")
                    
                except Exception as e:
                    logger.error(f"Error queuing job {job.job_id}: {str(e)}")
                    job.status = "failed"
                    job.error_message = f"Failed to queue scheduled upload: {str(e)}"
                    db.commit()
            
            # Now process queued jobs one at a time (respecting max concurrent)
            await self._process_queued_jobs(upload_service, queue_manager)
                    
        finally:
            db.close()
    
    async def _process_queued_jobs(self, upload_service, queue_manager):
        """Process queued jobs, respecting the max concurrent limit."""
        from . import database
        
        if database.SessionLocal is None:
            return
        
        db: Session = database.SessionLocal()
        try:
            # Keep starting jobs while we can
            while queue_manager.can_start_job():
                next_job_id = queue_manager.get_next_job()
                if not next_job_id:
                    # Check database for any queued jobs not in memory queue
                    queued_job = db.query(UploadJob).filter(
                        UploadJob.status == "queued"
                    ).first()
                    if queued_job:
                        next_job_id = queued_job.job_id
                    else:
                        break
                
                # Start this job
                logger.info(f"Starting queued job: {next_job_id}")
                asyncio.create_task(self._run_scheduled_upload(next_job_id, upload_service, queue_manager))
                
                # Small delay to let the job register as running
                await asyncio.sleep(0.5)
        finally:
            db.close()
            
    async def _run_scheduled_upload(self, job_id: str, upload_service, queue_manager):
        """Run a scheduled upload job."""
        from . import database
        from .services import make_progress_callback
        from datetime import timedelta

        if database.SessionLocal is None:
            logger.error(f"SessionLocal not initialized, cannot run job {job_id}")
            return

        db: Session = database.SessionLocal()
        try:
            job = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not job:
                logger.error(f"Job {job_id} not found")
                return

            # Fix #11: job may have been cancelled before scheduler picked it up
            if job.status == "cancelled":
                return

            # Update status to running
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
                exclude_folders=job.filters.get('exclude_folders') if job.filters else None,
                no_clobber=getattr(job, 'no_clobber', False) or False,
                custom_command=getattr(job, 'custom_command', None),
                progress_callback=make_progress_callback(job_id, db),
            )

            # Update job status
            if success:
                job.status = "completed"
                job.files_uploaded = job.total_files
                job.bytes_uploaded = job.total_size_bytes
            else:
                # Auto-retry logic (Issue #14)
                retry_count = getattr(job, 'retry_count', 0) or 0
                max_retries = getattr(job, 'max_auto_retries', 3) or 3
                if getattr(job, 'auto_retry', False) and retry_count < max_retries:
                    delay = getattr(job, 'auto_retry_delay_minutes', 30) or 30
                    job.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay)
                    job.retry_count = retry_count + 1
                    job.status = "scheduled"
                    job.scheduled_for = job.next_retry_at
                    job.error_message = (
                        f"Auto-retry {retry_count + 1}/{max_retries} "
                        f"scheduled for {job.next_retry_at.strftime('%H:%M UTC')}"
                    )
                else:
                    job.status = "failed"
                    job.error_message = "Upload failed - check logs"
            
            # Save upload output to database
            job.upload_output = output
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            
            logger.info(f"Scheduled job {job_id} completed with status: {job.status}")
            
        except Exception as e:
            logger.error(f"Error running scheduled job {job_id}: {str(e)}")
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            queue_manager.complete_job(job_id)
            db.close()
            
            # Trigger processing of next queued job
            asyncio.create_task(self._process_queued_jobs(upload_service, queue_manager))


# Global scheduler instance
scheduler = UploadScheduler()
