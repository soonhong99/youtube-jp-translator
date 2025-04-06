import json
import redis
from .redis_client import get_redis_client, get_message_ttl # Redis 클라이언트 함수 임포트

import os
import math
import logging
import asyncio
from typing import Any
from pathlib import Path
from pydub import AudioSegment
# from pydub.silence import split_on_silence # 또는 고정 길이 분할 사용

# Celery 앱, STT 함수, WebSocket 매니저 임포트
from .celery_app import celery_app
from .stt import transcribe_audio_file_with_timestamps # STT 로직 (타임스탬프 포함)

# from .main import manager # FastAPI 앱의 WebSocket 매니저 인스턴스
from .ws_manager import manager

logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO) # uvicorn/celery 로거 사용 권장

# --- WebSocket 업데이트 헬퍼 함수 ---
async def _send_ws_update_async(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    """비동기적으로 WebSocket 메시지를 전송하는 내부 함수"""
    message = {"status": status}
    if progress is not None:
        message["progress"] = max(0, min(100, progress)) # 0-100 범위 보장
    if data is not None:
        message["data"] = data # 예: 세그먼트 리스트
    if error is not None:
        message["error"] = error
    try:
        await manager.send_json_message(task_id, message)
    except Exception as e:
        # send_json_message 내부에서 로깅하지만, 여기서도 로깅 가능
        logger.error(f"[Task {task_id}] Failed to send WebSocket update ({status}): {e}")
    
    redis_client = get_redis_client()
    if redis_client: # Redis 클라이언트가 정상적으로 초기화되었을 때만 실행
        try:
            redis_key = f"ws_messages:{task_id}"
            message_json = json.dumps(message) # Dictionary를 JSON 문자열로 변환
            # RPUSH: 리스트 오른쪽에 추가 (시간 순서대로 저장됨)
            redis_client.rpush(redis_key, message_json)
            # EXPIRE: 키에 만료 시간 설정 (초 단위)
            redis_client.expire(redis_key, get_message_ttl())
            logger.debug(f"Saved WS message to Redis list {redis_key}")
        except json.JSONDecodeError as json_err:
             logger.error(f"[Task {task_id}] Failed to serialize message to JSON: {json_err}", exc_info=True)
        except redis.exceptions.RedisError as redis_err:
            logger.error(f"[Task {task_id}] Failed to save WS message to Redis: {redis_err}", exc_info=True)
        except Exception as e:
            logger.error(f"[Task {task_id}] Unexpected error saving WS message to Redis: {e}", exc_info=True)
    else:
        logger.warning(f"[Task {task_id}] Redis client not available, skipping message save.")

def send_ws_update(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    """동기 Celery 작업 내에서 WebSocket 업데이트를 보내기 위한 동기 래퍼"""
    try:
        # Celery 작업 내에서 실행되므로 기존 이벤트 루프를 사용하거나 새로 생성
        loop = asyncio.get_event_loop()
        if loop.is_closed():
             loop = asyncio.new_event_loop()
             asyncio.set_event_loop(loop)

        # asyncio.run()은 새 루프를 만들므로 run_until_complete 사용
        loop.run_until_complete(
            _send_ws_update_async(task_id, status, progress, data, error)
        )
    except RuntimeError as e:
         # 루프 관련 문제 발생 시 (예: 다른 스레드에서 루프 실행)
         logger.error(f"[Task {task_id}] RuntimeError sending WS update ({status}): {e}. Trying with a new loop.")
         try:
             # 새 이벤트 루프에서 실행 시도
             asyncio.run(_send_ws_update_async(task_id, status, progress, data, error))
         except Exception as final_e:
             logger.error(f"[Task {task_id}] Final attempt failed to send WS update ({status}): {final_e}")
    except Exception as e:
        logger.error(f"[Task {task_id}] Unexpected error sending WS update ({status}): {e}", exc_info=True)


# --- 메인 Celery 작업: 오디오 분할 및 서브태스크 관리 ---
@celery_app.task(bind=True, name="process_audio_file")
def process_audio_file(self, task_id: str, wav_file_path: str, language: str = "ja"):
    """
    전체 오디오 파일을 처리하는 메인 작업.
    1. 오디오 분할
    2. 각 청크에 대한 STT 서브태스크 생성 및 실행 요청
    3. WebSocket을 통해 진행 상황 및 결과 전송
    """
    logger.info(f"[Task {task_id}] Processing started for: {wav_file_path}")
    send_ws_update(task_id, "PROCESSING", progress=0)

    # 임시 청크 저장 디렉토리 생성
    # 공유 볼륨 내에 생성해야 워커가 접근 가능
    base_dir = Path(wav_file_path).parent
    chunk_output_dir = base_dir / f"chunks_{task_id}"
    try:
        chunk_output_dir.mkdir(exist_ok=True, parents=True)
    except OSError as e:
        logger.error(f"[Task {task_id}] Failed to create chunk directory {chunk_output_dir}: {e}")
        send_ws_update(task_id, "FAILED", error=f"Cannot create temporary directory: {e}")
        raise # 작업 실패 처리

    chunk_paths = [] # 생성된 청크 파일 경로 저장
    total_processed_duration = 0.0 # 오프셋 계산용

    try:
        # 1. 오디오 로드 및 분할
        logger.info(f"[Task {task_id}] Loading audio file...")
        audio = AudioSegment.from_wav(wav_file_path)
        total_duration_ms = len(audio)
        logger.info(f"[Task {task_id}] Audio loaded. Duration: {total_duration_ms / 1000:.2f}s")
        send_ws_update(task_id, "PROCESSING", progress=5, data={"message": "Audio loaded, splitting..."})

        # 고정 길이 (예: 60초) 로 분할
        chunk_length_ms = 60 * 1000
        chunks = []
        for i in range(0, total_duration_ms, chunk_length_ms):
            chunks.append(audio[i:min(i + chunk_length_ms, total_duration_ms)])

        if not chunks:
             logger.warning(f"[Task {task_id}] No chunks generated from audio file.")
             send_ws_update(task_id, "COMPLETED", progress=100, data=[]) # 빈 결과 반환
             return []

        logger.info(f"[Task {task_id}] Split into {len(chunks)} chunks.")
        send_ws_update(task_id, "PROCESSING", progress=10, data={"message": f"Split into {len(chunks)} chunks."})

        # 2. 서브태스크 생성 및 실행
        subtask_signatures = []
        chunk_durations_sec = [] # 각 청크 길이 저장 (오프셋 계산용)
        for i, chunk in enumerate(chunks):
            chunk_path = chunk_output_dir / f"chunk_{i}.wav"
            try:
                 logger.debug(f"[Task {task_id}] Exporting chunk {i+1}/{len(chunks)} to {chunk_path}")
                 chunk.export(str(chunk_path), format="wav")
                 chunk_paths.append(str(chunk_path))
                 chunk_durations_sec.append(len(chunk) / 1000.0)
                 # Celery 서브태스크 시그니처 생성
                 subtask_signatures.append(
                     process_stt_chunk(task_id, str(chunk_path), language, i, len(chunks))
                 )
            except Exception as e:
                 logger.error(f"[Task {task_id}] Failed to export chunk {i}: {e}")
                 # 실패한 청크 처리 방안 결정 (예: 건너뛰기, 전체 작업 실패)
                 send_ws_update(task_id, "FAILED", error=f"Failed to process audio chunk {i+1}: {e}")
                 # 필요시 생성된 청크 파일 정리
                 # for p in chunk_paths: os.remove(p)
                 # if chunk_output_dir.exists(): os.rmdir(chunk_output_dir)
                 raise # 전체 작업 실패

        if not subtask_signatures:
             logger.warning(f"[Task {task_id}] No subtasks created.")
             send_ws_update(task_id, "COMPLETED", progress=100, data=[])
             return []


        # Celery group을 사용하여 서브태스크들을 병렬로 실행 요청
        from celery import group, chord
        job = group(subtask_signatures)
        # chord 사용 시: 모든 서브태스크 완료 후 콜백 실행 가능
        # result_group = chord(job)(combine_chunk_results.s(task_id=task_id, chunk_durations=chunk_durations_sec))

        # 여기서는 group 결과만 사용 (서브태스크가 직접 WS 업데이트)
        result_group = job.apply_async()
        logger.info(f"[Task {task_id}] Dispatched {len(subtask_signatures)} chunk subtasks. Group ID: {result_group.id}")
        # 서브태스크가 진행 상황 업데이트하므로, 메인 태스크는 완료 대기 가능
        # (선택적) result_group.get()으로 모든 결과 대기 (타임아웃 설정 권장)
        # results = result_group.get(timeout=3600) # 예: 1시간 타임아웃


        # 메인 태스크는 여기서 종료. 서브태스크들이 결과를 WS로 보내고,
        # 마지막 서브태스크 또는 별도 콜백 태스크가 최종 완료 메시지 전송
        # (아래 finalize_task 예시 참조)

        # 임시: 간단하게 마지막 청크 처리 후 완료 메시지 전송 위임
        # (더 나은 방법: chord 콜백 사용 또는 Redis 등으로 상태 집계)


    except FileNotFoundError:
        logger.error(f"[Task {task_id}] Audio file not found: {wav_file_path}")
        send_ws_update(task_id, "FAILED", error="Input audio file not found.")
        # 실패 시 생성된 파일 정리
        # ... cleanup logic ...
    except Exception as e:
        logger.error(f"[Task {task_id}] Unexpected error in main task: {e}", exc_info=True)
        send_ws_update(task_id, "FAILED", error=f"An unexpected error occurred: {e}")
        # 실패 시 생성된 파일 정리
        # ... cleanup logic ...
        raise # Celery가 실패로 기록하도록 예외 다시 발생


# --- 서브태스크: 개별 오디오 청크 STT 처리 ---
@celery_app.task(name="process_stt_chunk")
def process_stt_chunk(task_id: str, chunk_path: str, language: str, chunk_index: int, total_chunks: int):
    """개별 오디오 청크를 STT 처리하고 결과를 WebSocket으로 전송"""
    logger.info(f"[Task {task_id}] Subtask started for chunk {chunk_index + 1}/{total_chunks}: {chunk_path}")
    try:
        # STT 로직 호출 (타임스탬프 포함 결과 반환 가정)
        segments = transcribe_audio_file_with_timestamps(chunk_path, language)
        logger.info(f"[Task {task_id}] STT complete for chunk {chunk_index + 1}. Found {len(segments)} segments.")

        # 현재 청크의 결과(세그먼트)를 WebSocket으로 전송
        # 진행률 계산 (10% ~ 100% 범위를 청크 수로 나눔)
        progress = 10 + int(90 * (chunk_index + 1) / total_chunks)
        send_ws_update(task_id, "PROCESSING", progress=progress, data=segments) # 부분 결과 전송

        # 마지막 청크 처리 완료 시, 최종 완료 메시지 전송
        if chunk_index == total_chunks - 1:
            logger.info(f"[Task {task_id}] Last chunk processed. Sending final completion message.")
            send_ws_update(task_id, "COMPLETED", progress=100)
            # (선택적) 임시 청크 파일 디렉토리 정리
            chunk_output_dir = Path(chunk_path).parent
            try:
                 for p in chunk_output_dir.glob("*.wav"):
                      os.remove(p)
                 chunk_output_dir.rmdir()
                 logger.info(f"[Task {task_id}] Cleaned up chunk directory: {chunk_output_dir}")
            except Exception as e:
                 logger.warning(f"[Task {task_id}] Could not clean up chunk directory {chunk_output_dir}: {e}")


        return True # 서브태스크 성공 여부 반환 (결과 자체는 WS로 전송됨)

    except FileNotFoundError:
        logger.error(f"[Task {task_id}] Chunk file not found: {chunk_path}")
        send_ws_update(task_id, "CHUNK_FAILED", error=f"Chunk file not found: {chunk_path}")
        # 실패 처리 (예: None 반환 또는 예외 발생)
        return False
    except Exception as e:
        logger.error(f"[Task {task_id}] Error processing chunk {chunk_index + 1}: {e}", exc_info=True)
        send_ws_update(task_id, "CHUNK_FAILED", error=f"Error in chunk {chunk_index + 1}: {e}")
        return False

# (선택 사항) Chord 콜백 함수: 모든 청크 처리 후 결과 취합
# @celery_app.task(name="combine_chunk_results")
# def combine_chunk_results(results, task_id: str, chunk_durations: list):
#     logger.info(f"[Task {task_id}] Combining results from all chunks.")
#     all_segments = []
#     current_offset_sec = 0.0
#     has_failed_chunk = False
#
#     for i, chunk_result in enumerate(results):
#         if chunk_result and isinstance(chunk_result, list): # 성공한 청크 결과 확인
#             for segment in chunk_result:
#                 segment['start'] += current_offset_sec
#                 segment['end'] += current_offset_sec
#                 all_segments.append(segment)
#         elif chunk_result is False: # 명시적 실패 표시
#             has_failed_chunk = True
#             logger.warning(f"[Task {task_id}] Detected failed chunk result at index {i}")
#         else: # 예상치 못한 결과 또는 None
#             logger.warning(f"[Task {task_id}] Invalid or missing result for chunk at index {i}")
#             # 실패로 간주할지 결정
#
#         # 다음 오프셋 계산 (실패 여부와 관계없이 진행)
#         if i < len(chunk_durations):
#             current_offset_sec += chunk_durations[i]
#         else:
#              logger.error(f"[Task {task_id}] Mismatch between results and chunk_durations at index {i}")
#
#     if has_failed_chunk:
#         logger.error(f"[Task {task_id}] Transcription completed with errors (some chunks failed).")
#         send_ws_update(task_id, "FAILED", error="Processing completed with errors in some chunks.", data=all_segments) # 부분 결과라도 보낼 수 있음
#     else:
#         logger.info(f"[Task {task_id}] Successfully combined all chunk results.")
#         send_ws_update(task_id, "COMPLETED", progress=100, data=all_segments) # 최종 통합 결과 전송
#
#     # 최종 결과 저장 등 추가 작업
#     # ...
#     return all_segments # 최종 결과 반환