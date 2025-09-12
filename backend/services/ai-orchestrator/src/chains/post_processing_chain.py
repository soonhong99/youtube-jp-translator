"""
후처리 체인 - 요약, 포맷팅, 메타데이터 생성을 통합한 워크플로우
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from langchain_core.runnables import RunnablePassthrough, RunnableLambda, RunnableParallel

from ..agents.summarizer import SummarizerAgent
from ..agents.formatter import FormatterAgent
from ..config import MAX_CONCURRENT_TASKS

logger = logging.getLogger(__name__)

class PostProcessingChain:
    """번역 후처리 통합 체인 (요약, 포맷팅, 메타데이터)"""
    
    def __init__(self, enable_summary: bool = True, enable_formatting: bool = True, enable_highlights: bool = True):
        self.enable_summary = enable_summary
        self.enable_formatting = enable_formatting
        self.enable_highlights = enable_highlights
        
        # 에이전트 초기화
        self.summarizer = SummarizerAgent() if enable_summary else None
        self.formatter = FormatterAgent() if enable_formatting else None
        
        # 체인 구성
        self._build_chain()
    
    def _build_chain(self):
        """후처리 체인 구성"""
        try:
            # 병렬 처리 가능한 작업들
            parallel_tasks = {}
            
            # 요약 작업
            if self.enable_summary and self.summarizer and self.summarizer.is_available():
                parallel_tasks["summary"] = RunnableLambda(self._generate_summary)
                
                if self.enable_highlights:
                    parallel_tasks["highlights"] = RunnableLambda(self._extract_highlights)
            
            # 포맷팅 작업
            if self.enable_formatting and self.formatter and self.formatter.is_available():
                parallel_tasks["korean_resegmentation"] = RunnableLambda(self._korean_sentence_segmentation)
                parallel_tasks["speaker_analysis"] = RunnableLambda(self._analyze_speakers)
                parallel_tasks["subtitle_formatting"] = RunnableLambda(self._format_subtitles)
                parallel_tasks["readability_enhancement"] = RunnableLambda(self._enhance_readability)
            
            # 병렬 실행 체인 구성
            if parallel_tasks:
                self.parallel_chain = RunnableParallel(**parallel_tasks)
            else:
                self.parallel_chain = None
            
            # 후처리 통합 체인
            self.main_chain = (
                RunnablePassthrough()
                | RunnableLambda(self._prepare_input)
                | (self.parallel_chain if self.parallel_chain else RunnableLambda(self._passthrough))
                | RunnableLambda(self._integrate_results)
            )
            
            logger.info(f"Post-processing chain built with {len(parallel_tasks)} parallel tasks")
            
        except Exception as e:
            logger.error(f"Failed to build post-processing chain: {e}")
            self.main_chain = None
    
    def is_available(self) -> bool:
        """체인 사용 가능 여부"""
        return self.main_chain is not None
    
    async def process(self, segments: List[Dict[str, Any]], options: Dict[str, Any] = None) -> Dict[str, Any]:
        """후처리 파이프라인 실행"""
        if not self.is_available():
            return {
                "error": "Post-processing chain not available",
                "segments": segments,
                "metadata": {"chain_available": False}
            }
        
        options = options or {}
        start_time = asyncio.get_event_loop().time()
        
        try:
            logger.info(f"Starting post-processing chain for {len(segments)} segments")
            
            # 후처리 실행
            result = await self.main_chain.ainvoke({
                "segments": segments,
                "options": options
            })
            
            if "error" in result:
                return result
            
            processing_time = asyncio.get_event_loop().time() - start_time
            result["metadata"]["processing_time"] = processing_time
            
            logger.info(f"Post-processing chain completed in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Post-processing chain error: {e}")
            return {
                "error": f"Post-processing failed: {str(e)}",
                "segments": segments,
                "metadata": {"processing_time": asyncio.get_event_loop().time() - start_time}
            }
    
    async def _prepare_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """입력 데이터 준비"""
        return input_data
    
    async def _passthrough(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """병렬 체인이 없을 때의 패스스루"""
        return input_data
    
    async def _generate_summary(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """콘텐츠 요약 생성"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            summary_result = await self.summarizer.summarize_content(segments)
            
            return {
                "summary_data": summary_result,
                "summary_available": "error" not in summary_result
            }
            
        except Exception as e:
            logger.error(f"Summary generation error: {e}")
            return {
                "summary_data": {"error": str(e)},
                "summary_available": False
            }
    
    async def _extract_highlights(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """핵심 구간 추출"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            highlight_count = options.get("highlight_count", 3)
            highlights = await self.summarizer.extract_highlights(segments, highlight_count)
            
            return {
                "highlights": highlights,
                "highlight_count": len(highlights)
            }
            
        except Exception as e:
            logger.error(f"Highlight extraction error: {e}")
            return {
                "highlights": [],
                "highlight_count": 0,
                "error": str(e)
            }
    
    async def _analyze_speakers(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """화자 분석"""
        segments = input_data["segments"]
        
        try:
            speaker_analysis = await self.formatter.analyze_speakers(segments)
            
            return {
                "speaker_analysis": speaker_analysis,
                "speaker_detection_available": "error" not in speaker_analysis
            }
            
        except Exception as e:
            logger.error(f"Speaker analysis error: {e}")
            return {
                "speaker_analysis": {"error": str(e)},
                "speaker_detection_available": False
            }
    
    async def _format_subtitles(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """자막 포맷팅"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            max_chars = options.get("max_chars_per_line", 40)
            formatted_segments = await self.formatter.format_subtitles(segments, max_chars)
            
            return {
                "formatted_segments": formatted_segments,
                "subtitle_formatting_applied": True
            }
            
        except Exception as e:
            logger.error(f"Subtitle formatting error: {e}")
            return {
                "formatted_segments": segments,
                "subtitle_formatting_applied": False,
                "error": str(e)
            }
    
    async def _enhance_readability(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """가독성 향상"""
        segments = input_data["segments"]
        
        try:
            enhanced_segments = await self.formatter.enhance_readability(segments)
            
            return {
                "enhanced_segments": enhanced_segments,
                "readability_enhanced": True
            }
            
        except Exception as e:
            logger.error(f"Readability enhancement error: {e}")
            return {
                "enhanced_segments": segments,
                "readability_enhanced": False,
                "error": str(e)
            }
    
    async def _korean_sentence_segmentation(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """번역된 한국어 텍스트 재분할"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            refined_segments = []
            segmentation_applied_count = 0
            
            for segment in segments:
                korean_text = segment.get('korean_text', '').strip()
                
                # 번역 실패한 세그먼트는 그대로 유지
                if not korean_text or korean_text.startswith('['):
                    refined_segments.append(segment)
                    continue
                
                # 한국어 문장 분할 적용
                sub_sentences = self._split_korean_sentence(korean_text)
                
                if len(sub_sentences) > 1:
                    # 여러 문장으로 분할된 경우 시간 분배
                    duration = segment.get('end', 0) - segment.get('start', 0)
                    time_per_sentence = duration / len(sub_sentences)
                    
                    for i, sub_text in enumerate(sub_sentences):
                        sub_segment = segment.copy()
                        sub_segment['korean_text'] = sub_text.strip()
                        sub_segment['original_korean_text'] = korean_text  # 원본 보존
                        sub_segment['start'] = segment['start'] + (i * time_per_sentence)
                        sub_segment['end'] = segment['start'] + ((i + 1) * time_per_sentence)
                        sub_segment['segmentation_applied'] = True
                        refined_segments.append(sub_segment)
                    
                    segmentation_applied_count += 1
                else:
                    # 분할되지 않은 경우 원본 그대로
                    segment_copy = segment.copy()
                    segment_copy['segmentation_applied'] = False
                    refined_segments.append(segment_copy)
            
            logger.info(f"Korean resegmentation: {segmentation_applied_count} segments split into {len(refined_segments)} total")
            
            return {
                "refined_segments": refined_segments,
                "segmentation_applied": True,
                "original_segment_count": len(segments),
                "final_segment_count": len(refined_segments),
                "split_applied_count": segmentation_applied_count
            }
            
        except Exception as e:
            logger.error(f"Korean sentence segmentation error: {e}")
            return {
                "refined_segments": segments,
                "segmentation_applied": False,
                "error": str(e)
            }
    
    def _split_korean_sentence(self, text: str) -> List[str]:
        """한국어 문장 분할 (간단한 규칙 기반)"""
        if not text or len(text) < 20:
            return [text]
        
        import re
        
        # 한국어 문장 종료 패턴들
        split_patterns = [
            r'([다요])\s*[.!?]?\s*([가-힣])',     # 다/요 + 다음문장
            r'(니다)\s*[.!?]?\s*([가-힣])',       # 니다 + 다음문장  
            r'(습니다)\s*[.!?]?\s*([가-힣])',     # 습니다 + 다음문장
            r'(네요)\s*[.!?]?\s*([가-힣])',       # 네요 + 다음문장
            r'(죠)\s*[.!?]?\s*([가-힣])',         # 죠 + 다음문장
            r'([.!?])\s*([가-힣])',               # 문장부호 + 한글
        ]
        
        for pattern in split_patterns:
            if re.search(pattern, text):
                # 분할 지점 찾기
                parts = re.split(pattern, text)
                if len(parts) > 3:  # 성공적으로 분할됨
                    sentences = []
                    current_sentence = ""
                    
                    for i, part in enumerate(parts):
                        if part.strip():
                            if i % 3 == 0:  # 첫 번째 부분
                                current_sentence += part
                            elif i % 3 == 1:  # 종료 패턴
                                current_sentence += part
                                if current_sentence.strip():
                                    sentences.append(current_sentence.strip())
                                current_sentence = ""
                            else:  # 다음 문장 시작
                                current_sentence = part
                    
                    if current_sentence.strip():
                        sentences.append(current_sentence.strip())
                    
                    # 유효한 분할인지 확인 (너무 짧은 문장 방지)
                    valid_sentences = [s for s in sentences if len(s) > 5]
                    if len(valid_sentences) > 1:
                        return valid_sentences
        
        # 분할 실패 시 원문 반환
        return [text]
    
    async def _integrate_results(self, parallel_results: Dict[str, Any]) -> Dict[str, Any]:
        """병렬 처리 결과 통합"""
        if isinstance(parallel_results, dict) and "segments" in parallel_results:
            # passthrough인 경우
            return {
                "segments": parallel_results["segments"],
                "metadata": {
                    "summary": None,
                    "highlights": [],
                    "speaker_analysis": None,
                    "formatting_applied": False,
                    "post_processing_steps": []
                }
            }
        
        try:
            # 원본 세그먼트 가져오기
            input_data = parallel_results.get("segments") or parallel_results
            segments = None
            options = {}
            
            if isinstance(input_data, dict) and "segments" in input_data:
                segments = input_data["segments"]
                options = input_data.get("options", {})
            else:
                # 병렬 결과에서 세그먼트 추출
                for key, value in parallel_results.items():
                    if isinstance(value, dict):
                        if "segments" in value:
                            segments = value["segments"]
                            break
                        elif "formatted_segments" in value:
                            segments = value["formatted_segments"]
                            break
                        elif "enhanced_segments" in value:
                            segments = value["enhanced_segments"]
                            break
                
                # 추가 로깅으로 디버깅
                if segments is None:
                    logger.error(f"No segments found. parallel_results keys: {list(parallel_results.keys())}")
                    logger.error(f"parallel_results content: {parallel_results}")
                    raise ValueError("No segments found in parallel results")
                
                options = {}
            
            # 최종 세그먼트 결정 (우선순위: korean_resegmentation > enhanced > formatted > original)
            final_segments = segments
            if "korean_resegmentation" in parallel_results:
                resegmentation_result = parallel_results["korean_resegmentation"]
                if resegmentation_result.get("segmentation_applied", False):
                    final_segments = resegmentation_result["refined_segments"]
                    logger.info(f"Using Korean resegmented segments: {len(final_segments)} segments")
            elif "readability_enhancement" in parallel_results:
                enhancement_result = parallel_results["readability_enhancement"]
                if enhancement_result.get("readability_enhanced", False):
                    final_segments = enhancement_result["enhanced_segments"]
            elif "subtitle_formatting" in parallel_results:
                formatting_result = parallel_results["subtitle_formatting"]
                if formatting_result.get("subtitle_formatting_applied", False):
                    final_segments = formatting_result["formatted_segments"]
            
            # 화자 정보 적용
            if "speaker_analysis" in parallel_results:
                speaker_result = parallel_results["speaker_analysis"]
                if speaker_result.get("speaker_detection_available", False):
                    speaker_analysis = speaker_result["speaker_analysis"]
                    final_segments = await self.formatter.apply_speaker_formatting(
                        final_segments, speaker_analysis
                    )
            
            # 메타데이터 구성
            metadata = {
                "post_processing_steps": list(parallel_results.keys()),
                "summary": parallel_results.get("summary", {}).get("summary_data"),
                "highlights": parallel_results.get("highlights", {}).get("highlights", []),
                "speaker_analysis": parallel_results.get("speaker_analysis", {}).get("speaker_analysis"),
                "formatting_applied": parallel_results.get("subtitle_formatting", {}).get("subtitle_formatting_applied", False),
                "readability_enhanced": parallel_results.get("readability_enhancement", {}).get("readability_enhanced", False),
                "agents_used": {
                    "summarizer": self.summarizer.get_agent_info() if self.summarizer else None,
                    "formatter": self.formatter.get_agent_info() if self.formatter else None
                }
            }
            
            # 처리 통계
            stats = self._calculate_processing_stats(final_segments, metadata)
            metadata["processing_stats"] = stats
            
            return {
                "segments": final_segments,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"Result integration error: {e}")
            # 원본 세그먼트라도 반환
            fallback_segments = []
            for value in parallel_results.values():
                if isinstance(value, dict) and "segments" in value:
                    fallback_segments = value["segments"]
                    break
            
            return {
                "segments": fallback_segments,
                "metadata": {
                    "error": f"Result integration failed: {str(e)}",
                    "post_processing_steps": []
                }
            }
    
    def _calculate_processing_stats(self, segments: List[Dict[str, Any]], metadata: Dict[str, Any]) -> Dict[str, Any]:
        """처리 통계 계산"""
        stats = {
            "total_segments": len(segments),
            "translated_segments": 0,
            "formatted_segments": 0,
            "enhanced_segments": 0,
            "speaker_detected_segments": 0,
            "total_duration": 0.0,
            "total_characters": 0
        }
        
        for segment in segments:
            # 번역된 세그먼트 수
            korean_text = segment.get('korean_text', '')
            if korean_text and not korean_text.startswith('['):
                stats["translated_segments"] += 1
                stats["total_characters"] += len(korean_text)
            
            # 포맷팅된 세그먼트 수
            if segment.get('formatted_korean'):
                stats["formatted_segments"] += 1
            
            # 향상된 세그먼트 수
            if segment.get('enhanced_korean'):
                stats["enhanced_segments"] += 1
            
            # 화자가 인식된 세그먼트 수
            if segment.get('speaker_id'):
                stats["speaker_detected_segments"] += 1
            
            # 총 재생 시간
            if segment.get('end') and segment.get('start'):
                stats["total_duration"] += segment['end'] - segment['start']
        
        # 요약 통계
        summary_data = metadata.get("summary", {})
        if summary_data and "error" not in summary_data:
            stats["summary_available"] = True
            stats["keyword_count"] = len(summary_data.get("keywords", []))
            stats["topic_count"] = len(summary_data.get("topics", []))
        else:
            stats["summary_available"] = False
            stats["keyword_count"] = 0
            stats["topic_count"] = 0
        
        # 하이라이트 통계
        highlights = metadata.get("highlights", [])
        stats["highlight_count"] = len(highlights)
        
        return stats
    
    async def process_with_custom_options(self, segments: List[Dict[str, Any]], 
                                        custom_options: Dict[str, Any]) -> Dict[str, Any]:
        """커스텀 옵션을 사용한 처리"""
        # 기본 옵션과 커스텀 옵션 병합
        options = {
            "max_chars_per_line": 40,
            "highlight_count": 3,
            "include_speaker_detection": True,
            "enhance_readability": True,
            **custom_options
        }
        
        return await self.process(segments, options)
    
    def get_chain_info(self) -> Dict[str, Any]:
        """체인 정보 반환"""
        return {
            "chain_type": "post_processing_chain",
            "available": self.is_available(),
            "features": {
                "summary": self.enable_summary and self.summarizer is not None,
                "formatting": self.enable_formatting and self.formatter is not None,
                "highlights": self.enable_highlights and self.summarizer is not None,
                "speaker_detection": self.enable_formatting and self.formatter is not None,
                "readability_enhancement": self.enable_formatting and self.formatter is not None
            },
            "agents": {
                "summarizer": self.summarizer.get_agent_info() if self.summarizer else None,
                "formatter": self.formatter.get_agent_info() if self.formatter else None
            }
        }