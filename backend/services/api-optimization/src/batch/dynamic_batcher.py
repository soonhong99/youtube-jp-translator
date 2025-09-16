"""
동적 배치 처리 시스템 - 최적 배치 크기 및 병렬 처리
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Optional, Tuple, Any, Callable, Awaitable
from dataclasses import dataclass, asdict, field
from collections import deque
from enum import Enum
import statistics
import numpy as np

logger = logging.getLogger(__name__)

class BatchPriority(Enum):
    """배치 우선순위"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class BatchStatus(Enum):
    """배치 상태"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"

@dataclass
class BatchItem:
    """배치 항목"""
    item_id: str
    data: Dict[str, Any]
    priority: BatchPriority = BatchPriority.NORMAL
    timeout: float = 30.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """만료 여부 확인"""
        return time.time() - self.created_at > self.timeout

@dataclass
class BatchGroup:
    """배치 그룹"""
    batch_id: str
    items: List[BatchItem]
    priority: BatchPriority
    status: BatchStatus = BatchStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    processing_time: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def size(self) -> int:
        """배치 크기"""
        return len(self.items)

    @property
    def total_processing_time(self) -> float:
        """총 처리 시간"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return time.time() - self.started_at
        return 0.0

    def start_processing(self):
        """처리 시작"""
        self.status = BatchStatus.PROCESSING
        self.started_at = time.time()

    def complete_processing(self, success_count: int, failure_count: int):
        """처리 완료"""
        self.status = BatchStatus.COMPLETED if failure_count == 0 else BatchStatus.FAILED
        self.completed_at = time.time()
        self.success_count = success_count
        self.failure_count = failure_count

@dataclass
class BatchingMetrics:
    """배치 처리 메트릭"""
    total_batches: int = 0
    total_items: int = 0
    average_batch_size: float = 0.0
    average_processing_time: float = 0.0
    throughput_per_second: float = 0.0
    success_rate: float = 0.0
    processing_times: deque = field(default_factory=lambda: deque(maxlen=100))
    batch_sizes: deque = field(default_factory=lambda: deque(maxlen=100))

    def add_batch_result(self, batch: BatchGroup):
        """배치 결과 추가"""
        self.total_batches += 1
        self.total_items += batch.size

        processing_time = batch.total_processing_time
        self.processing_times.append(processing_time)
        self.batch_sizes.append(batch.size)

        # 평균 계산
        if self.processing_times:
            self.average_processing_time = statistics.mean(self.processing_times)
        if self.batch_sizes:
            self.average_batch_size = statistics.mean(self.batch_sizes)

        # 처리량 계산 (최근 1분간)
        recent_times = [t for t in self.processing_times if t > 0]
        if recent_times and processing_time > 0:
            items_processed = sum(list(self.batch_sizes)[-len(recent_times):])
            total_time = sum(recent_times)
            self.throughput_per_second = items_processed / total_time if total_time > 0 else 0.0

        # 성공률 계산
        if batch.size > 0:
            current_success_rate = batch.success_count / batch.size
            self.success_rate = (self.success_rate * (self.total_batches - 1) + current_success_rate) / self.total_batches

class DynamicBatcher:
    """동적 배치 처리 시스템"""

    def __init__(self, processor_func: Callable, redis_client=None, result_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None):
        self.processor_func = processor_func
        self.redis_client = redis_client
        self.result_callback = result_callback

        # 설정
        self.config = {
            'min_batch_size': 1,           # 최소 배치 크기
            'max_batch_size': 10,          # 최대 배치 크기
            'default_batch_size': 3,       # 기본 배치 크기
            'max_wait_time': 5.0,          # 최대 대기 시간 (초)
            'processing_timeout': 30.0,    # 처리 타임아웃 (초)
            'max_concurrent_batches': 5,   # 최대 동시 배치 수
            'optimization_interval': 60,   # 최적화 간격 (초)
            'metrics_window': 300,         # 메트릭 윈도우 (초)
        }

        # 상태 관리
        self.pending_items: Dict[BatchPriority, List[BatchItem]] = {
            BatchPriority.CRITICAL: [],
            BatchPriority.HIGH: [],
            BatchPriority.NORMAL: [],
            BatchPriority.LOW: []
        }
        self.active_batches: Dict[str, BatchGroup] = {}
        self.completed_batches: deque = deque(maxlen=1000)

        # 메트릭
        self.metrics = BatchingMetrics()

        # 적응형 파라미터
        self.adaptive_params = {
            'optimal_batch_size': self.config['default_batch_size'],
            'wait_time_multiplier': 1.0,
            'load_threshold': 0.7,
            'performance_weight': 0.6,  # 성능 vs 지연시간 가중치
        }

        # 태스크 관리
        self.batch_scheduler_task = None
        self.optimization_task = None
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        self.is_running = False

        logger.info("✅ DynamicBatcher 초기화 완료")

    async def start(self):
        """배치 처리기 시작"""
        try:
            self.is_running = True

            # 배치 스케줄러 시작
            self.batch_scheduler_task = asyncio.create_task(self._batch_scheduler())

            # 최적화 태스크 시작
            self.optimization_task = asyncio.create_task(self._optimization_loop())

            logger.info("✅ DynamicBatcher 시작 완료")

        except Exception as e:
            logger.error(f"❌ DynamicBatcher 시작 실패: {e}")
            raise

    async def stop(self):
        """배치 처리기 종료"""
        try:
            self.is_running = False

            # 스케줄러 종료
            if self.batch_scheduler_task:
                self.batch_scheduler_task.cancel()
            if self.optimization_task:
                self.optimization_task.cancel()

            # 활성 배치 처리 대기
            if self.processing_tasks:
                await asyncio.gather(*self.processing_tasks.values(), return_exceptions=True)

            logger.info("✅ DynamicBatcher 종료 완료")

        except Exception as e:
            logger.error(f"❌ DynamicBatcher 종료 실패: {e}")

    async def add_item(self, item_id: str, data: Dict[str, Any],
                      priority: BatchPriority = BatchPriority.NORMAL,
                      timeout: float = 30.0) -> bool:
        """배치 항목 추가"""
        try:
            item = BatchItem(
                item_id=item_id,
                data=data,
                priority=priority,
                timeout=timeout
            )

            self.pending_items[priority].append(item)

            logger.debug(f"📦 배치 항목 추가: {item_id} (우선순위: {priority.name})")
            return True

        except Exception as e:
            logger.error(f"❌ 배치 항목 추가 실패: {item_id} - {e}")
            return False

    async def _batch_scheduler(self):
        """배치 스케줄러"""
        while self.is_running:
            try:
                # 배치 생성 조건 확인
                if await self._should_create_batch():
                    batch = await self._create_next_batch()
                    if batch:
                        await self._process_batch(batch)

                await asyncio.sleep(0.1)  # 100ms 간격으로 확인

            except Exception as e:
                logger.error(f"❌ 배치 스케줄러 오류: {e}")
                await asyncio.sleep(1.0)

    async def _should_create_batch(self) -> bool:
        """배치 생성 여부 결정"""
        try:
            # 1. 동시 배치 수 제한 확인
            if len(self.active_batches) >= self.config['max_concurrent_batches']:
                return False

            # 2. 대기 중인 항목이 있는지 확인
            total_pending = sum(len(items) for items in self.pending_items.values())
            if total_pending == 0:
                return False

            # 3. 긴급 항목이 있으면 즉시 배치 생성
            if self.pending_items[BatchPriority.CRITICAL]:
                return True

            # 4. 적응형 배치 크기에 도달했으면 배치 생성
            optimal_size = self.adaptive_params['optimal_batch_size']
            if total_pending >= optimal_size:
                return True

            # 5. 최대 대기 시간 초과 확인
            oldest_item_time = self._get_oldest_item_time()
            if oldest_item_time and time.time() - oldest_item_time > self.config['max_wait_time']:
                return True

            return False

        except Exception as e:
            logger.error(f"❌ 배치 생성 조건 확인 실패: {e}")
            return False

    def _get_oldest_item_time(self) -> Optional[float]:
        """가장 오래된 항목의 생성 시간"""
        try:
            oldest_time = None

            for priority_items in self.pending_items.values():
                if priority_items:
                    item_time = priority_items[0].created_at
                    if oldest_time is None or item_time < oldest_time:
                        oldest_time = item_time

            return oldest_time

        except Exception:
            return None

    async def _create_next_batch(self) -> Optional[BatchGroup]:
        """다음 배치 생성"""
        try:
            batch_items = []
            batch_priority = BatchPriority.LOW

            # 우선순위별로 항목 수집
            target_size = self._calculate_optimal_batch_size()

            for priority in [BatchPriority.CRITICAL, BatchPriority.HIGH,
                           BatchPriority.NORMAL, BatchPriority.LOW]:
                items = self.pending_items[priority]

                while items and len(batch_items) < target_size:
                    item = items.pop(0)

                    # 만료된 항목 건너뛰기
                    if item.is_expired():
                        logger.warning(f"⏰ 만료된 항목 건너뛰기: {item.item_id}")
                        continue

                    batch_items.append(item)
                    batch_priority = max(batch_priority, priority)

                if len(batch_items) >= target_size:
                    break

            if not batch_items:
                return None

            # 배치 그룹 생성
            batch_id = f"batch_{int(time.time() * 1000)}"
            batch = BatchGroup(
                batch_id=batch_id,
                items=batch_items,
                priority=batch_priority
            )

            self.active_batches[batch_id] = batch

            logger.debug(f"🎯 배치 생성: {batch_id} (크기: {len(batch_items)}, 우선순위: {batch_priority.name})")
            return batch

        except Exception as e:
            logger.error(f"❌ 배치 생성 실패: {e}")
            return None

    def _calculate_optimal_batch_size(self) -> int:
        """최적 배치 크기 계산"""
        try:
            # 기본 적응형 크기
            base_size = self.adaptive_params['optimal_batch_size']

            # 현재 부하 상황 고려
            current_load = len(self.active_batches) / self.config['max_concurrent_batches']

            if current_load > self.adaptive_params['load_threshold']:
                # 고부하 시 작은 배치
                adjusted_size = max(self.config['min_batch_size'], int(base_size * 0.7))
            else:
                # 저부하 시 큰 배치
                adjusted_size = min(self.config['max_batch_size'], int(base_size * 1.3))

            # 대기 중인 항목 수 제한
            total_pending = sum(len(items) for items in self.pending_items.values())
            final_size = min(adjusted_size, total_pending)

            return max(self.config['min_batch_size'], final_size)

        except Exception as e:
            logger.error(f"❌ 최적 배치 크기 계산 실패: {e}")
            return self.config['default_batch_size']

    async def _process_batch(self, batch: BatchGroup):
        """배치 처리"""
        try:
            # 처리 태스크 생성
            task = asyncio.create_task(self._execute_batch_processing(batch))
            self.processing_tasks[batch.batch_id] = task

            # 태스크 완료 대기 (백그라운드)
            asyncio.create_task(self._handle_batch_completion(batch.batch_id, task))

        except Exception as e:
            logger.error(f"❌ 배치 처리 시작 실패: {batch.batch_id} - {e}")

    async def _execute_batch_processing(self, batch: BatchGroup) -> BatchGroup:
        """배치 처리 실행"""
        try:
            batch.start_processing()

            logger.info(f"🚀 배치 처리 시작: {batch.batch_id} (크기: {batch.size})")

            # 배치 데이터 준비
            batch_data = [item.data for item in batch.items]

            # 프로세서 함수 호출
            start_time = time.time()
            results = await asyncio.wait_for(
                self.processor_func(batch_data),
                timeout=self.config['processing_timeout']
            )
            processing_time = time.time() - start_time

            # 결과 처리
            success_count = 0
            failure_count = 0

            if isinstance(results, list) and len(results) == len(batch.items):
                batch.results = results
                for result in results:
                    if result.get('success', True):
                        success_count += 1
                    else:
                        failure_count += 1
            else:
                # 결과 형식이 잘못된 경우
                failure_count = len(batch.items)
                batch.results = [{'success': False, 'error': 'Invalid result format'}] * len(batch.items)

            batch.complete_processing(success_count, failure_count)
            batch.processing_time = processing_time

            logger.info(f"✅ 배치 처리 완료: {batch.batch_id} (성공: {success_count}, 실패: {failure_count}, 시간: {processing_time:.2f}s)")
            return batch

        except asyncio.TimeoutError:
            batch.status = BatchStatus.TIMEOUT
            logger.error(f"⏰ 배치 처리 타임아웃: {batch.batch_id}")
            return batch

        except Exception as e:
            batch.status = BatchStatus.FAILED
            logger.error(f"❌ 배치 처리 실패: {batch.batch_id} - {e}")
            return batch

    async def _handle_batch_completion(self, batch_id: str, task: asyncio.Task):
        """배치 완료 처리"""
        try:
            batch = await task

            # 메트릭 업데이트
            self.metrics.add_batch_result(batch)

            # 완료된 배치를 기록에 추가
            self.completed_batches.append(batch)

            # 🔥 CRITICAL FIX: 배치 결과를 Kafka로 발행
            await self._publish_batch_results(batch)

            # 활성 배치에서 제거
            if batch_id in self.active_batches:
                del self.active_batches[batch_id]
            if batch_id in self.processing_tasks:
                del self.processing_tasks[batch_id]

            # Redis에 결과 저장 (선택적)
            if self.redis_client:
                await self._store_batch_result(batch)

            # 결과 콜백을 통해 Kafka로 결과 전송 (항목별)
            try:
                if self.result_callback and isinstance(batch.results, list):
                    for result in batch.results:
                        task_id = result.get('task_id') or (result.get('data') or {}).get('task_id')
                        if task_id:
                            await self.result_callback(task_id, {
                                'translated_text': result.get('translated_text', ''),
                                'cache_hit': result.get('cache_hit', False),
                                'model_used': result.get('model_used', 'batch'),
                                'processing_time': result.get('processing_time', 0.0),
                                'cost': result.get('cost', 0.0)
                            })
            except Exception as e:
                logger.error(f"❌ 결과 콜백 전송 실패: {e}")

        except Exception as e:
            logger.error(f"❌ 배치 완료 처리 실패: {batch_id} - {e}")

    async def _store_batch_result(self, batch: BatchGroup):
        """배치 결과 Redis 저장"""
        try:
            result_data = {
                'batch_id': batch.batch_id,
                'status': batch.status.value,
                'processing_time': batch.processing_time,
                'success_count': batch.success_count,
                'failure_count': batch.failure_count,
                'results': batch.results,
                'completed_at': batch.completed_at
            }

            await self.redis_client.setex(
                f"batch_result:{batch.batch_id}",
                3600,  # 1시간 TTL
                json.dumps(result_data, ensure_ascii=False)
            )

        except Exception as e:
            logger.error(f"❌ 배치 결과 저장 실패: {batch.batch_id} - {e}")

    async def _optimization_loop(self):
        """최적화 루프"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config['optimization_interval'])
                await self._optimize_parameters()

            except Exception as e:
                logger.error(f"❌ 최적화 루프 오류: {e}")

    async def _optimize_parameters(self):
        """파라미터 최적화"""
        try:
            if len(self.completed_batches) < 5:
                return  # 충분한 데이터 없음

            # 최근 배치들 분석
            recent_batches = list(self.completed_batches)[-20:]  # 최근 20개

            # 배치 크기별 성능 분석
            size_performance = {}
            for batch in recent_batches:
                size = batch.size
                if size not in size_performance:
                    size_performance[size] = []

                # 성능 점수 = 처리량 / 처리시간 * 성공률
                if batch.processing_time > 0:
                    throughput = size / batch.processing_time
                    success_rate = batch.success_count / size if size > 0 else 0
                    performance_score = throughput * success_rate
                    size_performance[size].append(performance_score)

            # 최적 배치 크기 찾기
            if size_performance:
                avg_performance = {}
                for size, scores in size_performance.items():
                    if len(scores) >= 2:  # 최소 2개 샘플
                        avg_performance[size] = statistics.mean(scores)

                if avg_performance:
                    optimal_size = max(avg_performance.keys(), key=avg_performance.get)

                    # 점진적 조정
                    current_optimal = self.adaptive_params['optimal_batch_size']
                    adjustment_factor = 0.2  # 20%씩 조정

                    if optimal_size > current_optimal:
                        new_optimal = current_optimal + (optimal_size - current_optimal) * adjustment_factor
                    elif optimal_size < current_optimal:
                        new_optimal = current_optimal - (current_optimal - optimal_size) * adjustment_factor
                    else:
                        new_optimal = current_optimal

                    self.adaptive_params['optimal_batch_size'] = max(
                        self.config['min_batch_size'],
                        min(self.config['max_batch_size'], int(new_optimal))
                    )

            # 대기 시간 최적화
            avg_processing_time = self.metrics.average_processing_time
            if avg_processing_time > 0:
                # 처리 시간이 긴 경우 대기 시간 단축
                if avg_processing_time > 10.0:
                    self.adaptive_params['wait_time_multiplier'] = 0.8
                elif avg_processing_time < 3.0:
                    self.adaptive_params['wait_time_multiplier'] = 1.2
                else:
                    self.adaptive_params['wait_time_multiplier'] = 1.0

            logger.debug(f"📊 파라미터 최적화 완료: {self.adaptive_params}")

        except Exception as e:
            logger.error(f"❌ 파라미터 최적화 실패: {e}")

    async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """배치 상태 조회"""
        try:
            # 활성 배치 확인
            if batch_id in self.active_batches:
                batch = self.active_batches[batch_id]
                return {
                    'batch_id': batch.batch_id,
                    'status': batch.status.value,
                    'size': batch.size,
                    'priority': batch.priority.name,
                    'created_at': batch.created_at,
                    'started_at': batch.started_at,
                    'processing_time': batch.total_processing_time
                }

            # 완료된 배치 확인
            for batch in self.completed_batches:
                if batch.batch_id == batch_id:
                    return {
                        'batch_id': batch.batch_id,
                        'status': batch.status.value,
                        'size': batch.size,
                        'processing_time': batch.processing_time,
                        'success_count': batch.success_count,
                        'failure_count': batch.failure_count,
                        'completed_at': batch.completed_at
                    }

            # Redis에서 확인
            if self.redis_client:
                result_data = await self.redis_client.get(f"batch_result:{batch_id}")
                if result_data:
                    return json.loads(result_data)

            return None

        except Exception as e:
            logger.error(f"❌ 배치 상태 조회 실패: {batch_id} - {e}")
            return None

    async def get_metrics(self) -> Dict[str, Any]:
        """메트릭 조회"""
        try:
            total_pending = sum(len(items) for items in self.pending_items.values())

            return {
                'pending_items_total': total_pending,
                'pending_by_priority': {
                    priority.name: len(items)
                    for priority, items in self.pending_items.items()
                },
                'active_batches': len(self.active_batches),
                'completed_batches_total': len(self.completed_batches),
                'metrics': asdict(self.metrics),
                'adaptive_parameters': self.adaptive_params.copy(),
                'config': self.config.copy()
            }

        except Exception as e:
            logger.error(f"❌ 메트릭 조회 실패: {e}")
            return {}

    async def _publish_batch_results(self, batch: BatchGroup):
        """배치 결과를 Kafka로 발행 (CRITICAL FIX)"""
        try:
            if not hasattr(self, 'kafka_producer') or not self.kafka_producer:
                logger.warning(f"⚠️ Kafka 프로듀서 없음, 결과 발행 건너뜀: {batch.batch_id}")
                return

            # 각 배치 항목의 결과를 개별적으로 발행
            for i, (item, result) in enumerate(zip(batch.items, batch.results)):
                if result.get('success', True):
                    # 성공한 번역 결과 발행
                    result_payload = {
                        'task_id': item.data.get('task_id', item.item_id),
                        'result': {
                            'translated_text': result.get('translated_text', ''),
                            'model_used': result.get('model_used', 'unknown'),
                            'processing_time': result.get('processing_time', 0.0),
                            'cost': result.get('cost', 0.0),
                            'cache_hit': result.get('cache_hit', False),
                            'batch_id': batch.batch_id,
                            'batch_processing_time': batch.processing_time,
                            'timestamp': time.time()
                        }
                    }

                    # optimized_translation_results 토픽으로 발행
                    self.kafka_producer.send(
                        'optimized_translation_results',
                        key=result_payload['task_id'],
                        value=result_payload
                    )

                    logger.debug(f"📤 배치 결과 발행: {result_payload['task_id']} (배치: {batch.batch_id})")

            # 배치 전체 완료 통계 발행 (선택적)
            batch_summary = {
                'batch_id': batch.batch_id,
                'total_items': batch.size,
                'success_count': batch.success_count,
                'failure_count': batch.failure_count,
                'processing_time': batch.processing_time,
                'completed_at': batch.completed_at
            }

            self.kafka_producer.send(
                'batch_processing_stats',
                key=batch.batch_id,
                value=batch_summary
            )

            # Kafka 프로듀서 flush (중요!)
            self.kafka_producer.flush(timeout=5)

            logger.info(f"✅ 배치 결과 발행 완료: {batch.batch_id} ({batch.success_count}/{batch.size} 성공)")

        except Exception as e:
            logger.error(f"❌ 배치 결과 발행 실패: {batch.batch_id} - {e}")

    def set_kafka_producer(self, kafka_producer):
        """Kafka 프로듀서 설정 (외부에서 주입)"""
        self.kafka_producer = kafka_producer
        logger.info("✅ DynamicBatcher에 Kafka 프로듀서 설정 완료")
