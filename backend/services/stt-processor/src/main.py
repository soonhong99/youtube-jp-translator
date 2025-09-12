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

# AI Orchestrator 토픽
AI_PROCESSING_REQUEST_TOPIC = "ai_processing_requests" 
AI_PROCESSING_RESULT_TOPIC = "ai_processing_results"

# WebSocket Manager 및 Redis Client (메시지 히스토리용)
from .ws_manager import manager
from .redis_client import get_redis_client, get_message_ttl # Redis는 히스토리용으로 유지

# Gemini 모델 설정
from .gemini_config import get_gemini_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# System metrics logger (local adapter)
from .system_logger_adapter import (
    log_kafka_message,
)

# Gemini 모델 초기화
gemini_config = get_gemini_config()
gemini_translation_model = gemini_config.model_instance

# 모델 정보 로깅
model_info = gemini_config.get_model_info()
logger.info(f"Gemini configuration: {model_info}")

if not gemini_config.is_available():
    logger.warning("Gemini translation model is not available. Translation will be disabled.")

# async def translate_japanese_to_korean_with_gemini(japanese_text: str) -> Union[str, None]:
#     """주어진 일본어 텍스트를 Gemini API를 사용하여 한국어로 번역합니다."""

#     if not gemini_translation_model: # 초기화된 모델 인스턴스 사용
#         logger.warning("Gemini translation model is not initialized. Skipping translation.")
#         return None

#     # --- 프롬프트 엔지니어링 (구어체 및 자연스러운 번역 유도) ---
#     # 예시 프롬프트입니다. 실제 사용 시 다양한 테스트를 통해 최적화하세요.
#     prompt = f"""다음 일본어 구어체 문장을 매우 자연스러운 한국어 구어체로 번역해주세요.
#                 일본어: "{japanese_text}"
#                 한국어:"""
    
#     logger.debug(f"Sending text to Gemini for translation: '{japanese_text}'")

#     try:
#         # API 호출 시 안전 설정 및 생성 설정 (선택적)
#         generation_config = genai.types.GenerationConfig(
#             temperature=0.7, # 창의성 조절 (0.0 ~ 1.0)
#             # max_output_tokens=..., # 필요시 최대 출력 토큰 수 제한
#         )
#         # 안전 설정 (유해 콘텐츠 차단 레벨 조정 - 필요시)
#         # safety_settings = [
#         #     {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
#         #     {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
#         #     {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
#         #     {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
#         # ]

#         # 비동기 API 호출
#         response = await gemini_translation_model.generate_content_async(
#             prompt,
#             generation_config=generation_config,
#             # safety_settings=safety_settings # 안전 설정 적용 시
#         )

#         if response.parts:
#             translated_korean_text = response.text.strip()
#             logger.debug(f"Gemini translation successful: '{japanese_text}' -> '{translated_korean_text}'")
#             return translated_korean_text
#         else:
#             # 응답에 텍스트 파트가 없는 경우 (차단 등)
#             block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
#             safety_ratings_str = str(response.candidates[0].safety_ratings) if response.candidates and response.candidates[0].safety_ratings else "N/A"
#             logger.warning(f"Gemini response for '{japanese_text}' did not contain text parts. Blocked: {block_reason}, SafetyRatings: {safety_ratings_str}")
#             return "[번역 실패: Gemini 응답 없음]"
#     except Exception as e:
#         logger.error(f"Error during Gemini API call for text '{japanese_text}': {e}", exc_info=True)
#         return "[번역 오류 발생]"

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

SEGMENT_SEPARATOR = "[TRANSLATION_SEGMENT_BREAK]" # 문장 구분자 정의

async def translate_batched_japanese_to_korean_with_gemini(
    japanese_segments_texts: List[str]
) -> List[Union[str, None]]:
    """
    일본어 텍스트 리스트를 받아 하나의 요청으로 Gemini API에 번역을 요청하고,
    번역된 한국어 텍스트 리스트를 반환합니다.
    """
    if not gemini_translation_model:
        logger.warning("Gemini translation model not initialized. Skipping batch translation.")
        return ["[번역 건너뜀 - 모델 미초기화]" for _ in japanese_segments_texts]

    if not japanese_segments_texts:
        return []
    
    example_jp_input = f"こんにちは{SEGMENT_SEPARATOR}\nお元気ですか" # 입력 시 구분자는 \n 없이 사용 가능
    example_ko_output = f"안녕하세요.{SEGMENT_SEPARATOR}\n잘 지내세요?" # 출력 시 번호, 구분자, 줄바꿈 명시


    # 구분자를 사용하여 모든 일본어 텍스트를 하나의 문자열로 합침
    combined_japanese_text = f"\n{SEGMENT_SEPARATOR}\n".join(japanese_segments_texts)

    prompt = f"""다음은 유튜브에서 추출해낸 총 {len(japanese_segments_texts)}개의 독립적인 일본어 구어체 문장들입니다. 각 문장은 "{SEGMENT_SEPARATOR}"로 구분되어 있습니다.
    맥락에 맞게 매우 자연스러운 한국어 구어체로 번역하고, 각 번역된 문장 뒤에는 반드시 원래의 "{SEGMENT_SEPARATOR}" 구분자를 정확히 유지해주세요.
    최종적으로 번역된 한국어 문장도 정확히 {len(japanese_segments_texts)}개가 되어야 합니다.
    각 번역된 문장 외에는 어떠한 부연 설명, 인사말 등을 절대 포함하지 마세요.

    예시:
    일본어 원문:
    {example_jp_input}

    한국어 번역:
    {example_ko_output}

    일본어 원문:
    {combined_japanese_text}

    한국어 번역:"""

    logger.info(f"Sending {len(japanese_segments_texts)} segments to Gemini for batch translation.")
    logger.debug(f"Combined Japanese text for Gemini:\n{combined_japanese_text}")

    try:
        generation_config = gemini_config.get_generation_config(temperature=0.7)
        response = await gemini_translation_model.generate_content_async(
            prompt,
            generation_config=generation_config,
        )

        if response.parts:
            combined_korean_text = response.text.strip()
            logger.debug(f"Combined Korean translation from Gemini:\n{combined_korean_text}")

            # 구분자를 기준으로 번역된 한국어 텍스트 분리
            translated_korean_segments = combined_korean_text.split(f"{SEGMENT_SEPARATOR}\n")
            
            # 원본 세그먼트 수와 번역된 세그먼트 수가 일치하는지 확인
            if len(translated_korean_segments) == len(japanese_segments_texts):
                logger.info(f"Batch translation successful. Received {len(translated_korean_segments)} translated segments.")
                return translated_korean_segments
            else:
                logger.error(f"Mismatch in segment count after batch translation. Expected {len(japanese_segments_texts)}, got {len(translated_korean_segments)}. Full response: '{combined_korean_text}'")
                # 오류 처리: 개별 번역으로 전환하거나, 에러 메시지 반환
                return ["[일괄 번역 분할 오류]" for _ in japanese_segments_texts]
        else:
            block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
            logger.warning(f"Gemini batch response did not contain text parts. Blocked: {block_reason}")
            return ["[일괄 번역 실패: Gemini 응답 없음]" for _ in japanese_segments_texts]
    except Exception as e:
        logger.error(f"Error during Gemini batch API call: {e}", exc_info=True)
        return ["[일괄 번역 중 오류 발생]" for _ in japanese_segments_texts]

# --- FastAPI 앱 생성 및 CORS 설정 ---
app = FastAPI(title="Kafka-based STT Processor API", version="0.3.0")
# ... (CORS 미들웨어 설정은 이전과 동일하게 추가) ...
from fastapi.middleware.cors import CORSMiddleware
origins = ["http://localhost", "http://localhost:3000", "http://localhost:3003"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- API 모델 정의 ---
class TranscriptionRequest(BaseModel):
    wav_file_path: str = Field(..., description="Path to the WAV file inside the container.")
    task_id: str = Field(..., description="Task ID from client for WebSocket connection.")
    language: str = Field("ja", description="Language code (e.g., 'ja').")
    ai_mode: str = Field("standard", description="AI processing mode.")

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
    STT 결과를 받아, 최종 STT 완료 시점에만 Gemini로 일괄 번역 후 
    WebSocket 통신 및 Redis 저장을 수행합니다.
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
                result_data = message.value # KafkaConsumer 설정에 따라 이미 dict로 변환되었을 것
                task_id = result_data.get('task_id')

                if not task_id:
                    logger.warning(f"[Thread] Received message without task_id: {result_data}")
                    continue 

                current_status = result_data.get("status", "UNKNOWN")
                logger.info(f"[Thread][Task {task_id}] Kafka message received. Status: {current_status}, Progress: {result_data.get('progress')}")
                logger.debug(f"[Thread][Task {task_id}] Raw message data payload: {result_data.get('data')}")

                # system metrics: kafka message receipt
                try:
                    log_kafka_message(task_id, topic=message.topic, message=current_status)
                except Exception:
                    pass

                # --- 핵심 로직: 상태에 따라 분기 처리 ---
                if current_status == "STT_COMPLETED_ALL_SEGMENTS" or current_status == "COMPLETED":
                    # 워커가 모든 STT 처리를 완료하고 전체 일본어 세그먼트를 보낸 경우
                    stt_segments = result_data.get("data")
                    
                    # 데이터 유효성 검사 (리스트 형태인지, 비어있지 않은지 등)
                    if isinstance(stt_segments, list):
                        if not stt_segments: # STT 결과 세그먼트가 없는 경우 (예: 무음 영상)
                            logger.info(f"[Thread][Task {task_id}] STT produced no segments. Finalizing as COMPLETED with empty data.")
                            result_data["status"] = "COMPLETED"
                            result_data["progress"] = 100
                            result_data["data"] = [] # 데이터는 빈 리스트로 확실히 설정
                        else: # STT 세그먼트가 있는 경우, 일괄 번역 진행
                            logger.info(f"[Thread][Task {task_id}] Received all {len(stt_segments)} STT segments. Starting batch translation with Gemini.")
                            
                            # 번역할 일본어 텍스트만 추출
                            japanese_texts_to_translate = [
                                seg.get("text", "") for seg in stt_segments if isinstance(seg, dict) and seg.get("text")
                            ]
                            
                            if not japanese_texts_to_translate: # 추출된 일본어 텍스트가 없는 경우
                                logger.warning(f"[Thread][Task {task_id}] No valid Japanese text found in segments to translate.")
                                for segment in stt_segments: # 모든 세그먼트에 플레이스홀더 추가
                                     if isinstance(segment, dict): segment["korean_text"] = "[원본 JP 텍스트 없음]"
                                result_data["status"] = "COMPLETED" # 번역할 내용 없으므로 바로 완료
                                result_data["progress"] = 100

                            elif main_loop and main_loop.is_running() and gemini_translation_model:
                                # 비동기 일괄 번역 함수 호출
                                async def _perform_batch_translation_async():
                                    return await translate_batched_japanese_to_korean_with_gemini(japanese_texts_to_translate)

                                future = asyncio.run_coroutine_threadsafe(_perform_batch_translation_async(), main_loop)
                                try:
                                    timeout_seconds = 60 + (len(japanese_texts_to_translate) * 5) # 타임아웃 조절
                                    logger.debug(f"[Thread][Task {task_id}] Waiting for batch translation from Gemini (timeout: {timeout_seconds}s)...")
                                    translated_korean_list = future.result(timeout=timeout_seconds)
                                    logger.info(f"[Thread][Task {task_id}] Gemini batch translation finished.")

                                    # 번역 결과를 원본 세그먼트에 매칭하여 추가
                                    translation_idx = 0
                                    for segment in stt_segments:
                                        if isinstance(segment, dict) and segment.get("text"): # 실제 텍스트가 있었던 세그먼트에만 매칭
                                            if translation_idx < len(translated_korean_list):
                                                ko_text_result = translated_korean_list[translation_idx]
                                                if isinstance(ko_text_result, Exception):
                                                    segment["korean_text"] = "[번역 중 오류]"
                                                    logger.error(f"[Thread][Task {task_id}] Translation failed for JP: '{segment.get('text')}': {ko_text_result}")
                                                else:
                                                    segment["korean_text"] = str(ko_text_result) if ko_text_result else "[번역 결과 없음]"
                                                
                                                # 번역 품질 로깅 강화
                                                jp_text = segment.get('text', '')
                                                ko_text = segment.get('korean_text', '')
                                                logger.info(f"[Thread][Task {task_id}][{gemini_config.model_name}] Translation: JP='{jp_text}' -> KO='{ko_text}'")
                                                
                                                # 번역 길이 비교 (품질 지표)
                                                jp_len = len(jp_text)
                                                ko_len = len(ko_text)
                                                length_ratio = ko_len / jp_len if jp_len > 0 else 0
                                                if length_ratio > 3 or length_ratio < 0.3:
                                                    logger.warning(f"[Thread][Task {task_id}] Unusual translation length ratio: {length_ratio:.2f} (JP:{jp_len} -> KO:{ko_len})")
                                                
                                                translation_idx += 1
                                            else: # 번역 결과 리스트가 예상보다 짧은 경우
                                                segment["korean_text"] = "[번역 누락]"
                                                logger.warning(f"[Thread][Task {task_id}] Missing translation for JP: '{segment.get('text')}'")
                                        elif isinstance(segment, dict): # text 필드가 없는 segment
                                            segment["korean_text"] = "[원본 JP 텍스트 없음]"

                                    result_data["status"] = "COMPLETED" # 모든 작업 완료
                                    result_data["progress"] = 100
                                except asyncio.TimeoutError:
                                    logger.error(f"[Thread][Task {task_id}] Gemini batch translation timed out.")
                                    for segment in stt_segments: 
                                        if isinstance(segment, dict): segment["korean_text"] = "[일괄 번역 시간 초과]"
                                    result_data["status"] = "FAILED"; result_data["error"] = "Translation timed out"
                                except Exception as e_trans_batch:
                                    logger.error(f"[Thread][Task {task_id}] Error in batch translation: {e_trans_batch}", exc_info=True)
                                    for segment in stt_segments: 
                                        if isinstance(segment, dict): segment["korean_text"] = "[일괄 번역 시스템 오류]"
                                    result_data["status"] = "FAILED"; result_data["error"] = "Translation system error"
                            elif not gemini_translation_model:
                                logger.warning(f"[Thread][Task {task_id}] Gemini model not initialized. Skipping translation for STT_COMPLETED_ALL_SEGMENTS.")
                                for segment in stt_segments: 
                                    if isinstance(segment, dict): segment["korean_text"] = "[번역 건너뜀 - 모델 미초기화]"
                                result_data["status"] = "COMPLETED" # STT는 완료됨
                                result_data["progress"] = 100 # 번역은 안됐지만 진행률은 100
                            else: # main_loop 문제
                                logger.warning(f"[Thread][Task {task_id}] Main event loop not available. Skipping translation for STT_COMPLETED_ALL_SEGMENTS.")
                                for segment in stt_segments: 
                                    if isinstance(segment, dict): segment["korean_text"] = "[번역 건너뜀 - 루프 없음]"
                                result_data["status"] = "COMPLETED"
                                result_data["progress"] = 100
                    else: # stt_segments가 리스트가 아닌 경우
                        logger.error(f"[Thread][Task {task_id}] 'STT_COMPLETED_ALL_SEGMENTS' status but 'data' is not a list: {stt_segments}")
                        result_data["status"] = "FAILED"
                        result_data["error"] = "Invalid STT segment data format for translation."
                    
                    # result_data["data"]는 이미 stt_segments로 업데이트 되어 있음

                elif current_status == "PROCESSING":
                    # 중간 STT 결과 (일본어 텍스트만) 또는 상태 메시지
                    # 이 메시지들은 번역 없이 그대로 전달
                    logger.info(f"[Thread][Task {task_id}] Forwarding 'PROCESSING' message as is (no translation).")
                    # result_data는 이미 수신한 그대로 사용
                
                elif current_status == "AI_PROCESSING_COMPLETED":
                    # AI 처리 완료 - 번역된 세그먼트 데이터 전달
                    logger.info(f"[Thread][Task {task_id}] AI processing completed. Forwarding translated segments.")
                    
                    # AI Orchestrator가 보낸 데이터 추출
                    ai_result_data = result_data.get("data", {})
                    if isinstance(ai_result_data, dict) and "segments" in ai_result_data:
                        translated_segments = ai_result_data["segments"]
                        logger.info(f"[Thread][Task {task_id}] Received {len(translated_segments)} translated segments from AI Orchestrator")
                        
                        # 최종 완료 상태로 변경
                        result_data["status"] = "COMPLETED"
                        result_data["progress"] = 100
                        result_data["data"] = translated_segments
                    else:
                        logger.warning(f"[Thread][Task {task_id}] AI processing completed but no segments data found")
                        result_data["status"] = "COMPLETED"
                        result_data["progress"] = 100
                        result_data["data"] = []

                elif current_status == "AI_PROCESSING" or current_status == "AI_PROCESSING_FAILED":
                    # AI 처리 중간 상태 또는 실패 상태 전달
                    logger.info(f"[Thread][Task {task_id}] Forwarding AI processing status: {current_status}")
                    # result_data는 이미 수신한 그대로 사용

                elif current_status == "FAILED" or "CHUNK_FAILED" in current_status:
                    # 워커에서 발생한 실패 상태 그대로 전달
                    logger.warning(f"[Thread][Task {task_id}] Forwarding 'FAILED' or 'CHUNK_FAILED' message as is.")
                    # result_data는 이미 수신한 그대로 사용

                else:
                    logger.warning(f"[Thread][Task {task_id}] Received message with unhandled status '{current_status}'. Forwarding as is.")
                    # 알 수 없는 다른 상태도 일단 그대로 전달

                # --- 최종 메시지 전송 및 저장 (모든 상태 공통) ---
                # result_data는 위 분기에서 상태, 진행률, 데이터(번역 포함 또는 미포함)가 업데이트 되었음
                if main_loop and main_loop.is_running():
                    logger.info(f"[Thread][Task {task_id}] Scheduling WebSocket send with final status: {result_data.get('status')}, progress: {result_data.get('progress')}")
                    asyncio.run_coroutine_threadsafe(
                        _send_ws_update_async(
                            task_id,
                            result_data
                        ),
                        main_loop
                    )
                else:
                    logger.warning(f"[Thread][Task {task_id}] Main event loop not available for final WebSocket/Redis update.")

                if redis_client:
                    try:
                        redis_key = f"ws_messages:{task_id}"
                        message_to_store = result_data if isinstance(result_data, dict) else {"error": "Invalid data format for Redis storage"}
                        message_json = json.dumps(message_to_store)
                        redis_client.rpush(redis_key, message_json)
                        redis_client.expire(redis_key, get_message_ttl())
                        logger.debug(f"[Thread][Task {task_id}] Saved final message to Redis: {message_json[:200]}...") # 로그 너무 길지 않게
                    except Exception as e_redis:
                        logger.error(f"[Thread][Task {task_id}] Failed to save final message to Redis: {e_redis}", exc_info=True)

            except json.JSONDecodeError as e_json_decode:
                 logger.error(f"[Thread] Failed to decode Kafka message value: {message.value}. Error: {e_json_decode}", exc_info=True)
            except Exception as e_msg_proc: # 개별 메시지 처리 중 예외
                task_id_for_error = task_id if 'task_id' in locals() and task_id else 'UnknownTaskID'
                logger.error(f"[Thread][Task {task_id_for_error}] Error processing individual Kafka message: {e_msg_proc}", exc_info=True)
                # 이 경우 해당 메시지 처리는 실패하고 다음 메시지로 넘어감

    except KeyboardInterrupt:
        logger.info("Kafka Consumer thread received KeyboardInterrupt. Exiting...")
    except Exception as e_consumer_loop: # 루프 자체의 심각한 오류
        logger.error(f"Fatal error in Kafka Consumer main loop: {e_consumer_loop}", exc_info=True)
    finally:
        logger.info("Closing Kafka Consumer in thread.")
        if consumer:
            consumer.close()

# Health check 엔드포인트 추가
@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    health_status = {
        "status": "healthy",
        "service": "stt-processor-api",
        "timestamp": time.time()
    }
    
    # Kafka 연결 상태 확인
    if producer:
        health_status["kafka_producer"] = "connected"
    else:
        health_status["kafka_producer"] = "disconnected"
        health_status["status"] = "degraded"
    
    # Redis 연결 상태 확인
    redis_client = get_redis_client()
    if redis_client:
        try:
            redis_client.ping()
            health_status["redis"] = "connected"
        except:
            health_status["redis"] = "disconnected"
            health_status["status"] = "degraded"
    else:
        health_status["redis"] = "disconnected"
        health_status["status"] = "degraded"
    
    # 모델 로드 상태 확인
    if gemini_config.is_available():
        health_status["gemini_model"] = {
            "status": "loaded",
            "model_name": gemini_config.model_name,
            "temperature": gemini_config.temperature
        }
    else:
        health_status["gemini_model"] = "not_loaded"
        # Gemini는 선택적이므로 degraded로만 표시
    
    # unhealthy 상태면 503 반환
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    
    return health_status

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
                    STT_RESULT_TOPIC, # STT 결과 토픽
                    AI_PROCESSING_RESULT_TOPIC, # AI Orchestrator 결과 토픽
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
                logger.info(f"Kafka Consumer initialized successfully for topics: {STT_RESULT_TOPIC}, {AI_PROCESSING_RESULT_TOPIC}")
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

# --- WebSocket 메시지 전송 함수 (전체 페이로드 전송) ---
# (이 함수는 메인 이벤트 루프에서 실행될 것이므로 async def 유지)
async def _send_ws_update_async(task_id: str, payload: Dict[str, Any]):
    """비동기적으로 WebSocket 메시지를 전송 (Kafka 원본 페이로드 그대로)"""
    try:
        if not isinstance(payload, dict):
            logger.warning(f"[Task {task_id}] Invalid payload type for WS send: {type(payload)}. Wrapping as error message.")
            payload = {"status": "UNKNOWN", "error": "Invalid payload for WS send"}

        if manager:
            await manager.send_json_message(task_id, payload)
            logger.info(f"[Task {task_id}] Successfully sent WebSocket message with status: {payload.get('status')}")
        else:
            logger.warning(f"[Task {task_id}] WebSocket manager not available, skipping live send.")
    except Exception as e:
        logger.error(f"[Task {task_id}] Failed to send WebSocket update: {e}")

# --- API 엔드포인트 수정 ---
@app.post("/request_transcription", response_model=TranscriptionResponse, status_code=202, summary="Request Transcription via Kafka")
async def request_transcription(request: TranscriptionRequest):
    if not producer:
        raise HTTPException(status_code=503, detail="Kafka Producer is not available.")
    if not os.path.exists(request.wav_file_path):
        raise HTTPException(status_code=404, detail=f"WAV file not found at: {request.wav_file_path}")

    # 클라이언트에서 보낸 task_id 사용
    task_id = request.task_id
    message = {
        "task_id": task_id,
        "wav_file_path": request.wav_file_path,
        "language": request.language,
        "ai_mode": request.ai_mode,
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
