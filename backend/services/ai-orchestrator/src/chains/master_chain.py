"""
마스터 체인 - 번역과 후처리를 통합하는 최상위 워크플로우
조건부 분기, 병렬 처리, 에러 복구 등 고급 오케스트레이션 기능 제공
"""
import logging
import asyncio
import re
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel

from .translation_chain import TranslationChain
from .post_processing_chain import PostProcessingChain
from ..agents.sentence_segmenter import SentenceSegmentationAgent
from ..config import MAX_CONCURRENT_TASKS

logger = logging.getLogger(__name__)

class ProcessingMode(Enum):
    """처리 모드"""
    FAST = "fast"           # 번역만
    STANDARD = "standard"   # 번역 + 기본 후처리
    PREMIUM = "premium"     # 번역 + 검토 + 전체 후처리
    CUSTOM = "custom"       # 사용자 정의

class MasterChain:
    """AI 오케스트레이션 마스터 체인"""
    
    def __init__(self):
        # 하위 체인들 및 에이전트 초기화
        self.translation_chain = TranslationChain(enable_review=True, enable_improvement=True)
        self.post_processing_chain = PostProcessingChain(
            enable_summary=True, 
            enable_formatting=True, 
            enable_highlights=True
        )
        self.sentence_segmenter = SentenceSegmentationAgent()
        
        # 처리 모드별 설정
        self.mode_configs = {
            ProcessingMode.FAST: {
                "translation": {"enable_review": False, "enable_improvement": False},
                "post_processing": {"enabled": False}
            },
            ProcessingMode.STANDARD: {
                "translation": {"enable_review": False, "enable_improvement": False},
                "post_processing": {"enabled": True, "enable_summary": True, "enable_formatting": True, "enable_highlights": False}
            },
            ProcessingMode.PREMIUM: {
                "translation": {"enable_review": True, "enable_improvement": True},
                "post_processing": {"enabled": True, "enable_summary": True, "enable_formatting": True, "enable_highlights": True}
            }
        }
        
        # 체인 상태
        self.is_initialized = self._validate_chains()
    
    def _validate_chains(self) -> bool:
        """하위 체인들의 상태 검증"""
        try:
            translation_ok = self.translation_chain.is_available()
            post_processing_ok = self.post_processing_chain.is_available()
            segmenter_ok = self.sentence_segmenter.is_available()
            
            logger.info(f"Chain validation: translation={translation_ok}, post_processing={post_processing_ok}, segmenter={segmenter_ok}")
            
            return translation_ok  # 번역은 필수, 후처리와 문장분할은 선택적
            
        except Exception as e:
            logger.error(f"Chain validation failed: {e}")
            return False
    
    def is_available(self) -> bool:
        """마스터 체인 사용 가능 여부"""
        return self.is_initialized
    
    async def process(self, segments: List[Dict[str, Any]], 
                     mode: Union[ProcessingMode, str] = ProcessingMode.STANDARD,
                     custom_options: Dict[str, Any] = None) -> Dict[str, Any]:
        """마스터 처리 파이프라인"""
        if not self.is_available():
            return {
                "error": "Master chain not available",
                "segments": segments,
                "metadata": {"chain_available": False}
            }
        
        # 모드 정규화
        if isinstance(mode, str):
            try:
                mode = ProcessingMode(mode)
            except ValueError:
                logger.warning(f"Invalid mode '{mode}', using STANDARD")
                mode = ProcessingMode.STANDARD
        
        start_time = asyncio.get_event_loop().time()
        custom_options = custom_options or {}
        
        try:
            logger.info(f"Starting master chain processing: mode={mode.value}, segments={len(segments)}")
            
            # 처리 설정 결정
            processing_config = self._determine_processing_config(mode, custom_options)
            
            # 처리 실행
            if processing_config["parallel_processing"]:
                result = await self._process_parallel(segments, processing_config)
            else:
                result = await self._process_sequential(segments, processing_config)
            
            # 최종 결과 정리
            processing_time = asyncio.get_event_loop().time() - start_time
            result = self._finalize_result(result, mode, processing_time, processing_config)
            
            logger.info(f"Master chain completed in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Master chain processing error: {e}")
            return {
                "error": f"Master chain failed: {str(e)}",
                "segments": segments,
                "metadata": {
                    "processing_time": asyncio.get_event_loop().time() - start_time,
                    "mode": mode.value,
                    "failed_at": "master_chain"
                }
            }
    
    async def process_sentence_first_workflow(self, raw_text: str, word_timestamps: List[Dict], 
                                            mode: Union[ProcessingMode, str] = ProcessingMode.STANDARD,
                                            custom_options: Dict[str, Any] = None,
                                            status_callback = None, task_id: str = "unknown",
                                            cancel_event = None) -> Dict[str, Any]:
        """
        새로운 sentence-first 워크플로우
        1. AI 기반 지능형 문장 분할
        2. 번역 최적화 그룹핑
        3. 효율적인 배치 번역
        4. 후처리
        """
        if not self.is_available():
            return {
                "error": "Master chain not available",
                "segments": [],
                "metadata": {"chain_available": False}
            }
        
        # 모드 정규화
        if isinstance(mode, str):
            try:
                mode = ProcessingMode(mode)
            except ValueError:
                logger.warning(f"Invalid mode '{mode}', using STANDARD")
                mode = ProcessingMode.STANDARD
        
        start_time = asyncio.get_event_loop().time()
        custom_options = custom_options or {}
        
        try:
            logger.info(f"Starting sentence-first workflow: mode={mode.value}, text_length={len(raw_text)}")
            
            # 취소 확인 함수
            def check_cancellation():
                if cancel_event and cancel_event.is_set():
                    raise Exception(f"Task {task_id} was cancelled")
            
            # 상태 콜백 함수
            def update_status(stage: str, progress: int = 0, details: Dict = None):
                # 취소 확인 먼저
                check_cancellation()
                if status_callback:
                    status_callback({
                        "current_stage": stage,
                        "progress": progress,
                        "details": details or {}
                    })
            
            # 1. 조건부 AI 기반 지능형 문장 분할 (할당량 확인)
            update_status("sentence_segmentation", 10, {"message": "문장 분할 전략 결정 중"})
            
            check_cancellation()  # 취소 확인
            
            # 할당량 및 비용 기반 AI 분할 사용 여부 결정
            use_ai_segmentation = await self._should_use_ai_segmentation(task_id, len(raw_text))
            
            if use_ai_segmentation and self.sentence_segmenter.is_available():
                update_status("sentence_segmentation", 15, {"message": "AI 기반 지능형 문장 분할 시작"})
                sentence_segments = await self.sentence_segmenter.intelligent_segment(
                    raw_text, word_timestamps, task_id=task_id
                )
                logger.info(f"AI segmentation completed: {len(sentence_segments)} segments")
            else:
                # Fallback to basic segmentation (API 호출 없음)
                fallback_reason = "할당량 절약" if not use_ai_segmentation else "AI 분할기 비활성화"
                logger.info(f"Using basic segmentation: {fallback_reason}")
                update_status("sentence_segmentation", 15, {"message": f"기본 분할 사용 ({fallback_reason})"})
                sentence_segments = await self.sentence_segmenter._fallback_segmentation(
                    raw_text, word_timestamps
                )
            
            if not sentence_segments:
                raise Exception("문장 분할에 실패했습니다")
            
            update_status("sentence_segmentation", 30, {
                "message": f"{len(sentence_segments)}개 문장으로 분할 완료",
                "segment_count": len(sentence_segments)
            })
            
            check_cancellation()  # 취소 확인
            
            # 2. 번역 최적화 그룹핑
            update_status("translation_optimization", 40, {"message": "번역 그룹 최적화 중"})
            
            translation_groups = await self.sentence_segmenter.optimize_for_translation(
                sentence_segments, max_tokens_per_group=200  # 800 → 200으로 대폭 축소
            )
            
            logger.info(f"Created {len(translation_groups)} translation groups")
            update_status("translation_optimization", 50, {
                "message": f"{len(translation_groups)}개 번역 그룹 생성",
                "group_count": len(translation_groups),
                "estimated_cost": sum(g.estimated_tokens for g in translation_groups) * 0.001  # 대략적인 비용
            })
            
            check_cancellation()  # 취소 확인
            
            # 3. 효율적인 배치 번역 (할당량 고려)
            update_status("batch_translation", 60, {"message": "배치 번역 시작"})
            
            try:
                translated_segments = await self._process_translation_groups(
                    translation_groups, mode, custom_options, 
                    lambda progress: update_status("batch_translation", 60 + progress // 3),
                    cancel_event=cancel_event,  # 취소 이벤트 전달
                    task_id=task_id  # task_id 전달 추가
                )
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    logger.warning(f"Translation quota exceeded, providing partial results: {e}")
                    # 기본 구조만 제공
                    translated_segments = self._create_fallback_segments(translation_groups)
                    update_status("batch_translation", 80, {
                        "message": "API 할당량 초과 - 기본 구조로 처리",
                        "quota_exceeded": True
                    })
                else:
                    raise
            
            update_status("batch_translation", 80, {
                "message": f"{len(translated_segments)}개 세그먼트 번역 완료",
                "success_count": len([s for s in translated_segments if s.get('korean_text')])
            })
            
            # 4. 후처리 (필요한 경우)
            processing_config = self._determine_processing_config(mode, custom_options)
            
            if processing_config.get("post_processing_enabled", False):
                update_status("post_processing", 85, {"message": "후처리 작업 시작"})
                
                post_result = await self.post_processing_chain.process(
                    translated_segments, custom_options
                )
                
                if "error" not in post_result:
                    translated_segments = post_result["segments"]
                    logger.info("Post-processing completed successfully")
                else:
                    logger.warning(f"Post-processing failed: {post_result['error']}")
                
                update_status("post_processing", 95, {"message": "후처리 완료"})
            
            # 최종 결과 구성
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = {
                "segments": translated_segments,
                "metadata": {
                    "workflow_type": "sentence_first",
                    "processing_mode": mode.value,
                    "processing_time": processing_time,
                    "original_text_length": len(raw_text),
                    "sentence_count": len(sentence_segments),
                    "translation_groups": len(translation_groups),
                    "success_rate": len([s for s in translated_segments if s.get('korean_text')]) / len(translated_segments) if translated_segments else 0,
                    "segmenter_available": self.sentence_segmenter.is_available(),
                    "estimated_tokens": sum(g.estimated_tokens for g in translation_groups),
                    "processing_stages": ["sentence_segmentation", "translation_optimization", "batch_translation", "post_processing"] if processing_config.get("post_processing_enabled") else ["sentence_segmentation", "translation_optimization", "batch_translation"]
                }
            }
            
            update_status("completed", 100, {"message": "전체 처리 완료"})
            logger.info(f"Sentence-first workflow completed in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Sentence-first workflow error: {e}")
            return {
                "error": f"Sentence-first workflow failed: {str(e)}",
                "segments": [],
                "metadata": {
                    "workflow_type": "sentence_first",
                    "processing_time": asyncio.get_event_loop().time() - start_time,
                    "mode": mode.value,
                    "failed_at": "sentence_first_workflow"
                }
            }
    
    async def _process_translation_groups(self, translation_groups: List, mode: ProcessingMode, 
                                        custom_options: Dict[str, Any], 
                                        progress_callback = None, cancel_event = None, task_id: str = "unknown") -> List[Dict[str, Any]]:
        """번역 그룹 처리"""
        all_segments = []
        
        for i, group in enumerate(translation_groups):
            try:
                # 취소 확인
                if cancel_event and cancel_event.is_set():
                    logger.info(f"Translation cancelled at group {i}/{len(translation_groups)}")
                    raise Exception("Translation cancelled")
                
                if progress_callback:
                    progress = int((i / len(translation_groups)) * 30)  # 30% 범위 내에서 진행률
                    progress_callback(progress)
                
                # task_id를 번역 에이전트에 설정
                self.translation_chain.translator.set_task_id(f"{task_id}-group-{i}")
                
                # 그룹의 결합된 텍스트를 번역 (취소 이벤트도 전달)
                translation_result = await self.translation_chain.translator.translate_batch(
                    [group.combined_text], cancel_event=cancel_event
                )
                
                if translation_result and len(translation_result) > 0:
                    group_translation = translation_result[0]
                    
                    # 번역 결과를 개별 세그먼트로 분배
                    translated_sentences = self._distribute_translation_to_segments(
                        group_translation, group.segments
                    )
                    
                    # 세그먼트 데이터 구성
                    for j, (segment, korean_text) in enumerate(zip(group.segments, translated_sentences)):
                        segment_data = {
                            'text': segment.text,
                            'korean_text': korean_text.strip() if korean_text else '[번역 실패]',
                            'start': segment.start_time,
                            'end': segment.end_time,
                            'confidence': segment.confidence,
                            'segment_type': segment.segment_type,
                            'speaker_change': segment.speaker_change,
                            'semantic_group': segment.semantic_group,
                            'translation_group': i,
                            'context_type': group.context_type
                        }
                        all_segments.append(segment_data)
                else:
                    # 번역 실패 시 기본 데이터
                    for segment in group.segments:
                        segment_data = {
                            'text': segment.text,
                            'korean_text': '[번역 실패]',
                            'start': segment.start_time,
                            'end': segment.end_time,
                            'confidence': segment.confidence,
                            'segment_type': segment.segment_type,
                            'speaker_change': segment.speaker_change
                        }
                        all_segments.append(segment_data)
                
            except Exception as e:
                logger.error(f"Translation group {i} failed: {e}")
                # 실패한 그룹도 기본 구조로 추가
                for segment in group.segments:
                    segment_data = {
                        'text': segment.text,
                        'korean_text': '[번역 오류]',
                        'start': segment.start_time,
                        'end': segment.end_time,
                        'confidence': 0.0
                    }
                    all_segments.append(segment_data)
        
        return all_segments
    
    def _distribute_translation_to_segments(self, group_translation: str, segments) -> List[str]:
        """그룹 번역 결과를 개별 세그먼트로 분배 (개선된 로직)"""
        if not group_translation or not segments:
            return ['[번역 실패]'] * len(segments)
        
        # 단일 세그먼트인 경우 번역 전체를 할당
        if len(segments) == 1:
            return [group_translation.strip()]
        
        # 1차: 한국어 문장 구분자로 분리 (더 정확한 패턴)
        korean_sentence_patterns = [
            r'[.!?。！？]\s*',  # 문장부호 + 공백
            r'\n\s*',           # 줄바꿈 + 공백
            r'(?<=다)\s+(?=[가-힣])',    # '다' 뒤 공백 (한국어 어미)
            r'(?<=요)\s+(?=[가-힣])',    # '요' 뒤 공백 (존댓말)
            r'(?<=니다)\s+(?=[가-힣])',  # '니다' 뒤 공백
        ]
        
        best_split = None
        best_score = 0
        
        # 각 패턴으로 분리 시도하여 최적의 분할 찾기
        for pattern in korean_sentence_patterns:
            try:
                split_result = re.split(pattern, group_translation)
                split_result = [s.strip() for s in split_result if s.strip()]
                
                # 세그먼트 수와 정확히 일치하면 바로 사용
                if len(split_result) == len(segments):
                    return split_result
                
                # 적합도 계산 (세그먼트 수에 가까울수록 높은 점수)
                score = 1.0 - abs(len(split_result) - len(segments)) / max(len(segments), len(split_result))
                if score > best_score and len(split_result) > 0:
                    best_score = score
                    best_split = split_result
                    
            except Exception:
                continue
        
        # 최적 분할이 있으면 사용
        if best_split:
            return self._adjust_translation_length(best_split, len(segments))
        
        # 2차: 공백 기반 분리 (fallback)
        words = group_translation.split()
        if len(words) >= len(segments):
            # 단어를 세그먼트 수만큼 그룹화
            words_per_segment = len(words) // len(segments)
            remainder = len(words) % len(segments)
            
            result = []
            word_idx = 0
            for i in range(len(segments)):
                segment_words = words_per_segment + (1 if i < remainder else 0)
                segment_text = ' '.join(words[word_idx:word_idx + segment_words])
                result.append(segment_text if segment_text else '[번역 누락]')
                word_idx += segment_words
            
            return result
        
        # 최종 fallback: 전체 번역을 첫 번째 세그먼트에, 나머지는 기본값
        result = [group_translation.strip()]
        result.extend(['[번역 연속]'] * (len(segments) - 1))
        
        return result
    
    def _adjust_translation_length(self, translations: List[str], target_length: int) -> List[str]:
        """번역 리스트를 목표 길이에 맞게 조정"""
        if len(translations) == target_length:
            return translations
        elif len(translations) > target_length:
            # 번역이 더 많은 경우: 마지막 세그먼트에 나머지 합치기
            result = translations[:target_length-1]
            remaining = ' '.join(translations[target_length-1:])
            result.append(remaining)
            return result
        else:
            # 번역이 부족한 경우: 마지막 번역을 반복하거나 기본값 사용
            result = translations[:]
            while len(result) < target_length:
                if translations:
                    # 마지막 번역의 변형 또는 연속 표시
                    result.append('[번역 연속]')
                else:
                    result.append('[번역 누락]')
            return result
    
    def _create_fallback_segments(self, translation_groups: List) -> List[Dict[str, Any]]:
        """할당량 초과 시 fallback 세그먼트 생성"""
        fallback_segments = []
        
        for i, group in enumerate(translation_groups):
            for j, segment in enumerate(group.segments):
                segment_data = {
                    'text': segment.text,
                    'korean_text': f'[번역 할당량 초과] {segment.text}',  # 원본 텍스트 표시
                    'start': segment.start_time,
                    'end': segment.end_time,
                    'confidence': segment.confidence,
                    'segment_type': segment.segment_type,
                    'speaker_change': segment.speaker_change,
                    'semantic_group': getattr(segment, 'semantic_group', 0),
                    'translation_group': i,
                    'context_type': group.context_type,
                    'quota_exceeded': True
                }
                fallback_segments.append(segment_data)
        
        logger.info(f"Created {len(fallback_segments)} fallback segments due to quota limits")
        return fallback_segments
    
    async def _should_use_ai_segmentation(self, task_id: str, text_length: int) -> bool:
        """AI 분할 사용 여부 결정 (할당량 기반)"""
        try:
            # Circuit Breaker 상태 확인
            from ..utils.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig
            
            config = CircuitBreakerConfig(
                quota_limit=35,      # 보수적 할당량 설정
                cost_limit=0.8       # 일일 비용 제한
            )
            
            breaker = get_circuit_breaker("sentence_segmentation", config)
            status = breaker.get_status()
            
            # 할당량 부족 시 AI 분할 비활성화
            if status["remaining_quota"] < 3:
                logger.info(f"AI segmentation disabled: insufficient quota ({status['remaining_quota']} remaining)")
                return False
            
            # 비용 제한 근접 시 비활성화
            if status["remaining_cost"] < 0.1:
                logger.info(f"AI segmentation disabled: cost limit approaching (${status['remaining_cost']:.4f} remaining)")
                return False
            
            # 텍스트 길이 기반 필요성 판단
            if text_length < 500:  # 짧은 텍스트는 기본 분할로 충분
                logger.info(f"AI segmentation disabled: text too short ({text_length} chars)")
                return False
            
            # Circuit Breaker 상태 확인
            if status["state"] != "closed":
                logger.info(f"AI segmentation disabled: circuit breaker state is {status['state']}")
                return False
            
            logger.info(f"AI segmentation enabled: quota={status['remaining_quota']}, cost=${status['remaining_cost']:.4f}")
            return True
            
        except Exception as e:
            logger.warning(f"Error checking AI segmentation conditions: {e}, defaulting to basic segmentation")
            return False
    
    def _determine_processing_config(self, mode: ProcessingMode, custom_options: Dict[str, Any]) -> Dict[str, Any]:
        """처리 설정 결정"""
        if mode == ProcessingMode.CUSTOM:
            # 커스텀 모드는 custom_options에서 모든 설정을 가져옴
            config = {
                "translation_enabled": custom_options.get("enable_translation", True),
                "review_enabled": custom_options.get("enable_review", False),
                "improvement_enabled": custom_options.get("enable_improvement", False),
                "post_processing_enabled": custom_options.get("enable_post_processing", True),
                "summary_enabled": custom_options.get("enable_summary", True),
                "formatting_enabled": custom_options.get("enable_formatting", True),
                "highlights_enabled": custom_options.get("enable_highlights", False),
                "parallel_processing": custom_options.get("parallel_processing", False),
                "custom_options": custom_options
            }
        else:
            # 미리 정의된 모드 설정
            mode_config = self.mode_configs[mode]
            translation_config = mode_config["translation"]
            post_config = mode_config["post_processing"]
            
            config = {
                "translation_enabled": True,
                "review_enabled": translation_config.get("enable_review", False),
                "improvement_enabled": translation_config.get("enable_improvement", False),
                "post_processing_enabled": post_config.get("enabled", True),
                "summary_enabled": post_config.get("enable_summary", True),
                "formatting_enabled": post_config.get("enable_formatting", True),
                "highlights_enabled": post_config.get("enable_highlights", False),
                "parallel_processing": custom_options.get("parallel_processing", mode == ProcessingMode.PREMIUM),
                "custom_options": custom_options
            }
        
        return config
    
    async def _process_sequential(self, segments: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
        """순차 처리"""
        result = {"segments": segments}
        
        try:
            # 1. 번역 단계
            if config["translation_enabled"]:
                translation_options = {
                    "include_detailed_results": config["custom_options"].get("include_detailed_results", False)
                }
                
                # 번역 체인 임시 재구성 (필요시)
                temp_translation_chain = TranslationChain(
                    enable_review=config["review_enabled"],
                    enable_improvement=config["improvement_enabled"]
                )
                
                translation_result = await temp_translation_chain.process(segments, translation_options)
                
                if "error" in translation_result:
                    return translation_result
                
                result["segments"] = translation_result["segments"]
                result["translation_metadata"] = translation_result.get("metadata", {})
            
            # 2. 후처리 단계
            if config["post_processing_enabled"]:
                post_processing_options = {
                    "max_chars_per_line": config["custom_options"].get("max_chars_per_line", 40),
                    "highlight_count": config["custom_options"].get("highlight_count", 3)
                }
                
                # 후처리 체인 임시 재구성 (필요시)
                temp_post_chain = PostProcessingChain(
                    enable_summary=config["summary_enabled"],
                    enable_formatting=config["formatting_enabled"],
                    enable_highlights=config["highlights_enabled"]
                )
                
                post_result = await temp_post_chain.process(result["segments"], post_processing_options)
                
                if "error" not in post_result:
                    result["segments"] = post_result["segments"]
                    result["post_processing_metadata"] = post_result.get("metadata", {})
                else:
                    # 후처리 실패해도 번역 결과는 유지
                    result["post_processing_error"] = post_result["error"]
            
            return result
            
        except Exception as e:
            logger.error(f"Sequential processing error: {e}")
            return {
                "error": f"Sequential processing failed: {str(e)}",
                "segments": segments
            }
    
    async def _process_parallel(self, segments: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
        """병렬 처리 (번역과 분석 작업을 동시에)"""
        try:
            # 번역은 필수이므로 먼저 실행
            translation_options = {
                "include_detailed_results": config["custom_options"].get("include_detailed_results", False)
            }
            
            temp_translation_chain = TranslationChain(
                enable_review=config["review_enabled"],
                enable_improvement=config["improvement_enabled"]
            )
            
            translation_result = await temp_translation_chain.process(segments, translation_options)
            
            if "error" in translation_result:
                return translation_result
            
            translated_segments = translation_result["segments"]
            
            # 번역이 완료된 후 후처리 작업들을 병렬로 실행
            if config["post_processing_enabled"]:
                parallel_tasks = {}
                
                # 요약 작업
                if config["summary_enabled"] and self.post_processing_chain.summarizer:
                    parallel_tasks["summary"] = self._run_summary_task(translated_segments)
                
                # 포맷팅 작업들
                if config["formatting_enabled"] and self.post_processing_chain.formatter:
                    parallel_tasks["formatting"] = self._run_formatting_task(
                        translated_segments, 
                        config["custom_options"]
                    )
                
                # 하이라이트 추출
                if config["highlights_enabled"] and self.post_processing_chain.summarizer:
                    parallel_tasks["highlights"] = self._run_highlights_task(
                        translated_segments,
                        config["custom_options"].get("highlight_count", 3)
                    )
                
                # 병렬 실행
                if parallel_tasks:
                    logger.info(f"Running {len(parallel_tasks)} post-processing tasks in parallel")
                    parallel_results = await asyncio.gather(
                        *parallel_tasks.values(),
                        return_exceptions=True
                    )
                    
                    # 결과 통합
                    integrated_result = self._integrate_parallel_results(
                        translated_segments,
                        parallel_tasks,
                        parallel_results
                    )
                    
                    return {
                        "segments": integrated_result["segments"],
                        "translation_metadata": translation_result.get("metadata", {}),
                        "post_processing_metadata": integrated_result.get("metadata", {})
                    }
            
            # 후처리 없이 번역만
            return {
                "segments": translated_segments,
                "translation_metadata": translation_result.get("metadata", {})
            }
            
        except Exception as e:
            logger.error(f"Parallel processing error: {e}")
            return {
                "error": f"Parallel processing failed: {str(e)}",
                "segments": segments
            }
    
    async def _run_summary_task(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """요약 작업 실행"""
        try:
            summary_result = await self.post_processing_chain.summarizer.summarize_content(segments)
            return {"type": "summary", "result": summary_result}
        except Exception as e:
            return {"type": "summary", "error": str(e)}
    
    async def _run_formatting_task(self, segments: List[Dict[str, Any]], options: Dict[str, Any]) -> Dict[str, Any]:
        """포맷팅 작업 실행"""
        try:
            # 화자 분석
            speaker_analysis = await self.post_processing_chain.formatter.analyze_speakers(segments)
            
            # 자막 포맷팅
            max_chars = options.get("max_chars_per_line", 40)
            formatted_segments = await self.post_processing_chain.formatter.format_subtitles(segments, max_chars)
            
            # 가독성 향상
            enhanced_segments = await self.post_processing_chain.formatter.enhance_readability(formatted_segments)
            
            # 화자 정보 적용
            if "error" not in speaker_analysis:
                final_segments = await self.post_processing_chain.formatter.apply_speaker_formatting(
                    enhanced_segments, speaker_analysis
                )
            else:
                final_segments = enhanced_segments
            
            return {
                "type": "formatting",
                "result": {
                    "segments": final_segments,
                    "speaker_analysis": speaker_analysis
                }
            }
        except Exception as e:
            return {"type": "formatting", "error": str(e)}
    
    async def _run_highlights_task(self, segments: List[Dict[str, Any]], highlight_count: int) -> Dict[str, Any]:
        """하이라이트 추출 작업 실행"""
        try:
            highlights = await self.post_processing_chain.summarizer.extract_highlights(segments, highlight_count)
            return {"type": "highlights", "result": highlights}
        except Exception as e:
            return {"type": "highlights", "error": str(e)}
    
    def _integrate_parallel_results(self, base_segments: List[Dict[str, Any]], 
                                  task_names: Dict[str, Any], 
                                  results: List[Any]) -> Dict[str, Any]:
        """병렬 처리 결과 통합"""
        try:
            final_segments = base_segments
            metadata = {"parallel_tasks": {}}
            
            task_list = list(task_names.keys())
            
            for i, (task_name, result) in enumerate(zip(task_list, results)):
                if isinstance(result, Exception):
                    metadata["parallel_tasks"][task_name] = {"error": str(result)}
                    continue
                
                if result.get("type") == "summary":
                    metadata["summary"] = result.get("result", {})
                elif result.get("type") == "formatting":
                    formatting_result = result.get("result", {})
                    if "segments" in formatting_result:
                        final_segments = formatting_result["segments"]
                    metadata["speaker_analysis"] = formatting_result.get("speaker_analysis", {})
                    metadata["formatting_applied"] = True
                elif result.get("type") == "highlights":
                    metadata["highlights"] = result.get("result", [])
                
                metadata["parallel_tasks"][task_name] = {"status": "completed"}
            
            return {"segments": final_segments, "metadata": metadata}
            
        except Exception as e:
            logger.error(f"Parallel result integration error: {e}")
            return {"segments": base_segments, "metadata": {"integration_error": str(e)}}
    
    def _finalize_result(self, result: Dict[str, Any], mode: ProcessingMode, 
                        processing_time: float, config: Dict[str, Any]) -> Dict[str, Any]:
        """최종 결과 정리"""
        if "error" in result:
            return result
        
        # 최종 메타데이터 구성
        final_metadata = {
            "processing_mode": mode.value,
            "processing_time": processing_time,
            "configuration": {
                "translation_enabled": config["translation_enabled"],
                "review_enabled": config["review_enabled"],
                "improvement_enabled": config["improvement_enabled"],
                "post_processing_enabled": config["post_processing_enabled"],
                "parallel_processing": config["parallel_processing"]
            },
            "chain_info": {
                "translation_chain": self.translation_chain.get_chain_info(),
                "post_processing_chain": self.post_processing_chain.get_chain_info()
            }
        }
        
        # 기존 메타데이터와 병합
        if "translation_metadata" in result:
            final_metadata["translation"] = result["translation_metadata"]
        
        if "post_processing_metadata" in result:
            final_metadata["post_processing"] = result["post_processing_metadata"]
        
        # 처리 통계 계산
        segments = result["segments"]
        stats = self._calculate_master_stats(segments, final_metadata)
        final_metadata["statistics"] = stats
        
        return {
            "segments": segments,
            "metadata": final_metadata
        }
    
    def _calculate_master_stats(self, segments: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """마스터 처리 통계"""
        stats = {
            "total_segments": len(segments),
            "successful_translations": 0,
            "enhanced_segments": 0,
            "speaker_detected_segments": 0,
            "total_processing_time": metadata.get("processing_time", 0.0)
        }
        
        for segment in segments:
            korean_text = segment.get('korean_text', '')
            if korean_text and not korean_text.startswith('['):
                stats["successful_translations"] += 1
            
            if segment.get('enhanced_korean') or segment.get('formatted_korean'):
                stats["enhanced_segments"] += 1
            
            if segment.get('speaker_id'):
                stats["speaker_detected_segments"] += 1
        
        # 성공률 계산
        if stats["total_segments"] > 0:
            stats["translation_success_rate"] = stats["successful_translations"] / stats["total_segments"]
            stats["enhancement_rate"] = stats["enhanced_segments"] / stats["total_segments"]
        else:
            stats["translation_success_rate"] = 0.0
            stats["enhancement_rate"] = 0.0
        
        return stats
    
    async def process_with_fallback(self, segments: List[Dict[str, Any]], 
                                  preferred_mode: ProcessingMode = ProcessingMode.PREMIUM,
                                  fallback_modes: List[ProcessingMode] = None) -> Dict[str, Any]:
        """실패 시 자동 fallback을 지원하는 처리"""
        if fallback_modes is None:
            fallback_modes = [ProcessingMode.STANDARD, ProcessingMode.FAST]
        
        modes_to_try = [preferred_mode] + fallback_modes
        
        for mode in modes_to_try:
            try:
                logger.info(f"Attempting processing with mode: {mode.value}")
                result = await self.process(segments, mode)
                
                if "error" not in result:
                    logger.info(f"Processing succeeded with mode: {mode.value}")
                    return result
                else:
                    logger.warning(f"Processing failed with mode {mode.value}: {result['error']}")
                    
            except Exception as e:
                logger.error(f"Mode {mode.value} failed with exception: {e}")
                continue
        
        # 모든 모드 실패
        logger.error("All processing modes failed")
        return {
            "error": "All processing modes failed",
            "segments": segments,
            "metadata": {
                "attempted_modes": [mode.value for mode in modes_to_try],
                "fallback_exhausted": True
            }
        }
    
    def get_chain_info(self) -> Dict[str, Any]:
        """마스터 체인 정보"""
        return {
            "chain_type": "master_chain",
            "available": self.is_available(),
            "processing_modes": [mode.value for mode in ProcessingMode],
            "sub_chains": {
                "translation_chain": self.translation_chain.get_chain_info(),
                "post_processing_chain": self.post_processing_chain.get_chain_info()
            },
            "capabilities": [
                "sequential_processing",
                "parallel_processing", 
                "conditional_branching",
                "fallback_processing",
                "custom_workflows"
            ]
        }