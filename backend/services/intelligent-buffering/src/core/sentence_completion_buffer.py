"""
문장 완성도 기반 지능형 버퍼링 시스템
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import asdict

from ..models.completion_models import (
    CompletionScore, CompletionLevel, TextChunk, BufferState,
    TriggerDecision, TriggerReason, ProcessingContext, AdaptiveThreshold,
    BufferMetrics, SentenceAnalysis
)
from ..utils.japanese_nlp import JapaneseNLPProcessor

logger = logging.getLogger(__name__)

class SentenceCompletionBuffer:
    """문장 완성도 기반 지능형 버퍼"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.nlp_processor = JapaneseNLPProcessor()

        # 설정 파라미터
        self.config = {
            'completion_threshold': 0.8,      # 기본 완성도 임계값
            'max_buffer_duration': 10.0,      # 최대 버퍼 시간 (초)
            'min_buffer_duration': 1.0,       # 최소 버퍼 시간 (초)
            'urgent_threshold': 4,             # 긴급 요청 임계값
            'quality_threshold': 0.7,          # 품질 임계값
            'max_chunk_count': 10,             # 최대 청크 개수
        }

        # 활성 버퍼들
        self.active_buffers: Dict[str, BufferState] = {}

        # 메트릭 수집
        self.metrics = BufferMetrics()

        logger.info("✅ SentenceCompletionBuffer 초기화 완료")

    async def add_chunk(self, task_id: str, chunk: TextChunk) -> Optional[TriggerDecision]:
        """
        새로운 텍스트 청크를 버퍼에 추가하고 트리거 여부 결정

        Args:
            task_id: 작업 ID
            chunk: 텍스트 청크

        Returns:
            TriggerDecision: 번역 트리거 결정 (None이면 계속 버퍼링)
        """
        try:
            logger.debug(f"📥 청크 추가: {task_id} - {chunk.text[:50]}...")

            # 버퍼 가져오기 또는 생성
            buffer_state = self._get_or_create_buffer(task_id)

            # 청크 추가
            buffer_state.chunks.append(chunk)
            buffer_state.last_update_time = time.time()
            buffer_state.total_duration = chunk.end_time - buffer_state.chunks[0].start_time

            # 완성도 분석
            completion_score = await self._analyze_completion(buffer_state)
            buffer_state.completion_scores.append(completion_score)

            # 트리거 결정
            decision = await self._make_trigger_decision(task_id, buffer_state)

            if decision.should_trigger:
                logger.info(f"🚀 번역 트리거: {task_id} - {decision.reason.value}")
                await self._process_trigger(task_id, buffer_state, decision)
                return decision

            logger.debug(f"⏳ 계속 버퍼링: {task_id} - 완성도: {completion_score.overall_score:.2f}")
            return None

        except Exception as e:
            logger.error(f"❌ 청크 추가 실패: {task_id} - {e}")
            return None

    def _get_or_create_buffer(self, task_id: str) -> BufferState:
        """버퍼 가져오기 또는 생성"""
        if task_id not in self.active_buffers:
            self.active_buffers[task_id] = BufferState()
            logger.debug(f"🆕 새 버퍼 생성: {task_id}")

        return self.active_buffers[task_id]

    async def _analyze_completion(self, buffer_state: BufferState) -> CompletionScore:
        """문장 완성도 분석"""
        try:
            combined_text = buffer_state.combined_text

            if not combined_text.strip():
                return CompletionScore(
                    overall_score=0.0,
                    punctuation_score=0.0,
                    grammar_score=0.0,
                    semantic_score=0.0,
                    confidence=1.0,
                    level=CompletionLevel.INCOMPLETE
                )

            # 각 요소별 점수 계산
            punctuation_score = self.nlp_processor.calculate_punctuation_score(combined_text)
            grammar_score = self.nlp_processor.calculate_grammar_completeness(combined_text)
            semantic_score = self.nlp_processor.calculate_semantic_completeness(combined_text)

            # 가중 평균으로 전체 점수 계산
            overall_score = (
                punctuation_score * 0.3 +
                grammar_score * 0.4 +
                semantic_score * 0.3
            )

            # 완성도 레벨 결정
            if overall_score >= 0.8:
                level = CompletionLevel.COMPLETE
            elif overall_score >= 0.6:
                level = CompletionLevel.MOSTLY_COMPLETE
            elif overall_score >= 0.3:
                level = CompletionLevel.PARTIAL
            else:
                level = CompletionLevel.INCOMPLETE

            # 신뢰도 계산 (청크 개수와 일관성 기반)
            confidence = self._calculate_confidence(buffer_state, overall_score)

            # 점수 산정 이유
            reasons = []
            if punctuation_score > 0.7:
                reasons.append("적절한_문장부호")
            if grammar_score > 0.7:
                reasons.append("완전한_문법구조")
            if semantic_score > 0.7:
                reasons.append("의미적_완성도")

            completion_score = CompletionScore(
                overall_score=overall_score,
                punctuation_score=punctuation_score,
                grammar_score=grammar_score,
                semantic_score=semantic_score,
                confidence=confidence,
                level=level,
                reasons=reasons
            )

            logger.debug(f"📊 완성도 분석: {overall_score:.2f} ({level.value})")
            return completion_score

        except Exception as e:
            logger.error(f"❌ 완성도 분석 실패: {e}")
            return CompletionScore(
                overall_score=0.0,
                punctuation_score=0.0,
                grammar_score=0.0,
                semantic_score=0.0,
                confidence=0.0,
                level=CompletionLevel.INCOMPLETE
            )

    def _calculate_confidence(self, buffer_state: BufferState, overall_score: float) -> float:
        """신뢰도 계산"""
        try:
            confidence = 0.5  # 기본값

            # 청크 개수 기반 조정 (더 많은 정보일수록 신뢰도 증가)
            chunk_count_factor = min(1.0, len(buffer_state.chunks) / 3.0)
            confidence += chunk_count_factor * 0.2

            # 점수 일관성 기반 조정
            if len(buffer_state.completion_scores) > 1:
                recent_scores = [score.overall_score for score in buffer_state.completion_scores[-3:]]
                score_variance = sum((score - overall_score) ** 2 for score in recent_scores) / len(recent_scores)
                consistency_factor = max(0.0, 1.0 - score_variance)
                confidence += consistency_factor * 0.3

            return min(1.0, confidence)

        except Exception:
            return 0.5

    async def _make_trigger_decision(self, task_id: str, buffer_state: BufferState) -> TriggerDecision:
        """트리거 결정 로직"""
        try:
            latest_completion = buffer_state.get_latest_completion_score()
            if not latest_completion:
                return TriggerDecision(
                    should_trigger=False,
                    reason=TriggerReason.SENTENCE_COMPLETE,
                    confidence=0.0,
                    estimated_processing_time=0.0
                )

            # 컨텍스트 구성
            context = ProcessingContext(
                task_id=task_id,
                buffer_state=buffer_state,
                system_load=await self._get_system_load(),
                urgency_level=buffer_state.priority,
                quality_requirement=0.8,
                cost_priority=0.5,
                latency_requirement=buffer_state.max_latency
            )

            # 적응형 임계값 계산
            adaptive_threshold = self._calculate_adaptive_threshold(context)

            # 트리거 조건 확인
            trigger_checks = [
                # 1. 문장 완성도 기반
                (latest_completion.overall_score >= self.config['completion_threshold'],
                 TriggerReason.SENTENCE_COMPLETE, latest_completion.confidence),

                # 2. 시간 임계값 기반
                (buffer_state.buffer_age >= adaptive_threshold.effective_threshold,
                 TriggerReason.TIME_THRESHOLD, 0.8),

                # 3. 버퍼 가득참
                (len(buffer_state.chunks) >= self.config['max_chunk_count'],
                 TriggerReason.BUFFER_FULL, 0.9),

                # 4. 긴급 요청
                (context.urgency_level >= self.config['urgent_threshold'],
                 TriggerReason.URGENT_REQUEST, 1.0),

                # 5. 최대 버퍼 시간 초과
                (buffer_state.buffer_age >= self.config['max_buffer_duration'],
                 TriggerReason.TIME_THRESHOLD, 1.0)
            ]

            # 첫 번째로 만족하는 조건 선택
            for should_trigger, reason, confidence in trigger_checks:
                if should_trigger:
                    estimated_time = await self._estimate_processing_time(buffer_state)
                    return TriggerDecision(
                        should_trigger=True,
                        reason=reason,
                        confidence=confidence,
                        estimated_processing_time=estimated_time,
                        recommended_batch_size=len(buffer_state.chunks),
                        additional_info={
                            'completion_score': latest_completion.overall_score,
                            'buffer_age': buffer_state.buffer_age,
                            'chunk_count': len(buffer_state.chunks),
                            'adaptive_threshold': adaptive_threshold.effective_threshold
                        }
                    )

            # 트리거 조건 불만족
            return TriggerDecision(
                should_trigger=False,
                reason=TriggerReason.SENTENCE_COMPLETE,
                confidence=latest_completion.confidence,
                estimated_processing_time=0.0
            )

        except Exception as e:
            logger.error(f"❌ 트리거 결정 실패: {task_id} - {e}")
            return TriggerDecision(
                should_trigger=True,  # 오류 시 안전을 위해 트리거
                reason=TriggerReason.TIME_THRESHOLD,
                confidence=0.5,
                estimated_processing_time=5.0
            )

    def _calculate_adaptive_threshold(self, context: ProcessingContext) -> AdaptiveThreshold:
        """적응형 임계값 계산"""
        try:
            threshold = AdaptiveThreshold()

            # 긴급도에 따른 조정
            if context.urgency_level >= 4:
                threshold.urgency_multiplier = 0.5  # 빠른 처리
            elif context.urgency_level >= 3:
                threshold.urgency_multiplier = 0.8
            else:
                threshold.urgency_multiplier = 1.0

            # 시스템 부하에 따른 조정
            if context.system_load > 0.8:
                threshold.load_adjustment = 2.0  # 부하 높으면 대기
            elif context.system_load > 0.6:
                threshold.load_adjustment = 1.0
            else:
                threshold.load_adjustment = -0.5  # 부하 낮으면 빠른 처리

            # 품질 요구사항에 따른 조정
            if context.quality_requirement > 0.9:
                threshold.quality_adjustment = 1.0  # 높은 품질은 더 대기
            elif context.quality_requirement < 0.7:
                threshold.quality_adjustment = -1.0  # 낮은 품질은 빠른 처리

            return threshold

        except Exception as e:
            logger.error(f"❌ 적응형 임계값 계산 실패: {e}")
            return AdaptiveThreshold()

    async def _get_system_load(self) -> float:
        """시스템 부하 조회"""
        try:
            if self.redis_client:
                load_data = await self.redis_client.get("system_load")
                if load_data:
                    return float(load_data)

            # 기본값 반환
            return 0.5

        except Exception:
            return 0.5

    async def _estimate_processing_time(self, buffer_state: BufferState) -> float:
        """처리 시간 예측"""
        try:
            # 기본 처리 시간 (청크당 0.5초)
            base_time = len(buffer_state.chunks) * 0.5

            # 텍스트 길이에 따른 조정
            total_length = len(buffer_state.combined_text)
            length_factor = min(2.0, total_length / 100.0)

            # 복잡도에 따른 조정
            complexity_factor = 1.0
            if any(chunk.confidence < 0.8 for chunk in buffer_state.chunks):
                complexity_factor = 1.5

            estimated_time = base_time * length_factor * complexity_factor
            return max(1.0, min(30.0, estimated_time))  # 1-30초 범위

        except Exception:
            return 5.0  # 기본값

    async def _process_trigger(self, task_id: str, buffer_state: BufferState,
                             decision: TriggerDecision):
        """트리거 처리"""
        try:
            # 메트릭 업데이트
            latest_completion = buffer_state.get_latest_completion_score()
            completion_score = latest_completion.overall_score if latest_completion else 0.0

            self.metrics.update_metrics(
                completion_score=completion_score,
                buffer_duration=buffer_state.buffer_age,
                trigger_reason=decision.reason,
                processing_time=decision.estimated_processing_time
            )

            # Redis에 트리거 정보 저장
            if self.redis_client:
                trigger_data = {
                    'task_id': task_id,
                    'trigger_reason': decision.reason.value,
                    'completion_score': completion_score,
                    'chunks': [asdict(chunk) for chunk in buffer_state.chunks],
                    'estimated_processing_time': decision.estimated_processing_time,
                    'timestamp': time.time()
                }

                await self.redis_client.setex(
                    f"trigger:{task_id}",
                    3600,  # 1시간 TTL
                    json.dumps(trigger_data, ensure_ascii=False)
                )

            # 버퍼 정리
            if task_id in self.active_buffers:
                del self.active_buffers[task_id]

            logger.info(f"✅ 트리거 처리 완료: {task_id}")

        except Exception as e:
            logger.error(f"❌ 트리거 처리 실패: {task_id} - {e}")

    async def get_buffer_status(self, task_id: str) -> Optional[Dict]:
        """버퍼 상태 조회"""
        try:
            if task_id not in self.active_buffers:
                return None

            buffer_state = self.active_buffers[task_id]
            latest_completion = buffer_state.get_latest_completion_score()

            return {
                'task_id': task_id,
                'chunk_count': len(buffer_state.chunks),
                'buffer_age': buffer_state.buffer_age,
                'total_duration': buffer_state.total_duration,
                'combined_text_length': len(buffer_state.combined_text),
                'latest_completion_score': latest_completion.overall_score if latest_completion else 0.0,
                'is_processing': buffer_state.is_processing,
                'priority': buffer_state.priority
            }

        except Exception as e:
            logger.error(f"❌ 버퍼 상태 조회 실패: {task_id} - {e}")
            return None

    async def get_metrics(self) -> Dict:
        """메트릭 조회"""
        try:
            metrics_dict = asdict(self.metrics)
            metrics_dict['active_buffers'] = len(self.active_buffers)
            metrics_dict['average_processing_time'] = (
                sum(self.metrics.processing_times) / len(self.metrics.processing_times)
                if self.metrics.processing_times else 0.0
            )

            return metrics_dict

        except Exception as e:
            logger.error(f"❌ 메트릭 조회 실패: {e}")
            return {}

    def get_combined_text(self, task_id: str) -> str:
        """현재 버퍼의 결합 텍스트 조회"""
        try:
            if task_id not in self.active_buffers:
                return ""
            buffer_state = self.active_buffers[task_id]
            return buffer_state.combined_text
        except Exception:
            return ""

    async def force_trigger(self, task_id: str, reason: str = "manual") -> bool:
        """강제 트리거"""
        try:
            if task_id not in self.active_buffers:
                return False

            buffer_state = self.active_buffers[task_id]

            decision = TriggerDecision(
                should_trigger=True,
                reason=TriggerReason.URGENT_REQUEST,
                confidence=1.0,
                estimated_processing_time=await self._estimate_processing_time(buffer_state),
                additional_info={'force_reason': reason}
            )

            await self._process_trigger(task_id, buffer_state, decision)
            logger.info(f"🔥 강제 트리거 완료: {task_id} - {reason}")
            return True

        except Exception as e:
            logger.error(f"❌ 강제 트리거 실패: {task_id} - {e}")
            return False

    def cleanup_old_buffers(self, max_age: float = 300.0):
        """오래된 버퍼 정리"""
        try:
            current_time = time.time()
            to_remove = []

            for task_id, buffer_state in self.active_buffers.items():
                if current_time - buffer_state.buffer_start_time > max_age:
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self.active_buffers[task_id]
                logger.info(f"🧹 오래된 버퍼 정리: {task_id}")

            return len(to_remove)

        except Exception as e:
            logger.error(f"❌ 버퍼 정리 실패: {e}")
            return 0
