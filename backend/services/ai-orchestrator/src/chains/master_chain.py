"""
마스터 체인 - 번역과 후처리를 통합하는 최상위 워크플로우
조건부 분기, 병렬 처리, 에러 복구 등 고급 오케스트레이션 기능 제공
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel

from .translation_chain import TranslationChain
from .post_processing_chain import PostProcessingChain
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
        # 하위 체인들 초기화
        self.translation_chain = TranslationChain(enable_review=True, enable_improvement=True)
        self.post_processing_chain = PostProcessingChain(
            enable_summary=True, 
            enable_formatting=True, 
            enable_highlights=True
        )
        
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
            
            logger.info(f"Chain validation: translation={translation_ok}, post_processing={post_processing_ok}")
            
            return translation_ok  # 번역은 필수, 후처리는 선택적
            
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