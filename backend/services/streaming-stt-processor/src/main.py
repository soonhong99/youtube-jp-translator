"""
Streaming STT Processor API Server
5초 청크 + 1초 오버랩 방식으로 실시간 일본어 STT 처리
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
import uvicorn

from streaming_worker import StreamingSTTWorker
import os
from audio_chunker import AudioChunker
from sentence_detector import JapaneseSentenceDetector
from whisper_pool import WhisperModelPool
from config import StreamingSTTConfig
from utils import setup_logging, health_check
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import json
from kafka import KafkaConsumer

# 로깅 설정
setup_logging()
logger = logging.getLogger(__name__)

# 글로벌 컴포넌트들
config = StreamingSTTConfig()
whisper_pool = None
audio_chunker = None
sentence_detector = None
streaming_worker = None

class StreamingSTTRequest(BaseModel):
    task_id: str = Field(..., description="작업 ID")
    audio_file_path: str = Field(..., description="오디오 파일 경로")
    language: str = Field(default="ja", description="음성 언어")
    chunk_duration: float = Field(default=5.0, description="청크 길이 (초)")
    overlap_duration: float = Field(default=1.0, description="오버랩 길이 (초)")
    priority: int = Field(default=1, description="우선순위 (1=높음, 5=낮음)")

class StreamingSTTResponse(BaseModel):
    task_id: str
    status: str
    message: str
    estimated_duration: float = 0.0

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 시 리소스 관리"""
    global whisper_pool, audio_chunker, sentence_detector, streaming_worker

    try:
        logger.info("🚀 Streaming STT Processor 초기화 시작...")

        # Whisper 모델 풀 초기화 (3개 인스턴스)
        whisper_pool = WhisperModelPool(
            model_name=config.WHISPER_MODEL,
            pool_size=config.WHISPER_POOL_SIZE,
            device=config.DEVICE
        )
        await whisper_pool.initialize()
        logger.info(f"✅ Whisper 모델 풀 초기화 완료 (크기: {config.WHISPER_POOL_SIZE})")

        # 오디오 청커 초기화
        audio_chunker = AudioChunker(
            chunk_duration=config.DEFAULT_CHUNK_DURATION,
            overlap_duration=config.DEFAULT_OVERLAP_DURATION,
            sample_rate=config.AUDIO_SAMPLE_RATE
        )
        logger.info("✅ 오디오 청커 초기화 완료")

        # 일본어 문장 감지기 초기화
        sentence_detector = JapaneseSentenceDetector()
        logger.info("✅ 일본어 문장 감지기 초기화 완료")

        # 스트리밍 워커 초기화
        streaming_worker = StreamingSTTWorker(
            whisper_pool=whisper_pool,
            audio_chunker=audio_chunker,
            sentence_detector=sentence_detector,
            config=config
        )
        await streaming_worker.start()
        logger.info("✅ 스트리밍 STT 워커 시작 완료")

        # Kafka 컨슈머 시작 (스트리밍 요청)
        asyncio.create_task(start_kafka_consumer())

        logger.info("🎉 Streaming STT Processor 초기화 완료!")
        yield

    except Exception as e:
        logger.error(f"❌ 초기화 실패: {e}")
        raise

    finally:
        # 정리 작업
        logger.info("🔄 Streaming STT Processor 종료 중...")

        if streaming_worker:
            await streaming_worker.stop()
            logger.info("✅ 스트리밍 워커 종료 완료")

        if whisper_pool:
            await whisper_pool.cleanup()
            logger.info("✅ Whisper 모델 풀 정리 완료")

        logger.info("👋 Streaming STT Processor 종료 완료")

# FastAPI 앱 생성
app = FastAPI(
    title="Streaming STT Processor",
    description="실시간 일본어 음성 인식 서비스 (5초 청크 + 1초 오버랩)",
    version="2.0.0",
    lifespan=lifespan
)

async def start_kafka_consumer():
    """Kafka 컨슈머 시작: streaming_requests 토픽 소비"""
    try:
        # 호환성을 위해 두 토픽을 모두 구독 (env로 커스터마이즈 가능)
        legacy_topic = config.KAFKA_TOPIC_STREAMING_REQUESTS  # 기본: streaming_requests
        stt_api_topic = os.getenv("KAFKA_TOPIC_STT_REQUESTS", "stt_requests")

        topics = [t for t in [legacy_topic, stt_api_topic] if t]

        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS.split(','),
            group_id='streaming-stt-processor',
            auto_offset_reset='latest',
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )

        logger.info(f"🎧 Kafka 컨슈머 시작: {', '.join(topics)}")

        while True:
            records = await asyncio.to_thread(consumer.poll, timeout_ms=1000)
            if not records:
                continue
            for _tp, messages in records.items():
                for message in messages:
                    try:
                        data = message.value or {}
                        task_id = data.get('task_id')
                        if not task_id:
                            continue
                        # 호환: stt-processor-api는 wav_file_path를 사용
                        audio_file_path = data.get('audio_file_path') or data.get('wav_file_path')
                        if not audio_file_path:
                            logger.warning(f"⚠️ Kafka 메시지에 오디오 경로가 없습니다: task_id={task_id}")
                            continue
                        language = data.get('language', 'ja')
                        chunk_duration = float(data.get('chunk_duration', config.DEFAULT_CHUNK_DURATION))
                        overlap_duration = float(data.get('overlap_duration', config.DEFAULT_OVERLAP_DURATION))
                        priority = int(data.get('priority', 1))

                        # 백그라운드로 처리 시작
                        asyncio.create_task(
                            streaming_worker.process_streaming_stt(
                                task_id=task_id,
                                audio_file_path=audio_file_path,
                                language=language,
                                chunk_duration=chunk_duration,
                                overlap_duration=overlap_duration,
                                priority=priority
                            )
                        )
                        logger.info(f"📝 스트리밍 요청 수신(Kafka): {task_id} (topic={message.topic})")

                    except Exception as e:
                        logger.error(f"❌ streaming_requests 처리 실패: {e}")

    except Exception as e:
        logger.error(f"❌ Kafka 컨슈머 오류(streaming_requests): {e}")

@app.get("/health")
async def health_endpoint():
    """헬스 체크 엔드포인트"""
    return await health_check(whisper_pool, streaming_worker)

@app.get("/status")
async def status():
    """서비스 상태 조회"""
    if not all([whisper_pool, streaming_worker]):
        raise HTTPException(status_code=503, detail="서비스가 초기화되지 않았습니다")

    pool_status = await whisper_pool.get_status()
    worker_status = await streaming_worker.get_status()

    return {
        "service": "streaming-stt-processor",
        "version": "2.0.0",
        "status": "running",
        "whisper_pool": pool_status,
        "worker": worker_status,
        "config": {
            "model": config.WHISPER_MODEL,
            "pool_size": config.WHISPER_POOL_SIZE,
            "device": config.DEVICE,
            "chunk_duration": config.DEFAULT_CHUNK_DURATION,
            "overlap_duration": config.DEFAULT_OVERLAP_DURATION
        }
    }

@app.post("/process", response_model=StreamingSTTResponse)
async def process_streaming_stt(
    request: StreamingSTTRequest,
    background_tasks: BackgroundTasks
):
    """스트리밍 STT 처리 요청"""
    if not streaming_worker:
        raise HTTPException(status_code=503, detail="스트리밍 워커가 초기화되지 않았습니다")

    try:
        logger.info(f"📝 스트리밍 STT 요청 수신: {request.task_id}")

        # 오디오 파일 정보 확인
        duration = await audio_chunker.get_audio_duration(request.audio_file_path)
        if duration <= 0:
            raise HTTPException(status_code=400, detail="유효하지 않은 오디오 파일")

        # 백그라운드에서 스트리밍 처리 시작
        background_tasks.add_task(
            streaming_worker.process_streaming_stt,
            task_id=request.task_id,
            audio_file_path=request.audio_file_path,
            language=request.language,
            chunk_duration=request.chunk_duration,
            overlap_duration=request.overlap_duration,
            priority=request.priority
        )

        logger.info(f"✅ 스트리밍 STT 처리 시작: {request.task_id} (예상 시간: {duration:.1f}초)")

        return StreamingSTTResponse(
            task_id=request.task_id,
            status="processing",
            message="스트리밍 STT 처리가 시작되었습니다",
            estimated_duration=duration
        )

    except Exception as e:
        logger.error(f"❌ 스트리밍 STT 처리 오류: {e}")
        raise HTTPException(status_code=500, detail=f"처리 오류: {str(e)}")

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """작업 상태 조회"""
    if not streaming_worker:
        raise HTTPException(status_code=503, detail="스트리밍 워커가 초기화되지 않았습니다")

    status = await streaming_worker.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    return status

@app.get("/stats")
async def get_stats():
    """서비스 통계(JSON)"""
    if not all([whisper_pool, streaming_worker]):
        return {"error": "서비스가 초기화되지 않았습니다"}

    pool_metrics = await whisper_pool.get_metrics()
    worker_metrics = await streaming_worker.get_metrics()

    return {
        "whisper_pool": pool_metrics,
        "worker": worker_metrics,
        "timestamp": asyncio.get_event_loop().time()
    }

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """작업 취소"""
    if not streaming_worker:
        raise HTTPException(status_code=503, detail="스트리밍 워커가 초기화되지 않았습니다")

    success = await streaming_worker.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없거나 취소할 수 없습니다")

    return {"message": f"작업 {task_id}가 취소되었습니다"}

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """글로벌 예외 처리"""
    logger.error(f"❌ 예상치 못한 오류: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "내부 서버 오류가 발생했습니다"}
    )

if __name__ == "__main__":
    # 개발 환경에서 직접 실행
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8007,
        reload=True,
        log_level="info"
    )
