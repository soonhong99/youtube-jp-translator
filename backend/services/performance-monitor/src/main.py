"""
Performance Monitor Service
시스템 성능 모니터링 및 메트릭 수집
"""

import asyncio
import json
import logging
import os
import psutil
import time
from typing import Dict, List, Optional, Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from pydantic import BaseModel

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus 메트릭
stt_processing_time = Histogram('stt_processing_seconds', 'STT processing time', ['chunk_size'])
translation_latency = Histogram('translation_latency_seconds', 'Translation latency', ['model', 'batch_size'])
api_requests_total = Counter('api_requests_total', 'Total API requests', ['model', 'status'])
active_tasks = Gauge('active_tasks_total', 'Number of active tasks')
system_load = Gauge('system_load_percent', 'System load percentage')
memory_usage = Gauge('memory_usage_percent', 'Memory usage percentage')
cpu_usage = Gauge('cpu_usage_percent', 'CPU usage percentage')
kafka_message_rate = Gauge('kafka_message_rate', 'Kafka message rate', ['topic'])
redis_connections = Gauge('redis_connections_total', 'Redis connections')

class MetricsData(BaseModel):
    type: str
    task_id: Optional[str] = None
    timestamp: float
    data: Dict[str, Any]

class PerformanceMetricsCollector:
    def __init__(self):
        self.redis_client = None
        self.kafka_consumer = None
        self.kafka_producer = None
        self.collection_interval = int(os.getenv('METRICS_COLLECTION_INTERVAL', '10'))
        self.running = False

    async def initialize(self):
        """메트릭 수집기 초기화"""
        try:
            # Redis 연결
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', '6379'))
            redis_db = int(os.getenv('REDIS_DB_METRICS', '7'))

            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True
            )

            await self.redis_client.ping()
            logger.info("✅ Redis connected successfully")

            # Kafka 연결
            kafka_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

            # Kafka 컨슈머 (메트릭 수집용)
            self.kafka_consumer = KafkaConsumer(
                'performance_metrics',
                bootstrap_servers=kafka_servers.split(','),
                value_deserializer=lambda v: json.loads(v.decode('utf-8')),
                auto_offset_reset='latest',
                group_id='performance-monitor-group'
            )

            # Kafka 프로듀서 (알림 발송용)
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=kafka_servers.split(','),
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )

            logger.info("✅ Kafka connected successfully")

        except Exception as e:
            logger.error(f"❌ Metrics collector initialization failed: {e}")
            raise

    async def start_monitoring(self):
        """모니터링 시작"""
        self.running = True
        logger.info("🚀 Performance monitoring started")

        # 여러 모니터링 태스크 병렬 실행
        await asyncio.gather(
            self.collect_kafka_metrics(),
            self.collect_system_metrics(),
            self.collect_redis_metrics(),
            self.monitor_application_metrics()
        )

    async def stop_monitoring(self):
        """모니터링 중지"""
        self.running = False
        logger.info("🛑 Performance monitoring stopped")

    async def collect_kafka_metrics(self):
        """Kafka에서 성능 메트릭 수집"""
        logger.info("📊 Starting Kafka metrics collection")

        try:
            while self.running:
                # Kafka 메시지 처리 (논블로킹)
                await asyncio.to_thread(self._process_kafka_messages)
                await asyncio.sleep(1)  # 1초마다 체크

        except Exception as e:
            logger.error(f"❌ Kafka metrics collection error: {e}")

    def _process_kafka_messages(self):
        """Kafka 메시지 처리 (동기 함수)"""
        try:
            messages = self.kafka_consumer.poll(timeout_ms=100)

            for topic_partition, message_list in messages.items():
                for message in message_list:
                    self._process_performance_metric(message.value)

        except Exception as e:
            logger.error(f"❌ Kafka message processing error: {e}")

    def _process_performance_metric(self, metric_data: Dict[str, Any]):
        """성능 메트릭 처리"""
        try:
            metric_type = metric_data.get('type')

            if metric_type == 'stt_processing':
                chunk_size = metric_data.get('chunk_size', 'unknown')
                processing_time = metric_data.get('processing_time', 0)
                stt_processing_time.labels(chunk_size=chunk_size).observe(processing_time)

            elif metric_type == 'translation':
                model = metric_data.get('model', 'unknown')
                batch_size = metric_data.get('batch_size', 'unknown')
                latency = metric_data.get('latency', 0)
                status = metric_data.get('status', 'unknown')

                translation_latency.labels(model=model, batch_size=str(batch_size)).observe(latency)
                api_requests_total.labels(model=model, status=status).inc()

            elif metric_type == 'task_status':
                task_count = metric_data.get('active_count', 0)
                active_tasks.set(task_count)

        except Exception as e:
            logger.error(f"❌ Metric processing error: {e}")

    async def collect_system_metrics(self):
        """시스템 메트릭 수집"""
        logger.info("💻 Starting system metrics collection")

        while self.running:
            try:
                # CPU 사용률
                cpu_percent = psutil.cpu_percent(interval=1)
                cpu_usage.set(cpu_percent)

                # 메모리 사용률
                memory = psutil.virtual_memory()
                memory_usage.set(memory.percent)

                # 시스템 로드 (Linux/Mac)
                try:
                    load_avg = psutil.getloadavg()[0]  # 1분 평균
                    load_percent = (load_avg / psutil.cpu_count()) * 100
                    system_load.set(min(load_percent, 100))
                except:
                    # Windows에서는 loadavg가 없으므로 CPU 사용률로 대체
                    system_load.set(cpu_percent)

                # 디스크 사용률
                disk = psutil.disk_usage('/')
                disk_usage_percent = (disk.used / disk.total) * 100

                # Redis에 시스템 메트릭 저장
                system_metrics = {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'system_load': load_percent if 'load_avg' in locals() else cpu_percent,
                    'disk_usage': disk_usage_percent,
                    'timestamp': time.time()
                }

                await self.redis_client.setex(
                    'system_metrics',
                    60,  # 1분 TTL
                    json.dumps(system_metrics)
                )

                logger.debug(f"📊 System metrics: CPU={cpu_percent:.1f}%, Memory={memory.percent:.1f}%")

            except Exception as e:
                logger.error(f"❌ System metrics collection error: {e}")

            await asyncio.sleep(self.collection_interval)

    async def collect_redis_metrics(self):
        """Redis 메트릭 수집"""
        logger.info("🔗 Starting Redis metrics collection")

        while self.running:
            try:
                # Redis 정보 수집
                info = await self.redis_client.info()

                # 연결 수
                connected_clients = info.get('connected_clients', 0)
                redis_connections.set(connected_clients)

                # 메모리 사용량
                used_memory = info.get('used_memory', 0)
                max_memory = info.get('maxmemory', 0)

                if max_memory > 0:
                    redis_memory_percent = (used_memory / max_memory) * 100
                else:
                    redis_memory_percent = 0

                # Redis 메트릭 저장
                redis_metrics = {
                    'connected_clients': connected_clients,
                    'used_memory_bytes': used_memory,
                    'memory_percent': redis_memory_percent,
                    'total_commands_processed': info.get('total_commands_processed', 0),
                    'timestamp': time.time()
                }

                await self.redis_client.setex(
                    'redis_metrics',
                    60,
                    json.dumps(redis_metrics)
                )

                logger.debug(f"🔗 Redis metrics: Connections={connected_clients}, Memory={redis_memory_percent:.1f}%")

            except Exception as e:
                logger.error(f"❌ Redis metrics collection error: {e}")

            await asyncio.sleep(self.collection_interval * 2)  # Redis는 덜 자주 체크

    async def monitor_application_metrics(self):
        """애플리케이션별 메트릭 모니터링"""
        logger.info("🎯 Starting application metrics monitoring")

        while self.running:
            try:
                # 활성 작업 수 계산
                active_count = await self.get_active_tasks_count()
                active_tasks.set(active_count)

                # Kafka 토픽별 메시지 처리율 계산
                await self.calculate_kafka_message_rates()

                # 임계값 체크 및 알림
                await self.check_performance_thresholds()

            except Exception as e:
                logger.error(f"❌ Application metrics monitoring error: {e}")

            await asyncio.sleep(self.collection_interval)

    async def get_active_tasks_count(self) -> int:
        """활성 작업 수 계산"""
        try:
            # Redis에서 활성 작업 키 패턴 조회
            task_keys = await self.redis_client.keys('task:*:status')
            active_count = 0

            for key in task_keys:
                status = await self.redis_client.get(key)
                if status in ['processing', 'translating', 'streaming']:
                    active_count += 1

            return active_count

        except Exception as e:
            logger.error(f"❌ Failed to get active tasks count: {e}")
            return 0

    async def calculate_kafka_message_rates(self):
        """Kafka 토픽별 메시지 처리율 계산"""
        try:
            topics = ['stt_requests', 'stt_results', 'translation_queue', 'realtime_results']

            for topic in topics:
                # 최근 메시지 수 조회 (이전 구현에서 저장된 값 기반)
                rate_key = f'kafka_rate:{topic}'
                rate = await self.redis_client.get(rate_key)

                if rate:
                    kafka_message_rate.labels(topic=topic).set(float(rate))

        except Exception as e:
            logger.error(f"❌ Kafka message rate calculation error: {e}")

    async def check_performance_thresholds(self):
        """성능 임계값 체크 및 알림"""
        try:
            # 시스템 메트릭 가져오기
            system_metrics_data = await self.redis_client.get('system_metrics')
            if not system_metrics_data:
                return

            metrics = json.loads(system_metrics_data)

            alerts = []

            # CPU 사용률 체크
            if metrics['cpu_percent'] > 80:
                alerts.append({
                    'type': 'high_cpu',
                    'value': metrics['cpu_percent'],
                    'threshold': 80,
                    'severity': 'warning'
                })

            # 메모리 사용률 체크
            if metrics['memory_percent'] > 85:
                alerts.append({
                    'type': 'high_memory',
                    'value': metrics['memory_percent'],
                    'threshold': 85,
                    'severity': 'critical'
                })

            # 시스템 로드 체크
            if metrics['system_load'] > 90:
                alerts.append({
                    'type': 'high_load',
                    'value': metrics['system_load'],
                    'threshold': 90,
                    'severity': 'critical'
                })

            # 알림 발송
            if alerts:
                await self.send_performance_alerts(alerts)

        except Exception as e:
            logger.error(f"❌ Performance threshold check error: {e}")

    async def send_performance_alerts(self, alerts: List[Dict]):
        """성능 알림 발송"""
        try:
            alert_message = {
                'type': 'performance_alert',
                'alerts': alerts,
                'timestamp': time.time(),
                'source': 'performance-monitor'
            }

            # Kafka로 알림 발송
            self.kafka_producer.send(
                'system_alerts',
                value=alert_message
            )

            # Redis에도 최근 알림 저장
            await self.redis_client.setex(
                'latest_alerts',
                300,  # 5분 TTL
                json.dumps(alert_message)
            )

            logger.warning(f"🚨 Performance alerts sent: {len(alerts)} alerts")

        except Exception as e:
            logger.error(f"❌ Alert sending error: {e}")

    async def get_performance_summary(self) -> Dict[str, Any]:
        """성능 요약 조회"""
        try:
            # 시스템 메트릭
            system_data = await self.redis_client.get('system_metrics')
            system_metrics = json.loads(system_data) if system_data else {}

            # Redis 메트릭
            redis_data = await self.redis_client.get('redis_metrics')
            redis_metrics = json.loads(redis_data) if redis_data else {}

            # 활성 작업 수
            active_count = await self.get_active_tasks_count()

            return {
                'system': system_metrics,
                'redis': redis_metrics,
                'active_tasks': active_count,
                'collection_interval': self.collection_interval,
                'monitoring_status': 'running' if self.running else 'stopped',
                'timestamp': time.time()
            }

        except Exception as e:
            logger.error(f"❌ Performance summary error: {e}")
            return {'error': str(e)}

# FastAPI 앱 초기화
app = FastAPI(title="Performance Monitor Service", version="1.0.0")
metrics_collector = PerformanceMetricsCollector()

@app.on_event("startup")
async def startup_event():
    """서비스 시작 시 초기화"""
    await metrics_collector.initialize()

    # Prometheus 메트릭 서버 시작
    start_http_server(8000)
    logger.info("📊 Prometheus metrics server started on port 8000")

    # 백그라운드에서 모니터링 시작
    asyncio.create_task(metrics_collector.start_monitoring())

@app.on_event("shutdown")
async def shutdown_event():
    """서비스 종료 시 정리"""
    await metrics_collector.stop_monitoring()

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    try:
        await metrics_collector.redis_client.ping()

        return {
            "status": "healthy",
            "monitoring_status": "running" if metrics_collector.running else "stopped",
            "collection_interval": metrics_collector.collection_interval,
            "timestamp": time.time()
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/performance/summary")
async def get_performance_summary():
    """성능 요약 조회"""
    return await metrics_collector.get_performance_summary()

@app.get("/performance/alerts")
async def get_recent_alerts():
    """최근 알림 조회"""
    try:
        alerts_data = await metrics_collector.redis_client.get('latest_alerts')
        if alerts_data:
            return json.loads(alerts_data)
        return {"alerts": [], "message": "No recent alerts"}

    except Exception as e:
        return {"error": str(e)}

@app.post("/monitoring/start")
async def start_monitoring():
    """모니터링 시작"""
    if not metrics_collector.running:
        asyncio.create_task(metrics_collector.start_monitoring())
        return {"status": "started"}
    return {"status": "already_running"}

@app.post("/monitoring/stop")
async def stop_monitoring():
    """모니터링 중지"""
    await metrics_collector.stop_monitoring()
    return {"status": "stopped"}

@app.get("/metrics")
async def get_metrics():
    """Prometheus 메트릭 조회"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )