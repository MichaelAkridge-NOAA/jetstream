"""Dataset Creator API - build and save GCS media catalogs."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import DatasetCatalog, get_db
from ..services_dataset import (
    IMAGE_MEDIA_TYPES,
    DatasetCatalogRecord,
    DatasetCatalogRecordSummary,
    DatasetCatalogRequest,
    DatasetCatalogResponse,
    DatasetCatalogSaveRequest,
    DatasetScanRequest,
    DatasetScanResponse,
    DatasetViewerSessionResponse,
    build_catalog,
    build_gcs_uris,
    create_viewer_session,
    get_viewer_session,
    is_bucket_allowed,
    list_media_blobs,
    parse_gcs_uri,
    resolve_extensions,
    to_export_payload,
    validate_prefix,
)
from .cloud_analyzer import get_storage_client

router = APIRouter()


def _require_allowed_bucket(gcs_uri: str) -> None:
    try:
        bucket, _ = parse_gcs_uri(gcs_uri)
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected gs:// URI")
    if not is_bucket_allowed(bucket):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Bucket '{bucket}' is not allowed. Set DATASET_CREATOR_ALLOWED_BUCKETS "
                "in your .env to a comma-separated list of buckets, or to * to allow any."
            ),
        )


def _effective_limit(requested: int) -> int:
    ceiling = settings.DATASET_CREATOR_MAX_SCAN_RESULTS
    if requested <= 0:
        return ceiling
    return min(requested, ceiling)


def _scan(req: DatasetScanRequest) -> tuple[List[str], List[str], bool]:
    """Return (blob names, extensions used, truncated)."""
    selected_exts = resolve_extensions(req.include_images, req.include_videos, req.extensions)
    if not selected_exts:
        raise HTTPException(
            status_code=422, detail="At least one media type or extension must be selected"
        )

    _require_allowed_bucket(req.gcs_prefix)
    client = get_storage_client()
    if not validate_prefix(client, req.gcs_prefix):
        raise HTTPException(status_code=422, detail=f"Cannot access input prefix: {req.gcs_prefix}")

    limit = _effective_limit(req.max_results)
    matches, hit_ceiling = list_media_blobs(
        client,
        req.gcs_prefix,
        include_images=req.include_images,
        include_videos=req.include_videos,
        extensions=selected_exts,
        filename_filter=req.filename_filter,
        folder_filter=req.folder_filter,
        ignore_folder_names=req.ignore_folder_names,
        max_path_depth=req.max_path_depth,
        scan_ceiling=limit,
    )
    return matches, selected_exts, hit_ceiling


def _json_attachment(payload: dict, filename: str) -> Response:
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


@router.post("/scan", response_model=DatasetScanResponse)
async def scan_dataset(req: DatasetScanRequest):
    """Scan a GCS prefix and return matching media URIs."""
    matches, selected_exts, truncated = _scan(req)
    return DatasetScanResponse(
        gcs_prefix=req.gcs_prefix,
        total_matched=len(matches),
        total_returned=len(matches),
        truncated=truncated,
        extensions_used=selected_exts,
        items=build_gcs_uris(req.gcs_prefix, matches),
    )


@router.post("/catalog", response_model=DatasetCatalogResponse)
async def build_dataset_catalog(req: DatasetCatalogRequest):
    """Scan and group a GCS prefix into a dataset catalog."""
    matches, selected_exts, truncated = _scan(req)
    result = build_catalog(req, build_gcs_uris(req.gcs_prefix, matches))

    catalog = result.response
    catalog.metadata["extensions_used"] = selected_exts
    catalog.metadata["truncated"] = truncated
    catalog.metadata["total_matched"] = len(matches)
    catalog.metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
    return catalog


@router.post("/export")
async def export_dataset_catalog(payload: DatasetCatalogResponse):
    """Download an unsaved catalog as JSON."""
    return _json_attachment(to_export_payload(payload), f"dataset_catalog_{_timestamp()}.json")


@router.post("/viewer-session", response_model=DatasetViewerSessionResponse)
async def create_catalog_viewer_session(payload: DatasetCatalogResponse):
    """Stash a catalog server-side and return a short-lived viewer token."""
    token = create_viewer_session(payload.model_dump(mode="json"))
    return DatasetViewerSessionResponse(
        token=token,
        viewer_url=f"/static/dataset-catalog-viewer.html?token={token}",
    )


@router.get("/viewer-session/{token}")
async def read_catalog_viewer_session(token: str):
    """Fetch the catalog payload behind a viewer token."""
    payload = get_viewer_session(token)
    if not payload:
        raise HTTPException(status_code=404, detail="Catalog viewer session not found or expired")
    return payload


@router.post("/catalogs", response_model=DatasetCatalogRecordSummary)
async def save_catalog(req: DatasetCatalogSaveRequest, db: Session = Depends(get_db)):
    """Persist a catalog to the database."""
    now = datetime.now(timezone.utc)
    name = (req.name or f"catalog-{now.strftime('%Y%m%d-%H%M%S')}").strip()

    record = DatasetCatalog(
        catalog_id=uuid.uuid4().hex,
        name=name,
        gcs_prefix=req.catalog.gcs_prefix,
        catalog_format=req.catalog.catalog_format.value,
        payload=req.catalog.model_dump(mode="json"),
        total_items=len(req.catalog.flat_instances),
        total_groups=len(req.catalog.grouped_instances),
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return DatasetCatalogRecordSummary(**record.to_dict())


@router.get("/catalogs", response_model=List[DatasetCatalogRecordSummary])
async def list_catalogs(limit: int = 50, db: Session = Depends(get_db)):
    """List saved catalogs, newest first."""
    rows = (
        db.query(DatasetCatalog)
        .order_by(DatasetCatalog.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [DatasetCatalogRecordSummary(**row.to_dict()) for row in rows]


def _get_record(catalog_id: str, db: Session) -> DatasetCatalog:
    record = db.query(DatasetCatalog).filter(DatasetCatalog.catalog_id == catalog_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Catalog not found")
    return record


@router.get("/catalogs/{catalog_id}", response_model=DatasetCatalogRecord)
async def get_catalog(catalog_id: str, db: Session = Depends(get_db)):
    """Fetch a saved catalog including its full payload."""
    return DatasetCatalogRecord(**_get_record(catalog_id, db).to_dict(include_payload=True))


@router.delete("/catalogs/{catalog_id}")
async def delete_catalog(catalog_id: str, db: Session = Depends(get_db)):
    """Delete a saved catalog."""
    record = _get_record(catalog_id, db)
    db.delete(record)
    db.commit()
    return {"deleted": True, "catalog_id": catalog_id}


@router.post("/catalogs/{catalog_id}/viewer-session", response_model=DatasetViewerSessionResponse)
async def create_saved_catalog_viewer_session(catalog_id: str, db: Session = Depends(get_db)):
    """Create a viewer token for a saved catalog."""
    record = _get_record(catalog_id, db)
    token = create_viewer_session(record.payload)
    return DatasetViewerSessionResponse(
        token=token,
        viewer_url=f"/static/dataset-catalog-viewer.html?token={token}",
    )


@router.get("/catalogs/{catalog_id}/export")
async def export_saved_catalog(
    catalog_id: str,
    catalog_format: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Download a saved catalog as JSON in flat, grouped, or both formats."""
    record = _get_record(catalog_id, db)
    catalog = DatasetCatalogResponse.model_validate(record.payload)

    if catalog_format:
        normalized = catalog_format.strip().lower()
        if normalized not in {"flat", "grouped", "both"}:
            raise HTTPException(
                status_code=400, detail="catalog_format must be flat, grouped, or both"
            )
        catalog.catalog_format = normalized

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in record.name)
    return _json_attachment(to_export_payload(catalog), f"{safe_name}_{_timestamp()}.json")


@router.get("/proxy")
async def proxy_dataset_image(gcs_uri: str):
    """Stream a GCS image for catalog viewer previews.

    Restricted to the configured bucket allowlist and known image extensions.
    """
    if not gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Expected gs:// URI")

    ext = gcs_uri.rsplit(".", 1)[-1].lower() if "." in gcs_uri else ""
    media_type = IMAGE_MEDIA_TYPES.get(ext)
    if not media_type:
        raise HTTPException(status_code=415, detail="Only image previews are supported")

    _require_allowed_bucket(gcs_uri)

    client = get_storage_client()
    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    if not blob_name:
        raise HTTPException(status_code=400, detail="Expected gs://bucket/path/to/image")

    blob = client.bucket(bucket_name).blob(blob_name)
    try:
        blob.reload()
    except Exception as exc:
        from google.cloud.exceptions import NotFound  # type: ignore

        if isinstance(exc, NotFound):
            raise HTTPException(status_code=404, detail="Image not found in GCS")
        raise HTTPException(status_code=502, detail=f"GCS error: {exc}")

    chunk_size = 256 * 1024

    def _stream() -> Iterator[bytes]:
        with blob.open("rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    headers = {"Cache-Control": "private, max-age=3600"}
    if blob.size:
        headers["Content-Length"] = str(blob.size)
    return StreamingResponse(_stream(), media_type=media_type, headers=headers)
