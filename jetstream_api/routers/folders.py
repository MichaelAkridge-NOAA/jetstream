"""Folder analysis and preview endpoints."""

from fastapi import APIRouter, HTTPException
from typing import List

from ..models import FolderAnalysisRequest, FolderAnalysisResponse
from ..services import FileFilter, FolderAnalyzer

router = APIRouter()

@router.post("/analyze", response_model=FolderAnalysisResponse)
async def analyze_folder(request: FolderAnalysisRequest):
    """
    Analyze a folder and return statistics.
    Provides preview of what would be uploaded without actually uploading.
    
    Automatically uses fast folder-only mode for large directories (>100 subfolders or >10k files).
    """
    # Create file filter
    file_filter = FileFilter(
        include_patterns=request.include_patterns,
        exclude_patterns=request.exclude_patterns,
        exclude_folders=request.exclude_folders
    )
    
    # Analyze folder
    analyzer = FolderAnalyzer(file_filter)
    
    try:
        stats = analyzer.analyze(request.path, recursive=request.recursive)
        
        # Convert to response format
        response_data = {
            'path': stats['path'],
            'total_files': stats['total_files'],
            'total_size_bytes': stats['total_size_bytes'],
            'total_size_mb': round(stats['total_size_bytes'] / (1024 * 1024), 2),
            'total_size_gb': round(stats['total_size_bytes'] / (1024 * 1024 * 1024), 2),
            'file_types': stats.get('file_types', {}),
            'subfolder_count': stats['subfolder_count'],
            'preview_files': stats.get('preview_files', []),
            'scan_mode': stats.get('scan_mode', 'detailed'),
            'scan_duration': round(stats.get('scan_duration', 0), 2)
        }
        
        return FolderAnalysisResponse(**response_data)
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/analyze-split")
async def analyze_folder_split(request: FolderAnalysisRequest):
    """
    Analyze a folder with subfolder breakdown.
    Shows stats for each immediate subfolder separately.
    
    Uses fast folder-only mode for large directories to speed up analysis.
    """
    # Create file filter
    file_filter = FileFilter(
        include_patterns=request.include_patterns,
        exclude_patterns=request.exclude_patterns,
        exclude_folders=request.exclude_folders
    )
    
    # Analyze folder
    analyzer = FolderAnalyzer(file_filter)
    
    try:
        # Get overall stats (use folder-only mode for speed)
        overall_stats = analyzer.analyze(request.path, recursive=request.recursive, 
                                        folder_only_mode=True)
        
        # Get subfolder breakdown (also use folder-only mode)
        subfolders = analyzer.analyze_subfolders(request.path, folder_only_mode=True)
        
        # Format subfolder data
        subfolder_data = []
        for sf in subfolders:
            subfolder_data.append({
                'name': sf['name'],
                'path': sf['path'],
                'total_files': sf.get('total_files', 0),
                'total_size_bytes': sf['total_size_bytes'],
                'total_size_mb': round(sf['total_size_bytes'] / (1024 * 1024), 2),
                'total_size_gb': round(sf['total_size_bytes'] / (1024 * 1024 * 1024), 2),
                'file_types': sf.get('file_types', {}),
                'scan_mode': sf.get('scan_mode', 'folder_only')
            })
        
        return {
            'overall': {
                'path': overall_stats['path'],
                'total_files': overall_stats.get('total_files', 0),
                'total_size_bytes': overall_stats['total_size_bytes'],
                'total_size_mb': round(overall_stats['total_size_bytes'] / (1024 * 1024), 2),
                'total_size_gb': round(overall_stats['total_size_bytes'] / (1024 * 1024 * 1024), 2),
                'file_types': overall_stats.get('file_types', {}),
                'subfolder_count': overall_stats['subfolder_count'],
                'scan_mode': overall_stats.get('scan_mode', 'folder_only'),
                'scan_duration': round(overall_stats.get('scan_duration', 0), 2)
            },
            'subfolders': subfolder_data,
            'recommended_split': len(subfolder_data) > 1
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/preview/{path:path}")
async def preview_files(path: str, limit: int = 50):
    """Get a preview list of files in a folder."""
    import os
    
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
    
    files = []
    try:
        for root, dirs, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(root, filename)
                try:
                    size = os.path.getsize(filepath)
                    files.append({
                        'path': filepath,
                        'name': filename,
                        'size': size,
                        'size_mb': round(size / (1024 * 1024), 2)
                    })
                    
                    if len(files) >= limit:
                        break
                except:
                    continue
            
            if len(files) >= limit:
                break
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {
        'files': files,
        'count': len(files),
        'limited': len(files) >= limit
    }
