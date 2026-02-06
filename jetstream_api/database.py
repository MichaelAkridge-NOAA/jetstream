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
    
    def to_dict(self):
        """Convert to dictionary."""
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
            "progress_percent": round((self.bytes_uploaded / self.total_size_bytes * 100) if self.total_size_bytes > 0 else 0, 2),
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
            "filters": self.filters
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

def _run_migrations():
    """Run database migrations for schema changes."""
    if SessionLocal is None or engine is None:
        return
    
    try:
        # Check existing columns
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
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
        
        if not migrations_run:
            print("✓ Database schema is up to date")
            
    except Exception as e:
        print(f"⚠ Migration warning: {e}")
        # Don't fail startup if migration has issues
        pass

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
        # Find jobs stuck in running or pending state
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
