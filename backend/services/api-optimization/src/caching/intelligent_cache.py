"""
지능형 캐싱 시스템 - 유사 번역 캐싱 및 재활용
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from collections import defaultdict
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

import rapidfuzz
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

@dataclass
class CacheEntry:
    """캐시 항목"""
    source_text: str
    target_text: str
    cache_key: str
    similarity_vector: Optional[List[float]] = None
    metadata: Dict[str, Any] = None
    usage_count: int = 1
    quality_score: float = 1.0
    created_at: float = 0.0
    last_used: float = 0.0
    ttl: float = 3600.0  # 1시간

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.last_used == 0.0:
            self.last_used = time.time()
        if self.metadata is None:
            self.metadata = {}

    def is_expired(self) -> bool:
        """만료 여부 확인"""
        return time.time() - self.created_at > self.ttl

    def update_usage(self):
        """사용 기록 업데이트"""
        self.usage_count += 1
        self.last_used = time.time()

@dataclass
class SimilarityMatch:
    """유사도 매치 결과"""
    cache_entry: CacheEntry
    similarity_score: float
    match_type: str  # exact, semantic, fuzzy
    confidence: float

class IntelligentCache:
    """지능형 캐싱 시스템"""

    def __init__(self, redis_client=None):
        self.redis_client = redis_client

        # 설정
        self.config = {
            'max_cache_size': 10000,           # 최대 캐시 크기
            'similarity_threshold': 0.85,      # 유사도 임계값
            'semantic_similarity_threshold': 0.90,  # 의미적 유사도 임계값
            'fuzzy_similarity_threshold': 0.90,     # 퍼지 유사도 임계값
            'cache_ttl': 3600,                 # 기본 TTL (초)
            'cleanup_interval': 300,           # 정리 간격 (초)
            'embedding_cache_size': 5000,      # 임베딩 캐시 크기
        }

        # 메모리 캐시
        self.memory_cache: Dict[str, CacheEntry] = {}
        self.similarity_index: Dict[str, List[str]] = defaultdict(list)  # 키워드 기반 인덱스

        # 의미적 유사도 모델
        self.sentence_model = None
        self.embedding_cache: Dict[str, List[float]] = {}

        # 통계
        self.stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'exact_matches': 0,
            'semantic_matches': 0,
            'fuzzy_matches': 0,
            'cache_misses': 0
        }

        # 백그라운드 태스크
        self.cleanup_task = None
        self.is_running = False

        self._initialize_sentence_model()
        logger.info("✅ IntelligentCache 초기화 완료")

    def _initialize_sentence_model(self):
        """문장 임베딩 모델 초기화"""
        try:
            if SENTENCE_TRANSFORMERS_AVAILABLE:
                # 경량 다국어 모델 사용
                self.sentence_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                logger.info("✅ SentenceTransformer 모델 로드 완료")
            else:
                logger.warning("⚠️ sentence-transformers 없음 - 의미적 유사도 비활성화")

        except Exception as e:
            logger.error(f"❌ SentenceTransformer 로드 실패: {e}")
            self.sentence_model = None

    async def start(self):
        """캐시 시스템 시작"""
        try:
            self.is_running = True

            # Redis에서 기존 캐시 로드
            await self._load_from_redis()

            # 백그라운드 정리 태스크 시작
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())

            logger.info("✅ IntelligentCache 시작 완료")

        except Exception as e:
            logger.error(f"❌ IntelligentCache 시작 실패: {e}")
            raise

    async def stop(self):
        """캐시 시스템 종료"""
        self.is_running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()

        # Redis에 캐시 저장
        await self._save_to_redis()

        logger.info("✅ IntelligentCache 종료 완료")

    async def get_translation(self, source_text: str, context: Optional[Dict] = None) -> Optional[SimilarityMatch]:
        """번역 캐시 조회"""
        try:
            self.stats['total_requests'] += 1

            # 1. 정확한 매치 확인
            exact_match = await self._find_exact_match(source_text)
            if exact_match:
                self.stats['cache_hits'] += 1
                self.stats['exact_matches'] += 1
                exact_match.update_usage()
                await self._update_redis_entry(exact_match)

                return SimilarityMatch(
                    cache_entry=exact_match,
                    similarity_score=1.0,
                    match_type="exact",
                    confidence=1.0
                )

            # 2. 의미적 유사도 매치
            if self.sentence_model:
                semantic_match = await self._find_semantic_match(source_text, context)
                if semantic_match and semantic_match.similarity_score >= self.config['semantic_similarity_threshold']:
                    self.stats['cache_hits'] += 1
                    self.stats['semantic_matches'] += 1
                    semantic_match.cache_entry.update_usage()
                    await self._update_redis_entry(semantic_match.cache_entry)
                    return semantic_match

            # 3. 퍼지 유사도 매치
            fuzzy_match = await self._find_fuzzy_match(source_text)
            if fuzzy_match and fuzzy_match.similarity_score >= self.config['fuzzy_similarity_threshold']:
                self.stats['cache_hits'] += 1
                self.stats['fuzzy_matches'] += 1
                fuzzy_match.cache_entry.update_usage()
                await self._update_redis_entry(fuzzy_match.cache_entry)
                return fuzzy_match

            # 4. 캐시 미스
            self.stats['cache_misses'] += 1
            return None

        except Exception as e:
            logger.error(f"❌ 번역 캐시 조회 실패: {e}")
            return None

    async def store_translation(self, source_text: str, target_text: str,
                              quality_score: float = 1.0, metadata: Optional[Dict] = None,
                              ttl: Optional[float] = None) -> bool:
        """번역 캐시 저장"""
        try:
            # 캐시 키 생성
            cache_key = self._generate_cache_key(source_text)

            # 임베딩 생성
            similarity_vector = await self._generate_embedding(source_text)

            # 캐시 항목 생성
            entry = CacheEntry(
                source_text=source_text,
                target_text=target_text,
                cache_key=cache_key,
                similarity_vector=similarity_vector,
                metadata=metadata or {},
                quality_score=quality_score,
                ttl=ttl or self.config['cache_ttl']
            )

            # 메모리 캐시에 저장
            self.memory_cache[cache_key] = entry

            # 유사도 인덱스 업데이트
            self._update_similarity_index(source_text, cache_key)

            # Redis에 저장
            await self._store_to_redis(entry)

            # 캐시 크기 관리
            await self._manage_cache_size()

            logger.debug(f"💾 번역 캐시 저장: {source_text[:50]}...")
            return True

        except Exception as e:
            logger.error(f"❌ 번역 캐시 저장 실패: {e}")
            return False

    async def _find_exact_match(self, source_text: str) -> Optional[CacheEntry]:
        """정확한 매치 찾기"""
        try:
            cache_key = self._generate_cache_key(source_text)

            # 메모리 캐시 확인
            if cache_key in self.memory_cache:
                entry = self.memory_cache[cache_key]
                if not entry.is_expired():
                    return entry
                else:
                    del self.memory_cache[cache_key]

            # Redis 확인
            if self.redis_client:
                redis_data = await self.redis_client.get(f"translation_cache:{cache_key}")
                if redis_data:
                    entry_data = json.loads(redis_data)
                    entry = CacheEntry(**entry_data)
                    if not entry.is_expired():
                        self.memory_cache[cache_key] = entry
                        return entry

            return None

        except Exception as e:
            logger.error(f"❌ 정확한 매치 찾기 실패: {e}")
            return None

    async def _find_semantic_match(self, source_text: str, context: Optional[Dict] = None) -> Optional[SimilarityMatch]:
        """의미적 유사도 매치 찾기"""
        try:
            if not self.sentence_model:
                return None

            # 소스 텍스트 임베딩
            source_embedding = await self._generate_embedding(source_text)
            if not source_embedding:
                return None

            best_match = None
            best_similarity = 0.0

            # 모든 캐시 항목과 비교
            for cache_key, entry in self.memory_cache.items():
                if entry.is_expired():
                    continue

                if entry.similarity_vector:
                    similarity = self._calculate_cosine_similarity(
                        source_embedding, entry.similarity_vector
                    )

                    if similarity > best_similarity and similarity >= self.config['semantic_similarity_threshold']:
                        best_similarity = similarity
                        best_match = entry

            if best_match:
                return SimilarityMatch(
                    cache_entry=best_match,
                    similarity_score=best_similarity,
                    match_type="semantic",
                    confidence=best_similarity
                )

            return None

        except Exception as e:
            logger.error(f"❌ 의미적 유사도 매치 실패: {e}")
            return None

    async def _find_fuzzy_match(self, source_text: str) -> Optional[SimilarityMatch]:
        """퍼지 유사도 매치 찾기"""
        try:
            best_match = None
            best_similarity = 0.0

            # 키워드 기반 후보 필터링
            candidates = self._get_fuzzy_candidates(source_text)

            for cache_key in candidates:
                if cache_key in self.memory_cache:
                    entry = self.memory_cache[cache_key]
                    if entry.is_expired():
                        continue

                    # 다양한 퍼지 매칭 알고리즘 사용
                    similarities = [
                        fuzz.ratio(source_text, entry.source_text) / 100.0,
                        fuzz.partial_ratio(source_text, entry.source_text) / 100.0,
                        fuzz.token_sort_ratio(source_text, entry.source_text) / 100.0,
                        fuzz.token_set_ratio(source_text, entry.source_text) / 100.0
                    ]

                    # 최고 유사도 선택
                    similarity = max(similarities)

                    if similarity > best_similarity and similarity >= self.config['fuzzy_similarity_threshold']:
                        best_similarity = similarity
                        best_match = entry

            if best_match:
                return SimilarityMatch(
                    cache_entry=best_match,
                    similarity_score=best_similarity,
                    match_type="fuzzy",
                    confidence=best_similarity * 0.9  # 퍼지 매치는 신뢰도 약간 낮춤
                )

            return None

        except Exception as e:
            logger.error(f"❌ 퍼지 유사도 매치 실패: {e}")
            return None

    def _get_fuzzy_candidates(self, source_text: str) -> List[str]:
        """퍼지 매치 후보 추출"""
        try:
            # 키워드 추출
            keywords = self._extract_keywords(source_text)
            candidates = set()

            # 키워드 기반 후보 수집
            for keyword in keywords:
                if keyword in self.similarity_index:
                    candidates.update(self.similarity_index[keyword])

            # 텍스트 길이 기반 필터링
            source_length = len(source_text)
            filtered_candidates = []

            for cache_key in candidates:
                if cache_key in self.memory_cache:
                    entry = self.memory_cache[cache_key]
                    entry_length = len(entry.source_text)

                    # 길이 차이가 50% 이내인 것만 고려
                    if abs(source_length - entry_length) / max(source_length, entry_length) <= 0.5:
                        filtered_candidates.append(cache_key)

            return filtered_candidates[:50]  # 최대 50개 후보

        except Exception as e:
            logger.error(f"❌ 퍼지 후보 추출 실패: {e}")
            return []

    def _extract_keywords(self, text: str) -> List[str]:
        """키워드 추출"""
        try:
            # 간단한 키워드 추출 (실제로는 더 정교한 방법 필요)
            import re

            # 일본어/한글/영어 단어 추출
            words = re.findall(r'[\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\uAC00-\uD7AF]+', text)

            # 길이 2 이상인 단어만 키워드로 사용
            keywords = [word.lower() for word in words if len(word) >= 2]

            return list(set(keywords))  # 중복 제거

        except Exception:
            return []

    async def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """텍스트 임베딩 생성"""
        try:
            if not self.sentence_model:
                return None

            # 캐시 확인
            text_hash = hashlib.md5(text.encode()).hexdigest()
            if text_hash in self.embedding_cache:
                return self.embedding_cache[text_hash]

            # 임베딩 생성
            embedding = self.sentence_model.encode(text, convert_to_numpy=True)
            embedding_list = embedding.tolist()

            # 캐시에 저장
            self.embedding_cache[text_hash] = embedding_list

            # 캐시 크기 관리
            if len(self.embedding_cache) > self.config['embedding_cache_size']:
                # LRU 방식으로 오래된 것 제거
                oldest_keys = list(self.embedding_cache.keys())[:100]
                for key in oldest_keys:
                    del self.embedding_cache[key]

            return embedding_list

        except Exception as e:
            logger.error(f"❌ 임베딩 생성 실패: {e}")
            return None

    def _calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """코사인 유사도 계산"""
        try:
            if len(vec1) != len(vec2):
                return 0.0

            vec1_np = np.array(vec1)
            vec2_np = np.array(vec2)

            # 코사인 유사도 계산
            dot_product = np.dot(vec1_np, vec2_np)
            norm1 = np.linalg.norm(vec1_np)
            norm2 = np.linalg.norm(vec2_np)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)
            return max(0.0, min(1.0, similarity))  # 0-1 범위로 제한

        except Exception as e:
            logger.error(f"❌ 코사인 유사도 계산 실패: {e}")
            return 0.0

    def _generate_cache_key(self, text: str) -> str:
        """캐시 키 생성"""
        # 텍스트 정규화 후 해시 생성
        normalized_text = text.strip().lower()
        return hashlib.md5(normalized_text.encode()).hexdigest()

    def _update_similarity_index(self, text: str, cache_key: str):
        """유사도 인덱스 업데이트"""
        try:
            keywords = self._extract_keywords(text)
            for keyword in keywords:
                if cache_key not in self.similarity_index[keyword]:
                    self.similarity_index[keyword].append(cache_key)

        except Exception as e:
            logger.error(f"❌ 유사도 인덱스 업데이트 실패: {e}")

    async def _store_to_redis(self, entry: CacheEntry):
        """Redis에 캐시 항목 저장"""
        try:
            if self.redis_client:
                entry_data = asdict(entry)
                await self.redis_client.setex(
                    f"translation_cache:{entry.cache_key}",
                    int(entry.ttl),
                    json.dumps(entry_data, ensure_ascii=False)
                )

        except Exception as e:
            logger.error(f"❌ Redis 캐시 저장 실패: {e}")

    async def _update_redis_entry(self, entry: CacheEntry):
        """Redis 캐시 항목 업데이트"""
        try:
            if self.redis_client:
                entry_data = asdict(entry)
                await self.redis_client.setex(
                    f"translation_cache:{entry.cache_key}",
                    int(entry.ttl - (time.time() - entry.created_at)),
                    json.dumps(entry_data, ensure_ascii=False)
                )

        except Exception as e:
            logger.error(f"❌ Redis 캐시 업데이트 실패: {e}")

    async def _load_from_redis(self):
        """Redis에서 캐시 로드"""
        try:
            if not self.redis_client:
                return

            # Redis 키 패턴으로 모든 번역 캐시 조회
            keys = []
            async for key in self.redis_client.scan_iter(match="translation_cache:*"):
                keys.append(key)

            loaded_count = 0
            for key in keys[:1000]:  # 최대 1000개만 로드
                try:
                    data = await self.redis_client.get(key)
                    if data:
                        entry_data = json.loads(data)
                        entry = CacheEntry(**entry_data)

                        if not entry.is_expired():
                            self.memory_cache[entry.cache_key] = entry
                            self._update_similarity_index(entry.source_text, entry.cache_key)
                            loaded_count += 1

                except Exception as e:
                    logger.debug(f"캐시 항목 로드 실패: {key} - {e}")

            logger.info(f"✅ Redis에서 {loaded_count}개 캐시 항목 로드 완료")

        except Exception as e:
            logger.error(f"❌ Redis 캐시 로드 실패: {e}")

    async def _save_to_redis(self):
        """Redis에 캐시 저장"""
        try:
            if not self.redis_client:
                return

            saved_count = 0
            for entry in self.memory_cache.values():
                if not entry.is_expired():
                    await self._store_to_redis(entry)
                    saved_count += 1

            logger.info(f"✅ Redis에 {saved_count}개 캐시 항목 저장 완료")

        except Exception as e:
            logger.error(f"❌ Redis 캐시 저장 실패: {e}")

    async def _manage_cache_size(self):
        """캐시 크기 관리"""
        try:
            if len(self.memory_cache) <= self.config['max_cache_size']:
                return

            # 사용 빈도와 최근 사용 시간 기반 정리
            cache_items = list(self.memory_cache.items())

            # 점수 계산 (사용 빈도 + 최근성)
            scored_items = []
            current_time = time.time()

            for cache_key, entry in cache_items:
                if entry.is_expired():
                    continue

                # 점수 = 사용 빈도 * 품질 + 최근성 가중치
                recency_weight = max(0.1, 1.0 - (current_time - entry.last_used) / 3600.0)
                score = entry.usage_count * entry.quality_score * recency_weight
                scored_items.append((score, cache_key, entry))

            # 점수 순으로 정렬
            scored_items.sort(key=lambda x: x[0], reverse=True)

            # 상위 항목만 유지
            keep_count = int(self.config['max_cache_size'] * 0.8)
            new_cache = {}

            for score, cache_key, entry in scored_items[:keep_count]:
                new_cache[cache_key] = entry

            self.memory_cache = new_cache

            # 유사도 인덱스 재구성
            self.similarity_index.clear()
            for cache_key, entry in self.memory_cache.items():
                self._update_similarity_index(entry.source_text, cache_key)

            logger.debug(f"🧹 캐시 정리 완료: {len(self.memory_cache)}개 유지")

        except Exception as e:
            logger.error(f"❌ 캐시 크기 관리 실패: {e}")

    async def _cleanup_loop(self):
        """백그라운드 정리 루프"""
        while self.is_running:
            try:
                await asyncio.sleep(self.config['cleanup_interval'])

                # 만료된 항목 제거
                expired_keys = [
                    key for key, entry in self.memory_cache.items()
                    if entry.is_expired()
                ]

                for key in expired_keys:
                    del self.memory_cache[key]

                # 캐시 크기 관리
                await self._manage_cache_size()

                logger.debug(f"🧹 정기 캐시 정리: {len(expired_keys)}개 만료 항목 제거")

            except Exception as e:
                logger.error(f"❌ 캐시 정리 오류: {e}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """캐시 통계 조회"""
        try:
            total_requests = self.stats['total_requests']
            cache_hits = self.stats['cache_hits']

            hit_rate = (cache_hits / total_requests * 100) if total_requests > 0 else 0.0

            return {
                'total_requests': total_requests,
                'cache_hits': cache_hits,
                'cache_misses': self.stats['cache_misses'],
                'hit_rate_percent': hit_rate,
                'exact_matches': self.stats['exact_matches'],
                'semantic_matches': self.stats['semantic_matches'],
                'fuzzy_matches': self.stats['fuzzy_matches'],
                'cache_size': len(self.memory_cache),
                'similarity_index_size': len(self.similarity_index),
                'embedding_cache_size': len(self.embedding_cache),
                'semantic_search_available': self.sentence_model is not None
            }

        except Exception as e:
            logger.error(f"❌ 캐시 통계 조회 실패: {e}")
            return {}

    async def clear_cache(self, pattern: Optional[str] = None) -> int:
        """캐시 정리"""
        try:
            if pattern:
                # 패턴 매치 항목만 제거
                removed_count = 0
                keys_to_remove = []

                for cache_key, entry in self.memory_cache.items():
                    if pattern in entry.source_text or pattern in entry.target_text:
                        keys_to_remove.append(cache_key)

                for key in keys_to_remove:
                    del self.memory_cache[key]
                    removed_count += 1

                return removed_count
            else:
                # 전체 캐시 정리
                cache_size = len(self.memory_cache)
                self.memory_cache.clear()
                self.similarity_index.clear()
                self.embedding_cache.clear()

                # 통계 초기화
                self.stats = {
                    'total_requests': 0,
                    'cache_hits': 0,
                    'exact_matches': 0,
                    'semantic_matches': 0,
                    'fuzzy_matches': 0,
                    'cache_misses': 0
                }

                return cache_size

        except Exception as e:
            logger.error(f"❌ 캐시 정리 실패: {e}")
            return 0