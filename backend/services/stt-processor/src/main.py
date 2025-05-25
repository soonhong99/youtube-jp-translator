import logging
import uuid # 고유 Task ID 생성용
import asyncio
import google.generativeai as genai
import os
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Union, Dict, List, Any
from fastapi.middleware.cors import CORSMiddleware # 이 import 확인
import json
import time
import threading

# Kafka Producer/Consumer 설정
from kafka import KafkaProducer, KafkaConsumer
from kafka.errors import KafkaError
from .kafka_config import KAFKA_BOOTSTRAP_SERVERS, STT_REQUEST_TOPIC, STT_RESULT_TOPIC

# WebSocket Manager 및 Redis Client (메시지 히스토리용)
from .ws_manager import manager
from .redis_client import get_redis_client, get_message_ttl # Redis는 히스토리용으로 유지

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수에서 Gemini API 키 로드
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini API Key configured successfully.")
        # 번역에 사용할 모델 인스턴스 (애플리케이션 로드 시 한 번만 생성 권장)
        # 사용 가능한 모델: gemini-1.5-flash-latest, gemini-1.5-pro-latest, gemini-pro 등
        gemini_translation_model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info("Gemini model 'gemini-1.5-flash-latest' initialized for translation.")
    except Exception as e:
        logger.error(f"Failed to configure Gemini API or initialize model: {e}", exc_info=True)
        gemini_translation_model = None # 초기화 실패 시 None으로 설정
else:
    logger.warning("GEMINI_API_KEY environment variable not found. Translation via Gemini will be disabled.")
    gemini_translation_model = None

async def translate_japanese_to_korean_with_gemini(japanese_text: str) -> Union[str, None]:
    """주어진 일본어 텍스트를 Gemini API를 사용하여 한국어로 번역합니다."""
    if not gemini_translation_model: # 초기화된 모델 인스턴스 사용
        logger.warning("Gemini translation model is not initialized. Skipping translation.")
        return None

    # --- 프롬프트 엔지니어링 (구어체 및 자연스러운 번역 유도) ---
    # 예시 프롬프트입니다. 실제 사용 시 다양한 테스트를 통해 최적화하세요.
    prompt = f"""다음 일본어 구어체 문장을 매우 자연스러운 한국어 구어체로 번역해주세요.
                일본어: "{japanese_text}"
                한국어:"""
    
    logger.debug(f"Sending text to Gemini for translation: '{japanese_text}'")

    try:
        # API 호출 시 안전 설정 및 생성 설정 (선택적)
        generation_config = genai.types.GenerationConfig(
            temperature=0.7, # 창의성 조절 (0.0 ~ 1.0)
            # max_output_tokens=..., # 필요시 최대 출력 토큰 수 제한
        )
        # 안전 설정 (유해 콘텐츠 차단 레벨 조정 - 필요시)
        # safety_settings = [
        #     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        #     {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        #     {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        #     {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        # ]

        # 비동기 API 호출
        response = await gemini_translation_model.generate_content_async(
            prompt,
            generation_config=generation_config,
            # safety_settings=safety_settings # 안전 설정 적용 시
        )

        if response.parts:
            translated_korean_text = response.text.strip()
            logger.debug(f"Gemini translation successful: '{japanese_text}' -> '{translated_korean_text}'")
            return translated_korean_text
        else:
            # 응답에 텍스트 파트가 없는 경우 (차단 등)
            block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
            safety_ratings_str = str(response.candidates[0].safety_ratings) if response.candidates and response.candidates[0].safety_ratings else "N/A"
            logger.warning(f"Gemini response for '{japanese_text}' did not contain text parts. Blocked: {block_reason}, SafetyRatings: {safety_ratings_str}")
            return "[번역 실패: Gemini 응답 없음]"
    except Exception as e:
        logger.error(f"Error during Gemini API call for text '{japanese_text}': {e}", exc_info=True)
        return "[번역 오류 발생]"

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
consumer_thread = None
stop_consumer_event = threading.Event()
consumer = None # Consumer 객체를 전역 또는 클래스 멤버로 관리

# --- 백그라운드 Consumer 루프 함수 ---
# (이 함수는 스레드에서 실행되므로 동기 함수로 정의)
def _run_kafka_consumer_loop(consumer: KafkaConsumer, main_loop: asyncio.AbstractEventLoop):
    """
    백그라운드 스레드에서 실행될 Kafka Consumer 루프.
    STT 결과를 받아 Gemini로 번역 후 WebSocket 통신 및 Redis 저장을 수행합니다.
    """
    redis_client = get_redis_client()
    logger.info("Kafka Consumer thread started. Waiting for messages from topic '{}'...".format(STT_RESULT_TOPIC))

    try:
        for message in consumer: # Kafka 메시지 수신 루프
            if stop_consumer_event.is_set():
                logger.info("Stop event received by Kafka consumer thread, exiting loop.")
                break

            logger.info(f"!!!!!!!!!! [Thread] Message Received from Kafka: {message.topic}/{message.partition}/{message.offset}: key={message.key} !!!!!!!!!!")

            try:
                result_data = message.value # JSON 역직렬화된 dict (KafkaConsumer 설정에 따름)
                task_id = result_data.get('task_id')

                if not task_id:
                    logger.warning(f"[Thread] Received message without task_id: {result_data}")
                    continue # task_id 없으면 다음 메시지로

                logger.info(f"[Thread][Task {task_id}] Received Kafka message, Status: {result_data.get('status')}, Progress: {result_data.get('progress')}")
                logger.debug(f"[Thread][Task {task_id}] Raw message data: {result_data.get('data')}")

                # --- STT 세그먼트 데이터가 있고, 번역이 필요한 경우 ---
                # result_data["data"]가 리스트이고, 그 안에 "text" 키를 가진 딕셔너리들이 있다면 STT 결과로 간주
                is_stt_segment_data = (
                    result_data.get("data")
                    and isinstance(result_data["data"], list)
                    and len(result_data["data"]) > 0
                    and isinstance(result_data["data"][0], dict)
                    and "text" in result_data["data"][0] # 첫 번째 요소에 text 필드 확인
                )

                if is_stt_segment_data:
                    stt_segments = result_data["data"]
                    logger.info(f"[Thread][Task {task_id}] Found {len(stt_segments)} STT segments. Proceeding to translate with Gemini.")

                    # --- 비동기 번역 작업을 위한 헬퍼 함수 ---
                    async def _translate_batch_async(segments_to_translate):
                        translation_coroutines = []
                        for seg_idx, segment_content in enumerate(segments_to_translate):
                            jp_text = segment_content.get("text")
                            if jp_text and isinstance(jp_text, str): # 실제 텍스트가 있는지 확인
                                logger.debug(f"[Thread][Task {task_id}][Seg {seg_idx+1}] Scheduling translation for: '{jp_text}'")
                                translation_coroutines.append(translate_japanese_to_korean_with_gemini(jp_text))
                            else:
                                # 번역할 일본어 텍스트가 없는 경우 (예: 빈 문자열, None)
                                logger.debug(f"[Thread][Task {task_id}][Seg {seg_idx+1}] No Japanese text to translate, skipping Gemini call.")
                                translation_coroutines.append(asyncio.sleep(0, result="[원본 텍스트 없음 또는 부적절]")) # 즉시 완료, 플레이스홀더 반환
                        
                        # 모든 번역 작업을 동시에 실행하고 결과 수집 (개별 작업 오류도 반환)
                        return await asyncio.gather(*translation_coroutines, return_exceptions=True)
                    # --- 비동기 번역 헬퍼 함수 끝 ---

                    # 메인 이벤트 루프에서 번역 작업들 실행 및 결과 대기
                    if main_loop and main_loop.is_running() and gemini_translation_model: # Gemini 모델 초기화 확인
                        future = asyncio.run_coroutine_threadsafe(_translate_batch_async(stt_segments), main_loop)
                        try:
                            # 번역 작업 타임아웃 설정 (넉넉하게, 세그먼트 수에 따라 조절)
                            # 예: 기본 30초 + (세그먼트당 평균 5초 * 세그먼트 수)
                            timeout_seconds = 30 + (len(stt_segments) * 5) 
                            logger.debug(f"[Thread][Task {task_id}] Waiting for {len(stt_segments)} translations with timeout {timeout_seconds}s...")
                            translated_texts_or_errors_list = future.result(timeout=timeout_seconds)
                            logger.info(f"[Thread][Task {task_id}] Gemini translation batch completed.")

                            # 번역 결과를 원본 세그먼트에 'korean_text' 키로 추가
                            for i, segment in enumerate(stt_segments):
                                original_jp_text = segment.get("text", "[원본 JP 없음]") # 로깅용
                                if i < len(translated_texts_or_errors_list):
                                    translation_result = translated_texts_or_errors_list[i]
                                    if isinstance(translation_result, Exception):
                                        # 개별 번역 작업에서 예외 발생 시
                                        logger.error(f"[Thread][Task {task_id}][Seg {i+1}] Translation failed for '{original_jp_text}': {translation_result}")
                                        segment["korean_text"] = "[번역 중 오류 발생]"
                                    elif translation_result is None:
                                        # translate_japanese_to_korean_with_gemini 가 None 반환 시 (API 키 없음 등)
                                        logger.warning(f"[Thread][Task {task_id}][Seg {i+1}] Translation for '{original_jp_text}' returned None.")
                                        segment["korean_text"] = "[번역 결과 없음]"
                                    else:
                                        segment["korean_text"] = str(translation_result) # 문자열로 확실히 변환
                                        # --- 번역된 한국어 내용 로그로 바로 확인 ---
                                        logger.info(f"[Thread][Task {task_id}][Seg {i+1}] JP: '{original_jp_text}'  ==>  KO: '{segment['korean_text']}'")
                                else:
                                    logger.warning(f"[Thread][Task {task_id}][Seg {i+1}] Translation result missing for '{original_jp_text}'.")
                                    segment["korean_text"] = "[번역 누락]"
                        except asyncio.TimeoutError:
                            logger.error(f"[Thread][Task {task_id}] Gemini translation for segments timed out after {timeout_seconds}s.")
                            for segment in stt_segments: segment["korean_text"] = "[번역 시간 초과]"
                        except Exception as e_trans_batch:
                            logger.error(f"[Thread][Task {task_id}] An error occurred during batch Gemini translation execution: {e_trans_batch}", exc_info=True)
                            for segment in stt_segments: segment["korean_text"] = "[번역 시스템 오류]"
                    elif not gemini_translation_model:
                        logger.warning(f"[Thread][Task {task_id}] Gemini model not initialized. Skipping all translations.")
                        for segment in stt_segments: segment["korean_text"] = "[번역 건너뜀 - 모델 미초기화]"
                    else: # main_loop 없거나 실행 중 아닐 때
                        logger.warning(f"[Thread][Task {task_id}] Main event loop not available. Skipping all translations.")
                        for segment in stt_segments: segment["korean_text"] = "[번역 건너뜀 - 루프 없음]"
                    
                    result_data["data"] = stt_segments # 번역된 텍스트가 포함된 세그먼트로 업데이트
                # --- STT 세그먼트 번역 처리 끝 ---

                # WebSocket으로 업데이트된 result_data 전송 및 Redis 저장
                if main_loop and main_loop.is_running():
                    logger.debug(f"[Thread][Task {task_id}] Scheduling WebSocket send and Redis save.")
                    asyncio.run_coroutine_threadsafe(
                        _send_ws_update_async(
                            task_id,
                            result_data.get("status", "UNKNOWN"),
                            result_data.get("progress"),
                            result_data.get("data"), # 이제 여기에 korean_text 포함됨
                            result_data.get("error")
                        ),
                        main_loop
                    )
                else:
                    logger.warning(f"[Thread][Task {task_id}] Main event loop not available for WebSocket/Redis update.")
                
                # Redis 저장 (동기적, 에러 핸들링 추가)
                if redis_client:
                    try:
                        redis_key = f"ws_messages:{task_id}"
                        # result_data가 dict인지 확인 (value_deserializer에 의해 이미 dict여야 함)
                        message_to_store = result_data if isinstance(result_data, dict) else {"error": "Invalid data format for Redis"}
                        message_json = json.dumps(message_to_store) # 이제 korean_text 포함
                        redis_client.rpush(redis_key, message_json)
                        redis_client.expire(redis_key, get_message_ttl())
                        logger.debug(f"[Thread][Task {task_id}] Saved updated message to Redis list {redis_key}")
                    except Exception as e_redis:
                        logger.error(f"[Thread][Task {task_id}] Failed to save message to Redis: {e_redis}", exc_info=True)

            except json.JSONDecodeError as e_json_decode:
                 logger.error(f"[Thread] Failed to decode Kafka message value: {message.value}. Error: {e_json_decode}", exc_info=True)
            except Exception as e_msg_proc:
                logger.error(f"[Thread][Task {task_id if 'task_id' in locals() else 'Unknown'}] Error processing Kafka message: {e_msg_proc}", exc_info=True)

    except KeyboardInterrupt: # Ctrl+C 등으로 스레드 종료 시
        logger.info("Kafka Consumer thread received KeyboardInterrupt. Exiting...")
    except Exception as e_consumer_loop:
        logger.error(f"Fatal error in Kafka Consumer loop: {e_consumer_loop}", exc_info=True)
    finally:
        logger.info("Closing Kafka Consumer in thread.")
        if consumer: # consumer 객체가 None이 아닐 때만 close 호출
            consumer.close()

# --- 앱 시작 시 Kafka Consumer 스레드 실행 ---
@app.on_event("startup")
async def startup_event():
    global consumer_thread, consumer # 전역 변수 사용
    logger.info("Application starting up...")

    # Kafka Consumer 초기화 (재시도 로직 포함)
    consumer = None
    if KAFKA_BOOTSTRAP_SERVERS:
        MAX_RETRIES = 5
        RETRY_DELAY = 5
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(f"Attempting to initialize Kafka Consumer (Attempt {attempt + 1}/{MAX_RETRIES})...")
                consumer = KafkaConsumer(
                    STT_RESULT_TOPIC, # 구독할 토픽
                    bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                    group_id='stt_result_consumers_api', # 컨슈머 그룹 ID
                    auto_offset_reset='earliest', # 오프셋 초기값
                    enable_auto_commit=True, # 자동 오프셋 커밋 (간편하지만 메시지 유실 가능성)
                    consumer_timeout_ms=-1, # 메시지 기다리는 시간 (-1: 무한 대기)
                    # 추가 옵션 (필요시):
                    # session_timeout_ms=30000,
                    # heartbeat_interval_ms=10000,
                )
                # 간단한 연결 테스트 (토픽 목록 가져오기)
                consumer.topics() # 브로커와 통신이 되어야 성공
                logger.info(f"Kafka Consumer initialized successfully for topic: {STT_RESULT_TOPIC}")
                break # 성공 시 루프 탈출
            except KafkaError as e:
                logger.warning(f"Kafka Consumer initialization error (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY} seconds...")
                if attempt == MAX_RETRIES - 1:
                    logger.error("Max retries reached. Failed to initialize Kafka Consumer.")
                    consumer = None
                time.sleep(RETRY_DELAY)
            except Exception as e:
                 logger.error(f"Unexpected error during Kafka Consumer initialization (Attempt {attempt + 1}): {e}", exc_info=True)
                 consumer = None
                 break # 예상치 못한 오류는 재시도 중단

        # Consumer 초기화 성공 시에만 스레드 시작
        if consumer:
            logger.info("Starting Kafka result consumer thread...")
            stop_consumer_event.clear()
            try:
                # 현재 실행 중인 (메인) 이벤트 루프를 가져옴
                main_event_loop = asyncio.get_running_loop()
                consumer_thread = threading.Thread(
                    target=_run_kafka_consumer_loop,
                    # consumer 객체와 메인 이벤트 루프 객체를 인자로 전달
                    args=(consumer, main_event_loop,),
                    daemon=True # 메인 스레드 종료 시 자동 종료
                )
                consumer_thread.start()
                logger.info("Kafka result consumer thread started successfully.")
            except RuntimeError as e:
                 # get_running_loop() 실패 시 등 (이론상 startup에서는 발생 안해야 함)
                 logger.error(f"Could not get running event loop to start consumer thread: {e}", exc_info=True)
                 # consumer를 닫아주는 것이 안전할 수 있음
                 if consumer:
                     consumer.close()
        else:
             logger.error("Kafka Consumer could not be initialized. Background result processing will not start.")
    else:
         logger.error("Kafka bootstrap servers not configured. Result consumer cannot start.")



# --- 앱 종료 시 처리 ---
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutting down...")
    if consumer_thread and consumer_thread.is_alive():
        logger.info("Signaling Kafka consumer thread to stop...")
        stop_consumer_event.set()
        consumer_thread.join(timeout=5) # 최대 5초 대기
        if consumer_thread.is_alive():
            logger.warning("Kafka consumer thread did not stop gracefully after 5 seconds.")
        else:
             logger.info("Kafka consumer thread stopped.")
    else:
        logger.info("Kafka consumer thread was not running or already stopped.")
    # Producer도 여기서 닫아주는 것이 좋음 (애플리케이션 종료 시)
    if producer:
        logger.info("Closing Kafka Producer.")
        producer.close(timeout=5) # 타임아웃 지정 가능

# --- WebSocket 메시지 전송 함수 (async def 로 정의) ---
# (이 함수는 메인 이벤트 루프에서 실행될 것이므로 async def 유지)
async def _send_ws_update_async(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    """비동기적으로 WebSocket 메시지를 전송하는 내부 함수"""
    message = {"status": status}
    if progress is not None: message["progress"] = max(0, min(100, progress))
    if data is not None: message["data"] = data
    if error is not None: message["error"] = error
    try:
        if manager:
            await manager.send_json_message(task_id, message)
        else:
            logger.warning(f"[Task {task_id}] WebSocket manager not available, skipping live send.")
    except Exception as e:
        logger.error(f"[Task {task_id}] Failed to send WebSocket update ({status}): {e}")

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