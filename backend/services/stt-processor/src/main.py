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

# WebSocket Manager 임포트 (새 파일에서 가져옴)
from .ws_manager import manager # <--- 변경된 부분

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FastAPI 앱 생성 ---
app = FastAPI(
    title="Asynchronous STT Processor Service",
    description="Transcribes audio files asynchronously using Celery and Faster-Whisper.",
    version="0.2.0"
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
        tasks.process_audio_file.delay(
            task_id=task_id,
            wav_file_path=request.wav_file_path,
            language=request.language
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
    await manager.connect(websocket, task_id)
    try:
        # 연결 유지 및 클라이언트 메시지 수신 (선택 사항)
        while True:
            # data = await websocket.receive_text() # 클라이언트로부터 메시지 받기 (예: 핑퐁)
            # logger.debug(f"Received WS message from {task_id}: {data}")
            # 서버 -> 클라이언트 메시지는 Celery Task에서 manager를 통해 전송됨
            await asyncio.sleep(30) # 연결 유지를 위한 대기 (또는 PING 전송)
    except WebSocketDisconnect:
        logger.info(f"WebSocket client for task {task_id} disconnected gracefully.")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}", exc_info=True)
    finally:
        # 연결 종료 시 정리
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