"""
지능형 버퍼링 서비스 메인 애플리케이션
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from kafka import KafkaProducer, KafkaConsumer

from .core.sentence_completion_buffer import SentenceCompletionBuffer
from .core.context_analyzer import ContextAnalyzer
from .core.timing_optimizer import TimingOptimizer
from .models.completion_models import TextChunk, ProcessingContext, BufferState
from .models.context_models import ContextualSegment

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB_BUFFERING = int(os.getenv('REDIS_DB_BUFFERING', 9))
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(',')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# 전역 상태
redis_client = None
kafka_producer = None
sentence_buffer = None
context_analyzer = None
timing_optimizer = None

# Pydantic 모델
class BufferingRequest(BaseModel):
    task_id: str
    text: str
    start_time: float
    end_time: float
    chunk_id: str
    confidence: float = 0.0
    speaker_id: Optional[str] = None
    audio_features: Optional[Dict] = None

class BufferingResponse(BaseModel):
    task_id: str
    should_trigger: bool
    trigger_reason: Optional[str] = None
    confidence: float = 0.0
    estimated_processing_time: float = 0.0
    recommended_batch_size: int = 1
    buffer_status: Dict[str, Any] = {}

class ForceeTriggerRequest(BaseModel):
    task_id: str
    reason: str = "manual"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    global redis_client, kafka_producer, sentence_buffer, context_analyzer, timing_optimizer

    try:
        # Redis 연결
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB_BUFFERING,
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("✅ Redis 연결 완료")

        # Kafka 프로듀서 초기화
        kafka_producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8'),
            key_serializer=lambda x: x.encode('utf-8') if x else None
        )
        logger.info("✅ Kafka 프로듀서 초기화 완료")

        # 핵심 컴포넌트 초기화
        sentence_buffer = SentenceCompletionBuffer(redis_client)
        context_analyzer = ContextAnalyzer(redis_client)
        timing_optimizer = TimingOptimizer(redis_client)

        # 컴포넌트 시작
        await timing_optimizer.start()
        await context_analyzer.start() if hasattr(context_analyzer, 'start') else None

        # Kafka 컨슈머 시작
        asyncio.create_task(start_kafka_consumer())

        logger.info("✅ 지능형 버퍼링 서비스 시작 완료")

        yield

    except Exception as e:
        logger.error(f"❌ 애플리케이션 시작 실패: {e}")
        raise

    finally:
        # 정리
        try:
            if timing_optimizer:
                await timing_optimizer.stop()
            if context_analyzer and hasattr(context_analyzer, 'stop'):
                await context_analyzer.stop()
            if redis_client:
                await redis_client.close()
            if kafka_producer:
                kafka_producer.close()

            logger.info("✅ 지능형 버퍼링 서비스 종료 완료")

        except Exception as e:
            logger.error(f"❌ 애플리케이션 종료 오류: {e}")

# FastAPI 애플리케이션
app = FastAPI(
    title="Intelligent Buffering Service",
    description="Phase 3 지능형 버퍼링 시스템",
    version="1.0.0",
    lifespan=lifespan
)

async def start_kafka_consumer():
    """Kafka 컨슈머 시작"""
    try:
        consumer = KafkaConsumer(
            'stt_chunks',           # STT 청크 토픽
            'buffering_requests',   # 버퍼링 요청 토픽
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id='intelligent-buffering',
            auto_offset_reset='latest',
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )

        logger.info("🎧 Kafka 컨슈머 시작")

        for message in consumer:
            try:
                await process_kafka_message(message)
            except Exception as e:
                logger.error(f"❌ Kafka 메시지 처리 실패: {e}")

    except Exception as e:
        logger.error(f"❌ Kafka 컨슈머 오류: {e}")

async def process_kafka_message(message):
    """Kafka 메시지 처리"""
    try:
        topic = message.topic
        data = message.value

        if topic == 'stt_chunks':
            await handle_stt_chunk(data)
        elif topic == 'buffering_requests':
            await handle_buffering_request(data)

    except Exception as e:
        logger.error(f"❌ Kafka 메시지 처리 실패: {e}")

async def handle_stt_chunk(data: Dict):
    """STT 청크 처리"""
    try:
        task_id = data.get('task_id')
        chunk_data = data.get('data', {})

        # TextChunk 생성
        chunk = TextChunk(
            text=chunk_data.get('text', ''),
            start_time=chunk_data.get('start_time', 0.0),
            end_time=chunk_data.get('end_time', 0.0),
            chunk_id=chunk_data.get('chunk_id', ''),
            confidence=chunk_data.get('confidence', 0.0),
            speaker_id=chunk_data.get('speaker_id')
        )

        # 지능형 버퍼링 처리
        decision = await sentence_buffer.add_chunk(task_id, chunk)

        if decision and decision.should_trigger:
            # 번역 트리거 발생
            await send_translation_trigger(task_id, decision)

        logger.debug(f"📥 STT 청크 처리 완료: {task_id}")

    except Exception as e:
        logger.error(f"❌ STT 청크 처리 실패: {e}")

async def handle_buffering_request(data: Dict):
    """버퍼링 요청 처리"""
    try:
        request_data = BufferingRequest(**data)

        # TextChunk 생성
        chunk = TextChunk(
            text=request_data.text,
            start_time=request_data.start_time,
            end_time=request_data.end_time,
            chunk_id=request_data.chunk_id,
            confidence=request_data.confidence,
            speaker_id=request_data.speaker_id
        )

        # 지능형 버퍼링 처리
        decision = await sentence_buffer.add_chunk(request_data.task_id, chunk)

        if decision and decision.should_trigger:
            await send_translation_trigger(request_data.task_id, decision)

    except Exception as e:
        logger.error(f"❌ 버퍼링 요청 처리 실패: {e}")

async def send_translation_trigger(task_id: str, decision):
    """번역 트리거 전송"""
    try:
        # 버퍼 상태 조회
        buffer_status = await sentence_buffer.get_buffer_status(task_id)
        combined_text = sentence_buffer.get_combined_text(task_id) if sentence_buffer else ""

        # 번역 큐 작업 데이터 구성 (워커 풀용)
        translation_task = {
            'task_id': task_id,
            'chunk_id': f"buffer_{int(time.time())}",
            'text': combined_text or '',
            'priority': buffer_status.get('priority', 2) if buffer_status else 2,
            'max_latency': decision.estimated_processing_time if hasattr(decision, 'estimated_processing_time') else 30.0,
            'context': {
                'buffer_status': buffer_status,
                'trigger_reason': decision.reason.value,
                'confidence': decision.confidence
            },
            'timestamp': time.time()
        }

        # Kafka로 번역 큐 전송
        kafka_producer.send(
            'translation_queue',
            key=task_id,
            value=translation_task
        )
        kafka_producer.flush()

        logger.info(f"🚀 번역 작업 큐 전송: {task_id} - {decision.reason.value}")

    except Exception as e:
        logger.error(f"❌ 번역 트리거 전송 실패: {task_id} - {e}")

@app.get("/health")
async def health_check():
    """헬스체크"""
    try:
        # Redis 연결 확인
        await redis_client.ping()

        return {
            "status": "healthy",
            "service": "intelligent-buffering",
            "timestamp": time.time(),
            "components": {
                "redis": "connected",
                "kafka": "connected",
                "sentence_buffer": "active",
                "context_analyzer": "active",
                "timing_optimizer": "active"
            }
        }

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.post("/buffer/add", response_model=BufferingResponse)
async def add_to_buffer(request: BufferingRequest):
    """버퍼에 텍스트 청크 추가"""
    try:
        # TextChunk 생성
        chunk = TextChunk(
            text=request.text,
            start_time=request.start_time,
            end_time=request.end_time,
            chunk_id=request.chunk_id,
            confidence=request.confidence,
            speaker_id=request.speaker_id
        )

        # 문맥 분석 (선택적)
        context_analysis = None
        if request.audio_features:
            # 오디오 특성이 있으면 문맥 분석 수행
            segments = [ContextualSegment(
                text=request.text,
                start_time=request.start_time,
                end_time=request.end_time,
                speaker_id=request.speaker_id
            )]
            context_analysis = await context_analyzer.analyze_context(request.task_id, segments)

        # 지능형 버퍼링 처리
        decision = await sentence_buffer.add_chunk(request.task_id, chunk)

        # 버퍼 상태 조회
        buffer_status = await sentence_buffer.get_buffer_status(request.task_id) or {}

        # 트리거 발생 시 처리
        if decision and decision.should_trigger:
            await send_translation_trigger(request.task_id, decision)

        return BufferingResponse(
            task_id=request.task_id,
            should_trigger=decision.should_trigger if decision else False,
            trigger_reason=decision.reason.value if decision else None,
            confidence=decision.confidence if decision else 0.0,
            estimated_processing_time=decision.estimated_processing_time if decision else 0.0,
            recommended_batch_size=decision.recommended_batch_size if decision else 1,
            buffer_status=buffer_status
        )

    except Exception as e:
        logger.error(f"❌ 버퍼 추가 실패: {request.task_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/buffer/force-trigger")
async def force_trigger(request: ForceeTriggerRequest):
    """강제 트리거"""
    try:
        success = await sentence_buffer.force_trigger(request.task_id, request.reason)

        if success:
            return {
                "task_id": request.task_id,
                "triggered": True,
                "reason": request.reason,
                "message": "강제 트리거 성공"
            }
        else:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    except Exception as e:
        logger.error(f"❌ 강제 트리거 실패: {request.task_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/buffer/status/{task_id}")
async def get_buffer_status(task_id: str):
    """버퍼 상태 조회"""
    try:
        status = await sentence_buffer.get_buffer_status(task_id)

        if status:
            return status
        else:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    except Exception as e:
        logger.error(f"❌ 버퍼 상태 조회 실패: {task_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    """메트릭 조회"""
    try:
        # 각 컴포넌트의 메트릭 수집
        buffer_metrics = await sentence_buffer.get_metrics()
        context_metrics = await context_analyzer.get_context_metrics()
        timing_metrics = await timing_optimizer.get_optimization_metrics()

        return {
            "buffer_metrics": buffer_metrics,
            "context_metrics": context_metrics,
            "timing_metrics": timing_metrics,
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(f"❌ 메트릭 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/context/analyze/{task_id}")
async def analyze_context(task_id: str):
    """문맥 분석"""
    try:
        # 간단한 테스트용 - 실제로는 세그먼트 데이터가 필요
        segments = []  # 실제 구현에서는 Redis에서 조회

        result = await context_analyzer.analyze_context(task_id, segments)

        return {
            "task_id": task_id,
            "context_analysis": result.__dict__ if result else None
        }

    except Exception as e:
        logger.error(f"❌ 문맥 분석 실패: {task_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/timing/optimize")
async def optimize_timing(request: Dict[str, Any]):
    """타이밍 최적화"""
    try:
        # ProcessingContext 구성이 복잡하므로 간단한 API로 제공
        task_id = request.get('task_id', 'test')

        # 실제 구현에서는 더 복잡한 컨텍스트 구성 필요
        from ..models.completion_models import CompletionScore, CompletionLevel

        completion_score = CompletionScore(
            overall_score=request.get('completion_score', 0.5),
            punctuation_score=0.5,
            grammar_score=0.5,
            semantic_score=0.5,
            confidence=0.8,
            level=CompletionLevel.PARTIAL
        )

        # 기본 처리 컨텍스트 생성
        context = ProcessingContext(
            task_id=task_id,
            buffer_state=BufferState(),
            system_load=0.5,
            urgency_level=request.get('urgency_level', 2),
            quality_requirement=request.get('quality_requirement', 0.8),
            cost_priority=request.get('cost_priority', 0.5),
            latency_requirement=request.get('latency_requirement', 10.0)
        )

        decision = await timing_optimizer.optimize_trigger_timing(context, completion_score)

        return {
            "task_id": task_id,
            "timing_decision": {
                "should_trigger": decision.should_trigger,
                "reason": decision.reason.value,
                "confidence": decision.confidence,
                "estimated_processing_time": decision.estimated_processing_time,
                "recommended_batch_size": decision.recommended_batch_size,
                "additional_info": decision.additional_info
            }
        }

    except Exception as e:
        logger.error(f"❌ 타이밍 최적화 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/buffer/cleanup")
async def cleanup_buffers():
    """오래된 버퍼 정리"""
    try:
        removed_count = sentence_buffer.cleanup_old_buffers()

        return {
            "message": "버퍼 정리 완료",
            "removed_buffers": removed_count,
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(f"❌ 버퍼 정리 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
