"""
번역 체인 - 번역, 검토, 개선을 통합한 복합 워크플로우
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.runnables.utils import Input, Output

from ..agents.translator import TranslatorAgent
from ..agents.reviewer import ReviewerAgent
from ..config import MAX_CONCURRENT_TASKS

logger = logging.getLogger(__name__)

class TranslationChain:
    """번역 + 품질 검토 + 개선 통합 체인"""
    
    def __init__(self, enable_review: bool = True, enable_improvement: bool = True):
        self.enable_review = enable_review
        self.enable_improvement = enable_improvement
        
        # 에이전트 초기화
        self.translator = TranslatorAgent()
        self.reviewer = ReviewerAgent() if enable_review else None
        
        # 체인 구성
        self._build_chain()
    
    def _build_chain(self):
        """체인 구성"""
        try:
            # 기본 번역 체인
            self.base_chain = (
                RunnablePassthrough()
                | RunnableLambda(self._translate_segments)
            )
            
            # 리뷰 체인 (선택적)
            if self.enable_review and self.reviewer and self.reviewer.is_available():
                self.review_chain = (
                    RunnablePassthrough()
                    | RunnableLambda(self._review_translation)
                )
                
                # 개선 체인 (선택적)
                if self.enable_improvement:
                    self.improvement_chain = (
                        RunnablePassthrough()
                        | RunnableLambda(self._improve_translation)
                    )
                else:
                    self.improvement_chain = None
            else:
                self.review_chain = None
                self.improvement_chain = None
            
            logger.info(f"Translation chain built: review={self.enable_review}, improvement={self.enable_improvement}")
            
        except Exception as e:
            logger.error(f"Failed to build translation chain: {e}")
            self.base_chain = None
    
    def is_available(self) -> bool:
        """체인 사용 가능 여부"""
        return (self.translator and self.translator.is_available() and 
                self.base_chain is not None)
    
    async def process(self, segments: List[Dict[str, Any]], options: Dict[str, Any] = None) -> Dict[str, Any]:
        """전체 번역 파이프라인 실행"""
        if not self.is_available():
            return {
                "error": "Translation chain not available",
                "segments": segments,
                "metadata": {"chain_available": False}
            }
        
        options = options or {}
        start_time = asyncio.get_event_loop().time()
        
        try:
            logger.info(f"Starting translation chain for {len(segments)} segments")
            
            # 1. 기본 번역
            translation_result = await self.base_chain.ainvoke({
                "segments": segments,
                "options": options
            })
            
            if "error" in translation_result:
                return translation_result
            
            translated_segments = translation_result["segments"]
            
            # 2. 품질 검토 (선택적)
            review_result = None
            if self.review_chain:
                logger.info("Starting quality review...")
                review_input = {
                    "segments": translated_segments,
                    "options": options
                }
                review_result = await self.review_chain.ainvoke(review_input)
                
                if "error" not in review_result:
                    translated_segments = review_result["segments"]
            
            # 3. 개선 적용 (선택적)
            improvement_result = None
            if self.improvement_chain and review_result and "error" not in review_result:
                needs_improvement = any(
                    segment.get("needs_revision", False) 
                    for segment in review_result.get("review_results", [])
                )
                
                if needs_improvement:
                    logger.info("Starting translation improvement...")
                    improvement_input = {
                        "segments": translated_segments,
                        "review_results": review_result.get("review_results", []),
                        "options": options
                    }
                    improvement_result = await self.improvement_chain.ainvoke(improvement_input)
                    
                    if "error" not in improvement_result:
                        translated_segments = improvement_result["segments"]
            
            # 결과 종합
            processing_time = asyncio.get_event_loop().time() - start_time
            
            result = {
                "segments": translated_segments,
                "metadata": {
                    "processing_time": processing_time,
                    "chain_steps": {
                        "translation": True,
                        "review": review_result is not None and "error" not in review_result,
                        "improvement": improvement_result is not None and "error" not in improvement_result
                    },
                    "quality_metrics": self._extract_quality_metrics(review_result),
                    "agent_info": {
                        "translator": self.translator.get_agent_info(),
                        "reviewer": self.reviewer.get_agent_info() if self.reviewer else None
                    }
                }
            }
            
            # 상세 결과 추가 (옵션)
            if options.get("include_detailed_results", False):
                result["detailed_results"] = {
                    "translation_result": translation_result,
                    "review_result": review_result,
                    "improvement_result": improvement_result
                }
            
            logger.info(f"Translation chain completed in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Translation chain processing error: {e}")
            return {
                "error": f"Chain processing failed: {str(e)}",
                "segments": segments,
                "metadata": {"processing_time": asyncio.get_event_loop().time() - start_time}
            }
    
    async def _translate_segments(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """번역 실행"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            translated_segments = await self.translator.translate_segments(segments)
            
            return {
                "segments": translated_segments,
                "translation_info": {
                    "agent": self.translator.get_agent_info(),
                    "segment_count": len(translated_segments)
                }
            }
            
        except Exception as e:
            logger.error(f"Translation step error: {e}")
            return {
                "error": f"Translation failed: {str(e)}",
                "segments": segments
            }
    
    async def _review_translation(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """번역 품질 검토"""
        segments = input_data["segments"]
        options = input_data.get("options", {})
        
        try:
            # 품질 검토 실행
            review_results = await self.reviewer.review_translation_quality(segments)
            
            # 검토 결과를 세그먼트에 통합
            reviewed_segments = []
            for i, (segment, review) in enumerate(zip(segments, review_results)):
                reviewed_segment = segment.copy()
                reviewed_segment["review"] = review
                
                # 품질 점수가 낮은 세그먼트 표시
                if review.get("reviewable", False):
                    quality_scores = review.get("quality_scores", {})
                    overall_score = quality_scores.get("overall", 8.0)
                    
                    if overall_score < self.reviewer.quality_threshold:
                        reviewed_segment["needs_revision"] = True
                        reviewed_segment["quality_issues"] = review.get("issues", [])
                
                reviewed_segments.append(reviewed_segment)
            
            # 전체 품질 메트릭 계산
            overall_metrics = self._calculate_overall_quality(review_results)
            
            return {
                "segments": reviewed_segments,
                "review_results": review_results,
                "quality_metrics": overall_metrics
            }
            
        except Exception as e:
            logger.error(f"Review step error: {e}")
            return {
                "error": f"Review failed: {str(e)}",
                "segments": segments
            }
    
    async def _improve_translation(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """번역 개선"""
        segments = input_data["segments"]
        review_results = input_data.get("review_results", [])
        options = input_data.get("options", {})
        
        try:
            # 개선이 필요한 세그먼트만 처리
            improved_segments = await self.reviewer.suggest_improvements(segments, review_results)
            
            # 개선 통계
            improvement_count = sum(
                1 for segment in improved_segments 
                if segment.get("improvement_applied", False)
            )
            
            return {
                "segments": improved_segments,
                "improvement_info": {
                    "segments_improved": improvement_count,
                    "total_segments": len(improved_segments)
                }
            }
            
        except Exception as e:
            logger.error(f"Improvement step error: {e}")
            return {
                "error": f"Improvement failed: {str(e)}",
                "segments": segments
            }
    
    def _calculate_overall_quality(self, review_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """전체 품질 메트릭 계산"""
        reviewable_results = [
            result for result in review_results 
            if result.get("reviewable", False) and "quality_scores" in result
        ]
        
        if not reviewable_results:
            return {"overall_score": 8.0, "reviewable_segments": 0}
        
        # 평균 점수 계산
        total_scores = {
            "accuracy": 0.0,
            "naturalness": 0.0,
            "fluency": 0.0,
            "consistency": 0.0,
            "overall": 0.0
        }
        
        for result in reviewable_results:
            quality_scores = result["quality_scores"]
            for key in total_scores:
                total_scores[key] += quality_scores.get(key, 8.0)
        
        count = len(reviewable_results)
        average_scores = {key: round(score / count, 2) for key, score in total_scores.items()}
        
        # 품질 등급 결정
        overall_avg = average_scores["overall"]
        if overall_avg >= 9.0:
            quality_grade = "Excellent"
        elif overall_avg >= 8.0:
            quality_grade = "Good"
        elif overall_avg >= 7.0:
            quality_grade = "Fair"
        elif overall_avg >= 6.0:
            quality_grade = "Poor"
        else:
            quality_grade = "Very Poor"
        
        return {
            "average_scores": average_scores,
            "quality_grade": quality_grade,
            "reviewable_segments": count,
            "total_segments": len(review_results)
        }
    
    def _extract_quality_metrics(self, review_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """품질 메트릭 추출"""
        if not review_result or "error" in review_result:
            return {"available": False}
        
        return review_result.get("quality_metrics", {"available": False})
    
    async def process_batch(self, batch_requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """배치 처리 (여러 요청을 동시에)"""
        if not self.is_available():
            return [{"error": "Translation chain not available"} for _ in batch_requests]
        
        # 동시 처리 제한
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        
        async def process_single(request):
            async with semaphore:
                return await self.process(
                    request.get("segments", []),
                    request.get("options", {})
                )
        
        try:
            # 모든 요청을 동시에 처리
            results = await asyncio.gather(
                *[process_single(request) for request in batch_requests],
                return_exceptions=True
            )
            
            # 예외 처리
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append({
                        "error": f"Batch processing failed: {str(result)}",
                        "segments": batch_requests[i].get("segments", [])
                    })
                else:
                    processed_results.append(result)
            
            logger.info(f"Batch processing completed: {len(batch_requests)} requests")
            return processed_results
            
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            return [{"error": f"Batch processing failed: {str(e)}"} for _ in batch_requests]
    
    def get_chain_info(self) -> Dict[str, Any]:
        """체인 정보 반환"""
        return {
            "chain_type": "translation_chain",
            "available": self.is_available(),
            "features": {
                "translation": True,
                "review": self.enable_review and self.reviewer is not None,
                "improvement": self.enable_improvement and self.reviewer is not None
            },
            "agents": {
                "translator": self.translator.get_agent_info() if self.translator else None,
                "reviewer": self.reviewer.get_agent_info() if self.reviewer else None
            }
        }