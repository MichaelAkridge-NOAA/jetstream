"""Cloud Storage Analyzer - On-demand GCS bucket analysis."""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from google.cloud import storage
from datetime import datetime, timezone
import asyncio
import subprocess
import uuid

router = APIRouter()

# Store for tracking cloud transfer jobs (in-memory for simplicity)
cloud_transfer_jobs = {}

class CloudAnalysisRequest(BaseModel):
    """Request model for cloud storage analysis."""
    bucket_name: str = Field(..., description="GCS bucket name")
    prefix: str = Field("", description="Folder prefix to analyze (optional)")
    max_depth: int = Field(3, description="Maximum folder depth to analyze")

class CloudTransferRequest(BaseModel):
    """Request model for cloud-to-cloud transfer."""
    source_path: str = Field(..., description="Source GCS path (gs://bucket/path or bucket/path)")
    dest_path: str = Field(..., description="Destination GCS path (gs://bucket/path or bucket/path)")
    recursive: bool = Field(True, description="Include subfolders")
    dry_run: bool = Field(True, description="Preview without actually transferring")
    exclude_patterns: Optional[List[str]] = Field(None, description="Patterns to exclude")

class CloudTransferResponse(BaseModel):
    """Response model for cloud transfer."""
    job_id: str
    status: str
    message: str
    command: str
    
class FolderStats(BaseModel):
    """Folder statistics model."""
    path: str
    file_count: int
    folder_count: int
    total_size_bytes: int
    total_size_gb: float
    earliest_created: Optional[str]
    latest_updated: Optional[str]

@router.post("/analyze-bucket")
async def analyze_bucket(request: CloudAnalysisRequest):
    """
    Analyze a GCS bucket and return statistics.
    This can be a long-running operation for large buckets.
    """
    try:
        def analyze_sync():
            """Synchronous analysis function to run in thread."""
            try:
                # Use Application Default Credentials (ADC)
                # This automatically finds credentials from:
                # 1. GOOGLE_APPLICATION_CREDENTIALS env var
                # 2. gcloud auth application-default credentials
                # 3. Compute Engine/Cloud Run service account
                client = storage.Client()
            except Exception as e:
                raise HTTPException(
                    status_code=401, 
                    detail=f"Authentication failed. Please run 'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS environment variable. Error: {str(e)}"
                )
            
            bucket = client.bucket(request.bucket_name)
            
            # Check if bucket exists
            if not bucket.exists():
                raise HTTPException(status_code=404, detail=f"Bucket '{request.bucket_name}' not found")
            
            folder_stats = {}
            
            # List all blobs with the given prefix
            blobs = bucket.list_blobs(prefix=request.prefix)
            
            total_blobs = 0
            for blob in blobs:
                total_blobs += 1
                
                # Extract folder path
                if blob.name.endswith('/'):
                    # It's a folder marker
                    folder_path = blob.name
                    if folder_path not in folder_stats:
                        folder_stats[folder_path] = {
                            'files': [],
                            'subfolders': set(),
                            'total_size': 0
                        }
                else:
                    # It's a file
                    parts = blob.name.split('/')
                    
                    # Track file in its immediate folder
                    if len(parts) > 1:
                        folder_path = '/'.join(parts[:-1]) + '/'
                    else:
                        folder_path = '/'
                    
                    if folder_path not in folder_stats:
                        folder_stats[folder_path] = {
                            'files': [],
                            'subfolders': set(),
                            'total_size': 0
                        }
                    
                    folder_stats[folder_path]['files'].append({
                        'name': blob.name,
                        'size': blob.size or 0,
                        'created': blob.time_created.isoformat() if blob.time_created else None,
                        'updated': blob.updated.isoformat() if blob.updated else None
                    })
                    folder_stats[folder_path]['total_size'] += blob.size or 0
                
                # Stop after reasonable amount for quick preview
                if total_blobs > 10000:
                    break
            
            # Calculate statistics
            results = []
            for path, stats in folder_stats.items():
                files = stats['files']
                results.append({
                    'path': path,
                    'file_count': len(files),
                    'folder_count': len(stats['subfolders']),
                    'total_size_bytes': stats['total_size'],
                    'total_size_gb': round(stats['total_size'] / (1024**3), 4),
                    'earliest_created': min((f['created'] for f in files if f['created']), default=None),
                    'latest_updated': max((f['updated'] for f in files if f['updated']), default=None)
                })
            
            # Sort by size descending
            results.sort(key=lambda x: x['total_size_bytes'], reverse=True)
            
            return {
                'bucket_name': request.bucket_name,
                'prefix': request.prefix,
                'total_folders_analyzed': len(results),
                'total_blobs_scanned': total_blobs,
                'folders': results[:50],  # Return top 50 folders
                'analysis_time': datetime.now(timezone.utc).isoformat()
            }
        
        # Run analysis in thread pool to avoid blocking
        result = await asyncio.to_thread(analyze_sync)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@router.get("/bucket-summary/{bucket_name}")
async def get_bucket_summary(bucket_name: str):
    """Get quick summary of a GCS bucket."""
    try:
        def get_summary():
            try:
                # Use Application Default Credentials (ADC)
                client = storage.Client()
            except Exception as e:
                raise HTTPException(
                    status_code=401, 
                    detail=f"Authentication failed. Please run 'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS environment variable. Error: {str(e)}"
                )
            
            bucket = client.bucket(bucket_name)
            
            if not bucket.exists():
                raise HTTPException(status_code=404, detail=f"Bucket '{bucket_name}' not found")
            
            # Get bucket metadata
            bucket.reload()
            
            # Count objects (limited sample for speed)
            blobs = list(bucket.list_blobs(max_results=1000))
            sample_size = len(blobs)
            total_size = sum(blob.size for blob in blobs if blob.size)
            
            return {
                'bucket_name': bucket_name,
                'location': bucket.location,
                'storage_class': bucket.storage_class,
                'created': bucket.time_created.isoformat() if bucket.time_created else None,
                'sample_object_count': sample_size,
                'sample_total_size_gb': round(total_size / (1024**3), 2),
                'note': 'Limited to first 1000 objects for quick preview'
            }
        
        result = await asyncio.to_thread(get_summary)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get bucket summary: {str(e)}")


def normalize_gcs_path(path: str) -> str:
    """Normalize a GCS path to gs:// format."""
    path = path.strip().rstrip('/')
    if path.startswith('gs://'):
        return path
    return f"gs://{path}"


@router.post("/transfer", response_model=CloudTransferResponse)
async def start_cloud_transfer(request: CloudTransferRequest, background_tasks: BackgroundTasks):
    """
    Start a cloud-to-cloud transfer using gcloud storage rsync.
    """
    job_id = str(uuid.uuid4())[:8]
    
    source = normalize_gcs_path(request.source_path)
    dest = normalize_gcs_path(request.dest_path)
    
    # Build command
    cmd = ["gcloud", "storage", "rsync"]
    
    if request.recursive:
        cmd.append("--recursive")
    
    if request.dry_run:
        cmd.append("--dry-run")
    
    # Add exclude patterns
    if request.exclude_patterns:
        for pattern in request.exclude_patterns:
            if pattern.strip():
                cmd.append(f"--exclude={pattern.strip()}")
    
    cmd.extend([source, dest])
    
    # Build display command
    command_str = " ".join(cmd)
    
    # Initialize job status
    cloud_transfer_jobs[job_id] = {
        "status": "running",
        "source_path": source,
        "dest_path": dest,
        "dry_run": request.dry_run,
        "command": command_str,
        "output": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None
    }
    
    # Run transfer in background
    background_tasks.add_task(run_cloud_transfer, job_id, cmd)
    
    return CloudTransferResponse(
        job_id=job_id,
        status="running",
        message="Cloud transfer started" + (" (dry run)" if request.dry_run else ""),
        command=command_str
    )


async def run_cloud_transfer(job_id: str, cmd: list):
    """Execute the cloud transfer command."""
    try:
        def run_sync():
            # Build shell command with proper quoting
            shell_cmd_parts = []
            for arg in cmd:
                if ' ' in arg or '=' in arg:
                    shell_cmd_parts.append(f'"{arg}"')
                else:
                    shell_cmd_parts.append(arg)
            shell_cmd = ' '.join(shell_cmd_parts)
            
            print(f"🚀 Cloud Transfer: {shell_cmd}")
            
            process = subprocess.Popen(
                shell_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate()
            return process.returncode, stdout, stderr
        
        returncode, stdout, stderr = await asyncio.to_thread(run_sync)
        
        output = f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
        
        if returncode == 0:
            cloud_transfer_jobs[job_id]["status"] = "completed"
            cloud_transfer_jobs[job_id]["output"] = output
        else:
            cloud_transfer_jobs[job_id]["status"] = "failed"
            cloud_transfer_jobs[job_id]["output"] = output
            cloud_transfer_jobs[job_id]["error"] = stderr or "Unknown error"
        
        cloud_transfer_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
        
    except Exception as e:
        cloud_transfer_jobs[job_id]["status"] = "failed"
        cloud_transfer_jobs[job_id]["error"] = str(e)
        cloud_transfer_jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()


@router.get("/transfer/{job_id}")
async def get_transfer_status(job_id: str):
    """Get status of a cloud transfer job."""
    if job_id not in cloud_transfer_jobs:
        raise HTTPException(status_code=404, detail="Transfer job not found")
    
    job = cloud_transfer_jobs[job_id].copy()
    job["job_id"] = job_id
    return job


@router.get("/transfers")
async def list_transfers():
    """List recent cloud transfer jobs."""
    # Return as array with job_id included in each item
    jobs = []
    for job_id, job_data in cloud_transfer_jobs.items():
        job = job_data.copy()
        job["job_id"] = job_id
        jobs.append(job)
    return jobs
