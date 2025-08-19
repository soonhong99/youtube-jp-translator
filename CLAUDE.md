# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a YouTube Japanese Speech-to-Text (STT) and Translation system that extracts Japanese audio from YouTube videos, transcribes it to text using Faster-Whisper, and translates it to Korean using Gemini API. The system uses a microservices architecture with Kafka for async processing and WebSocket for real-time updates.

## Architecture

**Microservices Architecture:**
- **Frontend**: React-based web client (port 3000)
- **API Gateway**: Single entry point routing requests (port 8080)
- **YouTube Extractor**: Audio extraction service (internal)
- **STT Processor**: API server + background worker for speech-to-text
- **Infrastructure**: Kafka + Zookeeper, Redis for message history

**Message Flow:**
1. Client requests audio extraction via API Gateway
2. STT request sent to Kafka topic `stt_requests`
3. Worker processes audio chunks with Faster-Whisper
4. Results published to Kafka topic `stt_results`
5. API consumer performs batch translation via Gemini
6. Real-time updates sent via WebSocket

## Development Commands

### Backend Development
```bash
# Navigate to backend directory
cd backend

# Start all services (REQUIRED after restart/shutdown)
docker-compose down -v  # Clear volumes to prevent WebSocket conflicts
docker-compose build    # Build images on first run or code changes
docker-compose up -d    # Start all services

# View logs
docker-compose logs -f [service-name]

# Stop services
docker-compose down

# Start monitoring tools (optional)
docker-compose --profile monitoring up -d
# Access Kafka UI: http://localhost:8090
# Access Redis Commander: http://localhost:8091
```

### Frontend Development
```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (first time)
npm install

# Start development server
npm start

# Run tests
npm test

# Build for production
npm run build
```

### Environment Setup
- Backend: Environment variables managed via Docker Compose
- Frontend: Create `.env` file with API Gateway URL:
  ```
  REACT_APP_API_GATEWAY_URL=http://localhost:8080
  REACT_APP_WS_BASE_URL=ws://localhost:8080/api
  ```
- **IMPORTANT**: Set `GEMINI_API_KEY` environment variable for translation functionality

## Key Service Details

### API Gateway (port 8080)
- **File**: `backend/services/api-gateway/src/main.py`
- Routes requests to appropriate microservices
- Handles WebSocket proxying for real-time updates
- Single external entry point for all API calls

### STT Processor
- **API Server**: `backend/services/stt-processor/src/main.py`
- **Worker**: `backend/services/stt-processor/src/worker.py`
- Uses Faster-Whisper base model for Japanese STT
- Batch translation via Gemini API when all segments complete
- WebSocket manager for real-time client updates

### YouTube Extractor
- **File**: `backend/services/youtube-extractor/src/main.py`
- Uses yt-dlp and pydub for audio extraction
- Saves WAV files to shared Docker volume

## Important Patterns

### Error Handling
- Services use structured logging with task IDs
- Failed STT chunks are retried with fallback processing
- WebSocket connections handle disconnection gracefully
- Redis stores message history for late-joining clients

### Data Flow
- All inter-service communication via Kafka topics
- WebSocket messages include progress, status, and data
- Translation occurs only after all STT segments complete
- Segment data structure includes both Japanese and Korean text

### Development Notes
- WebSocket connections can become stale - restart with `docker-compose down -v`
- Faster-Whisper models download on first container start
- Redis TTL manages message history cleanup
- Kafka auto-creates topics on service startup

## Testing

- Frontend: Uses React Testing Library (`npm test`)
- Backend: No formal test suite currently implemented
- Manual testing via web interface at `http://localhost:3000`

## Common Issues

1. **WebSocket Connection Issues**: Run `docker-compose down -v` before restart
2. **Translation Not Working**: Verify `GEMINI_API_KEY` environment variable
3. **Audio Extraction Fails**: Check YouTube URL accessibility and yt-dlp compatibility
4. **STT Processing Slow**: Base model runs on CPU - consider GPU setup for production

## File Locations

- **Frontend Components**: `frontend/src/components/`, `frontend/src/pages/`
- **Backend Services**: `backend/services/[service-name]/src/`
- **Docker Configuration**: `backend/docker-compose.yml`
- **Environment Files**: `frontend/.env`, Docker Compose environment variables