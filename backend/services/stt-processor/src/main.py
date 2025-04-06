import json
from .redis_client import get_redis_client # Redis 클라이언트 함수 임포트

import logging
import uuid # 고유 Task ID 생성용
import asyncio
import os
from fastapi import FastAPI, HTTPException, Body, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel, Field
from typing import Dict, List, Any

# Celery 앱 및 작업 함수 임포트
from .celery_app import celery_app
from . import tasks

from .ws_manager import manager

from fastapi.middleware.cors import CORSMiddleware

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI 앱 생성 ---
app = FastAPI(
    title="Asynchronous STT Processor Service",
    description="Transcribes audio files asynchronously using Celery and Faster-Whisper.",
    version="0.2.0"
)

# CORS 설정
origins = [
    "http://localhost",         # 로컬 개발 환경 (포트 없이)
    "http://localhost:3000",    # 기본 React 개발 서버 포트
    # 필요에 따라 실제 배포될 프론트엔드 주소 추가
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # 허용할 출처 목록
    allow_credentials=True,          # 쿠키 포함 요청 허용 여부
    allow_methods=["*"],             # 허용할 HTTP 메소드 (GET, POST 등)
    allow_headers=["*"],             # 허용할 HTTP 헤더
)

# --- API 모델 정의 ---
class TranscriptionRequest(BaseModel):
    wav_file_path: str = Field(..., description="Path to the WAV file inside the container.")
    language: str = Field("ja", description="Language code (e.g., 'ja').")

class TranscriptionResponse(BaseModel):
    task_id: str = Field(..., description="Unique ID for the transcription task.")
    status: str = Field("Queued", description="Initial status of the task.")
    websocket_url: str = Field(..., description="Relative URL for WebSocket connection.")
    status_url: str = Field(..., description="Relative URL to poll for task status.")


# --- API 엔드포인트 ---
@app.post("/request_transcription", response_model=TranscriptionResponse, status_code=202, summary="Request Asynchronous Transcription")
async def request_transcription(request: TranscriptionRequest):
    """
    Receives transcription request, queues it for background processing,
    and returns IDs and URLs for status tracking and real-time updates.
    """
    if not os.path.exists(request.wav_file_path):
         logger.error(f"File not found at path provided: {request.wav_file_path}")
         raise HTTPException(status_code=404, detail=f"WAV file not found at: {request.wav_file_path}")

    try:
        # 고유 Task ID 생성 (Celery Task ID와 별개로 API 레벨에서 생성하여 즉시 반환)
        task_id = str(uuid.uuid4())
        logger.info(f"Received transcription request for '{request.wav_file_path}'. Assigned task ID: {task_id}")

        # Celery 백그라운드 작업 등록 (delay() 메서드 사용)
        # Task ID를 작업 함수에 전달하여 WebSocket 통신에 사용
        tasks.process_audio_file.apply_async( # .delay() 대신 .apply_async() 사용
            args=[task_id, request.wav_file_path, request.language], # 인자는 args로 전달
            # kwargs={} # 키워드 인자가 있다면 kwargs로 전달
            queue='priority_queue' # 작업 큐 이름 지정
        )

        # 클라이언트에게 반환할 URL 생성
        ws_url = f"/ws/{task_id}"
        status_url = f"/status/{task_id}"

        return TranscriptionResponse(
            task_id=task_id,
            status="Queued",
            websocket_url=ws_url,
            status_url=status_url
        )
    except Exception as e:
        logger.error(f"Failed to queue transcription task for {request.wav_file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error: Could not queue the task.")

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for clients to receive real-time transcription updates."""
    await manager.connect(websocket, task_id) # 클라이언트 연결 등록

    redis_client = get_redis_client()
    redis_key = f"ws_messages:{task_id}"
    initial_send_failed = False # 이전 메시지 전송 중 오류 플래그

    try:
        # 1. Redis에서 이전 메시지 가져와서 전송 (클라이언트 연결 직후)
        if redis_client: # Redis 클라이언트가 사용 가능할 때만 시도
            try:
                logger.info(f"Retrieving past messages for {task_id} from Redis key {redis_key}")
                # LRANGE key start stop: 리스트의 특정 범위 요소 가져오기 (0 -1 은 전체)
                past_messages_json = redis_client.lrange(redis_key, 0, -1)

                if past_messages_json:
                    logger.info(f"Sending {len(past_messages_json)} past messages to client {task_id}")
                    for msg_json in past_messages_json:
                        try:
                            msg_dict = json.loads(msg_json) # JSON 문자열을 Dictionary로 파싱
                            await websocket.send_json(msg_dict) # 파싱된 메시지 전송
                        except json.JSONDecodeError:
                            logger.warning(f"Could not decode JSON message from Redis for {task_id}: {msg_json}")
                        except WebSocketDisconnect: # 이전 메시지 보내는 중 연결 끊길 경우
                             logger.warning(f"Client {task_id} disconnected while sending past messages.")
                             initial_send_failed = True
                             break # 루프 중단
                        except Exception as send_err:
                            logger.warning(f"Error sending past message to {task_id}: {send_err}")
                            initial_send_failed = True
                            break # 루프 중단 (연결 문제 가능성)
                    if not initial_send_failed:
                         logger.info(f"Finished sending past messages for {task_id}.")
                else:
                     logger.info(f"No past messages found in Redis for task {task_id}.")

            except redis.exceptions.RedisError as redis_err:
                logger.error(f"Failed to retrieve past messages for {task_id} from Redis: {redis_err}", exc_info=True)
            except Exception as e:
                 logger.error(f"Unexpected error retrieving past messages for {task_id}: {e}", exc_info=True)

        # 2. 이후 실시간 메시지 수신 대기 (이전 메시지 전송 실패 시 대기 루프 진입 안 함)
        if not initial_send_failed:
            while True:
                # WebSocket 연결 유지를 위해 주기적으로 sleep 또는 ping/pong 필요
                # 클라이언트로부터 메시지를 받을 수도 있음 (여기서는 생략)
                # await websocket.receive_text()
                await asyncio.sleep(60) # 예: 60초마다 깨어나서 연결 상태 확인

    except WebSocketDisconnect:
        logger.info(f"WebSocket client for task {task_id} disconnected gracefully.")
    except Exception as e:
        # WebSocket 연결 또는 유지 중 예상치 못한 오류 발생
        logger.error(f"WebSocket error for task {task_id}: {e}", exc_info=True)
    finally:
        # 클라이언트 연결 종료 시 항상 ConnectionManager에서 제거
        manager.disconnect(task_id)


@app.get("/status/{task_id}", summary="Get Task Status (Polling)")
async def get_task_status(task_id: str):
    """Retrieves the current status and result (if available) of a transcription task."""
    # Celery의 AsyncResult를 사용하여 작업 상태 확인
    task_result = celery_app.AsyncResult(task_id) # 주의: Celery 내부 Task ID 사용 시 필요

    # API 레벨 Task ID를 사용하므로, 상태는 Redis 등에 별도 저장/조회 필요
    # 여기서는 간단히 Celery 백엔드 조회 예시를 보여주지만, 실제로는 task_id 매핑 필요
    # 또는 Celery 작업 ID를 저장해두었다가 사용
    # -> 여기서는 Redis에 task_id 별 상태를 저장하는 방식이 더 적합

    # 임시 예시: 실제로는 Redis 등에서 task_id로 상태 조회
    status_info = {"status": "UNKNOWN", "progress": None, "result": None, "error": None}
    try:
         # 예시: Redis에서 task_id 관련 정보 가져오기 (구현 필요)
         # status_data_json = redis_client.get(f"task_status:{task_id}")
         # if status_data_json:
         #    status_info = json.loads(status_data_json)
         pass # 실제 구현 필요
    except Exception as e:
         logger.error(f"Failed to get status for task {task_id} from storage: {e}")
         # 상태 조회 실패 시 기본값 반환 또는 오류 처리


    # Celery Task 상태 확인 (만약 Celery task ID를 안다면)
    # celery_task_id = get_celery_task_id_for_api_task(task_id) # DB 등에서 조회
    # if celery_task_id:
    #     celery_task = celery_app.AsyncResult(celery_task_id)
    #     status_info['celery_status'] = celery_task.status
    #     if celery_task.ready():
    #         if celery_task.successful():
    #             status_info['result'] = celery_task.result
    #         else:
    #             status_info['error'] = str(celery_task.info) # 실패 정보

    if status_info["status"] == "UNKNOWN":
         raise HTTPException(status_code=404, detail="Task not found or status not available yet.")

    return status_info

# 앱 초기화 시 로거 설정 등 추가 가능
# @app.on_event("startup")
# async def startup_event():
#     pass

# @app.on_event("shutdown")
# async def shutdown_event():
#     pass