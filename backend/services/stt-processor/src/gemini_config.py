"""
Gemini API 모델 설정 및 초기화 관리 모듈
"""
import os
import logging
from typing import Optional, List
import google.generativeai as genai

logger = logging.getLogger(__name__)

class GeminiModelConfig:
    """Gemini 모델 설정 및 관리 클래스"""
    
    # 사용 가능한 모델 우선순위 (최신 → 구형)
    AVAILABLE_MODELS = [
        "gemini-2.0-flash-exp",      # 최신 실험 모델
        "gemini-1.5-pro-latest",     # 고품질 프로덕션 모델
        "gemini-1.5-flash-latest",   # 빠른 응답 모델
        "gemini-pro"                 # 기본 모델 (fallback)
    ]
    
    # 기본 설정값
    DEFAULT_TEMPERATURE = 0.3  # 번역 일관성을 위해 낮춤
    DEFAULT_MODEL = "gemini-1.5-pro-latest"
    
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = self._get_model_name()
        self.temperature = self._get_temperature()
        self.model_instance = None
        
    def _get_model_name(self) -> str:
        """환경변수 또는 기본값에서 모델명 가져오기"""
        model_name = os.getenv("GEMINI_MODEL", self.DEFAULT_MODEL)
        
        # 환경변수에 지정된 모델이 사용 가능한 목록에 없으면 경고 후 기본값 사용
        if model_name not in self.AVAILABLE_MODELS:
            logger.warning(
                f"Specified model '{model_name}' not in available models. "
                f"Using default: {self.DEFAULT_MODEL}"
            )
            model_name = self.DEFAULT_MODEL
            
        return model_name
    
    def _get_temperature(self) -> float:
        """환경변수에서 temperature 값 가져오기"""
        try:
            temp = float(os.getenv("GEMINI_TEMPERATURE", self.DEFAULT_TEMPERATURE))
            # 유효 범위 체크
            if 0.0 <= temp <= 1.0:
                return temp
            else:
                logger.warning(f"Invalid temperature value: {temp}. Using default: {self.DEFAULT_TEMPERATURE}")
                return self.DEFAULT_TEMPERATURE
        except (ValueError, TypeError):
            logger.warning(f"Invalid temperature format. Using default: {self.DEFAULT_TEMPERATURE}")
            return self.DEFAULT_TEMPERATURE
    
    def initialize_model(self) -> bool:
        """Gemini 모델 초기화"""
        if not self.api_key:
            logger.warning("GEMINI_API_KEY environment variable not found. Translation will be disabled.")
            return False
        
        try:
            # API 키 설정
            genai.configure(api_key=self.api_key)
            logger.info("Gemini API Key configured successfully.")
            
            # 모델 초기화 시도 (fallback 체인)
            for model_name in self._get_model_fallback_chain():
                try:
                    self.model_instance = genai.GenerativeModel(model_name)
                    # 간단한 테스트 호출로 모델 유효성 검증
                    test_config = genai.types.GenerationConfig(
                        temperature=self.temperature,
                        max_output_tokens=10
                    )
                    # 동기 테스트 호출
                    test_response = self.model_instance.generate_content(
                        "Test", generation_config=test_config
                    )
                    if test_response:
                        self.model_name = model_name
                        logger.info(f"Gemini model '{model_name}' initialized successfully with temperature {self.temperature}")
                        return True
                except Exception as e:
                    logger.warning(f"Failed to initialize model '{model_name}': {e}")
                    continue
            
            # 모든 모델 초기화 실패
            logger.error("Failed to initialize any Gemini model from the fallback chain.")
            return False
            
        except Exception as e:
            logger.error(f"Failed to configure Gemini API: {e}", exc_info=True)
            return False
    
    def _get_model_fallback_chain(self) -> List[str]:
        """모델 fallback 체인 생성"""
        # 환경변수로 지정된 모델을 최우선으로, 나머지는 우선순위대로
        chain = [self.model_name]
        for model in self.AVAILABLE_MODELS:
            if model != self.model_name:
                chain.append(model)
        return chain
    
    def get_generation_config(self, **kwargs) -> genai.types.GenerationConfig:
        """생성 설정 반환"""
        config_kwargs = {
            "temperature": kwargs.get("temperature", self.temperature),
        }
        
        # 선택적 매개변수 추가
        if "max_output_tokens" in kwargs:
            config_kwargs["max_output_tokens"] = kwargs["max_output_tokens"]
        if "top_p" in kwargs:
            config_kwargs["top_p"] = kwargs["top_p"]
        if "top_k" in kwargs:
            config_kwargs["top_k"] = kwargs["top_k"]
            
        return genai.types.GenerationConfig(**config_kwargs)
    
    def is_available(self) -> bool:
        """모델 사용 가능 여부 확인"""
        return self.model_instance is not None
    
    def get_model_info(self) -> dict:
        """현재 모델 정보 반환"""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "api_key_configured": bool(self.api_key),
            "model_initialized": self.is_available()
        }

# 전역 인스턴스 (싱글톤 패턴)
_gemini_config = None

def get_gemini_config() -> GeminiModelConfig:
    """Gemini 설정 인스턴스 반환 (싱글톤)"""
    global _gemini_config
    if _gemini_config is None:
        _gemini_config = GeminiModelConfig()
        _gemini_config.initialize_model()
    return _gemini_config

def reinitialize_gemini_config() -> GeminiModelConfig:
    """Gemini 설정 재초기화 (환경변수 변경 시 사용)"""
    global _gemini_config
    _gemini_config = GeminiModelConfig()
    _gemini_config.initialize_model()
    return _gemini_config