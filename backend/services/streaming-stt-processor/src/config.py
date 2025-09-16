"""
Streaming STT Processor Configuration
"""

import os
from typing import List

class StreamingSTTConfig:
    """스트리밍 STT 처리기 설정"""

    # 서버 설정
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8007"))

    # Whisper 모델 설정
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    WHISPER_POOL_SIZE = int(os.getenv("WHISPER_POOL_SIZE", "3"))
    DEVICE = os.getenv("DEVICE", "auto")

    # 오디오 처리 설정
    AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
    DEFAULT_CHUNK_DURATION = float(os.getenv("DEFAULT_CHUNK_DURATION", "5.0"))
    DEFAULT_OVERLAP_DURATION = float(os.getenv("DEFAULT_OVERLAP_DURATION", "1.0"))

    # Kafka 설정
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_TOPIC_STT_CHUNKS = os.getenv("KAFKA_TOPIC_STT_CHUNKS", "stt_chunks")
    KAFKA_TOPIC_STT_RESULTS = os.getenv("KAFKA_TOPIC_STT_RESULTS", "stt_results")
    KAFKA_TOPIC_STREAMING_CONTROL = os.getenv("KAFKA_TOPIC_STREAMING_CONTROL", "streaming_control")
    KAFKA_TOPIC_STREAMING_REQUESTS = os.getenv("KAFKA_TOPIC_STREAMING_REQUESTS", "streaming_requests")

    # Redis 설정
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB_STT = int(os.getenv("REDIS_DB_STT", "8"))

    # Redis TTL 설정 (초)
    REDIS_TTL_STT_CHUNKS = int(os.getenv("REDIS_TTL_STT_CHUNKS", "3600"))  # 1시간
    REDIS_TTL_STT_RESULTS = int(os.getenv("REDIS_TTL_STT_RESULTS", "86400"))  # 24시간
    REDIS_TTL_PROGRESS = int(os.getenv("REDIS_TTL_PROGRESS", "7200"))  # 2시간

    # 처리 성능 설정
    MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "5"))
    CHUNK_PROCESSING_TIMEOUT = int(os.getenv("CHUNK_PROCESSING_TIMEOUT", "30"))
    MODEL_ALLOCATION_TIMEOUT = int(os.getenv("MODEL_ALLOCATION_TIMEOUT", "30"))

    # 로깅 설정
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 파일 시스템 설정
    TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/streaming_stt")
    MAX_CHUNK_FILE_SIZE = int(os.getenv("MAX_CHUNK_FILE_SIZE", "50")) * 1024 * 1024  # 50MB

    # 품질 설정
    MIN_CONFIDENCE_THRESHOLD = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.7"))
    MIN_AUDIO_DURATION = float(os.getenv("MIN_AUDIO_DURATION", "0.5"))  # 최소 0.5초
    MAX_AUDIO_DURATION = float(os.getenv("MAX_AUDIO_DURATION", "3600"))  # 최대 1시간

    # VAD (Voice Activity Detection) 설정
    VAD_ENERGY_THRESHOLD = float(os.getenv("VAD_ENERGY_THRESHOLD", "0.01"))
    VAD_ZCR_THRESHOLD = float(os.getenv("VAD_ZCR_THRESHOLD", "0.01"))

    # 문장 재구성 설정
    MAX_SENTENCE_LENGTH = int(os.getenv("MAX_SENTENCE_LENGTH", "500"))
    MAX_CHUNKS_PER_SENTENCE = int(os.getenv("MAX_CHUNKS_PER_SENTENCE", "8"))
    SENTENCE_CONFIDENCE_THRESHOLD = float(os.getenv("SENTENCE_CONFIDENCE_THRESHOLD", "0.7"))

    @classmethod
    def get_kafka_consumer_config(cls) -> dict:
        """Kafka Consumer 설정 반환"""
        return {
            'bootstrap_servers': cls.KAFKA_BOOTSTRAP_SERVERS.split(','),
            'group_id': 'streaming-stt-processor',
            'auto_offset_reset': 'latest',
            'enable_auto_commit': True,
            'key_deserializer': lambda x: x.decode('utf-8') if x else None,
            'value_deserializer': lambda x: x.decode('utf-8') if x else None
        }

    @classmethod
    def get_kafka_producer_config(cls) -> dict:
        """Kafka Producer 설정 반환"""
        return {
            'bootstrap_servers': cls.KAFKA_BOOTSTRAP_SERVERS.split(','),
            'acks': 'all',
            'retries': 3,
            'batch_size': 16384,
            'linger_ms': 10,
            'buffer_memory': 33554432
        }

    @classmethod
    def get_redis_config(cls) -> dict:
        """Redis 설정 반환"""
        return {
            'host': cls.REDIS_HOST,
            'port': cls.REDIS_PORT,
            'db': cls.REDIS_DB_STT,
            'decode_responses': True,
            'socket_connect_timeout': 5,
            'socket_timeout': 5,
            'retry_on_timeout': True
        }

    @classmethod
    def validate_config(cls) -> List[str]:
        """설정 검증"""
        errors = []

        # 필수 설정 검증
        if cls.WHISPER_POOL_SIZE < 1:
            errors.append("WHISPER_POOL_SIZE는 1 이상이어야 합니다")

        if cls.DEFAULT_CHUNK_DURATION <= 0:
            errors.append("DEFAULT_CHUNK_DURATION은 0보다 커야 합니다")

        if cls.DEFAULT_OVERLAP_DURATION < 0:
            errors.append("DEFAULT_OVERLAP_DURATION은 0 이상이어야 합니다")

        if cls.DEFAULT_OVERLAP_DURATION >= cls.DEFAULT_CHUNK_DURATION:
            errors.append("DEFAULT_OVERLAP_DURATION은 DEFAULT_CHUNK_DURATION보다 작아야 합니다")

        if cls.MAX_CONCURRENT_TASKS < 1:
            errors.append("MAX_CONCURRENT_TASKS는 1 이상이어야 합니다")

        # 신뢰도 임계값 검증
        if not 0 <= cls.MIN_CONFIDENCE_THRESHOLD <= 1:
            errors.append("MIN_CONFIDENCE_THRESHOLD는 0과 1 사이여야 합니다")

        if not 0 <= cls.SENTENCE_CONFIDENCE_THRESHOLD <= 1:
            errors.append("SENTENCE_CONFIDENCE_THRESHOLD는 0과 1 사이여야 합니다")

        # 오디오 길이 검증
        if cls.MIN_AUDIO_DURATION <= 0:
            errors.append("MIN_AUDIO_DURATION은 0보다 커야 합니다")

        if cls.MAX_AUDIO_DURATION <= cls.MIN_AUDIO_DURATION:
            errors.append("MAX_AUDIO_DURATION은 MIN_AUDIO_DURATION보다 커야 합니다")

        return errors

    @classmethod
    def print_config(cls):
        """현재 설정 출력"""
        print("=== Streaming STT Processor Configuration ===")
        print(f"서버: {cls.HOST}:{cls.PORT}")
        print(f"Whisper 모델: {cls.WHISPER_MODEL} x{cls.WHISPER_POOL_SIZE} on {cls.DEVICE}")
        print(f"청크 설정: {cls.DEFAULT_CHUNK_DURATION}s 청크, {cls.DEFAULT_OVERLAP_DURATION}s 오버랩")
        print(f"Kafka: {cls.KAFKA_BOOTSTRAP_SERVERS}")
        print(f"Redis: {cls.REDIS_HOST}:{cls.REDIS_PORT}/{cls.REDIS_DB_STT}")
        print(f"동시 처리: {cls.MAX_CONCURRENT_TASKS}개")
        print(f"로그 레벨: {cls.LOG_LEVEL}")
        print("=" * 47)
