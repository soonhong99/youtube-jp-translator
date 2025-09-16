"""
Enhanced Worker Pool Manager
실시간 스트리밍을 위한 고도화된 워커 풀 관리 시스템
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import redis.asyncio as redis
from kafka import KafkaProducer, KafkaConsumer
from prometheus_client import Counter, Histogram, Gauge
import json

logger = logging.getLogger(__name__)

@dataclass
class TranslationTask:
    """번역 작업 정의"""
    task_id: str
    chunk_id: str
    text: str
    priority: int
    max_latency: float
    context: Optional[Dict] = None
    retry_count: int = 0
    created_at: float = 0.0
    deadline: float = 0.0

@dataclass
class WorkerMetrics:
    """워커 성능 메트릭"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_response_time: float = 0.0
    current_load: float = 0.0
    success_rate: float = 1.0
    last_error: Optional[str] = None
    last_activity: float = 0.0

class TaskPriority(Enum):
    """작업 우선순위"""
    CRITICAL = 1  # 8초 이내 완료 필요
    HIGH = 2      # 15초 이내 완료
    NORMAL = 3    # 30초 이내 완료
    LOW = 4       # 60초 이내 완료

class WorkerPoolManager:
    """고도화된 워커 풀 관리자"""

    def __init__(self, config):
        self.config = config
        self.workers = {}
        self.task_queues = {
            TaskPriority.CRITICAL: asyncio.PriorityQueue(),
            TaskPriority.HIGH: asyncio.PriorityQueue(),
            TaskPriority.NORMAL: asyncio.PriorityQueue(),
            TaskPriority.LOW: asyncio.PriorityQueue()
        }

        # Redis & Kafka
        self.redis_client = None
        self.kafka_producer = None
        self.kafka_consumer = None

        # 메트릭
        self.worker_metrics: Dict[str, WorkerMetrics] = {}
        self.pool_metrics = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "avg_processing_time": 0.0,
            "current_queue_size": 0,
            "peak_queue_size": 0
        }

        # 워커 관리
        self.worker_tasks = {}
        self.is_running = False

        # 동적 스케일링
        self.scaling_config = {
            "min_workers": 2,
            "max_workers": 8,
            "scale_up_threshold": 0.7,  # 70% 부하 시 스케일 업
            "scale_down_threshold": 0.3,  # 30% 부하 시 스케일 다운
            "scale_up_cooldown": 60,    # 스케일 업 후 60초 대기
            "scale_down_cooldown": 300  # 스케일 다운 후 300초 대기
        }

        self.last_scale_time = 0

    async def initialize(self):
        """워커 풀 매니저 초기화"""
        try:
            logger.info("🚀 워커 풀 매니저 초기화 시작...")

            # Redis 연결
            self.redis_client = redis.Redis(
                host=self.config.REDIS_HOST,
                port=self.config.REDIS_PORT,
                db=self.config.REDIS_DB_WORKERS,
                decode_responses=True
            )
            await self.redis_client.ping()

            # Kafka 프로듀서
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=self.config.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda x: json.dumps(x, ensure_ascii=False).encode('utf-8'),
                key_serializer=lambda x: x.encode('utf-8') if x else None
            )

            # 초기 워커 생성
            await self._initialize_workers()

            # 백그라운드 작업 시작
            self.is_running = True
            await self._start_background_tasks()

            logger.info(f"✅ 워커 풀 매니저 초기화 완료: {len(self.workers)}개 워커")

        except Exception as e:
            logger.error(f"❌ 워커 풀 매니저 초기화 실패: {e}")
            raise

    async def _initialize_workers(self):
        """초기 워커 생성"""
        from main import GeminiWorker, ClaudeWorker
        import os

        # Gemini 워커들
        if os.getenv('GEMINI_API_KEY'):
            self.workers["gemini_flash_1"] = GeminiWorker("gemini-1.5-flash-latest", 60)
            self.workers["gemini_flash_2"] = GeminiWorker("gemini-1.5-flash-latest", 60)
            self.workers["gemini_pro"] = GeminiWorker("gemini-2.0-flash-exp", 30)

            # 워커 메트릭 초기화
            for worker_name in ["gemini_flash_1", "gemini_flash_2", "gemini_pro"]:
                self.worker_metrics[worker_name] = WorkerMetrics()

        # Claude 워커
        if os.getenv('CLAUDE_API_KEY'):
            self.workers["claude_haiku"] = ClaudeWorker("claude-3-haiku-20240307", 40)
            self.worker_metrics["claude_haiku"] = WorkerMetrics()

    async def _start_background_tasks(self):
        """백그라운드 작업 시작"""
        # 작업 처리기들
        for priority in TaskPriority:
            task = asyncio.create_task(self._task_processor(priority))
            self.worker_tasks[f"processor_{priority.name}"] = task

        # 메트릭 수집기
        self.worker_tasks["metrics_collector"] = asyncio.create_task(
            self._metrics_collector()
        )

        # 동적 스케일링
        self.worker_tasks["auto_scaler"] = asyncio.create_task(
            self._auto_scaler()
        )

        # 헬스 체커
        self.worker_tasks["health_checker"] = asyncio.create_task(
            self._health_checker()
        )

    async def submit_translation_task(
        self,
        task_id: str,
        chunk_id: str,
        text: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        max_latency: float = 30.0,
        context: Optional[Dict] = None
    ) -> bool:
        """번역 작업 제출"""
        try:
            task = TranslationTask(
                task_id=task_id,
                chunk_id=chunk_id,
                text=text,
                priority=priority.value,
                max_latency=max_latency,
                context=context,
                created_at=time.time(),
                deadline=time.time() + max_latency
            )

            # 우선순위 큐에 추가
            await self.task_queues[priority].put((priority.value, time.time(), task))

            # 메트릭 업데이트
            self.pool_metrics["total_tasks"] += 1
            current_queue_size = sum(q.qsize() for q in self.task_queues.values())
            self.pool_metrics["current_queue_size"] = current_queue_size
            self.pool_metrics["peak_queue_size"] = max(
                self.pool_metrics["peak_queue_size"],
                current_queue_size
            )

            logger.debug(f"📥 번역 작업 제출: {task_id}/{chunk_id} (우선순위: {priority.name})")
            return True

        except Exception as e:
            logger.error(f"❌ 작업 제출 실패: {e}")
            return False

    async def _task_processor(self, priority: TaskPriority):
        """우선순위별 작업 처리기"""
        logger.info(f"🔄 작업 처리기 시작: {priority.name}")

        while self.is_running:
            try:
                # 작업 대기 (타임아웃 1초)
                try:
                    _, timestamp, task = await asyncio.wait_for(
                        self.task_queues[priority].get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # 데드라인 체크
                if time.time() > task.deadline:
                    logger.warning(f"⏰ 작업 데드라인 초과: {task.task_id}/{task.chunk_id}")
                    await self._handle_task_timeout(task)
                    continue

                # 최적 워커 선택
                selected_worker = await self._select_optimal_worker(task)
                if not selected_worker:
                    # 다시 큐에 넣기 (재시도)
                    task.retry_count += 1
                    if task.retry_count < 3:
                        await self.task_queues[priority].put((priority.value, time.time(), task))
                    else:
                        await self._handle_task_failure(task, "No available workers")
                    continue

                # 번역 실행
                asyncio.create_task(self._execute_translation(selected_worker, task))

            except Exception as e:
                logger.error(f"❌ 작업 처리기 오류 ({priority.name}): {e}")
                await asyncio.sleep(1)

    async def _select_optimal_worker(self, task: TranslationTask) -> Optional[str]:
        """최적 워커 선택"""
        best_worker = None
        best_score = -1

        for worker_name, worker in self.workers.items():
            if not hasattr(worker, 'client'):
                continue

            metrics = self.worker_metrics[worker_name]

            # 현재 부하율
            current_load = await worker.get_current_load()

            # 부하율이 90% 이상이면 제외
            if current_load > 0.9:
                continue

            # 성능 점수 계산
            performance_score = self._calculate_worker_score(
                worker, metrics, task, current_load
            )

            if performance_score > best_score:
                best_score = performance_score
                best_worker = worker_name

        return best_worker

    def _calculate_worker_score(
        self,
        worker,
        metrics: WorkerMetrics,
        task: TranslationTask,
        current_load: float
    ) -> float:
        """워커 성능 점수 계산"""
        # 기본 점수
        base_score = 1.0

        # 성공률 가중치 (30%)
        success_weight = metrics.success_rate * 0.3

        # 응답 시간 가중치 (25%)
        if metrics.avg_response_time > 0:
            # 빠를수록 높은 점수
            time_weight = max(0, (10 - metrics.avg_response_time) / 10) * 0.25
        else:
            time_weight = 0.25

        # 부하 가중치 (25%)
        load_weight = (1 - current_load) * 0.25

        # 모델별 특성 가중치 (20%)
        model_weight = 0.0
        if task.priority == TaskPriority.CRITICAL.value:
            # 긴급한 작업은 빠른 모델 선호
            if "flash" in worker.model_name:
                model_weight = 0.2
            elif "haiku" in worker.model_name:
                model_weight = 0.15
        else:
            # 일반 작업은 품질 모델 선호
            if "pro" in worker.model_name:
                model_weight = 0.2
            elif "flash" in worker.model_name:
                model_weight = 0.15

        total_score = success_weight + time_weight + load_weight + model_weight
        return total_score

    async def _execute_translation(self, worker_name: str, task: TranslationTask):
        """번역 실행"""
        start_time = time.time()
        worker = self.workers[worker_name]
        metrics = self.worker_metrics[worker_name]

        try:
            logger.debug(f"🔄 번역 실행: {task.task_id}/{task.chunk_id} -> {worker_name}")

            # 번역 수행
            translations = await asyncio.wait_for(
                worker.translate_batch([task.text], task.context),
                timeout=task.max_latency
            )

            translation = translations[0] if translations else "[번역 실패]"
            processing_time = time.time() - start_time

            # 성공 처리
            await self._handle_task_success(task, translation, worker_name, processing_time)

            # 메트릭 업데이트
            metrics.successful_requests += 1
            metrics.total_requests += 1
            metrics.avg_response_time = (
                (metrics.avg_response_time * (metrics.total_requests - 1) + processing_time) /
                metrics.total_requests
            )
            metrics.success_rate = metrics.successful_requests / metrics.total_requests
            metrics.last_activity = time.time()

        except asyncio.TimeoutError:
            logger.warning(f"⏰ 번역 타임아웃: {task.task_id}/{task.chunk_id}")
            await self._handle_task_timeout(task)

            # 메트릭 업데이트
            metrics.failed_requests += 1
            metrics.total_requests += 1
            metrics.success_rate = metrics.successful_requests / metrics.total_requests

        except Exception as e:
            logger.error(f"❌ 번역 실행 실패: {task.task_id}/{task.chunk_id} - {e}")
            await self._handle_task_failure(task, str(e))

            # 메트릭 업데이트
            metrics.failed_requests += 1
            metrics.total_requests += 1
            metrics.success_rate = metrics.successful_requests / metrics.total_requests
            metrics.last_error = str(e)

    async def _handle_task_success(
        self,
        task: TranslationTask,
        translation: str,
        worker_name: str,
        processing_time: float
    ):
        """작업 성공 처리"""
        result = {
            "type": "translation_result",
            "task_id": task.task_id,
            "chunk_id": task.chunk_id,
            "original_text": task.text,
            "translated_text": translation,
            "worker_used": worker_name,
            "processing_time": processing_time,
            "status": "success",
            "timestamp": time.time()
        }

        # Kafka로 결과 전송
        self.kafka_producer.send(
            self.config.KAFKA_TOPIC_TRANSLATION_RESULTS,
            key=task.task_id,
            value=result
        )

        # Redis에 결과 캐싱
        cache_key = f"translation_result:{task.task_id}:{task.chunk_id}"
        await self.redis_client.setex(
            cache_key,
            self.config.REDIS_TTL_TRANSLATION_RESULTS,
            json.dumps(result, ensure_ascii=False)
        )

        # 메트릭 업데이트
        self.pool_metrics["completed_tasks"] += 1
        total_completed = self.pool_metrics["completed_tasks"]
        current_avg = self.pool_metrics["avg_processing_time"]
        self.pool_metrics["avg_processing_time"] = (
            (current_avg * (total_completed - 1) + processing_time) / total_completed
        )

        logger.debug(f"✅ 번역 완료: {task.task_id}/{task.chunk_id} ({processing_time:.2f}s)")

    async def _handle_task_timeout(self, task: TranslationTask):
        """작업 타임아웃 처리"""
        await self._send_error_result(task, "timeout", "번역 시간 초과")

    async def _handle_task_failure(self, task: TranslationTask, error_message: str):
        """작업 실패 처리"""
        await self._send_error_result(task, "failed", error_message)

    async def _send_error_result(self, task: TranslationTask, status: str, message: str):
        """에러 결과 전송"""
        result = {
            "type": "translation_error",
            "task_id": task.task_id,
            "chunk_id": task.chunk_id,
            "original_text": task.text,
            "status": status,
            "error_message": message,
            "timestamp": time.time()
        }

        # Kafka로 에러 전송
        self.kafka_producer.send(
            self.config.KAFKA_TOPIC_TRANSLATION_RESULTS,
            key=task.task_id,
            value=result
        )

        # 메트릭 업데이트
        self.pool_metrics["failed_tasks"] += 1

    async def _metrics_collector(self):
        """메트릭 수집 및 전송"""
        while self.is_running:
            try:
                # 워커별 부하 업데이트
                for worker_name, worker in self.workers.items():
                    if hasattr(worker, 'client'):
                        current_load = await worker.get_current_load()
                        self.worker_metrics[worker_name].current_load = current_load

                # 큐 사이즈 업데이트
                current_queue_size = sum(q.qsize() for q in self.task_queues.values())
                self.pool_metrics["current_queue_size"] = current_queue_size

                # Redis에 메트릭 저장
                metrics_data = {
                    "pool_metrics": self.pool_metrics,
                    "worker_metrics": {
                        name: asdict(metrics)
                        for name, metrics in self.worker_metrics.items()
                    },
                    "timestamp": time.time()
                }

                await self.redis_client.setex(
                    "worker_pool_metrics",
                    300,  # 5분 TTL
                    json.dumps(metrics_data, ensure_ascii=False)
                )

                await asyncio.sleep(10)  # 10초마다 수집

            except Exception as e:
                logger.error(f"❌ 메트릭 수집 오류: {e}")
                await asyncio.sleep(10)

    async def _auto_scaler(self):
        """동적 스케일링"""
        while self.is_running:
            try:
                await asyncio.sleep(30)  # 30초마다 체크

                # 현재 부하 계산
                total_load = sum(
                    metrics.current_load
                    for metrics in self.worker_metrics.values()
                )
                avg_load = total_load / len(self.worker_metrics) if self.worker_metrics else 0

                current_time = time.time()
                current_workers = len(self.workers)

                # 스케일 업 조건
                if (avg_load > self.scaling_config["scale_up_threshold"] and
                    current_workers < self.scaling_config["max_workers"] and
                    current_time - self.last_scale_time > self.scaling_config["scale_up_cooldown"]):

                    await self._scale_up()
                    self.last_scale_time = current_time

                # 스케일 다운 조건
                elif (avg_load < self.scaling_config["scale_down_threshold"] and
                      current_workers > self.scaling_config["min_workers"] and
                      current_time - self.last_scale_time > self.scaling_config["scale_down_cooldown"]):

                    await self._scale_down()
                    self.last_scale_time = current_time

            except Exception as e:
                logger.error(f"❌ 자동 스케일링 오류: {e}")

    async def _scale_up(self):
        """워커 추가"""
        try:
            import os
            from main import GeminiWorker

            if os.getenv('GEMINI_API_KEY'):
                new_worker_name = f"gemini_flash_{len(self.workers) + 1}"
                self.workers[new_worker_name] = GeminiWorker("gemini-1.5-flash-latest", 60)
                self.worker_metrics[new_worker_name] = WorkerMetrics()

                logger.info(f"📈 워커 추가: {new_worker_name} (총 {len(self.workers)}개)")

        except Exception as e:
            logger.error(f"❌ 워커 추가 실패: {e}")

    async def _scale_down(self):
        """워커 제거"""
        try:
            # 가장 부하가 낮은 워커 찾기
            lowest_load_worker = min(
                self.worker_metrics.keys(),
                key=lambda name: self.worker_metrics[name].current_load
            )

            # Flash 워커만 제거 (핵심 워커는 유지)
            if "flash" in lowest_load_worker and lowest_load_worker != "gemini_flash_1":
                del self.workers[lowest_load_worker]
                del self.worker_metrics[lowest_load_worker]

                logger.info(f"📉 워커 제거: {lowest_load_worker} (총 {len(self.workers)}개)")

        except Exception as e:
            logger.error(f"❌ 워커 제거 실패: {e}")

    async def _health_checker(self):
        """워커 헬스 체크"""
        while self.is_running:
            try:
                for worker_name, worker in self.workers.items():
                    if hasattr(worker, 'client'):
                        # 5분 이상 비활성 워커 체크
                        metrics = self.worker_metrics[worker_name]
                        if (time.time() - metrics.last_activity > 300 and
                            metrics.success_rate < 0.5):
                            logger.warning(f"⚠️ 비정상 워커 감지: {worker_name}")

                await asyncio.sleep(60)  # 1분마다 체크

            except Exception as e:
                logger.error(f"❌ 헬스 체크 오류: {e}")
                await asyncio.sleep(60)

    async def get_status(self) -> Dict[str, Any]:
        """워커 풀 상태 조회"""
        return {
            "is_running": self.is_running,
            "total_workers": len(self.workers),
            "pool_metrics": self.pool_metrics.copy(),
            "worker_metrics": {
                name: asdict(metrics)
                for name, metrics in self.worker_metrics.items()
            },
            "queue_sizes": {
                priority.name: queue.qsize()
                for priority, queue in self.task_queues.items()
            }
        }

    async def stop(self):
        """워커 풀 매니저 종료"""
        self.is_running = False

        # 백그라운드 작업 종료
        for task in self.worker_tasks.values():
            task.cancel()

        # 연결 종료
        if self.kafka_producer:
            self.kafka_producer.close()

        if self.redis_client:
            await self.redis_client.close()

        logger.info("✅ 워커 풀 매니저 종료 완료")