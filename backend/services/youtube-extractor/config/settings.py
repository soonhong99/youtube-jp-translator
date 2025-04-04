import os
from pathlib import Path
from typing import Dict, Any, Optional

class Settings:
    """애플리케이션 설정을 관리하는 클래스"""
    
    def __init__(self):
        # 기본 디렉토리 설정
        self.BASE_DIR = Path(__file__).resolve().parent.parent
        
        # 오디오 출력 디렉토리
        self.OUTPUT_DIR = os.getenv("OUTPUT_DIR", str(self.BASE_DIR / "downloads"))
        
        # 오디오 설정
        self.DEFAULT_FORMAT = os.getenv("DEFAULT_FORMAT", "wav")
        self.DEFAULT_SAMPLE_RATE = int(os.getenv("DEFAULT_SAMPLE_RATE", "16000"))
        self.DEFAULT_CHANNELS = int(os.getenv("DEFAULT_CHANNELS", "1"))
        
        # API 설정
        self.API_HOST = os.getenv("API_HOST", "0.0.0.0")
        self.API_PORT = int(os.getenv("API_PORT", "8000"))
        
        # 로깅 설정
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    def get_audio_settings(self) -> Dict[str, Any]:
        """오디오 관련 설정 가져오기"""
        return {
            "preferred_format": self.DEFAULT_FORMAT,
            "sample_rate": self.DEFAULT_SAMPLE_RATE,
            "channels": self.DEFAULT_CHANNELS,
        }
    
    def get_api_settings(self) -> Dict[str, Any]:
        """API 관련 설정 가져오기"""
        return {
            "host": self.API_HOST,
            "port": self.API_PORT,
        }

# 설정 인스턴스 생성
settings = Settings()