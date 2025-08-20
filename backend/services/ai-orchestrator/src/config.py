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

# Gemini 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro-latest")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", 0.3))

# AI Orchestrator 설정
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", 5))
TRANSLATION_CACHE_TTL = int(os.getenv("TRANSLATION_CACHE_TTL", 3600))  # 1시간

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