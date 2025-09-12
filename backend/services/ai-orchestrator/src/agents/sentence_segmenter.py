"""
SentenceSegmentationAgent - AI 기반 지능형 문장 분할 에이전트
일본어 텍스트를 의미 단위로 분할하고 번역에 최적화된 그룹을 생성
"""
import logging
import asyncio
import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
import google.generativeai as genai

from ..config import get_gemini_config
from ..utils.api_tracker import get_api_tracker

logger = logging.getLogger(__name__)

@dataclass
class SentenceSegment:
    """문장 세그먼트 데이터 클래스"""
    text: str
    start_time: float
    end_time: float
    confidence: float
    segment_type: str  # 'statement', 'question', 'exclamation', 'transition'
    speaker_change: bool = False
    semantic_group: int = 0

@dataclass
class TranslationGroup:
    """번역 그룹 데이터 클래스"""
    segments: List[SentenceSegment]
    combined_text: str
    estimated_tokens: int
    context_type: str  # 'dialogue', 'monologue', 'description'

class SentenceSegmentationAgent:
    """AI 기반 지능형 문장 분할 에이전트"""
    
    def __init__(self):
        self.gemini_config = get_gemini_config()
        self.model = self.gemini_config.model_instance if self.gemini_config.is_available() else None
        self.api_tracker = get_api_tracker()
        self.current_task_id = "unknown"  # 추적을 위한 현재 작업 ID
        
        self.agent_info = {
            "name": "SentenceSegmentationAgent",
            "version": "1.0.0",
            "status": "initialized" if self.model else "unavailable",
            "capabilities": [
                "intelligent_sentence_segmentation",
                "speaker_change_detection", 
                "semantic_grouping",
                "translation_optimization"
            ]
        }
        logger.info(f"SentenceSegmentationAgent initialized: {self.agent_info['status']}")
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부 확인"""
        return self.model is not None
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return self.agent_info.copy()
    
    async def intelligent_segment(self, full_text: str, word_timestamps: List[Dict], 
                                context: Dict[str, Any] = None, task_id: str = "unknown") -> List[SentenceSegment]:
        """
        AI 기반 지능형 문장 분할 (API 호출 추적 포함)
        """
        self.current_task_id = task_id
        
        if not self.is_available():
            logger.warning("Gemini model not available, using fallback segmentation")
            return await self._fallback_segmentation(full_text, word_timestamps)
        
        try:
            logger.info(f"Starting intelligent segmentation for text of length: {len(full_text)}")
            
            # 1. AI를 사용한 의미 기반 문장 분할 (추적 포함)
            semantic_segments = await self._ai_semantic_segmentation_tracked(full_text)
            
            if not semantic_segments:
                logger.warning("AI segmentation returned empty results, using fallback")
                return await self._fallback_segmentation(full_text, word_timestamps)
            
            # 2. 화자 변화 감지 (간단한 휴리스틱 사용)
            speaker_changes = await self._detect_speaker_changes_fallback(full_text, semantic_segments)
            
            # 3. 타임스탬프 매핑
            timed_segments = self._map_timestamps_to_segments(
                semantic_segments, word_timestamps, speaker_changes
            )
            
            # 4. 문장 타입 분류 및 신뢰도 계산
            classified_segments = await self._classify_and_score_segments(timed_segments)
            
            logger.info(f"Intelligent segmentation completed: {len(classified_segments)} segments")
            return classified_segments
            
        except Exception as e:
            logger.error(f"Intelligent segmentation failed: {e}, using fallback")
            return await self._fallback_segmentation(full_text, word_timestamps)
    
    async def _ai_semantic_segmentation(self, full_text: str) -> List[str]:
        """AI를 사용한 의미 기반 문장 분할"""
        if not full_text.strip():
            return []
        
        prompt = f"""다음은 유튜브 일본어 음성을 텍스트로 변환한 결과입니다. 
이 텍스트를 의미 단위로 자연스럽게 분할해주세요. 각 문장은 번역하기에 적절한 길이여야 하며, 
문맥과 의미를 해치지 않도록 분할해야 합니다.

규칙:
1. 화자가 바뀌는 지점에서 분할
2. 완결된 의미를 가진 문장 단위로 분할  
3. 너무 짧거나 긴 문장은 적절히 조정
4. 구어체의 자연스러운 흐름을 고려
5. 각 문장을 새 줄로 구분하여 출력

일본어 텍스트:
{full_text}

분할된 문장들:"""

        try:
            response = await self.model.generate_content_async(
                prompt,
                generation_config=self.gemini_config.get_generation_config()
            )
            
            if response.parts and response.text:
                segments = [line.strip() for line in response.text.strip().split('\n') 
                           if line.strip() and len(line.strip()) > 5]
                
                logger.info(f"AI segmentation produced {len(segments)} segments")
                return segments
            else:
                logger.warning("AI segmentation returned empty response")
                return self._basic_segmentation(full_text)
                
        except Exception as e:
            # 할당량 초과나 기타 API 오류 시 fallback 사용
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning(f"Gemini API quota exceeded, using basic segmentation: {e}")
            else:
                logger.error(f"AI segmentation error: {e}")
            return self._basic_segmentation(full_text)
    
    async def _ai_semantic_segmentation_tracked(self, full_text: str) -> List[str]:
        """추적 가능한 AI 기반 의미 문장 분할"""
        if not full_text.strip():
            return []
        
        # API 추적 래퍼를 사용하여 호출
        tracker = self.api_tracker.track_api_call(
            task_id=self.current_task_id,
            agent_name="SentenceSegmentationAgent", 
            function_name="_ai_semantic_segmentation_tracked"
        )
        
        @tracker
        async def _tracked_segmentation(prompt_text: str):
            return await self.model.generate_content_async(
                prompt_text,
                generation_config=self.gemini_config.get_generation_config()
            )
        
        prompt = f"""다음은 유튜브 일본어 음성을 텍스트로 변환한 결과입니다. 
이 텍스트를 의미 단위로 자연스럽게 분할해주세요. 각 문장은 번역하기에 적절한 길이여야 하며, 
문맥과 의미를 해치지 않도록 분할해야 합니다.

규칙:
1. 화자가 바뀌는 지점에서 분할
2. 완결된 의미를 가진 문장 단위로 분할  
3. 너무 짧거나 긴 문장은 적절히 조정
4. 구어체의 자연스러운 흐름을 고려
5. 각 문장을 새 줄로 구분하여 출력

일본어 텍스트:
{full_text}

분할된 문장들:"""

        try:
            logger.info(f"🚀 API CALL START: SentenceSegmentation for task {self.current_task_id}")
            
            response = await _tracked_segmentation(prompt)
            
            if response.parts and response.text:
                segments = [line.strip() for line in response.text.strip().split('\n') 
                           if line.strip() and len(line.strip()) > 5]
                
                logger.info(f"✅ API CALL SUCCESS: Produced {len(segments)} segments")
                return segments
            else:
                logger.warning("❌ API CALL EMPTY: Using fallback segmentation")
                return self._basic_segmentation(full_text)
                
        except Exception as e:
            # 할당량 초과나 기타 API 오류 시 fallback 사용
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning(f"🚨 QUOTA EXCEEDED: Using basic segmentation: {e}")
            else:
                logger.error(f"❌ API CALL ERROR: {e}")
            return self._basic_segmentation(full_text)
    
    def _basic_segmentation(self, text: str) -> List[str]:
        """개선된 일본어 문장 분할 (구어체 특화)"""
        if not text.strip():
            return []
        
        # 1단계: 주요 문장 종결 패턴으로 분할
        primary_patterns = [
            r'[。！？]\s*',                    # 문장부호 + 공백
            r'です\s*[。！？]?\s*',             # 정중한 어미
            r'ます\s*[。！？]?\s*',             # 정중한 동사
            r'でした\s*[。！？]?\s*',           # 과거 정중체
            r'でしょう\s*[。！？]?\s*',         # 추측
            r'ですね\s*[。！？]?\s*',           # 확인
            r'ません\s*[。！？]?\s*',           # 부정
            r'[だの]\s*[。！？]?\s*',           # 단정
            r'んです\s*[。！？]?\s*',           # 설명
        ]
        
        # 2단계: 구어체 종결 패턴 추가
        colloquial_patterns = [
            r'よね\s*[。！？]?\s*',             # 확인 요청
            r'[よな]\s*[。！？]?\s*',          # 감탄/종결
            r'けど\s*[。！？]?\s*',             # 연결어미(구어체 종결)
            r'から\s*[。！？]?\s*',             # 이유 설명 종결
            r'ので\s*[。！？]?\s*',             # 원인 설명 종결
            r'って\s*[。！？]?\s*',             # 인용/전언 종결
            r'かな\s*[。！？]?\s*',             # 추측 종결
            r'でしょ\s*[。！？]?\s*',           # 확인 종결
        ]
        
        # 3단계: 모든 패턴 결합
        all_patterns = primary_patterns + colloquial_patterns
        combined_pattern = '|'.join(all_patterns)
        
        # 분할 실행
        segments = re.split(combined_pattern, text)
        segments = [s.strip() for s in segments if s.strip()]
        
        # 4단계: 너무 짧은 세그먼트 처리 (10자 미만은 앞 세그먼트와 합침)
        merged_segments = []
        for segment in segments:
            if len(segment) < 10 and merged_segments:
                merged_segments[-1] += " " + segment
            elif len(segment) >= 10:
                merged_segments.append(segment)
        
        # 5단계: 긴 문장 추가 분할 (150자 이상)
        final_segments = []
        for segment in merged_segments:
            if len(segment) > 150:
                sub_segments = self._split_long_sentence_improved(segment)
                final_segments.extend(sub_segments)
            else:
                final_segments.append(segment)
        
        return final_segments
    
    def _split_long_sentence_improved(self, sentence: str) -> List[str]:
        """개선된 긴 문장 분할 (구어체 특화)"""
        if len(sentence) <= 150:
            return [sentence]
        
        # 1단계: 구어체 연결 표현으로 분할
        colloquial_breaks = [
            r'[、，]\s*',                       # 쉼표
            r'そして\s+', r'それで\s+', r'だから\s+',  # 접속사
            r'でも\s+', r'しかし\s+', r'ただ\s+',     # 역접
            r'また\s+', r'さらに\s+', r'それに\s+',   # 추가
            r'ところで\s+', r'あと\s+', r'で\s+',     # 화제 전환
        ]
        
        # 분할 시도
        for pattern in colloquial_breaks:
            parts = re.split(pattern, sentence)
            if len(parts) > 1:
                # 적절한 길이로 재구성
                result = []
                current = ""
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if len(current + part) < 80 and current:
                        current += "、" + part
                    else:
                        if current:
                            result.append(current.strip())
                        current = part
                
                if current:
                    result.append(current.strip())
                
                if len(result) > 1:
                    return result
        
        # 2단계: 길이 기반 균등 분할 (fallback)
        mid_point = len(sentence) // 2
        split_points = [
            sentence.find('、', mid_point - 20, mid_point + 20),
            sentence.find(' ', mid_point - 15, mid_point + 15),
            sentence.find('て', mid_point - 10, mid_point + 10),
            sentence.find('で', mid_point - 10, mid_point + 10),
        ]
        
        split_point = None
        for point in split_points:
            if point != -1:
                split_point = point
                break
        
        if split_point and split_point > 20:
            return [
                sentence[:split_point + 1].strip(),
                sentence[split_point + 1:].strip()
            ]
        
        # 최종 fallback: 중간 지점에서 분할
        return [
            sentence[:len(sentence)//2].strip(),
            sentence[len(sentence)//2:].strip()
        ]
    
    def _split_long_sentence(self, sentence: str) -> List[str]:
        """긴 문장을 더 작은 단위로 분할"""
        if len(sentence) <= 400:
            return [sentence]
        
        # 접속사나 쉼표 기준으로 분할
        parts = re.split(r'[、，,]|\s+そして\s+|\s+それで\s+|\s+また\s+|\s+さらに\s+|\s+しかし\s+', sentence)
        parts = [p.strip() for p in parts if p.strip()]
        
        # 너무 작은 부분들은 합치기
        result = []
        current = ""
        for part in parts:
            if len(current + part) < 200 and current:
                current += "、" + part
            else:
                if current:
                    result.append(current.strip())
                current = part
        
        if current:
            result.append(current.strip())
        
        return result if result else [sentence]
    
    async def _detect_speaker_changes(self, full_text: str, segments: List[str]) -> List[bool]:
        """화자 변화 감지"""
        if not self.is_available() or len(segments) <= 1:
            return [False] * len(segments)
        
        try:
            # 간단한 휴리스틱으로 화자 변화 감지
            speaker_changes = []
            
            for i, segment in enumerate(segments):
                is_speaker_change = False
                
                # 첫 번째 세그먼트는 항상 False
                if i == 0:
                    speaker_changes.append(False)
                    continue
                
                prev_segment = segments[i-1] if i > 0 else ""
                
                # 화자 변화를 나타내는 패턴들
                change_indicators = [
                    # 호칭이나 대화 시작 패턴
                    r'^[あのねえ|それでねえ|ところで|でもねえ]',
                    # 감탄사나 응답 패턴  
                    r'^[はい|いいえ|そうですね|そうそう|ええ]',
                    # 질문에서 답변으로의 전환
                    r'[？].*$' in prev_segment and not r'[？]' in segment,
                    # 문체 변화 (존댓말 ↔ 반말)
                    r'です|ます' in prev_segment and not r'です|ます' in segment,
                    not r'です|ます' in prev_segment and r'です|ます' in segment
                ]
                
                # 패턴 매칭으로 화자 변화 감지
                for pattern in change_indicators[:2]:  # 정규식 패턴만 확인
                    if re.search(pattern, segment):
                        is_speaker_change = True
                        break
                
                # 문체 변화 확인
                prev_formal = bool(re.search(r'です|ます', prev_segment))
                curr_formal = bool(re.search(r'です|ます', segment))
                if prev_formal != curr_formal:
                    is_speaker_change = True
                
                speaker_changes.append(is_speaker_change)
            
            logger.info(f"Detected {sum(speaker_changes)} speaker changes")
            return speaker_changes
            
        except Exception as e:
            logger.error(f"Speaker change detection error: {e}")
            return [False] * len(segments)
    
    async def _detect_speaker_changes_fallback(self, full_text: str, segments: List[str]) -> List[bool]:
        """화자 변화 감지 (fallback 버전)"""
        if len(segments) <= 1:
            return [False] * len(segments)
        
        logger.info("Using fallback speaker change detection")
        speaker_changes = []
        
        for i, segment in enumerate(segments):
            is_speaker_change = False
            
            # 첫 번째 세그먼트는 항상 False
            if i == 0:
                speaker_changes.append(False)
                continue
            
            prev_segment = segments[i-1] if i > 0 else ""
            
            # 간단한 휴리스틱으로 화자 변화 감지
            # 1. 감탄사나 응답 패턴
            if re.search(r'^[はい|いいえ|そうですね|そうそう|ええ|あの|それで|でも]', segment):
                is_speaker_change = True
            
            # 2. 문체 변화 (존댓말 ↔ 반말)
            prev_formal = bool(re.search(r'です|ます', prev_segment))
            curr_formal = bool(re.search(r'です|ます', segment))
            if prev_formal != curr_formal:
                is_speaker_change = True
            
            # 3. 질문에서 답변으로의 전환
            if re.search(r'[？]', prev_segment) and not re.search(r'[？]', segment):
                is_speaker_change = True
            
            speaker_changes.append(is_speaker_change)
        
        logger.info(f"Fallback detected {sum(speaker_changes)} speaker changes")
        return speaker_changes
    
    def _map_timestamps_to_segments(self, segments: List[str], word_timestamps: List[Dict], 
                                  speaker_changes: List[bool]) -> List[SentenceSegment]:
        """문장 세그먼트에 타임스탬프 매핑"""
        if not word_timestamps or not segments:
            # 타임스탬프가 없는 경우 균등 분할
            total_duration = 300.0  # 기본 5분으로 가정
            duration_per_segment = total_duration / len(segments) if segments else 0
            
            timed_segments = []
            for i, (text, speaker_change) in enumerate(zip(segments, speaker_changes)):
                start_time = i * duration_per_segment
                end_time = (i + 1) * duration_per_segment
                
                timed_segments.append(SentenceSegment(
                    text=text,
                    start_time=start_time,
                    end_time=end_time,
                    confidence=0.7,  # 기본 신뢰도
                    segment_type='statement',
                    speaker_change=speaker_change
                ))
            
            return timed_segments
        
        # 전체 텍스트 복원
        full_text = " ".join(segments)
        original_text = " ".join([w.get('word', '') for w in word_timestamps])
        
        # 간단한 비례 배분 방식으로 타임스탬프 매핑
        total_duration = word_timestamps[-1].get('end', 0) if word_timestamps else 0
        total_chars = sum(len(seg) for seg in segments)
        
        timed_segments = []
        current_time = 0.0
        
        for i, (text, speaker_change) in enumerate(zip(segments, speaker_changes)):
            # 문장의 길이에 비례하여 시간 할당
            segment_duration = (len(text) / total_chars * total_duration) if total_chars > 0 else 0
            
            start_time = current_time
            end_time = current_time + segment_duration
            current_time = end_time
            
            timed_segments.append(SentenceSegment(
                text=text,
                start_time=round(start_time, 3),
                end_time=round(end_time, 3),
                confidence=0.8,  # 타임스탬프 기반 신뢰도
                segment_type='statement',
                speaker_change=speaker_change
            ))
        
        return timed_segments
    
    async def _classify_and_score_segments(self, segments: List[SentenceSegment]) -> List[SentenceSegment]:
        """문장 타입 분류 및 신뢰도 점수 계산"""
        for segment in segments:
            # 문장 타입 분류
            text = segment.text
            
            if re.search(r'[？]', text):
                segment.segment_type = 'question'
            elif re.search(r'[！]', text):
                segment.segment_type = 'exclamation'
            elif re.search(r'そして|それで|また|さらに|しかし|でも', text):
                segment.segment_type = 'transition'
            else:
                segment.segment_type = 'statement'
            
            # 신뢰도 점수 조정
            confidence_factors = [
                len(text) > 10,  # 적절한 길이
                not re.search(r'[？]{2,}|[！]{2,}', text),  # 과도한 구두점 없음
                len(text) < 500,  # 너무 길지 않음
                bool(re.search(r'[。！？]', text))  # 적절한 종결
            ]
            
            segment.confidence = min(0.95, segment.confidence + sum(confidence_factors) * 0.05)
        
        return segments
    
    async def _fallback_segmentation(self, full_text: str, word_timestamps: List[Dict]) -> List[SentenceSegment]:
        """AI 사용 불가 시 fallback 분할"""
        logger.info("Using fallback segmentation method")
        
        segments = self._basic_segmentation(full_text)
        speaker_changes = [False] * len(segments)  # fallback에서는 화자 변화 감지 없음
        
        return self._map_timestamps_to_segments(segments, word_timestamps, speaker_changes)
    
    async def optimize_for_translation(self, segments: List[SentenceSegment], 
                                     max_tokens_per_group: int = 1200) -> List[TranslationGroup]:
        """번역에 최적화된 그룹 생성 (적응적 그룹 크기)"""
        if not segments:
            return []
        
        logger.info(f"Optimizing {len(segments)} segments for translation with adaptive grouping")
        
        # 할당량 기반 동적 그룹 크기 조정
        adaptive_max_tokens = await self._calculate_adaptive_group_size(len(segments), max_tokens_per_group)
        adaptive_max_sentences = await self._calculate_adaptive_sentence_limit(len(segments))
        
        logger.info(f"Adaptive grouping: max_tokens={adaptive_max_tokens}, max_sentences={adaptive_max_sentences}")
        
        groups = []
        current_group = []
        current_tokens = 0
        current_context = None
        
        for segment in segments:
            # 개선된 토큰 수 추정 (API 트래커와 동일한 로직 사용)
            estimated_tokens = self._accurate_token_estimation(segment.text)
            
            # 개별 세그먼트 우선 처리 강화: 더 많은 조건에서 개별 처리
            should_create_individual_group = (
                len(segment.text.strip()) < 50 or  # 50자 미만은 개별 처리 (30→50)
                self._is_complete_sentence(segment.text) or  # 완결된 문장은 개별 처리
                segment.speaker_change or  # 화자 변화는 항상 개별 처리
                estimated_tokens > adaptive_max_tokens * 0.5 or  # 큰 세그먼트는 개별 처리 (0.7→0.5)
                re.search(r'[？！]', segment.text)  # 질문이나 감탄문은 개별 처리
            )
            
            if should_create_individual_group and not current_group:
                # 현재 그룹이 비어있고 개별 처리 조건을 만족하면 바로 개별 그룹 생성
                groups.append(self._create_translation_group([segment]))
                continue
            
            # 새 그룹 시작 조건 (개별 처리 우선화)
            should_start_new_group = (
                len(current_group) >= adaptive_max_sentences or  # 적응적 문장 제한
                current_tokens + estimated_tokens > adaptive_max_tokens or  # 적응적 토큰 제한
                should_create_individual_group or  # 개별 처리 조건
                (current_context and self._context_changed(current_context, segment))  # 문맥 변화
            )
            
            if should_start_new_group and current_group:
                # 현재 그룹을 완성하고 새 그룹 시작
                groups.append(self._create_translation_group(current_group))
                current_group = []
                current_tokens = 0
            
            current_group.append(segment)
            current_tokens += estimated_tokens
            current_context = self._determine_context(segment)
        
        # 마지막 그룹 처리
        if current_group:
            groups.append(self._create_translation_group(current_group))
        
        logger.info(f"Created {len(groups)} translation groups (avg {len(segments)/len(groups):.1f} segments per group)")
        return groups
    
    async def _calculate_adaptive_group_size(self, total_segments: int, default_max_tokens: int) -> int:
        """할당량 기반 적응적 그룹 크기 계산 (설정값 존중)"""
        try:
            from ..utils.circuit_breaker import get_circuit_breaker
            
            breaker = get_circuit_breaker("translation")
            status = breaker.get_status()
            
            # 남은 할당량에 따라 그룹 크기 조정 (단, 설정값을 절대 초과하지 않음)
            remaining_quota = status.get("remaining_quota", 50)
            
            if remaining_quota < 10:
                # 할당량 부족: 설정값의 1.5배까지만 (여전히 제한적)
                adaptive_tokens = min(default_max_tokens * 1.5, default_max_tokens + 100)
                logger.info(f"Low quota ({remaining_quota}): using controlled groups ({adaptive_tokens} tokens, base={default_max_tokens})")
                return int(adaptive_tokens)
            elif remaining_quota < 20:
                # 할당량 주의: 설정값의 1.2배까지만
                adaptive_tokens = min(default_max_tokens * 1.2, default_max_tokens + 50)
                logger.info(f"Medium quota ({remaining_quota}): using slightly larger groups ({adaptive_tokens} tokens, base={default_max_tokens})")
                return int(adaptive_tokens)
            else:
                # 할당량 충분: 설정값 그대로 사용
                logger.info(f"Sufficient quota ({remaining_quota}): using configured groups ({default_max_tokens} tokens)")
                return default_max_tokens
                
        except Exception as e:
            logger.warning(f"Failed to calculate adaptive group size: {e}, using default={default_max_tokens}")
            return default_max_tokens
    
    async def _calculate_adaptive_sentence_limit(self, total_segments: int) -> int:
        """적응적 문장 수 제한 계산 (개별 번역 우선)"""
        try:
            from ..utils.circuit_breaker import get_circuit_breaker
            
            breaker = get_circuit_breaker("translation")
            status = breaker.get_status()
            
            remaining_quota = status.get("remaining_quota", 50)
            
            if remaining_quota < 10:
                # 할당량 부족: 최대 2문장 (더욱 보수적)
                return min(2, max(1, total_segments // 12))
            elif remaining_quota < 20:
                # 할당량 주의: 최대 2문장  
                return min(2, max(1, total_segments // 15))
            else:
                # 할당량 충분: 개별 번역 최우선 (1문장씩)
                return 1
                
        except Exception as e:
            logger.warning(f"Failed to calculate adaptive sentence limit: {e}, using default")
            return 1  # 개별 번역 최우선
    
    def _is_complete_sentence(self, text: str) -> bool:
        """일본어 문장 완결성 판단"""
        if not text or len(text.strip()) < 10:
            return False
        
        text = text.strip()
        
        # 일본어 문장 완결 패턴들
        complete_patterns = [
            r'[。！？]$',                    # 문장 부호로 끝남
            r'です$', r'だ$', r'である$',      # 정중한 어미
            r'ます$', r'まして$', r'ました$',   # 정중한 동사 어미
            r'よね$', r'ね$', r'よ$',         # 종료 조사
            r'でした$', r'でしょう$',          # 과거/추측 어미
            r'ん[だで]す$', r'んです$',       # 설명 어미
            r'[まし]たい$',                   # 희망 표현
            r'けど$', r'けれど$',             # 연결 어미 (구어체에서 종결)
        ]
        
        # 미완결 패턴들 (그룹핑 필요)
        incomplete_patterns = [
            r'は$', r'が$', r'を$', r'に$',    # 조사로만 끝남
            r'と$', r'で$', r'から$',          # 접속/부사 조사
            r'して$', r'なって$',              # 연결형
            r'[いきし]て$',                     # 동사 연결형
        ]
        
        # 미완결 패턴 확인
        for pattern in incomplete_patterns:
            if re.search(pattern, text):
                return False
        
        # 완결 패턴 확인
        for pattern in complete_patterns:
            if re.search(pattern, text):
                return True
        
        # 길이 기반 판단 (40자 이상이면서 동사로 끝나면 완결로 간주)
        if len(text) > 40 and re.search(r'[るすくぐむぶぬづつ]$', text):
            return True
        
        return False
    
    def _accurate_token_estimation(self, text: str) -> int:
        """정확한 토큰 수 추정 (API 트래커와 동일한 로직)"""
        if not text:
            return 0
        
        # 아시아 문자 비율 계산
        asian_chars = len([c for c in text if ord(c) > 0x2000])
        asian_ratio = asian_chars / len(text) if len(text) > 0 else 0
        
        if asian_ratio > 0.3:  # 일본어/한국어
            # 한자 비율로 더 정교한 추정
            kanji_chars = len([c for c in text if 0x4E00 <= ord(c) <= 0x9FAF])
            kanji_ratio = kanji_chars / len(text) if len(text) > 0 else 0
            
            base_factor = 1.8
            kanji_penalty = kanji_ratio * 0.4
            length_bonus = min(0.2, len(text) / 5000)
            
            token_factor = base_factor + kanji_penalty - length_bonus
            return max(1, int(len(text) / token_factor))
        else:
            # 영어
            return max(1, len(text) // 4)
    
    def _context_changed(self, current_context: str, segment: SentenceSegment) -> bool:
        """문맥 변화 감지"""
        new_context = self._determine_context(segment)
        return current_context != new_context
    
    def _determine_context(self, segment: SentenceSegment) -> str:
        """문장의 문맥 타입 결정"""
        text = segment.text
        
        # 대화 패턴
        if re.search(r'[？]|はい|いいえ|そうですね|ありがとう', text):
            return 'dialogue'
        
        # 설명/서술 패턴  
        if re.search(r'について|に関して|というのは|つまり', text):
            return 'description'
        
        # 기본은 독백
        return 'monologue'
    
    def _create_translation_group(self, segments: List[SentenceSegment]) -> TranslationGroup:
        """번역 그룹 생성"""
        if not segments:
            return TranslationGroup([], "", 0, "unknown")
        
        combined_text = "\n".join([seg.text for seg in segments])
        estimated_tokens = sum(int(len(seg.text) * 1.2) for seg in segments)
        
        # 그룹의 주요 문맥 결정
        contexts = [self._determine_context(seg) for seg in segments]
        context_type = max(set(contexts), key=contexts.count)
        
        return TranslationGroup(
            segments=segments,
            combined_text=combined_text,
            estimated_tokens=estimated_tokens,
            context_type=context_type
        )
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """처리 통계 반환"""
        return {
            "agent_name": "SentenceSegmentationAgent",
            "model_available": self.is_available(),
            "model_name": self.gemini_config.model_name if self.gemini_config else "N/A",
            "supported_features": [
                "semantic_segmentation",
                "speaker_detection", 
                "translation_optimization"
            ]
        }