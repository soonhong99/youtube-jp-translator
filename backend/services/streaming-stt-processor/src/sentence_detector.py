"""
Japanese Sentence Detector
일본어 문장 경계 감지 및 문장 재구성 시스템
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
import asyncio

logger = logging.getLogger(__name__)

class JapaneseSentenceDetector:
    """일본어 문장 감지 및 재구성 클래스"""

    def __init__(self):
        # 일본어 문장 종료 표시
        self.sentence_endings = [
            '。', '！', '？', '…', '・・・',
            '.', '!', '?', '...', '...'
        ]

        # 일본어 쉼표 및 구분자
        self.pause_markers = [
            '、', '，', ',', 'ー', '〜', '～'
        ]

        # 문장 경계 패턴
        self.sentence_boundary_pattern = re.compile(
            r'[。！？\.!\?…・]+|(?<=[ます|です|である|だ|でしょう|ね|よ|な|か])[。、]*'
        )

        # 불완전한 문장 패턴
        self.incomplete_patterns = [
            r'[あのそのこのその]$',  # 지시어로 끝남
            r'[はがをに]$',        # 조사로 끝남
            r'[というのは]$',       # 연결어로 끝남
            r'[ですがしかし]$',     # 접속사로 끝남
        ]

        # 문장 완성도 평가 패턴
        self.completeness_patterns = {
            'complete': [
                r'[。！？]$',
                r'[ます|ました|です|でした|である|だった|でしょう]$',
                r'[よね|ですね|ますね]$'
            ],
            'likely_complete': [
                r'[な|か|よ]$',
                r'[らしい|そうです|みたいです]$'
            ],
            'incomplete': [
                r'[て|で|が|を|に|は|の]$',
                r'[という|から|ので]$',
                r'[あの|その|この]$'
            ]
        }

    async def reconstruct_sentences(
        self,
        chunks: List[Dict],
        confidence_threshold: float = 0.7
    ) -> List[Dict]:
        """청크들을 문장 단위로 재구성"""
        try:
            logger.info(f"📝 문장 재구성 시작: {len(chunks)}개 청크")

            if not chunks:
                return []

            # 청크를 시간순으로 정렬
            sorted_chunks = sorted(chunks, key=lambda x: x.start_time)

            # 문장 재구성 수행
            sentences = await self._reconstruct_sentences_async(
                sorted_chunks, confidence_threshold
            )

            logger.info(f"✅ 문장 재구성 완료: {len(sentences)}개 문장")
            return sentences

        except Exception as e:
            logger.error(f"❌ 문장 재구성 실패: {e}")
            return []

    async def _reconstruct_sentences_async(
        self,
        chunks: List[Dict],
        confidence_threshold: float
    ) -> List[Dict]:
        """비동기적으로 문장 재구성"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._reconstruct_sentences_sync,
            chunks,
            confidence_threshold
        )

    def _reconstruct_sentences_sync(
        self,
        chunks: List[Dict],
        confidence_threshold: float
    ) -> List[Dict]:
        """동기적으로 문장 재구성 수행"""
        sentences = []
        current_sentence = {
            "text": "",
            "start_time": 0.0,
            "end_time": 0.0,
            "confidence": 0.0,
            "speaker_change": False,
            "chunk_ids": []
        }

        accumulated_confidence = 0.0
        chunk_count = 0

        for chunk in chunks:
            text = chunk.text.strip()
            if not text:
                continue

            # 첫 번째 청크인 경우
            if not current_sentence["text"]:
                current_sentence["start_time"] = chunk.start_time
                current_sentence["speaker_change"] = chunk.speaker_change

            # 텍스트 추가
            if current_sentence["text"]:
                current_sentence["text"] += " " + text
            else:
                current_sentence["text"] = text

            current_sentence["end_time"] = chunk.end_time
            current_sentence["chunk_ids"].append(chunk.chunk_id)

            # 신뢰도 누적
            accumulated_confidence += chunk.confidence
            chunk_count += 1

            # 문장 완성도 평가
            completeness = self._evaluate_sentence_completeness(text)

            # 문장 경계 감지
            is_sentence_end = (
                completeness == "complete" or
                (completeness == "likely_complete" and chunk_count >= 2) or
                self._detect_sentence_boundary(text)
            )

            # 화자 변화 감지 (다음 청크에서)
            next_chunk_speaker_change = False
            if len(chunks) > chunks.index(chunk) + 1:
                next_chunk = chunks[chunks.index(chunk) + 1]
                next_chunk_speaker_change = next_chunk.speaker_change

            # 문장 종료 조건
            should_end_sentence = (
                is_sentence_end or
                next_chunk_speaker_change or
                chunk_count >= 8  # 최대 8개 청크로 제한
            )

            if should_end_sentence:
                # 문장 완료
                current_sentence["confidence"] = (
                    accumulated_confidence / chunk_count if chunk_count > 0 else 0.0
                )

                # 후처리
                processed_sentence = self._post_process_sentence(current_sentence)

                # 신뢰도 필터링
                if processed_sentence["confidence"] >= confidence_threshold:
                    sentences.append(processed_sentence)

                # 다음 문장 준비
                current_sentence = {
                    "text": "",
                    "start_time": 0.0,
                    "end_time": 0.0,
                    "confidence": 0.0,
                    "speaker_change": False,
                    "chunk_ids": []
                }
                accumulated_confidence = 0.0
                chunk_count = 0

        # 마지막 미완성 문장 처리
        if current_sentence["text"].strip():
            current_sentence["confidence"] = (
                accumulated_confidence / chunk_count if chunk_count > 0 else 0.0
            )
            processed_sentence = self._post_process_sentence(current_sentence)

            if processed_sentence["confidence"] >= confidence_threshold:
                sentences.append(processed_sentence)

        return sentences

    def _evaluate_sentence_completeness(self, text: str) -> str:
        """문장 완성도 평가"""
        text = text.strip()

        # 완전한 문장
        for pattern in self.completeness_patterns['complete']:
            if re.search(pattern, text):
                return "complete"

        # 완성 가능성 높은 문장
        for pattern in self.completeness_patterns['likely_complete']:
            if re.search(pattern, text):
                return "likely_complete"

        # 불완전한 문장
        for pattern in self.completeness_patterns['incomplete']:
            if re.search(pattern, text):
                return "incomplete"

        return "uncertain"

    def _detect_sentence_boundary(self, text: str) -> bool:
        """문장 경계 감지"""
        # 문장 종료 기호 확인
        for ending in self.sentence_endings:
            if text.endswith(ending):
                return True

        # 정규식 패턴 매칭
        if self.sentence_boundary_pattern.search(text):
            return True

        return False

    def _post_process_sentence(self, sentence: Dict) -> Dict:
        """문장 후처리"""
        text = sentence["text"].strip()

        # 중복 공백 제거
        text = re.sub(r'\s+', ' ', text)

        # 중복 구두점 정리
        text = re.sub(r'[。]+', '。', text)
        text = re.sub(r'[！]+', '！', text)
        text = re.sub(r'[？]+', '？', text)

        # 불필요한 접속어 제거
        text = re.sub(r'^[あのそのこの]\s*', '', text)

        # 문장 끝 정리
        if not any(text.endswith(ending) for ending in self.sentence_endings):
            if re.search(r'[ます|です|である|だ]$', text):
                text += '。'

        sentence["text"] = text
        sentence["processed"] = True

        return sentence

    async def detect_real_time_sentence_boundary(
        self,
        current_text: str,
        previous_context: List[str] = None
    ) -> Tuple[bool, float]:
        """실시간 문장 경계 감지"""
        try:
            # 기본 완성도 평가
            completeness = self._evaluate_sentence_completeness(current_text)

            # 신뢰도 계산
            confidence = 0.0

            if completeness == "complete":
                confidence = 0.9
            elif completeness == "likely_complete":
                confidence = 0.7
            elif completeness == "uncertain":
                confidence = 0.4
            else:
                confidence = 0.1

            # 문맥 기반 보정
            if previous_context:
                context_bonus = self._calculate_context_bonus(
                    current_text, previous_context
                )
                confidence = min(1.0, confidence + context_bonus)

            is_boundary = confidence >= 0.6

            return is_boundary, confidence

        except Exception as e:
            logger.error(f"❌ 실시간 문장 경계 감지 실패: {e}")
            return False, 0.0

    def _calculate_context_bonus(
        self,
        current_text: str,
        previous_context: List[str]
    ) -> float:
        """문맥 기반 신뢰도 보너스 계산"""
        bonus = 0.0

        # 이전 텍스트와의 연속성 확인
        if previous_context:
            last_text = previous_context[-1] if previous_context else ""

            # 문장 연결 패턴 확인
            if self._is_sentence_continuation(last_text, current_text):
                bonus += 0.1

            # 주제 일관성 확인
            if self._has_topic_consistency(previous_context, current_text):
                bonus += 0.1

        return bonus

    def _is_sentence_continuation(self, previous: str, current: str) -> bool:
        """문장 연결 확인"""
        # 접속사나 연결어로 시작하는 경우
        continuation_starters = [
            'しかし', 'でも', 'そして', 'それで', 'また', 'さらに', 'ただし'
        ]

        for starter in continuation_starters:
            if current.strip().startswith(starter):
                return True

        return False

    def _has_topic_consistency(
        self,
        previous_context: List[str],
        current_text: str
    ) -> bool:
        """주제 일관성 확인"""
        # 간단한 키워드 기반 일관성 확인
        # 실제로는 더 정교한 NLP 기법 사용 가능

        if not previous_context:
            return False

        # 최근 3개 문장에서 공통 키워드 찾기
        recent_texts = previous_context[-3:] + [current_text]
        all_text = ' '.join(recent_texts)

        # 중요 키워드 추출 (간단한 버전)
        keywords = re.findall(r'[一-龯]+', all_text)  # 한자 키워드

        if len(set(keywords)) / len(keywords) if keywords else 0 < 0.8:
            return True  # 키워드 중복도가 높으면 일관성 있음

        return False

    async def get_sentence_statistics(self, sentences: List[Dict]) -> Dict:
        """문장 통계 정보 반환"""
        if not sentences:
            return {}

        total_sentences = len(sentences)
        total_duration = sum(s["end_time"] - s["start_time"] for s in sentences)
        avg_confidence = sum(s["confidence"] for s in sentences) / total_sentences
        avg_length = sum(len(s["text"]) for s in sentences) / total_sentences

        return {
            "total_sentences": total_sentences,
            "total_duration": total_duration,
            "average_confidence": avg_confidence,
            "average_length": avg_length,
            "sentences_per_minute": (total_sentences / total_duration) * 60 if total_duration > 0 else 0
        }