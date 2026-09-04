"""Dataset Creator: GCS media scanning, grouping engine, and catalog schemas.

Ported from the OASIS dataset-creator feature. The export payload shape is
intentionally frozen for compatibility with downstream OASIS tooling.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from .config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg"}

IMAGE_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "gif": "image/gif",
}

# User-supplied regexes are compiled server-side; cap length to blunt ReDoS.
MAX_REGEX_LENGTH = 200


# ── Schemas ──────────────────────────────────────────────────────────────────

class GroupByMode(str, Enum):
    none = "none"
    filename_token = "filename_token"
    folder_segment = "folder_segment"
    regex = "regex"
    manual = "manual"


class CatalogFormat(str, Enum):
    flat = "flat"
    grouped = "grouped"
    both = "both"


class SiteInstanceMode(str, Enum):
    none = "none"
    manual = "manual"
    threshold = "threshold"
    folder_boundary = "folder_boundary"
    filename_pattern = "filename_pattern"


class DatasetScanRequest(BaseModel):
    gcs_prefix: str = Field(..., description="gs://bucket/path/to/data/")
    include_images: bool = True
    include_videos: bool = True
    extensions: Optional[List[str]] = Field(
        None, description="Optional extension allowlist (example: ['.jpg', '.mp4'])."
    )
    filename_filter: Optional[str] = Field(
        None, description="Glob or substring filter matched against filename."
    )
    folder_filter: Optional[str] = Field(
        None, description="Optional substring filter matched against full blob path."
    )
    ignore_folder_names: List[str] = Field(
        default_factory=list,
        description="Case-insensitive folder names to exclude below the selected prefix.",
    )
    max_path_depth: Optional[int] = Field(None, ge=0, le=50)
    max_results: int = Field(
        0, ge=0, description="Maximum results to keep. Use 0 for the server default cap."
    )

    @field_validator("gcs_prefix")
    @classmethod
    def prefix_must_be_gcs(cls, v: str) -> str:
        if not v.startswith("gs://"):
            raise ValueError("Path must start with gs://")
        return v.rstrip("/") + "/"

    @field_validator("ignore_folder_names", mode="before")
    @classmethod
    def normalize_ignore_folder_names(cls, value) -> List[str]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, list):
            items = value
        else:
            raise ValueError("ignore_folder_names must be a list of folder names")

        normalized: List[str] = []
        seen: set = set()
        for item in items:
            name = str(item or "").strip()
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            normalized.append(name)
        return normalized


class DatasetCatalogRequest(DatasetScanRequest):
    catalog_format: CatalogFormat = CatalogFormat.both
    group_by_mode: GroupByMode = GroupByMode.filename_token
    filename_delimiter: str = "_"
    filename_token_count: int = Field(3, ge=1, le=10)
    folder_segment_index: int = Field(0, ge=0, le=50)
    regex_pattern: Optional[str] = Field(None, max_length=MAX_REGEX_LENGTH)
    regex_group_index: int = Field(1, ge=0, le=20)
    manual_overrides: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Manual group mapping where key=group and value=list of glob/substring patterns.",
    )
    selected_groups: List[str] = Field(
        default_factory=list, description="Optional allowlist of group keys to include."
    )

    site_instance_mode: SiteInstanceMode = SiteInstanceMode.none
    site_instance_threshold: int = Field(25, ge=1, le=1000000)
    site_instance_pattern: Optional[str] = Field(None, max_length=MAX_REGEX_LENGTH)
    site_instance_folder_segment_index: int = Field(0, ge=0, le=50)
    manual_site_groups: List[str] = Field(default_factory=list)


class DatasetScanResponse(BaseModel):
    gcs_prefix: str
    total_matched: int
    total_returned: int
    truncated: bool
    extensions_used: List[str]
    items: List[str]


class DatasetGroupSummary(BaseModel):
    group_key: str
    count: int
    is_site_instance: bool


class DatasetCatalogResponse(BaseModel):
    gcs_prefix: str
    flat_instances: List[str]
    grouped_instances: Dict[str, List[str]]
    site_instances: Dict[str, List[str]]
    groups: List[DatasetGroupSummary]
    catalog_format: CatalogFormat
    metadata: Dict[str, Any]


class DatasetViewerSessionResponse(BaseModel):
    token: str
    viewer_url: str


class DatasetCatalogSaveRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    catalog: DatasetCatalogResponse


class DatasetCatalogRecordSummary(BaseModel):
    id: str
    name: str
    created_at: Optional[str] = None
    gcs_prefix: str = ""
    total_items: int = 0
    total_groups: int = 0


class DatasetCatalogRecord(DatasetCatalogRecordSummary):
    catalog: DatasetCatalogResponse


@dataclass
class CatalogBuildResult:
    response: DatasetCatalogResponse
    selected_extensions: List[str]


# ── URI helpers ──────────────────────────────────────────────────────────────

def parse_gcs_uri(uri: str) -> Tuple[str, str]:
    """Split ``gs://bucket/prefix`` into ``("bucket", "prefix")``."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {uri!r}")
    without_scheme = uri[5:]
    slash = without_scheme.find("/")
    if slash == -1:
        return without_scheme, ""
    return without_scheme[:slash], without_scheme[slash + 1:]


def uri_path(uri: str) -> str:
    if not uri.startswith("gs://"):
        return uri
    without_scheme = uri[5:]
    slash = without_scheme.find("/")
    return "" if slash == -1 else without_scheme[slash + 1:]


def allowed_buckets() -> Optional[set]:
    """Return the bucket allowlist, or None when any bucket is permitted."""
    raw = (settings.DATASET_CREATOR_ALLOWED_BUCKETS or "").strip()
    if raw == "*":
        return None
    if raw:
        return {b.strip() for b in raw.split(",") if b.strip()}
    return {settings.GCS_BUCKET_NAME} if settings.GCS_BUCKET_NAME else None


def is_bucket_allowed(bucket: str) -> bool:
    allowed = allowed_buckets()
    return allowed is None or bucket in allowed


def build_gcs_uris(gcs_prefix: str, blob_names: List[str]) -> List[str]:
    bucket, prefix = parse_gcs_uri(gcs_prefix)
    normalized_prefix = prefix.rstrip("/")

    uris: List[str] = []
    for blob_name in blob_names:
        if blob_name.startswith("gs://"):
            uris.append(blob_name)
            continue
        if normalized_prefix and blob_name.startswith(normalized_prefix + "/"):
            uris.append(f"gs://{bucket}/{blob_name}")
        else:
            joined = f"{normalized_prefix}/{blob_name}".strip("/")
            uris.append(f"gs://{bucket}/{joined}")
    return uris


def resolve_extensions(
    include_images: bool,
    include_videos: bool,
    extensions: Optional[List[str]],
) -> List[str]:
    if extensions:
        normalized = {
            e.lower() if e.startswith(".") else f".{e.lower()}"
            for e in extensions
            if e and e.strip()
        }
        return sorted(normalized)

    resolved = set()
    if include_images:
        resolved |= IMAGE_EXTENSIONS
    if include_videos:
        resolved |= VIDEO_EXTENSIONS
    return sorted(resolved)


def compile_user_regex(pattern: str) -> Optional[re.Pattern]:
    if not pattern or len(pattern) > MAX_REGEX_LENGTH:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


# ── GCS scanning ─────────────────────────────────────────────────────────────

def validate_prefix(client, gcs_uri: str) -> bool:
    """Return True when the bucket is reachable with the current credentials."""
    bucket_name, prefix = parse_gcs_uri(gcs_uri)
    try:
        list(client.bucket(bucket_name).list_blobs(prefix=prefix, max_results=1))
        return True
    except Exception as exc:
        logger.error("GCS validation failed for %s: %s", gcs_uri, exc)
        return False


def list_media_blobs(
    client,
    gcs_uri: str,
    *,
    include_images: bool = True,
    include_videos: bool = False,
    extensions: Optional[List[str]] = None,
    filename_filter: Optional[str] = None,
    folder_filter: Optional[str] = None,
    ignore_folder_names: Optional[List[str]] = None,
    max_path_depth: Optional[int] = None,
    scan_ceiling: Optional[int] = None,
) -> Tuple[List[str], bool]:
    """Return (blob names matching the filters, hit_ceiling)."""
    bucket_name, prefix = parse_gcs_uri(gcs_uri)
    blobs = client.bucket(bucket_name).list_blobs(prefix=prefix)

    ignored_names = {
        name.casefold() for name in (ignore_folder_names or []) if str(name).strip()
    }

    if extensions:
        ext_allow = {
            e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions
        }
    else:
        ext_allow = set()
        if include_images:
            ext_allow |= IMAGE_EXTENSIONS
        if include_videos:
            ext_allow |= VIDEO_EXTENSIONS

    if filename_filter:
        f = filename_filter.strip()
        if f and not any(c in f for c in ("*", "?", "[")):
            f = f"*{f}*"
        filename_filter = f

    results: List[str] = []
    hit_ceiling = False
    for b in blobs:
        if b.name.endswith("/"):
            continue

        relative = b.name[len(prefix):] if prefix and b.name.startswith(prefix) else b.name
        segments = [s for s in relative.split("/") if s]
        folder_segments = segments[:-1] if segments else []

        if ignored_names and any(s.casefold() in ignored_names for s in folder_segments):
            continue
        if max_path_depth is not None and len(folder_segments) > max_path_depth:
            continue
        if folder_filter and folder_filter.lower() not in b.name.lower():
            continue

        fname = os.path.basename(b.name)
        ext = os.path.splitext(fname)[1].lower()
        if ext_allow and ext not in ext_allow:
            continue
        if filename_filter and not fnmatch.fnmatch(fname.lower(), filename_filter.lower()):
            continue

        results.append(b.name)
        if scan_ceiling and len(results) >= scan_ceiling:
            hit_ceiling = True
            break

    return results, hit_ceiling


# ── Grouping engine ──────────────────────────────────────────────────────────

def build_catalog(req: DatasetCatalogRequest, uris: List[str]) -> CatalogBuildResult:
    groups = _group_instances(req, uris)

    if req.selected_groups:
        allow = set(req.selected_groups)
        groups = {k: v for k, v in groups.items() if k in allow}

    flat_instances = sorted([u for values in groups.values() for u in values])
    grouped_instances = {k: sorted(v) for k, v in sorted(groups.items(), key=lambda x: x[0])}

    site_instances = _derive_site_instances(req, grouped_instances)
    summaries = [
        DatasetGroupSummary(
            group_key=key,
            count=len(values),
            is_site_instance=key in site_instances,
        )
        for key, values in grouped_instances.items()
    ]

    response = DatasetCatalogResponse(
        gcs_prefix=req.gcs_prefix,
        flat_instances=flat_instances,
        grouped_instances=grouped_instances,
        site_instances=site_instances,
        groups=summaries,
        catalog_format=req.catalog_format,
        metadata={
            "group_by_mode": req.group_by_mode.value,
            "site_instance_mode": req.site_instance_mode.value,
            "total_items": len(flat_instances),
            "total_groups": len(grouped_instances),
        },
    )
    selected_extensions = resolve_extensions(
        req.include_images, req.include_videos, req.extensions
    )
    return CatalogBuildResult(response=response, selected_extensions=selected_extensions)


def to_export_payload(catalog: DatasetCatalogResponse) -> Dict[str, Any]:
    """Frozen export contract shared with OASIS downstream tooling."""
    if catalog.catalog_format == CatalogFormat.flat:
        return {"instances": catalog.flat_instances}

    if catalog.catalog_format == CatalogFormat.grouped:
        return {"instances": catalog.grouped_instances}

    payload: Dict[str, Any] = {
        "instances": catalog.flat_instances,
        "instances_grouped": catalog.grouped_instances,
    }
    if catalog.site_instances:
        payload["site_instances"] = catalog.site_instances
    return payload


def _group_instances(req: DatasetCatalogRequest, uris: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    compiled = (
        compile_user_regex(req.regex_pattern)
        if req.group_by_mode == GroupByMode.regex and req.regex_pattern
        else None
    )
    for uri in uris:
        key = _derive_group_key(req, uri, compiled)
        grouped.setdefault(key, []).append(uri)
    return grouped


def _derive_group_key(
    req: DatasetCatalogRequest,
    uri: str,
    compiled_regex: Optional[re.Pattern] = None,
) -> str:
    path = uri_path(uri)
    fname = os.path.basename(path)
    stem, _ = os.path.splitext(fname)

    if req.group_by_mode == GroupByMode.filename_token:
        parts = [p for p in stem.split(req.filename_delimiter) if p]
        if not parts:
            return "ungrouped"
        return req.filename_delimiter.join(parts[: req.filename_token_count])

    if req.group_by_mode == GroupByMode.folder_segment:
        segments = [s for s in os.path.dirname(path).split("/") if s]
        if not segments:
            return "root"
        idx = min(req.folder_segment_index, len(segments) - 1)
        return segments[idx]

    if req.group_by_mode == GroupByMode.regex:
        if compiled_regex is None:
            return "unmatched"
        m = compiled_regex.search(fname)
        if m:
            try:
                return str(m.group(req.regex_group_index))
            except IndexError:
                return m.group(0)
        return "unmatched"

    if req.group_by_mode == GroupByMode.manual and req.manual_overrides:
        lower_uri = uri.lower()
        lower_fname = fname.lower()
        for group_key, patterns in req.manual_overrides.items():
            for pattern in patterns:
                p = (pattern or "").strip()
                if not p:
                    continue
                pl = p.lower()
                if any(ch in pl for ch in ["*", "?", "["]):
                    if fnmatch.fnmatch(lower_fname, pl) or fnmatch.fnmatch(lower_uri, pl):
                        return group_key
                elif pl in lower_fname or pl in lower_uri:
                    return group_key
        return "unmapped"

    return "all"


def _derive_site_instances(
    req: DatasetCatalogRequest,
    grouped: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    if req.site_instance_mode == SiteInstanceMode.none:
        return {}

    if req.site_instance_mode == SiteInstanceMode.manual:
        allow = set(req.manual_site_groups)
        return {k: v for k, v in grouped.items() if k in allow}

    if req.site_instance_mode == SiteInstanceMode.threshold:
        return {k: v for k, v in grouped.items() if len(v) >= req.site_instance_threshold}

    if req.site_instance_mode == SiteInstanceMode.folder_boundary:
        out: Dict[str, List[str]] = {}
        for group_key, values in grouped.items():
            if not values:
                continue
            segments = [s for s in os.path.dirname(uri_path(values[0])).split("/") if s]
            if not segments:
                continue
            idx = min(req.site_instance_folder_segment_index, len(segments) - 1)
            if segments[idx] == group_key:
                out[group_key] = values
        return out

    if req.site_instance_mode == SiteInstanceMode.filename_pattern:
        rx = compile_user_regex(req.site_instance_pattern or "")
        if rx is None:
            return {}
        out = {}
        for group_key, values in grouped.items():
            if any(rx.search(os.path.basename(uri_path(v))) for v in values):
                out[group_key] = values
        return out

    return {}


# ── Viewer sessions (in-process, TTL bounded) ────────────────────────────────

_VIEWER_SESSIONS: Dict[str, Dict[str, Any]] = {}
_MAX_VIEWER_SESSIONS = 50


def create_viewer_session(catalog_payload: Dict[str, Any]) -> str:
    _cleanup_sessions()
    if len(_VIEWER_SESSIONS) >= _MAX_VIEWER_SESSIONS:
        oldest = min(_VIEWER_SESSIONS, key=lambda t: _VIEWER_SESSIONS[t]["created_at"])
        _VIEWER_SESSIONS.pop(oldest, None)

    token = uuid.uuid4().hex
    _VIEWER_SESSIONS[token] = {"payload": catalog_payload, "created_at": time.time()}
    return token


def get_viewer_session(token: str) -> Optional[Dict[str, Any]]:
    _cleanup_sessions()
    rec = _VIEWER_SESSIONS.get(token)
    if not rec:
        return None
    payload = rec.get("payload")
    return payload if isinstance(payload, dict) else None


def _cleanup_sessions() -> None:
    ttl = settings.DATASET_CREATOR_VIEWER_TTL_SECONDS
    now = time.time()
    expired = [
        token
        for token, record in _VIEWER_SESSIONS.items()
        if now - float(record.get("created_at", 0.0)) > ttl
    ]
    for token in expired:
        _VIEWER_SESSIONS.pop(token, None)
