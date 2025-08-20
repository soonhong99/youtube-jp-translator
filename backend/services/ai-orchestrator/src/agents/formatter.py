"""
포매터 에이전트 - 자막 분할, 화자 인식, 텍스트 정제
"""
import logging
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field

from ..config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TEMPERATURE

logger = logging.getLogger(__name__)

class FormattedSegment(BaseModel):
    """포맷팅된 세그먼트 모델"""
    start: float = Field(description="시작 시간 (초)")
    end: float = Field(description="종료 시간 (초)")
    japanese_text: str = Field(description="원본 일본어 텍스트")
    korean_text: str = Field(description="번역된 한국어 텍스트")
    formatted_korean: str = Field(description="포맷팅된 한국어 텍스트")
    speaker_id: Optional[str] = Field(description="화자 ID (Speaker_A, Speaker_B 등)")
    confidence: float = Field(description="화자 인식 신뢰도 (0.0-1.0)")
    subtitle_lines: List[str] = Field(description="자막용 줄바꿈된 텍스트")

class SpeakerAnalysis(BaseModel):
    """화자 분석 결과"""
    total_speakers: int = Field(description="감지된 총 화자 수")
    speaker_segments: List[Dict] = Field(description="화자별 세그먼트 정보")
    conversation_type: str = Field(description="대화 유형 (monologue, dialogue, multi-speaker)")

class FormatterAgent:
    """자막 포맷팅 및 화자 인식 에이전트"""
    
    def __init__(self, model_name: str = None, temperature: float = None):
        self.model_name = model_name or GEMINI_MODEL
        self.temperature = temperature or GEMINI_TEMPERATURE
        self.llm = None
        self._initialize_chains()
    
    def _initialize_chains(self) -> bool:
        """포맷팅 체인들 초기화"""
        if not GEMINI_API_KEY:
            logger.warning("Gemini API key not found. Formatter agent will be disabled.")
            return False
        
        try:
            # LangChain Gemini 모델 초기화
            self.llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                google_api_key=GEMINI_API_KEY
            )
            
            logger.info(f"Formatter agent initialized with model: {self.model_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize formatter chains: {e}")
            return False
    
    def is_available(self) -> bool:
        """에이전트 사용 가능 여부"""
        return self.llm is not None
    
    async def analyze_speakers(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """화자 분석 및 인식"""
        if not self.is_available():
            return {"error": "Formatter agent not available"}
        
        if not segments:
            return {
                "total_speakers": 0,
                "speaker_segments": [],
                "conversation_type": "empty"
            }
        
        try:
            # 화자 분석용 프롬프트
            speaker_prompt = ChatPromptTemplate.from_template("""
            다음은 유튜브 영상에서 추출한 음성 텍스트 세그먼트들입니다. 
            문맥과 어조, 말투의 변화를 분석하여 화자를 구분해주세요.

            분석 기준:
            1. 말투와 어조의 변화
            2. 대화의 흐름과 맥락
            3. 질문과 답변의 패턴
            4. 존댓말/반말의 사용 패턴

            세그먼트 목록:
            {segments_text}

            다음 JSON 형식으로 분석 결과를 제공해주세요:
            {{
                "total_speakers": 1,
                "conversation_type": "monologue|dialogue|multi-speaker",
                "speaker_segments": [
                    {{
                        "segment_index": 0,
                        "speaker_id": "Speaker_A",
                        "confidence": 0.95,
                        "reasoning": "단조로운 설명 톤"
                    }}
                ]
            }}
            """)
            
            # 세그먼트 텍스트 구성
            segments_text = []
            for i, seg in enumerate(segments):
                korean_text = seg.get('korean_text', '').strip()
                japanese_text = seg.get('text', '').strip()
                segments_text.append(f"[{i}] 일본어: {japanese_text}")
                segments_text.append(f"    한국어: {korean_text}")
            
            speaker_chain = (
                speaker_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await speaker_chain.ainvoke({
                "segments_text": "\n".join(segments_text)
            })
            
            logger.info(f"Speaker analysis completed: {result.get('total_speakers', 0)} speakers detected")
            return result
            
        except Exception as e:
            logger.error(f"Speaker analysis error: {e}")
            return {
                "error": f"Speaker analysis failed: {str(e)}",
                "total_speakers": 1,
                "speaker_segments": [],
                "conversation_type": "unknown"
            }
    
    async def format_subtitles(self, segments: List[Dict[str, Any]], max_chars_per_line: int = 40) -> List[Dict[str, Any]]:
        """자막 포맷팅 (줄바꿈, 길이 조절)"""
        if not self.is_available():
            return segments
        
        try:
            formatted_segments = []
            
            for segment in segments:
                korean_text = segment.get('korean_text', '').strip()
                
                if not korean_text or korean_text.startswith('['):
                    # 번역 실패한 세그먼트는 그대로 유지
                    formatted_segments.append(segment)
                    continue
                
                # 자막 줄바꿈 최적화
                subtitle_lines = await self._optimize_subtitle_lines(korean_text, max_chars_per_line)
                
                # 포맷팅된 세그먼트 생성
                formatted_segment = segment.copy()
                formatted_segment['formatted_korean'] = '\n'.join(subtitle_lines)
                formatted_segment['subtitle_lines'] = subtitle_lines
                formatted_segment['char_count'] = len(korean_text)
                formatted_segment['line_count'] = len(subtitle_lines)
                
                formatted_segments.append(formatted_segment)
            
            logger.info(f"Subtitle formatting completed for {len(formatted_segments)} segments")
            return formatted_segments
            
        except Exception as e:
            logger.error(f"Subtitle formatting error: {e}")
            return segments
    
    async def _optimize_subtitle_lines(self, text: str, max_chars_per_line: int) -> List[str]:
        """자막 줄바꿈 최적화"""
        if len(text) <= max_chars_per_line:
            return [text]
        
        try:
            # 줄바꿈 최적화 프롬프트
            line_break_prompt = ChatPromptTemplate.from_template("""
            다음 한국어 텍스트를 자막용으로 최적화해주세요.
            한 줄당 최대 {max_chars}자까지, 의미 단위로 자연스럽게 줄바꿈해주세요.

            규칙:
            1. 한 줄당 최대 {max_chars}자
            2. 의미가 끊어지지 않도록 단어 단위로 분할
            3. 조사나 어미가 혼자 다음 줄로 가지 않도록 주의
            4. 최대 3줄까지만 사용

            원본 텍스트: {text}

            JSON 형식으로 줄바꿈된 결과를 반환해주세요:
            {{"lines": ["첫 번째 줄", "두 번째 줄"]}}
            """)
            
            line_break_chain = (
                line_break_prompt
                | self.llm
                | JsonOutputParser()
            )
            
            result = await line_break_chain.ainvoke({
                "text": text,
                "max_chars": max_chars_per_line
            })
            
            lines = result.get("lines", [text])
            
            # 안전장치: 각 줄이 여전히 너무 길면 강제 분할
            final_lines = []
            for line in lines:
                if len(line) <= max_chars_per_line:
                    final_lines.append(line)
                else:
                    # 강제 분할
                    words = line.split()
                    current_line = ""
                    
                    for word in words:
                        if len(current_line + " " + word) <= max_chars_per_line:
                            current_line = current_line + " " + word if current_line else word
                        else:
                            if current_line:
                                final_lines.append(current_line)
                            current_line = word
                    
                    if current_line:
                        final_lines.append(current_line)
            
            return final_lines[:3]  # 최대 3줄
            
        except Exception as e:
            logger.error(f"Line break optimization error: {e}")
            # Fallback: 단순 분할
            return self._simple_line_break(text, max_chars_per_line)
    
    def _simple_line_break(self, text: str, max_chars_per_line: int) -> List[str]:
        """단순 줄바꿈 (Fallback)"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if len(current_line + " " + word) <= max_chars_per_line:
                current_line = current_line + " " + word if current_line else word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines[:3]  # 최대 3줄
    
    async def apply_speaker_formatting(self, segments: List[Dict[str, Any]], speaker_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """화자 정보를 적용한 포맷팅"""
        if not speaker_analysis.get("speaker_segments"):
            return segments
        
        try:
            # 화자 정보 매핑
            speaker_map = {}
            for speaker_info in speaker_analysis["speaker_segments"]:
                segment_idx = speaker_info.get("segment_index")
                speaker_id = speaker_info.get("speaker_id", "Speaker_A")
                confidence = speaker_info.get("confidence", 0.5)
                
                if segment_idx is not None and 0 <= segment_idx < len(segments):
                    speaker_map[segment_idx] = {
                        "speaker_id": speaker_id,
                        "confidence": confidence
                    }
            
            # 세그먼트에 화자 정보 적용
            formatted_segments = []
            for i, segment in enumerate(segments):
                formatted_segment = segment.copy()
                
                if i in speaker_map:
                    speaker_info = speaker_map[i]
                    formatted_segment["speaker_id"] = speaker_info["speaker_id"]
                    formatted_segment["speaker_confidence"] = speaker_info["confidence"]
                    
                    # 화자 표시가 포함된 포맷팅
                    korean_text = formatted_segment.get("formatted_korean") or formatted_segment.get("korean_text", "")
                    if korean_text and not korean_text.startswith('['):
                        speaker_id = speaker_info["speaker_id"]
                        formatted_segment["formatted_korean_with_speaker"] = f"[{speaker_id}] {korean_text}"
                else:
                    formatted_segment["speaker_id"] = "Speaker_A"  # 기본값
                    formatted_segment["speaker_confidence"] = 0.5
                
                formatted_segments.append(formatted_segment)
            
            logger.info(f"Applied speaker formatting to {len(formatted_segments)} segments")
            return formatted_segments
            
        except Exception as e:
            logger.error(f"Speaker formatting error: {e}")
            return segments
    
    async def enhance_readability(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """가독성 향상 (문장 정제, 띄어쓰기 교정 등)"""
        if not self.is_available():
            return segments
        
        try:
            enhanced_segments = []
            
            for segment in segments:
                korean_text = segment.get('korean_text', '').strip()
                
                if not korean_text or korean_text.startswith('['):
                    enhanced_segments.append(segment)
                    continue
                
                # 가독성 향상 프롬프트
                readability_prompt = ChatPromptTemplate.from_template("""
                다음 한국어 번역 텍스트의 가독성을 향상시켜주세요.

                개선 사항:
                1. 띄어쓰기 교정
                2. 문장 부호 정리
                3. 어색한 표현 자연스럽게 수정
                4. 구어체를 살리되 읽기 편하게 정리

                원본: {text}

                개선된 텍스트만 반환해주세요 (부연 설명 없이):
                """)
                
                readability_chain = (
                    readability_prompt
                    | self.llm
                )
                
                enhanced_text = await readability_chain.ainvoke({"text": korean_text})
                
                # 향상된 세그먼트 생성
                enhanced_segment = segment.copy()
                enhanced_segment['enhanced_korean'] = enhanced_text.content.strip()
                enhanced_segment['original_korean'] = korean_text
                
                enhanced_segments.append(enhanced_segment)
            
            logger.info(f"Enhanced readability for {len(enhanced_segments)} segments")
            return enhanced_segments
            
        except Exception as e:
            logger.error(f"Readability enhancement error: {e}")
            return segments
    
    def get_agent_info(self) -> Dict[str, Any]:
        """에이전트 정보 반환"""
        return {
            "agent_type": "formatter",
            "model_name": self.model_name,
            "temperature": self.temperature,
            "is_available": self.is_available(),
            "capabilities": ["speaker_detection", "subtitle_formatting", "line_breaking", "readability_enhancement"]
        }