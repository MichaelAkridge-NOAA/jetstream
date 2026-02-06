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
    
    # Computed properties for backward compatibility
    destination_bucket: Optional[str] = None
    destination_path: Optional[str] = None
    
    @validator('scheduled_for')
    def convert_to_utc(cls, v):
        """Convert scheduled_for to UTC if it has timezone info."""
        if v is None:
            return v
        from datetime import timezone
        # If timezone aware, convert to UTC
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc)
        # If naive, assume it's already UTC
        return v
    
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
