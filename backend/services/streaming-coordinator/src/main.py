"""
Streaming Coordinator Service
스트리밍 요청을 조율하고 전체 워크플로우를 관리하는 서비스
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from kafka import KafkaProducer, KafkaConsumer
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from pydantic import BaseModel

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus 메트릭
streaming_requests_total = Counter('streaming_requests_total', 'Total streaming requests', ['status'])
streaming_processing_time = Histogram('streaming_processing_seconds', 'Streaming processing time')
active_streams = Gauge('active_streams_total', 'Number of active streams')
coordinator_health = Gauge('coordinator_health', 'Coordinator health status')

class StreamingRequest(BaseModel):
    task_id: str
    mode: str = "streaming"  # streaming, hybrid, legacy
    priority: int = 1  # 1-5 (5가 highest)
    max_latency: int = 10  # seconds
    quality_threshold: float = 0.7

class StreamingCoordinator:
    def __init__(self):
        self.redis_client = None
        self.kafka_producer = None
        self.active_streams: Dict[str, Dict] = {}
        self.max_concurrent_streams = int(os.getenv('MAX_CONCURRENT_STREAMS', '10'))
        self.ready = False

    async def initialize(self):
        """서비스 초기화"""
        try:
            # 백오프 재시도
            attempt = 0
            last_err: Optional[Exception] = None
            while attempt < 6 and not self.ready:
                try:
                    # Redis 연결
                    redis_host = os.getenv('REDIS_HOST', 'localhost')
                    redis_port = int(os.getenv('REDIS_PORT', '6379'))
                    redis_db = int(os.getenv('REDIS_DB_STREAMING', '5'))

                    self.redis_client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        db=redis_db,
                        decode_responses=True
                    )
                    await self.redis_client.ping()
                    logger.info("✅ Redis connected successfully")

                    # Kafka 프로듀서 초기화
                    kafka_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
                    self.kafka_producer = KafkaProducer(
                        bootstrap_servers=kafka_servers.split(','),
                        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                        key_serializer=lambda k: k.encode('utf-8') if k else None
                    )
                    logger.info("✅ Kafka producer initialized")

                    self.ready = True
                    coordinator_health.set(1)
                    break
                except Exception as e:
                    last_err = e
                    delay = min(30, 2 ** attempt)
                    logger.warning(f"⏳ Init retry in {delay}s (attempt {attempt+1}/6): {e}")
                    await asyncio.sleep(delay)

            if not self.ready and last_err:
                logger.error(f"❌ Initialization failed after retries: {last_err}")
                coordinator_health.set(0)
                return

            # 백그라운드 태스크 시작
            asyncio.create_task(self.stream_monitor_loop())

        except Exception as e:
            logger.error(f"❌ Initialization fatal error: {e}")
            coordinator_health.set(0)

    async def coordinate_streaming_request(self, request: StreamingRequest) -> Dict[str, Any]:
        """스트리밍 요청 조율"""
        start_time = time.time()

        try:
            # 동시 스트림 수 체크
            if len(self.active_streams) >= self.max_concurrent_streams:
                # 우선순위가 낮은 스트림 정리
                await self._cleanup_low_priority_streams(request.priority)

                if len(self.active_streams) >= self.max_concurrent_streams:
                    streaming_requests_total.labels(status='rejected').inc()
                    raise HTTPException(
                        status_code=429,
                        detail="Too many concurrent streams"
                    )

            # 스트림 상태 등록
            stream_info = {
                "task_id": request.task_id,
                "mode": request.mode,
                "priority": request.priority,
                "max_latency": request.max_latency,
                "quality_threshold": request.quality_threshold,
                "start_time": time.time(),
                "status": "initializing",
                "last_update": time.time()
            }

            self.active_streams[request.task_id] = stream_info
            active_streams.set(len(self.active_streams))

            # Redis에 스트림 정보 저장
            await self.redis_client.setex(
                f"stream:{request.task_id}",
                3600,  # 1시간 TTL
                json.dumps(stream_info)
            )

            # 스트리밍 워크플로우 시작
            await self._initiate_streaming_workflow(request)

            # 성공 메트릭 기록
            processing_time = time.time() - start_time
            streaming_processing_time.observe(processing_time)
            streaming_requests_total.labels(status='accepted').inc()

            return {
                "status": "accepted",
                "task_id": request.task_id,
                "mode": request.mode,
                "estimated_latency": self._calculate_estimated_latency(request),
                "stream_url": f"/stream/{request.task_id}"
            }

        except Exception as e:
            logger.error(f"❌ Streaming coordination failed for {request.task_id}: {e}")
            streaming_requests_total.labels(status='failed').inc()

            # 실패한 스트림 정리
            if request.task_id in self.active_streams:
                del self.active_streams[request.task_id]
                active_streams.set(len(self.active_streams))

            raise HTTPException(status_code=500, detail=str(e))

    async def _initiate_streaming_workflow(self, request: StreamingRequest):
        """스트리밍 워크플로우 시작"""
        try:
            # Kafka 메시지로 스트리밍 시작 신호 전송
            workflow_message = {
                "task_id": request.task_id,
                "mode": request.mode,
                "priority": request.priority,
                "max_latency": request.max_latency,
                "quality_threshold": request.quality_threshold,
                "timestamp": time.time(),
                "action": "start_streaming"
            }

            # 스트리밍 제어 토픽으로 전송
            self.kafka_producer.send(
                'streaming_control',
                key=request.task_id,
                value=workflow_message
            )

            # 스트림 상태 업데이트
            self.active_streams[request.task_id]["status"] = "active"
            self.active_streams[request.task_id]["last_update"] = time.time()

            logger.info(f"✅ Streaming workflow initiated for {request.task_id}")

        except Exception as e:
            logger.error(f"❌ Failed to initiate workflow for {request.task_id}: {e}")
            raise

    async def _cleanup_low_priority_streams(self, current_priority: int):
        """우선순위가 낮은 스트림 정리"""
        try:
            streams_to_remove = []

            for task_id, stream_info in self.active_streams.items():
                # 현재 요청보다 우선순위가 낮거나 오래된 스트림 찾기
                if (stream_info["priority"] < current_priority or
                    time.time() - stream_info["last_update"] > 300):  # 5분 이상 비활성
                    streams_to_remove.append(task_id)

            # 찾은 스트림들 정리
            for task_id in streams_to_remove[:2]:  # 최대 2개까지만 정리
                await self._terminate_stream(task_id, reason="priority_cleanup")
                logger.info(f"🧹 Terminated low priority stream: {task_id}")

        except Exception as e:
            logger.error(f"❌ Stream cleanup failed: {e}")

    async def _terminate_stream(self, task_id: str, reason: str = "manual"):
        """스트림 종료"""
        try:
            if task_id in self.active_streams:
                # Kafka로 종료 신호 전송
                termination_message = {
                    "task_id": task_id,
                    "action": "terminate_stream",
                    "reason": reason,
                    "timestamp": time.time()
                }

                self.kafka_producer.send(
                    'streaming_control',
                    key=task_id,
                    value=termination_message
                )

                # 로컬 상태 정리
                del self.active_streams[task_id]
                active_streams.set(len(self.active_streams))

                # Redis 정리
                await self.redis_client.delete(f"stream:{task_id}")

                logger.info(f"🛑 Stream terminated: {task_id} (reason: {reason})")

        except Exception as e:
            logger.error(f"❌ Stream termination failed for {task_id}: {e}")

    async def stream_monitor_loop(self):
        """스트림 모니터링 루프"""
        while True:
            try:
                current_time = time.time()
                stale_streams = []

                for task_id, stream_info in self.active_streams.items():
                    # 10분 이상 업데이트 없는 스트림은 stale로 간주
                    if current_time - stream_info["last_update"] > 600:
                        stale_streams.append(task_id)

                # Stale 스트림 정리
                for task_id in stale_streams:
                    await self._terminate_stream(task_id, reason="stale")

                # 30초마다 체크
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"❌ Stream monitor error: {e}")
                await asyncio.sleep(60)  # 에러 시 더 긴 간격으로 재시도

    def _calculate_estimated_latency(self, request: StreamingRequest) -> float:
        """예상 지연시간 계산"""
        base_latency = 5.0  # 기본 5초

        # 모드별 지연시간 조정
        mode_multiplier = {
            "streaming": 1.0,
            "hybrid": 1.5,
            "legacy": 3.0
        }.get(request.mode, 1.0)

        # 현재 부하에 따른 조정
        load_factor = len(self.active_streams) / self.max_concurrent_streams
        load_multiplier = 1.0 + (load_factor * 0.5)

        return base_latency * mode_multiplier * load_multiplier

    async def get_stream_status(self, task_id: str) -> Dict[str, Any]:
        """스트림 상태 조회"""
        try:
            # 로컬 캐시에서 먼저 확인
            if task_id in self.active_streams:
                return self.active_streams[task_id]

            # Redis에서 조회
            stream_data = await self.redis_client.get(f"stream:{task_id}")
            if stream_data:
                return json.loads(stream_data)

            return {"status": "not_found"}

        except Exception as e:
            logger.error(f"❌ Failed to get stream status for {task_id}: {e}")
            return {"status": "error", "error": str(e)}

# FastAPI 앱 초기화
app = FastAPI(title="Streaming Coordinator Service", version="1.0.0")
coordinator = StreamingCoordinator()

@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 초기화 (비차단)"""
    asyncio.create_task(coordinator.initialize())

    # Prometheus 메트릭 서버 시작
    start_http_server(8000)
    logger.info("📊 Prometheus metrics server started on port 8000")

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    try:
        status = "healthy" if coordinator.ready else "starting"
        # Redis 연결 확인 시도 (준비완료 시에만)
        if coordinator.ready and coordinator.redis_client:
            await coordinator.redis_client.ping()

        return {
            "status": status,
            "active_streams": len(coordinator.active_streams),
            "max_streams": coordinator.max_concurrent_streams,
            "timestamp": time.time()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.post("/coordinate")
async def coordinate_streaming(request: StreamingRequest):
    """스트리밍 요청 조율"""
    return await coordinator.coordinate_streaming_request(request)

@app.get("/stream/{task_id}/status")
async def get_stream_status(task_id: str):
    """스트림 상태 조회"""
    return await coordinator.get_stream_status(task_id)

@app.delete("/stream/{task_id}")
async def terminate_stream(task_id: str):
    """스트림 종료"""
    await coordinator._terminate_stream(task_id, reason="manual")
    return {"status": "terminated", "task_id": task_id}

@app.get("/streams")
async def list_active_streams():
    """활성 스트림 목록"""
    return {
        "active_streams": list(coordinator.active_streams.keys()),
        "count": len(coordinator.active_streams),
        "max_capacity": coordinator.max_concurrent_streams
    }

@app.get("/metrics")
async def get_metrics():
    """메트릭 조회"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
