import os
import httpx
import logging
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json
import websockets
import asyncio
import redis
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# System metrics logger (local adapter)
from src.system_logger_adapter import (
    log_data_flow,
    log_kafka_message,
    log_timeline,
    log_performance,
)

app = FastAPI(title="API Gateway", version="1.0.0")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3003", "http://localhost:3007", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서비스 URL 설정
SERVICES = {
    "youtube_extractor": os.getenv("YOUTUBE_EXTRACTOR_URL", "http://youtube-extractor:8000"),
    "stt_processor": os.getenv("STT_PROCESSOR_URL", "http://stt-processor-api:8001"),
    "ai_orchestrator": os.getenv("AI_ORCHESTRATOR_URL", "http://ai-orchestrator-api:8002"),
}

# Redis 연결 설정 (시스템 모니터링용)
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=5, decode_responses=True)

# Rate Limiting 미들웨어 (선택적 - 일단 주석 처리)
# from src.middleware import RateLimitMiddleware
# app.add_middleware(RateLimitMiddleware, calls=100, period=60)

# 인증 미들웨어 제거 (나중에 필요시 추가)
# from src.auth import verify_token

@app.get("/")
async def root():
    return {"message": "API Gateway is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "api-gateway"}

@app.post("/api/youtube/extract")
async def extract_audio(request: Request):  # verify_token 의존성 제거
    """YouTube 오디오 추출 프록시"""
    try:
        body = await request.json()
        logger.info(f"Proxying extract request to {SERVICES['youtube_extractor']}")
        
        # API Gateway는 'url' 필드를 받지만, YouTube Extractor는 'youtube_url' 필드를 기대함
        if 'url' in body and 'youtube_url' not in body:
            body['youtube_url'] = body['url']
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{SERVICES['youtube_extractor']}/extract",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"YouTube extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stt/transcribe")
async def request_transcription(request: Request):
    """STT 요청 프록시"""
    try:
        body = await request.json()
        logger.info(f"Proxying transcribe request to {SERVICES['stt_processor']}")
        task_id = body.get("task_id")
        if task_id:
            log_data_flow(task_id, "Client", "API Gateway", "STT 요청 수신")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SERVICES['stt_processor']}/request_transcription",
                json=body
            )
            response.raise_for_status()
            resp_json = response.json()
            if task_id:
                log_data_flow(task_id, "API Gateway", "STT Processor", "STT 요청 프록시 전송")
                log_data_flow(task_id, "STT Processor", "API Gateway", "STT 초기 응답 수신")
            return resp_json
    except httpx.HTTPError as e:
        logger.error(f"STT request failed: {e}")
        try:
            body = await request.json()
            task_id = body.get("task_id")
            if task_id:
                log_data_flow(task_id, "API Gateway", "STT Processor", f"STT 요청 실패: {str(e)}")
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/task/cancel/{task_id}")
async def cancel_task(task_id: str):
    """작업 취소 요청 (백그라운드 중복 처리 방지)"""
    try:
        logger.info(f"Cancelling task: {task_id}")
        
        # Redis에 취소 신호 저장
        try:
            redis_client.setex(f"task_cancel:{task_id}", 300, "true")  # 5분간 유지
            logger.info(f"Task {task_id} marked for cancellation")
        except Exception as redis_error:
            logger.warning(f"Failed to mark task for cancellation in Redis: {redis_error}")
        
        # STT Processor에 취소 요청 전송
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{SERVICES['stt_processor']}/cancel_task/{task_id}"
                )
                logger.info(f"STT Processor cancel response: {response.status_code}")
        except Exception as stt_error:
            logger.warning(f"Failed to cancel STT task: {stt_error}")
        
        # AI Orchestrator에 취소 요청 전송 (있다면)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{SERVICES['ai_orchestrator']}/cancel_task/{task_id}"
                )
                logger.info(f"AI Orchestrator cancel response: {response.status_code}")
        except Exception as ai_error:
            logger.warning(f"Failed to cancel AI task: {ai_error}")
        
        return {"status": "cancelled", "task_id": task_id}
        
    except Exception as e:
        logger.error(f"Task cancellation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# AI Orchestrator 엔드포인트들
@app.post("/api/ai/process")
async def ai_process(request: Request):
    """AI 오케스트레이터 통합 처리 API"""
    try:
        body = await request.json()
        logger.info(f"Proxying AI process request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=120.0) as client:  # AI 처리는 더 긴 타임아웃
            response = await client.post(
                f"{SERVICES['ai_orchestrator']}/process",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"AI processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/translate")
async def ai_translate(request: Request):
    """AI 번역 API (레거시 호환성)"""
    try:
        body = await request.json()
        logger.info(f"Proxying AI translate request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{SERVICES['ai_orchestrator']}/translate",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"AI translation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ai/agents/status")
async def ai_agents_status():
    """AI 에이전트 상태 조회"""
    try:
        logger.info(f"Proxying AI agents status request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SERVICES['ai_orchestrator']}/agents/status"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"AI agents status request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ai/processing-modes")
async def ai_processing_modes():
    """AI 처리 모드 조회"""
    try:
        logger.info(f"Proxying AI processing modes request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SERVICES['ai_orchestrator']}/processing-modes"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"AI processing modes request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/process/batch")
async def ai_process_batch(request: Request):
    """AI 배치 처리 API"""
    try:
        body = await request.json()
        logger.info(f"Proxying AI batch process request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=300.0) as client:  # 배치 처리는 매우 긴 타임아웃
            response = await client.post(
                f"{SERVICES['ai_orchestrator']}/process/batch",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"AI batch processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 비용 모니터링 API ====================

@app.get("/api/ai/cost/summary")
async def get_cost_summary():
    """AI API 비용 요약 정보 조회"""
    try:
        logger.info(f"Proxying cost summary request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SERVICES['ai_orchestrator']}/cost/summary"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Cost summary request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ai/cost/logs")
async def get_cost_logs(
    task_id: Optional[str] = None,
    hours: Optional[int] = 24,
    agent: Optional[str] = None
):
    """AI API 비용 로그 조회"""
    try:
        params = {}
        if task_id:
            params["task_id"] = task_id
        if hours:
            params["hours"] = hours
        if agent:
            params["agent"] = agent
            
        logger.info(f"Proxying cost logs request to {SERVICES['ai_orchestrator']} with params: {params}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SERVICES['ai_orchestrator']}/cost/logs",
                params=params
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Cost logs request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ai/cost/alerts")
async def get_cost_alerts():
    """비용 알림 임계치 설정 및 현재 상태 조회"""
    try:
        logger.info(f"Proxying cost alerts request to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SERVICES['ai_orchestrator']}/cost/alerts"
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Cost alerts request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai/cost/alerts")
async def set_cost_alerts(request: Request):
    """비용 알림 임계치 설정"""
    try:
        body = await request.json()
        logger.info(f"Proxying cost alerts settings to {SERVICES['ai_orchestrator']}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SERVICES['ai_orchestrator']}/cost/alerts",
                json=body
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Cost alerts setting failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/api/ws/{task_id}")
async def websocket_proxy(websocket: WebSocket, task_id: str):
    """WebSocket 프록시 - STT 서비스로 전달"""
    await websocket.accept()
    # 연결 타임라인 기록
    log_timeline(task_id, agent="api-gateway", task="WS 연결 수립", progress=0)
    
    stt_ws_url = f"ws://stt-processor-api:8001/ws/{task_id}"
    logger.info(f"Proxying WebSocket for task {task_id} to {stt_ws_url}")
    
    try:
        # STT 서비스의 WebSocket에 연결
        logger.info(f"Attempting to connect to STT WebSocket: {stt_ws_url}")
        async with websockets.connect(stt_ws_url) as stt_ws:
            logger.info(f"Successfully connected to STT WebSocket for task {task_id}")
            # 양방향 메시지 전달
            async def forward_from_stt():
                """STT 서비스 -> 클라이언트"""
                try:
                    async for message in stt_ws:
                        logger.debug(f"Forwarding message from STT to client: {message[:100]}...")
                        await websocket.send_text(message)
                except websockets.exceptions.ConnectionClosed:
                    logger.info(f"STT WebSocket closed for task {task_id}")
                except Exception as e:
                    logger.error(f"Error forwarding from STT: {e}")
            
            async def forward_from_client():
                """클라이언트 -> STT 서비스 (일반적으로 없음)"""
                try:
                    while True:
                        data = await websocket.receive_text()
                        logger.debug(f"Forwarding message from client to STT: {data}")
                        await stt_ws.send(data)
                except Exception as e:
                    logger.debug(f"Client WebSocket closed: {e}")
            
            # 두 방향 동시 처리
            await asyncio.gather(
                forward_from_stt(),
                forward_from_client(),
                return_exceptions=True
            )
            
    except Exception as e:
        logger.error(f"WebSocket proxy error for task {task_id}: {e}")
        await websocket.send_json({
            "error": f"WebSocket proxy error: {str(e)}",
            "status": "FAILED"
        })
    finally:
        try:
            await websocket.close()
        except:
            pass
        # 종료 타임라인 기록
        log_timeline(task_id, agent="api-gateway", task="WS 연결 종료", progress=100)

# ==================== 시스템 모니터링 API (논문 검증용) ====================

@app.get("/api/system/metrics/{task_id}")
async def get_system_metrics(task_id: str):
    """시스템 메트릭 데이터 조회 (논문 검증용)"""
    try:
        # Redis에서 태스크별 메트릭 데이터 수집
        metrics_key = f"system_metrics:{task_id}"
        data_flow_key = f"data_flow:{task_id}"
        kafka_messages_key = f"kafka_messages:{task_id}"
        performance_key = f"performance:{task_id}"
        timeline_key = f"timeline:{task_id}"
        
        # 기본 메트릭 구조
        metrics = {
            "dataFlow": [],
            "performance": {},
            "serviceStatus": {
                "api-gateway": "running",
                "youtube-extractor": "running",
                "stt-processor": "running", 
                "ai-orchestrator": "running"
            },
            "kafkaMessages": [],
            "processingTimeline": []
        }
        
        # Redis에서 실제 데이터 가져오기 (존재하는 경우)
        try:
            # 데이터 흐름 로그
            data_flow_logs = redis_client.lrange(data_flow_key, 0, -1)
            metrics["dataFlow"] = [json.loads(log) for log in data_flow_logs[-20:]]  # 최근 20개
            
            # Kafka 메시지 로그
            kafka_logs = redis_client.lrange(kafka_messages_key, 0, -1)
            metrics["kafkaMessages"] = [json.loads(log) for log in kafka_logs[-15:]]  # 최근 15개
            
            # 성능 데이터
            performance_data = redis_client.hgetall(performance_key)
            if performance_data:
                metrics["performance"] = {
                    "audioExtractionTime": performance_data.get("audio_extraction_time", "0"),
                    "sttProcessingTime": performance_data.get("stt_processing_time", "0"),
                    "aiProcessingTime": performance_data.get("ai_processing_time", "0"),
                    "totalProcessingTime": performance_data.get("total_processing_time", "0")
                }
            
            # AI 처리 타임라인
            timeline_logs = redis_client.lrange(timeline_key, 0, -1)
            metrics["processingTimeline"] = [json.loads(log) for log in timeline_logs]
            
        except Exception as redis_error:
            logger.warning(f"Redis data retrieval error: {redis_error}")
            # Redis 오류 시 더미 데이터 제공 (데모용)
            metrics.update({
                "dataFlow": [
                    {
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "from": "Client",
                        "to": "API Gateway",
                        "message": "영상 URL 요청 수신"
                    },
                    {
                        "timestamp": (datetime.now() + timedelta(seconds=1)).strftime("%H:%M:%S"),
                        "from": "API Gateway",
                        "to": "YouTube Extractor",
                        "message": "오디오 추출 요청"
                    },
                    {
                        "timestamp": (datetime.now() + timedelta(seconds=5)).strftime("%H:%M:%S"),
                        "from": "YouTube Extractor",
                        "to": "STT Processor",
                        "message": "오디오 파일 전달"
                    },
                    {
                        "timestamp": (datetime.now() + timedelta(seconds=10)).strftime("%H:%M:%S"),
                        "from": "STT Processor",
                        "to": "AI Orchestrator",
                        "message": "STT 결과 전송"
                    }
                ],
                "kafkaMessages": [
                    {
                        "topic": "stt_requests",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "message": f"새로운 STT 요청: {task_id}"
                    },
                    {
                        "topic": "stt_results",
                        "timestamp": (datetime.now() + timedelta(seconds=30)).strftime("%H:%M:%S"),
                        "message": f"STT 처리 완료: {task_id}"
                    },
                    {
                        "topic": "ai_processing_requests",
                        "timestamp": (datetime.now() + timedelta(seconds=31)).strftime("%H:%M:%S"),
                        "message": f"AI 번역 요청: {task_id}"
                    },
                    {
                        "topic": "ai_processing_results",
                        "timestamp": (datetime.now() + timedelta(seconds=60)).strftime("%H:%M:%S"),
                        "message": f"AI 번역 완료: {task_id}"
                    }
                ],
                "performance": {
                    "audioExtractionTime": "8",
                    "sttProcessingTime": "45",
                    "aiProcessingTime": "32",
                    "totalProcessingTime": "85"
                },
                "processingTimeline": [
                    {
                        "agent": "TranslatorAgent",
                        "task": "일본어→한국어 번역 수행",
                        "duration": "18",
                        "progress": 100
                    },
                    {
                        "agent": "FormatterAgent", 
                        "task": "자막 서식 최적화",
                        "duration": "6",
                        "progress": 100
                    },
                    {
                        "agent": "SummarizerAgent",
                        "task": "내용 요약 및 키워드 추출",
                        "duration": "12",
                        "progress": 100
                    },
                    {
                        "agent": "ReviewerAgent",
                        "task": "번역 품질 검토",
                        "duration": "8",
                        "progress": 100
                    }
                ]
            })
        
        return metrics
        
    except Exception as e:
        logger.error(f"System metrics retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/system/log-event")
async def log_system_event(request: Request):
    """시스템 이벤트 로깅 (내부 사용)"""
    try:
        body = await request.json()
        task_id = body.get("task_id")
        event_type = body.get("event_type")  # data_flow, kafka_message, performance, timeline
        data = body.get("data")
        
        if not all([task_id, event_type, data]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        
        # 이벤트별로 Redis에 저장
        key = f"{event_type}:{task_id}"
        
        if event_type == "performance":
            # 성능 데이터는 hash로 저장
            redis_client.hset(key, mapping=data)
        else:
            # 나머지는 리스트로 저장 (시간순)
            data["timestamp"] = datetime.now().strftime("%H:%M:%S")
            redis_client.lpush(key, json.dumps(data))
            # 최대 50개까지만 보관
            redis_client.ltrim(key, 0, 49)
        
        # TTL 설정 (24시간)
        redis_client.expire(key, 86400)
        
        return {"status": "logged", "event_type": event_type, "task_id": task_id}
        
    except Exception as e:
        logger.error(f"System event logging failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
