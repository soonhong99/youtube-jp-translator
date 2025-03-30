"""YouTube Extractor API service.

This module provides a FastAPI application to extract audio from YouTube videos.
"""

import os
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl

from .extractor import YouTubeExtractor
from config.settings import AUDIO_OUTPUT_DIR, DEFAULT_AUDIO_FORMAT

app = FastAPI(
    title="YouTube Audio Extractor",
    description="Extract audio from YouTube videos for STT processing",
    version="0.1.0",
)

# Create extractor instance
extractor = YouTubeExtractor()

class YouTubeRequest(BaseModel):
    """Request model for YouTube audio extraction."""
    
    url: HttpUrl
    audio_format: Optional[str] = DEFAULT_AUDIO_FORMAT
    filename: Optional[str] = None

class YouTubeResponse(BaseModel):
    """Response model for YouTube audio extraction."""
    
    file_path: str
    download_url: str
    video_title: str

@app.post("/extract", response_model=YouTubeResponse)
async def extract_audio(request: YouTubeRequest):
    """Extract audio from a YouTube video.
    
    Args:
        request: YouTube extraction request
        
    Returns:
        YouTubeResponse: Response with file path and download URL
    """
    try:
        # Validate audio format
        if request.audio_format not in ["mp3", "wav"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported audio format: {request.audio_format}"
            )
        
        # Set the extractor format if specified
        if request.audio_format != extractor.audio_format:
            extractor.audio_format = request.audio_format
        
        # Extract audio
        file_path, video_title = extractor.extract_audio(
            youtube_url=str(request.url),  # Convert HttpUrl to str
            filename=request.filename
        )
        
        # Get the filename from the path
        filename = os.path.basename(file_path)
        
        return YouTubeResponse(
            file_path=file_path,
            download_url=f"/download/{filename}",
            video_title=video_title
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{filename}")
async def download_file(filename: str):
    """Download an extracted audio file.
    
    Args:
        filename: Name of the file to download
        
    Returns:
        FileResponse: The audio file
    """
    file_path = os.path.join(AUDIO_OUTPUT_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=f"audio/{os.path.splitext(filename)[1].lstrip('.')}"
    )

@app.get("/info")
async def get_video_info(url: HttpUrl):
    """Get information about a YouTube video.
    
    Args:
        url: YouTube URL
        
    Returns:
        dict: Video information
    """
    try:
        return extractor.get_video_info(str(url))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/files/{filename}")
async def delete_file(filename: str, background_tasks: BackgroundTasks):
    """Delete an extracted audio file.
    
    Args:
        filename: Name of the file to delete
        background_tasks: Background tasks for async deletion
        
    Returns:
        dict: Success message
    """
    file_path = os.path.join(AUDIO_OUTPUT_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    def remove_file(path: str):
        try:
            os.remove(path)
        except Exception:
            pass
    
    background_tasks.add_task(remove_file, file_path)
    return {"message": f"File {filename} will be deleted"}

@app.get("/")
async def root():
    """API root endpoint.
    
    Returns:
        dict: API information
    """
    return {
        "service": "YouTube Audio Extractor",
        "version": "0.1.0",
        "endpoints": [
            {"path": "/extract", "method": "POST", "description": "Extract audio from YouTube"},
            {"path": "/download/{filename}", "method": "GET", "description": "Download extracted audio"},
            {"path": "/info", "method": "GET", "description": "Get YouTube video information"},
            {"path": "/files/{filename}", "method": "DELETE", "description": "Delete extracted audio file"}
        ]
    }