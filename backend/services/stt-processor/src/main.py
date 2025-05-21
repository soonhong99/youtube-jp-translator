import logging
import uuid # 고유 Task ID 생성용
import asyncio
import os
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, List, Any
from fastapi.middleware.cors import CORSMiddleware # 이 import 확인
import json
import time
import threading

# Kafka Producer/Consumer 설정
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from .kafka_config import (
    KAFKA_BOOTSTRAP_SERVERS, 
    STT_REQUEST_TOPIC, 
    STT_RESULT_TOPIC,
    TRANSLATION_REQUESTS_TOPIC, # New import
    TRANSLATION_RESULTS_TOPIC   # New import
)

# WebSocket Manager 및 Redis Client (메시지 히스토리용)
from .ws_manager import manager
from .redis_client import get_redis_client, get_message_ttl # Redis는 히스토리용으로 유지

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Kafka Producer 초기화 ---
# Producer는 비교적 가벼우므로 요청 시 생성하거나, 앱 시작 시 생성 가능
# 안정성을 위해 앱 시작 시 생성 권장
producer = None
MAX_RETRIES = 5 # 최대 재시도 횟수
RETRY_DELAY = 5 # 재시도 간격 (초)

for attempt in range(MAX_RETRIES):
    try:
        logger.info(f"Attempting to initialize Kafka Producer (Attempt {attempt + 1}/{MAX_RETRIES})...")
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=3, # Producer 내부 재시도 설정 (이것도 유지)
            acks='all',
            # Producer 생성 시 타임아웃 설정 (선택적)
            # request_timeout_ms=10000, # 예: 10초
            # api_version_auto_timeout_ms=10000
        )
        # 연결 테스트 (선택적이지만 확실한 확인 방법)
        # producer.partitions_for(STT_REQUEST_TOPIC) # 토픽 메타데이터 가져오기 시도
        logger.info(f"Kafka Producer connected successfully to {KAFKA_BOOTSTRAP_SERVERS}")
        break # 성공 시 루프 탈출
    except KafkaError as e:
        logger.warning(f"Failed to initialize Kafka Producer (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY} seconds...")
        if attempt == MAX_RETRIES - 1: # 마지막 재시도 실패 시 에러 로깅
            logger.error("Max retries reached. Failed to initialize Kafka Producer.", exc_info=True)
            producer = None # 확실히 None으로 설정
        time.sleep(RETRY_DELAY) # 다음 시도 전 대기
    except Exception as e:
         logger.error(f"Unexpected error during Kafka Producer initialization (Attempt {attempt + 1}): {e}", exc_info=True)
         producer = None # 확실히 None으로 설정
         # 예상치 못한 오류는 바로 루프 중단 고려 가능
         break

# --- FastAPI 앱 생성 및 CORS 설정 ---
app = FastAPI(title="Kafka-based STT Processor API", version="0.3.0")
# ... (CORS 미들웨어 설정은 이전과 동일하게 추가) ...
from fastapi.middleware.cors import CORSMiddleware
origins = ["http://localhost", "http://localhost:3000"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- API 모델 정의 ---
class TranscriptionRequest(BaseModel):
    wav_file_path: str = Field(..., description="Path to the WAV file inside the container.")
    language: str = Field("ja", description="Language code (e.g., 'ja').")

class TranscriptionResponse(BaseModel):
    task_id: str = Field(..., description="Unique ID for the transcription task.")
    status: str = Field("Queued", description="Initial status of the task.")
    websocket_url: str = Field(..., description="Relative URL for WebSocket connection.")
    # status_url: str = Field(..., description="Relative URL to poll for task status.")

# 전역 변수 (Consumer 스레드 및 종료 이벤트)
# For STT results
consumer_thread = None
stop_consumer_event = threading.Event()
consumer = None # Consumer 객체를 전역 또는 클래스 멤버로 관리

# For Translation results
translation_consumer_thread = None
stop_translation_consumer_event = threading.Event()
translation_consumer = None

# In-memory store for consolidating Japanese transcripts before sending for translation
# This is a simple approach. For production, consider Redis or another persistent store
# if the API restarts frequently or if transcripts are very large.
# Key: task_id, Value: list of Japanese text segments
task_stt_segments: Dict[str, List[str]] = {}


# --- 백그라운드 Consumer 루프 함수 ---
# (이 함수는 스레드에서 실행되므로 동기 함수로 정의)
def _run_kafka_consumer_loop(consumer: KafkaConsumer, main_loop: asyncio.AbstractEventLoop):
    """
    백그라운드 스레드에서 실행될 Kafka Consumer 루프.
    메인 asyncio 루프 객체를 인자로 받아 WebSocket 통신에 사용합니다.
    """
    # 스레드 내에서 필요한 클라이언트 등 얻기 (Redis 예시)
    redis_client = get_redis_client()
    logger.info("Kafka Consumer thread started. Waiting for messages from topic '{}'...".format(STT_RESULT_TOPIC))

    try:
        for message in consumer: # consumer_timeout_ms in consumer init makes this non-blocking if no messages
            if stop_consumer_event.is_set():
                logger.info("Stop event received, exiting STT result consumer loop.")
                break
            
            if message is None: # Handle case where poll times out
                continue

            logger.info(f"[STT Consumer Thread] Message Received: {message.topic}/{message.partition}/{message.offset}: key={message.key}")

            try:
                result_data = message.value
                task_id = result_data.get('task_id')
                status = result_data.get('status')
                data_segments = result_data.get('data') # This should be a list of segment dicts

                if not task_id:
                    logger.warning(f"[STT Consumer Thread] Received message without task_id: {result_data}")
                    continue

                logger.info(f"[STT Consumer Thread] Task {task_id}, Status: {status}")

                # --- Accumulate STT segments ---
                if status == "PROCESSING" and data_segments and isinstance(data_segments, list):
                    if task_id not in task_stt_segments:
                        task_stt_segments[task_id] = []
                    for segment in data_segments:
                        if isinstance(segment, dict) and 'text' in segment:
                            task_stt_segments[task_id].append(segment['text'])
                    logger.debug(f"[STT Consumer Thread] Appended {len(data_segments)} segments for task {task_id}. Total segments now: {len(task_stt_segments[task_id])}")

                # --- Handle STT Completion ---
                if status == "COMPLETED":
                    logger.info(f"[STT Consumer Thread] Task {task_id} COMPLETED. Consolidating transcript.")
                    full_japanese_transcript = ""
                    if task_id in task_stt_segments:
                        full_japanese_transcript = " ".join(task_stt_segments[task_id])
                        logger.info(f"[STT Consumer Thread] Consolidated transcript for task {task_id}: '{full_japanese_transcript[:200]}...'")
                        del task_stt_segments[task_id] # Clean up memory
                    else:
                        # Fallback: Check Redis history if in-memory store is empty (e.g. after API restart)
                        # This part assumes Redis stores STT segments in a way that can be reconstructed.
                        # The current Redis usage (rpush of full ws_messages) makes this complex.
                        # For simplicity, we'll rely on in-memory accumulation for now.
                        # If worker sends full transcript with "COMPLETED", this would be simpler.
                        logger.warning(f"[STT Consumer Thread] Task {task_id} COMPLETED, but no in-memory segments found. Attempting Redis fallback (if implemented).")
                        # --- Attempt to reconstruct from Redis (if needed and Redis stores segments appropriately) ---
                        # This is a simplified placeholder. Actual Redis structure for segments would be needed.
                        # if redis_client:
                        #     redis_key = f"ws_messages:{task_id}" # This key stores full WS messages, not just segments
                        #     past_messages_json = redis_client.lrange(redis_key, 0, -1)
                        #     temp_segments = []
                        #     for msg_json_str in past_messages_json:
                        #         msg_content = json.loads(msg_json_str)
                        #         if msg_content.get("status") == "PROCESSING" and msg_content.get("data"):
                        #             for seg in msg_content["data"]:
                        #                 if isinstance(seg, dict) and "text" in seg:
                        #                     temp_segments.append(seg["text"])
                        #     if temp_segments:
                        #         full_japanese_transcript = " ".join(temp_segments)
                        #         logger.info(f"[STT Consumer Thread] Reconstructed transcript from Redis for task {task_id}: '{full_japanese_transcript[:100]}...'")


                    if full_japanese_transcript and producer:
                        translation_request_message = {
                            "task_id": task_id,
                            "japanese_text": full_japanese_transcript
                        }
                        try:
                            producer.send(TRANSLATION_REQUESTS_TOPIC, key=task_id, value=translation_request_message)
                            producer.flush() # Ensure message is sent
                            logger.info(f"[STT Consumer Thread] Sent full transcript for task {task_id} to topic '{TRANSLATION_REQUESTS_TOPIC}'.")
                        except KafkaError as e:
                            logger.error(f"[STT Consumer Thread] Failed to send translation request for task {task_id} to Kafka: {e}", exc_info=True)
                        except Exception as e:
                            logger.error(f"[STT Consumer Thread] Unexpected error sending translation request for task {task_id}: {e}", exc_info=True)
                    elif not full_japanese_transcript:
                        logger.warning(f"[STT Consumer Thread] Task {task_id} COMPLETED, but no transcript was consolidated. Translation request not sent.")
                    elif not producer:
                        logger.error(f"[STT Consumer Thread] Kafka producer not available. Cannot send translation request for task {task_id}.")


                # --- WebSocket Update & Redis History ---
                if main_loop and main_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        _send_ws_update_async(
                            task_id,
                            status,
                            result_data.get("progress"),
                            data_segments, # Send original segments for STT display
                            result_data.get("error")
                        ),
                        main_loop
                    )
                    # Optionally handle future.result() with timeout for debugging

                if redis_client: # Save original message to Redis history
                    try:
                        redis_key = f"ws_messages:{task_id}"
                        # result_data already contains the full message payload for STT
                        message_json_to_store = json.dumps(result_data) 
                        redis_client.rpush(redis_key, message_json_to_store)
                        redis_client.expire(redis_key, get_message_ttl())
                        logger.debug(f"[STT Consumer Thread] Saved original STT message to Redis for task {task_id}")
                    except Exception as e:
                        logger.error(f"[STT Consumer Thread] Failed to save STT message to Redis for {task_id}: {e}", exc_info=True)

            except json.JSONDecodeError:
                 logger.error(f"[STT Consumer Thread] Failed to decode STT message value: {message.value}", exc_info=True)
            except Exception as e:
                logger.error(f"[STT Consumer Thread] Error processing STT message: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Unexpected error in STT Kafka Consumer loop: {e}", exc_info=True)
    finally:
        logger.info("Closing STT Kafka Consumer in thread.")
        if consumer: # Ensure consumer exists before closing
            consumer.close()

# --- Kafka Consumer Loop for Translation Results ---
def _run_translation_result_consumer_loop(consumer_instance: KafkaConsumer, main_loop: asyncio.AbstractEventLoop):
    logger.info("Translation Result Kafka Consumer thread started. Waiting for messages from topic '{}'...".format(TRANSLATION_RESULTS_TOPIC))
    redis_client = get_redis_client() # For saving translation results to history (optional)

    try:
        for message in consumer_instance: # consumer_timeout_ms makes this non-blocking
            if stop_translation_consumer_event.is_set():
                logger.info("Stop event received, exiting translation result consumer loop.")
                break

            if message is None: # Handle poll timeout
                continue
            
            logger.info(f"[Translation Consumer Thread] Message Received: {message.topic}/{message.partition}/{message.offset}: key={message.key}")

            try:
                result_data = message.value
                task_id = result_data.get('task_id')
                status = result_data.get('status') # "TRANSLATED", "TRANSLATION_ERROR"
                korean_text = result_data.get('korean_text')
                error_message = result_data.get('error_message')

                if not task_id:
                    logger.warning(f"[Translation Consumer Thread] Received message without task_id: {result_data}")
                    continue
                
                logger.info(f"[Translation Consumer Thread] Task {task_id}, Status: {status}")

                # Send to WebSocket
                if main_loop and main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        _send_ws_translation_update_async(
                            task_id,
                            status,
                            korean_text,
                            error_message
                        ),
                        main_loop
                    )
                
                # Save to Redis history (optional, similar to STT results)
                if redis_client:
                    try:
                        # Construct a payload consistent with what frontend might expect for history
                        history_payload = {
                            "task_id": task_id,
                            "type": "translation", # To distinguish in history
                            "status": status,
                            "korean_text": korean_text,
                            "error": error_message,
                            "timestamp": time.time() # Optional: add a timestamp
                        }
                        redis_key = f"ws_messages:{task_id}" # Append to the same history list
                        message_json_to_store = json.dumps(history_payload)
                        redis_client.rpush(redis_key, message_json_to_store)
                        # TTL is managed by STT consumer for the whole list
                        logger.debug(f"[Translation Consumer Thread] Saved translation message to Redis for task {task_id}")
                    except Exception as e:
                        logger.error(f"[Translation Consumer Thread] Failed to save translation message to Redis for {task_id}: {e}", exc_info=True)

            except json.JSONDecodeError:
                logger.error(f"[Translation Consumer Thread] Failed to decode translation message value: {message.value}", exc_info=True)
            except Exception as e:
                logger.error(f"[Translation Consumer Thread] Error processing translation message: {e}", exc_info=True)
                
    except Exception as e:
        logger.error(f"Unexpected error in Translation Kafka Consumer loop: {e}", exc_info=True)
    finally:
        logger.info("Closing Translation Kafka Consumer in thread.")
        if consumer_instance: # Ensure consumer_instance exists
            consumer_instance.close()

# --- 앱 시작 시 Kafka Consumer 스레드 실행 ---
@app.on_event("startup")
async def startup_event():
    global consumer_thread, consumer, translation_consumer_thread, translation_consumer # 전역 변수 사용
    logger.info("Application starting up...")

    # Kafka Consumer 초기화 (재시도 로직 포함)
    # Initialize STT Result Consumer
    consumer = None
    if KAFKA_BOOTSTRAP_SERVERS:
        MAX_RETRIES_INIT = 3 # Reduced retries for faster startup in dev, adjust for prod
        RETRY_DELAY_INIT = 3
        for attempt in range(MAX_RETRIES_INIT):
            try:
                logger.info(f"Attempting to initialize STT Result Kafka Consumer (Attempt {attempt + 1}/{MAX_RETRIES_INIT})...")
                consumer = KafkaConsumer(
                    STT_RESULT_TOPIC, 
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    key_deserializer=lambda k: k.decode('utf-8') if k else None,
                    group_id='stt_result_consumers_api', 
                    auto_offset_reset='earliest', 
                    enable_auto_commit=True, 
                    consumer_timeout_ms=1000 # To allow periodic check of stop_event
                )
                consumer.topics() 
                logger.info(f"STT Result Kafka Consumer initialized successfully for topic: {STT_RESULT_TOPIC}")
                break 
            except KafkaError as e:
                logger.warning(f"STT Result Kafka Consumer initialization error (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY_INIT} seconds...")
                if attempt == MAX_RETRIES_INIT - 1:
                    logger.error("Max retries reached. Failed to initialize STT Result Kafka Consumer.")
                    consumer = None
                time.sleep(RETRY_DELAY_INIT)
            except Exception as e:
                 logger.error(f"Unexpected error during STT Result Kafka Consumer initialization (Attempt {attempt + 1}): {e}", exc_info=True)
                 consumer = None
                 break 

        if consumer:
            logger.info("Starting STT Kafka result consumer thread...")
            stop_consumer_event.clear()
            try:
                main_event_loop = asyncio.get_running_loop()
                consumer_thread = threading.Thread(
                    target=_run_kafka_consumer_loop,
                    args=(consumer, main_event_loop,),
                    daemon=True 
                )
                consumer_thread.start()
                logger.info("STT Kafka result consumer thread started successfully.")
            except RuntimeError as e:
                 logger.error(f"Could not get running event loop to start STT result consumer thread: {e}", exc_info=True)
                 if consumer: consumer.close()
        else:
             logger.error("STT Result Kafka Consumer could not be initialized. Background STT result processing will not start.")

        # Initialize Translation Result Consumer
        translation_consumer = None
        for attempt in range(MAX_RETRIES_INIT):
            try:
                logger.info(f"Attempting to initialize Translation Result Kafka Consumer (Attempt {attempt + 1}/{MAX_RETRIES_INIT})...")
                translation_consumer = KafkaConsumer(
                    TRANSLATION_RESULTS_TOPIC, 
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    key_deserializer=lambda k: k.decode('utf-8') if k else None,
                    group_id='stt_api_translation_result_consumers', # New group ID
                    auto_offset_reset='earliest', 
                    enable_auto_commit=True,
                    consumer_timeout_ms=1000 # To allow periodic check of stop_event
                )
                translation_consumer.topics()
                logger.info(f"Translation Result Kafka Consumer initialized successfully for topic: {TRANSLATION_RESULTS_TOPIC}")
                break
            except KafkaError as e:
                logger.warning(f"Translation Result Kafka Consumer initialization error (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY_INIT} seconds...")
                if attempt == MAX_RETRIES_INIT - 1:
                    logger.error("Max retries reached. Failed to initialize Translation Result Kafka Consumer.")
                    translation_consumer = None
                time.sleep(RETRY_DELAY_INIT)
            except Exception as e:
                 logger.error(f"Unexpected error during Translation Result Kafka Consumer initialization (Attempt {attempt + 1}): {e}", exc_info=True)
                 translation_consumer = None
                 break
        
        if translation_consumer:
            logger.info("Starting Kafka translation result consumer thread...")
            stop_translation_consumer_event.clear()
            try:
                main_event_loop = asyncio.get_running_loop() # Should be the same loop
                translation_consumer_thread = threading.Thread(
                    target=_run_translation_result_consumer_loop, # New loop function
                    args=(translation_consumer, main_event_loop,),
                    daemon=True
                )
                translation_consumer_thread.start()
                logger.info("Kafka translation result consumer thread started successfully.")
            except RuntimeError as e:
                 logger.error(f"Could not get running event loop to start translation result consumer thread: {e}", exc_info=True)
                 if translation_consumer: translation_consumer.close()
        else:
            logger.error("Translation Result Kafka Consumer could not be initialized. Background translation result processing will not start.")
            
    else:
         logger.error("Kafka bootstrap servers not configured. Result consumers cannot start.")



# --- 앱 종료 시 처리 ---
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down...")
    # Stop STT result consumer
    if consumer_thread and consumer_thread.is_alive():
        logger.info("Signaling STT result Kafka consumer thread to stop...")
        stop_consumer_event.set()
        consumer_thread.join(timeout=5) 
        if consumer_thread.is_alive():
            logger.warning("STT result Kafka consumer thread did not stop gracefully after 5 seconds.")
        else:
             logger.info("STT result Kafka consumer thread stopped.")
    else:
        logger.info("STT result Kafka consumer thread was not running or already stopped.")

    # Stop Translation result consumer
    if translation_consumer_thread and translation_consumer_thread.is_alive():
        logger.info("Signaling Translation result Kafka consumer thread to stop...")
        stop_translation_consumer_event.set()
        translation_consumer_thread.join(timeout=5)
        if translation_consumer_thread.is_alive():
            logger.warning("Translation result Kafka consumer thread did not stop gracefully after 5 seconds.")
        else:
            logger.info("Translation result Kafka consumer thread stopped.")
    else:
        logger.info("Translation result Kafka consumer thread was not running or already stopped.")

    if producer:
        logger.info("Closing Kafka Producer.")
        producer.close(timeout=5) 

# --- WebSocket 메시지 전송 함수 (async def 로 정의) ---
# (이 함수는 메인 이벤트 루프에서 실행될 것이므로 async def 유지)
async def _send_ws_update_async(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    """비동기적으로 WebSocket 메시지를 전송하는 내부 함수"""
    # This function is for STT updates
    ws_payload = {"task_id": task_id, "type": "stt", "status": status}
    if progress is not None: ws_payload["progress"] = max(0, min(100, progress))
    if data is not None: ws_payload["data"] = data # This data is STT segments
    if error is not None: ws_payload["error"] = error
    
    try:
        if manager:
            # logger.debug(f"Sending STT WS update for {task_id}: Status {status}, Data type: {type(data)}")
            await manager.send_json_message(task_id, ws_payload)
        else:
            logger.warning(f"[Task {task_id}] WebSocket manager not available, skipping STT live send.")
    except Exception as e:
        logger.error(f"[Task {task_id}] Failed to send STT WebSocket update ({status}): {e}")


async def _send_ws_translation_update_async(task_id: str, status: str, korean_text: str = None, error: str = None):
    """비동기적으로 WebSocket으로 번역 결과를 전송하는 내부 함수"""
    ws_payload = {
        "task_id": task_id,
        "type": "translation", # New type
        "status": status, # "TRANSLATED" or "TRANSLATION_ERROR"
    }
    if korean_text:
        ws_payload["korean_text"] = korean_text
    if error:
        ws_payload["error"] = error
    
    try:
        if manager:
            # logger.debug(f"Sending Translation WS update for {task_id}: Status {status}")
            await manager.send_json_message(task_id, ws_payload)
        else:
            logger.warning(f"[Task {task_id}] WebSocket manager not available, skipping translation live send.")
    except Exception as e:
        logger.error(f"[Task {task_id}] Failed to send translation WebSocket update ({status}): {e}")


# --- API 엔드포인트 수정 ---
@app.post("/request_transcription", response_model=TranscriptionResponse, status_code=202, summary="Request Transcription via Kafka")
async def request_transcription(request: TranscriptionRequest):
    if not producer:
        raise HTTPException(status_code=503, detail="Kafka Producer is not available.")
    if not os.path.exists(request.wav_file_path):
        raise HTTPException(status_code=404, detail=f"WAV file not found at: {request.wav_file_path}")

    task_id = str(uuid.uuid4()) # Kafka 메시지 구분을 위한 고유 ID (이전 task_id 역할)
    message = {
        "task_id": task_id,
        "wav_file_path": request.wav_file_path,
        "language": request.language,
        "request_time": asyncio.get_event_loop().time() # 요청 시간 (선택적)
    }

    try:
        logger.info(f"Sending transcription request to Kafka topic '{STT_REQUEST_TOPIC}' for task ID: {task_id}")
        # Kafka 토픽으로 메시지 전송
        future = producer.send(STT_REQUEST_TOPIC, value=message, key=task_id.encode('utf-8')) # key 설정 시 파티션 분배에 영향
        # 전송 결과 확인 (선택적, 비동기 방식)
        # future.add_callback(on_send_success)
        # future.add_errback(on_send_error)
        producer.flush() # 메시지 즉시 전송 시도 (운영 환경에서는 배치 전송 고려)
        logger.info(f"Request for task {task_id} sent to Kafka.")

        ws_url = f"/ws/{task_id}"
        # status_url은 Kafka 환경에서 단순 조회가 어려우므로 다르게 구현하거나 제외

        return TranscriptionResponse(
            task_id=task_id,
            status="Queued", # Kafka에 발행되었음을 의미
            websocket_url=ws_url,
            status_url="" # 임시로 비워둠
        )
    except KafkaError as e:
        logger.error(f"Failed to send message to Kafka: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error: Could not send request to Kafka.")
    except Exception as e:
        logger.error(f"Unexpected error during Kafka request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for clients to receive real-time transcription updates."""
    await manager.connect(websocket, task_id)
    redis_client = get_redis_client()
    redis_key = f"ws_messages:{task_id}"
    initial_send_failed = False
    try:
        # Redis에서 이전 메시지 로딩 (구현은 이전 답변과 동일)
        if redis_client:
            try:
                logger.info(f"Retrieving past messages for {task_id} from Redis key {redis_key}")
                past_messages_json = redis_client.lrange(redis_key, 0, -1)
                if past_messages_json:
                     logger.info(f"Sending {len(past_messages_json)} past messages to client {task_id}")
                     for msg_json in past_messages_json:
                         try:
                             msg_dict = json.loads(msg_json)
                             await websocket.send_json(msg_dict)
                         except Exception as send_err:
                             logger.warning(f"Error sending past message to {task_id}: {send_err}")
                             initial_send_failed = True; break
                     if not initial_send_failed: logger.info(f"Finished sending past messages for {task_id}.")
                else: logger.info(f"No past messages found in Redis for task {task_id}.")
            except Exception as redis_err: logger.error(f"Failed to retrieve past messages from Redis: {redis_err}")

        # 연결 유지 (실시간 메시지는 백그라운드 Kafka Consumer가 manager를 통해 전송)
        if not initial_send_failed:
            while True:
                await asyncio.sleep(60)

    except WebSocketDisconnect: logger.info(f"WebSocket client for task {task_id} disconnected.")
    except Exception as e: logger.error(f"WebSocket error for task {task_id}: {e}", exc_info=True)
    finally: manager.disconnect(task_id)

# 재설계 필요
# @app.get("/status/{task_id}", summary="Get Task Status (Polling)")
# async def get_task_status(task_id: str):
#     """Retrieves the current status and result (if available) of a transcription task."""
#     # Celery의 AsyncResult를 사용하여 작업 상태 확인
#     task_result = celery_app.AsyncResult(task_id) # 주의: Celery 내부 Task ID 사용 시 필요

#     # API 레벨 Task ID를 사용하므로, 상태는 Redis 등에 별도 저장/조회 필요
#     # 여기서는 간단히 Celery 백엔드 조회 예시를 보여주지만, 실제로는 task_id 매핑 필요
#     # 또는 Celery 작업 ID를 저장해두었다가 사용
#     # -> 여기서는 Redis에 task_id 별 상태를 저장하는 방식이 더 적합

#     # 임시 예시: 실제로는 Redis 등에서 task_id로 상태 조회
#     status_info = {"status": "UNKNOWN", "progress": None, "result": None, "error": None}
#     try:
#          # 예시: Redis에서 task_id 관련 정보 가져오기 (구현 필요)
#          # status_data_json = redis_client.get(f"task_status:{task_id}")
#          # if status_data_json:
#          #    status_info = json.loads(status_data_json)
#          pass # 실제 구현 필요
#     except Exception as e:
#          logger.error(f"Failed to get status for task {task_id} from storage: {e}")
#          # 상태 조회 실패 시 기본값 반환 또는 오류 처리


#     # Celery Task 상태 확인 (만약 Celery task ID를 안다면)
#     # celery_task_id = get_celery_task_id_for_api_task(task_id) # DB 등에서 조회
#     # if celery_task_id:
#     #     celery_task = celery_app.AsyncResult(celery_task_id)
#     #     status_info['celery_status'] = celery_task.status
#     #     if celery_task.ready():
#     #         if celery_task.successful():
#     #             status_info['result'] = celery_task.result
#     #         else:
#     #             status_info['error'] = str(celery_task.info) # 실패 정보

#     if status_info["status"] == "UNKNOWN":
#          raise HTTPException(status_code=404, detail="Task not found or status not available yet.")

#     return status_info

# 앱 초기화 시 로거 설정 등 추가 가능
# @app.on_event("startup")
# async def startup_event():
#     pass

# @app.on_event("shutdown")
# async def shutdown_event():
#     pass