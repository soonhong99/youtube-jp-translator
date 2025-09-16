"""
Translation Worker Pool Configuration
"""

import os
from typing import List

class TranslationWorkerPoolConfig:
    """번역 워커 풀 설정"""

    # 서버 설정
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8005"))

    # Redis 설정
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB_WORKERS = int(os.getenv("REDIS_DB_WORKERS", "6"))

    # Kafka 설정
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_TOPIC_TRANSLATION_QUEUE = os.getenv("KAFKA_TOPIC_TRANSLATION_QUEUE", "translation_queue")
    KAFKA_TOPIC_TRANSLATION_RESULTS = os.getenv("KAFKA_TOPIC_TRANSLATION_RESULTS", "translation_results")
    KAFKA_TOPIC_REALTIME_RESULTS = os.getenv("KAFKA_TOPIC_REALTIME_RESULTS", "realtime_results")

    # API 키 설정
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # 워커 풀 설정
    WORKER_POOL_SIZE = int(os.getenv("WORKER_POOL_SIZE", "5"))
    MIN_WORKERS = int(os.getenv("MIN_WORKERS", "2"))
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))

    # 성능 설정
    MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "10"))
    DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "30"))
    PRIORITY_TIMEOUT = int(os.getenv("PRIORITY_TIMEOUT", "8"))

    # Circuit Breaker 설정
    CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "3"))
    CIRCUIT_BREAKER_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60"))

    # 스케일링 설정
    SCALE_UP_THRESHOLD = float(os.getenv("SCALE_UP_THRESHOLD", "0.7"))
    SCALE_DOWN_THRESHOLD = float(os.getenv("SCALE_DOWN_THRESHOLD", "0.3"))
    SCALE_UP_COOLDOWN = int(os.getenv("SCALE_UP_COOLDOWN", "60"))
    SCALE_DOWN_COOLDOWN = int(os.getenv("SCALE_DOWN_COOLDOWN", "300"))

    # Redis TTL 설정 (초)
    REDIS_TTL_TRANSLATION_RESULTS = int(os.getenv("REDIS_TTL_TRANSLATION_RESULTS", "3600"))
    REDIS_TTL_WORKER_METRICS = int(os.getenv("REDIS_TTL_WORKER_METRICS", "300"))
    REDIS_TTL_TASK_CACHE = int(os.getenv("REDIS_TTL_TASK_CACHE", "1800"))

    # 로깅 설정
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def validate_config(cls) -> List[str]:
        """설정 검증"""
        errors = []

        # API 키 검증
        if not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY가 설정되지 않았습니다")

        # 워커 풀 크기 검증
        if cls.MIN_WORKERS < 1:
            errors.append("MIN_WORKERS는 1 이상이어야 합니다")

        if cls.MAX_WORKERS < cls.MIN_WORKERS:
            errors.append("MAX_WORKERS는 MIN_WORKERS보다 커야 합니다")

        if cls.WORKER_POOL_SIZE < cls.MIN_WORKERS or cls.WORKER_POOL_SIZE > cls.MAX_WORKERS:
            errors.append("WORKER_POOL_SIZE는 MIN_WORKERS와 MAX_WORKERS 사이여야 합니다")

        # 타임아웃 검증
        if cls.PRIORITY_TIMEOUT <= 0:
            errors.append("PRIORITY_TIMEOUT은 0보다 커야 합니다")

        if cls.DEFAULT_TIMEOUT < cls.PRIORITY_TIMEOUT:
            errors.append("DEFAULT_TIMEOUT은 PRIORITY_TIMEOUT보다 커야 합니다")

        # 스케일링 임계값 검증
        if not 0 <= cls.SCALE_UP_THRESHOLD <= 1:
            errors.append("SCALE_UP_THRESHOLD는 0과 1 사이여야 합니다")

        if not 0 <= cls.SCALE_DOWN_THRESHOLD <= 1:
            errors.append("SCALE_DOWN_THRESHOLD는 0과 1 사이여야 합니다")

        if cls.SCALE_DOWN_THRESHOLD >= cls.SCALE_UP_THRESHOLD:
            errors.append("SCALE_DOWN_THRESHOLD는 SCALE_UP_THRESHOLD보다 작아야 합니다")

        return errors

    @classmethod
    def print_config(cls):
        """현재 설정 출력"""
        print("=== Translation Worker Pool Configuration ===")
        print(f"서버: {cls.HOST}:{cls.PORT}")
        print(f"워커 풀: {cls.MIN_WORKERS}-{cls.MAX_WORKERS}개 (기본: {cls.WORKER_POOL_SIZE})")
        print(f"타임아웃: 우선순위 {cls.PRIORITY_TIMEOUT}s, 일반 {cls.DEFAULT_TIMEOUT}s")
        print(f"Redis: {cls.REDIS_HOST}:{cls.REDIS_PORT}/{cls.REDIS_DB_WORKERS}")
        print(f"Kafka: {cls.KAFKA_BOOTSTRAP_SERVERS}")
        print(f"API 키: Gemini {'✓' if cls.GEMINI_API_KEY else '✗'}, Claude {'✓' if cls.CLAUDE_API_KEY else '✗'}")
        print("=" * 48)