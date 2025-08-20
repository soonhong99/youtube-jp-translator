"""
STT Processor API - AI Orchestrator 연동 버전
기존 번역 로직을 제거하고 AI Orchestrator에 위임
"""
import logging
import uuid
import asyncio
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from typing import Union, Dict, List, Any
from fastapi.middleware.cors import CORSMiddleware
import json
import time
import threading

# Kafka Producer/Consumer 설정
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from .kafka_config import KAFKA_BOOTSTRAP_SERVERS, STT_REQUEST_TOPIC, STT_RESULT_TOPIC

# AI Orchestrator 토픽
AI_PROCESSING_REQUEST_TOPIC = "ai_processing_requests"
AI_PROCESSING_RESULT_TOPIC = "ai_processing_results"

# WebSocket Manager 및 Redis Client
from .ws_manager import manager
from .redis_client import get_redis_client, get_message_ttl

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Kafka Producer 초기화 ---
producer = None
MAX_RETRIES = 5
RETRY_DELAY = 5

for attempt in range(MAX_RETRIES):
    try:
        logger.info(f"Attempting to initialize Kafka Producer (Attempt {attempt + 1}/{MAX_RETRIES})...")
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=3,
            acks='all',
        )
        logger.info(f"Kafka Producer connected successfully to {KAFKA_BOOTSTRAP_SERVERS}")
        break
    except KafkaError as e:
        logger.warning(f"Failed to initialize Kafka Producer (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY} seconds...")
        if attempt == MAX_RETRIES - 1:
            logger.error("Max retries reached. Failed to initialize Kafka Producer.", exc_info=True)
            producer = None
        time.sleep(RETRY_DELAY)
    except Exception as e:
         logger.error(f"Unexpected error during Kafka Producer initialization (Attempt {attempt + 1}): {e}", exc_info=True)
         producer = None
         break

# --- FastAPI 앱 생성 및 CORS 설정 ---
app = FastAPI(title="STT Processor API (AI Orchestrator 연동)", version="0.4.0")
origins = ["http://localhost", "http://localhost:3000", "http://localhost:3003"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- API 모델 정의 ---
class TranscriptionRequest(BaseModel):
    wav_file_path: str = Field(..., description="Path to the WAV file inside the container.")
    language: str = Field("ja", description="Language code (e.g., 'ja').")

class TranscriptionResponse(BaseModel):
    task_id: str = Field(..., description="Unique ID for the transcription task.")
    status: str = Field("Queued", description="Initial status of the task.")
    websocket_url: str = Field(..., description="Relative URL for WebSocket connection.")

# 전역 변수
consumer_thread = None
stop_consumer_event = threading.Event()
consumer = None

# --- 백그라운드 Consumer 루프 함수 ---
def _run_kafka_consumer_loop(consumer: KafkaConsumer, main_loop: asyncio.AbstractEventLoop):
    """
    백그라운드 스레드에서 실행될 Kafka Consumer 루프.
    STT 결과와 AI 처리 결과를 받아 WebSocket으로 전달
    """
    redis_client = get_redis_client()
    logger.info("Kafka Consumer thread started. Waiting for messages...")

    try:
        for message in consumer:
            if stop_consumer_event.is_set():
                logger.info("Stop event received by Kafka consumer thread, exiting loop.")
                break

            logger.info(f"[Thread] Message Received from Kafka: {message.topic}/{message.partition}/{message.offset}")

            try:
                result_data = message.value
                task_id = result_data.get('task_id')

                if not task_id:
                    logger.warning(f"[Thread] Received message without task_id: {result_data}")
                    continue 

                current_status = result_data.get("status", "UNKNOWN")
                logger.info(f"[Thread][Task {task_id}] Message received. Status: {current_status}, Progress: {result_data.get('progress')}")

                # --- 상태에 따른 처리 로직 ---
                if current_status == "STT_COMPLETED_ALL_SEGMENTS":
                    # STT 완료 -> AI Orchestrator로 전달
                    stt_segments = result_data.get("data")
                    
                    if isinstance(stt_segments, list):
                        if not stt_segments:
                            logger.info(f"[Thread][Task {task_id}] STT produced no segments. Finalizing as COMPLETED.")
                            result_data["status"] = "COMPLETED"
                            result_data["progress"] = 100
                            result_data["data"] = []
                        else:
                            logger.info(f"[Thread][Task {task_id}] Sending {len(stt_segments)} segments to AI Orchestrator")
                            
                            # AI Orchestrator로 번역 요청
                            ai_request = {
                                "task_id": task_id,
                                "type": "translation",
                                "segments": stt_segments,
                                "options": {
                                    "source_language": "ja",
                                    "target_language": "ko"
                                }
                            }
                            
                            try:
                                producer.send(
                                    AI_PROCESSING_REQUEST_TOPIC,
                                    value=ai_request,
                                    key=task_id.encode('utf-8')
                                )
                                producer.flush()
                                logger.info(f"[Thread][Task {task_id}] AI processing request sent")
                                
                                # 상태 업데이트
                                result_data["status"] = "STT_COMPLETED_AI_PROCESSING"
                                result_data["progress"] = 90
                                result_data["data"] = {"message": "STT completed, AI processing started"}
                                
                            except Exception as e_ai:
                                logger.error(f"[Thread][Task {task_id}] Failed to send AI request: {e_ai}")
                                result_data["status"] = "FAILED"
                                result_data["error"] = "Failed to start AI processing"
                    else:
                        logger.error(f"[Thread][Task {task_id}] Invalid STT data format")
                        result_data["status"] = "FAILED"
                        result_data["error"] = "Invalid STT segment data format"

                elif current_status == "AI_PROCESSING_COMPLETED":
                    # AI Orchestrator 처리 완료
                    logger.info(f"[Thread][Task {task_id}] AI processing completed")
                    ai_result = result_data.get("data", {})
                    
                    if "segments" in ai_result:
                        result_data["status"] = "COMPLETED"
                        result_data["progress"] = 100
                        result_data["data"] = ai_result["segments"]
                        
                        processing_info = ai_result.get("processing_info", {})
                        logger.info(f"[Thread][Task {task_id}] Final: {len(result_data['data'])} segments by {processing_info.get('model_name')} in {processing_info.get('processing_time', 0):.2f}s")
                    else:
                        result_data["status"] = "FAILED"
                        result_data["error"] = "AI processing completed but no valid result"

                elif current_status == "AI_PROCESSING_FAILED":
                    # AI Orchestrator 처리 실패
                    logger.error(f"[Thread][Task {task_id}] AI processing failed: {result_data.get('error')}")
                    result_data["status"] = "FAILED"

                elif current_status in ["PROCESSING", "FAILED"]:
                    # 중간 처리 상태나 실패 상태는 그대로 전달
                    logger.info(f"[Thread][Task {task_id}] Forwarding status: {current_status}")

                # --- WebSocket 및 Redis 저장 ---
                if main_loop and main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _send_ws_update_async(
                            task_id,
                            result_data.get("status"),
                            result_data.get("progress"),
                            result_data.get("data"),
                            result_data.get("error")
                        ),
                        main_loop
                    )

                if redis_client:
                    try:
                        redis_key = f"ws_messages:{task_id}"
                        message_json = json.dumps(result_data)
                        redis_client.rpush(redis_key, message_json)
                        redis_client.expire(redis_key, get_message_ttl())
                    except Exception as e_redis:
                        logger.error(f"[Thread][Task {task_id}] Redis save failed: {e_redis}")

            except Exception as e_msg:
                logger.error(f"[Thread] Error processing message: {e_msg}", exc_info=True)

    except Exception as e_loop:
        logger.error(f"Fatal error in consumer loop: {e_loop}", exc_info=True)
    finally:
        logger.info("Closing Kafka Consumer in thread.")
        if consumer:
            consumer.close()

# --- WebSocket 메시지 전송 함수 ---
async def _send_ws_update_async(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    """WebSocket 메시지 전송"""
    message = {"status": status}
    if progress is not None: message["progress"] = max(0, min(100, progress))
    if data is not None: message["data"] = data
    if error is not None: message["error"] = error
    
    try:
        if manager:
            await manager.send_json_message(task_id, message)
            logger.info(f"[Task {task_id}] WebSocket message sent: {status}")
    except Exception as e:
        logger.error(f"[Task {task_id}] WebSocket send failed: {e}")

# Health check 엔드포인트
@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    health_status = {
        "status": "healthy",
        "service": "stt-processor-api-v2",
        "timestamp": time.time(),
        "ai_orchestrator_integration": True
    }
    
    if producer:
        health_status["kafka_producer"] = "connected"
    else:
        health_status["kafka_producer"] = "disconnected"
        health_status["status"] = "degraded"
    
    redis_client = get_redis_client()
    if redis_client:
        try:
            redis_client.ping()
            health_status["redis"] = "connected"
        except:
            health_status["redis"] = "disconnected"
            health_status["status"] = "degraded"
    
    return health_status

# --- API 엔드포인트 ---
@app.post("/request_transcription", response_model=TranscriptionResponse, status_code=202)
async def request_transcription(request: TranscriptionRequest):
    if not producer:
        raise HTTPException(status_code=503, detail="Kafka Producer is not available.")
    if not os.path.exists(request.wav_file_path):
        raise HTTPException(status_code=404, detail=f"WAV file not found at: {request.wav_file_path}")

    task_id = str(uuid.uuid4())
    message = {
        "task_id": task_id,
        "wav_file_path": request.wav_file_path,
        "language": request.language,
        "request_time": asyncio.get_event_loop().time()
    }

    try:
        logger.info(f"Sending transcription request for task: {task_id}")
        producer.send(STT_REQUEST_TOPIC, value=message, key=task_id.encode('utf-8'))
        producer.flush()
        logger.info(f"Task {task_id} sent to Kafka")

        ws_url = f"/ws/{task_id}"
        return TranscriptionResponse(
            task_id=task_id,
            status="Queued",
            websocket_url=ws_url
        )
    except Exception as e:
        logger.error(f"Kafka request failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send request to Kafka.")

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket, task_id)
    redis_client = get_redis_client()
    redis_key = f"ws_messages:{task_id}"
    
    try:
        # Redis에서 이전 메시지 로딩
        if redis_client:
            try:
                past_messages = redis_client.lrange(redis_key, 0, -1)
                if past_messages:
                    logger.info(f"Sending {len(past_messages)} past messages to {task_id}")
                    for msg_json in past_messages:
                        msg_dict = json.loads(msg_json)
                        await websocket.send_json(msg_dict)
            except Exception as e:
                logger.error(f"Failed to load past messages: {e}")

        # 연결 유지
        while True:
            await asyncio.sleep(60)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client {task_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {task_id}: {e}")
    finally:
        manager.disconnect(task_id)

# --- 앱 시작/종료 이벤트 ---
@app.on_event("startup")
async def startup_event():
    global consumer_thread, consumer
    logger.info("Starting STT Processor API v2 with AI Orchestrator integration...")

    # Kafka Consumer 초기화 (두 토픽 모두 구독)
    consumer = None
    if KAFKA_BOOTSTRAP_SERVERS:
        for attempt in range(MAX_RETRIES):
            try:
                consumer = KafkaConsumer(
                    STT_RESULT_TOPIC,
                    AI_PROCESSING_RESULT_TOPIC,  # AI 결과도 구독
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    group_id='stt_result_consumers_api_v2',
                    auto_offset_reset='earliest',
                    enable_auto_commit=True,
                    consumer_timeout_ms=-1,
                )
                consumer.topics()
                logger.info(f"Kafka Consumer initialized for topics: {STT_RESULT_TOPIC}, {AI_PROCESSING_RESULT_TOPIC}")
                break
            except Exception as e:
                logger.error(f"Consumer init error (attempt {attempt + 1}): {e}")
                time.sleep(RETRY_DELAY)

        if consumer:
            logger.info("Starting Kafka consumer thread...")
            stop_consumer_event.clear()
            main_event_loop = asyncio.get_running_loop()
            consumer_thread = threading.Thread(
                target=_run_kafka_consumer_loop,
                args=(consumer, main_event_loop),
                daemon=True
            )
            consumer_thread.start()
            logger.info("Consumer thread started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down STT Processor API v2...")
    if consumer_thread and consumer_thread.is_alive():
        stop_consumer_event.set()
        consumer_thread.join(timeout=5)
    if producer:
        producer.close(timeout=5)