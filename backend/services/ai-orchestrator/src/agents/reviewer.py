"""
리뷰어 에이전트 - 번역 품질 검증 및 개선 제안
"""
import logging
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field

from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TEMPERATURE

logger = logging.getLogger(__name__)

class QualityScore(BaseModel):
    """품질 점수 모델"""
    accuracy: float = Field(description="정확성 점수 (0.0-10.0)")
    naturalness: float = Field(description="자연스러움 점수 (0.0-10.0)")
    fluency: float = Field(description="유창성 점수 (0.0-10.0)")
    consistency: float = Field(description="일관성 점수 (0.0-10.0)")
    overall: float = Field(description="전체 점수 (0.0-10.0)")

class ReviewResult(BaseModel):
    """리뷰 결과 모델"""
    segment_index: int = Field(description="세그먼트 인덱스")
    quality_scores: QualityScore = Field(description="품질 점수")
    issues: List[str] = Field(description="발견된 문제점들")
    suggestions: List[str] = Field(description="개선 제안들")
    needs_revision: bool = Field(description="재번역 필요 여부")
    confidence: float = Field(description="리뷰 신뢰도 (0.0-1.0)")

class ReviewerAgent:
    """번역 품질 검증 및 개선 제안 에이전트"""
    
    def __init__(self, model_name: str = None, temperature: float = None):
        self.model_name = model_name or GEMINI_MODEL
        self.temperature = temperature or (GEMINI_TEMPERATURE + 0.1)  # 리뷰어는 약간 더 창의적
        self.llm = None
        self.quality_threshold = 6.0  # 재번역 기준점
        self._initialize_chains()
    
    def _initialize_chains(self) -> bool:
        """리뷰 체인 초기화"""
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not found. Reviewer agent will be disabled.")
            return False
        
        try:
            # LangChain Gemini 모델 초기화
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                google_api_key=GEMINI_API_KEY
            )
            
            logger.info(f"Reviewer agent initialized with model: {self.model_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize reviewer chains: {e}")
            return False
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부"""
        return self.llm is not None
    
    async def review_translation_quality(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """번역 품질 종합 검토"""
        if not self.is_available():
            return [{"error": "Reviewer agent not available"} for _ in segments]
        
        if not segments:
            return []
        
        try:
            review_results = []
            
            # 각 세그먼트 개별 리뷰
            for i, segment in enumerate(segments):
                japanese_text = segment.get('text', '').strip()
                korean_text = segment.get('korean_text', '').strip()
                
                if not japanese_text or not korean_text or korean_text.startswith('['):
                    # 리뷰할 수 없는 세그먼트
                    review_results.append({
                        "segment_index": i,
                        "reviewable": False,
                        "reason": "No valid translation to review"
                    })
                    continue
                
                # 개별 세그먼트 리뷰
                review_result = await self._review_single_segment(i, japanese_text, korean_text)
                review_results.append(review_result)
            
            # 전체적인 일관성 검토
            consistency_review = await self._review_overall_consistency(segments, review_results)
            
            # 결과 통합
            final_results = self._integrate_review_results(review_results, consistency_review)
            
            logger.info(f"Translation quality review completed for {len(segments)} segments")
            return final_results
            
        except Exception as e:
            logger.error(f"Translation quality review error: {e}")
            return [{"error": f"Review failed: {str(e)}"} for _ in segments]
    
    async def _review_single_segment(self, index: int, japanese_text: str, korean_text: str) -> Dict[str, Any]:
        """단일 세그먼트 리뷰"""
        try:
            # 품질 평가 프롬프트
            quality_prompt = ChatPromptTemplate.from_template("""
            다음 일본어-한국어 번역의 품질을 전문적으로 평가해주세요.

            평가 기준:
            1. 정확성 (Accuracy): 원문의 의미가 정확히 전달되었는가?
            2. 자연스러움 (Naturalness): 한국어로서 자연스러운가?
            3. 유창성 (Fluency): 문법과 어법이 올바른가?
            4. 일관성 (Consistency): 용어와 문체가 일관적인가?

            일본어 원문: {japanese_text}
            한국어 번역: {korean_text}

            다음 JSON 형식으로 평가 결과를 제공해주세요:
            {{
                "quality_scores": {{
                    "accuracy": 8.5,
                    "naturalness": 7.0,
                    "fluency": 9.0,
                    "consistency": 8.0,
                    "overall": 8.1
                }},
                "issues": ["문제점1", "문제점2"],
                "suggestions": ["개선안1", "개선안2"],
                "needs_revision": false,
                "confidence": 0.85,
                "detailed_feedback": "상세한 피드백"
            }}
            """)
            
            quality_chain = (
                quality_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await quality_chain.ainvoke({
                "japanese_text": japanese_text,
                "korean_text": korean_text
            })
            
            # 결과에 인덱스 추가
            result["segment_index"] = index
            result["reviewable"] = True
            
            # 재번역 필요성 판단
            overall_score = result.get("quality_scores", {}).get("overall", 5.0)
            if overall_score < self.quality_threshold:
                result["needs_revision"] = True
            
            return result
            
        except Exception as e:
            logger.error(f"Single segment review error (index {index}): {e}")
            return {
                "segment_index": index,
                "reviewable": False,
                "error": str(e)
            }
    
    async def _review_overall_consistency(self, segments: List[Dict[str, Any]], individual_reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
        """전체 번역의 일관성 검토"""
        try:
            # 번역된 텍스트들만 추출
            korean_texts = []
            for segment in segments:
                korean_text = segment.get('korean_text', '').strip()
                if korean_text and not korean_text.startswith('['):
                    korean_texts.append(korean_text)
            
            if len(korean_texts) < 2:
                return {"consistency_score": 10.0, "issues": [], "suggestions": []}
            
            # 일관성 검토 프롬프트
            consistency_prompt = ChatPromptTemplate.from_template("""
            다음은 하나의 영상에서 추출한 번역 텍스트들입니다. 
            전체적인 번역 일관성을 평가해주세요.

            검토 항목:
            1. 용어 사용의 일관성
            2. 존댓말/반말 사용의 일관성
            3. 번역 스타일의 일관성
            4. 문체의 통일성

            번역 텍스트들:
            {korean_texts}

            JSON 형식으로 평가 결과를 제공해주세요:
            {{
                "consistency_score": 8.5,
                "terminology_issues": ["용어 불일치 사례"],
                "style_issues": ["문체 불일치 사례"],
                "suggestions": ["개선 제안들"],
                "overall_feedback": "전체적인 피드백"
            }}
            """)
            
            consistency_chain = (
                consistency_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await consistency_chain.ainvoke({
                "korean_texts": "\n".join([f"{i+1}. {text}" for i, text in enumerate(korean_texts)])
            })
            
            return result
            
        except Exception as e:
            logger.error(f"Overall consistency review error: {e}")
            return {
                "consistency_score": 5.0,
                "error": str(e)
            }
    
    def _integrate_review_results(self, individual_reviews: List[Dict[str, Any]], consistency_review: Dict[str, Any]) -> List[Dict[str, Any]]:
        """개별 리뷰와 전체 일관성 리뷰 통합"""
        integrated_results = []
        
        consistency_score = consistency_review.get("consistency_score", 8.0)
        consistency_issues = consistency_review.get("terminology_issues", []) + consistency_review.get("style_issues", [])
        
        for review in individual_reviews:
            if not review.get("reviewable", False):
                integrated_results.append(review)
                continue
            
            # 일관성 점수를 개별 점수에 반영
            quality_scores = review.get("quality_scores", {})
            if "consistency" in quality_scores:
                # 일관성 점수 조정
                original_consistency = quality_scores["consistency"]
                adjusted_consistency = (original_consistency + consistency_score) / 2
                quality_scores["consistency"] = round(adjusted_consistency, 1)
                
                # 전체 점수 재계산
                scores = [
                    quality_scores.get("accuracy", 8.0),
                    quality_scores.get("naturalness", 8.0),
                    quality_scores.get("fluency", 8.0),
                    adjusted_consistency
                ]
                quality_scores["overall"] = round(sum(scores) / len(scores), 1)
            
            # 일관성 이슈 추가
            issues = review.get("issues", [])
            for issue in consistency_issues:
                if issue not in issues:
                    issues.append(f"[일관성] {issue}")
            
            review["quality_scores"] = quality_scores
            review["issues"] = issues
            review["consistency_review"] = consistency_review
            
            integrated_results.append(review)
        
        return integrated_results
    
    async def suggest_improvements(self, segments: List[Dict[str, Any]], review_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """개선 제안 생성"""
        if not self.is_available():
            return segments
        
        try:
            improved_segments = []
            
            for i, (segment, review) in enumerate(zip(segments, review_results)):
                improved_segment = segment.copy()
                
                if not review.get("reviewable", False) or not review.get("needs_revision", False):
                    improved_segments.append(improved_segment)
                    continue
                
                # 개선된 번역 제안
                japanese_text = segment.get('text', '')
                korean_text = segment.get('korean_text', '')
                issues = review.get('issues', [])
                suggestions = review.get('suggestions', [])
                
                improvement_prompt = ChatPromptTemplate.from_template("""
                다음 번역을 검토 결과를 바탕으로 개선해주세요.

                일본어 원문: {japanese_text}
                현재 번역: {korean_text}
                
                발견된 문제점:
                {issues}
                
                개선 제안:
                {suggestions}

                개선된 한국어 번역만 제공해주세요 (부연 설명 없이):
                """)
                
                improvement_chain = (
                    improvement_prompt
                    | self.llm
                )
                
                improved_translation = await improvement_chain.ainvoke({
                    "japanese_text": japanese_text,
                    "korean_text": korean_text,
                    "issues": "\n".join(issues),
                    "suggestions": "\n".join(suggestions)
                })
                
                improved_segment["improved_korean"] = improved_translation.content.strip()
                improved_segment["original_korean"] = korean_text
                improved_segment["improvement_applied"] = True
                
                improved_segments.append(improved_segment)
            
            logger.info(f"Generated improvements for segments that needed revision")
            return improved_segments
            
        except Exception as e:
            logger.error(f"Improvement suggestion error: {e}")
            return segments
    
    async def validate_terminology(self, segments: List[Dict[str, Any]], domain_keywords: List[str] = None) -> Dict[str, Any]:
        """용어 사용 검증"""
        if not self.is_available():
            return {"error": "Reviewer agent not available"}
        
        try:
            # 번역된 텍스트에서 전문 용어 추출
            korean_texts = []
            for segment in segments:
                korean_text = segment.get('korean_text', '').strip()
                if korean_text and not korean_text.startswith('['):
                    korean_texts.append(korean_text)
            
            if not korean_texts:
                return {"terminology_score": 10.0, "issues": []}
            
            # 용어 검증 프롬프트
            terminology_prompt = ChatPromptTemplate.from_template("""
            다음 번역 텍스트들에서 전문 용어의 사용을 검증해주세요.

            검증 기준:
            1. 용어 번역의 정확성
            2. 용어 사용의 일관성
            3. 적절한 한국어 용어 선택
            4. 외래어 표기법 준수

            도메인 키워드 (참고용): {domain_keywords}
            
            번역 텍스트들:
            {korean_texts}

            JSON 형식으로 검증 결과를 제공해주세요:
            {{
                "terminology_score": 8.5,
                "terminology_issues": [
                    {{
                        "term": "문제가 있는 용어",
                        "issue": "문제점 설명",
                        "suggestion": "개선 제안"
                    }}
                ],
                "consistency_issues": ["일관성 문제들"],
                "recommendations": ["전반적인 권장사항"]
            }}
            """)
            
            terminology_chain = (
                terminology_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await terminology_chain.ainvoke({
                "domain_keywords": domain_keywords or ["일반"],
                "korean_texts": "\n".join(korean_texts)
            })
            
            logger.info(f"Terminology validation completed")
            return result
            
        except Exception as e:
            logger.error(f"Terminology validation error: {e}")
            return {"error": f"Terminology validation failed: {str(e)}"}
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return {
            "agent_type": "reviewer",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "quality_threshold": self.quality_threshold,
            "is_available": self.is_available(),
            "capabilities": ["quality_assessment", "consistency_review", "improvement_suggestions", "terminology_validation"]
        }