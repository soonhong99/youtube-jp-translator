"""
요약 에이전트 - 영상 내용 요약 및 키워드 추출
"""
import logging
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field

from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TEMPERATURE

logger = logging.getLogger(__name__)

class SummaryOutput(BaseModel):
    """요약 결과 모델"""
    summary: str = Field(description="영상의 핵심 내용 요약 (2-3문장)")
    detailed_summary: str = Field(description="상세 요약 (5-7문장)")
    keywords: List[str] = Field(description="주요 키워드 리스트 (5-10개)")
    topics: List[str] = Field(description="주요 주제/카테고리 (3-5개)")
    sentiment: str = Field(description="전반적인 감정/톤 (positive, negative, neutral)")
    video_type: str = Field(description="영상 유형 (educational, entertainment, news, tutorial, etc.)")

class SummarizerAgent:
    """영상 내용 요약 및 메타데이터 추출 에이전트"""
    
    def __init__(self, model_name: str = None, temperature: float = None):
        self.model_name = model_name or GEMINI_MODEL
        self.temperature = temperature or GEMINI_TEMPERATURE
        self.llm = None
        self.chain = None
        self._initialize_chain()
    
    def _initialize_chain(self) -> bool:
        """요약 체인 초기화"""
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not found. Summarizer agent will be disabled.")
            return False
        
        try:
            # LangChain Gemini 모델 초기화
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                google_api_key=GEMINI_API_KEY
            )
            
            # JSON 출력 파서
            parser = JsonOutputParser(pydantic_object=SummaryOutput)
            
            # 요약 프롬프트 템플릿
            summary_prompt = ChatPromptTemplate.from_template("""
            당신은 전문 콘텐츠 분석가입니다. 유튜브 영상의 한국어 번역 스크립트를 분석하여 종합적인 요약과 메타데이터를 생성해주세요.

            분석 지침:
            1. 영상의 핵심 메시지와 주요 내용을 파악하세요
            2. 시청자에게 유용한 키워드를 추출하세요
            3. 영상의 톤과 감정을 분석하세요
            4. 영상 유형을 분류하세요

            스크립트 (한국어 번역):
            {transcript}

            다음 JSON 형식으로 분석 결과를 제공해주세요:
            {format_instructions}
            """)
            
            # 체인 구성
            self.chain = (
                summary_prompt
                | self.llm
                | parser
            )
            
            logger.info(f"Summarizer agent initialized with model: {self.model_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize summarizer chain: {e}")
            return False
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부"""
        return self.chain is not None
    
    def _extract_transcript_text(self, segments: List[Dict[str, Any]]) -> str:
        """세그먼트에서 텍스트 추출"""
        transcript_parts = []
        
        for segment in segments:
            korean_text = segment.get('korean_text', '').strip()
            if korean_text and korean_text not in ['[번역 불가]', '[번역 오류]', '[번역 누락]']:
                transcript_parts.append(korean_text)
        
        return ' '.join(transcript_parts)
    
    async def summarize_content(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """콘텐츠 요약 및 메타데이터 추출"""
        if not self.is_available():
            return {
                "error": "Summarizer agent not available",
                "summary": "",
                "keywords": [],
                "topics": [],
                "sentiment": "unknown",
                "video_type": "unknown"
            }
        
        if not segments:
            return {
                "summary": "내용이 없는 영상입니다.",
                "detailed_summary": "분석할 스크립트가 없습니다.",
                "keywords": [],
                "topics": [],
                "sentiment": "neutral",
                "video_type": "unknown"
            }
        
        try:
            # 번역된 텍스트 추출
            transcript = self._extract_transcript_text(segments)
            
            if not transcript.strip():
                return {
                    "summary": "번역된 내용이 없습니다.",
                    "detailed_summary": "유효한 번역 결과가 없어 분석할 수 없습니다.",
                    "keywords": [],
                    "topics": [],
                    "sentiment": "neutral",
                    "video_type": "unknown"
                }
            
            # 너무 긴 텍스트는 truncate (Gemini 토큰 한계 고려)
            if len(transcript) > 10000:
                transcript = transcript[:10000] + "..."
                logger.warning("Transcript truncated due to length")
            
            # 요약 실행
            parser = JsonOutputParser(pydantic_object=SummaryOutput)
            result = await self.chain.ainvoke({
                "transcript": transcript,
                "format_instructions": parser.get_format_instructions()
            })
            
            logger.info(f"Content summarization completed: {len(result.get('keywords', []))} keywords, {len(result.get('topics', []))} topics")
            return result
            
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return {
                "error": f"Summarization failed: {str(e)}",
                "summary": "요약 생성 중 오류가 발생했습니다.",
                "detailed_summary": "시스템 오류로 인해 상세 요약을 생성할 수 없습니다.",
                "keywords": [],
                "topics": [],
                "sentiment": "unknown",
                "video_type": "unknown"
            }
    
    async def extract_highlights(self, segments: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
        """핵심 구간 추출"""
        if not self.is_available() or not segments:
            return []
        
        try:
            # 타임스탬프가 있는 세그먼트만 필터링
            timestamped_segments = [
                seg for seg in segments 
                if seg.get('start') is not None and seg.get('korean_text', '').strip()
            ]
            
            if len(timestamped_segments) < top_n:
                return timestamped_segments
            
            # 하이라이트 추출용 프롬프트
            highlight_prompt = ChatPromptTemplate.from_template("""
            다음은 유튜브 영상의 번역된 세그먼트들입니다. 이 중에서 가장 중요하고 흥미로운 {top_n}개의 핵심 구간을 선택해주세요.

            선택 기준:
            1. 정보의 중요도와 가치
            2. 시청자의 관심을 끌 수 있는 내용
            3. 영상의 핵심 메시지를 담고 있는 부분

            세그먼트들:
            {segments_text}

            선택된 세그먼트의 인덱스를 JSON 배열로 반환해주세요 (0부터 시작):
            {{"selected_indices": [0, 5, 12]}}
            """)
            
            # 세그먼트 텍스트 구성
            segments_text = []
            for i, seg in enumerate(timestamped_segments):
                korean_text = seg.get('korean_text', '').strip()
                start_time = seg.get('start', 0)
                segments_text.append(f"[{i}] {start_time:.1f}초: {korean_text}")
            
            highlight_chain = (
                highlight_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await highlight_chain.ainvoke({
                "segments_text": "\n".join(segments_text),
                "top_n": top_n
            })
            
            # 선택된 인덱스에 해당하는 세그먼트 반환
            selected_indices = result.get("selected_indices", [])
            highlights = []
            
            for idx in selected_indices:
                if 0 <= idx < len(timestamped_segments):
                    highlight = timestamped_segments[idx].copy()
                    highlight["highlight_reason"] = f"핵심 구간 {len(highlights) + 1}"
                    highlights.append(highlight)
            
            logger.info(f"Extracted {len(highlights)} highlights from {len(timestamped_segments)} segments")
            return highlights
            
        except Exception as e:
            logger.error(f"Highlight extraction error: {e}")
            return []
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return {
            "agent_type": "summarizer",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "is_available": self.is_available(),
            "capabilities": ["content_summary", "keyword_extraction", "topic_classification", "sentiment_analysis", "highlight_extraction"]
        }