"""
문장 완성도 및 버퍼링 관련 데이터 모델
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import time

class CompletionLevel(Enum):
    """문장 완성도 레벨"""
    INCOMPLETE = "incomplete"      # 미완성 (0.0-0.3)
    PARTIAL = "partial"           # 부분 완성 (0.3-0.6)
    MOSTLY_COMPLETE = "mostly"    # 대부분 완성 (0.6-0.8)
    COMPLETE = "complete"         # 완성 (0.8-1.0)

class TriggerReason(Enum):
    """번역 트리거 이유"""
    SENTENCE_COMPLETE = "sentence_complete"
    TIME_THRESHOLD = "time_threshold"
    BUFFER_FULL = "buffer_full"
    URGENT_REQUEST = "urgent_request"
    SPEAKER_CHANGE = "speaker_change"
    TOPIC_CHANGE = "topic_change"

@dataclass
class CompletionScore:
    """문장 완성도 점수"""
    overall_score: float  # 전체 완성도 점수 (0.0-1.0)
    punctuation_score: float  # 문장 부호 점수
    grammar_score: float      # 문법적 완성도 점수
    semantic_score: float     # 의미적 완성도 점수
    confidence: float         # 신뢰도
    level: CompletionLevel    # 완성도 레벨
    reasons: List[str] = field(default_factory=list)  # 점수 산정 이유

    def is_ready_for_translation(self) -> bool:
        """번역 준비 여부"""
        return self.overall_score >= 0.8 or self.level == CompletionLevel.COMPLETE

@dataclass
class TextChunk:
    """텍스트 청크"""
    text: str
    start_time: float
    end_time: float
    chunk_id: str
    confidence: float = 0.0
    speaker_id: Optional[str] = None
    processing_time: float = 0.0
    created_at: float = field(default_factory=time.time)

@dataclass
class BufferState:
    """버퍼 상태"""
    chunks: List[TextChunk] = field(default_factory=list)
    total_duration: float = 0.0
    buffer_start_time: float = field(default_factory=time.time)
    last_update_time: float = field(default_factory=time.time)
    completion_scores: List[CompletionScore] = field(default_factory=list)
    is_processing: bool = False
    priority: int = 1
    max_latency: float = 10.0

    @property
    def buffer_age(self) -> float:
        """버퍼 나이 (초)"""
        return time.time() - self.buffer_start_time

    @property
    def combined_text(self) -> str:
        """결합된 텍스트"""
        return "".join(chunk.text for chunk in self.chunks)

    @property
    def chunk_count(self) -> int:
        """청크 개수"""
        return len(self.chunks)

    def get_latest_completion_score(self) -> Optional[CompletionScore]:
        """최신 완성도 점수"""
        return self.completion_scores[-1] if self.completion_scores else None

@dataclass
class TriggerDecision:
    """트리거 결정"""
    should_trigger: bool
    reason: TriggerReason
    confidence: float
    estimated_processing_time: float
    recommended_batch_size: int = 1
    additional_info: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProcessingContext:
    """처리 컨텍스트"""
    task_id: str
    buffer_state: BufferState
    system_load: float  # 0.0-1.0
    urgency_level: int  # 1-5
    quality_requirement: float  # 0.0-1.0
    cost_priority: float  # 0.0-1.0 (높을수록 비용 중시)
    latency_requirement: float  # 최대 허용 지연시간 (초)
    current_metrics: Dict[str, float] = field(default_factory=dict)

@dataclass
class SentenceAnalysis:
    """문장 분석 결과"""
    text: str
    morphemes: List[Dict]  # 형태소 분석 결과
    dependencies: List[Dict]  # 의존 구문 분석
    entities: List[Dict]  # 개체명 인식
    sentiment: float  # 감정 점수
    complexity: float  # 문장 복잡도
    topic_keywords: List[str]  # 주제 키워드
    grammar_issues: List[str]  # 문법 문제점
    completeness_indicators: Dict[str, bool]  # 완성도 지표

@dataclass
class AdaptiveThreshold:
    """적응형 임계값"""
    base_threshold: float = 5.0  # 기본 임계값 (초)
    urgency_multiplier: float = 1.0  # 긴급도 배수
    load_adjustment: float = 0.0  # 부하 조정값
    quality_adjustment: float = 0.0  # 품질 조정값

    @property
    def effective_threshold(self) -> float:
        """실효 임계값"""
        return max(1.0, self.base_threshold * self.urgency_multiplier +
                  self.load_adjustment + self.quality_adjustment)

@dataclass
class BufferMetrics:
    """버퍼 메트릭"""
    total_chunks_processed: int = 0
    average_completion_score: float = 0.0
    average_buffer_duration: float = 0.0
    trigger_reason_counts: Dict[TriggerReason, int] = field(default_factory=dict)
    processing_times: List[float] = field(default_factory=list)
    quality_scores: List[float] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def update_metrics(self, completion_score: float, buffer_duration: float,
                      trigger_reason: TriggerReason, processing_time: float):
        """메트릭 업데이트"""
        self.total_chunks_processed += 1

        # 평균 계산
        count = self.total_chunks_processed
        self.average_completion_score = (
            (self.average_completion_score * (count - 1) + completion_score) / count
        )
        self.average_buffer_duration = (
            (self.average_buffer_duration * (count - 1) + buffer_duration) / count
        )

        # 트리거 이유 카운트
        if trigger_reason not in self.trigger_reason_counts:
            self.trigger_reason_counts[trigger_reason] = 0
        self.trigger_reason_counts[trigger_reason] += 1

        # 처리 시간 기록
        self.processing_times.append(processing_time)
        if len(self.processing_times) > 100:  # 최근 100개만 유지
            self.processing_times.pop(0)