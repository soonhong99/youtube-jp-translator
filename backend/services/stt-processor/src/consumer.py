# stt-processor/src/consumer.py

import os
import json
import logging
import time
from pathlib import Path
from pydub import AudioSegment
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
from typing import Any

# 내부 모듈 임포트
from stt import transcribe_audio_file_with_timestamps # STT 함수 (stt.py 파일 필요)
from kafka_config import KAFKA_BOOTSTRAP_SERVERS, STT_REQUEST_TOPIC, STT_RESULT_TOPIC

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("KafkaSTTConsumer")

# --- Kafka Producer 초기화 (결과 전송용 - 재시도 로직 추가) ---
producer = None
MAX_RETRIES = 5
RETRY_DELAY = 5

for attempt in range(MAX_RETRIES):
    try:
        logger.info(f"Attempting to initialize Kafka Producer for results (Attempt {attempt + 1}/{MAX_RETRIES})...")
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=3, # Producer 내부 재시도
            # request_timeout_ms=10000 # 필요시 타임아웃 추가
        )
        # 간단한 연결 테스트 (예: 토픽 메타데이터 요청)
        producer.partitions_for(STT_RESULT_TOPIC) # 실제 통신 시도
        logger.info(f"Kafka Producer for results connected successfully to {KAFKA_BOOTSTRAP_SERVERS}")
        break # 성공 시 루프 탈출
    except KafkaError as e:
        logger.warning(f"Failed to initialize Kafka Producer for results (Attempt {attempt + 1}): {e}. Retrying in {RETRY_DELAY} seconds...")
        if attempt == MAX_RETRIES - 1:
            logger.error("Max retries reached. Failed to initialize Kafka Producer for results.", exc_info=True)
            producer = None
        time.sleep(RETRY_DELAY)
    except Exception as e:
         logger.error(f"Unexpected error during Kafka Producer initialization in consumer (Attempt {attempt + 1}): {e}", exc_info=True)
         producer = None
         break # 예상치 못한 오류는 중단



# --- 결과/진행상황 전송 함수 ---
def send_update_to_kafka(task_id: str, status: str, progress: int = None, data: Any = None, error: str = None):
    if not producer:
        logger.error(f"[Task {task_id}] Kafka Producer not available. Cannot send update: {status}")
        return

    message = {"task_id": task_id, "status": status}
    if progress is not None: message["progress"] = max(0, min(100, progress))
    if data is not None: message["data"] = data
    if error is not None: message["error"] = error

    try:
        logger.info(f"Sending update to Kafka topic '{STT_RESULT_TOPIC}' for task {task_id}: Status={status}")
        future = producer.send(STT_RESULT_TOPIC, value=message, key=task_id.encode('utf-8'))
        # 전송 완료 동기 확인 (선택적, 성능 영향 있을 수 있음)
        # record_metadata = future.get(timeout=10)
        # logger.debug(f"Update sent to topic {record_metadata.topic} partition {record_metadata.partition}")
        producer.flush() # 메시지 전송 시도
    except KafkaError as e:
        logger.error(f"Failed to send update message to Kafka for task {task_id}: {e}", exc_info=True)
    except Exception as e:
         logger.error(f"Unexpected error sending update message to Kafka for task {task_id}: {e}", exc_info=True)


# --- 메인 처리 함수 ---
def process_stt_request(task_id: str, wav_file_path: str, language: str):
    """STT 요청 처리: 오디오 분할, 청크별 STT, 결과 Kafka 전송"""
    logger.info(f"[Task {task_id}] Processing started for: {wav_file_path}")
    # 초기 상태 업데이트: 작업 시작 알림
    send_update_to_kafka(task_id, "PROCESSING", progress=0, data={"message": "Audio processing initiated."})

    base_dir = Path(wav_file_path).parent
    # 작업별 고유한 청크 디렉토리 이름 생성 (충돌 방지)
    chunk_output_dir_name = f"chunks_{task_id}"
    chunk_output_dir = base_dir / chunk_output_dir_name
    try:
        chunk_output_dir.mkdir(exist_ok=True, parents=True)
        logger.info(f"[Task {task_id}] Created chunk directory: {chunk_output_dir}")
    except OSError as e:
        logger.error(f"[Task {task_id}] Failed to create chunk directory {chunk_output_dir}: {e}")
        send_update_to_kafka(task_id, "FAILED", error=f"Cannot create temporary directory: {e}")
        return

    all_segments_combined = [] # 모든 STT 세그먼트를 축적할 리스트
    has_chunk_error = False

    try:
        logger.info(f"[Task {task_id}] Loading audio file: {wav_file_path}")
        audio = AudioSegment.from_wav(wav_file_path)
        total_duration_ms = len(audio)
        logger.info(f"[Task {task_id}] Audio loaded. Duration: {total_duration_ms / 1000:.2f}s")
        send_update_to_kafka(task_id, "PROCESSING", progress=5, data={"message": "Audio loaded, splitting into chunks..."})

        chunk_length_ms = 60 * 1000  # 60초 단위로 청크 분할
        chunks = [audio[i:min(i + chunk_length_ms, total_duration_ms)] for i in range(0, total_duration_ms, chunk_length_ms)]
        total_chunks = len(chunks)

        if not chunks: # 청크가 생성되지 않은 경우 (예: 매우 짧은 오디오)
            logger.warning(f"[Task {task_id}] No audio chunks were generated from the input file.")
            # STT 작업은 완료되었지만, 번역할 내용이 없음을 API에 알림
            send_update_to_kafka(task_id, "STT_COMPLETED_ALL_SEGMENTS", progress=95, data=[])
            return

        logger.info(f"[Task {task_id}] Audio split into {total_chunks} chunks.")
        send_update_to_kafka(task_id, "PROCESSING", progress=10, data={"message": f"Split into {total_chunks} chunks."})

        # 각 청크 순차 처리
        for i, chunk_audio_segment in enumerate(chunks):
            chunk_file_name = f"chunk_{i}.wav"
            chunk_path_obj = chunk_output_dir / chunk_file_name
            chunk_path_str = str(chunk_path_obj)
            # 현재 청크의 시작 시간 오프셋 (전체 오디오 기준, 초 단위)
            current_chunk_start_offset_sec = (i * chunk_length_ms) / 1000.0

            try:
                logger.debug(f"[Task {task_id}] Exporting chunk {i+1}/{total_chunks} to {chunk_path_str}")
                chunk_audio_segment.export(chunk_path_str, format="wav")

                logger.info(f"[Task {task_id}] Starting STT for chunk {i+1}/{total_chunks} (Path: {chunk_path_str})")
                # STT 함수 호출 (결과는 [{ 'start': float, 'end': float, 'text': str }, ...])
                segments_in_chunk = transcribe_audio_file_with_timestamps(chunk_path_str, language)
                logger.info(f"[Task {task_id}] STT for chunk {i+1} completed. Found {len(segments_in_chunk)} segments.")

                # 현재 청크의 세그먼트들의 타임스탬프를 전체 오디오 기준으로 조정
                adjusted_segments_for_this_chunk = []
                for seg in segments_in_chunk:
                    adjusted_seg = seg.copy() # 원본 수정을 피하기 위해 복사
                    # round 함수로 소수점 자릿수 정리 (예: 3자리)
                    adjusted_seg['start'] = round(seg['start'] + current_chunk_start_offset_sec, 3)
                    adjusted_seg['end'] = round(seg['end'] + current_chunk_start_offset_sec, 3)
                    adjusted_segments_for_this_chunk.append(adjusted_seg)
                    all_segments_combined.append(adjusted_seg) # 전체 결과 리스트에도 누적

                # (선택적 유지) 현재 청크의 (타임스탬프 조정된) 일본어 결과만 Kafka로 전송
                # 진행률 계산: 초기 10% + STT 진행률 (전체 85% 할당)
                progress_after_chunk = 10 + int(85 * (i + 1) / total_chunks)
                send_update_to_kafka(
                    task_id,
                    "PROCESSING",
                    progress=progress_after_chunk,
                    data=adjusted_segments_for_this_chunk # 현재 청크의 결과만
                )
                
                # 사용한 임시 청크 파일 삭제 (성공적으로 처리된 경우)
                try:
                    os.remove(chunk_path_str)
                    logger.debug(f"[Task {task_id}] Removed temporary chunk file: {chunk_path_str}")
                except OSError as e_remove:
                    logger.warning(f"[Task {task_id}] Could not remove temporary chunk file {chunk_path_str}: {e_remove}")


            except FileNotFoundError:
                 logger.error(f"[Task {task_id}] Chunk file not found during STT processing: {chunk_path_str}")
                 send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"Chunk file not found: {chunk_path_str}")
                 has_chunk_error = True
            except RuntimeError as stt_err: # STT 모델 자체의 런타임 오류 등
                 logger.error(f"[Task {task_id}] STT Runtime error for chunk {i+1}: {stt_err}", exc_info=True)
                 send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"STT error in chunk {i+1}: {stt_err}")
                 has_chunk_error = True
            except Exception as e: # 기타 예외 처리
                logger.error(f"[Task {task_id}] Unexpected error processing chunk {i+1}: {e}", exc_info=True)
                send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"Error in chunk {i+1}: {e}")
                has_chunk_error = True
                # 중대한 오류 시 여기서 루프를 중단할지(break) 아니면 계속 진행할지 결정 필요

        # --- 모든 청크 처리 완료 후 ---
        if has_chunk_error:
            logger.warning(f"[Task {task_id}] STT processing finished with errors in some chunks.")
            send_update_to_kafka(task_id, "FAILED", progress=100, error="Processing completed with errors during STT.")
        else:
            logger.info(f"[Task {task_id}] All STT chunks processed successfully. Sending combined segments for batch translation trigger.")
            # *** 핵심 수정: 모든 일본어 세그먼트를 포함한 메시지를 API에 전달하여 일괄 번역 트리거 ***
            send_update_to_kafka(
                task_id,
                "STT_COMPLETED_ALL_SEGMENTS", # API가 이 상태를 보고 일괄 번역 시작
                progress=95, # STT 완료, 번역 대기 상태 (95%로 설정)
                data=all_segments_combined # 모든 (타임스탬프 조정된) 일본어 세그먼트 리스트
            )

    except FileNotFoundError: # 메인 오디오 파일 로드 실패
        logger.error(f"[Task {task_id}] Main audio file not found: {wav_file_path}")
        send_update_to_kafka(task_id, "FAILED", error=f"Input audio file not found: {wav_file_path}")
    except Exception as e: # 그 외 예기치 못한 오류
        logger.error(f"[Task {task_id}] Unexpected error during main STT processing: {e}", exc_info=True)
        send_update_to_kafka(task_id, "FAILED", error=f"An unexpected error occurred: {e}")
    finally:
        # 임시 청크 디렉토리 정리
        try:
            if chunk_output_dir.exists():
                # 디렉토리 내 파일들을 먼저 삭제 (선택적: shutil.rmtree 사용 시 불필요)
                # for p_file in chunk_output_dir.glob("*.wav"):
                #     try:
                #         os.remove(p_file)
                #     except Exception as e_remove_final:
                #         logger.warning(f"[Task {task_id}] Failed to remove chunk file {p_file} during final cleanup: {e_remove_final}")
                # 디렉토리 삭제 (shutil.rmtree 사용 권장)
                import shutil
                shutil.rmtree(chunk_output_dir)
                logger.info(f"[Task {task_id}] Successfully cleaned up chunk directory: {chunk_output_dir}")
        except Exception as e_cleanup:
            logger.warning(f"[Task {task_id}] Error during final cleanup of chunk directory {chunk_output_dir}: {e_cleanup}")


# --- Kafka Consumer 루프 ---
def run_consumer():
    if KAFKA_BOOTSTRAP_SERVERS is None:
        logger.critical("Kafka bootstrap servers not configured. Consumer cannot start.")
        return

    consumer = None
    while True: # 지속적으로 재연결 시도
        try:
            consumer = KafkaConsumer(
                STT_REQUEST_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                group_id='stt_request_workers', # 워커 그룹 ID (여러 워커 실행 시 필요)
                auto_offset_reset='earliest',
                # enable_auto_commit=False # 수동 커밋으로 변경하여 처리 보장 강화 가능
            )
            logger.info(f"Kafka Consumer connected, subscribed to {STT_REQUEST_TOPIC}. Waiting for messages...")

            for message in consumer:
                try:
                    request_data = message.value
                    task_id = request_data.get('task_id')
                    wav_path = request_data.get('wav_file_path')
                    lang = request_data.get('language', 'ja')

                    if task_id and wav_path:
                        logger.info(f"Received request for task {task_id}, file: {wav_path}")
                        # 실제 처리 함수 호출
                        process_stt_request(task_id, wav_path, lang)
                        # 수동 커밋 사용 시 여기서 커밋
                        # consumer.commit()
                    else:
                        logger.warning(f"Invalid message received: {request_data}")

                except json.JSONDecodeError:
                     logger.error(f"Failed to decode request message value: {message.value}")
                except Exception as e:
                    logger.error(f"Error processing request message: {e}", exc_info=True)
                    # 오류 발생 시 해당 메시지 처리 실패, 다음 메시지로 넘어감 (오프셋은 자동 커밋됨)

        except KafkaError as e:
            logger.error(f"Kafka Consumer connection error: {e}. Retrying in 10 seconds...")
            if consumer:
                try: consumer.close()
                except: pass
            time.sleep(10)
        except Exception as e:
             logger.error(f"Unexpected error in consumer loop: {e}. Retrying in 10 seconds...", exc_info=True)
             if consumer:
                 try: consumer.close()
                 except: pass
             time.sleep(10)

if __name__ == "__main__":
    # stt.py가 먼저 로드되어 모델 초기화하도록 함 (중요)
    logger.info("Initializing STT model...")
    if not transcribe_audio_file_with_timestamps: # 간단한 체크
        logger.critical("STT function not available from stt.py")
        exit(1)
    logger.info("STT model initialization likely complete (check previous logs). Starting consumer loop.")
    run_consumer()