"""Database models and initialization."""

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from .config import settings

Base = declarative_base()
engine = None
SessionLocal = None

class UploadJob(Base):
    """Model for upload jobs."""
    __tablename__ = "upload_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    friendly_name = Column(String, nullable=True)  # User-friendly job name
    status = Column(String, default="pending")  # pending, queued, running, completed, failed, cancelled
    source_path = Column(String, nullable=False)
    destination_bucket = Column(String, nullable=False)
    destination_path = Column(String)
    
    # Job details
    total_files = Column(Integer, default=0)
    total_size_bytes = Column(Float, default=0.0)
    files_uploaded = Column(Integer, default=0)
    bytes_uploaded = Column(Float, default=0.0)
    
    # Timing
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    scheduled_for = Column(DateTime, nullable=True)  # When to start the upload
    
    # Configuration
    dry_run = Column(Boolean, default=False)
    recursive = Column(Boolean, default=True)
    threads = Column(Integer, default=4)
    split_by_folder = Column(Boolean, default=False)
    upload_tool = Column(String, default="gcloud")  # "gcloud" or "gsutil"
    cleared = Column(Boolean, default=False)  # Hidden from recent jobs list
    
    # Metadata
    error_message = Column(Text, nullable=True)
    log_path = Column(String, nullable=True)
    upload_output = Column(Text, nullable=True)  # Store stdout/stderr from upload command
    filters = Column(JSON, nullable=True)  # Store include/exclude patterns

    # Data protection & rsync options (Issue #13)
    no_clobber = Column(Boolean, default=False)
    custom_command = Column(Text, nullable=True)  # Legacy column; cleared at startup for security.

    # Auto-retry configuration (Issue #14)
    auto_retry = Column(Boolean, default=False)
    auto_retry_delay_minutes = Column(Integer, default=30)
    retry_count = Column(Integer, default=0)
    max_auto_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime, nullable=True)
    
    def to_dict(self):
        """Convert to dictionary."""
        filters = self.filters or {}

        def calculate_progress_percent():
            if self.status == "completed":
                return 100.0

            total_size = self.total_size_bytes or 0
            if total_size <= 0:
                return 0.0

            return round(((self.bytes_uploaded or 0) / total_size) * 100, 2)

        # Helper to format datetime as UTC ISO string
        def format_dt(dt):
            if not dt:
                return None
            # Ensure timezone aware and convert to UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            # Return ISO format with 'Z' suffix for UTC
            return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        return {
            "id": self.id,
            "job_id": self.job_id,
            "friendly_name": self.friendly_name,
            "status": self.status,
            "source_path": self.source_path,
            "destination_bucket": self.destination_bucket,
            "destination_path": self.destination_path,
            "total_files": self.total_files,
            "total_size_bytes": self.total_size_bytes,
            "files_uploaded": self.files_uploaded,
            "bytes_uploaded": self.bytes_uploaded,
            "progress_percent": calculate_progress_percent(),
            "created_at": format_dt(self.created_at),
            "started_at": format_dt(self.started_at),
            "completed_at": format_dt(self.completed_at),
            "scheduled_for": format_dt(self.scheduled_for),
            "duration_seconds": self._calculate_duration(),
            "transfer_speed": self._calculate_speed(),
            "dry_run": self.dry_run,
            "recursive": self.recursive,
            "threads": self.threads,
            "split_by_folder": self.split_by_folder,
            "upload_tool": self.upload_tool or "gcloud",
            "error_message": self.error_message,
            "log_path": self.log_path,
            "upload_output": self.upload_output,
            "filters": self.filters,
            "job_type": filters.get("job_type", "upload"),
            "transfer_direction": filters.get("transfer_direction", "local_to_cloud"),
            "no_clobber": self.no_clobber or False,
            "auto_retry": self.auto_retry or False,
            "auto_retry_delay_minutes": self.auto_retry_delay_minutes or 30,
            "retry_count": self.retry_count or 0,
            "max_auto_retries": self.max_auto_retries or 3,
            "next_retry_at": format_dt(self.next_retry_at),
        }
    
    def _calculate_duration(self):
        """Calculate job duration in seconds."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now(timezone.utc)
        if self.started_at.tzinfo is None:
            start = self.started_at.replace(tzinfo=timezone.utc)
        else:
            start = self.started_at
        if end_time.tzinfo is None:
            end = end_time.replace(tzinfo=timezone.utc)
        else:
            end = end_time
        return (end - start).total_seconds()
    
    def _calculate_speed(self):
        """Calculate transfer speed in bytes/second."""
        duration = self._calculate_duration()
        if not duration or duration <= 0:
            return None
        if self.status == "completed" and self.total_size_bytes > 0:
            return self.total_size_bytes / duration
        return None

class FolderStats(Base):
    """Model for folder statistics."""
    __tablename__ = "folder_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, index=True)
    total_files = Column(Integer)
    total_size_bytes = Column(Float)
    file_types = Column(JSON)  # Dictionary of file extension counts
    subfolder_count = Column(Integer)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "path": self.path,
            "total_files": self.total_files,
            "total_size_bytes": self.total_size_bytes,
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 2),
            "total_size_gb": round(self.total_size_bytes / (1024 * 1024 * 1024), 2),
            "file_types": self.file_types,
            "subfolder_count": self.subfolder_count,
            "scanned_at": self.scanned_at.isoformat() if self.scanned_at else None
        }


class CloudAuditRun(Base):
    """Model for cloud bucket audit runs."""
    __tablename__ = "cloud_audit_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    status = Column(String, default="running")  # running, completed, failed
    bucket_name = Column(String, nullable=False, index=True)
    prefix = Column(String, default="")

    # Scan options
    dry_run = Column(Boolean, default=True)
    scan_limit = Column(Integer, default=0)
    reached_scan_limit = Column(Boolean, default=False)
    regex_patterns = Column(JSON, nullable=True)
    quarantine_bucket = Column(String, nullable=True)

    # Metrics
    scanned_objects = Column(Integer, default=0)
    scanned_bytes = Column(Float, default=0.0)
    junk_objects = Column(Integer, default=0)
    junk_bytes = Column(Float, default=0.0)
    quarantined_objects = Column(Integer, default=0)
    quarantined_bytes = Column(Float, default=0.0)

    # Timing and errors
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        """Convert to dictionary."""
        def format_dt(dt):
            if not dt:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        return {
            "id": self.id,
            "run_id": self.run_id,
            "status": self.status,
            "bucket_name": self.bucket_name,
            "prefix": self.prefix,
            "dry_run": self.dry_run,
            "scan_limit": self.scan_limit,
            "reached_scan_limit": self.reached_scan_limit,
            "regex_patterns": self.regex_patterns or [],
            "quarantine_bucket": self.quarantine_bucket,
            "scanned_objects": self.scanned_objects,
            "scanned_bytes": self.scanned_bytes,
            "junk_objects": self.junk_objects,
            "junk_bytes": self.junk_bytes,
            "quarantined_objects": self.quarantined_objects,
            "quarantined_bytes": self.quarantined_bytes,
            "created_at": format_dt(self.created_at),
            "started_at": format_dt(self.started_at),
            "completed_at": format_dt(self.completed_at),
            "error_message": self.error_message,
        }


class CloudAuditFinding(Base):
    """Model for per-object findings from cloud audit runs."""
    __tablename__ = "cloud_audit_findings"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, index=True)
    bucket_name = Column(String, index=True)
    object_name = Column(String, nullable=False, index=True)
    size_bytes = Column(Float, default=0.0)
    updated_at = Column(DateTime, nullable=True)
    matched_pattern = Column(String, nullable=False)
    suggested_action = Column(String, default="quarantine")
    action_status = Column(String, default="pending")  # pending, quarantined, skipped, error
    quarantine_object_name = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "bucket_name": self.bucket_name,
            "object_name": self.object_name,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "matched_pattern": self.matched_pattern,
            "suggested_action": self.suggested_action,
            "action_status": self.action_status,
            "quarantine_object_name": self.quarantine_object_name,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class LocalAuditRun(Base):
    """Model for local filesystem audit runs."""
    __tablename__ = "local_audit_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    status = Column(String, default="running")  # queued, running, completed, failed, cancelled
    target_path = Column(String, nullable=False, index=True)

    # Scan options and metadata
    recursive = Column(Boolean, default=True)
    scan_mode = Column(String, default="detailed")
    max_detailed_files = Column(Integer, default=0)
    detailed_truncated = Column(Boolean, default=False)
    skip_permission_count = Column(Integer, default=0)

    # Aggregates
    total_files = Column(Integer, default=0)
    total_size_bytes = Column(Float, default=0.0)
    subfolder_count = Column(Integer, default=0)
    file_types = Column(JSON, nullable=True)
    top_level_folders = Column(JSON, nullable=True)
    recommendations = Column(JSON, nullable=True)

    # Timing and errors
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    scan_duration_seconds = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        """Convert to dictionary."""
        def format_dt(dt):
            if not dt:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        return {
            "id": self.id,
            "run_id": self.run_id,
            "status": self.status,
            "target_path": self.target_path,
            "recursive": self.recursive,
            "scan_mode": self.scan_mode,
            "max_detailed_files": self.max_detailed_files,
            "detailed_truncated": bool(self.detailed_truncated),
            "skip_permission_count": int(self.skip_permission_count or 0),
            "total_files": int(self.total_files or 0),
            "total_size_bytes": float(self.total_size_bytes or 0.0),
            "subfolder_count": int(self.subfolder_count or 0),
            "file_types": self.file_types or {},
            "top_level_folders": self.top_level_folders or [],
            "recommendations": self.recommendations or [],
            "created_at": format_dt(self.created_at),
            "started_at": format_dt(self.started_at),
            "completed_at": format_dt(self.completed_at),
            "scan_duration_seconds": float(self.scan_duration_seconds or 0.0),
            "error_message": self.error_message,
        }


class LocalAuditFinding(Base):
    """Model for local audit detailed file findings."""
    __tablename__ = "local_audit_findings"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, index=True)
    top_level_folder = Column(String, index=True)
    relative_path = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    extension = Column(String, default="")
    file_category = Column(String, default="other")
    size_bytes = Column(Float, default=0.0)
    modified_at = Column(DateTime, nullable=True)
    age_days = Column(Integer, default=0)
    is_temp = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "top_level_folder": self.top_level_folder,
            "relative_path": self.relative_path,
            "file_name": self.file_name,
            "extension": self.extension,
            "file_category": self.file_category,
            "size_bytes": float(self.size_bytes or 0.0),
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "age_days": int(self.age_days or 0),
            "is_temp": bool(self.is_temp),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

def _run_migrations():
    """Run database migrations for schema changes."""
    if SessionLocal is None or engine is None:
        return
    
    try:
        # Check existing tables/columns
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Security migration: Drive OAuth tokens are memory-only. Remove the
        # legacy plaintext token table from older local databases.
        if 'drive_user_tokens' in tables:
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE drive_user_tokens"))
                conn.commit()
            print("✓ Dropped legacy Drive OAuth token table from database")

        # Migration: Create cloud audit tables (for existing DBs)
        if 'cloud_audit_runs' not in tables:
            print("⚙ Running migration: Creating 'cloud_audit_runs' table...")
            CloudAuditRun.__table__.create(bind=engine, checkfirst=True)
            print("✓ Migration completed: cloud_audit_runs table created")

        if 'cloud_audit_findings' not in tables:
            print("⚙ Running migration: Creating 'cloud_audit_findings' table...")
            CloudAuditFinding.__table__.create(bind=engine, checkfirst=True)
            print("✓ Migration completed: cloud_audit_findings table created")

        if 'local_audit_runs' not in tables:
            print("⚙ Running migration: Creating 'local_audit_runs' table...")
            LocalAuditRun.__table__.create(bind=engine, checkfirst=True)
            print("✓ Migration completed: local_audit_runs table created")

        if 'local_audit_findings' not in tables:
            print("⚙ Running migration: Creating 'local_audit_findings' table...")
            LocalAuditFinding.__table__.create(bind=engine, checkfirst=True)
            print("✓ Migration completed: local_audit_findings table created")

        columns = [col['name'] for col in inspector.get_columns('upload_jobs')]
        
        migrations_run = False
        
        # Migration: Add friendly_name column
        if 'friendly_name' not in columns:
            print("⚙ Running migration: Adding 'friendly_name' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN friendly_name VARCHAR"))
                conn.commit()
            print("✓ Migration completed: friendly_name column added")
            migrations_run = True
        
        # Migration: Add upload_tool column
        if 'upload_tool' not in columns:
            print("⚙ Running migration: Adding 'upload_tool' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN upload_tool VARCHAR DEFAULT 'gcloud'"))
                conn.commit()
            print("✓ Migration completed: upload_tool column added")
            migrations_run = True
        
        # Migration: Add cleared column
        if 'cleared' not in columns:
            print("⚙ Running migration: Adding 'cleared' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN cleared BOOLEAN DEFAULT 0"))
                conn.commit()
            print("✓ Migration completed: cleared column added")
            migrations_run = True
        
        # Migration: Add no_clobber column (Issue #13)
        if 'no_clobber' not in columns:
            print("⚙ Running migration: Adding 'no_clobber' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN no_clobber BOOLEAN DEFAULT 0"))
                conn.commit()
            print("✓ Migration completed: no_clobber column added")
            migrations_run = True

        # Migration: Add auto_retry columns (Issue #14)
        if 'auto_retry' not in columns:
            print("⚙ Running migration: Adding 'auto_retry' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN auto_retry BOOLEAN DEFAULT 0"))
                conn.commit()
            print("✓ Migration completed: auto_retry column added")
            migrations_run = True

        if 'auto_retry_delay_minutes' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN auto_retry_delay_minutes INTEGER DEFAULT 30"))
                conn.commit()
            migrations_run = True

        if 'retry_count' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN retry_count INTEGER DEFAULT 0"))
                conn.commit()
            migrations_run = True

        if 'max_auto_retries' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN max_auto_retries INTEGER DEFAULT 3"))
                conn.commit()
            migrations_run = True

        if 'next_retry_at' not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN next_retry_at DATETIME"))
                conn.commit()
            migrations_run = True

        if 'custom_command' not in columns:
            print("⚙ Running migration: Adding 'custom_command' column...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE upload_jobs ADD COLUMN custom_command TEXT"))
                conn.commit()
            print("✓ Migration completed: custom_command column added")
            migrations_run = True

        if 'custom_command' in columns:
            with engine.connect() as conn:
                result = conn.execute(text("UPDATE upload_jobs SET custom_command = NULL WHERE custom_command IS NOT NULL"))
                conn.commit()
            cleared = getattr(result, "rowcount", 0) or 0
            if cleared:
                print(f"✓ Cleared {cleared} legacy custom command value(s) from database")

        if not migrations_run:
            print("✓ Database schema is up to date")

    except Exception as e:
        print(f"⚠ Migration warning: {e}")
        # Don't fail startup if migration has issues
        pass

    # Migrate drive_sync_jobs table if it already exists but is missing columns
    try:
        inspector2 = inspect(engine)
        if 'drive_sync_jobs' in inspector2.get_table_names():
            drive_cols = [c['name'] for c in inspector2.get_columns('drive_sync_jobs')]
            if 'bisync_resync' not in drive_cols:
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE drive_sync_jobs ADD COLUMN bisync_resync BOOLEAN DEFAULT 0"))
                    conn.commit()
            if 'cleared' not in drive_cols:
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE drive_sync_jobs ADD COLUMN cleared BOOLEAN DEFAULT 0"))
                    conn.commit()
    except Exception as e:
        print(f"⚠ Drive table migration warning: {e}")

def init_db():
    """Initialize database."""
    global engine, SessionLocal
    
    # Create engine
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    )
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create session factory
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    print("✓ Database initialized")
    
    # Run migrations for existing databases
    _run_migrations()
    
    # Recover stuck jobs from server restart
    _recover_stuck_jobs()

def _recover_stuck_jobs():
    """Recover jobs stuck in running/pending state after server restart."""
    if SessionLocal is None:
        return
    
    db = SessionLocal()
    try:
        # Find upload jobs stuck in running or pending state
        stuck_jobs = db.query(UploadJob).filter(
            UploadJob.status.in_(['running', 'pending'])
        ).all()
        
        if stuck_jobs:
            print(f"⚠ Found {len(stuck_jobs)} stuck jobs from previous session")
            
            for job in stuck_jobs:
                job.status = 'failed'
                job.error_message = 'Server restarted while job was in progress'
                job.completed_at = datetime.now(timezone.utc)
                print(f"  - Reset job {job.job_id} from '{job.status}' to 'failed'")
            
            db.commit()
            print("✓ Recovered stuck jobs")

        # Find cloud audit runs that were interrupted by restart.
        stuck_audit_runs = db.query(CloudAuditRun).filter(
            CloudAuditRun.status.in_(['queued', 'running', 'cancel_requested'])
        ).all()

        if stuck_audit_runs:
            print(f"⚠ Found {len(stuck_audit_runs)} stuck cloud audit runs from previous session")

            for run in stuck_audit_runs:
                run.status = 'failed'
                run.error_message = 'Server restarted while cloud audit run was in progress'
                run.completed_at = datetime.now(timezone.utc)
                print(f"  - Reset cloud audit run {run.run_id} to 'failed'")

            db.commit()
            print("✓ Recovered stuck cloud audit runs")

        # Find local audit runs that were interrupted by restart.
        stuck_local_runs = db.query(LocalAuditRun).filter(
            LocalAuditRun.status.in_(['queued', 'running'])
        ).all()

        if stuck_local_runs:
            print(f"⚠ Found {len(stuck_local_runs)} stuck local audit runs from previous session")

            for run in stuck_local_runs:
                run.status = 'failed'
                run.error_message = 'Server restarted while local audit run was in progress'
                run.completed_at = datetime.now(timezone.utc)
                print(f"  - Reset local audit run {run.run_id} to 'failed'")

            db.commit()
            print("✓ Recovered stuck local audit runs")
    except Exception as e:
        print(f"❌ Error recovering stuck jobs: {e}")
    finally:
        db.close()

def close_db():
    """Close database connection."""
    global engine
    if engine:
        engine.dispose()
        print("✓ Database connection closed")

def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
