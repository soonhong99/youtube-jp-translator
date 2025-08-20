# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an advanced YouTube Japanese Speech-to-Text (STT) and AI-powered Translation system that extracts Japanese audio from YouTube videos, transcribes it using Faster-Whisper, and provides intelligent translation to Korean using Gemini 2.5 Pro/1.5 Flash with AI Agent orchestration. The system features a sophisticated microservices architecture with Kafka for async processing, WebSocket for real-time updates, and comprehensive AI workflow management.

## Architecture

**Advanced Microservices Architecture:**
- **Frontend**: React-based web client (port 3000)
- **API Gateway**: Single entry point routing requests (port 8080)
- **YouTube Extractor**: Audio extraction service (internal)
- **STT Processor**: API server + background worker for speech-to-text
- **AI Orchestrator**: Advanced AI workflow management with multiple agents (port 8002)
  - **TranslatorAgent**: Japanese↔Korean translation with Gemini 2.5/1.5 models
  - **SummarizerAgent**: Content analysis, keyword extraction, sentiment analysis
  - **FormatterAgent**: Subtitle formatting, speaker detection, readability enhancement
  - **ReviewerAgent**: Translation quality assessment and improvement suggestions
- **Infrastructure**: Kafka + Zookeeper, Redis for caching and message history

**Enhanced Message Flow:**
1. Client requests audio extraction via API Gateway
2. STT request sent to Kafka topic `stt_requests`
3. Worker processes audio chunks with Faster-Whisper
4. Results published to Kafka topic `stt_results`
5. STT results trigger AI Orchestrator via Kafka topic `ai_processing_requests`
6. AI Orchestrator processes with multiple agents:
   - **Fast Mode**: Translation only (~30s)
   - **Standard Mode**: Translation + basic post-processing (~60s)
   - **Premium Mode**: Full AI pipeline with review and enhancement (~120s)
   - **Custom Mode**: User-defined workflow selection
7. AI results published to Kafka topic `ai_processing_results`
8. Real-time updates sent via WebSocket with progress tracking

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
- **IMPORTANT**: Set AI/Gemini environment variables in `backend/.env`:
  ```bash
  GEMINI_API_KEY="your_api_key_here"
  GEMINI_MODEL=gemini-1.5-flash-latest  # Recommended for cost efficiency
  GEMINI_TEMPERATURE=0.3
  MAX_CONCURRENT_TASKS=5
  ```

## Gemini API Cost Analysis

**10-minute Video Translation Costs:**
- **Gemini 2.5 Pro**: ~$0.067 (91원) - Premium quality with advanced reasoning
- **Gemini 1.5 Pro**: ~$0.024 (32원) - High quality, balanced cost
- **Gemini 1.5 Flash**: ~$0.003 (4원) - Fast, cost-efficient, recommended

**Free Tier Limitations:**
- 1,500 requests/day, 15 requests/minute, 1M tokens/minute
- Pro models may exhaust free tier quickly; Flash recommended for development

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

### AI Orchestrator (port 8002)
- **API Server**: `backend/services/ai-orchestrator/src/main.py`
- **Worker**: `backend/services/ai-orchestrator/src/worker.py`
- **Agent System**: Advanced AI workflow management with 4 specialized agents
- **Processing Modes**: Fast/Standard/Premium/Custom with automatic fallback
- **Cost Optimization**: Model selection and token usage optimization

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
- All inter-service communication via Kafka topics (`stt_requests`, `stt_results`, `ai_processing_requests`, `ai_processing_results`)
- WebSocket messages include progress, status, and comprehensive AI metadata
- AI processing triggered after STT completion with configurable workflow modes
- Enhanced segment data structure includes Japanese text, Korean translation, quality metrics, and AI-generated metadata (summaries, keywords, speaker info)

### Development Notes
- WebSocket connections can become stale - restart with `docker-compose down -v`
- Faster-Whisper models download on first container start
- Gemini models auto-initialize with fallback chain support
- Redis TTL manages message history cleanup
- Kafka auto-creates all topics including AI processing topics
- AI agents support hot-swapping between Gemini models for cost optimization

## Testing

- Frontend: Uses React Testing Library (`npm test`)
- Backend: No formal test suite currently implemented
- Manual testing via web interface at `http://localhost:3000`
- **AI Orchestrator Testing**:
  ```bash
  # Test AI agents status
  curl http://localhost:8080/api/ai/agents/status
  
  # Test translation processing
  curl -X POST http://localhost:8080/api/ai/process \
    -H "Content-Type: application/json" \
    -d '{"task_id":"test-123","segments":[{"text":"こんにちは","start":0,"end":2}],"mode":"fast"}'
  ```

## Common Issues

1. **WebSocket Connection Issues**: Run `docker-compose down -v` before restart
2. **AI Translation Not Working**: 
   - Verify `GEMINI_API_KEY` environment variable in `backend/.env`
   - Check Gemini API quota limits (switch to Flash model if Pro quota exceeded)
   - Monitor AI Orchestrator logs: `docker-compose logs -f ai-orchestrator-api`
3. **Audio Extraction Fails**: Check YouTube URL accessibility and yt-dlp compatibility
4. **STT Processing Slow**: Base model runs on CPU - consider GPU setup for production
5. **AI Processing Timeout**: Reduce concurrent tasks or switch to faster Gemini model
6. **High API Costs**: Use `gemini-1.5-flash-latest` for cost optimization (recommended)

## File Locations

- **Frontend Components**: `frontend/src/components/`, `frontend/src/pages/`
- **Backend Services**: `backend/services/[service-name]/src/`
- **AI Orchestrator**: 
  - **Agents**: `backend/services/ai-orchestrator/src/agents/`
  - **Chains**: `backend/services/ai-orchestrator/src/chains/`
  - **Configuration**: `backend/services/ai-orchestrator/src/config.py`
- **Docker Configuration**: `backend/docker-compose.yml`
- **Environment Files**: `frontend/.env`, `backend/.env`
- **Documentation**: `AI_ORCHESTRATOR_README.md` (detailed AI system guide)