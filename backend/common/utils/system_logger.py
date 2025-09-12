import os
import json
import logging
from typing import Any, Dict, Optional
from datetime import datetime

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None  # lazy error handling

logger = logging.getLogger(__name__)

# Environment configuration
REDIS_HOST = os.getenv("SYSTEM_METRICS_REDIS_HOST", os.getenv("REDIS_HOST", "redis"))
REDIS_PORT = int(os.getenv("SYSTEM_METRICS_REDIS_PORT", os.getenv("REDIS_PORT", 6379)))
REDIS_DB = int(os.getenv("SYSTEM_METRICS_REDIS_DB", 5))  # api-gateway uses DB 5 for system metrics
KEY_TTL_SECONDS = int(os.getenv("SYSTEM_METRICS_TTL_SECONDS", 86400))  # default 24h

_redis_client: Optional["redis.Redis"] = None


def _get_client() -> Optional["redis.Redis"]:
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    if redis is None:
        logger.warning("system_logger: redis package not available; logging disabled")
        return None

    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        # test connection
        client.ping()
        _redis_client = client
        logger.info(
            f"system_logger connected to Redis at {REDIS_HOST}:{REDIS_PORT} db={REDIS_DB}"
        )
        return _redis_client
    except Exception as e:  # pragma: no cover
        logger.warning(f"system_logger: failed to connect Redis: {e}")
        return None


def log_event(event_type: str, task_id: str, data: Dict[str, Any]) -> bool:
    """
    Log a system monitoring event to Redis for thesis dashboard consumption.

    event_type: one of {data_flow, kafka_message, performance, timeline}
    task_id: pipeline task identifier
    data: event payload; for non-performance events timestamp is injected
    """
    client = _get_client()
    if client is None:
        return False

    if not event_type or not task_id or not isinstance(data, dict):
        logger.debug("system_logger: invalid parameters; skip")
        return False

    key = f"{event_type}:{task_id}"

    try:
        if event_type == "performance":
            # store as hash; update/merge
            client.hset(key, mapping={k: str(v) for k, v in data.items()})
            client.expire(key, KEY_TTL_SECONDS)
        else:
            # list append with timestamp and trim to 50
            entry = dict(data)
            if "timestamp" not in entry:
                entry["timestamp"] = datetime.now().strftime("%H:%M:%S")
            client.lpush(key, json.dumps(entry))
            client.ltrim(key, 0, 49)
            client.expire(key, KEY_TTL_SECONDS)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"system_logger: failed to write event {event_type} for {task_id}: {e}")
        return False


def log_data_flow(task_id: str, source: str, target: str, message: str, extra: Optional[Dict[str, Any]] = None) -> bool:
    payload: Dict[str, Any] = {"from": source, "to": target, "message": message}
    if extra:
        payload.update(extra)
    return log_event("data_flow", task_id, payload)


def log_kafka_message(task_id: str, topic: str, message: str, extra: Optional[Dict[str, Any]] = None) -> bool:
    payload: Dict[str, Any] = {"topic": topic, "message": message}
    if extra:
        payload.update(extra)
    return log_event("kafka_message", task_id, payload)


def log_timeline(task_id: str, agent: str, task: str, progress: int = 0, duration: Optional[float] = None, extra: Optional[Dict[str, Any]] = None) -> bool:
    payload: Dict[str, Any] = {"agent": agent, "task": task, "progress": progress}
    if duration is not None:
        payload["duration"] = str(duration)
    if extra:
        payload.update(extra)
    return log_event("timeline", task_id, payload)


def log_performance(task_id: str, metrics: Dict[str, Any]) -> bool:
    """
    Upsert performance metrics hash. Expected keys include:
    - audio_extraction_time, stt_processing_time, ai_processing_time, total_processing_time
    Values are stored as strings for compatibility.
    """
    return log_event("performance", task_id, metrics)

