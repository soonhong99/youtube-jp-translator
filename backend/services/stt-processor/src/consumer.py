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
    send_update_to_kafka(task_id, "PROCESSING", progress=0)

    base_dir = Path(wav_file_path).parent
    chunk_output_dir = base_dir / f"chunks_{task_id}"
    try:
        chunk_output_dir.mkdir(exist_ok=True, parents=True)
    except OSError as e:
        logger.error(f"[Task {task_id}] Failed to create chunk directory {chunk_output_dir}: {e}")
        send_update_to_kafka(task_id, "FAILED", error=f"Cannot create temporary directory: {e}")
        return # 작업 실패

    all_segments_combined = [] # 전체 결과 저장용 (선택 사항)
    has_chunk_error = False

    try:
        # 1. 오디오 로드 및 분할
        logger.info(f"[Task {task_id}] Loading audio file...")
        audio = AudioSegment.from_wav(wav_file_path)
        total_duration_ms = len(audio)
        logger.info(f"[Task {task_id}] Audio loaded. Duration: {total_duration_ms / 1000:.2f}s")
        send_update_to_kafka(task_id, "PROCESSING", progress=5, data={"message": "Audio loaded, splitting..."})

        chunk_length_ms = 60 * 1000
        chunks = [audio[i:min(i + chunk_length_ms, total_duration_ms)] for i in range(0, total_duration_ms, chunk_length_ms)]
        total_chunks = len(chunks)

        if not chunks:
            logger.warning(f"[Task {task_id}] No chunks generated.")
            send_update_to_kafka(task_id, "COMPLETED", progress=100, data=[])
            return

        logger.info(f"[Task {task_id}] Split into {total_chunks} chunks.")
        send_update_to_kafka(task_id, "PROCESSING", progress=10, data={"message": f"Split into {total_chunks} chunks."})

        # 2. 각 청크 처리 (순차적 또는 병렬 처리 구현 필요)
        # 여기서는 간단하게 순차 처리 예시
        for i, chunk in enumerate(chunks):
            chunk_path_obj = chunk_output_dir / f"chunk_{i}.wav"
            chunk_path = str(chunk_path_obj)
            chunk_start_time_sec = (i * chunk_length_ms) / 1000.0 # 청크 시작 오프셋

            try:
                logger.debug(f"[Task {task_id}] Exporting chunk {i+1}/{total_chunks} to {chunk_path}")
                chunk.export(chunk_path, format="wav")

                logger.info(f"[Task {task_id}] Starting STT for chunk {i+1}/{total_chunks}")
                # STT 함수 호출
                segments = transcribe_audio_file_with_timestamps(chunk_path, language)
                logger.info(f"[Task {task_id}] STT complete for chunk {i+1}. Found {len(segments)} segments.")

                # 결과 세그먼트의 타임스탬프 조정 (청크 오프셋 반영)
                adjusted_segments = []
                for seg in segments:
                    adjusted_seg = seg.copy()
                    adjusted_seg['start'] += chunk_start_time_sec
                    adjusted_seg['end'] += chunk_start_time_sec
                    adjusted_segments.append(adjusted_seg)
                    all_segments_combined.append(adjusted_seg) # 전체 결과 누적

                # 조정된 세그먼트를 Kafka로 전송
                progress = 10 + int(90 * (i + 1) / total_chunks)
                send_update_to_kafka(task_id, "PROCESSING", progress=progress, data=adjusted_segments)

                # 임시 청크 파일 삭제 (선택적)
                # os.remove(chunk_path)

            except FileNotFoundError:
                 logger.error(f"[Task {task_id}] Chunk file not found: {chunk_path}")
                 send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"Chunk file not found: {chunk_path}")
                 has_chunk_error = True
            except RuntimeError as stt_err: # STT 모델 로드 실패 등
                 logger.error(f"[Task {task_id}] STT Runtime error for chunk {i+1}: {stt_err}", exc_info=True)
                 send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"STT Runtime error in chunk {i+1}: {stt_err}")
                 has_chunk_error = True
            except Exception as e:
                logger.error(f"[Task {task_id}] Error processing chunk {i+1}: {e}", exc_info=True)
                send_update_to_kafka(task_id, "CHUNK_FAILED", error=f"Error processing chunk {i+1}: {e}")
                has_chunk_error = True
                # 오류 발생 시 계속 진행할지 결정

        # 3. 최종 완료/실패 메시지 전송
        if has_chunk_error:
            logger.warning(f"[Task {task_id}] Processing finished with errors.")
            send_update_to_kafka(task_id, "FAILED", progress=100, error="Processing completed with errors in some chunks.")
        else:
            logger.info(f"[Task {task_id}] Processing completed successfully.")
            # 최종 완료 메시지 (선택적으로 전체 세그먼트 포함 가능)
            # send_update_to_kafka(task_id, "COMPLETED", progress=100, data=all_segments_combined)
            send_update_to_kafka(task_id, "COMPLETED", progress=100)


    except FileNotFoundError:
        logger.error(f"[Task {task_id}] Main audio file not found: {wav_file_path}")
        send_update_to_kafka(task_id, "FAILED", error="Input audio file not found.")
    except Exception as e:
        logger.error(f"[Task {task_id}] Unexpected error during main processing: {e}", exc_info=True)
        send_update_to_kafka(task_id, "FAILED", error=f"An unexpected error occurred: {e}")
    finally:
        # 최종적으로 임시 청크 디렉토리 정리 (선택적)
        try:
            if chunk_output_dir.exists():
                for p in chunk_output_dir.glob("*.wav"):
                    os.remove(p)
                chunk_output_dir.rmdir()
                logger.info(f"[Task {task_id}] Cleaned up chunk directory: {chunk_output_dir}")
        except Exception as e:
            logger.warning(f"[Task {task_id}] Could not clean up chunk directory {chunk_output_dir}: {e}")

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