"""
문맥 분석 시스템 - 주제 연속성 및 화자 패턴 분석
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Optional, Tuple, Set
from collections import Counter, defaultdict
from dataclasses import asdict
import numpy as np

from ..models.context_models import (
    TopicVector, TopicAnalysis, TopicChangeType, ContextualSegment,
    ContextWindow, ContextAnalysisResult, TerminologyEntry,
    TranslationMemoryEntry, SpeakerChange, ContextCacheEntry
)
from ..models.completion_models import TextChunk
from ..utils.japanese_nlp import JapaneseNLPProcessor
from ..utils.audio_analysis import AudioAnalyzer

logger = logging.getLogger(__name__)

class ContextAnalyzer:
    """문맥 분석 시스템"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.nlp_processor = JapaneseNLPProcessor()
        self.audio_analyzer = AudioAnalyzer()

        # 설정
        self.config = {
            'context_window_duration': 30.0,      # 문맥 윈도우 크기 (초)
            'topic_similarity_threshold': 0.6,    # 주제 유사도 임계값
            'terminology_confidence_threshold': 0.8,  # 용어 신뢰도 임계값
            'speaker_change_threshold': 0.7,      # 화자 변경 임계값
            'max_terminology_entries': 1000,      # 최대 용어 항목
            'cache_ttl': 300,                     # 캐시 TTL (초)
        }

        # 상태 관리
        self.context_windows: Dict[str, ContextWindow] = {}
        self.terminology_cache: Dict[str, TerminologyEntry] = {}
        self.translation_memory: List[TranslationMemoryEntry] = []
        self.context_cache: Dict[str, ContextCacheEntry] = {}

        logger.info("✅ ContextAnalyzer 초기화 완료")

    async def analyze_context(self, task_id: str, segments: List[ContextualSegment]) -> ContextAnalysisResult:
        """종합 문맥 분석"""
        try:
            logger.debug(f"🔍 문맥 분석 시작: {task_id}")

            # 캐시 확인
            cache_key = self._generate_cache_key(task_id, segments)
            cached_result = await self._get_cached_analysis(cache_key)
            if cached_result:
                logger.debug(f"💾 캐시된 분석 결과 사용: {task_id}")
                return cached_result

            # 문맥 윈도우 업데이트
            context_window = self._update_context_window(task_id, segments)

            # 각 영역별 분석
            topic_analysis = await self._analyze_topic_continuity(segments)
            speaker_analysis = await self._analyze_speaker_stability(segments)
            terminology_analysis = await self._analyze_terminology_consistency(segments)

            # 종합 점수 계산
            overall_score = self._calculate_overall_context_score(
                topic_analysis, speaker_analysis, terminology_analysis
            )

            # 결과 구성
            result = ContextAnalysisResult(
                topic_continuity=topic_analysis.get('continuity_score', 0.0),
                speaker_stability=speaker_analysis.get('stability_score', 0.0),
                terminology_consistency=terminology_analysis.get('consistency_score', 0.0),
                overall_context_score=overall_score,
                topic_analysis=topic_analysis.get('analysis'),
                speaker_changes=speaker_analysis.get('changes', []),
                terminology_entries=terminology_analysis.get('entries', []),
                should_wait_for_completion=self._should_wait_for_completion(overall_score),
                recommended_buffer_time=self._calculate_recommended_buffer_time(overall_score),
                context_importance=self._calculate_context_importance(topic_analysis, speaker_analysis)
            )

            # 캐시 저장
            await self._cache_analysis_result(cache_key, result, context_window)

            logger.debug(f"✅ 문맥 분석 완료: {task_id} - 점수: {overall_score:.2f}")
            return result

        except Exception as e:
            logger.error(f"❌ 문맥 분석 실패: {task_id} - {e}")
            return self._create_fallback_result()

    def _update_context_window(self, task_id: str, segments: List[ContextualSegment]) -> ContextWindow:
        """문맥 윈도우 업데이트"""
        try:
            if task_id not in self.context_windows:
                self.context_windows[task_id] = ContextWindow()

            window = self.context_windows[task_id]

            # 새 세그먼트 추가
            for segment in segments:
                if segment not in window.segments:
                    window.segments.append(segment)

            # 오래된 세그먼트 제거
            current_time = time.time()
            window.segments = [
                seg for seg in window.segments
                if current_time - seg.end_time <= window.window_duration
            ]

            # 시간순 정렬
            window.segments.sort(key=lambda s: s.start_time)

            return window

        except Exception as e:
            logger.error(f"❌ 문맥 윈도우 업데이트 실패: {task_id} - {e}")
            return ContextWindow()

    async def _analyze_topic_continuity(self, segments: List[ContextualSegment]) -> Dict:
        """주제 연속성 분석"""
        try:
            if len(segments) < 2:
                return {
                    'continuity_score': 1.0,
                    'analysis': TopicAnalysis(
                        current_topic=TopicVector(keywords=[]),
                        continuity_score=1.0,
                        change_type=TopicChangeType.NONE
                    )
                }

            topic_vectors = []

            # 각 세그먼트의 주제 벡터 추출
            for segment in segments:
                keywords = self.nlp_processor.extract_topic_keywords(segment.text, top_k=5)
                if keywords:
                    topic_vectors.append(TopicVector(
                        keywords=keywords,
                        timestamp=segment.end_time
                    ))

            if not topic_vectors:
                return {'continuity_score': 0.5, 'analysis': None}

            # 주제 연속성 계산
            continuity_scores = []
            change_type = TopicChangeType.NONE

            for i in range(1, len(topic_vectors)):
                similarity = self._calculate_topic_similarity(
                    topic_vectors[i-1], topic_vectors[i]
                )
                continuity_scores.append(similarity)

                # 변경 유형 감지
                if similarity < 0.3:
                    change_type = TopicChangeType.SUDDEN
                elif similarity < 0.6:
                    change_type = TopicChangeType.GRADUAL

            overall_continuity = np.mean(continuity_scores) if continuity_scores else 1.0

            # 최신 주제 분석
            current_topic = topic_vectors[-1] if topic_vectors else TopicVector(keywords=[])
            previous_topics = topic_vectors[:-1] if len(topic_vectors) > 1 else []

            # 전환 키워드 추출
            transition_keywords = self._extract_transition_keywords(segments)

            analysis = TopicAnalysis(
                current_topic=current_topic,
                previous_topics=previous_topics,
                continuity_score=overall_continuity,
                change_type=change_type,
                confidence=min(1.0, len(topic_vectors) / 3.0),  # 데이터량 기반 신뢰도
                transition_keywords=transition_keywords
            )

            return {
                'continuity_score': overall_continuity,
                'analysis': analysis
            }

        except Exception as e:
            logger.error(f"❌ 주제 연속성 분석 실패: {e}")
            return {'continuity_score': 0.5, 'analysis': None}

    def _calculate_topic_similarity(self, topic1: TopicVector, topic2: TopicVector) -> float:
        """주제 벡터 간 유사도 계산"""
        try:
            if not topic1.keywords or not topic2.keywords:
                return 0.0

            # 키워드 교집합 기반 유사도
            set1 = set(topic1.keywords)
            set2 = set(topic2.keywords)

            intersection = set1 & set2
            union = set1 | set2

            # Jaccard 유사도
            jaccard_similarity = len(intersection) / len(union) if union else 0.0

            # 순서 가중치 (앞쪽 키워드에 높은 가중치)
            order_weighted_similarity = 0.0
            for i, keyword in enumerate(topic1.keywords):
                if keyword in topic2.keywords:
                    weight = 1.0 / (i + 1)  # 순서 기반 가중치
                    order_weighted_similarity += weight

            # 정규화
            max_order_weight = sum(1.0 / (i + 1) for i in range(len(topic1.keywords)))
            if max_order_weight > 0:
                order_weighted_similarity /= max_order_weight

            # 최종 유사도 (Jaccard 70% + 순서 가중치 30%)
            final_similarity = jaccard_similarity * 0.7 + order_weighted_similarity * 0.3

            return min(1.0, final_similarity)

        except Exception as e:
            logger.error(f"❌ 주제 유사도 계산 실패: {e}")
            return 0.0

    def _extract_transition_keywords(self, segments: List[ContextualSegment]) -> List[str]:
        """전환 키워드 추출"""
        try:
            transition_patterns = [
                # 주제 전환 표현
                'ところで', 'さて', 'それでは', 'それから', 'それで',
                '次に', '続いて', 'さらに', 'また', 'そして',
                # 대조 표현
                'しかし', 'でも', 'ところが', '一方', 'けれども',
                # 결론 표현
                'つまり', 'すなわち', '要するに', '結局', 'したがって'
            ]

            found_transitions = []
            for segment in segments:
                for pattern in transition_patterns:
                    if pattern in segment.text:
                        found_transitions.append(pattern)

            return list(set(found_transitions))

        except Exception:
            return []

    async def _analyze_speaker_stability(self, segments: List[ContextualSegment]) -> Dict:
        """화자 안정성 분석"""
        try:
            if len(segments) < 2:
                return {
                    'stability_score': 1.0,
                    'changes': []
                }

            speaker_changes = []
            speaker_consistency_scores = []

            # 화자 ID 기반 분석
            speaker_ids = [seg.speaker_id for seg in segments if seg.speaker_id]
            if speaker_ids:
                # 화자 변경 횟수 기반 안정성
                unique_speakers = len(set(speaker_ids))
                change_rate = (unique_speakers - 1) / len(segments)
                stability_from_ids = max(0.0, 1.0 - change_rate * 2)
                speaker_consistency_scores.append(stability_from_ids)

            # 오디오 특성 기반 분석 (가상의 데이터 사용)
            # 실제로는 오디오 데이터가 필요하지만, 여기서는 시뮬레이션
            for i in range(1, len(segments)):
                prev_segment = segments[i-1]
                curr_segment = segments[i]

                # 화자 신뢰도 기반 변경 감지
                if (prev_segment.speaker_confidence > 0.7 and
                    curr_segment.speaker_confidence > 0.7 and
                    prev_segment.speaker_id != curr_segment.speaker_id):

                    change = SpeakerChange(
                        timestamp=curr_segment.start_time,
                        confidence=min(prev_segment.speaker_confidence, curr_segment.speaker_confidence),
                        confidence_level=self._determine_confidence_level(
                            min(prev_segment.speaker_confidence, curr_segment.speaker_confidence)
                        )
                    )
                    speaker_changes.append(change)

                # 연속성 점수 계산
                if prev_segment.speaker_id and curr_segment.speaker_id:
                    if prev_segment.speaker_id == curr_segment.speaker_id:
                        speaker_consistency_scores.append(1.0)
                    else:
                        speaker_consistency_scores.append(0.0)

            # 전체 안정성 점수
            if speaker_consistency_scores:
                stability_score = np.mean(speaker_consistency_scores)
            else:
                stability_score = 0.8  # 기본값 (정보 부족시)

            return {
                'stability_score': stability_score,
                'changes': speaker_changes
            }

        except Exception as e:
            logger.error(f"❌ 화자 안정성 분석 실패: {e}")
            return {'stability_score': 0.5, 'changes': []}

    def _determine_confidence_level(self, confidence: float):
        """신뢰도 레벨 결정"""
        from ..models.context_models import SpeakerChangeConfidence

        if confidence >= 0.7:
            return SpeakerChangeConfidence.HIGH
        elif confidence >= 0.4:
            return SpeakerChangeConfidence.MEDIUM
        else:
            return SpeakerChangeConfidence.LOW

    async def _analyze_terminology_consistency(self, segments: List[ContextualSegment]) -> Dict:
        """전문 용어 일관성 분석"""
        try:
            terminology_entries = []
            consistency_scores = []
            term_translations = defaultdict(list)

            # 각 세그먼트에서 전문 용어 추출 및 분석
            for segment in segments:
                # 기존 용어 매칭
                segment_terms = self._extract_technical_terms(segment.text)

                for term in segment_terms:
                    # 캐시된 번역 확인
                    if term in self.terminology_cache:
                        cached_entry = self.terminology_cache[term]
                        cached_entry.frequency += 1
                        cached_entry.last_used = time.time()
                        terminology_entries.append(cached_entry)
                    else:
                        # 새 용어 항목 생성
                        new_entry = TerminologyEntry(
                            term=term,
                            translation=await self._get_term_translation(term, segment.text),
                            context=[segment.text[:100]],  # 첫 100자만 저장
                            domain=self._detect_domain(segment.text)
                        )
                        terminology_entries.append(new_entry)
                        self.terminology_cache[term] = new_entry

            # 번역 일관성 분석
            for entry in terminology_entries:
                term_translations[entry.term].append(entry.translation)

            # 일관성 점수 계산
            for term, translations in term_translations.items():
                unique_translations = set(translations)
                if len(translations) > 1:
                    consistency = 1.0 - (len(unique_translations) - 1) / len(translations)
                    consistency_scores.append(consistency)
                else:
                    consistency_scores.append(1.0)

            # 전체 일관성 점수
            overall_consistency = np.mean(consistency_scores) if consistency_scores else 1.0

            # 캐시 크기 관리
            self._manage_terminology_cache()

            return {
                'consistency_score': overall_consistency,
                'entries': terminology_entries
            }

        except Exception as e:
            logger.error(f"❌ 전문 용어 일관성 분석 실패: {e}")
            return {'consistency_score': 0.8, 'entries': []}

    def _extract_technical_terms(self, text: str) -> List[str]:
        """전문 용어 추출"""
        try:
            # 형태소 분석을 통한 전문 용어 후보 추출
            morphemes = self.nlp_processor.analyze_morphemes(text)

            technical_terms = []
            for morpheme in morphemes:
                surface = morpheme.get('surface', '')
                pos = morpheme.get('part_of_speech', '')

                # 전문 용어 패턴 확인
                if (len(surface) >= 3 and  # 3글자 이상
                    pos in ['NOUN', '명사'] and
                    self._is_technical_term_pattern(surface)):
                    technical_terms.append(surface)

            return technical_terms

        except Exception as e:
            logger.error(f"❌ 전문 용어 추출 실패: {e}")
            return []

    def _is_technical_term_pattern(self, term: str) -> bool:
        """전문 용어 패턴 확인"""
        try:
            # 기술/과학 용어 패턴
            technical_patterns = [
                r'.*システム$',    # 시스템
                r'.*技術$',        # 기술
                r'.*プロセス$',    # 프로세스
                r'.*アルゴリズム$', # 알고리즘
                r'.*プログラム$',   # 프로그램
                r'.*データ.*',     # 데이터
                r'.*ネットワーク$', # 네트워크
                r'.*インターフェース$', # 인터페이스
            ]

            import re
            for pattern in technical_patterns:
                if re.match(pattern, term):
                    return True

            # 영어/카타카나 조합
            if any(char in term for char in 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン'):
                return True

            return False

        except Exception:
            return False

    async def _get_term_translation(self, term: str, context: str) -> str:
        """용어 번역 조회/생성"""
        try:
            # 번역 메모리 검색
            for entry in self.translation_memory:
                if (entry.source_text == term and
                    entry.is_contextually_relevant(
                        self.nlp_processor.extract_topic_keywords(context)
                    )):
                    entry.usage_count += 1
                    entry.last_used = time.time()
                    return entry.target_text

            # 기본 번역 (실제로는 번역 API 호출)
            # 여기서는 간단한 매핑 사용
            basic_translations = {
                'システム': '시스템',
                'データ': '데이터',
                'プロセス': '프로세스',
                'アルゴリズム': '알고리즘',
                'プログラム': '프로그램',
                'ネットワーク': '네트워크',
                'インターフェース': '인터페이스'
            }

            translation = basic_translations.get(term, term)  # 번역 없으면 원문 유지

            # 번역 메모리에 추가
            memory_entry = TranslationMemoryEntry(
                source_text=term,
                target_text=translation,
                context_keywords=self.nlp_processor.extract_topic_keywords(context),
                domain=self._detect_domain(context)
            )
            self.translation_memory.append(memory_entry)

            return translation

        except Exception as e:
            logger.error(f"❌ 용어 번역 조회 실패: {term} - {e}")
            return term

    def _detect_domain(self, text: str) -> Optional[str]:
        """전문 분야 감지"""
        try:
            domain_keywords = {
                'technology': ['技術', 'システム', 'プログラム', 'データ', 'ネットワーク'],
                'business': ['ビジネス', '会社', '営業', '経営', '売上'],
                'science': ['研究', '実験', '理論', '分析', '科学'],
                'medical': ['医療', '病院', '治療', '薬', '診断'],
                'education': ['教育', '学校', '学習', '授業', '先生']
            }

            for domain, keywords in domain_keywords.items():
                if any(keyword in text for keyword in keywords):
                    return domain

            return None

        except Exception:
            return None

    def _manage_terminology_cache(self):
        """용어 캐시 관리"""
        try:
            if len(self.terminology_cache) > self.config['max_terminology_entries']:
                # 사용 빈도와 최근 사용 시간 기반 정리
                sorted_terms = sorted(
                    self.terminology_cache.items(),
                    key=lambda x: (x[1].frequency, x[1].last_used),
                    reverse=True
                )

                # 상위 항목만 유지
                keep_count = int(self.config['max_terminology_entries'] * 0.8)
                new_cache = dict(sorted_terms[:keep_count])
                self.terminology_cache = new_cache

                logger.debug(f"🧹 용어 캐시 정리: {len(new_cache)}개 유지")

        except Exception as e:
            logger.error(f"❌ 용어 캐시 관리 실패: {e}")

    def _calculate_overall_context_score(self, topic_analysis: Dict,
                                       speaker_analysis: Dict,
                                       terminology_analysis: Dict) -> float:
        """전체 문맥 점수 계산"""
        try:
            # 가중 평균 계산
            weights = {
                'topic': 0.4,       # 주제 연속성 40%
                'speaker': 0.3,     # 화자 안정성 30%
                'terminology': 0.3  # 용어 일관성 30%
            }

            topic_score = topic_analysis.get('continuity_score', 0.5)
            speaker_score = speaker_analysis.get('stability_score', 0.5)
            terminology_score = terminology_analysis.get('consistency_score', 0.5)

            overall_score = (
                topic_score * weights['topic'] +
                speaker_score * weights['speaker'] +
                terminology_score * weights['terminology']
            )

            return min(1.0, max(0.0, overall_score))

        except Exception as e:
            logger.error(f"❌ 전체 문맥 점수 계산 실패: {e}")
            return 0.5

    def _should_wait_for_completion(self, context_score: float) -> bool:
        """완성까지 대기 여부 결정"""
        # 문맥 점수가 높으면 완성까지 대기하는 것이 좋음
        return context_score > 0.7

    def _calculate_recommended_buffer_time(self, context_score: float) -> float:
        """권장 버퍼링 시간 계산"""
        # 문맥 점수에 따라 적응형 버퍼링 시간
        if context_score > 0.8:
            return 8.0   # 높은 문맥: 더 긴 버퍼링
        elif context_score > 0.6:
            return 5.0   # 보통 문맥: 표준 버퍼링
        else:
            return 3.0   # 낮은 문맥: 짧은 버퍼링

    def _calculate_context_importance(self, topic_analysis: Dict, speaker_analysis: Dict) -> float:
        """문맥 중요도 계산"""
        try:
            importance_factors = []

            # 주제 변경이 있으면 중요도 증가
            topic_continuity = topic_analysis.get('continuity_score', 0.5)
            if topic_continuity < 0.6:
                importance_factors.append(0.8)  # 주제 변경 시 높은 중요도

            # 화자 변경이 있으면 중요도 증가
            speaker_changes = speaker_analysis.get('changes', [])
            if speaker_changes:
                importance_factors.append(0.7)

            # 기본 중요도
            base_importance = 0.5

            if importance_factors:
                return min(1.0, max(importance_factors))
            else:
                return base_importance

        except Exception:
            return 0.5

    def _generate_cache_key(self, task_id: str, segments: List[ContextualSegment]) -> str:
        """캐시 키 생성"""
        try:
            # 세그먼트 텍스트 해시 기반 키 생성
            import hashlib
            content = ''.join(seg.text for seg in segments)
            content_hash = hashlib.md5(content.encode()).hexdigest()
            return f"context_analysis:{task_id}:{content_hash}"

        except Exception:
            return f"context_analysis:{task_id}:{time.time()}"

    async def _get_cached_analysis(self, cache_key: str) -> Optional[ContextAnalysisResult]:
        """캐시된 분석 결과 조회"""
        try:
            if cache_key in self.context_cache:
                entry = self.context_cache[cache_key]
                if not entry.is_expired():
                    entry.update_access()
                    return entry.analysis_result
                else:
                    del self.context_cache[cache_key]

            return None

        except Exception as e:
            logger.error(f"❌ 캐시 조회 실패: {e}")
            return None

    async def _cache_analysis_result(self, cache_key: str, result: ContextAnalysisResult,
                                   context_window: ContextWindow):
        """분석 결과 캐싱"""
        try:
            cache_entry = ContextCacheEntry(
                cache_key=cache_key,
                analysis_result=result,
                context_window=context_window,
                ttl=self.config['cache_ttl']
            )

            self.context_cache[cache_key] = cache_entry

            # 캐시 크기 관리
            if len(self.context_cache) > 100:  # 최대 100개 항목
                # 오래된 항목 제거
                expired_keys = [
                    key for key, entry in self.context_cache.items()
                    if entry.is_expired()
                ]
                for key in expired_keys:
                    del self.context_cache[key]

        except Exception as e:
            logger.error(f"❌ 분석 결과 캐싱 실패: {e}")

    def _create_fallback_result(self) -> ContextAnalysisResult:
        """기본 결과 생성 (오류 시)"""
        return ContextAnalysisResult(
            topic_continuity=0.5,
            speaker_stability=0.5,
            terminology_consistency=0.5,
            overall_context_score=0.5,
            recommended_buffer_time=5.0,
            context_importance=0.5
        )

    async def get_context_metrics(self) -> Dict:
        """문맥 분석 메트릭 조회"""
        try:
            return {
                'active_context_windows': len(self.context_windows),
                'terminology_cache_size': len(self.terminology_cache),
                'translation_memory_size': len(self.translation_memory),
                'context_cache_size': len(self.context_cache),
                'cache_hit_ratio': self._calculate_cache_hit_ratio()
            }

        except Exception as e:
            logger.error(f"❌ 메트릭 조회 실패: {e}")
            return {}

    def _calculate_cache_hit_ratio(self) -> float:
        """캐시 히트율 계산"""
        try:
            if not self.context_cache:
                return 0.0

            total_access = sum(entry.access_count for entry in self.context_cache.values())
            return min(1.0, total_access / len(self.context_cache)) if self.context_cache else 0.0

        except Exception:
            return 0.0