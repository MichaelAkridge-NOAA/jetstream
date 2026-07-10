"""Pydantic models for request/response validation."""

from pydantic import BaseModel, Field, validator, model_validator
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class UploadRequest(BaseModel):
    """Request model for creating an upload job."""
    source_path: str = Field(..., description="Local path to upload from")
    gcs_destination: str = Field(..., description="GCS destination (bucket/path or gs://bucket/path)")
    
    dry_run: bool = Field(False, description="Preview without uploading")
    recursive: bool = Field(True, description="Include subfolders")
    threads: int = Field(4, description="Number of parallel threads")
    split_by_folder: bool = Field(False, description="Split into separate jobs per subfolder")
    upload_tool: str = Field("gcloud", description="Upload tool: 'gcloud' or 'gsutil'")
    scheduled_for: Optional[datetime] = Field(None, description="Schedule upload for specific datetime (ISO format)")
    
    exclude_patterns: Optional[List[str]] = Field(None, description="Regex patterns for files to exclude")
    exclude_folders: Optional[List[str]] = Field(None, description="Folder names to exclude")

    # Data protection & rsync options (Issue #13)
    no_clobber: bool = Field(False, description="Skip files already existing in bucket (gcloud --no-clobber, gcloud only)")

    # Auto-retry configuration (Issue #14)
    auto_retry: bool = Field(False, description="Automatically retry failed jobs")
    auto_retry_delay_minutes: int = Field(30, description="Minutes to wait before auto-retry")
    max_auto_retries: int = Field(3, description="Maximum number of auto-retry attempts")
    
    # Computed properties for backward compatibility
    destination_bucket: Optional[str] = None
    destination_path: Optional[str] = None
    
    @validator('scheduled_for')
    def convert_to_utc(cls, v):
        """Normalize scheduled_for to naive UTC for DB consistency."""
        if v is None:
            return v
        from datetime import datetime, timezone

        # Treat naive input as local wall-clock time, then convert to UTC.
        if v.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            if local_tz is not None:
                v = v.replace(tzinfo=local_tz)

        # Store as naive UTC to match SQLite DateTime behavior in this app.
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    
    @validator('source_path')
    def validate_source_path(cls, v):
        """Validate source path exists."""
        import os
        if not os.path.exists(v):
            raise ValueError(f"Source path does not exist: {v}")
        if not os.path.isdir(v):
            raise ValueError(f"Source path is not a directory: {v}")
        return v
    
    @model_validator(mode='after')
    def parse_gcs_destination(self):
        """Parse GCS destination into bucket and path components."""
        gcs_dest = self.gcs_destination
        
        if not gcs_dest:
            raise ValueError("GCS destination is required")
        
        # Default bucket name
        default_bucket = "nmfs_odp_pifsc"
        
        # Strip gs:// prefix if present
        if gcs_dest.startswith('gs://'):
            gcs_dest = gcs_dest[5:]
        
        # Remove leading/trailing slashes
        gcs_dest = gcs_dest.strip('/')
        
        # Split into bucket and path
        parts = gcs_dest.split('/', 1)
        
        if len(parts) == 0 or not parts[0]:
            # No bucket specified, use default
            self.destination_bucket = default_bucket
            self.destination_path = gcs_dest if gcs_dest else ""
        elif len(parts) == 1:
            # Only bucket specified, no path
            self.destination_bucket = parts[0]
            self.destination_path = ""
        else:
            # Both bucket and path specified
            self.destination_bucket = parts[0]
            self.destination_path = parts[1]
        
        return self

class UploadResponse(BaseModel):
    """Response model for upload job."""
    job_id: str
    status: JobStatus
    message: str
    source_path: str
    destination: str

class JobStatusResponse(BaseModel):
    """Response model for job status."""
    id: int
    job_id: str
    friendly_name: Optional[str] = None
    status: JobStatus
    source_path: str
    destination_bucket: str
    destination_path: Optional[str]
    
    total_files: int
    total_size_bytes: float
    files_uploaded: int
    bytes_uploaded: float
    progress_percent: float
    
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    scheduled_for: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    transfer_speed: Optional[float] = None
    
    dry_run: bool
    recursive: bool = True
    threads: int = 4
    split_by_folder: bool = False
    upload_tool: Optional[str] = "gcloud"
    error_message: Optional[str]
    log_path: Optional[str]
    upload_output: Optional[str] = None
    filters: Optional[dict] = None
    job_type: str = "upload"
    transfer_direction: str = "local_to_cloud"

    # Data protection & rsync options (Issue #13)
    no_clobber: bool = False

    # Auto-retry fields (Issue #14)
    auto_retry: bool = False
    auto_retry_delay_minutes: int = 30
    retry_count: int = 0
    max_auto_retries: int = 3
    next_retry_at: Optional[datetime] = None

class FolderAnalysisRequest(BaseModel):
    """Request model for folder analysis."""
    path: str = Field(..., description="Path to analyze")
    recursive: bool = Field(True, description="Include subfolders")
    include_patterns: Optional[List[str]] = Field(None, description="File patterns to include")
    exclude_patterns: Optional[List[str]] = Field(None, description="File patterns to exclude")
    exclude_folders: Optional[List[str]] = Field(None, description="Folder names to exclude")

class FolderAnalysisResponse(BaseModel):
    """Response model for folder analysis."""
    path: str
    total_files: int
    total_size_bytes: float
    total_size_mb: float
    total_size_gb: float
    file_types: Dict[str, int]
    subfolder_count: int
    subfolders: Optional[List[Dict]] = None  # List of subfolder stats if split_by_folder
    preview_files: List[str] = Field(default_factory=list, description="Sample of files to upload")
    scan_mode: Optional[str] = Field(None, description="Scan mode used: 'detailed' or 'folder_only'")
    scan_duration: Optional[float] = Field(None, description="Time taken to scan in seconds")

class StatsResponse(BaseModel):
    """Response model for overall statistics."""
    total_jobs: int
    jobs_by_status: Dict[str, int]
    total_uploaded_bytes: float
    total_uploaded_gb: float
    total_files_uploaded: int
    active_jobs: int
    queue_length: int

class CloudAnalysisRequest(BaseModel):
    """Request model for cloud storage analysis."""
    bucket_name: str = Field(..., description="GCS bucket name")
    prefix: str = Field("", description="Folder prefix to analyze (optional)")
    max_depth: int = Field(3, description="Maximum folder depth to analyze")


# ── Native Google Drive API models (gdrive page) ─────────────────────────────

class GDriveAuthStatus(BaseModel):
    """Current OAuth connection status for the native Drive page."""
    connected: bool
    account_email: Optional[str] = None
    scopes: Optional[str] = None
    client_configured: bool   # True when GDRIVE_CLIENT_ID/SECRET are set
    auth_url: Optional[str] = None  # populated when not connected and client configured


class GDriveBrowseItem(BaseModel):
    """Single file or folder returned by the Drive browser."""
    id: str
    name: str
    mime_type: str
    is_folder: bool
    modified_time: Optional[str] = None
    size_bytes: Optional[int] = None
    web_view_link: Optional[str] = None


class GDriveBrowseResponse(BaseModel):
    """Response from the Drive folder browser endpoint."""
    folder_id: str
    folder_name: str
    items: List[GDriveBrowseItem]
    next_page_token: Optional[str] = None


class GDriveUploadRequest(BaseModel):
    """Request to upload a local file to Google Drive."""
    local_path: str = Field(..., description="Absolute local file path to upload")
    folder_id: str = Field("root", description="Drive folder ID to upload into")
    overwrite: bool = Field(False, description="If True, replace existing file with same name")


class GDriveUploadResponse(BaseModel):
    """Result of a Drive upload operation."""
    success: bool
    upload_id: Optional[str] = None
    status: Optional[str] = None
    progress_pct: Optional[int] = None
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    web_view_link: Optional[str] = None
    error: Optional[str] = None


class GDriveUploadStatusResponse(BaseModel):
    """Live status for an asynchronous single-file upload."""
    upload_id: str
    status: str
    progress_pct: int = 0
    file_name: Optional[str] = None
    file_id: Optional[str] = None
    web_view_link: Optional[str] = None
    error: Optional[str] = None


class GDriveSyncRequest(BaseModel):
    """Request to sync a local folder to a Google Drive folder."""
    local_folder: str = Field(..., description="Absolute local directory path to sync")
    drive_folder_id: str = Field("root", description="Drive folder ID to sync into")
    recursive: bool = Field(True, description="Include sub-folders")
    overwrite: bool = Field(False, description="Replace existing files with the same name")
    concurrency: int = Field(4, ge=1, le=16, description="Number of files to upload in parallel (1-16)")
    chunk_size_mb: int = Field(8, ge=1, le=64, description="Resumable upload chunk size in MB (1-64)")


class GDriveSyncFileResult(BaseModel):
    """Result for a single file within a sync operation."""
    local_path: str
    file_name: str
    success: bool
    file_id: Optional[str] = None
    web_view_link: Optional[str] = None
    error: Optional[str] = None


class GDriveSyncResponse(BaseModel):
    """Result of a folder sync operation."""
    total: int
    succeeded: int
    failed: int
    files: list[GDriveSyncFileResult]
