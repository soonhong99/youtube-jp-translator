"""
AI Orchestrator 서비스 설정
"""
import os
from typing import List

# Kafka 설정
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
AI_PROCESSING_REQUEST_TOPIC = "ai_processing_requests"
AI_PROCESSING_RESULT_TOPIC = "ai_processing_results"

# Redis 설정
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB_AI_CACHE = int(os.getenv("REDIS_DB_AI_CACHE", 4))

# Gemini 설정 (최적화된 기본값)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")  # Flash 모델 기본값으로 변경
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", 0.3))

# AI Orchestrator 설정 (할당량 최적화)
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 3))  # 동시 작업 수 제한
TRANSLATION_CACHE_TTL = int(os.getenv("TRANSLATION_CACHE_TTL", 3600))  # 1시간
QUOTA_MANAGEMENT_ENABLED = os.getenv("QUOTA_MANAGEMENT_ENABLED", "true").lower() == "true"
AI_SEGMENTATION_ENABLED = os.getenv("AI_SEGMENTATION_ENABLED", "false").lower() == "true"  # 기본 비활성화
CIRCUIT_BREAKER_ENABLED = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"

# 번역 강제 옵션
# true일 때, 번역은 1:1 경로만 사용하며 지능형 그룹핑과 배치 Fallback을 비활성화합니다.
TRANSLATION_FORCE_ONE_TO_ONE = os.getenv("TRANSLATION_FORCE_ONE_TO_ONE", "true").lower() == "true"

# 로깅 설정
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 사용 가능한 AI 에이전트 목록
AVAILABLE_AGENTS = [
    "translator",
    "summarizer", 
    "formatter",
    "reviewer"
]

# LangChain 설정
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY")  # 선택적

# Gemini 설정 함수 import
from .gemini_config import get_gemini_config
