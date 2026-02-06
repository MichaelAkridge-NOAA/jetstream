"""Settings and configuration management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import subprocess

router = APIRouter()

class SettingsResponse(BaseModel):
    """Response model for settings."""
    gcs_authenticated: bool
    auth_method: Optional[str]
    gcloud_account: Optional[str]


@router.get("/", response_model=SettingsResponse)
async def get_settings():
    """Get current settings and check ADC authentication status."""
    from ..config import settings
    from google.cloud import storage
    
    authenticated = False
    auth_method = None
    gcloud_account = None
    
    # Check if ADC is configured
    try:
        client = storage.Client()
        authenticated = True
        
        # Determine auth method
        if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            auth_method = "Service Account (GOOGLE_APPLICATION_CREDENTIALS)"
        else:
            auth_method = "User Credentials (gcloud ADC)"
            # Try to get gcloud account info
            try:
                result = subprocess.run(
                    ['gcloud', 'auth', 'list', '--filter=status:ACTIVE', '--format=value(account)'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    gcloud_account = result.stdout.strip()
            except:
                pass
    except:
        authenticated = False
    
    return SettingsResponse(
        gcs_authenticated=authenticated,
        auth_method=auth_method,
        gcloud_account=gcloud_account
    )
