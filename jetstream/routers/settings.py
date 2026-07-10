"""Settings and configuration management."""

from fastapi import APIRouter, Request
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
    gdrive_router_available: bool
    gdrive_router_error: Optional[str]
    gdrive_client_configured: bool


@router.get("/", response_model=SettingsResponse)
async def get_settings(request: Request):
    """Get current settings and check ADC authentication status."""
    from ..config import settings

    authenticated = False
    auth_method = None
    gcloud_account = None

    # Check if ADC credentials are configured using a LOCAL-ONLY check.
    # Deliberately avoid storage.Client() here.
    #
    # storage.Client() is safe when the local ADC access token is fresh (reads
    # from disk, no network needed).  But when the token is EXPIRED it calls
    # oauth2.googleapis.com to refresh — that outbound HTTPS request can be
    # blocked indefinitely by corporate firewalls/proxies, causing the API
    # endpoint to hang, the browser to give up, and "NetworkError" to appear.
    #
    # google.auth.default() only inspects local credential files / env vars and
    # never attempts a token refresh, so it is always safe regardless of network
    # conditions or token freshness.
    try:
        import google.auth
        import google.auth.exceptions

        # google.auth.default() reads the local ADC file / env vars only.
        # It does NOT make any network calls, so it is safe behind firewalls.
        credentials, _project = google.auth.default()
        authenticated = True

        # Determine auth method
        if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
            auth_method = "Service Account (GOOGLE_APPLICATION_CREDENTIALS)"
        else:
            auth_method = "User Credentials (gcloud ADC)"
            # Try to get gcloud account info (quick subprocess, 5 s timeout)
            try:
                result = subprocess.run(
                    ['gcloud', 'auth', 'list', '--filter=status:ACTIVE', '--format=value(account)'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    gcloud_account = result.stdout.strip()
            except Exception:
                pass
    except Exception:
        authenticated = False

    return SettingsResponse(
        gcs_authenticated=authenticated,
        auth_method=auth_method,
        gcloud_account=gcloud_account,
        gdrive_router_available=bool(getattr(request.app.state, "gdrive_router_available", False)),
        gdrive_router_error=getattr(request.app.state, "gdrive_router_import_error", None),
        gdrive_client_configured=bool(settings.GDRIVE_CLIENT_ID and settings.GDRIVE_CLIENT_SECRET),
    )
