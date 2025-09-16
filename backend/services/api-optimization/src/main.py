"""
API 최적화 서비스 메인 애플리케이션
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

from .caching.intelligent_cache import IntelligentCache
from .batch.dynamic_batcher import DynamicBatcher, BatchPriority
from .optimization.cost_optimizer import CostOptimizer, ModelType

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경변수
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB_OPTIMIZATION = int(os.getenv('REDIS_DB_OPTIMIZATION', 10))
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092').split(',')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# 전역 상태
redis_client = None
kafka_producer = None
intelligent_cache = None
dynamic_batcher = None
cost_optimizer = None

# Pydantic 모델
class TranslationRequest(BaseModel):
    task_id: str
    source_text: str
    target_language: str = "ko"
    priority: str = "normal"  # low, normal, high, critical
    max_cost: Optional[float] = None
    min_quality: Optional[float] = None
    max_latency: Optional[float] = None
    context: Optional[Dict] = None

class TranslationResponse(BaseModel):
    task_id: str
    source_text: str
    translated_text: str
    model_used: str
    processing_time: float
    cost: float
    cache_hit: bool
    quality_score: float
    confidence: float

class BatchTranslationRequest(BaseModel):
    batch_id: str
    requests: List[TranslationRequest]
    priority: str = "normal"

class ModelSelectionRequest(BaseModel):
    estimated_tokens: int
    priority: str = "normal"
    max_cost: Optional[float] = None
    min_quality: Optional[float] = None
    max_latency: Optional[float] = None

async def mock_translation_processor(batch_data: List[Dict]) -> List[Dict]:
    """모의 번역 처리기 (실제로는 번역 워커 풀과 연동)"""
    try:
        results = []

        for data in batch_data:
            # 시뮬레이션 지연
            await asyncio.sleep(0.5)  # 실제 번역 시간 시뮬레이션

            # 모의 번역 결과
            result = {
                'task_id': data.get('task_id', ''),
                'success': True,
                'translated_text': f"[번역됨] {data.get('source_text', '')}",
                'model_used': data.get('model_type', 'gemini-1.5-flash'),
                'processing_time': 0.5,
                'cost': 0.001,
                'quality_score': 0.85
            }
            results.append(result)

        return results

    except Exception as e:
        logger.error(f"❌ 번역 처리 실패: {e}")
        return [{'success': False, 'error': str(e)} for _ in batch_data]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    global redis_client, kafka_producer, intelligent_cache, dynamic_batcher, cost_optimizer

    try:
        # Redis 연결
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB_OPTIMIZATION,
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
        intelligent_cache = IntelligentCache(redis_client)
        # 결과 콜백을 통해 Kafka로 optimized_translation_results 발행
        async def _result_cb(task_id: str, result: Dict):
            await send_translation_result(task_id, result)

        dynamic_batcher = DynamicBatcher(mock_translation_processor, redis_client, result_callback=_result_cb)
        cost_optimizer = CostOptimizer(redis_client)

        # 🔥 CRITICAL FIX: DynamicBatcher에 Kafka 프로듀서 주입
        dynamic_batcher.set_kafka_producer(kafka_producer)

        # 컴포넌트 시작
        await intelligent_cache.start()
        await dynamic_batcher.start()

        # Kafka 컨슈머 시작
        asyncio.create_task(start_kafka_consumer())

        logger.info("✅ API 최적화 서비스 시작 완료")

        yield

    except Exception as e:
        logger.error(f"❌ 애플리케이션 시작 실패: {e}")
        raise

    finally:
        # 정리
        try:
            if intelligent_cache:
                await intelligent_cache.stop()
            if dynamic_batcher:
                await dynamic_batcher.stop()
            if redis_client:
                await redis_client.close()
            if kafka_producer:
                kafka_producer.close()

            logger.info("✅ API 최적화 서비스 종료 완료")

        except Exception as e:
            logger.error(f"❌ 애플리케이션 종료 오류: {e}")

# FastAPI 애플리케이션
app = FastAPI(
    title="API Optimization Service",
    description="Phase 3 API 최적화 시스템",
    version="1.0.0",
    lifespan=lifespan
)

async def start_kafka_consumer():
    """Kafka 컨슈머 시작"""
    try:
        consumer = KafkaConsumer(
            'intelligent_translation_requests',  # 지능형 번역 요청
            'optimization_requests',             # 최적화 요청
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id='api-optimization',
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

        if topic == 'intelligent_translation_requests':
            await handle_intelligent_translation_request(data)
        elif topic == 'optimization_requests':
            await handle_optimization_request(data)

    except Exception as e:
        logger.error(f"❌ Kafka 메시지 처리 실패: {e}")

async def handle_intelligent_translation_request(data: Dict):
    """지능형 번역 요청 처리"""
    try:
        task_id = data.get('task_id')

        # 실제 구현에서는 버퍼 상태에서 텍스트 추출
        # 여기서는 시뮬레이션
        source_text = f"Task {task_id} text"

        # 캐시 확인
        cache_result = await intelligent_cache.get_translation(source_text)

        if cache_result:
            # 캐시 히트
            logger.info(f"💾 캐시 히트: {task_id}")

            # 결과 전송
            await send_translation_result(task_id, {
                'translated_text': cache_result.cache_entry.target_text,
                'cache_hit': True,
                'model_used': 'cache',
                'processing_time': 0.1,
                'cost': 0.0
            })
        else:
            # 캐시 미스 - 배치 처리 큐에 추가
            priority_map = {
                'critical': BatchPriority.CRITICAL,
                'high': BatchPriority.HIGH,
                'normal': BatchPriority.NORMAL,
                'low': BatchPriority.LOW
            }

            priority = priority_map.get(data.get('priority', 'normal'), BatchPriority.NORMAL)

            await dynamic_batcher.add_item(
                item_id=task_id,
                data={
                    'task_id': task_id,
                    'source_text': source_text,
                    'target_language': 'ko'
                },
                priority=priority
            )

    except Exception as e:
        logger.error(f"❌ 지능형 번역 요청 처리 실패: {e}")

async def handle_optimization_request(data: Dict):
    """최적화 요청 처리"""
    try:
        # 최적화 로직 실행
        logger.debug(f"🔧 최적화 요청 처리: {data}")

    except Exception as e:
        logger.error(f"❌ 최적화 요청 처리 실패: {e}")

async def send_translation_result(task_id: str, result: Dict):
    """번역 결과 전송"""
    try:
        result_data = {
            'task_id': task_id,
            'result': result,
            'timestamp': time.time()
        }

        kafka_producer.send(
            'optimized_translation_results',
            key=task_id,
            value=result_data
        )
        kafka_producer.flush()

        logger.debug(f"📤 번역 결과 전송: {task_id}")

    except Exception as e:
        logger.error(f"❌ 번역 결과 전송 실패: {task_id} - {e}")

@app.get("/health")
async def health_check():
    """헬스체크"""
    try:
        # Redis 연결 확인
        await redis_client.ping()

        return {
            "status": "healthy",
            "service": "api-optimization",
            "timestamp": time.time(),
            "components": {
                "redis": "connected",
                "kafka": "connected",
                "intelligent_cache": "active",
                "dynamic_batcher": "active",
                "cost_optimizer": "active"
            }
        }

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

@app.post("/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    """텍스트 번역"""
    try:
        start_time = time.time()

        # 1. 캐시 확인
        cache_result = await intelligent_cache.get_translation(
            request.source_text,
            request.context
        )

        if cache_result and cache_result.similarity_score >= 0.9:
            # 캐시 히트
            processing_time = time.time() - start_time

            return TranslationResponse(
                task_id=request.task_id,
                source_text=request.source_text,
                translated_text=cache_result.cache_entry.target_text,
                model_used="cache",
                processing_time=processing_time,
                cost=0.0,
                cache_hit=True,
                quality_score=cache_result.cache_entry.quality_score,
                confidence=cache_result.confidence
            )

        # 2. 최적 모델 선택
        task_requirements = {
            'estimated_tokens': len(request.source_text.split()) * 2,  # 간단한 추정
            'priority': request.priority,
            'max_cost': request.max_cost,
            'min_quality': request.min_quality,
            'max_latency': request.max_latency
        }

        optimal_model, confidence = await cost_optimizer.select_optimal_model(task_requirements)

        # 3. 배치 처리 큐에 추가
        priority_map = {
            'critical': BatchPriority.CRITICAL,
            'high': BatchPriority.HIGH,
            'normal': BatchPriority.NORMAL,
            'low': BatchPriority.LOW
        }

        priority = priority_map.get(request.priority, BatchPriority.NORMAL)

        await dynamic_batcher.add_item(
            item_id=request.task_id,
            data={
                'task_id': request.task_id,
                'source_text': request.source_text,
                'target_language': request.target_language,
                'model_type': optimal_model.value,
                'context': request.context
            },
            priority=priority
        )

        # 4. 모의 번역 결과 (실제로는 배치 처리 결과 대기)
        processing_time = time.time() - start_time
        estimated_cost = cost_optimizer._estimate_cost(optimal_model, task_requirements['estimated_tokens'])

        translated_text = f"[{optimal_model.value}로 번역됨] {request.source_text}"

        # 5. 캐시에 저장
        await intelligent_cache.store_translation(
            request.source_text,
            translated_text,
            quality_score=0.85,
            metadata={'model': optimal_model.value, 'context': request.context}
        )

        # 6. 사용 기록
        cost_optimizer.record_usage(
            optimal_model,
            task_requirements['estimated_tokens'],
            estimated_cost,
            processing_time,
            True,
            0.85
        )

        return TranslationResponse(
            task_id=request.task_id,
            source_text=request.source_text,
            translated_text=translated_text,
            model_used=optimal_model.value,
            processing_time=processing_time,
            cost=estimated_cost,
            cache_hit=False,
            quality_score=0.85,
            confidence=confidence
        )

    except Exception as e:
        logger.error(f"❌ 번역 실패: {request.task_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/batch/translate")
async def batch_translate(request: BatchTranslationRequest):
    """배치 번역"""
    try:
        priority_map = {
            'critical': BatchPriority.CRITICAL,
            'high': BatchPriority.HIGH,
            'normal': BatchPriority.NORMAL,
            'low': BatchPriority.LOW
        }

        priority = priority_map.get(request.priority, BatchPriority.NORMAL)

        # 각 요청을 배치 큐에 추가
        for tr_request in request.requests:
            await dynamic_batcher.add_item(
                item_id=tr_request.task_id,
                data={
                    'task_id': tr_request.task_id,
                    'source_text': tr_request.source_text,
                    'target_language': tr_request.target_language,
                    'context': tr_request.context
                },
                priority=priority
            )

        return {
            "batch_id": request.batch_id,
            "queued_items": len(request.requests),
            "priority": request.priority,
            "message": "배치 번역 요청이 큐에 추가되었습니다"
        }

    except Exception as e:
        logger.error(f"❌ 배치 번역 실패: {request.batch_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/model/select")
async def select_model(request: ModelSelectionRequest):
    """최적 모델 선택"""
    try:
        task_requirements = {
            'estimated_tokens': request.estimated_tokens,
            'priority': request.priority,
            'max_cost': request.max_cost,
            'min_quality': request.min_quality,
            'max_latency': request.max_latency
        }

        optimal_model, confidence = await cost_optimizer.select_optimal_model(task_requirements)
        estimated_cost = cost_optimizer._estimate_cost(optimal_model, request.estimated_tokens)

        return {
            "optimal_model": optimal_model.value,
            "confidence": confidence,
            "estimated_cost": estimated_cost,
            "model_config": {
                "cost_per_1k_tokens": cost_optimizer.model_configs[optimal_model].cost_per_1k_tokens,
                "average_latency": cost_optimizer.model_configs[optimal_model].average_latency,
                "quality_score": cost_optimizer.model_configs[optimal_model].quality_score
            }
        }

    except Exception as e:
        logger.error(f"❌ 모델 선택 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cache/stats")
async def get_cache_stats():
    """캐시 통계"""
    try:
        return await intelligent_cache.get_cache_stats()

    except Exception as e:
        logger.error(f"❌ 캐시 통계 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/batch/status/{batch_id}")
async def get_batch_status(batch_id: str):
    """배치 상태 조회"""
    try:
        status = await dynamic_batcher.get_batch_status(batch_id)

        if status:
            return status
        else:
            raise HTTPException(status_code=404, detail="배치를 찾을 수 없습니다")

    except Exception as e:
        logger.error(f"❌ 배치 상태 조회 실패: {batch_id} - {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/batch/metrics")
async def get_batch_metrics():
    """배치 메트릭"""
    try:
        return await dynamic_batcher.get_metrics()

    except Exception as e:
        logger.error(f"❌ 배치 메트릭 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cost/analysis")
async def get_cost_analysis(period: str = "today"):
    """비용 분석"""
    try:
        return await cost_optimizer.get_cost_analysis(period)

    except Exception as e:
        logger.error(f"❌ 비용 분석 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/cost/alerts")
async def get_budget_alerts():
    """예산 경고"""
    try:
        return await cost_optimizer.get_budget_alerts()

    except Exception as e:
        logger.error(f"❌ 예산 경고 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cache/clear")
async def clear_cache(pattern: Optional[str] = None):
    """캐시 정리"""
    try:
        removed_count = await intelligent_cache.clear_cache(pattern)

        return {
            "message": "캐시 정리 완료",
            "removed_items": removed_count,
            "pattern": pattern,
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(f"❌ 캐시 정리 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics")
async def get_metrics():
    """종합 메트릭"""
    try:
        cache_stats = await intelligent_cache.get_cache_stats()
        batch_metrics = await dynamic_batcher.get_metrics()
        cost_analysis = await cost_optimizer.get_cost_analysis("today")

        return {
            "cache_metrics": cache_stats,
            "batch_metrics": batch_metrics,
            "cost_metrics": cost_analysis,
            "timestamp": time.time()
        }

    except Exception as e:
        logger.error(f"❌ 메트릭 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)
