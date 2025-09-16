"""
문맥 분석 관련 데이터 모델
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import time

class TopicChangeType(Enum):
    """주제 변경 유형"""
    NONE = "none"                # 변경 없음
    GRADUAL = "gradual"          # 점진적 변경
    SUDDEN = "sudden"            # 급격한 변경
    RETURN = "return"            # 이전 주제로 복귀

class SpeakerChangeConfidence(Enum):
    """화자 변경 신뢰도"""
    LOW = "low"                  # 낮음 (0.0-0.4)
    MEDIUM = "medium"            # 보통 (0.4-0.7)
    HIGH = "high"                # 높음 (0.7-1.0)

@dataclass
class TopicVector:
    """주제 벡터"""
    keywords: List[str]
    embeddings: Optional[List[float]] = None
    weight: float = 1.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class TopicAnalysis:
    """주제 분석 결과"""
    current_topic: TopicVector
    previous_topics: List[TopicVector] = field(default_factory=list)
    continuity_score: float = 0.0      # 연속성 점수 (0.0-1.0)
    change_type: TopicChangeType = TopicChangeType.NONE
    confidence: float = 0.0             # 분석 신뢰도
    transition_keywords: List[str] = field(default_factory=list)

    def is_topic_stable(self) -> bool:
        """주제가 안정적인지 확인"""
        return (self.continuity_score > 0.7 and
                self.change_type in [TopicChangeType.NONE, TopicChangeType.GRADUAL])

@dataclass
class AudioFeatures:
    """오디오 특성"""
    pitch_mean: float = 0.0         # 평균 피치
    pitch_variance: float = 0.0     # 피치 분산
    energy_mean: float = 0.0        # 평균 에너지
    energy_variance: float = 0.0    # 에너지 분산
    spectral_centroid: float = 0.0  # 스펙트럴 센트로이드
    zero_crossing_rate: float = 0.0 # 영교차율
    mfcc_features: List[float] = field(default_factory=list)  # MFCC 특성

@dataclass
class SpeakerChange:
    """화자 변경 정보"""
    timestamp: float                    # 변경 시점
    confidence: float                   # 신뢰도 (0.0-1.0)
    confidence_level: SpeakerChangeConfidence
    audio_features_diff: float = 0.0   # 오디오 특성 차이
    pause_duration: float = 0.0        # 발화 전 정지 시간
    volume_change: float = 0.0         # 볼륨 변화

    def is_reliable_change(self) -> bool:
        """신뢰할 만한 화자 변경인지 확인"""
        return (self.confidence > 0.7 and
                self.confidence_level == SpeakerChangeConfidence.HIGH)

@dataclass
class TerminologyEntry:
    """전문 용어 항목"""
    term: str                           # 용어
    translation: str                    # 번역
    frequency: int = 1                  # 사용 빈도
    context: List[str] = field(default_factory=list)  # 사용 문맥
    confidence: float = 1.0             # 번역 신뢰도
    last_used: float = field(default_factory=time.time)
    domain: Optional[str] = None        # 전문 분야

@dataclass
class ContextualSegment:
    """문맥적 세그먼트"""
    text: str
    start_time: float
    end_time: float
    topic_analysis: Optional[TopicAnalysis] = None
    speaker_id: Optional[str] = None
    speaker_confidence: float = 0.0
    terminology: List[TerminologyEntry] = field(default_factory=list)
    semantic_embedding: Optional[List[float]] = None

    @property
    def duration(self) -> float:
        """세그먼트 길이"""
        return self.end_time - self.start_time

@dataclass
class ContextWindow:
    """문맥 윈도우"""
    segments: List[ContextualSegment] = field(default_factory=list)
    window_duration: float = 30.0      # 윈도우 크기 (초)
    overlap_duration: float = 5.0      # 오버랩 크기 (초)

    def get_recent_segments(self, max_age: float = None) -> List[ContextualSegment]:
        """최근 세그먼트 조회"""
        if max_age is None:
            max_age = self.window_duration

        current_time = time.time()
        return [
            segment for segment in self.segments
            if current_time - segment.end_time <= max_age
        ]

    def get_dominant_topic(self) -> Optional[TopicVector]:
        """지배적 주제 추출"""
        if not self.segments:
            return None

        # 최근 세그먼트들의 주제 분석
        recent_segments = self.get_recent_segments()
        topic_keywords = []

        for segment in recent_segments:
            if segment.topic_analysis and segment.topic_analysis.current_topic:
                topic_keywords.extend(segment.topic_analysis.current_topic.keywords)

        # 키워드 빈도 계산
        from collections import Counter
        keyword_freq = Counter(topic_keywords)

        if keyword_freq:
            dominant_keywords = [kw for kw, freq in keyword_freq.most_common(5)]
            return TopicVector(keywords=dominant_keywords)

        return None

@dataclass
class ContextAnalysisResult:
    """문맥 분석 종합 결과"""
    topic_continuity: float             # 주제 연속성 (0.0-1.0)
    speaker_stability: float            # 화자 안정성 (0.0-1.0)
    terminology_consistency: float      # 용어 일관성 (0.0-1.0)
    overall_context_score: float        # 전체 문맥 점수 (0.0-1.0)

    # 상세 분석 결과
    topic_analysis: Optional[TopicAnalysis] = None
    speaker_changes: List[SpeakerChange] = field(default_factory=list)
    terminology_entries: List[TerminologyEntry] = field(default_factory=list)

    # 추천 사항
    should_wait_for_completion: bool = False    # 완성까지 대기 여부
    recommended_buffer_time: float = 5.0       # 권장 버퍼링 시간
    context_importance: float = 0.5             # 문맥 중요도

    def get_context_quality(self) -> str:
        """문맥 품질 평가"""
        if self.overall_context_score >= 0.8:
            return "excellent"
        elif self.overall_context_score >= 0.6:
            return "good"
        elif self.overall_context_score >= 0.4:
            return "fair"
        else:
            return "poor"

@dataclass
class TranslationMemoryEntry:
    """번역 메모리 항목"""
    source_text: str
    target_text: str
    context_keywords: List[str] = field(default_factory=list)
    domain: Optional[str] = None
    confidence: float = 1.0
    usage_count: int = 1
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def is_contextually_relevant(self, current_keywords: List[str],
                               threshold: float = 0.3) -> bool:
        """현재 문맥과의 관련성 확인"""
        if not self.context_keywords or not current_keywords:
            return False

        # 키워드 교집합 비율 계산
        common_keywords = set(self.context_keywords) & set(current_keywords)
        relevance_ratio = len(common_keywords) / len(set(self.context_keywords))

        return relevance_ratio >= threshold

@dataclass
class ContextCacheEntry:
    """문맥 캐시 항목"""
    cache_key: str
    analysis_result: ContextAnalysisResult
    context_window: ContextWindow
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    ttl: float = 300.0  # 5분 TTL

    def is_expired(self) -> bool:
        """캐시 만료 여부"""
        return time.time() - self.created_at > self.ttl

    def update_access(self):
        """접근 시간 업데이트"""
        self.access_count += 1