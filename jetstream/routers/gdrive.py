"""
Native Google Drive API router for JetStream.
Uses google-api-python-client + google-auth-oauthlib for per-user OAuth.
Separate from the rclone-backed /api/drive routes.
"""

import os
import secrets
import mimetypes
import asyncio
import time
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from threading import Lock
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from ..config import settings
from .. import database
from ..models import (
    GDriveAuthStatus,
    GDriveBrowseItem,
    GDriveBrowseResponse,
    GDriveUploadRequest,
    GDriveUploadResponse,
    GDriveUploadStatusResponse,
    GDriveSyncRequest,
    GDriveSyncFileResult,
    GDriveSyncResponse,
)

router = APIRouter()


@dataclass
class DriveUserToken:
    """In-memory Drive OAuth token record; never mapped to the database."""

    account_email: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[datetime] = None
    scopes: Optional[str] = None

# ── Constants ────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive"]

# Temporary in-memory state store for OAuth CSRF tokens (TTL enforced at use-time)
_oauth_states: dict = {}   # state_token -> {"created": datetime, "code_verifier": str}
_STATE_TTL_SECONDS = 600
_oauth_state_lock = Lock()

# In-memory credential cache used when token persistence is disabled.
_token_lock = Lock()
_memory_token: Optional[dict] = None

# Background single-file upload state
_upload_jobs_lock = Lock()
_upload_jobs: dict = {}
_UPLOAD_JOB_TTL_SECONDS = 24 * 60 * 60


# ── Internal helpers ─────────────────────────────────────────────────────────

def _redirect_uri() -> str:
    return f"{settings.JETSTREAM_BASE_URL.rstrip('/')}/api/gdrive/auth/callback"


def _client_configured() -> bool:
    return bool(settings.GDRIVE_CLIENT_ID and settings.GDRIVE_CLIENT_SECRET)


def _build_flow(state: Optional[str] = None, code_verifier: Optional[str] = None) -> Flow:
    """Construct an OAuth flow from settings."""
    client_config = {
        "web": {
            "client_id": settings.GDRIVE_CLIENT_ID,
            "client_secret": settings.GDRIVE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    return flow


def _create_auth_url() -> str:
    """Create a Google auth URL and persist PKCE verifier in state store."""
    _cleanup_oauth_states()
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    with _oauth_state_lock:
        _oauth_states[state] = {
            "created": datetime.now(timezone.utc),
            "code_verifier": code_verifier,
        }

    flow = _build_flow(state=state, code_verifier=code_verifier)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        code_challenge_method="S256",
        include_granted_scopes="true",
    )
    return auth_url


def _cleanup_oauth_states() -> None:
    """Prune expired OAuth states and cap total entries."""
    now = datetime.now(timezone.utc)
    max_entries = max(1, settings.GDRIVE_OAUTH_STATE_MAX_ENTRIES)
    with _oauth_state_lock:
        expired = [
            key for key, value in _oauth_states.items()
            if (now - value["created"]).total_seconds() > _STATE_TTL_SECONDS
        ]
        for key in expired:
            _oauth_states.pop(key, None)

        if len(_oauth_states) > max_entries:
            ordered = sorted(_oauth_states.items(), key=lambda item: item[1]["created"])
            overflow = len(_oauth_states) - max_entries
            for key, _ in ordered[:overflow]:
                _oauth_states.pop(key, None)


def _cleanup_upload_jobs() -> None:
    """Prune old completed/failed upload status entries."""
    now = datetime.now(timezone.utc)
    with _upload_jobs_lock:
        stale_ids = []
        for upload_id, payload in _upload_jobs.items():
            updated_at = payload.get("updated_at")
            if not updated_at:
                continue
            age = (now - updated_at).total_seconds()
            if age > _UPLOAD_JOB_TTL_SECONDS and payload.get("status") in {"completed", "failed"}:
                stale_ids.append(upload_id)
        for upload_id in stale_ids:
            _upload_jobs.pop(upload_id, None)


def _set_upload_job(upload_id: str, **changes) -> None:
    with _upload_jobs_lock:
        payload = _upload_jobs.get(upload_id, {})
        payload.setdefault("upload_id", upload_id)
        payload.update(changes)
        payload["updated_at"] = datetime.now(timezone.utc)
        _upload_jobs[upload_id] = payload


def _get_upload_job(upload_id: str) -> Optional[dict]:
    with _upload_jobs_lock:
        payload = _upload_jobs.get(upload_id)
        return dict(payload) if payload else None


def _allow_insecure_oauth_transport() -> bool:
    """Return True only when explicitly enabled for local/dev use."""
    if not settings.GDRIVE_ALLOW_INSECURE_OAUTH:
        return False
    host = (urlparse(settings.JETSTREAM_BASE_URL).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or settings.DEBUG


def _db_session():
    """Return a live DB session factory after init_db() has run."""
    if database.SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not initialized.")
    return database.SessionLocal()


def _load_token() -> Optional[DriveUserToken]:
    """Return credentials from the process-memory token cache."""
    with _token_lock:
        payload = dict(_memory_token) if _memory_token else None
    if payload is None:
        return None
    record = DriveUserToken(account_email=payload["account_email"])
    record.access_token = payload.get("access_token")
    record.refresh_token = payload.get("refresh_token")
    record.token_expiry = payload.get("token_expiry")
    record.scopes = payload.get("scopes")
    return record


def _save_token(credentials: Credentials, email: str) -> None:
    """Save credentials in process memory only."""
    with _token_lock:
        global _memory_token
        _memory_token = {
            "account_email": email,
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_expiry": credentials.expiry,
            "scopes": " ".join(credentials.scopes or SCOPES),
            "updated_at": datetime.now(timezone.utc),
        }


def _delete_token(email: str) -> None:
    with _token_lock:
        global _memory_token
        _memory_token = None


def _credentials_from_record(record: DriveUserToken) -> Credentials:
    """Reconstruct a google.oauth2.credentials.Credentials from a DB record."""
    creds = Credentials(
        token=record.access_token,
        refresh_token=record.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GDRIVE_CLIENT_ID,
        client_secret=settings.GDRIVE_CLIENT_SECRET,
        scopes=(record.scopes or " ".join(SCOPES)).split(),
    )
    if record.token_expiry:
        creds.expiry = record.token_expiry
    return creds


def _get_authed_service(record: DriveUserToken):
    """Return an authenticated Drive service, refreshing token if needed."""
    creds = _credentials_from_record(record)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            _delete_token(record.account_email)
            raise HTTPException(
                status_code=401,
                detail="Google Drive authorization expired or revoked. Please reconnect.",
            )
        # Persist refreshed token
        _save_token(creds, record.account_email)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _handle_drive_auth_error(record: DriveUserToken, err: Exception) -> None:
    """Convert Drive auth failures into a reconnect-required response."""
    if isinstance(err, RefreshError):
        _delete_token(record.account_email)
        raise HTTPException(
            status_code=401,
            detail="Google Drive authorization expired or revoked. Please reconnect.",
        )
    if isinstance(err, HttpError) and getattr(err.resp, "status", None) in {401, 403}:
        _delete_token(record.account_email)
        raise HTTPException(
            status_code=401,
            detail="Google Drive authorization is no longer valid. Please reconnect.",
        )


def _get_account_email(service) -> str:
    """Fetch the authenticated user's email from the Drive about endpoint."""
    try:
        about = service.about().get(fields="user/emailAddress").execute()
        return about.get("user", {}).get("emailAddress", "unknown")
    except Exception:
        return "unknown"


# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.get("/auth/status", response_model=GDriveAuthStatus)
async def auth_status():
    """Return current auth connection status."""
    _cleanup_oauth_states()
    record = _load_token()
    if record:
        try:
            # Validate token by making a lightweight Drive call.
            service = _get_authed_service(record)
            about = service.about().get(fields="user/emailAddress").execute()
            valid_email = about.get("user", {}).get("emailAddress") or record.account_email
        except HTTPException as e:
            if e.status_code == 401:
                record = None
            else:
                raise
        except Exception as e:
            _handle_drive_auth_error(record, e)

    if record:
        return GDriveAuthStatus(
            connected=True,
            account_email=valid_email,
            scopes=record.scopes,
            client_configured=_client_configured(),
        )
    # Not connected — return auth URL if client is configured
    auth_url = None
    if _client_configured():
        auth_url = _create_auth_url()
    return GDriveAuthStatus(
        connected=False,
        client_configured=_client_configured(),
        auth_url=auth_url,
    )


@router.get("/auth/start")
async def auth_start():
    """Generate an OAuth authorization URL and redirect the browser to it."""
    if not _client_configured():
        raise HTTPException(
            status_code=400,
            detail="GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET must be set in config/environment.",
        )
    auth_url = _create_auth_url()
    return RedirectResponse(url=auth_url)


@router.get("/auth/callback")
async def auth_callback(code: str = Query(...), state: str = Query(...)):
    """OAuth callback — exchange code for tokens and persist."""
    # Validate state (CSRF check)
    with _oauth_state_lock:
        stored = _oauth_states.pop(state, None)
    if stored is None:
        raise HTTPException(status_code=400, detail="Invalid OAuth state. Please retry.")
    age = (datetime.now(timezone.utc) - stored["created"]).total_seconds()
    if age > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired. Please retry.")
    code_verifier = stored.get("code_verifier")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="OAuth verifier missing. Please retry sign-in.")

    # Only allow insecure OAuth transport when explicitly enabled for local/dev.
    if _allow_insecure_oauth_transport():
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    else:
        os.environ.pop("OAUTHLIB_INSECURE_TRANSPORT", None)

    flow = _build_flow(state=state, code_verifier=code_verifier)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {e}")
    creds = flow.credentials

    # Get the user's email
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    email = _get_account_email(service)

    _save_token(creds, email)

    # Redirect back to the gdrive page
    return RedirectResponse(url="/static/gdrive.html?connected=1")


@router.post("/auth/disconnect")
async def auth_disconnect():
    """Revoke and delete stored credentials."""
    record = _load_token()
    if not record:
        return {"status": "ok", "message": "Not connected."}
    email = record.account_email
    # Best-effort revoke
    try:
        import requests as _requests
        creds = _credentials_from_record(record)
        _requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": creds.token or creds.refresh_token},
            timeout=5,
        )
    except Exception:
        pass
    _delete_token(email)
    return {"status": "ok", "message": f"Disconnected {email}"}


# ── Browse endpoint ───────────────────────────────────────────────────────────

@router.get("/browse", response_model=GDriveBrowseResponse)
async def browse(
    folder_id: str = Query("root", description="Drive folder ID to list"),
    page_token: Optional[str] = Query(None),
):
    """List files and folders inside a Drive folder."""
    record = _load_token()
    if not record:
        raise HTTPException(status_code=401, detail="Not connected to Google Drive.")

    service = _get_authed_service(record)

    # Resolve folder name
    folder_name = "My Drive"
    if folder_id != "root":
        try:
            meta = service.files().get(fileId=folder_id, fields="name").execute()
            folder_name = meta.get("name", folder_id)
        except Exception:
            folder_name = folder_id

    # List children
    query = f"'{folder_id}' in parents and trashed = false"
    kwargs = dict(
        q=query,
        pageSize=100,
        fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)",
        orderBy="folder,name",
    )
    if page_token:
        kwargs["pageToken"] = page_token

    try:
        result = service.files().list(**kwargs).execute()
    except Exception as e:
        _handle_drive_auth_error(record, e)
        raise
    raw_items = result.get("files", [])

    items = []
    for f in raw_items:
        is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
        size_str = f.get("size")
        items.append(GDriveBrowseItem(
            id=f["id"],
            name=f["name"],
            mime_type=f.get("mimeType", ""),
            is_folder=is_folder,
            modified_time=f.get("modifiedTime"),
            size_bytes=int(size_str) if size_str else None,
            web_view_link=f.get("webViewLink"),
        ))

    return GDriveBrowseResponse(
        folder_id=folder_id,
        folder_name=folder_name,
        items=items,
        next_page_token=result.get("nextPageToken"),
    )


# ── Upload endpoint ───────────────────────────────────────────────────────────

@router.post("/upload", response_model=GDriveUploadResponse)
async def upload_file(req: GDriveUploadRequest):
    """Queue a local file upload to Google Drive and return a status handle."""
    record = _load_token()
    if not record:
        raise HTTPException(status_code=401, detail="Not connected to Google Drive.")

    # Validate local path
    local = Path(req.local_path).resolve()
    if not local.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {req.local_path}")
    if not local.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {req.local_path}")

    mime_type = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
    file_name = local.name
    upload_id = uuid.uuid4().hex
    _set_upload_job(
        upload_id,
        status="queued",
        progress_pct=0,
        file_name=file_name,
        file_id=None,
        web_view_link=None,
        error=None,
    )

    async def _run_upload_job() -> None:
        _set_upload_job(upload_id, status="uploading", progress_pct=0)
        try:
            service = _get_authed_service(record)

            if req.overwrite:
                q = f"name = '{file_name}' and '{req.folder_id}' in parents and trashed = false"
                existing = service.files().list(q=q, fields="files(id)").execute().get("files", [])
                for ef in existing:
                    service.files().delete(fileId=ef["id"]).execute()

            media = MediaFileUpload(
                str(local),
                mimetype=mime_type,
                chunksize=8 * 1024 * 1024,
                resumable=True,
            )
            request = service.files().create(
                body={"name": file_name, "parents": [req.folder_id]},
                media_body=media,
                fields="id, name, webViewLink",
            )

            uploaded = None
            while uploaded is None:
                status, uploaded = await asyncio.to_thread(request.next_chunk)
                if status is not None:
                    pct = max(0, min(99, int(status.progress() * 100)))
                    _set_upload_job(upload_id, status="uploading", progress_pct=pct)

            _set_upload_job(
                upload_id,
                status="completed",
                progress_pct=100,
                file_id=uploaded.get("id"),
                file_name=uploaded.get("name"),
                web_view_link=uploaded.get("webViewLink"),
                error=None,
            )
        except Exception as e:
            try:
                _handle_drive_auth_error(record, e)
            except HTTPException as auth_exc:
                _set_upload_job(upload_id, status="failed", error=auth_exc.detail)
                return
            _set_upload_job(upload_id, status="failed", error=str(e))

    asyncio.create_task(_run_upload_job())
    _cleanup_upload_jobs()

    return GDriveUploadResponse(
        success=True,
        upload_id=upload_id,
        status="queued",
        progress_pct=0,
        file_name=file_name,
    )


@router.get("/upload/status/{upload_id}", response_model=GDriveUploadStatusResponse)
async def upload_status(upload_id: str):
    """Return live status for a queued/running single-file upload."""
    payload = _get_upload_job(upload_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Upload status not found or expired.")
    return GDriveUploadStatusResponse(
        upload_id=payload.get("upload_id", upload_id),
        status=payload.get("status", "unknown"),
        progress_pct=int(payload.get("progress_pct") or 0),
        file_name=payload.get("file_name"),
        file_id=payload.get("file_id"),
        web_view_link=payload.get("web_view_link"),
        error=payload.get("error"),
    )


# ── Sync folder endpoint ──────────────────────────────────────────────────────

_MAX_RETRIES = 4
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _upload_one(
    creds: Credentials,
    local_file: Path,
    drive_folder_id: str,
    overwrite: bool,
    chunk_size: int,
) -> GDriveSyncFileResult:
    """Upload a single file using its own Drive service instance (thread-safe).
    Retries on transient HTTP errors with exponential backoff. Never raises.
    """
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        mime_type = mimetypes.guess_type(str(local_file))[0] or "application/octet-stream"
        file_name = local_file.name

        if overwrite:
            q = f"name = '{file_name}' and '{drive_folder_id}' in parents and trashed = false"
            existing = service.files().list(q=q, fields="files(id)").execute().get("files", [])
            for ef in existing:
                service.files().delete(fileId=ef["id"]).execute()

        media = MediaFileUpload(str(local_file), mimetype=mime_type,
                                chunksize=chunk_size, resumable=True)
        last_exc: Exception = RuntimeError("upload did not run")
        for attempt in range(_MAX_RETRIES):
            try:
                uploaded = service.files().create(
                    body={"name": file_name, "parents": [drive_folder_id]},
                    media_body=media,
                    fields="id, name, webViewLink",
                ).execute()
                return GDriveSyncFileResult(
                    local_path=str(local_file),
                    file_name=file_name,
                    success=True,
                    file_id=uploaded.get("id"),
                    web_view_link=uploaded.get("webViewLink"),
                )
            except HttpError as e:
                last_exc = e
                if e.resp.status in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                    wait = min(2 ** attempt + random.uniform(0, 1), 30)
                    time.sleep(wait)
                    continue
                break
            except Exception as e:
                last_exc = e
                break
        raise last_exc
    except Exception as e:
        return GDriveSyncFileResult(
            local_path=str(local_file),
            file_name=local_file.name,
            success=False,
            error=str(e),
        )


def _ensure_drive_folder(service, parent_id: str, name: str) -> str:
    """Get or create a subfolder in Drive; return its ID."""
    q = f"name = '{name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if results:
        return results[0]["id"]
    folder = service.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
        fields="id",
    ).execute()
    return folder["id"]


@router.post("/sync", response_model=GDriveSyncResponse)
async def sync_folder(req: GDriveSyncRequest):
    """Upload all files from a local folder to a Drive folder.

    Phase 1 (serial): Walk the directory tree and create any missing Drive
    sub-folders, collecting a flat list of (file, drive_folder_id) work items.

    Phase 2 (parallel): Upload all collected files concurrently, bounded by
    req.concurrency (default 4). Each worker builds its own Drive service
    instance to avoid httplib2 thread-safety issues.
    """
    record = _load_token()
    if not record:
        raise HTTPException(status_code=401, detail="Not connected to Google Drive.")

    local_root = Path(req.local_folder).resolve()
    if not local_root.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.local_folder}")
    if not local_root.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {req.local_folder}")

    # Refresh credentials once in the main thread; workers reuse the same creds object.
    creds = _credentials_from_record(record)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, record.account_email)
        except Exception as e:
            _handle_drive_auth_error(record, e)
            raise

    chunk_size = req.chunk_size_mb * 1024 * 1024

    # ── Phase 1: collect all upload tasks (serial, fast – no large data transfer) ──
    folder_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    upload_tasks: list[tuple[Path, str]] = []  # (local_file, drive_folder_id)

    def _collect_dir(local_dir: Path, drive_folder_id: str) -> None:
        for entry in sorted(local_dir.iterdir()):
            if entry.is_file():
                upload_tasks.append((entry, drive_folder_id))
            elif entry.is_dir() and req.recursive:
                sub_id = _ensure_drive_folder(folder_service, drive_folder_id, entry.name)
                _collect_dir(entry, sub_id)

    try:
        _collect_dir(local_root, req.drive_folder_id)
    except Exception as e:
        _handle_drive_auth_error(record, e)
        raise

    # ── Phase 2: upload files in parallel ──
    semaphore = asyncio.Semaphore(req.concurrency)

    async def _bounded_upload(local_file: Path, folder_id: str) -> GDriveSyncFileResult:
        async with semaphore:
            return await asyncio.to_thread(
                _upload_one, creds, local_file, folder_id, req.overwrite, chunk_size
            )

    results = await asyncio.gather(*[
        _bounded_upload(f, fid) for f, fid in upload_tasks
    ])

    succeeded = sum(1 for r in results if r.success)
    return GDriveSyncResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        files=list(results),
    )
