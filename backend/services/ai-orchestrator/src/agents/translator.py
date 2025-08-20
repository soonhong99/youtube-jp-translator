"""
번역 에이전트 - LangChain 기반 일본어->한국어 번역
"""
import logging
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TEMPERATURE

logger = logging.getLogger(__name__)

class TranslatorAgent:
    """LangChain 기반 번역 에이전트"""
    
    def __init__(self, model_name: str = None, temperature: float = None):
        self.model_name = model_name or GEMINI_MODEL
        self.temperature = temperature or GEMINI_TEMPERATURE
        self.llm = None
        self.chain = None
        self._initialize_chain()
    
    def _initialize_chain(self) -> bool:
        """번역 체인 초기화"""
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not found. Translator agent will be disabled.")
            return False
        
        try:
            # LangChain Gemini 모델 초기화
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                google_api_key=GEMINI_API_KEY
            )
            
            # 번역 프롬프트 템플릿
            translation_prompt = ChatPromptTemplate.from_template("""
            당신은 전문 일본어-한국어 번역가입니다. 유튜브 동영상에서 추출한 일본어 음성을 자연스러운 한국어로 번역해주세요.

            번역 지침:
            1. 구어체와 감정을 그대로 살려서 번역하세요
            2. 원문의 뉘앙스와 톤을 유지하세요
            3. 한국어 어순에 맞게 자연스럽게 번역하세요
            4. 일본어 특유의 존댓말과 경어는 한국어 존댓말로 적절히 변환하세요
            5. 번역 결과만 출력하고 부가 설명은 하지 마세요

            일본어 원문:
            {japanese_text}

            한국어 번역:
            """)
            
            # 번역 체인 구성
            self.chain = (
                translation_prompt
                | self.llm
                | StrOutputParser()
            )
            
            logger.info(f"Translation agent initialized with model: {self.model_name}, temperature: {self.temperature}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize translation chain: {e}")
            return False
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부"""
        return self.chain is not None
    
    async def translate_single(self, japanese_text: str) -> str:
        """단일 텍스트 번역"""
        if not self.is_available():
            return "[번역 불가 - 에이전트 미초기화]"
        
        if not japanese_text.strip():
            return ""
        
        try:
            result = await self.chain.ainvoke({"japanese_text": japanese_text})
            logger.debug(f"Single translation: '{japanese_text}' -> '{result}'")
            return result.strip()
            
        except Exception as e:
            logger.error(f"Translation error for '{japanese_text}': {e}")
            return "[번역 오류]"
    
    async def translate_batch(self, japanese_texts: List[str]) -> List[str]:
        """배치 번역 (여러 텍스트를 하나의 요청으로)"""
        if not self.is_available():
            return ["[번역 불가 - 에이전트 미초기화]"] * len(japanese_texts)
        
        if not japanese_texts:
            return []
        
        # 빈 텍스트 필터링
        filtered_texts = [text.strip() for text in japanese_texts if text.strip()]
        if not filtered_texts:
            return [""] * len(japanese_texts)
        
        try:
            # 구분자를 사용한 배치 번역
            separator = "[TRANSLATION_SEGMENT_BREAK]"
            combined_text = f"\n{separator}\n".join(filtered_texts)
            
            # 배치 번역용 프롬프트 (기존 로직 유지하되 LangChain으로 실행)
            batch_prompt = ChatPromptTemplate.from_template("""
            다음은 유튜브에서 추출한 총 {segment_count}개의 독립적인 일본어 구어체 문장들입니다. 
            각 문장은 "{separator}"로 구분되어 있습니다.
            
            맥락에 맞게 매우 자연스러운 한국어 구어체로 번역하고, 각 번역된 문장 뒤에는 
            반드시 원래의 "{separator}" 구분자를 정확히 유지해주세요.
            최종적으로 번역된 한국어 문장도 정확히 {segment_count}개가 되어야 합니다.
            각 번역된 문장 외에는 어떠한 부연 설명, 인사말 등을 절대 포함하지 마세요.

            일본어 원문:
            {japanese_text}

            한국어 번역:
            """)
            
            batch_chain = (
                batch_prompt
                | self.llm
                | StrOutputParser()
            )
            
            result = await batch_chain.ainvoke({
                "japanese_text": combined_text,
                "separator": separator,
                "segment_count": len(filtered_texts)
            })
            
            # 결과 분할
            translated_segments = result.strip().split(f"{separator}\n")
            
            # 세그먼트 수 검증
            if len(translated_segments) == len(filtered_texts):
                logger.info(f"Batch translation successful: {len(filtered_texts)} segments using {self.model_name}")
                
                # 원본 배열과 매칭 (빈 텍스트 고려)
                result_list = []
                filtered_idx = 0
                for original_text in japanese_texts:
                    if original_text.strip():
                        result_list.append(translated_segments[filtered_idx].strip())
                        filtered_idx += 1
                    else:
                        result_list.append("")
                
                return result_list
            else:
                logger.warning(f"Batch translation segment mismatch: expected {len(filtered_texts)}, got {len(translated_segments)}")
                # Fallback: 개별 번역
                return await self._translate_individually(japanese_texts)
                
        except Exception as e:
            logger.error(f"Batch translation error: {e}")
            # Fallback: 개별 번역
            return await self._translate_individually(japanese_texts)
    
    async def _translate_individually(self, japanese_texts: List[str]) -> List[str]:
        """개별 번역 (배치 실패 시 fallback)"""
        logger.info(f"Falling back to individual translation for {len(japanese_texts)} segments")
        results = []
        
        for text in japanese_texts:
            if text.strip():
                translated = await self.translate_single(text)
                results.append(translated)
            else:
                results.append("")
        
        return results
    
    async def translate_segments(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """세그먼트 리스트 번역 (STT 결과 형식)"""
        if not segments:
            return []
        
        # 일본어 텍스트만 추출
        japanese_texts = [seg.get('text', '') for seg in segments]
        
        # 배치 번역 실행
        korean_translations = await self.translate_batch(japanese_texts)
        
        # 원본 세그먼트에 번역 결과 추가
        result_segments = []
        for i, segment in enumerate(segments):
            result_segment = segment.copy()
            if i < len(korean_translations):
                result_segment['korean_text'] = korean_translations[i]
            else:
                result_segment['korean_text'] = "[번역 누락]"
            result_segments.append(result_segment)
        
        return result_segments
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return {
            "agent_type": "translator",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "is_available": self.is_available(),
            "capabilities": ["single_translation", "batch_translation", "segment_translation"]
        }