"""Core services for upload management and folder analysis."""

import os
import re
import subprocess
import threading
import uuid
import random
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable
from datetime import datetime, timezone
from collections import defaultdict
import asyncio
import time
import logging

from .config import settings
from .database import UploadJob, FolderStats, get_db
from .models import JobStatus

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = [
    re.compile(
        r"(?i)\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|password|secret|authorization)\b\s*[:=]\s*([^\s\"']+|\"[^\"]*\"|'[^']*')"
    ),
    re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[^\s]+"),
    re.compile(r"(?i)\b(GOOGLE_APPLICATION_CREDENTIALS|GDRIVE_CLIENT_SECRET)\s*=\s*([^\s\"']+|\"[^\"]*\"|'[^']*')"),
    re.compile(r"(?i)([?&](?:X-Goog-Signature|X-Goog-Credential|X-Goog-Security-Token|Signature|AWSAccessKeyId)=)[^&\s]+"),
]


def redact_sensitive_text(value: object) -> str:
    """Redact common credential material before persistence or display."""
    text = "" if value is None else str(value)
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.pattern.startswith("(?i)\\bAuthorization"):
            text = pattern.sub("Authorization: Bearer [REDACTED]", text)
        elif "X-Goog" in pattern.pattern or "AWSAccessKeyId" in pattern.pattern:
            text = pattern.sub(r"\1[REDACTED]", text)
        else:
            text = pattern.sub(r"\1=[REDACTED]", text)
    return text

# Random word lists for friendly names
ADJECTIVES = [
    'swift', 'brave', 'calm', 'bold', 'keen', 'wise', 'cool', 'fast',
    'bright', 'clear', 'crisp', 'eager', 'fair', 'fine', 'glad', 'good',
    'happy', 'jolly', 'kind', 'light', 'merry', 'neat', 'nice', 'quick',
    'safe', 'true', 'warm', 'wild', 'witty', 'zesty'
]

NOUNS = [
    # Big cats
    'lion', 'tiger', 'leopard', 'jaguar', 'cheetah', 'cougar', 'panther',
    'lynx', 'bobcat', 'ocelot', 'caracal', 'serval', 'puma', 'margay',
    # Domestic & exotic breeds
    'siamese', 'persian', 'bengal', 'sphynx', 'ragdoll', 'abyssinian',
    'birman', 'burmese', 'manx', 'savannah', 'tonkinese', 'korat',
    'chartreux', 'peterbald', 'toyger', 'ocicat', 'singapura', 'somali',
    'balinese', 'himalayan', 'munchkin', 'nebelung', 'pixiebob', 'lykoi',
    # Wild cats
    'wildcat', 'sandcat', 'junglecat', 'pallas', 'margay', 'kodkod',
    'oncilla', 'clouded', 'snowleopard', 'fishingcat', 'rustyspot',
    # Extinct & mythical cats
    'sabertooth', 'sphinx', 'carbuncle', 'coeurl', 'thundercat',
    'potato', 'tacocat'
]

def generate_friendly_job_name(source_path: str = None) -> str:
    """Generate a user-friendly job name.
    
    Format: upload-YYYY-MM-DD-HHmmss-adjective-noun-xxxx
    Example: upload-2026-01-26-143052-swift-falcon-a3d9
    """
    timestamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
    adjective = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    short_id = uuid.uuid4().hex[:4]
    
    friendly_name = f"upload-{timestamp}-{adjective}-{noun}-{short_id}"
    
    return friendly_name

class FileFilter:
    """Handle file filtering based on patterns."""
    
    def __init__(self, include_patterns: List[str] = None, 
                 exclude_patterns: List[str] = None,
                 exclude_folders: List[str] = None):
        self.include_patterns = include_patterns or settings.INCLUDE_PATTERNS
        self.exclude_patterns = exclude_patterns or settings.EXCLUDE_PATTERNS
        # Use set for O(1) folder exclusion lookups
        self.exclude_folders = set(exclude_folders or settings.EXCLUDE_FOLDERS)
        
        # Consolidate regex patterns into single compiled expressions for performance
        if self.exclude_patterns:
            exclude_combined = "|".join(f"(?:{self._glob_to_regex(p)})" for p in self.exclude_patterns)
            self.exclude_regex = re.compile(exclude_combined, re.IGNORECASE)
        else:
            self.exclude_regex = None

        if self.include_patterns:
            include_combined = "|".join(f"(?:{self._glob_to_regex(p)})" for p in self.include_patterns)
            self.include_regex = re.compile(include_combined, re.IGNORECASE)
        else:
            self.include_regex = None
    
    def _glob_to_regex(self, pattern: str) -> str:
        """Convert a glob pattern to regex, or return as-is if already regex."""
        # Detect if pattern is already a regex (has regex-specific syntax)
        # These chars indicate it's likely already a regex: | ( ) ^ $ \ { } [ ] + ?
        regex_indicators = ['|', '(', ')', '^', '$', '\\', '{', '}', '[', ']', '+', '(?']
        is_likely_regex = any(indicator in pattern for indicator in regex_indicators)
        
        if is_likely_regex:
            # Already a regex pattern - pass through unchanged
            return pattern
        elif pattern.startswith('*.'):
            # Simple extension match: *.tmp -> .*\.tmp$
            ext = pattern[2:]
            return r'.*\.' + re.escape(ext) + r'$'
        elif pattern.startswith('*'):
            # Ends with pattern: *something -> .*something$
            return r'.*' + re.escape(pattern[1:]) + r'$'
        elif pattern.endswith('*'):
            # Starts with pattern: something* -> ^something.*
            return r'^' + re.escape(pattern[:-1]) + r'.*'
        elif '*' in pattern:
            # General glob: convert * to .*
            result = re.escape(pattern)
            result = result.replace(r'\*', '.*')
            return result
        else:
            # Exact filename match (e.g., Thumbs.db)
            return re.escape(pattern)
    
    def should_include_file(self, filepath: str, filename: str = None) -> bool:
        """Check if file should be included based on patterns.
        
        Optional filename parameter avoids redundant os.path.basename calls.
        """
        if filename is None:
            filename = os.path.basename(filepath)
        
        # Check exclude patterns first (consolidated regex)
        if self.exclude_regex and self.exclude_regex.match(filename):
            return False

        # Check include patterns (consolidated regex)
        if not self.include_regex:
            return True
        
        return bool(self.include_regex.match(filename))
    
    def should_exclude_folder(self, folder_name: str) -> bool:
        """Check if folder should be excluded."""
        return folder_name in self.exclude_folders

class FolderAnalyzer:
    """Analyze folder structure and calculate statistics."""
    
    def __init__(self, file_filter: FileFilter = None):
        self.file_filter = file_filter or FileFilter()
        self.scan_start_time = None
        self.file_count = 0
        self.folder_count = 0
    
    def get_tree_size_fast(self, path: str) -> int:
        """Fast tree size calculation using os.scandir (much faster than os.walk).
        
        This method is significantly faster for large directories because:
        1. os.scandir returns DirEntry objects with cached stat info
        2. Avoids redundant stat() calls
        3. More efficient than os.walk for size calculation
        """
        total = 0
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            # Skip excluded folders
                            if not self.file_filter.should_exclude_folder(entry.name):
                                total += self.get_tree_size_fast(entry.path)
                        else:
                            # Check if file should be included
                            if self.file_filter.should_include_file(entry.path, filename=entry.name):
                                total += entry.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return total
    
    def quick_folder_check(self, path: str) -> Tuple[int, int]:
        """Quick check to count immediate files and subfolders.
        Returns (file_count, subfolder_count) for performance decision.
        """
        file_count = 0
        folder_count = 0
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not self.file_filter.should_exclude_folder(entry.name):
                                folder_count += 1
                        else:
                            if self.file_filter.should_include_file(entry.path, filename=entry.name):
                                file_count += 1
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            pass
        return file_count, folder_count
    
    def analyze(self, path: str, recursive: bool = True, folder_only_mode: bool = False) -> Dict:
        """Analyze folder and return statistics.
        
        Args:
            path: Path to analyze
            recursive: Whether to recurse into subdirectories
            folder_only_mode: If True, only analyze folder sizes without detailed file enumeration.
                             This is much faster for large folders.
        
        Returns:
            Dict with folder statistics
        """
        self.scan_start_time = time.time()
        self.file_count = 0
        self.folder_count = 0
        
        stats = {
            'path': path,
            'total_files': 0,
            'total_size_bytes': 0,
            'file_types': defaultdict(int),
            'subfolder_count': 0,
            'subfolders': [],
            'preview_files': [],
            'scan_mode': 'detailed',
            'scan_duration': 0
        }
        
        if not os.path.exists(path):
            raise ValueError(f"Path does not exist: {path}")
        
        # Quick check to determine if we should use folder-only mode
        if not folder_only_mode and settings.ENABLE_FAST_SCAN:
            file_count, folder_count = self.quick_folder_check(path)
            
            # Switch to folder-only mode if directory is too large
            if (folder_count > settings.MAX_SUBFOLDERS_FOR_DETAILED_SCAN or 
                file_count > settings.MAX_FILES_FOR_DETAILED_SCAN):
                logger.info(f"Large directory detected ({folder_count} folders, {file_count} files at root). Switching to fast folder-only mode.")
                folder_only_mode = True
                stats['scan_mode'] = 'folder_only'
        
        if folder_only_mode:
            # Fast mode: Just calculate sizes per folder without detailed enumeration
            return self._analyze_folder_only(path, stats, recursive)
        
        # Detailed mode: Full file enumeration (for smaller folders)
        return self._analyze_detailed(path, stats, recursive)
    
    def _analyze_folder_only(self, path: str, stats: Dict, recursive: bool) -> Dict:
        """Fast folder-only analysis mode for large directories."""
        try:
            # Get immediate subfolders
            subfolders = []
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if not self.file_filter.should_exclude_folder(entry.name):
                            subfolders.append(entry.path)
            
            stats['subfolder_count'] = len(subfolders)
            
            # Calculate size for each subfolder
            for subfolder_path in subfolders:
                try:
                    # Use fast tree size calculation
                    folder_size = self.get_tree_size_fast(subfolder_path)
                    folder_name = os.path.basename(subfolder_path)
                    
                    stats['subfolders'].append({
                        'name': folder_name,
                        'path': subfolder_path,
                        'size_bytes': folder_size,
                        'size_gb': folder_size / (1024**3)
                    })
                    
                    stats['total_size_bytes'] += folder_size
                    
                    # Log progress for large scans
                    elapsed = time.time() - self.scan_start_time
                    if elapsed > 5:  # Log every few seconds for long scans
                        logger.info(f"Scanned {len(stats['subfolders'])}/{stats['subfolder_count']} folders...")
                    
                except (OSError, PermissionError) as e:
                    logger.warning(f"Cannot access folder {subfolder_path}: {e}")
                    continue
            
            # Also count files in root directory
            root_size = 0
            root_files = 0
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        if self.file_filter.should_include_file(entry.path, filename=entry.name):
                            try:
                                root_size += entry.stat(follow_symlinks=False).st_size
                                root_files += 1
                            except (OSError, PermissionError):
                                continue
            
            stats['total_size_bytes'] += root_size
            stats['total_files'] = root_files  # Note: This is only root files in folder-only mode
            stats['file_types'] = {}  # Not enumerated in folder-only mode
            
        except (OSError, PermissionError) as e:
            logger.error(f"Cannot access path {path}: {e}")
        
        stats['scan_duration'] = time.time() - self.scan_start_time
        return stats
    
    def _analyze_detailed(self, path: str, stats: Dict, recursive: bool) -> Dict:
        """Detailed analysis mode with full file enumeration."""
        stats['scan_mode'] = 'detailed'
        
        # Use os.scandir for better performance than os.walk
        if settings.ENABLE_FAST_SCAN:
            return self._analyze_with_scandir(path, stats, recursive)
        else:
            # Legacy os.walk method
            return self._analyze_with_walk(path, stats, recursive)
    
    def _analyze_with_scandir(self, path: str, stats: Dict, recursive: bool) -> Dict:
        """Optimized analysis using os.scandir (faster than os.walk)."""
        def scan_directory(current_path: str, is_root: bool = False):
            try:
                with os.scandir(current_path) as entries:
                    dirs = []
                    files = []
                    
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if not self.file_filter.should_exclude_folder(entry.name):
                                dirs.append(entry)
                        else:
                            files.append(entry)
                    
                    # Count subfolders at root level
                    if is_root:
                        stats['subfolder_count'] = len(dirs)
                    
                    # Process files
                    for file_entry in files:
                        if not self.file_filter.should_include_file(file_entry.path, filename=file_entry.name):
                            continue
                        
                        try:
                            file_size = file_entry.stat(follow_symlinks=False).st_size
                            stats['total_files'] += 1
                            stats['total_size_bytes'] += file_size
                            
                            # Track file types
                            ext = os.path.splitext(file_entry.name)[1].lower()
                            if not ext:
                                ext = 'no_extension'
                            stats['file_types'][ext] += 1
                            
                            if len(stats['preview_files']) < 20:
                                stats['preview_files'].append(file_entry.path)
                            
                            # Check timeout
                            if time.time() - self.scan_start_time > settings.SCAN_TIMEOUT_SECONDS:
                                logger.warning(f"Scan timeout reached after {settings.SCAN_TIMEOUT_SECONDS}s")
                                return False  # Signal timeout
                            
                        except (OSError, PermissionError):
                            continue
                    
                    # Recurse into subdirectories if requested
                    if recursive:
                        for dir_entry in dirs:
                            if scan_directory(dir_entry.path, is_root=False) is False:
                                return False  # Propagate timeout
                    
                    return True
                    
            except (OSError, PermissionError) as e:
                logger.warning(f"Cannot access directory {current_path}: {e}")
                return True
        
        # Start scanning from root
        scan_directory(path, is_root=True)
        
        stats['file_types'] = dict(stats['file_types'])
        stats['scan_duration'] = time.time() - self.scan_start_time
        return stats
    
    def _analyze_with_walk(self, path: str, stats: Dict, recursive: bool) -> Dict:
        """Legacy analysis using os.walk (kept for compatibility)."""
        # Walk through directory
        for root, dirs, files in os.walk(path):
            # Filter out excluded folders
            dirs[:] = [d for d in dirs if not self.file_filter.should_exclude_folder(d)]
            
            # Count subfolders at first level
            if root == path:
                stats['subfolder_count'] = len(dirs)
            
            # Process files
            for file in files:
                filepath = os.path.join(root, file)
                
                # Check if file should be included
                if not self.file_filter.should_include_file(filepath, filename=file):
                    continue
                
                try:
                    file_size = os.path.getsize(filepath)
                    stats['total_files'] += 1
                    stats['total_size_bytes'] += file_size
                    
                    # Track file types
                    ext = os.path.splitext(file)[1].lower()
                    if not ext:
                        ext = 'no_extension'
                    stats['file_types'][ext] += 1
                    
                    # Add to preview (first 20 files)
                    if len(stats['preview_files']) < 20:
                        stats['preview_files'].append(filepath)
                    
                    # Check timeout
                    if time.time() - self.scan_start_time > settings.SCAN_TIMEOUT_SECONDS:
                        logger.warning(f"Scan timeout reached after {settings.SCAN_TIMEOUT_SECONDS}s")
                        break
                    
                except (OSError, PermissionError):
                    continue
            
            # Don't recurse if not requested
            if not recursive:
                break
        
        stats['file_types'] = dict(stats['file_types'])
        stats['scan_duration'] = time.time() - self.scan_start_time
        return stats
    
    def analyze_subfolders(self, path: str, folder_only_mode: bool = False) -> List[Dict]:
        """Analyze each immediate subfolder separately.
        
        Args:
            path: Parent directory path
            folder_only_mode: If True, use fast folder-only scanning
        
        Returns:
            List of subfolder statistics
        """
        subfolders = []
        
        try:
            # Use scandir for better performance
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if not self.file_filter.should_exclude_folder(entry.name):
                            try:
                                subfolder_stats = self.analyze(entry.path, recursive=True, 
                                                              folder_only_mode=folder_only_mode)
                                subfolder_stats['name'] = entry.name
                                subfolders.append(subfolder_stats)
                                
                                # Log progress
                                logger.info(f"Analyzed subfolder: {entry.name} ({subfolder_stats.get('total_size_bytes', 0) / (1024**3):.2f} GB)")
                            except Exception as e:
                                logger.error(f"Error analyzing subfolder {entry.name}: {e}")
        except (OSError, PermissionError) as e:
            logger.error(f"Cannot access directory {path}: {e}")
        
        return subfolders


class LocalAuditService:
    """Service for local filesystem audits and recommendation generation."""

    DOC_EXTENSIONS = {
        '.doc', '.docx', '.pdf', '.txt', '.rtf', '.odt', '.xls', '.xlsx',
        '.csv', '.ppt', '.pptx', '.md'
    }
    MEDIA_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff', '.webp',
        '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav'
    }
    DATA_EXTENSIONS = {
        '.json', '.xml', '.parquet', '.feather', '.avro', '.sqlite', '.db',
        '.zip', '.gz', '.tar', '.7z', '.ndjson'
    }
    TEMP_EXTENSIONS = {'.tmp', '.temp', '.bak', '.old', '.log', '.dmp', '.cache'}

    @staticmethod
    def _all_files_filter() -> FileFilter:
        return FileFilter(
            include_patterns=[r'^.*$'],
            exclude_patterns=[],
            exclude_folders=[]
        )

    @staticmethod
    def validate_windows_local_path(path: str) -> str:
        """Validate and normalize a Windows local drive/folder path."""
        raw = (path or '').strip().strip('"').strip("'")
        if not raw:
            raise ValueError("Path is required")

        normalized = os.path.normpath(raw)

        # Reject UNC/network paths for v1.
        if normalized.startswith('\\\\'):
            raise ValueError("UNC/network paths are not supported in v1")

        # Require local drive paths like C:\\ or D:\\folder.
        if not re.match(r'^[A-Za-z]:\\', normalized + ('\\' if re.match(r'^[A-Za-z]:$', normalized) else '')):
            raise ValueError("Path must be a local Windows drive or folder (example: T:\\\\)")

        if re.match(r'^[A-Za-z]:$', normalized):
            normalized = normalized + '\\'

        if not os.path.exists(normalized):
            raise ValueError(f"Path does not exist: {normalized}")
        if not os.path.isdir(normalized):
            raise ValueError(f"Path is not a directory: {normalized}")

        return normalized

    @classmethod
    def categorize_extension(cls, extension: str) -> str:
        ext = (extension or '').lower()
        if ext in cls.DOC_EXTENSIONS:
            return 'docs'
        if ext in cls.MEDIA_EXTENSIONS:
            return 'media'
        if ext in cls.DATA_EXTENSIONS:
            return 'data'
        if ext in cls.TEMP_EXTENSIONS:
            return 'temp'
        return 'other'

    @classmethod
    def _safe_file_info(cls, file_path: str):
        try:
            stat = os.stat(file_path)
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            age_days = int((datetime.now(timezone.utc) - modified).total_seconds() // 86400)
            extension = os.path.splitext(file_path)[1].lower() or 'no_extension'
            return {
                'size_bytes': float(stat.st_size or 0.0),
                'modified_at': modified,
                'age_days': max(age_days, 0),
                'extension': extension,
                'file_category': cls.categorize_extension(extension),
                'is_temp': cls.categorize_extension(extension) == 'temp',
            }
        except (OSError, PermissionError):
            return None

    @classmethod
    def run_scan(cls, target_path: str, recursive: bool = True) -> Dict:
        """Run a local audit and return summary, folder breakdown, and detailed findings."""
        normalized_path = cls.validate_windows_local_path(target_path)
        started = time.time()
        skipped_permissions = 0

        analyzer = FolderAnalyzer(file_filter=cls._all_files_filter())
        summary = analyzer.analyze(normalized_path, recursive=recursive)

        top_level_folders = []
        root_file_types = defaultdict(int)
        root_files = 0
        root_size = 0.0

        try:
            with os.scandir(normalized_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            folder_stats = analyzer.analyze(entry.path, recursive=True)
                            top_level_folders.append({
                                'name': entry.name,
                                'path': entry.path,
                                'total_files': int(folder_stats.get('total_files', 0)),
                                'total_size_bytes': float(folder_stats.get('total_size_bytes', 0.0)),
                                'file_types': folder_stats.get('file_types', {}),
                                'scan_mode': folder_stats.get('scan_mode', 'detailed'),
                            })
                        elif entry.is_file(follow_symlinks=False):
                            info = cls._safe_file_info(entry.path)
                            if info:
                                root_files += 1
                                root_size += info['size_bytes']
                                root_file_types[info['extension']] += 1
                    except (OSError, PermissionError):
                        skipped_permissions += 1
                        continue
        except (OSError, PermissionError):
            skipped_permissions += 1

        top_level_folders.append({
            'name': '(root)',
            'path': normalized_path,
            'total_files': root_files,
            'total_size_bytes': root_size,
            'file_types': dict(root_file_types),
            'scan_mode': 'detailed',
        })

        top_level_folders.sort(key=lambda row: float(row.get('total_size_bytes', 0.0)), reverse=True)

        detailed_cap = int(settings.LOCAL_AUDIT_MAX_DETAILED_FILES)
        timeout_seconds = int(settings.LOCAL_AUDIT_SCAN_MAX_SECONDS)
        detailed_findings = []
        detailed_truncated = False

        def _on_walk_error(_err):
            nonlocal skipped_permissions
            skipped_permissions += 1

        for root, _dirs, files in os.walk(normalized_path, onerror=_on_walk_error):
            if not recursive and root != normalized_path:
                continue

            for file_name in files:
                if len(detailed_findings) >= detailed_cap:
                    detailed_truncated = True
                    break

                if time.time() - started > timeout_seconds:
                    detailed_truncated = True
                    break

                file_path = os.path.join(root, file_name)
                info = cls._safe_file_info(file_path)
                if not info:
                    skipped_permissions += 1
                    continue

                relative_path = os.path.relpath(file_path, normalized_path)
                first_part = relative_path.split(os.sep, 1)[0]
                top_level_folder = '(root)' if first_part == file_name else first_part

                detailed_findings.append({
                    'top_level_folder': top_level_folder,
                    'relative_path': relative_path,
                    'file_name': file_name,
                    'extension': info['extension'],
                    'file_category': info['file_category'],
                    'size_bytes': info['size_bytes'],
                    'modified_at': info['modified_at'],
                    'age_days': info['age_days'],
                    'is_temp': info['is_temp'],
                })

            if detailed_truncated:
                break

        recommendations = cls.generate_recommendations(
            total_files=int(summary.get('total_files', 0)),
            total_size_bytes=float(summary.get('total_size_bytes', 0.0)),
            file_types=summary.get('file_types', {}) or {},
            findings=detailed_findings,
            top_level_folders=top_level_folders,
        )

        return {
            'target_path': normalized_path,
            'summary': summary,
            'top_level_folders': top_level_folders,
            'detailed_findings': detailed_findings,
            'detailed_truncated': detailed_truncated,
            'max_detailed_files': detailed_cap,
            'skip_permission_count': skipped_permissions,
            'scan_duration_seconds': round(time.time() - started, 2),
            'recommendations': recommendations,
        }

    @classmethod
    def generate_recommendations(
        cls,
        total_files: int,
        total_size_bytes: float,
        file_types: Dict[str, int],
        findings: List[Dict],
        top_level_folders: List[Dict],
    ) -> List[Dict]:
        """Generate read-only recommendations based on scan stats."""
        recommendations = []
        safe_total_files = max(total_files, 1)

        temp_count = 0
        docs_count = 0
        media_data_count = 0
        for extension, count in (file_types or {}).items():
            category = cls.categorize_extension(extension)
            if category == 'temp':
                temp_count += int(count or 0)
            elif category == 'docs':
                docs_count += int(count or 0)
            elif category in {'media', 'data'}:
                media_data_count += int(count or 0)

        if temp_count > 0:
            temp_pct = (temp_count / safe_total_files) * 100
            recommendations.append({
                'kind': 'cleanup_temp_files',
                'priority': 'high' if temp_pct >= 10 else 'medium',
                'title': 'Review temporary/junk files for cleanup',
                'reason': f'{temp_count} temporary-like files detected ({temp_pct:.1f}% of scanned files).',
            })

        docs_ratio = docs_count / safe_total_files
        if docs_ratio >= float(settings.LOCAL_AUDIT_DOCS_DOMINANCE_PCT):
            recommendations.append({
                'kind': 'docs_to_shared_drive',
                'priority': 'medium',
                'title': 'Consider moving document-heavy content to Google Shared Drive',
                'reason': f'Documents represent {docs_ratio * 100:.1f}% of scanned files.',
            })

        media_ratio = media_data_count / safe_total_files
        if media_ratio >= float(settings.LOCAL_AUDIT_MEDIA_DOMINANCE_PCT):
            recommendations.append({
                'kind': 'media_data_to_gcs',
                'priority': 'medium',
                'title': 'Consider moving media/data-heavy content to Google Cloud Storage buckets',
                'reason': f'Media/data files represent {media_ratio * 100:.1f}% of scanned files.',
            })

        archive_age_days = int(settings.LOCAL_AUDIT_ARCHIVE_AGE_DAYS)
        archive_min_size_bytes = int(settings.LOCAL_AUDIT_ARCHIVE_MIN_SIZE_MB) * 1024 * 1024
        old_large = [
            item for item in findings
            if int(item.get('age_days', 0)) >= archive_age_days
            and float(item.get('size_bytes', 0.0)) >= archive_min_size_bytes
        ]
        if old_large:
            old_large_bytes = sum(float(item.get('size_bytes', 0.0)) for item in old_large)
            recommendations.append({
                'kind': 'archive_large_old_files',
                'priority': 'medium',
                'title': 'Archive large and old files',
                'reason': (
                    f'{len(old_large)} files are older than {archive_age_days} days '
                    f'and larger than {settings.LOCAL_AUDIT_ARCHIVE_MIN_SIZE_MB} MB '
                    f'({old_large_bytes / (1024**3):.2f} GB total).'
                ),
            })

        if not recommendations:
            recommendations.append({
                'kind': 'no_action_needed',
                'priority': 'low',
                'title': 'No immediate optimization recommendations',
                'reason': (
                    f'Scanned {total_files} files totaling {total_size_bytes / (1024**3):.2f} GB '
                    'without crossing current recommendation thresholds.'
                ),
            })

        # Provide folder-level hint for top storage contributors.
        heavy_folders = [f for f in top_level_folders if f.get('name') != '(root)']
        heavy_folders = sorted(heavy_folders, key=lambda row: float(row.get('total_size_bytes', 0.0)), reverse=True)[:3]
        if heavy_folders:
            recommendations.append({
                'kind': 'top_folders_for_review',
                'priority': 'low',
                'title': 'Prioritize largest folders for in-depth review',
                'reason': ', '.join(
                    f"{row['name']} ({float(row.get('total_size_bytes', 0.0)) / (1024**3):.2f} GB)"
                    for row in heavy_folders
                ),
            })

        return recommendations

# Progress line patterns for gcloud storage rsync output (Issue #12)
_PROGRESS_RE = re.compile(
    r'Completed\s+([\d.]+)\s*(B|KiB|MiB|GiB)\s*/\s*([\d.]+)\s*(B|KiB|MiB|GiB)'
)
_FILES_RE = re.compile(r'Operation completed over (\d+) objects')

def _to_bytes(val: float, unit: str) -> float:
    return val * {'B': 1, 'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}[unit]

def _parse_progress(line: str, callback: Callable) -> None:
    """Parse a gcloud/gsutil output line and invoke callback with progress."""
    m = _PROGRESS_RE.search(line)
    if m:
        callback(
            bytes_uploaded=_to_bytes(float(m.group(1)), m.group(2)),
            total_bytes=_to_bytes(float(m.group(3)), m.group(4))
        )
    mf = _FILES_RE.search(line)
    if mf:
        callback(files_uploaded=int(mf.group(1)))

def make_progress_callback(job_id: str, db) -> Callable:
    """Return a throttled progress callback that updates the job in the database."""
    last_write = [0.0]

    def callback(bytes_uploaded=None, total_bytes=None, files_uploaded=None):
        now = time.time()
        if now - last_write[0] < 2.0:
            return
        last_write[0] = now
        try:
            from .database import UploadJob
            j = db.query(UploadJob).filter(UploadJob.job_id == job_id).first()
            if not j:
                return
            if bytes_uploaded is not None:
                j.bytes_uploaded = bytes_uploaded
            if total_bytes and total_bytes > 0:
                j.total_size_bytes = total_bytes
            if files_uploaded is not None:
                j.files_uploaded = files_uploaded
            db.commit()
        except Exception:
            pass

    return callback


class UploadService:
    """Handle Google Cloud Storage uploads."""
    
    def __init__(self):
        self.active_uploads = {}  # Track active upload processes
    
    async def upload_to_gcs(self, job_id: str, source_path: str,
                           destination_bucket: str, destination_path: str = "",
                           dry_run: bool = False, recursive: bool = True,
                           threads: int = 4, log_path: str = None, upload_tool: str = "gcloud",
                           exclude_patterns: list = None, exclude_folders: list = None,
                           no_clobber: bool = False, progress_callback: Callable = None) -> bool:
        """Upload files to Google Cloud Storage using gcloud storage or gsutil."""
        
        # Strip bucket name from destination_path if it starts with it
        # This handles cases where users paste paths from GCS console that include the bucket
        if destination_path:
            path_parts = destination_path.strip('/').split('/', 1)
            if path_parts[0] == destination_bucket:
                destination_path = path_parts[1] if len(path_parts) > 1 else ""
                print(f"ℹ️  Stripped bucket name from path. Using: {destination_path}")
        
        # Construct GCS path
        gcs_path = f"gs://{destination_bucket}"
        if destination_path:
            gcs_path = f"{gcs_path}/{destination_path.strip('/')}"
        
        # Helper to convert glob patterns to regex for gsutil/gcloud
        def glob_to_regex(pattern: str) -> str:
            """Convert a glob pattern to regex for gsutil/gcloud exclude."""
            # Detect if pattern is already a regex (has regex-specific syntax)
            regex_indicators = ['|', '(', ')', '^', '$', '\\', '{', '}', '[', ']', '+', '(?']
            is_likely_regex = any(indicator in pattern for indicator in regex_indicators)
            
            if is_likely_regex:
                # Already a regex pattern - pass through unchanged
                return pattern
            elif pattern.startswith('*.'):
                # *.tmp -> .*\.tmp$
                ext = pattern[2:]
                return r'.*\.' + re.escape(ext) + r'$'
            elif pattern.startswith('*'):
                # *something -> .*something$
                return r'.*' + re.escape(pattern[1:]) + r'$'
            elif pattern.endswith('*'):
                # something* -> ^something.*
                return r'^' + re.escape(pattern[:-1]) + r'.*'
            elif '*' in pattern:
                # General glob: convert * to .*
                result = re.escape(pattern)
                result = result.replace(r'\*', '.*')
                return result
            else:
                # Exact filename match (e.g., Thumbs.db)
                return re.escape(pattern)
        
        # Convert user patterns (which may be glob) to regex for the upload tools
        all_exclude_patterns = []
        if exclude_patterns:
            for pattern in exclude_patterns:
                all_exclude_patterns.append(glob_to_regex(pattern))
        
        # Add exclude_folders as regex patterns
        if exclude_folders:
            for folder in exclude_folders:
                # Convert folder name to regex pattern that matches the folder anywhere in path
                # Pattern matches: folder/ or /folder/ anywhere in the path
                all_exclude_patterns.append(f".*/{re.escape(folder)}/.*")
                all_exclude_patterns.append(f"^{re.escape(folder)}/.*")
        
        # Build command based on selected tool
        if upload_tool == "gsutil":
            # Build gsutil command
            cmd = ["gsutil", "-m", "rsync"]
            
            if dry_run:
                cmd.append("-n")  # Dry run
            
            if recursive:
                cmd.append("-r")  # Recursive
            
            # Add exclude patterns for gsutil (uses -x with regex)
            # Combine multiple patterns with | alternation
            if all_exclude_patterns:
                combined_pattern = "|".join(f"({p})" for p in all_exclude_patterns)
                cmd.extend(["-x", combined_pattern])
        else:
            # Build gcloud storage rsync command (default)
            cmd = ["gcloud", "storage", "rsync"]
            
            if dry_run:
                cmd.append("--dry-run")  # Dry run
            
            if recursive:
                cmd.append("--recursive")  # Recursive
            
            # Use checksums to determine if files need updating (more reliable than timestamps)
            cmd.append("--checksums-only")

            # Skip files that already exist in the bucket (Issue #13)
            if no_clobber:
                cmd.append("--no-clobber")

            # Add exclude patterns for gcloud storage
            # Combine multiple patterns with | alternation
            if all_exclude_patterns:
                combined_pattern = "|".join(f"({p})" for p in all_exclude_patterns)
                cmd.append(f"--exclude={combined_pattern}")
        
        cmd.extend([source_path, gcs_path])
        
        # Build shell command string with proper quoting for all arguments
        # Always quote paths to handle spaces and special characters
        shell_cmd_parts = []
        for i, arg in enumerate(cmd):
            # Quote paths (source and destination are last two args) and args with spaces
            if i >= len(cmd) - 2 or ' ' in str(arg) or '\\' in str(arg):
                shell_cmd_parts.append(f'"{arg}"')
            else:
                shell_cmd_parts.append(arg)
        
        shell_cmd = ' '.join(shell_cmd_parts)
        display_shell_cmd = redact_sensitive_text(shell_cmd)
        print(f"🚀 Executing: {display_shell_cmd}")
        
        try:
            # Windows doesn't support asyncio subprocess properly, so we use thread pool
            import subprocess
            
            def run_subprocess():
                """Run subprocess synchronously in thread, capturing output in real-time.

                Uses two threads to read stdout and stderr concurrently to prevent
                OS pipe buffer deadlocks when both streams produce large output.
                """
                process = subprocess.Popen(
                    shell_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                self.active_uploads[job_id] = process

                stdout_lines = []
                stderr_lines = []

                def _read_stdout():
                    for line in process.stdout:
                        stdout_lines.append(line)

                def _read_stderr():
                    for line in process.stderr:
                        stderr_lines.append(line)
                        print(redact_sensitive_text(line.rstrip()))
                        if progress_callback:
                            _parse_progress(line, progress_callback)

                t1 = threading.Thread(target=_read_stdout, daemon=True)
                t2 = threading.Thread(target=_read_stderr, daemon=True)
                t1.start()
                t2.start()
                t1.join()
                t2.join()
                process.wait()

                return process.returncode, ''.join(stdout_lines), ''.join(stderr_lines)
            
            # Run in thread pool to avoid blocking
            returncode, stdout, stderr = await asyncio.to_thread(run_subprocess)
            
            # Remove from active uploads
            if job_id in self.active_uploads:
                del self.active_uploads[job_id]
            
            # Prepare output
            output = redact_sensitive_text(
                f"STDOUT:\n{stdout if stdout else 'No output'}\n\nSTDERR:\n{stderr if stderr else 'No errors'}"
            )
            
            # Save log if path provided (ALWAYS save, even on failure)
            if log_path:
                try:
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    with open(log_path, 'w', encoding='utf-8') as f:
                        # Enhanced header with full job context
                        f.write("="*80 + "\n")
                        f.write("JETSTREAM UPLOAD JOB LOG\n")
                        f.write("="*80 + "\n\n")
                        
                        # Get friendly name from filename
                        log_filename = os.path.basename(log_path)
                        friendly_name = log_filename.replace('.log', '')
                        
                        f.write(f"Job Name:        {friendly_name}\n")
                        f.write(f"Job ID:          {job_id}\n")
                        f.write(f"Timestamp:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"\n")
                        f.write(f"Source Path:     {source_path}\n")
                        f.write(f"Destination:     {gcs_path}\n")
                        f.write(f"Dry Run:         {dry_run}\n")
                        f.write(f"Recursive:       {recursive}\n")
                        f.write(f"\n")
                        f.write(f"Command:         {display_shell_cmd}\n")
                        f.write(f"Return Code:     {returncode}\n")
                        f.write(f"Status:          {'SUCCESS' if returncode == 0 else 'FAILED'}\n")
                        f.write("\n" + "="*80 + "\n")
                        f.write("COMMAND OUTPUT\n")
                        f.write("="*80 + "\n\n")
                        f.write(output)
                    print(f"✓ Log saved to: {log_path}")
                except Exception as log_error:
                    print(f"⚠ Warning: Could not save log file: {log_error}")
            
            # Check for errors
            if returncode != 0:
                error_msg = redact_sensitive_text(stderr if stderr else "Unknown error")
                print(f"❌ Upload failed: {error_msg}")
                return False, output
            
            print(f"✓ Upload completed successfully")
            # Return success and output for database storage
            return True, output
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ Upload exception: {str(e)}")
            print(f"Full traceback:\n{error_details}")
            
            # Save error to log file
            output = redact_sensitive_text(f"Exception: {str(e)}\n\n{error_details}")
            if log_path:
                try:
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    with open(log_path, 'w', encoding='utf-8') as f:
                        # Enhanced header for exception logs
                        f.write("="*80 + "\n")
                        f.write("JETSTREAM UPLOAD JOB LOG - EXCEPTION\n")
                        f.write("="*80 + "\n\n")
                        
                        log_filename = os.path.basename(log_path)
                        friendly_name = log_filename.replace('.log', '')
                        
                        f.write(f"Job Name:        {friendly_name}\n")
                        f.write(f"Job ID:          {job_id}\n")
                        f.write(f"Timestamp:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"\n")
                        f.write(f"Source Path:     {source_path}\n")
                        f.write(f"Destination:     {gcs_path}\n")
                        f.write(f"Command:         {redact_sensitive_text(shell_cmd)}\n")
                        f.write(f"Status:          EXCEPTION\n")
                        f.write("\n" + "="*80 + "\n")
                        f.write("ERROR DETAILS\n")
                        f.write("="*80 + "\n\n")
                        f.write(output)
                    print(f"✓ Error log saved to: {log_path}")
                except Exception as log_error:
                    print(f"⚠ Warning: Could not save error log: {log_error}")
            
            if job_id in self.active_uploads:
                del self.active_uploads[job_id]
            return False, output
    
    def cancel_upload(self, job_id: str) -> bool:
        """Cancel an active upload."""
        if job_id in self.active_uploads:
            try:
                process = self.active_uploads[job_id]
                process.kill()
                del self.active_uploads[job_id]
                return True
            except:
                return False
        return False

class QueueManager:
    """Manage upload queue and concurrent jobs."""

    def __init__(self, max_concurrent: int = 1):
        self.max_concurrent = max_concurrent
        self.running_jobs = set()
        self.queue = []
        self.paused = False

    def can_start_job(self) -> bool:
        """Check if a new job can be started (respects pause state)."""
        return not self.paused and len(self.running_jobs) < self.max_concurrent

    def pause(self) -> None:
        """Pause queue — no new jobs will start until resume() is called."""
        self.paused = True
        logger.info("Queue paused")

    def resume(self) -> None:
        """Resume queue processing."""
        self.paused = False
        logger.info("Queue resumed")

    def add_to_queue(self, job_id: str):
        """Add job to queue."""
        if job_id not in self.queue:
            self.queue.append(job_id)

    def start_job(self, job_id: str):
        """Mark job as started."""
        self.running_jobs.add(job_id)
        if job_id in self.queue:
            self.queue.remove(job_id)

    def complete_job(self, job_id: str):
        """Mark job as completed."""
        if job_id in self.running_jobs:
            self.running_jobs.remove(job_id)

    def get_next_job(self) -> Optional[str]:
        """Get next job from queue if can start."""
        if self.can_start_job() and self.queue:
            return self.queue[0]
        return None

    def get_queue_status(self) -> Dict:
        """Get current queue status."""
        return {
            'running_count': len(self.running_jobs),
            'queued_count': len(self.queue),
            'running_jobs': list(self.running_jobs),
            'queued_jobs': self.queue.copy(),
            'max_concurrent': self.max_concurrent,
            'paused': self.paused,
        }

# Global instances
upload_service = UploadService()
queue_manager = QueueManager()
