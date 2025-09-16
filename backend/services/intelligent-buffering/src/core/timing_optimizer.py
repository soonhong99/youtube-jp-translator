"""
타이밍 최적화 시스템 - 적응형 번역 트리거 및 배치 최적화
"""

import asyncio
import json
import logging
import time
import statistics
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import asdict, dataclass
from collections import deque, defaultdict
import numpy as np

from ..models.completion_models import (
    ProcessingContext, TriggerDecision, TriggerReason, BufferState,
    CompletionScore, AdaptiveThreshold
)
from ..models.context_models import ContextAnalysisResult, ContextualSegment

logger = logging.getLogger(__name__)

@dataclass
class SystemLoad:
    """시스템 부하 정보"""
    cpu_usage: float = 0.0          # CPU 사용률 (0.0-1.0)
    memory_usage: float = 0.0       # 메모리 사용률 (0.0-1.0)
    network_latency: float = 0.0    # 네트워크 지연시간 (ms)
    api_queue_length: int = 0       # API 큐 길이
    active_tasks: int = 0           # 활성 작업 수
    timestamp: float = 0.0

    @property
    def overall_load(self) -> float:
        """전체 부하 점수"""
        return (self.cpu_usage * 0.3 +
                self.memory_usage * 0.2 +
                min(1.0, self.network_latency / 1000.0) * 0.2 +
                min(1.0, self.api_queue_length / 50.0) * 0.2 +
                min(1.0, self.active_tasks / 20.0) * 0.1)

@dataclass
class ProcessingMetrics:
    """처리 메트릭"""
    processing_times: deque = None          # 최근 처리 시간들
    success_rates: deque = None             # 성공률 기록
    queue_wait_times: deque = None          # 큐 대기 시간들
    api_response_times: deque = None        # API 응답 시간들
    batch_sizes: deque = None               # 배치 크기 기록
    quality_scores: deque = None            # 품질 점수 기록

    def __post_init__(self):
        if self.processing_times is None:
            self.processing_times = deque(maxlen=100)
        if self.success_rates is None:
            self.success_rates = deque(maxlen=50)
        if self.queue_wait_times is None:
            self.queue_wait_times = deque(maxlen=100)
        if self.api_response_times is None:
            self.api_response_times = deque(maxlen=100)
        if self.batch_sizes is None:
            self.batch_sizes = deque(maxlen=100)
        if self.quality_scores is None:
            self.quality_scores = deque(maxlen=100)

    def add_processing_record(self, processing_time: float, success: bool,
                            queue_wait: float, api_response: float,
                            batch_size: int, quality_score: float):
        """처리 기록 추가"""
        self.processing_times.append(processing_time)
        self.success_rates.append(1.0 if success else 0.0)
        self.queue_wait_times.append(queue_wait)
        self.api_response_times.append(api_response)
        self.batch_sizes.append(batch_size)
        self.quality_scores.append(quality_score)

    def get_average_processing_time(self) -> float:
        """평균 처리 시간"""
        return statistics.mean(self.processing_times) if self.processing_times else 5.0

    def get_success_rate(self) -> float:
        """성공률"""
        return statistics.mean(self.success_rates) if self.success_rates else 0.9

    def get_optimal_batch_size(self) -> int:
        """최적 배치 크기 추정"""
        if not self.batch_sizes or not self.processing_times:
            return 3

        # 배치 크기별 평균 처리 시간 분석
        batch_performance = defaultdict(list)
        for batch_size, proc_time in zip(list(self.batch_sizes), list(self.processing_times)):
            batch_performance[batch_size].append(proc_time)

        if batch_performance:
            # 처리 시간이 가장 좋은 배치 크기 선택
            avg_times = {
                size: statistics.mean(times)
                for size, times in batch_performance.items()
                if len(times) >= 3  # 최소 3개 샘플
            }

            if avg_times:
                optimal_size = min(avg_times.keys(), key=avg_times.get)
                return max(1, min(10, optimal_size))  # 1-10 범위 제한

        return 3  # 기본값

class TimingOptimizer:
    """타이밍 최적화 시스템"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client

        # 설정
        self.config = {
            'min_trigger_interval': 0.5,       # 최소 트리거 간격 (초)
            'max_trigger_interval': 15.0,      # 최대 트리거 간격 (초)
            'performance_window': 300,         # 성능 윈도우 (초)
            'load_sampling_interval': 10,      # 부하 샘플링 간격 (초)
            'optimization_interval': 60,       # 최적화 간격 (초)
            'latency_target': 8.0,             # 목표 지연시간 (초)
            'quality_threshold': 0.8,          # 품질 임계값
        }

        # 상태 관리
        self.system_loads: deque = deque(maxlen=100)
        self.processing_metrics = ProcessingMetrics()
        self.trigger_history: deque = deque(maxlen=1000)
        self.optimization_cache: Dict[str, Any] = {}

        # 적응형 파라미터
        self.adaptive_params = {
            'base_threshold': 5.0,
            'urgency_multiplier': 1.0,
            'load_sensitivity': 0.5,
            'quality_weight': 0.3,
            'cost_weight': 0.3
        }

        # 백그라운드 태스크
        self.monitoring_task = None
        self.optimization_task = None
        self.is_running = False

        logger.info("✅ TimingOptimizer 초기화 완료")

    async def start(self):
        """최적화기 시작"""
        try:
            self.is_running = True

            # 백그라운드 모니터링 시작
            self.monitoring_task = asyncio.create_task(self._monitor_system_load())
            self.optimization_task = asyncio.create_task(self._optimize_parameters())

            logger.info("✅ TimingOptimizer 시작 완료")

        except Exception as e:
            logger.error(f"❌ TimingOptimizer 시작 실패: {e}")
            raise

    async def stop(self):
        """최적화기 종료"""
        self.is_running = False

        if self.monitoring_task:
            self.monitoring_task.cancel()
        if self.optimization_task:
            self.optimization_task.cancel()

        logger.info("✅ TimingOptimizer 종료 완료")

    async def optimize_trigger_timing(self, context: ProcessingContext,
                                    completion_score: CompletionScore,
                                    context_analysis: Optional[ContextAnalysisResult] = None) -> TriggerDecision:
        """최적 트리거 타이밍 결정"""
        try:
            logger.debug(f"🎯 트리거 타이밍 최적화: {context.task_id}")

            # 현재 시스템 상태 분석
            current_load = await self._get_current_system_load()
            predicted_processing_time = await self._predict_processing_time(context, current_load)

            # 적응형 임계값 계산
            adaptive_threshold = self._calculate_adaptive_threshold(
                context, current_load, context_analysis
            )

            # 최적 배치 크기 결정
            optimal_batch_size = self._determine_optimal_batch_size(
                context, current_load, predicted_processing_time
            )

            # 트리거 결정 로직
            decision = await self._make_timing_decision(
                context, completion_score, adaptive_threshold,
                optimal_batch_size, predicted_processing_time
            )

            # 결정 기록
            self._record_trigger_decision(context, decision, current_load)

            logger.debug(f"✅ 트리거 결정: {decision.should_trigger} - {decision.reason.value}")
            return decision

        except Exception as e:
            logger.error(f"❌ 트리거 타이밍 최적화 실패: {context.task_id} - {e}")
            return self._create_fallback_decision(context)

    async def _get_current_system_load(self) -> SystemLoad:
        """현재 시스템 부하 조회"""
        try:
            if self.redis_client:
                load_data = await self.redis_client.get("system_load")
                if load_data:
                    data = json.loads(load_data)
                    return SystemLoad(**data)

            # 시뮬레이션 데이터 (실제로는 시스템 모니터링 필요)
            load = SystemLoad(
                cpu_usage=np.random.uniform(0.3, 0.8),
                memory_usage=np.random.uniform(0.4, 0.7),
                network_latency=np.random.uniform(50, 200),
                api_queue_length=np.random.randint(0, 20),
                active_tasks=np.random.randint(5, 25),
                timestamp=time.time()
            )

            # 부하 기록 저장
            self.system_loads.append(load)
            return load

        except Exception as e:
            logger.error(f"❌ 시스템 부하 조회 실패: {e}")
            return SystemLoad(timestamp=time.time())

    async def _predict_processing_time(self, context: ProcessingContext,
                                     system_load: SystemLoad) -> float:
        """처리 시간 예측"""
        try:
            # 기본 처리 시간 (세그먼트 기반)
            segment_count = len(context.buffer_state.chunks)
            base_time = segment_count * 0.8  # 세그먼트당 0.8초

            # 텍스트 길이 보정
            text_length = len(context.buffer_state.combined_text)
            length_factor = 1.0 + (text_length / 1000.0) * 0.3  # 1000자당 30% 증가

            # 품질 요구사항 보정
            quality_factor = 1.0 + (context.quality_requirement - 0.5) * 0.4

            # 시스템 부하 보정
            load_factor = 1.0 + system_load.overall_load * 0.5

            # 이력 기반 보정
            historical_avg = self.processing_metrics.get_average_processing_time()
            if historical_avg > 0:
                history_factor = 0.7  # 70% 이력 기반, 30% 모델 기반
                predicted_time = (base_time * length_factor * quality_factor * load_factor * (1 - history_factor) +
                                historical_avg * history_factor)
            else:
                predicted_time = base_time * length_factor * quality_factor * load_factor

            # 제한 범위 적용
            return max(1.0, min(30.0, predicted_time))

        except Exception as e:
            logger.error(f"❌ 처리 시간 예측 실패: {e}")
            return 5.0

    def _calculate_adaptive_threshold(self, context: ProcessingContext,
                                    system_load: SystemLoad,
                                    context_analysis: Optional[ContextAnalysisResult] = None) -> AdaptiveThreshold:
        """적응형 임계값 계산"""
        try:
            threshold = AdaptiveThreshold(base_threshold=self.adaptive_params['base_threshold'])

            # 1. 긴급도 기반 조정
            urgency_adjustment = {
                1: 1.5,   # 낮은 긴급도 - 더 오래 대기
                2: 1.2,
                3: 1.0,   # 보통 긴급도
                4: 0.7,   # 높은 긴급도 - 빠른 처리
                5: 0.4    # 매우 긴급 - 즉시 처리
            }
            threshold.urgency_multiplier = urgency_adjustment.get(context.urgency_level, 1.0)

            # 2. 시스템 부하 기반 조정
            load_impact = system_load.overall_load * self.adaptive_params['load_sensitivity']
            if system_load.overall_load > 0.8:
                threshold.load_adjustment = 3.0  # 고부하 시 더 긴 대기
            elif system_load.overall_load > 0.6:
                threshold.load_adjustment = 1.0
            else:
                threshold.load_adjustment = -1.0  # 저부하 시 빠른 처리

            # 3. 품질 요구사항 기반 조정
            quality_impact = (context.quality_requirement - 0.5) * 4.0  # -2.0 ~ +2.0
            threshold.quality_adjustment = quality_impact

            # 4. 문맥 분석 기반 조정
            if context_analysis:
                if context_analysis.should_wait_for_completion:
                    threshold.quality_adjustment += 2.0  # 완성까지 대기

                # 주제 변경 시 빠른 처리
                if context_analysis.topic_continuity < 0.6:
                    threshold.urgency_multiplier *= 0.8

            # 5. 비용 민감도 기반 조정
            cost_impact = context.cost_priority * 2.0  # 비용 중시 시 더 긴 대기
            threshold.load_adjustment += cost_impact

            return threshold

        except Exception as e:
            logger.error(f"❌ 적응형 임계값 계산 실패: {e}")
            return AdaptiveThreshold()

    def _determine_optimal_batch_size(self, context: ProcessingContext,
                                    system_load: SystemLoad,
                                    predicted_processing_time: float) -> int:
        """최적 배치 크기 결정"""
        try:
            # 이력 기반 최적 크기
            historical_optimal = self.processing_metrics.get_optimal_batch_size()

            # 시스템 부하 기반 조정
            if system_load.overall_load > 0.8:
                load_adjusted = max(1, historical_optimal - 2)  # 고부하 시 작은 배치
            elif system_load.overall_load < 0.4:
                load_adjusted = min(8, historical_optimal + 2)  # 저부하 시 큰 배치
            else:
                load_adjusted = historical_optimal

            # 지연시간 요구사항 기반 조정
            if context.latency_requirement < 5.0:
                latency_adjusted = max(1, load_adjusted - 1)  # 낮은 지연시간 요구 시
            elif context.latency_requirement > 15.0:
                latency_adjusted = min(10, load_adjusted + 2)  # 높은 지연시간 허용 시
            else:
                latency_adjusted = load_adjusted

            # 품질 요구사항 기반 조정
            if context.quality_requirement > 0.9:
                final_size = max(1, latency_adjusted - 1)  # 높은 품질 요구 시 작은 배치
            else:
                final_size = latency_adjusted

            # 버퍼 크기 제한
            available_chunks = len(context.buffer_state.chunks)
            final_size = min(final_size, available_chunks, 10)  # 최대 10개

            return max(1, final_size)

        except Exception as e:
            logger.error(f"❌ 최적 배치 크기 결정 실패: {e}")
            return 3

    async def _make_timing_decision(self, context: ProcessingContext,
                                  completion_score: CompletionScore,
                                  adaptive_threshold: AdaptiveThreshold,
                                  optimal_batch_size: int,
                                  predicted_processing_time: float) -> TriggerDecision:
        """타이밍 결정 로직"""
        try:
            buffer_age = context.buffer_state.buffer_age
            chunk_count = len(context.buffer_state.chunks)

            # 결정 요소들 평가
            decision_factors = []

            # 1. 문장 완성도 기반
            if completion_score.overall_score >= self.config['quality_threshold']:
                confidence = completion_score.confidence
                decision_factors.append((True, TriggerReason.SENTENCE_COMPLETE, confidence))

            # 2. 적응형 시간 임계값 기반
            if buffer_age >= adaptive_threshold.effective_threshold:
                confidence = min(1.0, buffer_age / adaptive_threshold.effective_threshold)
                decision_factors.append((True, TriggerReason.TIME_THRESHOLD, confidence))

            # 3. 긴급도 기반
            if context.urgency_level >= 4:
                confidence = context.urgency_level / 5.0
                decision_factors.append((True, TriggerReason.URGENT_REQUEST, confidence))

            # 4. 지연시간 제한 기반
            if buffer_age + predicted_processing_time > context.latency_requirement:
                confidence = 0.9
                decision_factors.append((True, TriggerReason.TIME_THRESHOLD, confidence))

            # 5. 최대 버퍼 시간 초과
            if buffer_age >= self.config['max_trigger_interval']:
                confidence = 1.0
                decision_factors.append((True, TriggerReason.TIME_THRESHOLD, confidence))

            # 6. 최소 간격 체크
            last_trigger_time = await self._get_last_trigger_time(context.task_id)
            if last_trigger_time and (time.time() - last_trigger_time) < self.config['min_trigger_interval']:
                # 최소 간격 미만이면 대기
                return TriggerDecision(
                    should_trigger=False,
                    reason=TriggerReason.TIME_THRESHOLD,
                    confidence=0.0,
                    estimated_processing_time=predicted_processing_time,
                    recommended_batch_size=optimal_batch_size
                )

            # 결정 내리기
            if decision_factors:
                # 가장 신뢰도 높은 요소 선택
                should_trigger, reason, confidence = max(decision_factors, key=lambda x: x[2])

                return TriggerDecision(
                    should_trigger=should_trigger,
                    reason=reason,
                    confidence=confidence,
                    estimated_processing_time=predicted_processing_time,
                    recommended_batch_size=optimal_batch_size,
                    additional_info={
                        'buffer_age': buffer_age,
                        'completion_score': completion_score.overall_score,
                        'adaptive_threshold': adaptive_threshold.effective_threshold,
                        'urgency_level': context.urgency_level,
                        'chunk_count': chunk_count
                    }
                )
            else:
                # 트리거 조건 불만족
                return TriggerDecision(
                    should_trigger=False,
                    reason=TriggerReason.SENTENCE_COMPLETE,
                    confidence=completion_score.confidence,
                    estimated_processing_time=predicted_processing_time,
                    recommended_batch_size=optimal_batch_size
                )

        except Exception as e:
            logger.error(f"❌ 타이밍 결정 실패: {e}")
            return self._create_fallback_decision(context)

    async def _get_last_trigger_time(self, task_id: str) -> Optional[float]:
        """마지막 트리거 시간 조회"""
        try:
            if self.redis_client:
                trigger_time = await self.redis_client.get(f"last_trigger:{task_id}")
                if trigger_time:
                    return float(trigger_time)

            return None

        except Exception:
            return None

    def _record_trigger_decision(self, context: ProcessingContext,
                               decision: TriggerDecision, system_load: SystemLoad):
        """트리거 결정 기록"""
        try:
            record = {
                'task_id': context.task_id,
                'timestamp': time.time(),
                'should_trigger': decision.should_trigger,
                'reason': decision.reason.value,
                'confidence': decision.confidence,
                'buffer_age': context.buffer_state.buffer_age,
                'chunk_count': len(context.buffer_state.chunks),
                'system_load': system_load.overall_load,
                'urgency_level': context.urgency_level,
                'estimated_processing_time': decision.estimated_processing_time
            }

            self.trigger_history.append(record)

            # Redis에도 저장
            if self.redis_client and decision.should_trigger:
                asyncio.create_task(
                    self.redis_client.setex(
                        f"last_trigger:{context.task_id}",
                        300,  # 5분 TTL
                        str(time.time())
                    )
                )

        except Exception as e:
            logger.error(f"❌ 트리거 결정 기록 실패: {e}")

    def _create_fallback_decision(self, context: ProcessingContext) -> TriggerDecision:
        """기본 결정 생성 (오류 시)"""
        return TriggerDecision(
            should_trigger=context.buffer_state.buffer_age > 10.0,  # 10초 초과 시 트리거
            reason=TriggerReason.TIME_THRESHOLD,
            confidence=0.5,
            estimated_processing_time=5.0,
            recommended_batch_size=min(3, len(context.buffer_state.chunks))
        )

    async def _monitor_system_load(self):
        """시스템 부하 모니터링"""
        while self.is_running:
            try:
                await self._get_current_system_load()
                await asyncio.sleep(self.config['load_sampling_interval'])

            except Exception as e:
                logger.error(f"❌ 시스템 부하 모니터링 오류: {e}")
                await asyncio.sleep(self.config['load_sampling_interval'])

    async def _optimize_parameters(self):
        """파라미터 최적화"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config['optimization_interval'])
                await self._perform_parameter_optimization()

            except Exception as e:
                logger.error(f"❌ 파라미터 최적화 오류: {e}")

    async def _perform_parameter_optimization(self):
        """파라미터 최적화 수행"""
        try:
            if len(self.trigger_history) < 10:
                return  # 충분한 데이터 없음

            # 최근 성능 분석
            recent_triggers = list(self.trigger_history)[-50:]  # 최근 50개
            performance_metrics = self._analyze_performance(recent_triggers)

            # 목표 달성 여부 확인
            avg_processing_time = performance_metrics.get('avg_processing_time', 0)
            success_rate = performance_metrics.get('success_rate', 0)

            # 파라미터 조정
            if avg_processing_time > self.config['latency_target']:
                # 목표 지연시간 초과 - 더 적극적 트리거
                self.adaptive_params['base_threshold'] *= 0.95
                self.adaptive_params['urgency_multiplier'] *= 0.9
            elif avg_processing_time < self.config['latency_target'] * 0.7:
                # 목표보다 너무 빠름 - 품질 향상 가능
                self.adaptive_params['base_threshold'] *= 1.05
                self.adaptive_params['quality_weight'] *= 1.1

            if success_rate < 0.9:
                # 성공률 낮음 - 보수적 접근
                self.adaptive_params['quality_weight'] *= 1.2
                self.adaptive_params['load_sensitivity'] *= 1.1

            # 파라미터 범위 제한
            self.adaptive_params['base_threshold'] = max(2.0, min(15.0, self.adaptive_params['base_threshold']))
            self.adaptive_params['urgency_multiplier'] = max(0.3, min(2.0, self.adaptive_params['urgency_multiplier']))

            logger.debug(f"📊 파라미터 최적화 완료: {self.adaptive_params}")

        except Exception as e:
            logger.error(f"❌ 파라미터 최적화 수행 실패: {e}")

    def _analyze_performance(self, trigger_records: List[Dict]) -> Dict:
        """성능 분석"""
        try:
            if not trigger_records:
                return {}

            processing_times = [r.get('estimated_processing_time', 0) for r in trigger_records]
            success_indicators = [1.0 if r.get('confidence', 0) > 0.7 else 0.0 for r in trigger_records]

            return {
                'avg_processing_time': statistics.mean(processing_times) if processing_times else 0,
                'max_processing_time': max(processing_times) if processing_times else 0,
                'success_rate': statistics.mean(success_indicators) if success_indicators else 0,
                'trigger_frequency': len(trigger_records) / 300.0 if trigger_records else 0,  # per 5min
                'total_triggers': len(trigger_records)
            }

        except Exception as e:
            logger.error(f"❌ 성능 분석 실패: {e}")
            return {}

    async def get_optimization_metrics(self) -> Dict:
        """최적화 메트릭 조회"""
        try:
            recent_load = self.system_loads[-1] if self.system_loads else SystemLoad()
            avg_load = statistics.mean([load.overall_load for load in self.system_loads]) if self.system_loads else 0.0

            return {
                'current_system_load': recent_load.overall_load,
                'average_system_load': avg_load,
                'adaptive_parameters': self.adaptive_params.copy(),
                'trigger_history_size': len(self.trigger_history),
                'processing_metrics': {
                    'avg_processing_time': self.processing_metrics.get_average_processing_time(),
                    'success_rate': self.processing_metrics.get_success_rate(),
                    'optimal_batch_size': self.processing_metrics.get_optimal_batch_size()
                },
                'optimization_cache_size': len(self.optimization_cache)
            }

        except Exception as e:
            logger.error(f"❌ 최적화 메트릭 조회 실패: {e}")
            return {}

    def record_processing_result(self, task_id: str, processing_time: float,
                               success: bool, queue_wait: float = 0.0,
                               api_response: float = 0.0, batch_size: int = 1,
                               quality_score: float = 0.8):
        """처리 결과 기록"""
        try:
            self.processing_metrics.add_processing_record(
                processing_time, success, queue_wait, api_response, batch_size, quality_score
            )

            logger.debug(f"📊 처리 결과 기록: {task_id} - {processing_time:.2f}s")

        except Exception as e:
            logger.error(f"❌ 처리 결과 기록 실패: {task_id} - {e}")

    async def suggest_optimal_parameters(self, current_performance: Dict) -> Dict:
        """최적 파라미터 제안"""
        try:
            suggestions = {}

            current_latency = current_performance.get('avg_latency', 0)
            current_quality = current_performance.get('avg_quality', 0)
            current_cost = current_performance.get('avg_cost', 0)

            # 지연시간 최적화
            if current_latency > self.config['latency_target']:
                suggestions['base_threshold'] = max(2.0, self.adaptive_params['base_threshold'] * 0.9)
                suggestions['urgency_multiplier'] = max(0.3, self.adaptive_params['urgency_multiplier'] * 0.9)

            # 품질 최적화
            if current_quality < self.config['quality_threshold']:
                suggestions['quality_weight'] = min(1.0, self.adaptive_params['quality_weight'] * 1.2)

            # 비용 최적화
            if current_cost > 0.03:  # $0.03 임계값
                suggestions['cost_weight'] = min(1.0, self.adaptive_params['cost_weight'] * 1.1)

            return suggestions

        except Exception as e:
            logger.error(f"❌ 최적 파라미터 제안 실패: {e}")
            return {}