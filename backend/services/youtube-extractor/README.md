# YouTube Audio Extractor

This service extracts audio from YouTube videos for STT (Speech-to-Text) processing.

## Features

- Extract audio from YouTube videos in mp3 or wav format
- Optimize audio for STT processing (mono channel, appropriate sample rate)
- Get information about YouTube videos
- REST API for integration with other services

## Prerequisites

- Python 3.8+
- ffmpeg (for audio processing)

## Installation

### Using Docker (Recommended)

1. Build the Docker image:
   ```
   docker build -t youtube-extractor .
   ```

2. Run the container:
   ```
   docker run -p 8000:8000 -v /path/to/audio/storage:/tmp/youtube_audio youtube-extractor
   ```

### Manual Installation

1. Install required system dependencies:
   ```
   apt-get update && apt-get install -y ffmpeg
   ```

2. Install Python requirements:
   ```
   pip install -r requirements.txt
   ```

3. Run the application:
   ```
   uvicorn src.main:app --host 0.0.0.0 --port 8000
   ```

## API Usage

### Extract Audio from YouTube

```http
POST /extract
```

Request body:
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "audio_format": "wav",
  "filename": "optional_custom_filename"
}
```

Response:
```json
{
  "file_path": "/tmp/youtube_audio/filename.wav",
  "download_url": "/download/filename.wav",
  "video_title": "YouTube Video Title"
}
```

### Download Extracted Audio

```http
GET /download/{filename}
```

### Get Video Information

```http
GET /info?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

Response:
```json
{
  "title": "Video Title",
  "author": "Channel Name",
  "length_seconds": 212,
  "views": 1234567,
  "publish_date": "2023-01-01",
  "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
}
```

### Delete Extracted Audio File

```http
DELETE /files/{filename}
```

## Configuration

You can configure the service using environment variables:

- `AUDIO_OUTPUT_DIR`: Directory to store extracted audio (default: `/tmp/youtube_audio`)
- `DEFAULT_AUDIO_FORMAT`: Default audio format (default: `wav`)
- `DEFAULT_AUDIO_BITRATE`: Default audio bitrate for mp3 (default: `128k`)
- `DEFAULT_AUDIO_SAMPLE_RATE`: Default sample rate (default: `16000`)

## Testing

Run tests with pytest:

```
pytest
```

## License

[MIT License](LICENSE)