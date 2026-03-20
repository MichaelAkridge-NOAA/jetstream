"""Configuration settings for JetStream API."""

from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    """Application settings."""
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    AUTO_OPEN_BROWSER: bool = True  # Auto-open browser on startup
    
    # Database
    DATABASE_URL: str = "sqlite:///./jetstream.db"
    
    # Google Cloud Storage
    GCS_PROJECT_ID: Optional[str] = None
    GCS_CREDENTIALS_PATH: Optional[str] = None
    GCS_BUCKET_NAME: str = "nmfs_odp_pifsc"  # Default bucket name
    
    # Scanner Performance Settings (Optimized for very large folders)
    MAX_FILES_FOR_DETAILED_SCAN: int = 1000   # Switch to folder-only after this
    MAX_SUBFOLDERS_FOR_DETAILED_SCAN: int = 20  # Switch to folder-only after this
    SCAN_TIMEOUT_SECONDS: int = 60  # Max time for a scan (1 minute)
    ENABLE_FAST_SCAN: bool = True  # Use os.scandir instead of os.walk
    
    # File filtering (from jetstream.py)
    EXCLUDE_FOLDERS: list = [
        "_archive", "_YEAR", "ISLAND", "SITE-ID", "SITE_PHOTOS", 
        "Corrected", "corrected", "uncorrected", "MISC", "DARK", 
        "Products", "Thumbs.db", ".DS_Store", "__pycache__"
    ]
    
    EXCLUDE_PATTERNS: list = [
        r'.*\.tmp$',
        r'.*\.bak$',
        r'.*~$',
        r'.*\.pyc$',
    ]
    
    INCLUDE_PATTERNS: list = [
        r'^.*(?<!\.JPG)$',
        r'^.*\.(jpg|jpeg|png|tiff|tif|raw|cr2|nef|arw|dng)$',
        r'^.*\.(mp4|mov|avi|mkv)$',
        r'^.*\.(txt|csv|json|xml|log)$'
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
