# stt-processor/src/redis_client.py

import os
import redis # redis 라이브러리 import
import logging

logger = logging.getLogger(__name__)

# 환경 변수 또는 기본값 사용
REDIS_HOST = os.getenv("REDIS_HOST", "redis") # docker-compose 서비스 이름
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# WebSocket 메시지 저장용 DB 번호 (Celery 결과 백엔드 DB와 다른 번호 사용 권장)
REDIS_DB_MESSAGES = int(os.getenv("REDIS_DB_WS_MESSAGES", "3"))
# 메시지 저장 기간 (초 단위, 기본값 1시간)
REDIS_MESSAGE_TTL = int(os.getenv("REDIS_MESSAGE_TTL_SECONDS", 3600))

redis_connection = None
try:
    # decode_responses=True: Redis에서 받은 데이터를 자동으로 UTF-8 문자열로 디코딩
    # 연결 및 응답 타임아웃 설정 추가
    redis_connection = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB_MESSAGES,
        decode_responses=True,
        socket_connect_timeout=5, # 연결 시도 시간 제한 (초)
        socket_timeout=5          # 명령 응답 대기 시간 제한 (초)
    )
    # 연결 테스트 (ping)
    redis_connection.ping()
    logger.info(f"Successfully connected to Redis for WS messages at {REDIS_HOST}:{REDIS_PORT} DB {REDIS_DB_MESSAGES}")

except redis.exceptions.ConnectionError as e:
    # 연결 관련 오류 발생 시
    logger.error(f"Failed to connect to Redis for WS messages ({REDIS_HOST}:{REDIS_PORT} DB {REDIS_DB_MESSAGES}): {e}", exc_info=True)
    redis_connection = None # 연결 실패 시 None으로 설정

except Exception as e:
    # 그 외 예상치 못한 오류 발생 시
    logger.error(f"An unexpected error occurred during Redis initialization: {e}", exc_info=True)
    redis_connection = None

def get_redis_client():
    """
    초기화된 Redis 클라이언트 인스턴스를 반환합니다.
    연결 실패 시 None을 반환할 수 있습니다.
    """
    if redis_connection is None:
        # 필요하다면 여기서 로그를 남기거나, 재연결 시도 로직 추가 가능
        logger.error("Redis client for WS messages is not initialized or connection failed!")
        # raise ConnectionError("Redis client is not available.") # 또는 예외 발생
    return redis_connection

def get_message_ttl():
    """설정된 메시지 저장 TTL 값을 초 단위로 반환합니다."""
    return REDIS_MESSAGE_TTL